from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .hashing import sha256_file


class CheckpointError(RuntimeError):
    pass


class CompletedRunError(CheckpointError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _validate_blind_run_id(blind_run_id: str) -> None:
    if not blind_run_id or any(not (character.isalnum() or character in "_-") for character in blind_run_id):
        raise CheckpointError("Unsafe blind_run_id for checkpoint path")


@dataclass(frozen=True)
class RunAttempt:
    blind_run_id: str
    number: int
    directory: Path
    started_at: str
    operational_provenance: dict[str, Any] | None = None

    def artifact(self, name: str) -> Path:
        if Path(name).name != name:
            raise CheckpointError("Artifact name must not contain a path")
        return self.directory / name


class CheckpointStore:
    REQUIRED_HASHES = {
        "configuration_sha256",
        "prompt_sha256",
        "model_sha256",
        "image_digest",
        "output_schema_sha256",
        "representation_contract_sha256",
        "evaluation_contract_sha256",
        "run_selection_sha256",
        "dpca_reference_sha256",
        "dpca_artifact_sha256",
        "h3_reference_sha256",
        "methodological_amendment_sha256",
    }

    def __init__(
        self,
        root: str | Path,
        frozen_hashes: dict[str, str],
        operational_provenance: dict[str, Any] | None = None,
        now: Callable[[], str] = _utc_now,
    ) -> None:
        self.root = Path(root)
        self.runs_root = self.root / "runs"
        self.frozen_hashes = dict(frozen_hashes)
        self.operational_provenance = (
            dict(operational_provenance) if operational_provenance else None
        )
        self.now = now
        missing = self.REQUIRED_HASHES - set(self.frozen_hashes)
        empty = sorted(key for key, value in self.frozen_hashes.items() if not isinstance(value, str) or not value)
        if missing or empty:
            raise CheckpointError(f"Incomplete frozen hash set; missing={sorted(missing)}, empty={empty}")
        self.runs_root.mkdir(parents=True, exist_ok=True)
        contract_path = self.root / "checkpoint_contract.json"
        if contract_path.exists():
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            if contract.get("frozen_hashes") != self.frozen_hashes:
                raise CheckpointError("Resume blocked: frozen hashes differ from checkpoint contract")
        else:
            _atomic_json(contract_path, {
                "status": "ACTIVE",
                "created_at": self.now(),
                "frozen_hashes": self.frozen_hashes,
            })

    def _run_root(self, blind_run_id: str) -> Path:
        _validate_blind_run_id(blind_run_id)
        return self.runs_root / blind_run_id

    def _attempt_directories(self, blind_run_id: str) -> list[Path]:
        attempts = self._run_root(blind_run_id) / "attempts"
        return sorted(path for path in attempts.glob("[0-9][0-9][0-9][0-9]") if path.is_dir()) if attempts.exists() else []

    def _validate_status_hashes(self, value: dict[str, Any]) -> None:
        if value.get("frozen_hashes") != self.frozen_hashes:
            raise CheckpointError("Resume blocked: run-attempt hashes differ")

    def inspect(self, blind_run_id: str) -> str:
        run_root = self._run_root(blind_run_id)
        complete_path = run_root / "COMPLETE.json"
        if complete_path.exists():
            self.validate_complete(blind_run_id)
            return "COMPLETE"
        attempts = self._attempt_directories(blind_run_id)
        if not attempts:
            return "NEW"
        status_path = attempts[-1] / "status.json"
        if not status_path.exists():
            raise CheckpointError("Run attempt has no status.json")
        status = json.loads(status_path.read_text(encoding="utf-8"))
        self._validate_status_hashes(status)
        if status.get("status") not in {"PARTIAL", "FAILED"}:
            raise CheckpointError("Run without COMPLETE marker has invalid status")
        return str(status["status"])

    def begin_run(self, blind_run_id: str) -> RunAttempt:
        state = self.inspect(blind_run_id)
        if state == "COMPLETE":
            raise CompletedRunError(f"Completed run is immutable: {blind_run_id}")
        attempts = self._attempt_directories(blind_run_id)
        number = len(attempts) + 1
        directory = self._run_root(blind_run_id) / "attempts" / f"{number:04d}"
        directory.mkdir(parents=True, exist_ok=False)
        started_at = self.now()
        status = {
            "status": "PARTIAL",
            "blind_run_id": blind_run_id,
            "attempt": number,
            "started_at": started_at,
            "ended_at": None,
            "frozen_hashes": self.frozen_hashes,
        }
        if self.operational_provenance is not None:
            status["operational_provenance"] = self.operational_provenance
        _atomic_json(directory / "status.json", status)
        return RunAttempt(
            blind_run_id,
            number,
            directory,
            started_at,
            self.operational_provenance,
        )

    def mark_failed(self, attempt: RunAttempt, error: str) -> None:
        status = {
            "status": "FAILED",
            "blind_run_id": attempt.blind_run_id,
            "attempt": attempt.number,
            "started_at": attempt.started_at,
            "ended_at": self.now(),
            "error": str(error),
            "frozen_hashes": self.frozen_hashes,
        }
        if attempt.operational_provenance is not None:
            status["operational_provenance"] = attempt.operational_provenance
        _atomic_json(attempt.directory / "status.json", status)

    def complete_run(self, attempt: RunAttempt, artifact_names: list[str], counts: dict[str, int]) -> dict[str, Any]:
        complete_path = self._run_root(attempt.blind_run_id) / "COMPLETE.json"
        if complete_path.exists():
            raise CompletedRunError(f"Completed run is immutable: {attempt.blind_run_id}")
        artifacts = []
        for name in artifact_names:
            path = attempt.artifact(name)
            if not path.is_file():
                raise CheckpointError(f"Cannot complete run; missing artifact {name}")
            artifacts.append({"name": name, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
        ended_at = self.now()
        manifest = {
            "status": "COMPLETE",
            "blind_run_id": attempt.blind_run_id,
            "attempt": attempt.number,
            "started_at": attempt.started_at,
            "ended_at": ended_at,
            "frozen_hashes": self.frozen_hashes,
            "counts": {key: int(value) for key, value in counts.items()},
            "artifacts": artifacts,
        }
        if attempt.operational_provenance is not None:
            manifest["operational_provenance"] = attempt.operational_provenance
        manifest_path = attempt.directory / "run_manifest.json"
        _atomic_json(manifest_path, manifest)
        _atomic_json(attempt.directory / "status.json", manifest)
        marker = {
            "status": "COMPLETE",
            "blind_run_id": attempt.blind_run_id,
            "attempt": attempt.number,
            "completed_at": ended_at,
            "run_manifest_relative_path": str(manifest_path.relative_to(self.root)).replace(os.sep, "/"),
            "run_manifest_sha256": sha256_file(manifest_path),
            "frozen_hashes": self.frozen_hashes,
        }
        if attempt.operational_provenance is not None:
            marker["operational_provenance"] = attempt.operational_provenance
        _atomic_json(complete_path, marker)
        self.validate_complete(attempt.blind_run_id)
        return marker

    def validate_complete(self, blind_run_id: str) -> dict[str, Any]:
        run_root = self._run_root(blind_run_id)
        marker_path = run_root / "COMPLETE.json"
        if not marker_path.is_file():
            raise CheckpointError("Missing COMPLETE marker")
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if marker.get("status") != "COMPLETE" or marker.get("blind_run_id") != blind_run_id:
            raise CheckpointError("Invalid COMPLETE marker")
        self._validate_status_hashes(marker)
        manifest_path = self.root / marker["run_manifest_relative_path"]
        if sha256_file(manifest_path) != marker.get("run_manifest_sha256"):
            raise CheckpointError("Completed run manifest hash mismatch")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self._validate_status_hashes(manifest)
        if manifest.get("status") != "COMPLETE" or manifest.get("blind_run_id") != blind_run_id:
            raise CheckpointError("Completed run manifest is invalid")
        for artifact in manifest.get("artifacts", []):
            path = manifest_path.parent / artifact["name"]
            if not path.is_file() or path.stat().st_size != artifact["size_bytes"] or sha256_file(path) != artifact["sha256"]:
                raise CheckpointError(f"Completed artifact validation failed: {artifact['name']}")
        return manifest

    def completed_runs(self) -> list[str]:
        completed = []
        for run_root in sorted(path for path in self.runs_root.iterdir() if path.is_dir()):
            if (run_root / "COMPLETE.json").exists():
                self.validate_complete(run_root.name)
                completed.append(run_root.name)
        return completed

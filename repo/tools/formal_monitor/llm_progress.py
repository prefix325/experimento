from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


THEORETICAL_MAX_WINDOWS = 189


@dataclass(frozen=True)
class LLMProgress:
    completed_windows: int = 0
    current_window: int = 0
    max_windows: int = THEORETICAL_MAX_WINDOWS
    last_llm_decision: str | None = None
    first_indication_window: int | None = None
    confirmation_window: int | None = None
    confirmed_detection: bool = False
    early_stop: bool | None = None
    detection_state: str = "SEARCHING"
    verification_advance: int = 0
    verification_advances_required: int = 4
    mean_inference_seconds: float | None = None
    eta_seconds: float | None = None
    checkpoint_status: str | None = None
    source: str | None = None

    def response_fields(self) -> dict[str, Any]:
        value = asdict(self)
        value.update({
            "window_completed": self.completed_windows,
            "window_total_max": self.max_windows,
            "progress_batch_percent": round(
                100 * self.completed_windows / self.max_windows, 2
            ),
            "llm_mean_inference_seconds": self.mean_inference_seconds,
            "eta_batch_seconds": self.eta_seconds,
            "llm_progress_checkpoint_status": self.checkpoint_status,
            "llm_progress_source": self.source,
        })
        return value


class LLMProgressReader:
    """Read live LLM checkpoint progress without mutating scientific artifacts."""

    def __init__(
        self,
        repo_root: str | Path,
        workspace_root: str | Path,
        formal_results_id: str,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.workspace_root = Path(workspace_root).resolve()
        self.formal_results_id = str(formal_results_id)
        config_root = (
            self.repo_root / "experiments" / "tep" / "local_llm" / "config"
        )
        self._selection = {
            "target": self._load_selection(
                config_root / "formal_run_selection.json"
            ),
            "normal_holdout": self._load_selection(
                config_root / "formal_normal_holdout_selection.json"
            ),
        }

    @staticmethod
    def _load_selection(path: Path) -> tuple[int, frozenset[int]]:
        value = json.loads(path.read_text(encoding="utf-8"))
        return (
            int(value["seed"]),
            frozenset(int(run) for run in value["selected_simulation_runs"]),
        )

    @staticmethod
    def _blind_id(simulation_run: int, seed: int) -> str:
        value = f"psqza-formal-v1:{seed}:{int(simulation_run)}".encode("utf-8")
        return "BLIND_" + hashlib.sha256(value).hexdigest()[:16].upper()

    def _active_attempt(
        self,
        cohort: str,
        simulation_run: int,
        *,
        not_before: float | None,
    ) -> tuple[Path, str] | None:
        selection = self._selection.get(cohort)
        if selection is None:
            return None
        seed, selected_runs = selection
        if int(simulation_run) not in selected_runs:
            return None
        blind_id = self._blind_id(simulation_run, seed)
        attempts_root = (
            self.workspace_root
            / "results"
            / "formal"
            / self.formal_results_id
            / cohort
            / "llm"
            / "runs"
            / blind_id
            / "attempts"
        )
        attempts = sorted(
            path
            for path in attempts_root.glob("[0-9][0-9][0-9][0-9]")
            if path.is_dir()
        )
        if not attempts:
            return None
        attempt = attempts[-1]
        status_path = attempt / "status.json"
        try:
            if not_before is not None and status_path.stat().st_mtime < not_before:
                return None
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        checkpoint_status = str(status.get("status", ""))
        if checkpoint_status not in {"PARTIAL", "COMPLETE"}:
            return None
        return attempt, checkpoint_status

    @staticmethod
    def _complete_records(path: Path) -> list[dict[str, Any]]:
        try:
            payload = path.read_bytes()
        except OSError:
            return []
        records: list[dict[str, Any]] = []
        for raw_line in payload.splitlines(keepends=True):
            if not raw_line.endswith((b"\n", b"\r")):
                break
            try:
                record = json.loads(raw_line)
                if int(record.get("window_id", -1)) != len(records):
                    break
            except (TypeError, ValueError):
                break
            records.append(record)
        return records

    def read(
        self,
        cohort: str,
        simulation_run: int,
        *,
        not_before: float | None = None,
    ) -> LLMProgress:
        active = self._active_attempt(
            cohort, simulation_run, not_before=not_before
        )
        if active is None:
            return LLMProgress()
        attempt, checkpoint_status = active
        decisions_path = attempt / "llm_decisions.jsonl"
        records = self._complete_records(decisions_path)
        if not records:
            return LLMProgress(checkpoint_status=checkpoint_status)

        last = records[-1]
        detection = last.get("detection") or {}
        latencies = [
            float(record["latency_ms"]) / 1000
            for record in records
            if isinstance(record.get("latency_ms"), (int, float))
            and float(record["latency_ms"]) >= 0
        ]
        mean_seconds = sum(latencies) / len(latencies) if latencies else None
        completed = len(records)
        early_stop = bool(detection.get("should_stop"))
        eta_seconds = (
            0.0
            if early_stop
            else mean_seconds * max(0, THEORETICAL_MAX_WINDOWS - completed)
            if mean_seconds is not None
            else None
        )
        confirmation_window = detection.get("confirmation_window")
        return LLMProgress(
            completed_windows=completed,
            current_window=int(last["window_id"]) + 1,
            last_llm_decision=last.get("decision"),
            first_indication_window=detection.get("first_indication_window"),
            confirmation_window=confirmation_window,
            confirmed_detection=(
                confirmation_window is not None
                or detection.get("confirmed_detection_status")
                == "CONFIRMED_DETECTION"
            ),
            early_stop=early_stop,
            detection_state=str(detection.get("detection_state", "SEARCHING")),
            verification_advance=int(detection.get("verification_advance", 0)),
            verification_advances_required=int(
                detection.get("verification_advances_required", 4)
            ),
            mean_inference_seconds=mean_seconds,
            eta_seconds=eta_seconds,
            checkpoint_status=checkpoint_status,
            source="llm_decisions.jsonl",
        )

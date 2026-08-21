from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path


METHOD_FREEZE_ID = "TEP-METHOD-FREEZE-20260815-FULL-WINDOW-REFRESH"
CONFORMANCE_FILE = "method_refreeze_implementation_conformance_20260815.json"


@dataclass(frozen=True)
class GateReport:
    ready: bool
    status: str
    reasons: list[str]
    checks: dict[str, bool]
    evidence: dict[str, str | None]

    def to_dict(self) -> dict:
        return asdict(self)


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _latest_acceptance(root: Path) -> tuple[Path | None, dict]:
    candidates = sorted(
        root.glob("*/technical_acceptance.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    ) if root.exists() else []
    for path in candidates:
        artifact = _read(path)
        if artifact.get("status") in {
            "POST_REFREEZE_SYNTHETIC_GPU_ACCEPTANCE",
            "POST_FREEZE_OPERATIONAL_AMENDMENT_SYNTHETIC_ACCEPTANCE",
        }:
            return path, artifact
    return None, {}


def inspect_static_gates(repo_root: str | Path, workspace_root: str | Path) -> GateReport:
    """Inspect only governance artifacts; never opens a model or dataset."""
    repo_root = Path(repo_root)
    workspace_root = Path(workspace_root)
    config_root = repo_root / "experiments" / "tep" / "local_llm" / "config"
    formal_path = config_root / "formal.json"
    formal = _read(formal_path)
    operational_amendment_path = (
        config_root / "post_freeze_operational_amendment_001.json"
    )
    operational_amendment = _read(operational_amendment_path)
    local_gate_path = config_root / "local_execution_gate.json"
    local_gate = _read(local_gate_path)
    conformance_path = workspace_root / "manifests" / CONFORMANCE_FILE
    conformance = _read(conformance_path)
    acceptance_path, acceptance = _latest_acceptance(
        workspace_root / "results" / "technical_acceptance"
    )
    network_check = _read(acceptance_path.parent / "network_check.json") if acceptance_path else {}
    formal_sha256 = _sha256(formal_path) if formal_path.is_file() else None
    acceptance_sha256 = _sha256(acceptance_path) if acceptance_path else None
    operational_amendment_sha256 = (
        _sha256(operational_amendment_path)
        if operational_amendment_path.is_file()
        else None
    )
    acceptance_relative = (
        acceptance_path.resolve().relative_to(workspace_root.resolve()).as_posix()
        if acceptance_path
        else None
    )

    methodological_gate = (
        formal.get("methodology_frozen") is True
        and formal.get("method_freeze_id") == METHOD_FREEZE_ID
        and formal.get("status") == "FORMAL_REFROZEN_FULL_WINDOW_REFRESH"
    )
    implementation_conformance = (
        conformance.get("verdict") == "PASS"
        and conformance.get("method_freeze_id") == METHOD_FREEZE_ID
        and conformance.get("ZERO_NEW_LLM_INFERENCE") is True
        and conformance.get("formal_sha256") == _sha256(formal_path)
    ) if conformance_path.is_file() and formal_path.is_file() else False
    technical_acceptance = (
        acceptance.get("verdict") == "PASS"
        and acceptance.get("method_freeze_id") == METHOD_FREEZE_ID
        and acceptance.get("inference_count") == 1
        and acceptance.get("ZERO_TARGET_ACCESS") is True
        and acceptance.get("ZERO_FAULTFREE_TESTING_ACCESS") is True
        and acceptance.get("formal_scientific_execution_started") is False
        and acceptance.get("operational_amendment_id")
        == operational_amendment.get("amendment_id")
        and acceptance.get("operational_amendment_sha256")
        == operational_amendment_sha256
        and acceptance.get("requested_max_output_tokens") == 1024
        and acceptance.get("output_parser_result") == "PASS"
        and acceptance.get("finish_reason") != "length"
    )
    operational_amendment_gate = (
        operational_amendment.get("amendment_type")
        == "POST_FREEZE_OPERATIONAL_AMENDMENT"
        and operational_amendment.get("status")
        == "AUTHORIZED_FOR_TECHNICAL_MATERIALIZATION"
        and operational_amendment.get("methodological_logic_changed") is False
        and operational_amendment.get("target_informed_tuning") is False
        and operational_amendment.get("inference_runtime_parameter_changed") is True
        and operational_amendment.get("changed_parameter")
        == "/llm/max_output_tokens"
        and operational_amendment.get("from") == 768
        and operational_amendment.get("to") == 1024
        and operational_amendment.get("base_formal_sha256") == formal_sha256
    )
    gpu_offload_acceptance = (
        technical_acceptance
        and acceptance.get("gpu_offload", {}).get("pass") is True
        and acceptance.get("gpu_offload", {}).get("offload_observed") is True
        and acceptance.get("gpu_offload", {}).get("cpu_fallback_warning") is False
    )
    offline_acceptance = (
        acceptance.get("network_mode") == "none"
        and (
            acceptance.get("network_none_verified") is True
            or network_check.get("network_none_verified") is True
        )
    )
    durable_monitor_tests = conformance.get("durable_monitor_controller_tests") == "PASS"
    operational_continuity = (
        local_gate.get("formal_sha256") == formal_sha256
        and local_gate.get("operational_amendment_sha256")
        == operational_amendment_sha256
        and local_gate.get("effective_configuration_sha256")
        == operational_amendment.get("effective_configuration_sha256")
        and local_gate.get("technical_acceptance_artifact") == acceptance_relative
        and local_gate.get("technical_acceptance_artifact_sha256") == acceptance_sha256
        and local_gate.get("implementation_conformance") == "PASS"
        and local_gate.get("technical_acceptance") == "PASS"
        and local_gate.get("gpu_offload_acceptance") == "PASS"
        and local_gate.get("offline_network_none_acceptance") == "PASS"
        and local_gate.get("durable_monitor_controller_tests") == "PASS"
        and local_gate.get("technical_acceptance_inference_count") == 1
        and local_gate.get("gate_status") == "REAL START READY"
    )
    local_authorization = (
        local_gate.get("method_freeze_id") == METHOD_FREEZE_ID
        and local_gate.get("scientific_execution_authorized") is True
        and local_gate.get("formal_runs_started") is True
        and operational_continuity
    )

    checks = {
        "methodological_gate": methodological_gate,
        "operational_amendment_gate": operational_amendment_gate,
        "implementation_conformance": implementation_conformance,
        "technical_acceptance": technical_acceptance,
        "gpu_offload_acceptance": gpu_offload_acceptance,
        "offline_network_none_acceptance": offline_acceptance,
        "durable_monitor_controller_tests": durable_monitor_tests,
        "local_research_execution_authorization": local_authorization,
    }
    reason_names = {
        "methodological_gate": "METHODOLOGICAL_GATE_FAILED",
        "operational_amendment_gate": "OPERATIONAL_AMENDMENT_GATE_FAILED",
        "implementation_conformance": "IMPLEMENTATION_CONFORMANCE_FAILED",
        "technical_acceptance": "TECHNICAL_ACCEPTANCE_PENDING_OR_FAILED",
        "gpu_offload_acceptance": "GPU_OFFLOAD_ACCEPTANCE_PENDING_OR_FAILED",
        "offline_network_none_acceptance": "OFFLINE_ACCEPTANCE_PENDING_OR_FAILED",
        "durable_monitor_controller_tests": "DURABLE_MONITOR_TESTS_FAILED",
        "local_research_execution_authorization": "LOCAL_EXECUTION_NOT_AUTHORIZED",
    }
    reasons = [reason_names[name] for name, passed in checks.items() if not passed]
    ready = all(checks.values())
    return GateReport(
        ready=ready,
        status="REAL START READY" if ready else "REAL START BLOCKED",
        reasons=reasons,
        checks=checks,
        evidence={
            "formal": str(formal_path),
            "local_gate": str(local_gate_path),
            "operational_amendment": str(operational_amendment_path),
            "conformance_manifest": str(conformance_path) if conformance_path.is_file() else None,
            "technical_acceptance": str(acceptance_path) if acceptance_path else None,
            "formal_sha256": formal_sha256,
            "technical_acceptance_sha256": acceptance_sha256,
            "operational_amendment_sha256": operational_amendment_sha256,
        },
    )


def require_real_start(report: GateReport) -> None:
    if not report.ready:
        raise RuntimeError("FORMAL EXECUTION BLOCKED: " + ", ".join(report.reasons))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed operational gate check for formal execution"
    )
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--workspace-root", required=True)
    args = parser.parse_args(argv)
    report = inspect_static_gates(args.repo_root, args.workspace_root)
    print(json.dumps(report.to_dict(), indent=2))
    return 0 if report.ready and report.status == "REAL START READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())

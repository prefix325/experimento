import hashlib
import json
from pathlib import Path

import pytest

from tools.formal_monitor.gates import METHOD_FREEZE_ID, inspect_static_gates, main


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_operational_tree(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    workspace = tmp_path / "workspace"
    repo = workspace / "repo"
    config_root = repo / "experiments" / "tep" / "local_llm" / "config"
    formal_path = config_root / "formal.json"
    write_json(formal_path, {
        "status": "FORMAL_REFROZEN_FULL_WINDOW_REFRESH",
        "methodology_frozen": True,
        "method_freeze_id": METHOD_FREEZE_ID,
        "scientific_execution_permitted": False,
    })
    amendment_path = config_root / "post_freeze_operational_amendment_001.json"
    write_json(amendment_path, {
        "amendment_id": "POST_FREEZE_OPERATIONAL_AMENDMENT_001",
        "amendment_type": "POST_FREEZE_OPERATIONAL_AMENDMENT",
        "status": "AUTHORIZED_FOR_TECHNICAL_MATERIALIZATION",
        "methodological_logic_changed": False,
        "target_informed_tuning": False,
        "inference_runtime_parameter_changed": True,
        "changed_parameter": "/llm/max_output_tokens",
        "from": 768,
        "to": 1024,
        "base_formal_sha256": sha256(formal_path),
        "effective_configuration_sha256": "e" * 64,
    })
    write_json(
        workspace / "manifests" / "method_refreeze_implementation_conformance_20260815.json",
        {
            "verdict": "PASS",
            "method_freeze_id": METHOD_FREEZE_ID,
            "ZERO_NEW_LLM_INFERENCE": True,
            "formal_sha256": sha256(formal_path),
            "durable_monitor_controller_tests": "PASS",
        },
    )
    acceptance_path = (
        workspace
        / "results"
        / "technical_acceptance"
        / "accepted"
        / "technical_acceptance.json"
    )
    write_json(acceptance_path, {
        "status": "POST_FREEZE_OPERATIONAL_AMENDMENT_SYNTHETIC_ACCEPTANCE",
        "method_freeze_id": METHOD_FREEZE_ID,
        "verdict": "PASS",
        "inference_count": 1,
        "ZERO_TARGET_ACCESS": True,
        "ZERO_FAULTFREE_TESTING_ACCESS": True,
        "formal_scientific_execution_started": False,
        "operational_amendment_id": "POST_FREEZE_OPERATIONAL_AMENDMENT_001",
        "operational_amendment_sha256": sha256(amendment_path),
        "requested_max_output_tokens": 1024,
        "output_parser_result": "PASS",
        "finish_reason": "stop",
        "network_mode": "none",
        "network_none_verified": True,
        "gpu_offload": {
            "pass": True,
            "offload_observed": True,
            "cpu_fallback_warning": False,
        },
    })
    gate_path = config_root / "local_execution_gate.json"
    write_json(gate_path, {
        "method_freeze_id": METHOD_FREEZE_ID,
        "formal_sha256": sha256(formal_path),
        "scientific_execution_authorized": True,
        "formal_runs_started": True,
        "operational_amendment_sha256": sha256(amendment_path),
        "effective_configuration_sha256": "e" * 64,
        "gate_status": "REAL START READY",
        "implementation_conformance": "PASS",
        "technical_acceptance": "PASS",
        "gpu_offload_acceptance": "PASS",
        "offline_network_none_acceptance": "PASS",
        "durable_monitor_controller_tests": "PASS",
        "technical_acceptance_inference_count": 1,
        "technical_acceptance_artifact": acceptance_path.relative_to(workspace).as_posix(),
        "technical_acceptance_artifact_sha256": sha256(acceptance_path),
    })
    return repo, workspace, gate_path, acceptance_path


def test_ready_gate_matches_freeze_while_historical_permission_remains_false(tmp_path):
    repo, workspace, _, _ = valid_operational_tree(tmp_path)

    report = inspect_static_gates(repo, workspace)

    assert report.ready is True
    assert report.status == "REAL START READY"
    assert all(report.checks.values())
    formal = json.loads(
        (repo / "experiments" / "tep" / "local_llm" / "config" / "formal.json").read_text()
    )
    assert formal["scientific_execution_permitted"] is False
    assert main(["--repo-root", str(repo), "--workspace-root", str(workspace)]) == 0


def test_failed_technical_acceptance_blocks(tmp_path):
    repo, workspace, _, acceptance_path = valid_operational_tree(tmp_path)
    acceptance = json.loads(acceptance_path.read_text())
    acceptance["verdict"] = "FAIL"
    write_json(acceptance_path, acceptance)

    report = inspect_static_gates(repo, workspace)

    assert report.checks["technical_acceptance"] is False
    assert report.ready is False


def test_failed_gpu_offload_blocks(tmp_path):
    repo, workspace, _, acceptance_path = valid_operational_tree(tmp_path)
    acceptance = json.loads(acceptance_path.read_text())
    acceptance["gpu_offload"]["pass"] = False
    write_json(acceptance_path, acceptance)

    report = inspect_static_gates(repo, workspace)

    assert report.checks["gpu_offload_acceptance"] is False
    assert report.ready is False


def test_missing_local_authorization_blocks(tmp_path):
    repo, workspace, gate_path, _ = valid_operational_tree(tmp_path)
    gate = json.loads(gate_path.read_text())
    gate["scientific_execution_authorized"] = False
    write_json(gate_path, gate)

    report = inspect_static_gates(repo, workspace)

    assert report.checks["local_research_execution_authorization"] is False
    assert report.ready is False


def test_missing_gate_blocks(tmp_path):
    repo, workspace, gate_path, _ = valid_operational_tree(tmp_path)
    gate_path.unlink()

    report = inspect_static_gates(repo, workspace)

    assert report.checks["local_research_execution_authorization"] is False
    assert report.ready is False


@pytest.mark.parametrize("mismatch", ["freeze", "formal_hash", "acceptance_identity"])
def test_gate_continuity_mismatch_blocks(tmp_path, mismatch):
    repo, workspace, gate_path, _ = valid_operational_tree(tmp_path)
    gate = json.loads(gate_path.read_text())
    if mismatch == "freeze":
        gate["method_freeze_id"] = "OLD-FREEZE"
    elif mismatch == "formal_hash":
        gate["formal_sha256"] = "0" * 64
    else:
        gate["technical_acceptance_artifact"] = "results/technical_acceptance/old/technical_acceptance.json"
    write_json(gate_path, gate)

    report = inspect_static_gates(repo, workspace)

    assert report.checks["local_research_execution_authorization"] is False
    assert report.ready is False

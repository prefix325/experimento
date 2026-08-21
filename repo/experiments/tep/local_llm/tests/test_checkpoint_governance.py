import json

import pytest

from tep_local.pipeline import _require_checkpointed_operational_gate
from tools.formal_monitor.tests.test_operational_gate import (
    valid_operational_tree,
    write_json,
)


def governed_config(repo):
    path = repo / "experiments" / "tep" / "local_llm" / "config" / "formal.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_historical_false_with_ready_shared_gate_is_authorized(tmp_path):
    repo, workspace, _, _ = valid_operational_tree(tmp_path)
    config = governed_config(repo)

    report = _require_checkpointed_operational_gate(config, None, repo, workspace)

    assert config["scientific_execution_permitted"] is False
    assert report.ready is True
    assert report.status == "REAL START READY"


def test_shared_gate_without_local_authorization_is_blocked(tmp_path):
    repo, workspace, gate_path, _ = valid_operational_tree(tmp_path)
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["scientific_execution_authorized"] = False
    write_json(gate_path, gate)

    with pytest.raises(RuntimeError, match="LOCAL_EXECUTION_NOT_AUTHORIZED"):
        _require_checkpointed_operational_gate(
            governed_config(repo), None, repo, workspace
        )


@pytest.mark.parametrize("mismatch", ["freeze", "formal_hash"])
def test_shared_gate_freeze_or_hash_mismatch_is_blocked(tmp_path, mismatch):
    repo, workspace, gate_path, _ = valid_operational_tree(tmp_path)
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    if mismatch == "freeze":
        gate["method_freeze_id"] = "OLD-FREEZE"
    else:
        gate["formal_sha256"] = "0" * 64
    write_json(gate_path, gate)

    with pytest.raises(RuntimeError, match="LOCAL_EXECUTION_NOT_AUTHORIZED"):
        _require_checkpointed_operational_gate(
            governed_config(repo), None, repo, workspace
        )


def test_shared_gate_failed_acceptance_is_blocked(tmp_path):
    repo, workspace, _, acceptance_path = valid_operational_tree(tmp_path)
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    acceptance["verdict"] = "FAIL"
    write_json(acceptance_path, acceptance)

    with pytest.raises(RuntimeError, match="TECHNICAL_ACCEPTANCE_PENDING_OR_FAILED"):
        _require_checkpointed_operational_gate(
            governed_config(repo), None, repo, workspace
        )

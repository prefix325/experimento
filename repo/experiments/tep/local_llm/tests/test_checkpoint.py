import json

import pytest

from tep_local.checkpoint import CheckpointError, CheckpointStore, CompletedRunError


def hashes(suffix="a"):
    return {key: suffix * 64 for key in CheckpointStore.REQUIRED_HASHES}


def test_partial_run_restarts_as_new_attempt_and_complete_is_immutable(tmp_path):
    store = CheckpointStore(tmp_path, hashes())
    first = store.begin_run("BLIND_TEST")
    first.artifact("dpca_metrics.jsonl").write_text("{}\n", encoding="utf-8")
    assert store.inspect("BLIND_TEST") == "PARTIAL"
    second = store.begin_run("BLIND_TEST")
    assert second.number == 2
    second.artifact("dpca_metrics.jsonl").write_text("{}\n", encoding="utf-8")
    second.artifact("llm_decisions.jsonl").write_text("{}\n", encoding="utf-8")
    store.complete_run(second, ["dpca_metrics.jsonl", "llm_decisions.jsonl"], {"dpca": 1, "llm": 1})
    assert store.inspect("BLIND_TEST") == "COMPLETE"
    with pytest.raises(CompletedRunError):
        store.begin_run("BLIND_TEST")
    assert json.loads((tmp_path / "runs" / "BLIND_TEST" / "COMPLETE.json").read_text())["status"] == "COMPLETE"


def test_resume_hash_mismatch_is_fail_closed(tmp_path):
    CheckpointStore(tmp_path, hashes("a"))
    with pytest.raises(CheckpointError, match="frozen hashes differ"):
        CheckpointStore(tmp_path, hashes("b"))


def test_operational_provenance_creates_new_attempt_without_changing_contract(tmp_path):
    original = CheckpointStore(tmp_path, hashes())
    first = original.begin_run("BLIND_TEST")
    original.mark_failed(first, "truncated")
    contract_before = (tmp_path / "checkpoint_contract.json").read_bytes()
    provenance = {
        "amendment_id": "POST_FREEZE_OPERATIONAL_AMENDMENT_001",
        "amendment_sha256": "b" * 64,
        "base_configuration_sha256": "a" * 64,
        "effective_configuration_sha256": "c" * 64,
        "changed_parameter": "/llm/max_output_tokens",
        "from": 768,
        "to": 1024,
    }

    resumed = CheckpointStore(
        tmp_path, hashes(), operational_provenance=provenance
    )
    second = resumed.begin_run("BLIND_TEST")

    assert second.number == 2
    assert list(second.directory.glob("llm_decisions.jsonl")) == []
    status = json.loads((second.directory / "status.json").read_text())
    assert status["operational_provenance"] == provenance
    assert (tmp_path / "checkpoint_contract.json").read_bytes() == contract_before


def test_completed_artifact_tampering_is_detected(tmp_path):
    store = CheckpointStore(tmp_path, hashes())
    attempt = store.begin_run("BLIND_TEST")
    artifact = attempt.artifact("result.jsonl")
    artifact.write_text("original\n", encoding="utf-8")
    store.complete_run(attempt, ["result.jsonl"], {"records": 1})
    artifact.write_text("changed\n", encoding="utf-8")
    with pytest.raises(CheckpointError, match="artifact validation failed"):
        store.inspect("BLIND_TEST")

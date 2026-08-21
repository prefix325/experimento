import json
from pathlib import Path

import pytest

from tep_local.config import config_sha256, load_config, validate_development_config
from tep_local.constants import X_COLUMNS
from tep_local.leakage import LeakageError, validate_llm_payload
from tep_local.llm_runtime import validate_llm_output


CONFIG_ROOT = Path("/opt/tep/config")
if not CONFIG_ROOT.exists():
    CONFIG_ROOT = Path(__file__).resolve().parents[1] / "config"


def test_exactly_52_process_variables():
    assert len(X_COLUMNS) == 52
    assert X_COLUMNS[:2] == ["xmeas_1", "xmeas_2"]
    assert X_COLUMNS[-2:] == ["xmv_10", "xmv_11"]
    assert len(set(X_COLUMNS)) == 52


@pytest.mark.parametrize("key", ["y", "faultNumber", "is_anomaly", "dpca", "t2", "spe", "ground_truth"])
def test_prohibited_keys_fail_closed(key):
    with pytest.raises(LeakageError):
        validate_llm_payload({"variables": [], key: 0})


@pytest.mark.parametrize("text", [
    "IDV", "IDV13", "IDV(13)", "idv 13", "TEP", "Tennessee Eastman",
    "faultNumber", "ground truth", "DPCA", "SPE/Q",
])
def test_prohibited_text_fails_closed(text):
    with pytest.raises(LeakageError):
        validate_llm_payload({"note": text})


def test_neutral_payload_passes():
    validate_llm_payload({
        "sample_interval_minutes": 3,
        "representation": "TEST",
        "variables": [{"variable": "xmeas_1", "mean_z": 0.1}],
    })


def test_llm_output_schema_accepts_null_confidence():
    validate_llm_output({
        "decision": "EVIDENCE_INSUFFICIENT",
        "evidence": [],
        "summary": "No stable departure is visible.",
        "confidence": None,
    })


def test_absolute_temporal_keys_fail_closed():
    for key in ("window_id", "sample_start", "sample_end"):
        with pytest.raises(LeakageError, match="absolute temporal key"):
            validate_llm_payload({key: 1, "variables": []})


@pytest.mark.parametrize("key", ["blind_run_id", "simulationRun"])
def test_internal_identifier_keys_fail_closed(key):
    with pytest.raises(LeakageError, match="internal identifier key"):
        validate_llm_payload({key: "INTERNAL_ONLY", "variables": []})


def test_llm_output_rejects_artificial_confidence():
    with pytest.raises(ValueError):
        validate_llm_output({
            "decision": "NORMAL",
            "evidence": [],
            "summary": "Stable.",
            "confidence": 0.9,
        })


def test_smoke_config_is_explicitly_provisional_and_deterministic():
    config = load_config(CONFIG_ROOT / "smoke.json")
    validate_development_config(config)
    assert config["methodology_frozen"] is False
    assert config["window_samples"] == 20
    assert config["stride_samples"] == 5
    assert config["llm"]["temperature"] == 0.0
    assert config_sha256(config) == config_sha256(json.loads(json.dumps(config)))


def test_formal_config_is_frozen_but_scientific_execution_remains_blocked():
    config = load_config(CONFIG_ROOT / "formal.json", require_frozen=True)
    assert config["status"] == "FORMAL_REFROZEN_FULL_WINDOW_REFRESH"
    assert config["method_freeze_id"] == "TEP-METHOD-FREEZE-20260815-FULL-WINDOW-REFRESH"
    assert config["methodology_frozen"] is True
    assert config["scientific_execution_permitted"] is False

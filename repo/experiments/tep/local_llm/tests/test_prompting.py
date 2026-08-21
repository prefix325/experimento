from pathlib import Path

import numpy as np
import pandas as pd

from tep_local.constants import X_COLUMNS
from tep_local.leakage import validate_llm_payload
from tep_local.prompting import build_payload, render_prompt
from tep_local.records import build_internal_llm_record
from tep_local.windowing import CausalWindow


def test_prompt_contains_only_causal_blind_summary(tmp_path: Path):
    values = np.zeros((20, len(X_COLUMNS)))
    frame = pd.DataFrame(values, columns=X_COLUMNS)
    frame.insert(0, "sample", range(1, 21))
    frame.insert(0, "blind_run_id", "BLIND_410D713965BF95C6")
    window = CausalWindow("BLIND_410D713965BF95C6", 0, 1, 20, frame)
    payload = build_payload(window, "PROVISIONAL_SUMMARY_STATS_V1", 3)
    validate_llm_payload(payload)
    assert len(payload["variables"]) == 52
    assert max(item["max_z"] for item in payload["variables"]) == 0.0
    template = tmp_path / "prompt.txt"
    template.write_text("Analyze only this payload: {payload_json}", encoding="utf-8")
    prompt = render_prompt(payload, template)
    for field in ("blind_run_id", "simulationRun", "window_id", "sample_start", "sample_end"):
        assert field not in payload
        assert f'"{field}"' not in prompt
    assert "IDV" not in prompt.upper()
    assert "DPCA" not in prompt.upper()

    record = build_internal_llm_record(
        experiment_id="synthetic",
        window=window,
        payload=payload,
        prompt_hash="a" * 64,
        model_hash="b" * 64,
        usage={"prompt_tokens": 1, "completion_tokens": 1},
        inference_start="2026-01-01T00:00:00+00:00",
        inference_end="2026-01-01T00:00:01+00:00",
        latency_ms=1000,
        output={"decision": "NORMAL", "evidence": [], "summary": "stable", "confidence": None},
        sample_interval_minutes=3,
    )
    assert (record["window_id"], record["sample_start"], record["sample_end"]) == (0, 1, 20)
    assert record["simulation_run_blind_id"] == "BLIND_410D713965BF95C6"
    assert all(
        field not in record["llm_payload"]
        for field in ("blind_run_id", "simulationRun", "window_id", "sample_start", "sample_end")
    )


def test_primary_prompt_has_only_generic_process_context():
    template = Path(__file__).resolve().parents[1] / "config" / "prompt_template.txt"
    text = template.read_text(encoding="utf-8").lower()
    for forbidden in ("tennessee eastman", "tep", "idv", "fault 13", "fault number"):
        assert forbidden not in text
    assert "generic multivariate industrial process" in text
    assert "standardized against a normal-operation reference" in text


def test_serialized_primary_prompt_excludes_all_internal_and_domain_metadata():
    values = np.zeros((20, len(X_COLUMNS)))
    frame = pd.DataFrame(values, columns=X_COLUMNS)
    frame.insert(0, "sample", range(141, 161))
    frame.insert(0, "blind_run_id", "BLIND_SHOULD_NEVER_APPEAR")
    window = CausalWindow("BLIND_SHOULD_NEVER_APPEAR", 28, 141, 160, frame)
    payload = build_payload(window, "NORMAL_REFERENCE_STANDARDIZED_SYMMETRIC_SUMMARY_V1", 3)
    template = Path(__file__).resolve().parents[1] / "config" / "prompt_template.txt"
    prompt = render_prompt(payload, template)
    for forbidden_key in (
        "simulationRun", "blind_run_id", "window_id", "sample_start", "sample_end",
        "faultNumber", "y", "is_anomaly",
    ):
        assert f'"{forbidden_key}"' not in prompt
    lowered = prompt.lower()
    for forbidden_text in ("blind_should_never_appear", "idv", "tennessee eastman", "dpca", "t2", "spe/q"):
        assert forbidden_text not in lowered

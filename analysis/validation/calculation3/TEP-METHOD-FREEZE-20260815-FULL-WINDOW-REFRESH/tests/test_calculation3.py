"""Synthetic-only tests for the independent event/endpoint reconstruction."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest


CODE_DIR = Path(__file__).resolve().parents[1] / "code"
sys.path.insert(0, str(CODE_DIR))

from calculation3 import (  # noqa: E402
    evaluate_h3_item,
    h3_macro_mean,
    h3_response_score,
    h3_run_score,
    reconstruct_dpca_records,
    reconstruct_llm_records,
    verify_bytes_hash,
)


def llm_record(window: int, decision: str = "NORMAL") -> dict:
    return {
        "window_id": window,
        "sample_start": 1 + 5 * window,
        "sample_end": 20 + 5 * window,
        "decision": decision,
        "simulation_run_blind_id": "BLIND_SYNTHETIC",
    }


def dpca_records(raw_samples: set[int]) -> list[dict]:
    records: list[dict] = []
    native_streak = 0
    for sample in range(1, 961):
        raw = sample in raw_samples
        native_streak = native_streak + 1 if raw else 0
        records.append(
            {
                "sample": sample,
                "t2": 2.0 if raw else 0.0,
                "t2_limit": 1.0,
                "spe": 0.0,
                "spe_limit": 1.0,
                "alarm_raw": raw,
                "alarm_persistent": native_streak >= 3,
                "blind_run_id": "BLIND_SYNTHETIC",
            }
        )
    return records


def payload(variable: str = "xmeas_1", **overrides: float) -> dict:
    value = {
        "variable": variable,
        "start_z": 0.0,
        "end_z": 1.0,
        "min_z": -1.0,
        "max_z": 2.0,
        "slope_z_per_sample": 0.2,
    }
    value.update(overrides)
    return value


def thresholds(variable: str = "xmeas_1") -> dict:
    return {
        variable: {
            "high_max_z_q99": 1.5,
            "low_min_z_q01": -0.5,
            "increase_slope_q99": 0.1,
            "reduction_slope_q01": -0.1,
            "high_variability_range_q99": 2.5,
        }
    }


def test_hash_gate() -> None:
    data = b"synthetic fixture\n"
    expected = hashlib.sha256(data).hexdigest()
    assert verify_bytes_hash(data, expected)
    assert not verify_bytes_hash(data + b"changed", expected)


def test_llm_k_to_k_plus_4_confirmation() -> None:
    records = [llm_record(i, "ANOMALY" if i in {0, 4} else "NORMAL") for i in range(5)]
    endpoint, events, _ = reconstruct_llm_records(records, "normal_holdout")
    assert endpoint["any_raw_fa"] is True
    assert endpoint["any_confirmed_fa"] is True
    assert any(row["candidate_origin_window"] == 0 and row["window_id"] == 4 and row["confirmed"] for row in events)


def test_llm_simultaneous_candidates() -> None:
    positives = {0, 1, 4, 5}
    records = [llm_record(i, "ANOMALY" if i in positives else "NORMAL") for i in range(6)]
    endpoint, events, _ = reconstruct_llm_records(records, "normal_holdout")
    confirmed_origins = {row["candidate_origin_window"] for row in events if row["confirmed"]}
    assert endpoint["any_confirmed_fa"] is True
    assert {0, 1}.issubset(confirmed_origins)


def test_llm_failed_candidate_does_not_cancel_another() -> None:
    positives = {0, 1, 5}
    records = [llm_record(i, "ANOMALY" if i in positives else "NORMAL") for i in range(6)]
    endpoint, events, _ = reconstruct_llm_records(records, "normal_holdout")
    start_zero = next(row for row in events if row["window_id"] == 0)
    assert start_zero["candidate_final_status"] == "FAILED"
    assert any(row["candidate_origin_window"] == 1 and row["confirmed"] for row in events)
    assert endpoint["any_confirmed_fa"] is True


def test_llm_onset_reset_forbids_crossing_confirmation() -> None:
    records = [llm_record(i, "ANOMALY" if i in {28, 32} else "NORMAL") for i in range(28, 33)]
    endpoint, events, _ = reconstruct_llm_records(records, "target")
    assert endpoint["raw_pre_onset"] is True
    assert endpoint["raw_post_onset"] is True
    assert endpoint["confirmed_pre_onset"] is False
    assert endpoint["confirmed_post_onset"] is False
    start = next(row for row in events if row["window_id"] == 28)
    assert start["candidate_final_status"] == "RESET_AT_ONSET"


def test_llm_post_onset_candidate_can_confirm_after_reset() -> None:
    positives = {28, 29, 32, 33}
    records = [llm_record(i, "ANOMALY" if i in positives else "NORMAL") for i in range(28, 34)]
    endpoint, _, expected = reconstruct_llm_records(records, "target")
    assert endpoint["confirmed_pre_onset"] is False
    assert endpoint["confirmed_post_onset"] is True
    assert endpoint["confirmation_sample_end"] == 185
    assert expected["confirmation_candidate_window"] == 29
    assert expected["confirmation_window"] == 33


def test_normal_full_trajectory_has_no_onset_segmentation() -> None:
    records = [llm_record(i, "ANOMALY" if i in {28, 32} else "NORMAL") for i in range(28, 33)]
    endpoint, _, _ = reconstruct_llm_records(records, "normal_holdout")
    assert endpoint["any_confirmed_fa"] is True
    assert endpoint["raw_pre_onset"] is None
    assert endpoint["raw_delay_minutes"] is None


def test_llm_non_detection_has_false_and_null_delay() -> None:
    endpoint, _, _ = reconstruct_llm_records([llm_record(i) for i in range(29, 34)], "target")
    assert endpoint["raw_post_onset"] is False
    assert endpoint["confirmed_post_onset"] is False
    assert endpoint["raw_delay_minutes"] is None
    assert endpoint["confirmed_delay_minutes"] is None


def test_llm_terminal_candidate_has_incomplete_machine_state_but_no_endpoint() -> None:
    records = [llm_record(i, "ANOMALY" if i == 188 else "NORMAL") for i in range(185, 189)]
    endpoint, _, expected = reconstruct_llm_records(records, "normal_holdout")
    assert endpoint["any_confirmed_fa"] is False
    assert expected["confirmed_detection_status"] == "NO_CONFIRMED_DETECTION"
    assert expected["detection_state"] == "VERIFICATION_INCOMPLETE_END_OF_TRAJECTORY"


def test_dpca_persistence_three() -> None:
    endpoint, events, crosscheck = reconstruct_dpca_records(dpca_records({170, 171, 172}), "target")
    assert crosscheck == {"raw_mismatches": 0, "persistent_mismatches": 0}
    assert endpoint["first_raw_sample"] == 170
    assert endpoint["first_persistent_sample"] == 172
    assert next(row for row in events if row["time_coordinate"] == 172)["confirmed"] is True


def test_dpca_reset_at_onset() -> None:
    endpoint, _, _ = reconstruct_dpca_records(dpca_records({159, 160, 161, 162, 163}), "target")
    assert endpoint["confirmed_pre_onset"] is False
    assert endpoint["first_persistent_sample"] == 163
    assert endpoint["confirmed_delay_minutes"] == 6


def test_dpca_normal_uses_full_trajectory() -> None:
    endpoint, _, _ = reconstruct_dpca_records(dpca_records({10, 11, 12}), "normal_holdout")
    assert endpoint["any_raw_fa"] is True
    assert endpoint["any_confirmed_fa"] is True
    assert endpoint["first_raw_sample"] is None


@pytest.mark.parametrize(
    ("claim", "values"),
    [
        ("HIGH", {"max_z": 1.5}),
        ("LOW", {"min_z": -0.5}),
        ("INCREASE", {"slope_z_per_sample": 0.1, "start_z": 0.0, "end_z": 0.1}),
        ("REDUCTION", {"slope_z_per_sample": -0.1, "start_z": 0.1, "end_z": 0.0}),
        ("VARIABILITY", {"max_z": 1.5, "min_z": -1.0}),
    ],
)
def test_h3_claim_rules_pass_at_threshold(claim: str, values: dict[str, float]) -> None:
    item = {"variable": "xmeas_1", "claim": claim, "observation": "ignored"}
    result = evaluate_h3_item(item, {"xmeas_1": payload(**values)}, thresholds())
    assert result["verifiable"] is True
    assert result["numeric_rule_pass"] is True
    assert result["item_score"] == 1


def test_h3_invalid_variable() -> None:
    item = {"variable": "not_a_tep_variable", "claim": "HIGH", "observation": "ignored"}
    result = evaluate_h3_item(item, {"not_a_tep_variable": payload("not_a_tep_variable")}, thresholds("not_a_tep_variable"))
    assert result["variable_valid"] is False
    assert result["item_score"] == 0


def test_h3_invalid_claim() -> None:
    result = evaluate_h3_item(
        {"variable": "xmeas_1", "claim": "CAUSE", "observation": "ignored"},
        {"xmeas_1": payload()},
        thresholds(),
    )
    assert result["claim_valid"] is False
    assert result["item_score"] == 0


def test_h3_threshold_absent() -> None:
    result = evaluate_h3_item(
        {"variable": "xmeas_1", "claim": "HIGH", "observation": "ignored"},
        {"xmeas_1": payload()},
        {},
    )
    assert result["variable_valid"] is True
    assert result["threshold_present"] is False
    assert result["item_score"] == 0


def test_h3_empty_evidence_response_rules() -> None:
    assert h3_response_score("ANOMALY", []) == 0.0
    assert h3_response_score("NORMAL", []) is None
    assert h3_response_score("EVIDENCE_INSUFFICIENT", []) is None


def test_h3_run_score_and_macro_mean() -> None:
    assert h3_run_score([1.0, None, 0.0]) == 0.5
    assert h3_run_score([None, None]) is None
    assert h3_macro_mean([0.25, None, 0.75]) == 0.5
    assert h3_macro_mean([None]) is None

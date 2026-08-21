from __future__ import annotations

import sys
from pathlib import Path

import pytest


CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT))

from endpoint_rules import (  # noqa: E402
    dpca_run_endpoints,
    llm_run_endpoints,
    score_h3_run,
)
from statistical_utils import describe_values  # noqa: E402


def llm_records(decisions: dict[int, str], *, stop_at: int = 188) -> list[dict]:
    rows = []
    for window in range(stop_at + 1):
        rows.append(
            {
                "simulation_run_blind_id": "BLIND_TEST",
                "window_id": window,
                "sample_start": 1 + 5 * window,
                "sample_end": 20 + 5 * window,
                "decision": decisions.get(window, "NORMAL"),
                "detection": {"should_stop": window == stop_at and stop_at < 188},
                "evidence": [],
                "llm_payload": {"variables": []},
                "summary": "synthetic",
            }
        )
    return rows


def dpca_records(alarms: set[int]) -> list[dict]:
    rows = []
    streak = 0
    for sample in range(1, 961):
        raw = sample in alarms
        streak = streak + 1 if raw else 0
        rows.append(
            {
                "blind_run_id": "BLIND_TEST",
                "sample": sample,
                "alarm_raw": raw,
                "alarm_persistent": streak >= 3,
                "t2": None if sample <= 5 else 0.0,
                "spe": None if sample <= 5 else 0.0,
                "t2_limit": 1.0,
                "spe_limit": 1.0,
            }
        )
    return rows


def payload(variable: str = "xmeas_1", **changes: float) -> dict:
    result = {
        "variable": variable,
        "start_z": 0.0,
        "end_z": 2.0,
        "mean_z": 1.0,
        "min_z": -3.0,
        "max_z": 3.0,
        "slope_z_per_sample": 0.5,
    }
    result.update(changes)
    return result


THRESHOLDS = {
    "xmeas_1": {
        "high_max_z_q99": 2.0,
        "low_min_z_q01": -2.0,
        "increase_slope_q99": 0.2,
        "reduction_slope_q01": -0.2,
        "high_variability_range_q99": 4.0,
    }
}


def h3_record(window: int, decision: str, evidence: list[dict], variables: list[dict]) -> dict:
    return {
        "simulation_run_blind_id": "BLIND_TEST",
        "window_id": window,
        "sample_start": 1 + 5 * window,
        "sample_end": 20 + 5 * window,
        "decision": decision,
        "evidence": evidence,
        "llm_payload": {"variables": variables},
        "summary": "synthetic",
    }


def test_llm_confirmation_is_candidate_specific_k_plus_4() -> None:
    rows = llm_records({29: "ANOMALY", 31: "ANOMALY", 35: "ANOMALY"}, stop_at=35)
    result = llm_run_endpoints(rows, cohort="target")
    assert result["llm_first_indication_window"] == 29
    assert result["llm_confirmation_candidate_window"] == 31
    assert result["llm_confirmation_window"] == 35
    assert result["llm_confirmation_sample_end"] == 195


def test_llm_confirmation_does_not_cross_onset_reset() -> None:
    rows = llm_records({28: "ANOMALY", 32: "ANOMALY"})
    result = llm_run_endpoints(rows, cohort="target")
    assert result["llm_raw_pre_onset"] is True
    assert result["llm_confirmed_pre_onset"] is False
    assert result["llm_raw_post_onset"] is True
    assert result["llm_confirmed_post_onset"] is False


def test_llm_nondetection_has_null_delays() -> None:
    result = llm_run_endpoints(llm_records({}), cohort="target")
    assert result["llm_raw_post_onset"] is False
    assert result["llm_confirmed_post_onset"] is False
    assert result["llm_raw_delay_minutes"] is None
    assert result["llm_confirmed_delay_minutes"] is None


def test_normal_llm_requires_all_189_windows() -> None:
    result = llm_run_endpoints(llm_records({0: "ANOMALY", 4: "ANOMALY"}), cohort="normal_holdout")
    assert result["llm_any_raw_false_alarm"] is True
    assert result["llm_any_confirmed_false_alarm"] is True
    with pytest.raises(ValueError):
        llm_run_endpoints(llm_records({}, stop_at=187), cohort="normal_holdout")


def test_dpca_persistence_three_and_onset_reset() -> None:
    rows = dpca_records({159, 160, 161})
    result = dpca_run_endpoints(rows, cohort="target")
    assert result["dpca_raw_pre_onset"] is True
    assert result["dpca_confirmed_pre_onset"] is False
    assert result["dpca_raw_post_onset"] is True
    assert result["dpca_confirmed_post_onset"] is False


def test_dpca_first_persistent_and_delays() -> None:
    result = dpca_run_endpoints(dpca_records({170, 171, 172}), cohort="target")
    assert result["dpca_first_raw_sample"] == 170
    assert result["dpca_first_persistent_sample"] == 172
    assert result["dpca_raw_delay_minutes"] == 27
    assert result["dpca_confirmed_delay_minutes"] == 33


def test_h3_frozen_item_rules_oracle() -> None:
    claims = ["HIGH", "LOW", "INCREASE", "REDUCTION", "VARIABILITY"]
    evidence = [{"variable": "xmeas_1", "claim": claim, "observation": "audit only"} for claim in claims]
    run, audit = score_h3_run(
        [h3_record(0, "ANOMALY", evidence, [payload()])],
        THRESHOLDS,
        simulation_run=1,
        blind_run_id="BLIND_TEST",
    )
    assert [row["item_score"] for row in audit] == [1, 1, 1, 0, 1]
    assert run["h3_coverage"] == 1.0
    assert run["h3_run_score"] == pytest.approx(0.8)


def test_h3_verifiable_failure_differs_from_invalid_item() -> None:
    evidence = [
        {"variable": "xmeas_1", "claim": "HIGH", "observation": "valid but fails"},
        {"variable": "not_a_variable", "claim": "HIGH", "observation": "invalid"},
    ]
    run, audit = score_h3_run(
        [h3_record(0, "ANOMALY", evidence, [payload(max_z=1.0)])],
        THRESHOLDS,
        simulation_run=1,
        blind_run_id="BLIND_TEST",
    )
    assert [row["numerically_verifiable"] for row in audit] == [True, False]
    assert [row["item_score"] for row in audit] == [0, 0]
    assert run["h3_coverage"] == 0.5
    assert run["h3_run_score"] == 0.0


def test_h3_empty_response_applicability() -> None:
    records = [
        h3_record(0, "ANOMALY", [], []),
        h3_record(1, "NORMAL", [], []),
        h3_record(2, "EVIDENCE_INSUFFICIENT", [], []),
    ]
    run, audit = score_h3_run(records, THRESHOLDS, simulation_run=1, blind_run_id="BLIND_TEST")
    assert run["h3_applicable_responses"] == 1
    assert run["h3_run_score"] == 0.0
    assert [row["response_score"] for row in audit] == [0.0, None, None]


def test_h3_run_score_weights_responses_not_items() -> None:
    pass_item = {"variable": "xmeas_1", "claim": "HIGH", "observation": "pass"}
    fail_item = {"variable": "xmeas_1", "claim": "REDUCTION", "observation": "fail"}
    records = [
        h3_record(0, "ANOMALY", [pass_item], [payload()]),
        h3_record(1, "ANOMALY", [pass_item, fail_item, fail_item], [payload()]),
    ]
    run, _ = score_h3_run(records, THRESHOLDS, simulation_run=1, blind_run_id="BLIND_TEST")
    assert run["h3_run_score"] == pytest.approx((1.0 + 1.0 / 3.0) / 2.0)


def test_h3_macro_weights_runs_equally() -> None:
    short_run, _ = score_h3_run(
        [h3_record(0, "ANOMALY", [{"variable": "xmeas_1", "claim": "HIGH", "observation": "pass"}], [payload()])],
        THRESHOLDS,
        simulation_run=1,
        blind_run_id="BLIND_ONE",
    )
    long_run, _ = score_h3_run(
        [h3_record(window, "ANOMALY", [{"variable": "xmeas_1", "claim": "REDUCTION", "observation": "fail"}], [payload()]) for window in range(9)],
        THRESHOLDS,
        simulation_run=2,
        blind_run_id="BLIND_TWO",
    )
    macro = describe_values(
        [short_run["h3_run_score"], long_run["h3_run_score"]],
        label="synthetic-h3-macro",
        replicates=200,
        seed=20260820,
    )
    assert macro["mean"] == pytest.approx(0.5)

"""Synthetic tests for independent endpoint and H3 reconstruction.

No expected value in this file comes from a scientific run or prior analysis.
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest


CODE = Path(__file__).resolve().parents[1] / "code"
sys.path.insert(0, str(CODE))

from calculate_endpoints import (  # noqa: E402
    EndpointInputError,
    EndpointIntegrityError,
    crosscheck_endpoint_flag,
    crosscheck_native_flags,
    delay_minutes,
    reconstruct_dpca_endpoint,
    reconstruct_llm_endpoint,
)
from h3_independent import (  # noqa: E402
    evaluate_evidence_item,
    evaluate_h3_dataset,
    evaluate_h3_response,
    score_h3_run,
)


def llm(window: int, sample_end: int, decision: str, **extra):
    return {
        "window_id": window,
        "sample_end": sample_end,
        "decision": decision,
        **extra,
    }


def dpca(sample: int, raw: bool, persistent=None):
    row = {"sample": sample, "alarm_raw": raw}
    if persistent is not None:
        row["alarm_persistent"] = persistent
    return row


def test_llm_confirmation_is_exactly_k_plus_4():
    records = [
        llm(10, 161, "ANOMALY"),
        llm(13, 176, "ANOMALY"),  # k+3 does not confirm k=10
        llm(14, 181, "ANOMALY"),  # k+4 confirms k=10
    ]
    result = reconstruct_llm_endpoint(records, "target_post")
    assert result.raw is True
    assert result.confirmed is True
    assert result.confirmed_candidate_window_ids == (10,)
    assert result.first_confirmed_candidate_window_id == 10
    assert result.first_confirmation_window_id == 14
    assert result.first_confirmation_sample_end == 181


def test_llm_candidates_coexist_and_failure_does_not_clear_another():
    records = [
        llm(1, 161, "ANOMALY"),
        llm(2, 166, "ANOMALY"),
        llm(3, 171, "ANOMALY"),
        llm(5, 181, "NORMAL"),  # candidate 1 fails
        llm(6, 186, "ANOMALY"),  # candidate 2 confirms
        llm(7, 191, "ANOMALY"),  # candidate 3 confirms
    ]
    result = reconstruct_llm_endpoint(records, "target_post")
    assert result.confirmed_candidate_window_ids == (2, 3)
    assert result.first_confirmed_candidate_window_id == 2
    assert result.first_confirmation_window_id == 6


def test_llm_target_regions_reset_at_onset_and_never_cross_it():
    # Numerically these windows are k and k+4, but their sample_end values are
    # on different sides of the scientific boundary.
    records = [llm(20, 160, "ANOMALY"), llm(24, 161, "ANOMALY")]
    pre = reconstruct_llm_endpoint(records, "target_pre")
    post = reconstruct_llm_endpoint(records, "target_post")
    assert pre.raw is True and pre.confirmed is False
    assert post.raw is True and post.confirmed is False
    assert pre.confirmed_delay_minutes is None


def test_llm_normal_uses_full_trajectory_without_artificial_onset_reset():
    records = [llm(20, 160, "ANOMALY"), llm(24, 161, "ANOMALY")]
    normal = reconstruct_llm_endpoint(records, "normal_full")
    assert normal.confirmed is True
    assert normal.first_confirmation_sample_end == 161
    assert normal.raw_delay_minutes is None


def test_llm_eligibility_and_delays():
    records = [
        llm(1, 161, "ANOMALY", eligible=False),
        llm(2, 163, "ANOMALY"),
        llm(6, 167, "ANOMALY"),
    ]
    result = reconstruct_llm_endpoint(records, "target_post")
    assert result.first_raw_window_id == 2
    assert result.raw_delay_minutes == 6
    assert result.first_confirmation_window_id == 6
    assert result.confirmed_delay_minutes == 18


def test_llm_empty_n_zero_and_delay_null():
    result = reconstruct_llm_endpoint([], "target_post")
    assert result.raw is False
    assert result.confirmed is False
    assert result.no_confirmation is True
    assert result.raw_delay_minutes is None
    assert result.confirmed_delay_minutes is None
    assert delay_minutes(False, None) is None


def test_llm_duplicate_window_is_rejected():
    with pytest.raises(EndpointInputError):
        reconstruct_llm_endpoint(
            [llm(1, 161, "NORMAL"), llm(1, 166, "ANOMALY")], "target_post"
        )


def test_dpca_persistence_requires_three_consecutive_raw_alarms():
    records = [
        dpca(161, True),
        dpca(162, True),
        dpca(163, True),
        dpca(164, False),
        dpca(165, True),
        dpca(167, True),  # sample gap resets the streak
        dpca(168, True),
    ]
    result = reconstruct_dpca_endpoint(records, 161, 168, reset=True)
    assert result.raw is True
    assert result.confirmed is True
    assert result.first_raw_sample == 161
    assert result.first_persistent_sample == 163
    assert result.raw_delay_minutes == 0
    assert result.confirmed_delay_minutes == 6
    flags = {row.sample: row.alarm_persistent for row in result.sample_flags}
    assert flags[162] is False
    assert flags[163] is True
    assert flags[168] is False


def test_dpca_post_onset_reset_discards_pre_onset_streak():
    records = [dpca(sample, True) for sample in (159, 160, 161, 162, 163)]
    reset = reconstruct_dpca_endpoint(records, 161, 163, reset=True)
    carried = reconstruct_dpca_endpoint(records, 161, 163, reset=False)
    assert reset.first_persistent_sample == 163
    assert carried.first_persistent_sample == 161


def test_dpca_target_pre_does_not_cross_onset_and_has_no_delay():
    records = [dpca(159, True), dpca(160, True), dpca(161, True)]
    result = reconstruct_dpca_endpoint(records, 1, 160, reset=True)
    assert result.raw is True
    assert result.confirmed is False
    assert result.raw_delay_minutes is None
    assert result.confirmed_delay_minutes is None


def test_dpca_n_one_and_no_detection_delay_is_null():
    one = reconstruct_dpca_endpoint([dpca(161, True)], 161, 161, reset=True)
    assert one.raw is True
    assert one.confirmed is False
    assert one.raw_delay_minutes == 0
    assert one.confirmed_delay_minutes is None

    none = reconstruct_dpca_endpoint([dpca(161, False)], 161, 161, reset=True)
    assert none.raw is False
    assert none.raw_delay_minutes is None


def test_dpca_native_flag_crosscheck_pass_fail_and_not_applicable():
    passing = [
        dpca(1, True, False),
        dpca(2, True, False),
        dpca(3, True, True),
        dpca(4, False, False),
    ]
    result = crosscheck_native_flags(passing, first_sample=1)
    assert result.status == "PASS"
    assert result.compared == 2

    failing = [*passing[:3], dpca(4, False, True)]
    with pytest.raises(EndpointIntegrityError):
        crosscheck_native_flags(failing, first_sample=1)

    absent = [dpca(1, False), dpca(2, False), dpca(3, False)]
    assert crosscheck_native_flags(absent).status == "NOT_APPLICABLE"


def test_endpoint_native_flag_crosscheck_never_chooses_on_mismatch():
    assert crosscheck_endpoint_flag(True, True).status == "PASS"
    assert crosscheck_endpoint_flag(False, None).status == "NOT_APPLICABLE"
    with pytest.raises(EndpointIntegrityError):
        crosscheck_endpoint_flag(True, False)


THRESHOLDS = {
    "valid_variables": ["A", "B", "C", "D", "E"],
    "variables": {
        "A": {"high_max_z_q99": 2.0},
        "B": {"low_min_z_q01": -2.0},
        "C": {"increase_slope_q99": 0.2},
        "D": {"reduction_slope_q01": -0.2},
        "E": {"high_variability_range_q99": 3.0},
    },
}


def evidence(variable: str, claim: str, observation="ignored text"):
    return {"variable": variable, "claim": claim, "observation": observation}


@pytest.mark.parametrize(
    ("item", "payload"),
    [
        (evidence("A", "HIGH"), {"A": {"max_z": 2.0}}),
        (evidence("B", "LOW"), {"B": {"min_z": -2.0}}),
        (
            evidence("C", "INCREASE"),
            {"C": {"slope_z_per_sample": 0.2, "start_z": 1.0, "end_z": 1.1}},
        ),
        (
            evidence("D", "REDUCTION"),
            {"D": {"slope_z_per_sample": -0.2, "start_z": 1.0, "end_z": 0.9}},
        ),
        (evidence("E", "VARIABILITY"), {"E": {"max_z": 1.11116, "min_z": -1.88885}}),
    ],
)
def test_each_h3_numeric_rule_accepts_its_exact_boundary(item, payload):
    audit = evaluate_evidence_item(
        item, payload, THRESHOLDS, simulation_run=1, response_id="synthetic"
    )
    assert audit.verifiable is True
    assert audit.rule_satisfied is True
    assert audit.item_score == 1


def test_h3_increase_and_reduction_require_direction_too():
    increase = evaluate_evidence_item(
        evidence("C", "INCREASE"),
        {"C": {"slope_z_per_sample": 0.4, "start_z": 2.0, "end_z": 2.0}},
        THRESHOLDS,
    )
    reduction = evaluate_evidence_item(
        evidence("D", "REDUCTION"),
        {"D": {"slope_z_per_sample": -0.4, "start_z": 2.0, "end_z": 2.0}},
        THRESHOLDS,
    )
    assert increase.item_score == 0
    assert reduction.item_score == 0


def test_h3_variability_rounds_range_to_four_decimals_before_comparison():
    passing = evaluate_evidence_item(
        evidence("E", "VARIABILITY"),
        {"E": {"max_z": 1.00004, "min_z": -1.99995}},
        THRESHOLDS,
    )
    failing = evaluate_evidence_item(
        evidence("E", "VARIABILITY"),
        {"E": {"max_z": 1.0, "min_z": -1.99994}},
        THRESHOLDS,
    )
    assert passing.item_score == 1  # round(2.99999, 4) == 3.0
    assert failing.item_score == 0  # round(2.99994, 4) == 2.9999


def test_h3_observation_is_outside_the_score():
    payload = {"A": {"max_z": 2.1}}
    plausible = evaluate_evidence_item(
        evidence("A", "HIGH", "A is high"), payload, THRESHOLDS
    )
    contradictory = evaluate_evidence_item(
        evidence("A", "HIGH", "A is definitely not high"), payload, THRESHOLDS
    )
    assert plausible.item_score == contradictory.item_score == 1


def test_h3_verifiability_checks_enum_variable_payload_and_threshold():
    unsupported = evaluate_evidence_item(
        evidence("A", "OSCILLATION"), {"A": {"max_z": 9}}, THRESHOLDS
    )
    invalid_variable = evaluate_evidence_item(
        evidence("Z", "HIGH"), {"Z": {"max_z": 9}}, THRESHOLDS
    )
    wrong_window = evaluate_evidence_item(evidence("A", "HIGH"), {}, THRESHOLDS)
    missing_threshold = evaluate_evidence_item(
        evidence("B", "HIGH"), {"B": {"max_z": 9}}, THRESHOLDS
    )
    assert [
        unsupported.item_score,
        invalid_variable.item_score,
        wrong_window.item_score,
        missing_threshold.item_score,
    ] == [0, 0, 0, 0]
    assert not any(
        audit.verifiable
        for audit in (unsupported, invalid_variable, wrong_window, missing_threshold)
    )


def test_h3_no_evidence_decision_cases():
    anomaly = evaluate_h3_response(
        {"simulationRun": 1, "decision": "ANOMALY", "evidence": []}, THRESHOLDS
    )
    normal = evaluate_h3_response(
        {"simulationRun": 1, "decision": "NORMAL", "evidence": []}, THRESHOLDS
    )
    insufficient = evaluate_h3_response(
        {
            "simulationRun": 1,
            "decision": "EVIDENCE_INSUFFICIENT",
            "evidence": [],
        },
        THRESHOLDS,
    )
    assert anomaly.response_score == 0.0
    assert normal.response_score is None
    assert insufficient.response_score is None


def test_h3_run_score_means_only_applicable_responses():
    responses = [
        {
            "simulationRun": 7,
            "decision": "ANOMALY",
            "evidence": [evidence("A", "HIGH")],
            "payload": {"A": {"max_z": 3}},
        },
        {"simulationRun": 7, "decision": "NORMAL", "evidence": []},
        {"simulationRun": 7, "decision": "ANOMALY", "evidence": []},
    ]
    result = score_h3_run(responses, THRESHOLDS)
    assert result.applicable_responses == 2
    assert result.run_score == pytest.approx(0.5)


def test_h3_reads_the_persisted_llm_payload_shape():
    response = {
        "decision": "ANOMALY",
        "evidence": [evidence("A", "HIGH")],
        "llm_payload": {
            "variables": [
                {
                    "variable": "A",
                    "start_z": 0.0,
                    "end_z": 3.0,
                    "min_z": 0.0,
                    "max_z": 3.0,
                    "slope_z_per_sample": 0.2,
                }
            ]
        },
    }
    result = evaluate_h3_response(response, THRESHOLDS)
    assert result.response_score == 1.0
    assert result.audits[0].variable_valid is True


def test_h3_macro_has_equal_run_weight_and_micro_is_secondary():
    responses = [
        {
            "simulationRun": 1,
            "decision": "ANOMALY",
            "evidence": [evidence("A", "HIGH")],
            "payload": {"A": {"max_z": 3}},
        },
        {
            "simulationRun": 1,
            "decision": "ANOMALY",
            "evidence": [evidence("A", "HIGH")],
            "payload": {"A": {"max_z": 4}},
        },
        {
            "simulationRun": 2,
            "decision": "ANOMALY",
            "evidence": [evidence("A", "HIGH")],
            "payload": {"A": {"max_z": 0}},
        },
        {"simulationRun": 3, "decision": "NORMAL", "evidence": []},
    ]
    result = evaluate_h3_dataset(
        responses,
        THRESHOLDS,
        all_run_ids=[1, 2, 3],
        bootstrap_resamples=200,
        bootstrap_seed=123,
    )
    assert result.applicable_runs == 2
    assert result.non_applicable_runs == 1
    assert result.macro_mean == pytest.approx(0.5)  # mean(run1=1, run2=0)
    assert result.micro_score == pytest.approx(2 / 3)
    assert result.applicable_responses == 3
    assert result.coverage == 1.0
    assert len(result.audits) == 3


def test_h3_dataset_n_zero_and_n_one_are_defined_without_fake_items():
    empty = evaluate_h3_dataset(
        [], THRESHOLDS, all_run_ids=[], bootstrap_resamples=10
    )
    assert empty.total_evidence_items == 0
    assert empty.coverage is None
    assert empty.applicable_runs == 0
    assert empty.macro_mean is None
    assert empty.bootstrap_low is None

    one = evaluate_h3_dataset(
        [{"simulationRun": 1, "decision": "ANOMALY", "evidence": []}],
        THRESHOLDS,
        bootstrap_resamples=10,
    )
    assert one.total_evidence_items == 0
    assert one.applicable_runs == 1
    assert one.macro_mean == 0.0
    assert one.median == 0.0
    assert one.bootstrap_low is None
    assert one.bootstrap_high is None
    assert one.bootstrap_method is None

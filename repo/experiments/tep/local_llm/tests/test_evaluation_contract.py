import pandas as pd

from tep_local.evaluation import evaluate_dpca, evaluate_h3, evaluate_llm


RUN = "BLIND_SYNTHETIC"


def truth():
    return pd.DataFrame(
        {"blind_run_id": [RUN], "sample": [1], "y": [0]}
    )


def payload(
    maximum=0.0,
    minimum=0.0,
    start=0.0,
    end=0.0,
    slope=0.0,
):
    return {
        "sample_interval_minutes": 3,
        "representation": "TEST",
        "variables": [{
            "variable": "xmeas_1",
            "start_z": start,
            "end_z": end,
            "mean_z": 0.0,
            "min_z": minimum,
            "max_z": maximum,
            "slope_z_per_sample": slope,
        }],
    }


def llm_record(
    window_id,
    sample_end,
    decision="NORMAL",
    evidence=None,
    run_id=RUN,
):
    return {
        "simulation_run_blind_id": run_id,
        "window_id": window_id,
        "sample_end": sample_end,
        "decision": decision,
        "evidence": evidence or [],
        "llm_payload": payload(),
    }


def reference():
    return {"thresholds": {"xmeas_1": {
        "high_max_z_q99": 2.0,
        "low_min_z_q01": -2.0,
        "increase_slope_q99": 0.2,
        "reduction_slope_q01": -0.2,
        "high_variability_range_q99": 4.0,
    }}}


def test_pre_onset_candidate_cannot_cross_onset():
    records = [
        llm_record(0, 145, "ANOMALY"),
        llm_record(1, 150, "ANOMALY"),
        llm_record(2, 155),
        llm_record(3, 160),
        llm_record(4, 165, "ANOMALY"),
    ]
    result = evaluate_llm(records, truth(), 3, reference())
    run = result["h2"]["by_run"][RUN]
    assert result["h2"]["onset_reset"] is True
    assert run["first_indication"] == 165
    assert run["confirmed_alarm"] is None
    assert result["h1"]["prefault_raw_false_indication_runs"] == 1


def test_first_indication_and_confirmation_delays_are_separate():
    records = [
        llm_record(index, sample, decision)
        for index, (sample, decision) in enumerate([
            (165, "ANOMALY"),
            (170, "NORMAL"),
            (175, "NORMAL"),
            (180, "NORMAL"),
            (185, "ANOMALY"),
        ])
    ]
    result = evaluate_llm(records, truth(), 3, reference())
    run = result["h2"]["by_run"][RUN]
    assert run["first_indication_delay_samples"] == 4
    assert run["first_indication_delay_minutes"] == 12
    assert run["confirmed_detection_delay_samples"] == 24
    assert run["confirmed_detection_delay_minutes"] == 72
    assert result["h1"]["first_indication_rate"] == 1.0
    assert result["h1"]["confirmed_detection_rate"] == 1.0


def test_candidate_zero_fails_while_candidate_one_confirms():
    decisions = [
        "ANOMALY", "ANOMALY", "NORMAL",
        "NORMAL", "NORMAL", "ANOMALY",
    ]
    records = [
        llm_record(index, 161 + index * 5, decision)
        for index, decision in enumerate(decisions)
    ]
    result = evaluate_llm(records, truth(), 3, reference())
    run = result["h2"]["by_run"][RUN]
    assert run["failed_candidate_windows"] == [0]
    assert run["confirmation_candidate_window"] == 1
    assert run["confirmation_window"] == 5
    assert run["confirmed_alarm"] == 186


def test_normal_false_alarm_layers_use_same_candidate_machine():
    target = [llm_record(0, 165)]
    normal = [
        llm_record(
            index,
            20 + index * 5,
            "ANOMALY" if index in {0, 4} else "NORMAL",
            run_id="NORMAL_X",
        )
        for index in range(5)
    ]
    result = evaluate_llm(
        target, truth(), 3, reference(), normal
    )
    h1 = result["h1"]
    assert h1["raw_anomaly_window_rate"] == 2 / 5
    assert h1["raw_false_alarm_run_incidence"] == 1.0
    assert h1["confirmed_false_alarm_run_incidence"] == 1.0
    normal_run = h1["normal_holdout_by_run"]["NORMAL_X"]
    assert normal_run[
        "time_to_first_confirmed_false_alarm_minutes"
    ] == 117


def test_abstention_at_verification_fails_only_due_candidate():
    decisions = [
        "ANOMALY", "NORMAL", "NORMAL",
        "NORMAL", "EVIDENCE_INSUFFICIENT",
    ]
    records = [
        llm_record(index, 161 + index * 5, decision)
        for index, decision in enumerate(decisions)
    ]
    result = evaluate_llm(records, truth(), 3, reference())
    run = result["h2"]["by_run"][RUN]
    assert run["confirmed_alarm"] is None
    assert run["failed_candidate_windows"] == [0]
    assert result["h2"]["abstention_count"] == 1


def test_dpca_onset_reset_and_persistence_are_unchanged():
    records = [
        {
            "blind_run_id": RUN,
            "sample": sample,
            "t2": 1.0,
            "spe": 1.0,
            "alarm_raw": True,
        }
        for sample in (159, 160, 161)
    ]
    result = evaluate_dpca(records, truth(), 3)
    assert result["h2"]["by_run"][RUN]["detected"] is False
    records.extend([
        {
            "blind_run_id": RUN,
            "sample": sample,
            "t2": 1.0,
            "spe": 1.0,
            "alarm_raw": True,
        }
        for sample in (162, 163)
    ])
    result = evaluate_dpca(records, truth(), 3)
    assert result["h2"]["by_run"][RUN]["confirmed_alarm"] == 163


def test_h3_is_process_evidence_groundedness():
    claims = ["HIGH", "LOW", "INCREASE", "REDUCTION", "VARIABILITY"]
    record = llm_record(
        0,
        175,
        "ANOMALY",
        evidence=[
            {
                "variable": "xmeas_1",
                "claim": claim,
                "observation": "qualitative audit text",
            }
            for claim in claims
        ],
    )
    record["llm_payload"] = payload(
        maximum=3.0,
        minimum=-3.0,
        start=0.0,
        end=2.0,
        slope=0.5,
    )
    result = evaluate_h3([record], reference())
    assert result["coverage"] == 1.0
    assert result["macro_run_coherence"] == 0.8
    assert result["observation_text_used_for_primary_score"] is False

from __future__ import annotations

from typing import Any

import numpy as np

from .detection import FullWindowRefreshTracker, full_window_refresh_advances


def _safe_div(numerator: float, denominator: float) -> float | None:
    return float(numerator / denominator) if denominator else None


def _delay_summary(values: list[int]) -> dict[str, Any]:
    return {
        "count": len(values),
        "mean": float(np.mean(values)) if values else None,
        "median": float(np.median(values)) if values else None,
        "q25": float(np.quantile(values, 0.25)) if values else None,
        "q75": float(np.quantile(values, 0.75)) if values else None,
    }


def _track(
    records: list[dict[str, Any]],
    window_samples: int,
    stride_samples: int,
    *,
    target: bool,
) -> dict[str, Any]:
    ordered = sorted(
        records,
        key=lambda record: (
            int(record["window_id"]),
            int(record["sample_end"]),
        ),
    )
    tracker = FullWindowRefreshTracker(
        window_samples, stride_samples, target=target
    )
    confirmed_samples: list[int] = []
    failed_candidates: list[int] = []
    for record in ordered:
        update = tracker.observe(
            int(record["window_id"]), str(record["decision"])
        )
        for event in update.candidate_events:
            if event["event"] == "CONFIRMED_DETECTION":
                confirmed_samples.append(int(record["sample_end"]))
            elif event["event"] == "VERIFICATION_FAILED":
                failed_candidates.append(int(event["candidate_window"]))
    final = tracker.finalize()
    first_sample = None
    if tracker.first_indication_window is not None:
        first_sample = next(
            int(record["sample_end"])
            for record in ordered
            if int(record["window_id"]) == tracker.first_indication_window
        )
    return {
        "records": ordered,
        "raw_anomaly_samples": [
            int(record["sample_end"])
            for record in ordered
            if record.get("decision") == "ANOMALY"
        ],
        "first_indication_sample": first_sample,
        "first_indication_window": tracker.first_indication_window,
        "confirmed_samples": confirmed_samples,
        "confirmation_window": tracker.confirmation_window,
        "confirmation_candidate_window": (
            tracker.confirmation_candidate_window
        ),
        "failed_candidate_windows": failed_candidates,
        "incomplete_candidate_windows": list(
            tracker.incomplete_candidate_windows
        ),
        "final": final,
    }


def evaluate_confirmation_contract(
    records: list[dict[str, Any]],
    run_ids: list[str],
    interval_minutes: int,
    window_samples: int,
    stride_samples: int,
    fault_onset_sample: int,
    normal_holdout_records: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    by_run: dict[str, Any] = {}
    first_indication_runs = 0
    confirmed_detection_runs = 0
    prefault_raw_runs = 0
    prefault_confirmed_runs = 0
    first_delays: list[int] = []
    confirmed_delays: list[int] = []

    for run_id in run_ids:
        run = [
            record
            for record in records
            if str(record["simulation_run_blind_id"]) == run_id
        ]
        prefault = [
            record
            for record in run
            if int(record["sample_end"]) < fault_onset_sample
        ]
        post_onset = [
            record
            for record in run
            if int(record["sample_end"]) >= fault_onset_sample
        ]
        pre = _track(
            prefault, window_samples, stride_samples, target=False
        )
        post = _track(
            post_onset, window_samples, stride_samples, target=True
        )
        first_sample = post["first_indication_sample"]
        confirmed_sample = (
            post["confirmed_samples"][0]
            if post["confirmed_samples"]
            else None
        )
        first_delay_samples = (
            first_sample - fault_onset_sample
            if first_sample is not None
            else None
        )
        confirmed_delay_samples = (
            confirmed_sample - fault_onset_sample
            if confirmed_sample is not None
            else None
        )
        if first_sample is not None:
            first_indication_runs += 1
            first_delays.append(first_delay_samples * interval_minutes)
        if confirmed_sample is not None:
            confirmed_detection_runs += 1
            confirmed_delays.append(
                confirmed_delay_samples * interval_minutes
            )
        prefault_raw_runs += bool(pre["raw_anomaly_samples"])
        prefault_confirmed_runs += bool(pre["confirmed_samples"])
        by_run[run_id] = {
            "first_indication_status": (
                "FIRST_INDICATION"
                if first_sample is not None
                else "NO_FIRST_INDICATION"
            ),
            "confirmed_detection_status": (
                "CONFIRMED_DETECTION"
                if confirmed_sample is not None
                else "NO_CONFIRMED_DETECTION"
            ),
            "first_indication": first_sample,
            "first_indication_window": post["first_indication_window"],
            "confirmed_alarm": confirmed_sample,
            "confirmation_window": post["confirmation_window"],
            "confirmation_candidate_window": (
                post["confirmation_candidate_window"]
            ),
            "first_indication_delay_samples": first_delay_samples,
            "first_indication_delay_minutes": (
                first_delay_samples * interval_minutes
                if first_delay_samples is not None
                else None
            ),
            "confirmed_detection_delay_samples": (
                confirmed_delay_samples
            ),
            "confirmed_detection_delay_minutes": (
                confirmed_delay_samples * interval_minutes
                if confirmed_delay_samples is not None
                else None
            ),
            "detected": confirmed_sample is not None,
            "detection_delay_samples": confirmed_delay_samples,
            "detection_delay_minutes": (
                confirmed_delay_samples * interval_minutes
                if confirmed_delay_samples is not None
                else None
            ),
            "first_prefault_raw_anomaly": (
                pre["raw_anomaly_samples"][0]
                if pre["raw_anomaly_samples"]
                else None
            ),
            "first_prefault_confirmed_alarm": (
                pre["confirmed_samples"][0]
                if pre["confirmed_samples"]
                else None
            ),
            "failed_candidate_windows": post[
                "failed_candidate_windows"
            ],
            "incomplete_candidate_windows": post[
                "incomplete_candidate_windows"
            ],
        }

    total_runs = len(run_ids)
    h1 = {
        "runs": total_runs,
        "first_indication_runs": first_indication_runs,
        "first_indication_rate": _safe_div(
            first_indication_runs, total_runs
        ),
        "no_first_indication_runs": (
            total_runs - first_indication_runs
        ),
        "confirmed_detection_runs": confirmed_detection_runs,
        "confirmed_detection_rate": _safe_div(
            confirmed_detection_runs, total_runs
        ),
        "no_confirmed_detection_runs": (
            total_runs - confirmed_detection_runs
        ),
        "detected_runs": confirmed_detection_runs,
        "detection_rate": _safe_div(
            confirmed_detection_runs, total_runs
        ),
        "no_detection_runs": total_runs - confirmed_detection_runs,
        "no_detection_rate": _safe_div(
            total_runs - confirmed_detection_runs, total_runs
        ),
        "prefault_raw_false_indication_runs": prefault_raw_runs,
        "prefault_raw_false_indication_run_incidence": _safe_div(
            prefault_raw_runs, total_runs
        ),
        "false_alarm_runs_prefault": prefault_confirmed_runs,
        "false_alarm_rate_prefault": _safe_div(
            prefault_confirmed_runs, total_runs
        ),
        "first_indication_delay_minutes": _delay_summary(
            first_delays
        ),
        "confirmed_detection_delay_minutes": _delay_summary(
            confirmed_delays
        ),
    }
    normal = _normal_metrics(
        normal_holdout_records,
        interval_minutes,
        window_samples,
        stride_samples,
    )
    return {
        "h1": {**h1, **normal},
        "h2": {
            "confirmation_policy_id": (
                "FIRST_INDICATION_CONCURRENT_FULL_SAMPLE_REFRESH_V1"
            ),
            "window_samples": window_samples,
            "stride_samples": stride_samples,
            "verification_advances": full_window_refresh_advances(
                window_samples, stride_samples
            ),
            "fault_onset_sample": fault_onset_sample,
            "onset_reset": True,
            "candidate_concurrency": True,
            "by_run": by_run,
        },
    }


def _normal_metrics(
    records: list[dict[str, Any]] | None,
    interval_minutes: int,
    window_samples: int,
    stride_samples: int,
) -> dict[str, Any]:
    if records is None:
        return {
            "normal_holdout_runs": 0,
            "raw_anomaly_window_rate": None,
            "raw_false_alarm_run_incidence": None,
            "confirmed_false_alarm_run_incidence": None,
            "time_to_first_confirmed_false_alarm": None,
            "status": "NORMAL_HOLDOUT_NOT_EVALUATED",
        }
    run_ids = sorted(
        {
            str(record["simulation_run_blind_id"])
            for record in records
        }
    )
    raw_windows = 0
    total_windows = 0
    raw_runs = 0
    confirmed_runs = 0
    first_times: list[int] = []
    by_run: dict[str, Any] = {}
    for run_id in run_ids:
        run = [
            record
            for record in records
            if str(record["simulation_run_blind_id"]) == run_id
        ]
        tracked = _track(
            run, window_samples, stride_samples, target=False
        )
        raw_count = len(tracked["raw_anomaly_samples"])
        first_confirmed = (
            tracked["confirmed_samples"][0]
            if tracked["confirmed_samples"]
            else None
        )
        raw_windows += raw_count
        total_windows += len(run)
        raw_runs += raw_count > 0
        confirmed_runs += first_confirmed is not None
        time_minutes = (
            (first_confirmed - 1) * interval_minutes
            if first_confirmed is not None
            else None
        )
        if time_minutes is not None:
            first_times.append(time_minutes)
        by_run[run_id] = {
            "raw_anomaly_windows": raw_count,
            "raw_false_alarm": raw_count > 0,
            "confirmed_false_alarm": first_confirmed is not None,
            "first_confirmed_false_alarm_sample": first_confirmed,
            "time_to_first_confirmed_false_alarm_minutes": (
                time_minutes
            ),
        }
    return {
        "normal_holdout_runs": len(run_ids),
        "raw_anomaly_window_rate": _safe_div(
            raw_windows, total_windows
        ),
        "raw_false_alarm_run_incidence": _safe_div(
            raw_runs, len(run_ids)
        ),
        "confirmed_false_alarm_run_incidence": _safe_div(
            confirmed_runs, len(run_ids)
        ),
        "time_to_first_confirmed_false_alarm": _delay_summary(
            first_times
        ),
        "normal_holdout_by_run": by_run,
        "normal_early_stop": False,
        "alarm_episode_clustering_used": False,
    }

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from .constants import EVIDENCE_CLAIMS, X_COLUMNS
from .dataset import load_ground_truth
from .detection import FullWindowRefreshTracker, full_window_refresh_advances
from .confirmation_evaluation import evaluate_confirmation_contract
from .hashing import sha256_file
from .records import read_jsonl
from .selection import (
    apply_blind_mapping_to_ground_truth,
    apply_selection_to_ground_truth,
    blind_id_for_run,
    load_run_selection,
)


FAULT_ONSET_SAMPLE = 161


def _safe_div(numerator: float, denominator: float) -> float | None:
    return float(numerator / denominator) if denominator else None


def _confirmation_mask(positive: list[bool], persistence: int) -> list[bool]:
    consecutive = 0
    confirmed = []
    for value in positive:
        consecutive = consecutive + 1 if value else 0
        confirmed.append(consecutive >= persistence)
    return confirmed


def _sequence_metrics(
    records: list[dict[str, Any]],
    run_ids: list[str],
    run_key: str,
    time_key: str,
    is_positive: Callable[[dict[str, Any]], bool],
    persistence: int,
    interval_minutes: int,
    eligible: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    eligible = eligible or (lambda _: True)
    by_run: dict[str, dict[str, Any]] = {}
    detected_runs = 0
    prefault_alarm_runs = 0
    prefault_confirmed_opportunities = 0
    prefault_opportunities = 0
    delays = []

    for run_id in run_ids:
        run = sorted(
            (record for record in records if str(record[run_key]) == run_id and eligible(record)),
            key=lambda record: (int(record[time_key]), int(record.get("window_id", 0))),
        )
        first_positive = next((int(record[time_key]) for record in run if is_positive(record)), None)
        prefault = [record for record in run if int(record[time_key]) <= FAULT_ONSET_SAMPLE - 1]
        post_onset = [record for record in run if int(record[time_key]) >= FAULT_ONSET_SAMPLE]

        prefault_mask = _confirmation_mask([is_positive(record) for record in prefault], persistence)
        post_mask = _confirmation_mask([is_positive(record) for record in post_onset], persistence)
        prefault_confirmed = [
            int(record[time_key]) for record, confirmed in zip(prefault, prefault_mask) if confirmed
        ]
        post_confirmed = [
            int(record[time_key]) for record, confirmed in zip(post_onset, post_mask) if confirmed
        ]
        confirmed_alarm = post_confirmed[0] if post_confirmed else None
        detected = confirmed_alarm is not None
        delay_samples = confirmed_alarm - FAULT_ONSET_SAMPLE if detected else None
        delay_minutes = delay_samples * interval_minutes if delay_samples is not None else None
        if detected:
            detected_runs += 1
            delays.append(delay_minutes)
        if prefault_confirmed:
            prefault_alarm_runs += 1
        prefault_confirmed_opportunities += sum(prefault_mask)
        prefault_opportunities += len(prefault_mask)
        by_run[run_id] = {
            "first_positive": first_positive,
            "first_prefault_confirmed_alarm": prefault_confirmed[0] if prefault_confirmed else None,
            "confirmed_alarm": confirmed_alarm,
            "detected": detected,
            "detection_delay_samples": delay_samples,
            "detection_delay_minutes": delay_minutes,
        }

    total_runs = len(run_ids)
    return {
        "runs": total_runs,
        "detected_runs": detected_runs,
        "no_detection_runs": total_runs - detected_runs,
        "detection_rate": _safe_div(detected_runs, total_runs),
        "no_detection_rate": _safe_div(total_runs - detected_runs, total_runs),
        "false_alarm_runs_prefault": prefault_alarm_runs,
        "false_alarm_rate_prefault": _safe_div(prefault_alarm_runs, total_runs),
        "false_alarm_opportunity_rate_prefault": _safe_div(
            prefault_confirmed_opportunities, prefault_opportunities
        ),
        "prefault_confirmed_opportunities": prefault_confirmed_opportunities,
        "prefault_opportunities": prefault_opportunities,
        "detection_delay_minutes_detected_only": {
            "count": len(delays),
            "mean": float(np.mean(delays)) if delays else None,
            "median": float(np.median(delays)) if delays else None,
            "q25": float(np.quantile(delays, 0.25)) if delays else None,
            "q75": float(np.quantile(delays, 0.75)) if delays else None,
        },
        "by_run": by_run,
    }


def _normal_false_alarm_metrics(
    records: list[dict[str, Any]],
    run_key: str,
    time_key: str,
    is_positive: Callable[[dict[str, Any]], bool],
    persistence: int,
    eligible: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
    eligible = eligible or (lambda _: True)
    run_ids = sorted({str(record[run_key]) for record in records})
    false_alarm_runs = 0
    confirmed_opportunities = 0
    opportunities = 0
    for run_id in run_ids:
        run = sorted(
            (record for record in records if str(record[run_key]) == run_id and eligible(record)),
            key=lambda record: (int(record[time_key]), int(record.get("window_id", 0))),
        )
        mask = _confirmation_mask([is_positive(record) for record in run], persistence)
        false_alarm_runs += bool(any(mask))
        confirmed_opportunities += sum(mask)
        opportunities += len(mask)
    return {
        "normal_holdout_runs": len(run_ids),
        "false_alarm_runs_normal_holdout": int(false_alarm_runs),
        "false_alarm_rate_normal_holdout": _safe_div(false_alarm_runs, len(run_ids)),
        "false_alarm_opportunity_rate_normal_holdout": _safe_div(confirmed_opportunities, opportunities),
        "normal_holdout_confirmed_opportunities": confirmed_opportunities,
        "normal_holdout_opportunities": opportunities,
    }


def _full_refresh_sequence_metrics(
    records: list[dict[str, Any]],
    run_ids: list[str],
    interval_minutes: int,
    window_samples: int,
    stride_samples: int,
) -> dict[str, Any]:
    by_run: dict[str, dict[str, Any]] = {}
    detected_runs = 0
    prefault_alarm_runs = 0
    prefault_confirmed_opportunities = 0
    prefault_opportunities = 0
    delays = []
    advances_required = full_window_refresh_advances(window_samples, stride_samples)

    for run_id in run_ids:
        run = sorted(
            (record for record in records if str(record["simulation_run_blind_id"]) == run_id),
            key=lambda record: (int(record["window_id"]), int(record["sample_end"])),
        )
        tracker = FullWindowRefreshTracker(window_samples, stride_samples, target=True)
        first_anomaly = next(
            (int(record["sample_end"]) for record in run if record.get("decision") == "ANOMALY"),
            None,
        )
        first_indication = None
        first_indication_window = None
        confirmed_alarm = None
        confirmation_window = None
        for index, record in enumerate(run):
            update = tracker.observe(int(record["window_id"]), str(record.get("decision")))
            if update.event == "FIRST_INDICATION" and first_indication is None:
                first_indication = int(record["sample_end"])
                first_indication_window = int(record["window_id"])
            if update.event == "CONFIRMED_DETECTION":
                confirmed_alarm = int(record["sample_end"])
                confirmation_window = int(record["window_id"])
                if index != len(run) - 1:
                    raise RuntimeError("TARGET LLM records continue after CONFIRMED_DETECTION")
        final_update = tracker.finalize()

        prefault_confirmed = confirmed_alarm is not None and confirmed_alarm < FAULT_ONSET_SAMPLE
        detected = confirmed_alarm is not None and confirmed_alarm >= FAULT_ONSET_SAMPLE
        delay_samples = confirmed_alarm - FAULT_ONSET_SAMPLE if detected else None
        delay_minutes = delay_samples * interval_minutes if delay_samples is not None else None
        if detected:
            detected_runs += 1
            delays.append(delay_minutes)
        if prefault_confirmed:
            prefault_alarm_runs += 1
            prefault_confirmed_opportunities += 1
        prefault_opportunities += sum(int(record["sample_end"]) < FAULT_ONSET_SAMPLE for record in run)
        by_run[run_id] = {
            "first_anomaly": first_anomaly,
            "first_indication": first_indication,
            "first_indication_window": first_indication_window,
            "first_prefault_confirmed_alarm": confirmed_alarm if prefault_confirmed else None,
            "confirmed_alarm": confirmed_alarm if detected else None,
            "confirmation_window": confirmation_window if detected else None,
            "detected": detected,
            "detection_state": final_update.detection_state,
            "detection_delay_samples": delay_samples,
            "detection_delay_minutes": delay_minutes,
        }

    total_runs = len(run_ids)
    return {
        "runs": total_runs,
        "detected_runs": detected_runs,
        "no_detection_runs": total_runs - detected_runs,
        "detection_rate": _safe_div(detected_runs, total_runs),
        "no_detection_rate": _safe_div(total_runs - detected_runs, total_runs),
        "false_alarm_runs_prefault": prefault_alarm_runs,
        "false_alarm_rate_prefault": _safe_div(prefault_alarm_runs, total_runs),
        "false_alarm_opportunity_rate_prefault": _safe_div(
            prefault_confirmed_opportunities, prefault_opportunities
        ),
        "prefault_confirmed_opportunities": prefault_confirmed_opportunities,
        "prefault_opportunities": prefault_opportunities,
        "verification_advances_required": advances_required,
        "detection_delay_minutes_detected_only": {
            "count": len(delays),
            "mean": float(np.mean(delays)) if delays else None,
            "median": float(np.median(delays)) if delays else None,
            "q25": float(np.quantile(delays, 0.25)) if delays else None,
            "q75": float(np.quantile(delays, 0.75)) if delays else None,
        },
        "by_run": by_run,
    }


def _normal_llm_false_alarm_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    run_ids = sorted({str(record["simulation_run_blind_id"]) for record in records})
    false_alarm_runs = 0
    anomaly_opportunities = 0
    opportunities = 0
    for run_id in run_ids:
        run = [record for record in records if str(record["simulation_run_blind_id"]) == run_id]
        anomalies = sum(record.get("decision") == "ANOMALY" for record in run)
        false_alarm_runs += anomalies > 0
        anomaly_opportunities += anomalies
        opportunities += len(run)
    return {
        "normal_holdout_runs": len(run_ids),
        "false_alarm_runs_normal_holdout": int(false_alarm_runs),
        "false_alarm_rate_normal_holdout": _safe_div(false_alarm_runs, len(run_ids)),
        "false_alarm_opportunity_rate_normal_holdout": _safe_div(
            anomaly_opportunities, opportunities
        ),
        "normal_holdout_anomaly_opportunities": anomaly_opportunities,
        "normal_holdout_opportunities": opportunities,
        "normal_holdout_confirmation_rule": "ANY_ANOMALY_FULL_TRAJECTORY_NO_EARLY_STOP",
    }


def _new_rule_name() -> str:
    return "FIRST_INDICATION_CONCURRENT_FULL_SAMPLE_REFRESH_V1"


def _claim_passes(claim: str, payload: dict[str, Any], threshold: dict[str, float]) -> bool:
    if claim == "HIGH":
        return float(payload["max_z"]) >= float(threshold["high_max_z_q99"])
    if claim == "LOW":
        return float(payload["min_z"]) <= float(threshold["low_min_z_q01"])
    if claim == "INCREASE":
        return (
            float(payload["slope_z_per_sample"]) >= float(threshold["increase_slope_q99"])
            and float(payload["end_z"]) > float(payload["start_z"])
        )
    if claim == "REDUCTION":
        return (
            float(payload["slope_z_per_sample"]) <= float(threshold["reduction_slope_q01"])
            and float(payload["end_z"]) < float(payload["start_z"])
        )
    if claim == "VARIABILITY":
        observed_range = round(float(payload["max_z"]) - float(payload["min_z"]), 4)
        return observed_range >= float(threshold["high_variability_range_q99"])
    raise ValueError(f"Unsupported evidence claim: {claim}")


def evaluate_h3(records: list[dict[str, Any]], threshold_reference: dict[str, Any]) -> dict[str, Any]:
    thresholds = threshold_reference["thresholds"]
    response_rows = []
    item_count = 0
    verifiable_count = 0
    for record in records:
        payload_variables = {
            item["variable"]: item for item in record.get("llm_payload", {}).get("variables", [])
        }
        item_scores = []
        details = []
        for evidence in record.get("evidence", []):
            item_count += 1
            variable = evidence.get("variable")
            claim = evidence.get("claim")
            variable_valid = variable in X_COLUMNS and variable in payload_variables and variable in thresholds
            claim_valid = claim in EVIDENCE_CLAIMS
            verifiable = variable_valid and claim_valid
            if verifiable:
                verifiable_count += 1
                score = int(_claim_passes(claim, payload_variables[variable], thresholds[variable]))
            else:
                score = 0
            item_scores.append(score)
            details.append({
                "variable": variable,
                "claim": claim,
                "variable_valid": variable_valid,
                "claim_valid": claim_valid,
                "score": score,
            })
        if item_scores:
            response_score = float(np.mean(item_scores))
        elif record.get("decision") == "ANOMALY":
            response_score = 0.0
        else:
            response_score = None
        response_rows.append({
            "blind_run_id": str(record["simulation_run_blind_id"]),
            "window_id": int(record["window_id"]),
            "response_score": response_score,
            "items": details,
        })

    run_scores = {}
    for run_id in sorted({row["blind_run_id"] for row in response_rows}):
        applicable = [row["response_score"] for row in response_rows if row["blind_run_id"] == run_id and row["response_score"] is not None]
        run_scores[run_id] = float(np.mean(applicable)) if applicable else None
    applicable_runs = [score for score in run_scores.values() if score is not None]
    return {
        "evidence_items": item_count,
        "verifiable_evidence_items": verifiable_count,
        "coverage": _safe_div(verifiable_count, item_count),
        "macro_run_coherence": float(np.mean(applicable_runs)) if applicable_runs else None,
        "applicable_runs": len(applicable_runs),
        "run_scores": run_scores,
        "responses": response_rows,
        "observation_text_used_for_primary_score": False,
    }


def evaluate_llm(
    records: list[dict[str, Any]],
    truth: pd.DataFrame,
    interval_minutes: int,
    threshold_reference: dict[str, Any],
    normal_holdout_records: list[dict[str, Any]] | None = None,
    window_samples: int = 20,
    stride_samples: int = 5,
) -> dict[str, Any]:
    run_ids = sorted(truth["blind_run_id"].astype(str).unique())
    confirmation = evaluate_confirmation_contract(
        records,
        run_ids,
        interval_minutes,
        window_samples,
        stride_samples,
        FAULT_ONSET_SAMPLE,
        normal_holdout_records,
    )
    h2 = confirmation["h2"]
    h2["abstention_count"] = sum(
        record.get("decision") == "EVIDENCE_INSUFFICIENT"
        for record in records
    )
    h2["abstention_rate"] = _safe_div(
        h2["abstention_count"], len(records)
    )
    return {
        "h1": confirmation["h1"],
        "h2": h2,
        "h3": evaluate_h3(records, threshold_reference),
    }


def evaluate_dpca(
    records: list[dict[str, Any]],
    truth: pd.DataFrame,
    interval_minutes: int,
    normal_holdout_records: list[dict[str, Any]] | None = None,
    persistence: int = 3,
) -> dict[str, Any]:
    run_ids = sorted(truth["blind_run_id"].astype(str).unique())
    eligible = lambda record: record.get("t2") is not None and record.get("spe") is not None
    sequence = _sequence_metrics(
        records, run_ids, "blind_run_id", "sample",
        lambda record: bool(record.get("alarm_raw")), persistence, interval_minutes, eligible,
    )
    for run_summary in sequence["by_run"].values():
        run_summary["first_raw_exceedance"] = run_summary.pop("first_positive")
    normal_metrics = (
        _normal_false_alarm_metrics(
            normal_holdout_records, "blind_run_id", "sample",
            lambda record: bool(record.get("alarm_raw")), persistence, eligible,
        )
        if normal_holdout_records is not None else {
            "normal_holdout_runs": 0,
            "false_alarm_runs_normal_holdout": None,
            "false_alarm_rate_normal_holdout": None,
            "false_alarm_opportunity_rate_normal_holdout": None,
            "status": "NORMAL_HOLDOUT_NOT_EVALUATED",
        }
    )
    return {
        "h1": {**{key: value for key, value in sequence.items() if key != "by_run"}, **normal_metrics},
        "h2": {
            "persistence": persistence,
            "fault_onset_sample": FAULT_ONSET_SAMPLE,
            "onset_reset": True,
            "by_run": sequence["by_run"],
        },
    }


def _read_checkpoint_records(results_dir: Path, artifact_name: str) -> list[dict[str, Any]]:
    records = []
    runs_root = results_dir / "runs"
    if not runs_root.exists():
        return records
    for marker_path in sorted(runs_root.glob("*/COMPLETE.json")):
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        manifest_path = results_dir / marker["run_manifest_relative_path"]
        if sha256_file(manifest_path) != marker["run_manifest_sha256"]:
            raise RuntimeError("Checkpoint manifest hash mismatch during evaluation")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifact = next((item for item in manifest["artifacts"] if item["name"] == artifact_name), None)
        if artifact is None:
            raise RuntimeError(f"Completed run lacks {artifact_name}")
        artifact_path = manifest_path.parent / artifact_name
        if sha256_file(artifact_path) != artifact["sha256"]:
            raise RuntimeError("Checkpoint artifact hash mismatch during evaluation")
        records.extend(read_jsonl(artifact_path))
    return records


def _read_results_records(results_dir: str | Path, artifact_name: str, legacy_relative: str) -> list[dict[str, Any]]:
    results_dir = Path(results_dir)
    checkpoint_records = _read_checkpoint_records(results_dir, artifact_name)
    if checkpoint_records:
        return checkpoint_records
    legacy = results_dir / legacy_relative
    return read_jsonl(legacy) if legacy.exists() else []


def evaluate_results(
    results_dir: str | Path,
    truth_dir: str | Path,
    config: dict[str, Any],
    selection_path: str | Path,
    normal_selection_path: str | Path,
    h3_reference_path: str | Path,
    normal_results_dir: str | Path | None = None,
    methodological_amendment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if methodological_amendment is None:
        raise RuntimeError("Formal LLM evaluation requires the post-freeze methodological amendment")
    rule = methodological_amendment["new_rule"]
    if rule.get("name") != _new_rule_name():
        raise RuntimeError("Unsupported LLM confirmation rule for formal evaluation")
    selection_config = config["run_selections"]["llm_target"]
    selection = load_run_selection(selection_path, selection_config["sha256"])
    normal_selection_config = config["run_selections"]["llm_normal_holdout"]
    normal_selection = load_run_selection(normal_selection_path, normal_selection_config["sha256"])
    source_truth = load_ground_truth(truth_dir)
    llm_truth = apply_selection_to_ground_truth(source_truth, selection)
    dpca_truth = apply_blind_mapping_to_ground_truth(source_truth, int(selection["seed"]))
    h3_reference = json.loads(Path(h3_reference_path).read_text(encoding="utf-8"))
    results_dir = Path(results_dir)
    llm_records = _read_results_records(results_dir / "llm", "llm_decisions.jsonl", "raw_llm/decisions.jsonl")
    dpca_records = _read_results_records(results_dir / "dpca", "dpca_metrics.jsonl", "raw_dpca/metrics.jsonl")
    if not llm_records:
        llm_records = _read_results_records(results_dir, "llm_decisions.jsonl", "raw_llm/decisions.jsonl")
    if not dpca_records:
        dpca_records = _read_results_records(results_dir, "dpca_metrics.jsonl", "raw_dpca/metrics.jsonl")
    expected_target_llm = {item["blind_run_id"] for item in selection["mapping"]}
    expected_target_dpca = {
        blind_id_for_run(run, int(selection["seed"])) for run in range(1, 501)
    }
    if {str(record["simulation_run_blind_id"]) for record in llm_records} != expected_target_llm:
        raise RuntimeError("Target LLM results do not match the frozen 50-run selection")
    if {str(record["blind_run_id"]) for record in dpca_records} != expected_target_dpca:
        raise RuntimeError("Target DPCA results do not match the frozen 500-run universe")
    normal_llm = normal_dpca = None
    if normal_results_dir is not None:
        normal_results_dir = Path(normal_results_dir)
        normal_llm = _read_results_records(normal_results_dir, "llm_decisions.jsonl", "raw_llm/decisions.jsonl")
        normal_dpca = _read_results_records(normal_results_dir, "dpca_metrics.jsonl", "raw_dpca/metrics.jsonl")
        expected_normal_llm = {item["blind_run_id"] for item in normal_selection["mapping"]}
        expected_normal_dpca = {
            blind_id_for_run(run, int(normal_selection["seed"])) for run in range(1, 501)
        }
        if {str(record["simulation_run_blind_id"]) for record in normal_llm} != expected_normal_llm:
            raise RuntimeError("Normal-holdout LLM results do not match the frozen 50-run selection")
        if {str(record["blind_run_id"]) for record in normal_dpca} != expected_normal_dpca:
            raise RuntimeError("Normal-holdout DPCA results do not match the frozen 500-run universe")
    output = {
        "status": config["status"],
        "scientific_inference_permitted": False,
        "fault_onset_sample": FAULT_ONSET_SAMPLE,
        "llm": evaluate_llm(
            llm_records, llm_truth, int(config["sample_interval_minutes"]), h3_reference,
            normal_llm, int(config["window_samples"]), int(config["stride_samples"]),
        ),
        "dpca": evaluate_dpca(
            dpca_records, dpca_truth, int(config["sample_interval_minutes"]), normal_dpca,
            int(config["dpca"]["alarm_persistence"]),
        ),
    }
    destination = results_dir / "evaluation" / "metrics.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return output

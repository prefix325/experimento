"""Frozen run-level endpoint and H3 rules for the formal SAP analysis."""

from __future__ import annotations

import math
from typing import Any

import numpy as np


FAULT_ONSET_SAMPLE = 161
INTERVAL_MINUTES = 3
WINDOW_SAMPLES = 20
STRIDE_SAMPLES = 5
VERIFICATION_ADVANCES = 4
THEORETICAL_WINDOWS = 189
DPCA_PERSISTENCE = 3
DECISIONS = {"NORMAL", "EVIDENCE_INSUFFICIENT", "ANOMALY"}
CLAIMS = {"HIGH", "LOW", "INCREASE", "REDUCTION", "VARIABILITY"}
VARIABLES = {*(f"xmeas_{index}" for index in range(1, 42)), *(f"xmv_{index}" for index in range(1, 12))}


def _optional_delay(sample: int | None) -> int | None:
    return None if sample is None else (sample - FAULT_ONSET_SAMPLE) * INTERVAL_MINUTES


def validate_llm_records(records: list[dict[str, Any]], *, cohort: str) -> list[dict[str, Any]]:
    """Validate and order a final LLM trajectory without mutating it."""
    if not records:
        raise ValueError("LLM trajectory is empty")
    ordered = sorted(records, key=lambda row: (int(row["sample_end"]), int(row["window_id"])))
    blind_ids = {str(row["simulation_run_blind_id"]) for row in ordered}
    if len(blind_ids) != 1:
        raise ValueError("LLM trajectory contains multiple blind_run_id values")
    for expected_window, row in enumerate(ordered):
        window_id = int(row["window_id"])
        sample_start = int(row["sample_start"])
        sample_end = int(row["sample_end"])
        if window_id != expected_window:
            raise ValueError("LLM window IDs are not unique and consecutive from zero")
        if sample_start != 1 + STRIDE_SAMPLES * window_id:
            raise ValueError("LLM sample_start does not match frozen grid")
        if sample_end != WINDOW_SAMPLES + STRIDE_SAMPLES * window_id:
            raise ValueError("LLM sample_end does not match frozen grid")
        if row.get("decision") not in DECISIONS:
            raise ValueError("LLM decision violates frozen enum")
    if len(ordered) > THEORETICAL_WINDOWS:
        raise ValueError("LLM trajectory exceeds theoretical maximum")
    if cohort == "normal_holdout" and len(ordered) != THEORETICAL_WINDOWS:
        raise ValueError("NORMAL HOLDOUT LLM trajectory must contain exactly 189 windows")
    return ordered


def full_refresh_segment(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Recompute concurrent k/k+4 candidates for one eligibility segment."""
    ordered = sorted(records, key=lambda row: (int(row["sample_end"]), int(row["window_id"])))
    by_window = {int(row["window_id"]): row for row in ordered}
    if len(by_window) != len(ordered):
        raise ValueError("Duplicate LLM window ID")
    anomaly_rows = [row for row in ordered if row["decision"] == "ANOMALY"]
    confirmation_pairs: list[tuple[int, int, int]] = []
    for row in anomaly_rows:
        candidate = int(row["window_id"])
        verifier = by_window.get(candidate + VERIFICATION_ADVANCES)
        if verifier is not None and verifier["decision"] == "ANOMALY":
            confirmation_pairs.append((int(verifier["sample_end"]), candidate, candidate + VERIFICATION_ADVANCES))
    confirmation_pairs.sort()
    first = anomaly_rows[0] if anomaly_rows else None
    confirmed = confirmation_pairs[0] if confirmation_pairs else None
    return {
        "raw": first is not None,
        "first_sample_end": int(first["sample_end"]) if first is not None else None,
        "first_window": int(first["window_id"]) if first is not None else None,
        "confirmed": confirmed is not None,
        "confirmation_sample_end": confirmed[0] if confirmed is not None else None,
        "confirmation_candidate_window": confirmed[1] if confirmed is not None else None,
        "confirmation_window": confirmed[2] if confirmed is not None else None,
        "confirmation_pairs": confirmation_pairs,
    }


def llm_run_endpoints(records: list[dict[str, Any]], *, cohort: str) -> dict[str, Any]:
    ordered = validate_llm_records(records, cohort=cohort)
    if cohort == "target":
        pre = full_refresh_segment([row for row in ordered if int(row["sample_end"]) <= 160])
        post = full_refresh_segment([row for row in ordered if int(row["sample_end"]) >= FAULT_ONSET_SAMPLE])
        if post["confirmed"]:
            if int(ordered[-1]["window_id"]) != int(post["confirmation_window"]):
                raise ValueError("TARGET LLM continued or stopped before the first valid confirmation")
        elif len(ordered) != THEORETICAL_WINDOWS:
            raise ValueError("Unconfirmed TARGET LLM trajectory ended before 189 windows")
        return {
            "llm_records": len(ordered),
            "llm_early_stop": bool(post["confirmed"]),
            "llm_raw_post_onset": bool(post["raw"]),
            "llm_confirmed_post_onset": bool(post["confirmed"]),
            "llm_first_indication_sample_end": post["first_sample_end"],
            "llm_confirmation_sample_end": post["confirmation_sample_end"],
            "llm_raw_delay_minutes": _optional_delay(post["first_sample_end"]),
            "llm_confirmed_delay_minutes": _optional_delay(post["confirmation_sample_end"]),
            "llm_raw_pre_onset": bool(pre["raw"]),
            "llm_confirmed_pre_onset": bool(pre["confirmed"]),
            "llm_first_indication_window": post["first_window"],
            "llm_confirmation_window": post["confirmation_window"],
            "llm_confirmation_candidate_window": post["confirmation_candidate_window"],
        }
    if cohort == "normal_holdout":
        full = full_refresh_segment(ordered)
        if any(bool(row.get("detection", {}).get("should_stop")) for row in ordered):
            raise ValueError("NORMAL HOLDOUT contains should_stop=true")
        return {
            "llm_records": len(ordered),
            "llm_early_stop": False,
            "llm_any_raw_false_alarm": bool(full["raw"]),
            "llm_any_confirmed_false_alarm": bool(full["confirmed"]),
            "llm_first_raw_false_alarm_sample_end": full["first_sample_end"],
            "llm_first_confirmed_false_alarm_sample_end": full["confirmation_sample_end"],
            "llm_first_raw_false_alarm_window": full["first_window"],
            "llm_first_confirmed_false_alarm_window": full["confirmation_window"],
        }
    raise ValueError(f"Unsupported cohort: {cohort}")


def _first_persistent(records: list[dict[str, Any]], persistence: int = DPCA_PERSISTENCE) -> int | None:
    streak = 0
    for row in records:
        streak = streak + 1 if bool(row["alarm_raw"]) else 0
        if streak >= persistence:
            return int(row["sample"])
    return None


def validate_dpca_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(records) != 960:
        raise ValueError("DPCA trajectory must contain exactly 960 samples")
    ordered = sorted(records, key=lambda row: int(row["sample"]))
    blind_ids = {str(row["blind_run_id"]) for row in ordered}
    if len(blind_ids) != 1:
        raise ValueError("DPCA trajectory contains multiple blind_run_id values")
    streak = 0
    for expected_sample, row in enumerate(ordered, start=1):
        if int(row["sample"]) != expected_sample:
            raise ValueError("DPCA samples are not unique and consecutive from one")
        streak = streak + 1 if bool(row["alarm_raw"]) else 0
        expected_persistent = streak >= DPCA_PERSISTENCE
        if bool(row["alarm_persistent"]) != expected_persistent:
            raise ValueError("Persisted DPCA alarm_persistent conflicts with frozen full-trajectory rule")
        if expected_sample <= 5 and (
            row.get("t2") is not None
            or row.get("spe") is not None
            or bool(row["alarm_raw"])
            or bool(row["alarm_persistent"])
        ):
            raise ValueError("DPCA lag warm-up samples violate frozen contract")
    return ordered


def dpca_run_endpoints(records: list[dict[str, Any]], *, cohort: str) -> dict[str, Any]:
    ordered = validate_dpca_records(records)
    if cohort == "target":
        pre = [row for row in ordered if int(row["sample"]) <= 160]
        post = [row for row in ordered if int(row["sample"]) >= FAULT_ONSET_SAMPLE]
        first_pre_raw = next((int(row["sample"]) for row in pre if bool(row["alarm_raw"])), None)
        first_post_raw = next((int(row["sample"]) for row in post if bool(row["alarm_raw"])), None)
        first_pre_persistent = _first_persistent(pre)
        first_post_persistent = _first_persistent(post)
        return {
            "dpca_records": len(ordered),
            "dpca_raw_post_onset": first_post_raw is not None,
            "dpca_confirmed_post_onset": first_post_persistent is not None,
            "dpca_first_raw_sample": first_post_raw,
            "dpca_first_persistent_sample": first_post_persistent,
            "dpca_raw_delay_minutes": _optional_delay(first_post_raw),
            "dpca_confirmed_delay_minutes": _optional_delay(first_post_persistent),
            "dpca_raw_pre_onset": first_pre_raw is not None,
            "dpca_confirmed_pre_onset": first_pre_persistent is not None,
            "dpca_first_raw_pre_onset_sample": first_pre_raw,
            "dpca_first_persistent_pre_onset_sample": first_pre_persistent,
        }
    if cohort == "normal_holdout":
        first_raw = next((int(row["sample"]) for row in ordered if bool(row["alarm_raw"])), None)
        first_persistent = _first_persistent(ordered)
        return {
            "dpca_records": len(ordered),
            "dpca_any_raw_false_alarm": first_raw is not None,
            "dpca_any_confirmed_false_alarm": first_persistent is not None,
            "dpca_first_raw_false_alarm_sample": first_raw,
            "dpca_first_confirmed_false_alarm_sample": first_persistent,
        }
    raise ValueError(f"Unsupported cohort: {cohort}")


def _claim_audit(
    claim: str,
    payload: dict[str, Any],
    threshold: dict[str, Any],
) -> dict[str, Any]:
    required = {"start_z", "end_z", "min_z", "max_z", "slope_z_per_sample"}
    if any(key not in payload or payload[key] is None for key in required):
        raise ValueError("Verifiable H3 payload lacks a required numeric statistic")
    try:
        values = {key: float(payload[key]) for key in required}
    except (TypeError, ValueError) as exc:
        raise ValueError("Verifiable H3 payload contains a non-numeric statistic") from exc
    if any(not math.isfinite(value) for value in values.values()):
        raise ValueError("Verifiable H3 payload contains a non-finite statistic")
    direction_pass: bool | None = None
    if claim == "HIGH":
        observed = values["max_z"]
        threshold_value = float(threshold["high_max_z_q99"])
        comparator = ">="
        passes = observed >= threshold_value
    elif claim == "LOW":
        observed = values["min_z"]
        threshold_value = float(threshold["low_min_z_q01"])
        comparator = "<="
        passes = observed <= threshold_value
    elif claim == "INCREASE":
        observed = values["slope_z_per_sample"]
        threshold_value = float(threshold["increase_slope_q99"])
        comparator = ">= AND end_z > start_z"
        direction_pass = values["end_z"] > values["start_z"]
        passes = observed >= threshold_value and direction_pass
    elif claim == "REDUCTION":
        observed = values["slope_z_per_sample"]
        threshold_value = float(threshold["reduction_slope_q01"])
        comparator = "<= AND end_z < start_z"
        direction_pass = values["end_z"] < values["start_z"]
        passes = observed <= threshold_value and direction_pass
    elif claim == "VARIABILITY":
        observed = round(values["max_z"] - values["min_z"], 4)
        threshold_value = float(threshold["high_variability_range_q99"])
        comparator = ">="
        passes = observed >= threshold_value
    else:
        raise ValueError(f"Unsupported claim: {claim}")
    return {
        "observed_primary": observed,
        "threshold": threshold_value,
        "comparator": comparator,
        "endpoint_direction_pass": direction_pass,
        "numeric_rule_pass": bool(passes),
        **values,
    }


def score_h3_run(
    records: list[dict[str, Any]],
    thresholds: dict[str, Any],
    *,
    simulation_run: int,
    blind_run_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return one run-level H3 row and a response/item audit table."""
    response_scores: list[float] = []
    audit_rows: list[dict[str, Any]] = []
    evidence_items = 0
    verifiable_items = 0
    passing_items = 0
    for record in records:
        payload_items = record.get("llm_payload", {}).get("variables", [])
        payload_map = {item.get("variable"): item for item in payload_items}
        evidence = record.get("evidence", [])
        if not isinstance(evidence, list):
            raise ValueError("H3 evidence must be a list")
        item_scores: list[int] = []
        pending_rows: list[dict[str, Any]] = []
        for evidence_index, item in enumerate(evidence):
            evidence_items += 1
            variable = item.get("variable")
            claim = item.get("claim")
            variable_valid = variable in VARIABLES and variable in payload_map and variable in thresholds
            claim_valid = claim in CLAIMS
            verifiable = bool(variable_valid and claim_valid)
            claim_details: dict[str, Any] = {
                "observed_primary": None,
                "threshold": None,
                "comparator": None,
                "endpoint_direction_pass": None,
                "numeric_rule_pass": False,
                "start_z": None,
                "end_z": None,
                "min_z": None,
                "max_z": None,
                "slope_z_per_sample": None,
            }
            if verifiable:
                verifiable_items += 1
                claim_details = _claim_audit(str(claim), payload_map[variable], thresholds[variable])
            score = int(verifiable and claim_details["numeric_rule_pass"])
            passing_items += score
            item_scores.append(score)
            pending_rows.append(
                {
                    "evidence_index": evidence_index,
                    "variable": variable,
                    "claim": claim,
                    "observation": item.get("observation"),
                    "variable_valid": bool(variable_valid),
                    "claim_valid": bool(claim_valid),
                    "numerically_verifiable": verifiable,
                    "item_score": score,
                    **claim_details,
                }
            )
        decision = str(record["decision"])
        if item_scores:
            response_score: float | None = float(np.mean(item_scores))
        elif decision == "ANOMALY":
            response_score = 0.0
        else:
            response_score = None
        if response_score is not None:
            response_scores.append(response_score)
        base = {
            "simulationRun": simulation_run,
            "blind_run_id": blind_run_id,
            "window_id": int(record["window_id"]),
            "sample_start": int(record["sample_start"]),
            "sample_end": int(record["sample_end"]),
            "decision": decision,
            "summary": record.get("summary"),
            "response_applicable": response_score is not None,
            "response_score": response_score,
            "unsupported_process_claim": None,
            "unsupported_process_claim_review_status": "NOT_CODED_NO_FROZEN_RULE",
        }
        if pending_rows:
            audit_rows.extend([{**base, **row} for row in pending_rows])
        else:
            audit_rows.append(
                {
                    **base,
                    "evidence_index": None,
                    "variable": None,
                    "claim": None,
                    "observation": None,
                    "variable_valid": None,
                    "claim_valid": None,
                    "numerically_verifiable": None,
                    "item_score": None,
                    "observed_primary": None,
                    "threshold": None,
                    "comparator": None,
                    "endpoint_direction_pass": None,
                    "numeric_rule_pass": None,
                    "start_z": None,
                    "end_z": None,
                    "min_z": None,
                    "max_z": None,
                    "slope_z_per_sample": None,
                }
            )
    run_score = float(np.mean(response_scores)) if response_scores else None
    return (
        {
            "simulationRun": simulation_run,
            "blind_run_id": blind_run_id,
            "h3_run_score": run_score,
            "h3_applicable_responses": len(response_scores),
            "h3_evidence_items": evidence_items,
            "h3_verifiable_evidence_items": verifiable_items,
            "h3_passing_evidence_items": passing_items,
            "h3_coverage": (verifiable_items / evidence_items) if evidence_items else None,
        },
        audit_rows,
    )

"""Aggregate Calculation 2 strictly from the materialized run-level table."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

import statistics_independent as stats


BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20_260_820


@dataclass
class AggregateBundle:
    h1_target: pd.DataFrame
    normal_holdout: pd.DataFrame
    target_preonset: pd.DataFrame
    h2_delays: pd.DataFrame
    paired_binary: pd.DataFrame
    paired_delays: pd.DataFrame
    dpca_expanded: pd.DataFrame
    h3_statistics: dict[str, Any]
    primary_statistics: dict[str, Any]
    reconciliation_keys: dict[str, Any]
    bootstrap_audit: list[dict[str, Any]]


def _as_bool(series: pd.Series) -> np.ndarray:
    if series.isna().any():
        raise ValueError(f"Missing binary values in {series.name}")
    values = series.astype(bool).to_numpy()
    return values


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return frame.where(pd.notna(frame), None).to_dict(orient="records")


def _proportion_row(
    frame: pd.DataFrame,
    *,
    cohort: str,
    detector: str,
    analysis_set: str,
    endpoint: str,
    column: str,
    interpretation: str,
) -> dict[str, Any]:
    values = _as_bool(frame[column])
    summary = stats.proportion_summary(int(values.sum()), int(values.size))
    extreme = bool(summary["extreme_count"])
    return {
        "cohort": cohort,
        "detector": detector,
        "analysis_set": analysis_set,
        "endpoint": endpoint,
        "events": summary["events"],
        "denominator": summary["denominator"],
        "proportion": summary["proportion"],
        "wilson_95_lower": summary["wilson"]["lower"],
        "wilson_95_upper": summary["wilson"]["upper"],
        "clopper_pearson_sensitivity_reported": extreme,
        "clopper_pearson_95_lower": summary["clopper_pearson"]["lower"] if extreme else None,
        "clopper_pearson_95_upper": summary["clopper_pearson"]["upper"] if extreme else None,
        "interval_interpretation": interpretation,
    }


def _analysis_sets(run_level: pd.DataFrame, cohort: str) -> dict[str, pd.DataFrame]:
    cohort_rows = run_level.loc[run_level["cohort"] == cohort].copy()
    selected = cohort_rows.loc[cohort_rows["llm_selected"].astype(bool)].copy()
    paired = cohort_rows.loc[cohort_rows["dpca_paired_selected"].astype(bool)].copy()
    if len(selected) != 50 or len(paired) != 50 or len(cohort_rows) != 500:
        raise ValueError(f"Run-level denominators are invalid for {cohort}")
    if selected["simulationRun"].tolist() != paired["simulationRun"].tolist():
        raise ValueError(f"LLM and DPCA paired simulationRuns differ for {cohort}")
    return {"all": cohort_rows, "llm": selected, "paired": paired}


def _build_endpoint_table(run_level: pd.DataFrame, cohort: str) -> pd.DataFrame:
    sets = _analysis_sets(run_level, cohort)
    rows: list[dict[str, Any]] = []
    group_specs = [
        ("LLM", "llm_50", sets["llm"], "llm"),
        ("DPCA", "dpca_paired_50", sets["paired"], "dpca"),
        ("DPCA", "dpca_expanded_500", sets["all"], "dpca"),
    ]
    endpoint_specs = [
        ("raw_indication", "raw_endpoint"),
        ("confirmed_detection" if cohort == "target" else "confirmed_false_alarm", "confirmed_endpoint"),
        ("no_confirmation", "no_confirmation"),
    ]
    for detector, analysis_set, frame, prefix in group_specs:
        interpretation = (
            "model-based extrapolation for analogous trajectories"
            if analysis_set == "dpca_expanded_500"
            else "Wilson estimation interval for the specified run regime"
        )
        for endpoint, suffix in endpoint_specs:
            rows.append(
                _proportion_row(
                    frame,
                    cohort=cohort,
                    detector=detector,
                    analysis_set=analysis_set,
                    endpoint=endpoint,
                    column=f"{prefix}_{suffix}",
                    interpretation=interpretation,
                )
            )
    return pd.DataFrame(rows)


def _build_preonset(run_level: pd.DataFrame) -> pd.DataFrame:
    sets = _analysis_sets(run_level, "target")
    rows: list[dict[str, Any]] = []
    groups = [
        ("LLM", "llm_50", sets["llm"], "llm"),
        ("DPCA", "dpca_paired_50", sets["paired"], "dpca"),
        ("DPCA", "dpca_expanded_500", sets["all"], "dpca"),
    ]
    for detector, analysis_set, frame, prefix in groups:
        interpretation = (
            "model-based extrapolation for analogous trajectories"
            if analysis_set == "dpca_expanded_500"
            else "Wilson estimation interval for the specified run regime"
        )
        for endpoint, suffix in (
            ("raw_prefault_false_alarm", "prefault_raw"),
            ("confirmed_prefault_false_alarm", "prefault_confirmed"),
        ):
            rows.append(
                _proportion_row(
                    frame,
                    cohort="target_prefault_samples_1_160",
                    detector=detector,
                    analysis_set=analysis_set,
                    endpoint=endpoint,
                    column=f"{prefix}_{suffix}",
                    interpretation=interpretation,
                )
            )
    return pd.DataFrame(rows)


def _delay_row(
    frame: pd.DataFrame,
    *,
    detector: str,
    analysis_set: str,
    endpoint: str,
    detected_column: str,
    delay_column: str,
    bootstrap_audit: list[dict[str, Any]],
) -> dict[str, Any]:
    detected = _as_bool(frame[detected_column])
    delays = frame.loc[detected, delay_column]
    if delays.isna().any():
        raise ValueError(f"Detected runs contain null delays for {detector} {endpoint}")
    undefined = frame.loc[~detected, delay_column]
    if undefined.notna().any():
        raise ValueError(f"Non-detected runs contain defined delays for {detector} {endpoint}")
    values = delays.astype(float).to_numpy()
    if np.any(values < 0):
        raise ValueError(f"Negative delay for {detector} {endpoint}")
    descriptive = stats.summarize_numeric(values)
    mean_ci = stats.bootstrap_interval(
        values,
        np.mean,
        resamples=BOOTSTRAP_RESAMPLES,
        seed=BOOTSTRAP_SEED,
        method="bca",
    )
    median_ci = stats.bootstrap_interval(
        values,
        np.median,
        resamples=BOOTSTRAP_RESAMPLES,
        seed=BOOTSTRAP_SEED,
        method="bca",
    )
    bootstrap_audit.extend(
        [
            {"analysis": f"delay:{analysis_set}:{endpoint}:mean", **mean_ci},
            {"analysis": f"delay:{analysis_set}:{endpoint}:median", **median_ci},
        ]
    )
    return {
        "cohort": "target",
        "detector": detector,
        "analysis_set": analysis_set,
        "endpoint": endpoint,
        "total_runs": int(len(frame)),
        "detected_runs": int(detected.sum()),
        "conditional_delay_n": descriptive["n"],
        "mean_minutes": descriptive["mean"],
        "sample_sd_minutes": descriptive["sd"],
        "median_minutes": descriptive["median"],
        "q1_minutes": descriptive["q1"],
        "q3_minutes": descriptive["q3"],
        "iqr_minutes": descriptive["iqr"],
        "min_minutes": descriptive["min"],
        "max_minutes": descriptive["max"],
        "interval_interpretation": (
            "model-based extrapolation for analogous trajectories"
            if analysis_set == "dpca_expanded_500"
            else "conditional run-level estimation in the frozen corpus"
        ),
        "mean_bootstrap_95_lower": mean_ci["ci_lower"],
        "mean_bootstrap_95_upper": mean_ci["ci_upper"],
        "mean_bootstrap_method": mean_ci["method_used"],
        "mean_bootstrap_fallback_reason": mean_ci["fallback_reason"],
        "median_bootstrap_95_lower": median_ci["ci_lower"],
        "median_bootstrap_95_upper": median_ci["ci_upper"],
        "median_bootstrap_method": median_ci["method_used"],
        "median_bootstrap_fallback_reason": median_ci["fallback_reason"],
    }


def _build_delays(
    run_level: pd.DataFrame, bootstrap_audit: list[dict[str, Any]]
) -> pd.DataFrame:
    sets = _analysis_sets(run_level, "target")
    rows: list[dict[str, Any]] = []
    for detector, analysis_set, frame, prefix in (
        ("LLM", "llm_50", sets["llm"], "llm"),
        ("DPCA", "dpca_paired_50", sets["paired"], "dpca"),
        ("DPCA", "dpca_expanded_500", sets["all"], "dpca"),
    ):
        for endpoint, suffix in (("raw_indication", "raw"), ("confirmed_detection", "confirmed")):
            rows.append(
                _delay_row(
                    frame,
                    detector=detector,
                    analysis_set=analysis_set,
                    endpoint=endpoint,
                    detected_column=f"{prefix}_{suffix}_endpoint",
                    delay_column=f"{prefix}_{suffix}_delay_minutes",
                    bootstrap_audit=bootstrap_audit,
                )
            )
    return pd.DataFrame(rows)


def _build_paired_binary(
    run_level: pd.DataFrame, bootstrap_audit: list[dict[str, Any]]
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for cohort, endpoint_name in (
        ("target", "confirmed_detection"),
        ("normal_holdout", "confirmed_false_alarm"),
    ):
        paired = _analysis_sets(run_level, cohort)["paired"]
        llm = _as_bool(paired["llm_confirmed_endpoint"])
        dpca = _as_bool(paired["dpca_confirmed_endpoint"])
        analysis = stats.paired_binary_analysis(
            llm,
            dpca,
            resamples=BOOTSTRAP_RESAMPLES,
            seed=BOOTSTRAP_SEED,
            bootstrap_method="bca",
        )
        bootstrap_audit.append(
            {"analysis": f"paired_binary:{cohort}:{endpoint_name}", **analysis["bootstrap"]}
        )
        rows.append(
            {
                "cohort": cohort,
                "endpoint": endpoint_name,
                "pairs": analysis["pairs"],
                "00_neither": analysis["00"],
                "01_dpca_only": analysis["01"],
                "10_llm_only": analysis["10"],
                "11_both": analysis["11"],
                "concordant_pairs": analysis["00"] + analysis["11"],
                "discordant_pairs": analysis["01"] + analysis["10"],
                "paired_difference_llm_minus_dpca": analysis["paired_difference"],
                "paired_bootstrap_95_lower": analysis["bootstrap"]["ci_lower"],
                "paired_bootstrap_95_upper": analysis["bootstrap"]["ci_upper"],
                "paired_bootstrap_method": analysis["bootstrap"]["method_used"],
                "paired_bootstrap_fallback_reason": analysis["bootstrap"]["fallback_reason"],
                "mcnemar_exact_raw_p": analysis["mcnemar"]["p_value"],
                "mcnemar_zero_discordance": analysis["mcnemar"]["zero_discordance"],
            }
        )
    holm = stats.holm_adjust(
        {row["cohort"]: row["mcnemar_exact_raw_p"] for row in rows}
    )
    holm_by_name = {item["hypothesis"]: item for item in holm}
    for row in rows:
        adjustment = holm_by_name[row["cohort"]]
        row["holm_rank"] = adjustment["rank"]
        row["holm_multiplier"] = adjustment["multiplier"]
        row["holm_adjusted_p"] = adjustment["adjusted_p"]
    return pd.DataFrame(rows)


def _build_paired_delays(
    run_level: pd.DataFrame, bootstrap_audit: list[dict[str, Any]]
) -> pd.DataFrame:
    paired = _analysis_sets(run_level, "target")["paired"]
    rows: list[dict[str, Any]] = []
    for endpoint, suffix in (("raw_indication", "raw"), ("confirmed_detection", "confirmed")):
        llm_detected = _as_bool(paired[f"llm_{suffix}_endpoint"])
        dpca_detected = _as_bool(paired[f"dpca_{suffix}_endpoint"])
        neither = (~llm_detected) & (~dpca_detected)
        llm_only = llm_detected & (~dpca_detected)
        dpca_only = (~llm_detected) & dpca_detected
        both = llm_detected & dpca_detected
        llm_delays = paired.loc[both, f"llm_{suffix}_delay_minutes"].astype(float).to_numpy()
        dpca_delays = paired.loc[both, f"dpca_{suffix}_delay_minutes"].astype(float).to_numpy()
        if not np.all(np.isfinite(llm_delays)) or not np.all(np.isfinite(dpca_delays)):
            raise ValueError(f"Undefined paired delays in both-detected set: {endpoint}")
        differences = llm_delays - dpca_delays
        descriptive = stats.summarize_numeric(differences)
        mean_ci = stats.paired_bootstrap_interval(
            llm_delays,
            dpca_delays,
            np.mean,
            resamples=BOOTSTRAP_RESAMPLES,
            seed=BOOTSTRAP_SEED,
            method="bca",
        )
        median_ci = stats.paired_bootstrap_interval(
            llm_delays,
            dpca_delays,
            np.median,
            resamples=BOOTSTRAP_RESAMPLES,
            seed=BOOTSTRAP_SEED,
            method="bca",
        )
        sign = stats.sign_test_exact(differences)
        bootstrap_audit.extend(
            [
                {"analysis": f"paired_delay:{endpoint}:mean", **mean_ci},
                {"analysis": f"paired_delay:{endpoint}:median", **median_ci},
            ]
        )
        rows.append(
            {
                "cohort": "target",
                "endpoint": endpoint,
                "total_pairs": int(len(paired)),
                "neither_detected": int(neither.sum()),
                "llm_only": int(llm_only.sum()),
                "dpca_only": int(dpca_only.sum()),
                "both_detected": int(both.sum()),
                "pairs_with_both_delays": descriptive["n"],
                "difference_direction": "LLM - DPCA minutes",
                "mean_difference_minutes": descriptive["mean"],
                "sample_sd_difference_minutes": descriptive["sd"],
                "median_difference_minutes": descriptive["median"],
                "q1_difference_minutes": descriptive["q1"],
                "q3_difference_minutes": descriptive["q3"],
                "iqr_difference_minutes": descriptive["iqr"],
                "min_difference_minutes": descriptive["min"],
                "max_difference_minutes": descriptive["max"],
                "mean_bootstrap_95_lower": mean_ci["ci_lower"],
                "mean_bootstrap_95_upper": mean_ci["ci_upper"],
                "mean_bootstrap_method": mean_ci["method_used"],
                "mean_bootstrap_fallback_reason": mean_ci["fallback_reason"],
                "median_bootstrap_95_lower": median_ci["ci_lower"],
                "median_bootstrap_95_upper": median_ci["ci_upper"],
                "median_bootstrap_method": median_ci["method_used"],
                "median_bootstrap_fallback_reason": median_ci["fallback_reason"],
                "sign_positive": sign["positive"],
                "sign_negative": sign["negative"],
                "sign_ties": sign["ties"],
                "sign_binomial_n": sign["binomial_n"],
                "sign_exact_raw_p": sign["p_value"],
            }
        )
    family_name = "paired_delay_sign_tests_secondary"
    holm = stats.holm_adjust(
        {row["endpoint"]: row["sign_exact_raw_p"] for row in rows}
    )
    holm_by_endpoint = {item["hypothesis"]: item for item in holm}
    for row in rows:
        adjustment = holm_by_endpoint[row["endpoint"]]
        row["sign_holm_family"] = family_name
        row["sign_holm_rank"] = adjustment["rank"]
        row["sign_holm_multiplier"] = adjustment["multiplier"]
        row["sign_holm_adjusted_p"] = adjustment["adjusted_p"]
    return pd.DataFrame(rows)


def _build_h3(
    run_level: pd.DataFrame, bootstrap_audit: list[dict[str, Any]]
) -> dict[str, Any]:
    target = _analysis_sets(run_level, "target")["llm"]
    total_items = int(target["h3_total_items"].sum())
    verifiable = int(target["h3_verifiable_items"].sum())
    passed = int(target["h3_passed_items"].sum())
    applicable_responses = int(target["h3_applicable_responses"].sum())
    total_responses = int(target["h3_total_responses"].sum())
    scores = target["h3_run_score"].dropna().astype(float).to_numpy()
    descriptive = stats.summarize_numeric(scores)
    macro_ci = stats.bootstrap_interval(
        scores,
        np.mean,
        resamples=BOOTSTRAP_RESAMPLES,
        seed=BOOTSTRAP_SEED,
        method="bca",
    )
    bootstrap_audit.append({"analysis": "h3:macro_run_score_mean", **macro_ci})
    return {
        "scope": "50 TARGET LLM simulationRuns",
        "total_evidence_items": total_items,
        "verifiable_evidence_items": verifiable,
        "coverage": None if total_items == 0 else verifiable / total_items,
        "passed_evidence_items": passed,
        "micro_evidence_score_secondary": None if total_items == 0 else passed / total_items,
        "total_responses": total_responses,
        "applicable_responses": applicable_responses,
        "non_applicable_responses": total_responses - applicable_responses,
        "applicable_runs": descriptive["n"],
        "non_applicable_runs": int(len(target) - descriptive["n"]),
        "run_score_distribution": {
            "mean_macro": descriptive["mean"],
            "sample_sd": descriptive["sd"],
            "median": descriptive["median"],
            "q1": descriptive["q1"],
            "q3": descriptive["q3"],
            "iqr": descriptive["iqr"],
            "min": descriptive["min"],
            "max": descriptive["max"],
        },
        "macro_mean_bootstrap_95": {
            "lower": macro_ci["ci_lower"],
            "upper": macro_ci["ci_upper"],
            "method": macro_ci["method_used"],
            "fallback_reason": macro_ci["fallback_reason"],
            "resamples": macro_ci["resamples"],
            "seed": macro_ci["seed"],
        },
        "unsupported_process_claims": {
            "classified": False,
            "reason": "No frozen codebook; observation text excluded from primary score",
        },
    }


def _pick(frame: pd.DataFrame, **filters: Any) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    for column, value in filters.items():
        mask &= frame[column] == value
    selected = frame.loc[mask]
    if len(selected) != 1:
        raise ValueError(f"Expected one row for {filters}, found {len(selected)}")
    return selected.iloc[0]


def _reconciliation(
    h1: pd.DataFrame,
    normal: pd.DataFrame,
    pre: pd.DataFrame,
    delays: pd.DataFrame,
    paired_binary: pd.DataFrame,
    paired_delays: pd.DataFrame,
    h3: dict[str, Any],
) -> dict[str, Any]:
    def count(table: pd.DataFrame, analysis_set: str, endpoint: str) -> int:
        return int(_pick(table, analysis_set=analysis_set, endpoint=endpoint)["events"])

    def delay(analysis_set: str, endpoint: str, statistic: str) -> float | None:
        value = _pick(delays, analysis_set=analysis_set, endpoint=endpoint)[
            f"{statistic}_minutes"
        ]
        return None if pd.isna(value) else float(value)

    target_pair = _pick(paired_binary, cohort="target")
    normal_pair = _pick(paired_binary, cohort="normal_holdout")
    confirmed_delay = _pick(paired_delays, endpoint="confirmed_detection")
    return {
        "target_llm_raw_count": count(h1, "llm_50", "raw_indication"),
        "target_llm_confirmed_count": count(h1, "llm_50", "confirmed_detection"),
        "target_dpca_paired_raw_count": count(h1, "dpca_paired_50", "raw_indication"),
        "target_dpca_paired_confirmed_count": count(h1, "dpca_paired_50", "confirmed_detection"),
        "normal_llm_raw_fa_count": count(normal, "llm_50", "raw_indication"),
        "normal_llm_confirmed_fa_count": count(normal, "llm_50", "confirmed_false_alarm"),
        "normal_dpca_paired_raw_fa_count": count(normal, "dpca_paired_50", "raw_indication"),
        "normal_dpca_paired_confirmed_fa_count": count(normal, "dpca_paired_50", "confirmed_false_alarm"),
        "target_prefault_llm_raw_count": count(pre, "llm_50", "raw_prefault_false_alarm"),
        "target_prefault_llm_confirmed_count": count(pre, "llm_50", "confirmed_prefault_false_alarm"),
        "target_prefault_dpca_paired_raw_count": count(pre, "dpca_paired_50", "raw_prefault_false_alarm"),
        "target_prefault_dpca_paired_confirmed_count": count(pre, "dpca_paired_50", "confirmed_prefault_false_alarm"),
        "llm_raw_delay_mean": delay("llm_50", "raw_indication", "mean"),
        "llm_raw_delay_median": delay("llm_50", "raw_indication", "median"),
        "llm_confirmed_delay_mean": delay("llm_50", "confirmed_detection", "mean"),
        "llm_confirmed_delay_median": delay("llm_50", "confirmed_detection", "median"),
        "dpca_paired_raw_delay_mean": delay("dpca_paired_50", "raw_indication", "mean"),
        "dpca_paired_raw_delay_median": delay("dpca_paired_50", "raw_indication", "median"),
        "dpca_paired_confirmed_delay_mean": delay("dpca_paired_50", "confirmed_detection", "mean"),
        "dpca_paired_confirmed_delay_median": delay("dpca_paired_50", "confirmed_detection", "median"),
        "target_paired_00": int(target_pair["00_neither"]),
        "target_paired_01": int(target_pair["01_dpca_only"]),
        "target_paired_10": int(target_pair["10_llm_only"]),
        "target_paired_11": int(target_pair["11_both"]),
        "normal_paired_00": int(normal_pair["00_neither"]),
        "normal_paired_01": int(normal_pair["01_dpca_only"]),
        "normal_paired_10": int(normal_pair["10_llm_only"]),
        "normal_paired_11": int(normal_pair["11_both"]),
        "normal_paired_difference": float(normal_pair["paired_difference_llm_minus_dpca"]),
        "normal_mcnemar_raw_p": float(normal_pair["mcnemar_exact_raw_p"]),
        "paired_confirmed_delay_mean_difference": None if pd.isna(confirmed_delay["mean_difference_minutes"]) else float(confirmed_delay["mean_difference_minutes"]),
        "paired_confirmed_delay_median_difference": None if pd.isna(confirmed_delay["median_difference_minutes"]) else float(confirmed_delay["median_difference_minutes"]),
        "paired_confirmed_sign_positive": int(confirmed_delay["sign_positive"]),
        "paired_confirmed_sign_negative": int(confirmed_delay["sign_negative"]),
        "paired_confirmed_sign_ties": int(confirmed_delay["sign_ties"]),
        "h3_total_items": h3["total_evidence_items"],
        "h3_verifiable_items": h3["verifiable_evidence_items"],
        "h3_coverage": h3["coverage"],
        "h3_applicable_responses": h3["applicable_responses"],
        "h3_applicable_runs": h3["applicable_runs"],
        "h3_macro_mean": h3["run_score_distribution"]["mean_macro"],
        "h3_median": h3["run_score_distribution"]["median"],
        "h3_micro_score": h3["micro_evidence_score_secondary"],
        "dpca_expanded_target_confirmed_count": count(h1, "dpca_expanded_500", "confirmed_detection"),
        "dpca_expanded_normal_confirmed_fa_count": count(normal, "dpca_expanded_500", "confirmed_false_alarm"),
    }


def aggregate_from_run_level(run_level: pd.DataFrame) -> AggregateBundle:
    """Calculate every aggregate only after the 1,000-row table exists."""

    required_pairs = run_level[["cohort", "simulationRun"]]
    if len(run_level) != 1000 or required_pairs.duplicated().any():
        raise ValueError("Run-level table must contain 1,000 unique cohort/run rows")
    bootstrap_audit: list[dict[str, Any]] = []
    h1_target = _build_endpoint_table(run_level, "target")
    normal_holdout = _build_endpoint_table(run_level, "normal_holdout")
    target_preonset = _build_preonset(run_level)
    h2_delays = _build_delays(run_level, bootstrap_audit)
    paired_binary = _build_paired_binary(run_level, bootstrap_audit)
    paired_delays = _build_paired_delays(run_level, bootstrap_audit)
    h3_statistics = _build_h3(run_level, bootstrap_audit)
    dpca_expanded = pd.concat(
        [
            h1_target.loc[h1_target["analysis_set"] == "dpca_expanded_500"],
            normal_holdout.loc[normal_holdout["analysis_set"] == "dpca_expanded_500"],
        ],
        ignore_index=True,
    )
    primary_statistics = {
        "h1_target": _records(h1_target),
        "normal_holdout": _records(normal_holdout),
        "paired_binary_primary_family": _records(paired_binary),
        "multiplicity": {
            "method": "Holm step-down",
            "family": [
                "TARGET confirmed detection LLM vs DPCA",
                "NORMAL HOLDOUT confirmed false alarm LLM vs DPCA",
            ],
            "secondary_families": {
                "paired_delay_sign_tests_secondary": [
                    {
                        "endpoint": row["endpoint"],
                        "raw_p": row["sign_exact_raw_p"],
                        "rank": row["sign_holm_rank"],
                        "multiplier": row["sign_holm_multiplier"],
                        "adjusted_p": row["sign_holm_adjusted_p"],
                    }
                    for row in _records(paired_delays)
                ]
            },
        },
    }
    reconciliation = _reconciliation(
        h1_target,
        normal_holdout,
        target_preonset,
        h2_delays,
        paired_binary,
        paired_delays,
        h3_statistics,
    )
    return AggregateBundle(
        h1_target=h1_target,
        normal_holdout=normal_holdout,
        target_preonset=target_preonset,
        h2_delays=h2_delays,
        paired_binary=paired_binary,
        paired_delays=paired_delays,
        dpca_expanded=dpca_expanded,
        h3_statistics=h3_statistics,
        primary_statistics=primary_statistics,
        reconciliation_keys=reconciliation,
        bootstrap_audit=bootstrap_audit,
    )


__all__ = ["AggregateBundle", "aggregate_from_run_level"]

"""Run Calculation 2 from frozen primary JSONL to audited outputs."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import scipy

from aggregate_independent import aggregate_from_run_level
from calculate_endpoints import (
    DPCAEndpoint,
    LLMEndpoint,
    crosscheck_native_flags,
    reconstruct_dpca_endpoint,
    reconstruct_llm_endpoint,
)
from h3_independent import score_h3_run
from integrity_independent import (
    BRANCH,
    MANIFEST_SHA256,
    METHOD_FREEZE,
    SAP_BLOB,
    SAP_SHA256,
    SOURCE_COMMIT,
    audit_integrity,
    validate_snapshot_unchanged,
)


BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20_260_820
ONSET = 161
LAST_SAMPLE = 960
BASE_AMENDMENT_RUNS = {14, 23, 24, 26, 27, 55}


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if value is pd.NA:
        return None
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            _clean(value),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_frame(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(
        path,
        index=False,
        encoding="utf-8",
        lineterminator="\n",
        float_format="%.17g",
    )
    round_trip = pd.read_csv(path)
    if list(round_trip.columns) != list(frame.columns) or len(round_trip) != len(frame):
        raise RuntimeError(f"CSV round-trip validation failed: {path}")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"Expected JSON object at {path}:{line_number}")
            rows.append(value)
    return rows


def _component_path(root: Path, row: dict[str, Any], component: str, name: str) -> Path:
    attempt = row[f"{component}_scientific_attempt"]
    return (
        root
        / "results/formal"
        / METHOD_FREEZE
        / row["cohort"]
        / component
        / "runs"
        / row["blind_run_id"]
        / "attempts"
        / str(attempt)
        / name
    )


def _llm_summary_crosscheck(
    endpoint: LLMEndpoint,
    summary: dict[str, Any],
    *,
    cohort: str,
    simulation_run: int,
) -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []

    def compare(field: str, reconstructed: Any, persisted: Any) -> None:
        if reconstructed != persisted:
            mismatches.append(
                {"field": field, "reconstructed": reconstructed, "persisted": persisted}
            )

    persisted_raw = summary.get("first_indication_status") == "FIRST_INDICATION"
    persisted_confirmed = (
        summary.get("confirmed_detection_status") == "CONFIRMED_DETECTION"
    )
    compare("raw_endpoint", endpoint.raw, persisted_raw)
    compare("confirmed_endpoint", endpoint.confirmed, persisted_confirmed)
    compare("first_indication_window", endpoint.first_raw_window_id, summary.get("first_indication_window"))
    compare("confirmation_candidate_window", endpoint.first_confirmed_candidate_window_id, summary.get("confirmation_candidate_window"))
    compare("confirmation_window", endpoint.first_confirmation_window_id, summary.get("confirmation_window"))
    compare("verification_advances_required", 4, summary.get("verification_advances_required"))
    if cohort == "normal_holdout":
        compare("normal_holdout_should_stop", False, bool(summary.get("should_stop")))
    else:
        compare("target_should_stop_equals_confirmation", endpoint.confirmed, bool(summary.get("should_stop")))
    if mismatches:
        raise RuntimeError(
            f"LLM reconstruction cross-check failed for {cohort} run {simulation_run}: {mismatches}"
        )
    return {
        "cohort": cohort,
        "simulationRun": simulation_run,
        "status": "PASS",
        "fields_compared": 7,
    }


def _endpoint_columns(prefix: str, endpoint: LLMEndpoint | DPCAEndpoint) -> dict[str, Any]:
    if isinstance(endpoint, LLMEndpoint):
        return {
            f"{prefix}_raw_endpoint": endpoint.raw,
            f"{prefix}_confirmed_endpoint": endpoint.confirmed,
            f"{prefix}_no_confirmation": endpoint.no_confirmation,
            f"{prefix}_raw_event_window": endpoint.first_raw_window_id,
            f"{prefix}_raw_event_sample": endpoint.first_raw_sample_end,
            f"{prefix}_confirmed_candidate_window": endpoint.first_confirmed_candidate_window_id,
            f"{prefix}_confirmed_event_window": endpoint.first_confirmation_window_id,
            f"{prefix}_confirmed_event_sample": endpoint.first_confirmation_sample_end,
            f"{prefix}_raw_delay_minutes": endpoint.raw_delay_minutes,
            f"{prefix}_confirmed_delay_minutes": endpoint.confirmed_delay_minutes,
        }
    return {
        f"{prefix}_raw_endpoint": endpoint.raw,
        f"{prefix}_confirmed_endpoint": endpoint.confirmed,
        f"{prefix}_no_confirmation": endpoint.no_confirmation,
        f"{prefix}_raw_event_window": None,
        f"{prefix}_raw_event_sample": endpoint.first_raw_sample,
        f"{prefix}_confirmed_candidate_window": None,
        f"{prefix}_confirmed_event_window": None,
        f"{prefix}_confirmed_event_sample": endpoint.first_persistent_sample,
        f"{prefix}_raw_delay_minutes": endpoint.raw_delay_minutes,
        f"{prefix}_confirmed_delay_minutes": endpoint.confirmed_delay_minutes,
    }


def _blank_llm_columns() -> dict[str, Any]:
    return {
        "llm_record_count": None,
        "llm_raw_endpoint": None,
        "llm_confirmed_endpoint": None,
        "llm_no_confirmation": None,
        "llm_raw_event_window": None,
        "llm_raw_event_sample": None,
        "llm_confirmed_candidate_window": None,
        "llm_confirmed_event_window": None,
        "llm_confirmed_event_sample": None,
        "llm_raw_delay_minutes": None,
        "llm_confirmed_delay_minutes": None,
        "llm_prefault_raw": None,
        "llm_prefault_confirmed": None,
        "llm_reconstruction_crosscheck": None,
        "h3_total_items": None,
        "h3_verifiable_items": None,
        "h3_passed_items": None,
        "h3_applicable_responses": None,
        "h3_total_responses": None,
        "h3_run_score": None,
    }


def _h3_rows(
    run_evaluation: Any,
    records: list[dict[str, Any]],
    *,
    simulation_run: int,
    blind_run_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    by_window = {int(record["window_id"]): record for record in records}
    response_by_id = {
        evaluation.response_id: evaluation for evaluation in run_evaluation.response_scores
    }
    audits: list[dict[str, Any]] = []
    for response in run_evaluation.response_scores:
        record = by_window[int(response.response_id)]
        if not response.audits:
            audits.append(
                {
                    "row_type": "response_no_evidence",
                    "cohort": "target",
                    "simulationRun": simulation_run,
                    "blind_run_id": blind_run_id,
                    "window_id": response.response_id,
                    "sample_start": record.get("sample_start"),
                    "sample_end": record.get("sample_end"),
                    "decision": response.decision,
                    "response_score": response.response_score,
                    "evidence_index": None,
                    "variable": None,
                    "claim": None,
                    "observation": None,
                    "claim_valid": None,
                    "variable_allowed": None,
                    "variable_valid": None,
                    "variable_in_payload": None,
                    "threshold_available": None,
                    "threshold_name": None,
                    "threshold_value": None,
                    "start_z": None,
                    "end_z": None,
                    "min_z": None,
                    "max_z": None,
                    "slope_z_per_sample": None,
                    "variability_range_rounded": None,
                    "verifiable": None,
                    "rule_satisfied": None,
                    "item_score": None,
                    "reason": "ANOMALY_WITHOUT_EVIDENCE_SCORE_0" if response.response_score == 0 else "EMPTY_NON_ANOMALY_NOT_APPLICABLE",
                }
            )
            continue
        for audit in response.audits:
            row = audit.as_dict()
            row.update(
                {
                    "row_type": "evidence_item",
                    "cohort": "target",
                    "simulationRun": simulation_run,
                    "blind_run_id": blind_run_id,
                    "window_id": response.response_id,
                    "sample_start": record.get("sample_start"),
                    "sample_end": record.get("sample_end"),
                    "decision": response.decision,
                    "response_score": response.response_score,
                }
            )
            audits.append(row)
    # Keep a deterministic, human-auditable column order.
    audit_order = [
        "row_type", "cohort", "simulationRun", "blind_run_id", "window_id",
        "sample_start", "sample_end", "decision", "response_score",
        "evidence_index", "variable", "claim", "observation", "claim_valid",
        "variable_allowed", "variable_valid", "variable_in_payload",
        "threshold_available", "threshold_name", "threshold_value", "start_z",
        "end_z", "min_z", "max_z", "slope_z_per_sample",
        "variability_range_rounded", "verifiable", "rule_satisfied",
        "item_score", "reason",
    ]
    ordered_audits = [{key: item.get(key) for key in audit_order} for item in audits]
    fields = {
        "h3_total_items": len(run_evaluation.audits),
        "h3_verifiable_items": sum(item.verifiable for item in run_evaluation.audits),
        "h3_passed_items": sum(item.item_score for item in run_evaluation.audits),
        "h3_applicable_responses": run_evaluation.applicable_responses,
        "h3_total_responses": run_evaluation.total_responses,
        "h3_run_score": run_evaluation.run_score,
    }
    return fields, ordered_audits


def materialize_run_level(
    root: Path,
    manifest: dict[str, Any],
    target_selection: set[int],
    normal_selection: set[int],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    h3_reference = _read_json(
        root / "repo/experiments/tep/local_llm/config/h3_evidence_reference.json"
    )
    valid_h3_variables = set(h3_reference["thresholds"])
    run_rows: list[dict[str, Any]] = []
    h3_run_rows: list[dict[str, Any]] = []
    h3_audit_rows: list[dict[str, Any]] = []
    llm_crosschecks: list[dict[str, Any]] = []
    dpca_continuous_compared = 0
    dpca_reset_compared = 0
    dpca_reset_boundary_skipped = 0

    matrix = sorted(
        manifest["final_matrix"],
        key=lambda item: (0 if item["cohort"] == "target" else 1, item["simulationRun"]),
    )
    for manifest_row in matrix:
        cohort = manifest_row["cohort"]
        simulation_run = int(manifest_row["simulationRun"])
        blind = manifest_row["blind_run_id"]
        selected = simulation_run in (
            target_selection if cohort == "target" else normal_selection
        )
        dpca_path = _component_path(root, manifest_row, "dpca", "dpca_metrics.jsonl")
        dpca_records = _read_jsonl(dpca_path)

        # Cross-check native persistence continuously over the full trajectory.
        native_check = crosscheck_native_flags(
            dpca_records,
            first_sample=1,
            last_sample=LAST_SAMPLE,
            reset=False,
            persistence=3,
            raise_on_mismatch=True,
        )
        dpca_continuous_compared += native_check.compared

        if cohort == "target":
            dpca_endpoint = reconstruct_dpca_endpoint(
                dpca_records, ONSET, LAST_SAMPLE, reset=True, persistence=3, onset=ONSET
            )
            dpca_pre = reconstruct_dpca_endpoint(
                dpca_records, 1, ONSET - 1, reset=True, persistence=3, onset=ONSET
            )
            reset_check = crosscheck_native_flags(
                dpca_records,
                first_sample=ONSET,
                last_sample=LAST_SAMPLE,
                reset=True,
                persistence=3,
                raise_on_mismatch=True,
            )
            dpca_reset_compared += reset_check.compared
            dpca_reset_boundary_skipped += reset_check.skipped
        else:
            dpca_endpoint = reconstruct_dpca_endpoint(
                dpca_records, 1, LAST_SAMPLE, reset=True, persistence=3, onset=ONSET
            )
            dpca_pre = None

        run_row: dict[str, Any] = {
            "cohort": cohort,
            "simulationRun": simulation_run,
            "blind_run_id": blind,
            "llm_selected": selected,
            "dpca_paired_selected": selected,
            "final_outer_attempt": manifest_row["final_outer_attempt"],
            "dpca_scientific_attempt": manifest_row["dpca_scientific_attempt"],
            "llm_scientific_attempt": manifest_row.get("llm_scientific_attempt"),
            "dpca_record_count": len(dpca_records),
            **_endpoint_columns("dpca", dpca_endpoint),
            "dpca_prefault_raw": dpca_pre.raw if dpca_pre else None,
            "dpca_prefault_confirmed": dpca_pre.confirmed if dpca_pre else None,
            "dpca_reconstruction_crosscheck": "PASS",
            **_blank_llm_columns(),
        }

        if selected:
            llm_path = _component_path(root, manifest_row, "llm", "llm_decisions.jsonl")
            summary_path = _component_path(root, manifest_row, "llm", "detection_summary.json")
            llm_records = _read_jsonl(llm_path)
            region = "target_post" if cohort == "target" else "normal_full"
            llm_endpoint = reconstruct_llm_endpoint(llm_records, region, onset=ONSET, R=4)
            summary = _read_json(summary_path)
            llm_crosschecks.append(
                _llm_summary_crosscheck(
                    llm_endpoint,
                    summary,
                    cohort=cohort,
                    simulation_run=simulation_run,
                )
            )
            llm_pre = (
                reconstruct_llm_endpoint(llm_records, "target_pre", onset=ONSET, R=4)
                if cohort == "target"
                else None
            )
            run_row.update(_endpoint_columns("llm", llm_endpoint))
            run_row.update(
                {
                    "llm_record_count": len(llm_records),
                    "llm_prefault_raw": llm_pre.raw if llm_pre else None,
                    "llm_prefault_confirmed": llm_pre.confirmed if llm_pre else None,
                    "llm_reconstruction_crosscheck": "PASS",
                }
            )
            if cohort == "target":
                h3_eval = score_h3_run(
                    llm_records,
                    h3_reference,
                    valid_variables=valid_h3_variables,
                    simulation_run=simulation_run,
                )
                h3_fields, audit_rows = _h3_rows(
                    h3_eval,
                    llm_records,
                    simulation_run=simulation_run,
                    blind_run_id=blind,
                )
                run_row.update(h3_fields)
                h3_run_rows.append(
                    {
                        "cohort": cohort,
                        "simulationRun": simulation_run,
                        "blind_run_id": blind,
                        **h3_fields,
                    }
                )
                h3_audit_rows.extend(audit_rows)
        run_rows.append(run_row)

    run_frame = pd.DataFrame(run_rows)
    h3_run_frame = pd.DataFrame(h3_run_rows)
    h3_audit_frame = pd.DataFrame(h3_audit_rows)
    if len(run_frame) != 1000 or run_frame[["cohort", "simulationRun"]].duplicated().any():
        raise RuntimeError("Materialized run-level endpoint table is not 1,000 unique rows")
    if len(h3_run_frame) != 50:
        raise RuntimeError("H3 run-level table is not 50 TARGET LLM runs")
    if len(llm_crosschecks) != 100:
        raise RuntimeError("LLM reconstruction cross-check did not cover 100 final runs")
    crosscheck = {
        "llm": {
            "status": "PASS",
            "runs_compared": len(llm_crosschecks),
            "detection_summary_role": "audit only",
        },
        "dpca": {
            "status": "PASS",
            "runs_continuous_native_compared": 1000,
            "continuous_sample_flags_compared": dpca_continuous_compared,
            "target_postreset_runs_compared": 500,
            "target_postreset_sample_flags_compared": dpca_reset_compared,
            "target_reset_boundary_native_flags_skipped_as_noncomparable": dpca_reset_boundary_skipped,
        },
    }
    return run_frame, h3_run_frame, h3_audit_frame, crosscheck


def _amendment_frame(manifest: dict[str, Any], target_selection: set[int]) -> pd.DataFrame:
    manifest_base = set(
        manifest.get("amendment_provenance", {}).get(
            "target_llm_runs_using_base_configuration", []
        )
    )
    if manifest_base != BASE_AMENDMENT_RUNS:
        raise RuntimeError(
            f"Amendment base-run provenance differs: {sorted(manifest_base)}"
        )
    matrix_index = {
        (item["cohort"], item["simulationRun"]): item for item in manifest["final_matrix"]
    }
    rows: list[dict[str, Any]] = []
    for run in sorted(target_selection):
        final = matrix_index[("target", run)]
        phase = "base_768" if run in BASE_AMENDMENT_RUNS else "effective_1024"
        rows.append(
            {
                "record_type": "final_scientific_run",
                "cohort": "target",
                "simulationRun": run,
                "llm_attempt": final["llm_scientific_attempt"],
                "configuration_phase": phase,
                "max_output_tokens": 768 if phase == "base_768" else 1024,
                "included_in_performance": True,
                "provenance_note": "Preserved final scientific attempt; no subgroup efficacy analysis",
            }
        )
    rows.append(
        {
            "record_type": "historical_attempt",
            "cohort": "target",
            "simulationRun": 58,
            "llm_attempt": "0001",
            "configuration_phase": "pre_amendment_historical_768",
            "max_output_tokens": 768,
            "included_in_performance": False,
            "provenance_note": "Historical non-final attempt; excluded from all scientific endpoints",
        }
    )
    final_58 = next(
        row
        for row in rows
        if row["record_type"] == "final_scientific_run" and row["simulationRun"] == 58
    )
    if str(final_58["llm_attempt"]) != "0002":
        raise RuntimeError("TARGET run58 final LLM attempt is not 0002")
    return pd.DataFrame(rows)


def _environment(root: Path) -> dict[str, Any]:
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip(),
        "branch": subprocess.check_output(
            ["git", "-C", str(root), "branch", "--show-current"], text=True
        ).strip(),
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "timezone_environment": os.environ.get("TZ"),
        "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "llm_inference_executed": False,
        "dpca_inference_executed": False,
    }


def _methods(
    bootstrap_audit: list[dict[str, Any]], crosscheck: dict[str, Any]
) -> dict[str, Any]:
    return {
        "unit_of_inference": "simulationRun",
        "run_level_table_is_only_aggregate_source": True,
        "llm": {
            "raw": "eligible ANOMALY in the scientific region",
            "confirmed": "decision[k] == ANOMALY and decision[k+4] == ANOMALY",
            "candidate_concurrency": True,
            "onset_reset": 161,
            "delay_minutes": "(event sample_end - 161) * 3",
        },
        "dpca": {
            "raw_source": "alarm_raw from dpca_metrics.jsonl",
            "confirmed": "third consecutive alarm_raw after scientific-region reset",
            "target_postonset_reset": 161,
            "delay_minutes": "(event sample - 161) * 3",
        },
        "proportions": {
            "wilson_formula": "[(p+z^2/(2n)) +/- z*sqrt(p(1-p)/n+z^2/(4n^2))]/(1+z^2/n)",
            "confidence": 0.95,
            "clopper_pearson": "equal-tail scipy Beta quantiles; reported as sensitivity at 0/n or n/n",
        },
        "bootstrap": {
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
            "preferred": "BCa with explicit bias correction and delete-one jackknife acceleration",
            "fallback": "percentile using the same run-level replicates when BCa is undefined",
            "n_0": "undefined",
            "n_1": "no inferential interval under SAP",
            "calls": bootstrap_audit,
        },
        "dpca_expanded_intervals": "explicitly labeled model-based extrapolation for analogous trajectories",
        "paired_binary": {
            "difference": "mean(LLM - DPCA)",
            "bootstrap": "paired simulationRun clusters",
            "mcnemar": "exact two-sided binomial on discordant pairs; p=1 at zero discordance",
        },
        "holm_primary_family": [
            "TARGET confirmed detection LLM x DPCA",
            "NORMAL HOLDOUT confirmed false alarm LLM x DPCA",
        ],
        "holm_secondary_families": {
            "paired_delay_sign_tests_secondary": [
                "TARGET paired raw-delay exact sign test",
                "TARGET paired confirmed-delay exact sign test",
            ]
        },
        "paired_delays": {
            "conditioning": "both detectors have the same endpoint defined",
            "difference": "LLM - DPCA minutes",
            "sign_test": "exact two-sided binomial p=0.5; zero differences excluded as ties; the two secondary p-values form a separate Holm-adjusted family",
        },
        "h3": {
            "observation_used_in_score": False,
            "item_rules": {
                "HIGH": "max_z >= high_max_z_q99",
                "LOW": "min_z <= low_min_z_q01",
                "INCREASE": "slope_z_per_sample >= increase_slope_q99 AND end_z > start_z",
                "REDUCTION": "slope_z_per_sample <= reduction_slope_q01 AND end_z < start_z",
                "VARIABILITY": "round(max_z - min_z, 4) >= high_variability_range_q99",
            },
            "primary_aggregate": "equal-run macro mean of applicable run_score",
            "micro_score": "secondary mean item score over all evidence items",
            "unsupported_process_claims": "not classified without a frozen codebook",
        },
        "reconstruction_crosscheck": crosscheck,
    }


def _audit_markdown(
    integrity: dict[str, Any],
    crosscheck: dict[str, Any],
    input_validation: dict[str, Any],
    tests_status: str,
) -> str:
    counts = integrity["counts"]
    return f"""# CALCULATION 2 audit

## Independence and source

- Source commit: `{SOURCE_COMMIT}`
- Branch: `{BRANCH}`
- Prior-analysis contamination risk: `NO`
- Historical aggregation implementation imported: `NO`
- Prior analysis trees inspected: `NO`

## Frozen gates

- FINAL_CAMPAIGN_MANIFEST canonical SHA-256: `{MANIFEST_SHA256}` — `{integrity['final_manifest_gate']}`
- SAP Git blob: `{SAP_BLOB}`
- SAP canonical SHA-256: `{SAP_SHA256}` — `{integrity['sap_gate']}`
- Primary JSONL: `{counts['primary_files_found']}` found; `{counts['primary_hash_mismatches']}` hash mismatches
- Denominator gate: `{integrity['denominator_gate']}`

Tracked JSON/Markdown files use CRLF in this Windows checkout. Their frozen
digests were checked against explicitly normalized LF bytes, while raw checkout
hashes were retained and rechecked after calculation. Primary JSONL hashes were
checked directly over raw bytes.

## Reconstruction cross-checks

- LLM: `{crosscheck['llm']['status']}` across `{crosscheck['llm']['runs_compared']}` final runs; `detection_summary.json` used only as audit.
- DPCA: `{crosscheck['dpca']['status']}` across 1,000 full trajectories and 500 TARGET post-onset reset reconstructions.

## Statistical execution

- Aggregation source: `01_run_level/calculation2_run_level_endpoints.csv` only.
- Bootstrap: 10,000 run-level replicates, seed 20260820, BCa preferred with pre-specified percentile fallback.
- Multiplicity: the two primary McNemar p-values and the two secondary paired-delay sign-test p-values are Holm-adjusted in separate, explicitly labeled families.
- Tests: `{tests_status}`.
- Inputs modified during calculation: `{input_validation['input_results_modified']}`.
- LLM inference executed: `NO`.
- DPCA inference/fitting executed: `NO`.

## Provenance limitations

Two JSONL files from non-final historical partial attempts are referenced by the
campaign manifest but are not materialized in this clone. They are not among the
1,100 final primary artifacts, were not used in performance calculations, and do
not alter the final-corpus integrity gate. The 768→1024 amendment output is
strictly descriptive provenance and contains no subgroup efficacy analysis.
"""


def _calculation_manifest(output_root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in sorted(output_root.rglob("*")):
        if not path.is_file() or path.name == "CALCULATION2_MANIFEST.json":
            continue
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        data = path.read_bytes()
        files.append(
            {
                "path": path.relative_to(output_root).as_posix(),
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    return {
        "schema_version": "1.0.0",
        "calculation": "CALCULATION_2_INDEPENDENT",
        "source_commit": SOURCE_COMMIT,
        "branch": BRANCH,
        "method_freeze_id": METHOD_FREEZE,
        "files": files,
    }


def main() -> int:
    script = Path(__file__).resolve()
    output_root = script.parent.parent
    root = script.parents[5]
    if root.name != "calculation2-independent-20260820":
        raise RuntimeError(f"Unexpected repository root resolved from script: {root}")

    # This function writes only 00_integrity and aborts before any endpoint
    # materialization if a frozen gate fails.
    context = audit_integrity(root, output_root)
    for directory in (
        "01_run_level",
        "02_primary",
        "03_secondary",
        "04_h3",
        "05_audit",
    ):
        (output_root / directory).mkdir(parents=True, exist_ok=True)

    run_level, h3_runs, h3_audit, crosscheck = materialize_run_level(
        root,
        context.manifest,
        set(context.target_selection),
        set(context.normal_selection),
    )
    run_level_path = output_root / "01_run_level/calculation2_run_level_endpoints.csv"
    _write_frame(run_level_path, run_level)
    _write_frame(output_root / "01_run_level/calculation2_h3_run_scores.csv", h3_runs)
    _write_frame(output_root / "04_h3/h3_evidence_audit.csv", h3_audit)

    # Hard separation: all subsequent aggregates reload the persisted run-level
    # table and never revisit primary JSONL.
    aggregate_source = pd.read_csv(run_level_path)
    bundle = aggregate_from_run_level(aggregate_source)
    _write_frame(output_root / "02_primary/h1_target.csv", bundle.h1_target)
    _write_frame(output_root / "02_primary/normal_holdout.csv", bundle.normal_holdout)
    _write_frame(output_root / "02_primary/paired_binary.csv", bundle.paired_binary)
    _write_json(output_root / "02_primary/primary_statistics.json", bundle.primary_statistics)
    _write_frame(output_root / "03_secondary/target_preonset.csv", bundle.target_preonset)
    _write_frame(output_root / "03_secondary/h2_delays.csv", bundle.h2_delays)
    _write_frame(output_root / "03_secondary/paired_delays.csv", bundle.paired_delays)
    _write_frame(output_root / "03_secondary/dpca_expanded.csv", bundle.dpca_expanded)
    amendment = _amendment_frame(context.manifest, set(context.target_selection))
    _write_frame(output_root / "03_secondary/amendment_provenance.csv", amendment)
    _write_json(output_root / "04_h3/h3_statistics.json", bundle.h3_statistics)
    _write_json(output_root / "RECONCILIATION_KEYS.json", bundle.reconciliation_keys)

    input_validation = validate_snapshot_unchanged(root, context.snapshot)
    status_by_path = {item["path"]: item["status"] for item in input_validation["files"]}
    input_validation.update(
        {
            "sap_modified": "NO" if status_by_path["repo/project/final_campaign/STATISTICAL_ANALYSIS_PLAN.md"] == "UNCHANGED" else "YES",
            "final_campaign_manifest_modified": "NO" if status_by_path["repo/project/final_campaign/FINAL_CAMPAIGN_MANIFEST.json"] == "UNCHANGED" else "YES",
            "formal_json_modified": "NO" if status_by_path["repo/experiments/tep/local_llm/config/formal.json"] == "UNCHANGED" else "YES",
        }
    )
    _write_json(output_root / "05_audit/environment.json", _environment(root))
    _write_json(
        output_root / "05_audit/input_hash_validation.json", input_validation
    )
    _write_json(
        output_root / "05_audit/methods.json",
        _methods(bundle.bootstrap_audit, crosscheck),
    )
    audit_text = _audit_markdown(
        context.report,
        crosscheck,
        input_validation,
        tests_status="synthetic suite executed separately before commit",
    )
    (output_root / "05_audit/CALCULATION2_AUDIT.md").write_text(
        audit_text, encoding="utf-8", newline="\n"
    )

    if input_validation["input_results_modified"] != "NO":
        raise RuntimeError("A frozen scientific input changed during calculation")
    _write_json(
        output_root / "CALCULATION2_MANIFEST.json",
        _calculation_manifest(output_root),
    )

    print("FINAL_MANIFEST_GATE = PASS")
    print("SAP_GATE = PASS")
    print("PRIMARY_FILES_FOUND = 1100")
    print("DENOMINATOR_GATE = PASS")
    print("LLM_RECONSTRUCTION_CROSSCHECK = PASS")
    print("DPCA_RECONSTRUCTION_CROSSCHECK = PASS")
    print("STATISTICAL_ANALYSIS_EXECUTED = YES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

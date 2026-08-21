#!/usr/bin/env python3
"""Execute the frozen formal-campaign SAP on immutable final artifacts.

The command has an explicit two-phase gate:

* ``--integrity-only`` writes only the integrity report and denominator table.
* ``--full`` repeats the complete integrity gate before computing any estimate.

The script never writes below ``results/`` or ``repo/``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy

from endpoint_rules import dpca_run_endpoints, llm_run_endpoints, score_h3_run
from statistical_utils import (
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    bootstrap_interval,
    clopper_pearson_interval,
    describe_values,
    exact_sign_test,
    holm_adjust,
    paired_binary_summary,
    wilson_interval,
)


METHOD_FREEZE = "TEP-METHOD-FREEZE-20260815-FULL-WINDOW-REFRESH"
SOURCE_REPOSITORY = "prefix325/experimento"
SOURCE_MAIN_COMMIT = "536cd4462b2fdc7e1bac8317adc64534e546c809"
ANALYSIS_BRANCH = "analysis/formal-sap-results-20260820"
EXPECTED_SAP_BLOB = "401c245f6b222e85662d8e47d4312ce27e8e8c60"
EXPECTED_FINAL_MANIFEST_SHA256 = "d3f7cdde04b18182a2fe25cc8ea23e07833a0c3ab9441403d9eb1b17dd028db5"
SAP_REPO_PATH = "repo/project/final_campaign/STATISTICAL_ANALYSIS_PLAN.md"
MANIFEST_REPO_PATH = "repo/project/final_campaign/FINAL_CAMPAIGN_MANIFEST.json"
FORMAL_REPO_PATH = "repo/experiments/tep/local_llm/config/formal.json"
CONFIG_ROOT_REPO_PATH = "repo/experiments/tep/local_llm/config"
BASE_OUTPUT_CAP_RUNS = {14, 23, 24, 26, 27, 55}
TECHNICAL_BLOBS = {
    "repo/experiments/tep/local_llm/config/evaluation_contract.json": "183297c3570c6a6b2ceab3c9838ae3ec4ca3cd0e",
    "repo/experiments/tep/local_llm/config/formal_run_selection.json": "09b164f567b504b57e070f416910bd13d77dda7c",
    "repo/experiments/tep/local_llm/config/formal_normal_holdout_selection.json": "8fddb354a7c8853a8760b41a1012b4c16e85d930",
    "repo/experiments/tep/local_llm/config/h3_evidence_reference.json": "fbda319ba744054d33af2bf4f2cd99d264a100fc",
    "repo/experiments/tep/local_llm/src/tep_local/dpca.py": "668255aff7819032dd3aeb204e24cb2cca213b91",
    "repo/experiments/tep/local_llm/src/tep_local/evaluation.py": "7b992d573dfc34d09d9811bb04db66ce064520c5",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"Blank JSONL line at {path}:{line_number}")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"Non-object JSONL row at {path}:{line_number}")
            rows.append(value)
    return rows


def git(repo_root: Path, *args: str, binary: bool = False) -> str | bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=not binary,
    )
    return completed.stdout if binary else completed.stdout.strip()


def read_git_json(repo_root: Path, repo_path: str) -> dict[str, Any]:
    raw = git(repo_root, "show", f"HEAD:{repo_path}", binary=True)
    assert isinstance(raw, bytes)
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected Git-tracked JSON object: {repo_path}")
    return value


def rel(repo_root: Path, path: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if value is pd.NA:
        return None
    return value


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.writing")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(json_safe(value), handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
    temporary.replace(path)


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n", float_format="%.12g")
    round_trip = pd.read_csv(path)
    if list(round_trip.columns) != list(frame.columns) or len(round_trip) != len(frame):
        raise RuntimeError(f"CSV round-trip validation failed: {path}")


def _primary_artifact(
    repo_root: Path,
    results_root: Path,
    entry: dict[str, Any],
    detector: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    blind_id = str(entry["blind_run_id"])
    attempt_field = f"{detector}_scientific_attempt"
    attempt = entry.get(attempt_field)
    if attempt is None:
        raise ValueError(f"Required {detector} has no scientific attempt")
    attempt_text = str(attempt).zfill(4)
    detector_root = results_root / str(entry["cohort"]) / detector
    run_root = detector_root / "runs" / blind_id
    marker_path = run_root / "COMPLETE.json"
    marker = read_json(marker_path)
    manifest_path = detector_root / str(marker["run_manifest_relative_path"])
    run_manifest = read_json(manifest_path)
    artifact_name = "dpca_metrics.jsonl" if detector == "dpca" else "llm_decisions.jsonl"
    artifact_path = manifest_path.parent / artifact_name
    artifact_meta = next(
        (item for item in run_manifest.get("artifacts", []) if item.get("name") == artifact_name),
        None,
    )
    if artifact_meta is None:
        raise ValueError(f"Final run manifest lacks {artifact_name}: {manifest_path}")
    observed = {
        "cohort": entry["cohort"],
        "simulationRun": int(entry["simulationRun"]),
        "blind_run_id": blind_id,
        "detector": detector,
        "scientific_attempt": attempt_text,
        "complete_marker_path": rel(repo_root, marker_path),
        "complete_marker_expected_sha256": entry[f"{detector}_complete_marker_hash"],
        "complete_marker_observed_sha256": sha256_file(marker_path),
        "run_manifest_path": rel(repo_root, manifest_path),
        "run_manifest_expected_sha256": entry[f"{detector}_manifest_hash"],
        "run_manifest_observed_sha256": sha256_file(manifest_path),
        "primary_artifact_path": rel(repo_root, artifact_path),
        "primary_artifact_expected_sha256": (
            entry["dpca_artifact_hash"] if detector == "dpca" else entry["llm_decisions_hash"]
        ),
        "primary_artifact_manifest_sha256": artifact_meta["sha256"],
        "primary_artifact_observed_sha256": sha256_file(artifact_path),
        "primary_artifact_expected_size": int(artifact_meta["size_bytes"]),
        "primary_artifact_observed_size": artifact_path.stat().st_size,
        "marker_status": marker.get("status"),
        "run_manifest_status": run_manifest.get("status"),
        "marker_attempt": str(marker.get("attempt")).zfill(4),
        "run_manifest_attempt": str(run_manifest.get("attempt")).zfill(4),
        "run_manifest_blind_run_id": run_manifest.get("blind_run_id"),
    }
    checks = [
        observed["complete_marker_expected_sha256"] == observed["complete_marker_observed_sha256"],
        marker.get("run_manifest_sha256") == observed["run_manifest_observed_sha256"],
        observed["run_manifest_expected_sha256"] == observed["run_manifest_observed_sha256"],
        observed["primary_artifact_expected_sha256"] == observed["primary_artifact_observed_sha256"],
        observed["primary_artifact_manifest_sha256"] == observed["primary_artifact_observed_sha256"],
        observed["primary_artifact_expected_size"] == observed["primary_artifact_observed_size"],
        observed["marker_status"] == "COMPLETE",
        observed["run_manifest_status"] == "COMPLETE",
        observed["marker_attempt"] == attempt_text,
        observed["run_manifest_attempt"] == attempt_text,
        observed["run_manifest_blind_run_id"] == blind_id,
    ]
    observed["valid"] = all(checks)
    return observed, run_manifest.get("artifacts", [])


def validate_integrity(repo_root: Path) -> tuple[dict[str, Any], dict[tuple[str, int, str], Path]]:
    """Validate all frozen authorities and every final primary input."""
    output_root = repo_root / "analysis" / "formal" / METHOD_FREEZE
    results_root = repo_root / "results" / "formal" / METHOD_FREEZE
    manifest_path = repo_root / MANIFEST_REPO_PATH
    sap_path = repo_root / SAP_REPO_PATH
    formal_path = repo_root / FORMAL_REPO_PATH

    manifest_sha = sha256_file(manifest_path)
    manifest = read_json(manifest_path)
    sap_blob = str(git(repo_root, "rev-parse", f"HEAD:{SAP_REPO_PATH}"))
    sap_canonical_bytes = git(repo_root, "show", f"HEAD:{SAP_REPO_PATH}", binary=True)
    assert isinstance(sap_canonical_bytes, bytes)
    sap_canonical_sha = sha256_bytes(sap_canonical_bytes)
    sap_worktree_sha = sha256_file(sap_path)
    head = str(git(repo_root, "rev-parse", "HEAD"))
    branch = str(git(repo_root, "branch", "--show-current"))
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", SOURCE_MAIN_COMMIT, "HEAD"], cwd=repo_root
    ).returncode == 0

    technical_sources = []
    for repo_path, expected_blob in TECHNICAL_BLOBS.items():
        observed_blob = str(git(repo_root, "rev-parse", f"HEAD:{repo_path}"))
        technical_sources.append(
            {
                "path": repo_path,
                "expected_git_blob": expected_blob,
                "observed_git_blob": observed_blob,
                "valid": expected_blob == observed_blob,
                "worktree_sha256": sha256_file(repo_root / repo_path),
            }
        )
    technical_status = str(
        git(repo_root, "status", "--porcelain", "--", *TECHNICAL_BLOBS.keys())
    )
    target_selection = read_git_json(
        repo_root, "repo/experiments/tep/local_llm/config/formal_run_selection.json"
    )
    normal_selection = read_git_json(
        repo_root, "repo/experiments/tep/local_llm/config/formal_normal_holdout_selection.json"
    )
    selected = {
        "target": {int(x) for x in target_selection["selected_simulation_runs"]},
        "normal_holdout": {int(x) for x in normal_selection["selected_simulation_runs"]},
    }
    matrix = manifest.get("final_matrix", [])
    keys = [(str(row["cohort"]), int(row["simulationRun"])) for row in matrix]
    unique_keys = set(keys)
    duplicate_final_runs = len(keys) - len(unique_keys)
    cohort_counts = {
        cohort: sum(str(row["cohort"]) == cohort for row in matrix)
        for cohort in ("target", "normal_holdout")
    }

    inventory: list[dict[str, Any]] = []
    artifact_paths: dict[tuple[str, int, str], Path] = {}
    missing: list[str] = []
    problems: list[str] = []
    for entry in matrix:
        cohort = str(entry["cohort"])
        run = int(entry["simulationRun"])
        for detector in ("dpca", "llm"):
            required = bool(entry.get(f"{detector}_required"))
            if not required:
                continue
            try:
                audit_row, _ = _primary_artifact(repo_root, results_root, entry, detector)
                inventory.append(audit_row)
                artifact_paths[(cohort, run, detector)] = repo_root / audit_row["primary_artifact_path"]
                if not audit_row["valid"]:
                    problems.append(f"hash/status mismatch: {cohort}/{run}/{detector}")
            except (FileNotFoundError, KeyError, ValueError) as exc:
                missing.append(f"{cohort}/{run}/{detector}: {exc}")

    dpca_rows = [row for row in inventory if row["detector"] == "dpca"]
    llm_rows = [row for row in inventory if row["detector"] == "llm"]
    llm_manifest_selection = {
        cohort: {
            int(row["simulationRun"])
            for row in matrix
            if row["cohort"] == cohort and bool(row.get("llm_required"))
        }
        for cohort in selected
    }
    out_of_selection = sum(len(llm_manifest_selection[c] ^ selected[c]) for c in selected)
    duplicate_artifact_paths = len(inventory) - len({row["primary_artifact_path"] for row in inventory})
    hash_mismatches = sum(not bool(row["valid"]) for row in inventory)
    formal_sha = sha256_file(formal_path)
    formal_matches_manifest = formal_sha == manifest["configuration"]["formal_json_sha256"]

    protected_status = str(
        git(
            repo_root,
            "status",
            "--porcelain",
            "--",
            "results/formal",
            MANIFEST_REPO_PATH,
            SAP_REPO_PATH,
            FORMAL_REPO_PATH,
        )
    )
    gates = {
        "source_branch": branch == ANALYSIS_BRANCH,
        "source_commit_is_ancestor": ancestor,
        "final_manifest_sha256": manifest_sha == EXPECTED_FINAL_MANIFEST_SHA256,
        "final_manifest_sidecar": (
            (manifest_path.with_suffix(".sha256")).read_text(encoding="utf-8").split()[0]
            == manifest_sha
        ),
        "sap_git_blob": sap_blob == EXPECTED_SAP_BLOB,
        "linked_technical_git_blobs": all(row["valid"] for row in technical_sources),
        "linked_technical_worktree_unmodified": technical_status == "",
        "method_freeze": manifest.get("method_freeze_id") == METHOD_FREEZE,
        "total_runs": len(matrix) == 1000,
        "unique_runs": len(unique_keys) == 1000,
        "target_runs": cohort_counts["target"] == 500,
        "normal_holdout_runs": cohort_counts["normal_holdout"] == 500,
        "dpca_inputs": len(dpca_rows) == 1000,
        "llm_inputs": len(llm_rows) == 100,
        "llm_target_inputs": sum(row["cohort"] == "target" for row in llm_rows) == 50,
        "llm_normal_inputs": sum(row["cohort"] == "normal_holdout" for row in llm_rows) == 50,
        "missing_primary_artifacts": len(missing) == 0,
        "hash_mismatches": hash_mismatches == 0,
        "out_of_selection_llm": out_of_selection == 0,
        "duplicate_final_runs": duplicate_final_runs == 0,
        "duplicate_primary_artifacts": duplicate_artifact_paths == 0,
        "formal_json_matches_manifest": formal_matches_manifest,
        "protected_inputs_unmodified": protected_status == "",
    }
    passed = all(gates.values()) and not problems
    report = {
        "schema_version": "1.0.0",
        "generated_at_utc": utc_now(),
        "authority": {
            "source_repository": SOURCE_REPOSITORY,
            "source_main_commit": SOURCE_MAIN_COMMIT,
            "analysis_head_at_validation": head,
            "analysis_branch": branch,
            "method_freeze": METHOD_FREEZE,
            "final_manifest_path": MANIFEST_REPO_PATH,
            "final_manifest_sha256_expected": EXPECTED_FINAL_MANIFEST_SHA256,
            "final_manifest_sha256_observed": manifest_sha,
            "sap_path": SAP_REPO_PATH,
            "sap_git_blob_expected": EXPECTED_SAP_BLOB,
            "sap_git_blob_observed": sap_blob,
            "sap_sha256_canonical_git_blob": sap_canonical_sha,
            "sap_sha256_worktree_bytes": sap_worktree_sha,
            "sap_worktree_eol_note": "Worktree may be CRLF under core.autocrlf; canonical Git blob bytes govern portable provenance.",
            "formal_json_sha256": formal_sha,
            "linked_technical_sources": technical_sources,
        },
        "counts": {
            "simulation_runs_total": len(matrix),
            "target_runs": cohort_counts["target"],
            "normal_holdout_runs": cohort_counts["normal_holdout"],
            "dpca_primary_artifacts": len(dpca_rows),
            "llm_primary_artifacts": len(llm_rows),
            "llm_target_primary_artifacts": sum(row["cohort"] == "target" for row in llm_rows),
            "llm_normal_primary_artifacts": sum(row["cohort"] == "normal_holdout" for row in llm_rows),
            "primary_artifacts_total": len(inventory),
            "missing_primary_artifacts": len(missing),
            "primary_hash_mismatches": hash_mismatches,
            "out_of_selection_llm": out_of_selection,
            "duplicate_final_runs": duplicate_final_runs,
            "duplicate_primary_artifacts": duplicate_artifact_paths,
        },
        "gates": gates,
        "gate_status": "PASS" if passed else "FAIL",
        "missing": missing,
        "problems": problems,
        "input_artifacts": inventory,
        "non_invalidating_anomalies": manifest.get("non_invalidating_anomalies", []),
        "aggregate_statistics_calculated_by_this_phase": False,
        "output_root": rel(repo_root, output_root),
    }
    return report, artifact_paths


def denominator_frame(report: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for cohort, universe, llm_universe in (
        ("target", 500, 490),
        ("normal_holdout", 500, 500),
    ):
        for detector, analysis_set, main_set, paired_set, n_runs in (
            ("LLM", "principal", 50, 50, 50),
            ("DPCA", "paired", 50, 50, 50),
            ("DPCA", "expanded", 500, 50, 500),
        ):
            formal_universe = llm_universe if detector == "LLM" else universe
            artifacts = n_runs
            rows.append(
                {
                    "cohort": cohort,
                    "detector": detector,
                    "analysis_set": analysis_set,
                    "formal_universe_runs": formal_universe,
                    "main_analysis_set_runs": main_set,
                    "paired_set_runs": paired_set,
                    "number_of_runs": n_runs,
                    "final_artifacts": artifacts,
                    "missing_artifacts": 0,
                    "missingness_rate": 0.0,
                    "integrity_status": report["gate_status"],
                }
            )
    return pd.DataFrame(rows)


def materialize_integrity(repo_root: Path) -> tuple[dict[str, Any], dict[tuple[str, int, str], Path]]:
    report, artifact_paths = validate_integrity(repo_root)
    if report["gate_status"] != "PASS":
        raise RuntimeError("INTEGRITY GATE FAILED; no statistics were calculated")
    output_root = repo_root / "analysis" / "formal" / METHOD_FREEZE
    atomic_json(output_root / "00_integrity" / "integrity_report.json", report)
    write_csv(output_root / "00_integrity" / "denominator_table.csv", denominator_frame(report))
    return report, artifact_paths


RUN_LEVEL_COLUMNS = [
    "cohort",
    "simulationRun",
    "blind_run_id",
    "final_outer_attempt",
    "dpca_scientific_attempt",
    "llm_required",
    "llm_scientific_attempt",
    "integrity_status",
    "llm_records",
    "llm_early_stop",
    "llm_raw_post_onset",
    "llm_confirmed_post_onset",
    "llm_first_indication_sample_end",
    "llm_confirmation_sample_end",
    "llm_raw_delay_minutes",
    "llm_confirmed_delay_minutes",
    "llm_raw_pre_onset",
    "llm_confirmed_pre_onset",
    "dpca_records",
    "dpca_raw_post_onset",
    "dpca_confirmed_post_onset",
    "dpca_first_raw_sample",
    "dpca_first_persistent_sample",
    "dpca_raw_delay_minutes",
    "dpca_confirmed_delay_minutes",
    "dpca_raw_pre_onset",
    "dpca_confirmed_pre_onset",
    "llm_any_raw_false_alarm",
    "llm_any_confirmed_false_alarm",
    "dpca_any_raw_false_alarm",
    "dpca_any_confirmed_false_alarm",
    "h3_run_score",
    "h3_applicable_responses",
    "h3_evidence_items",
    "h3_verifiable_evidence_items",
]


def build_run_level(
    repo_root: Path,
    artifact_paths: dict[tuple[str, int, str], Path],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    manifest = read_json(repo_root / MANIFEST_REPO_PATH)
    thresholds = read_git_json(
        repo_root, "repo/experiments/tep/local_llm/config/h3_evidence_reference.json"
    )["thresholds"]
    rows: list[dict[str, Any]] = []
    h3_rows: list[dict[str, Any]] = []
    h3_audit: list[dict[str, Any]] = []
    provenance_rows: list[dict[str, Any]] = []

    ordering = {"target": 0, "normal_holdout": 1}
    matrix = sorted(
        manifest["final_matrix"],
        key=lambda item: (ordering[str(item["cohort"])], int(item["simulationRun"])),
    )
    for entry in matrix:
        cohort = str(entry["cohort"])
        run = int(entry["simulationRun"])
        blind_id = str(entry["blind_run_id"])
        base: dict[str, Any] = {column: None for column in RUN_LEVEL_COLUMNS}
        base.update(
            {
                "cohort": cohort,
                "simulationRun": run,
                "blind_run_id": blind_id,
                "final_outer_attempt": entry.get("final_outer_attempt"),
                "dpca_scientific_attempt": str(entry["dpca_scientific_attempt"]).zfill(4),
                "llm_required": bool(entry["llm_required"]),
                "llm_scientific_attempt": (
                    str(entry["llm_scientific_attempt"]).zfill(4)
                    if entry.get("llm_scientific_attempt") is not None
                    else None
                ),
                "integrity_status": entry["integrity_status"],
            }
        )

        dpca_records = read_jsonl(artifact_paths[(cohort, run, "dpca")])
        if {str(item["blind_run_id"]) for item in dpca_records} != {blind_id}:
            raise RuntimeError(f"DPCA blind ID mismatch at {cohort}/{run}")
        base.update(dpca_run_endpoints(dpca_records, cohort=cohort))

        if bool(entry["llm_required"]):
            llm_records = read_jsonl(artifact_paths[(cohort, run, "llm")])
            if {str(item["simulation_run_blind_id"]) for item in llm_records} != {blind_id}:
                raise RuntimeError(f"LLM blind ID mismatch at {cohort}/{run}")
            llm_endpoints = llm_run_endpoints(llm_records, cohort=cohort)
            base.update(llm_endpoints)
            if int(entry["llm_windows"]) != len(llm_records):
                raise RuntimeError(f"LLM window count conflicts with final manifest at {cohort}/{run}")
            if bool(entry["early_stop"]) != bool(llm_endpoints["llm_early_stop"]):
                raise RuntimeError(f"LLM early-stop conflicts with recomputation at {cohort}/{run}")
            if cohort == "target":
                if entry.get("first_indication") != llm_endpoints["llm_first_indication_window"]:
                    raise RuntimeError(f"LLM FIRST_INDICATION conflicts with recomputation at target/{run}")
                if entry.get("confirmed_detection") != llm_endpoints["llm_confirmation_window"]:
                    raise RuntimeError(f"LLM CONFIRMED_DETECTION conflicts with recomputation at target/{run}")
                h3_row, audit = score_h3_run(
                    llm_records,
                    thresholds,
                    simulation_run=run,
                    blind_run_id=blind_id,
                )
                h3_rows.append(h3_row)
                h3_audit.extend(audit)
                base.update(
                    {
                        key: h3_row[key]
                        for key in (
                            "h3_run_score",
                            "h3_applicable_responses",
                            "h3_evidence_items",
                            "h3_verifiable_evidence_items",
                        )
                    }
                )
                token_counts = [int(item["output_token_count"]) for item in llm_records]
                provenance_rows.append(
                    {
                        "cohort": cohort,
                        "simulationRun": run,
                        "blind_run_id": blind_id,
                        "final_llm_scientific_attempt": str(entry["llm_scientific_attempt"]).zfill(4),
                        "configuration_phase": (
                            "BASE_MAX_OUTPUT_TOKENS_768" if run in BASE_OUTPUT_CAP_RUNS else "EFFECTIVE_MAX_OUTPUT_TOKENS_1024"
                        ),
                        "max_output_tokens": 768 if run in BASE_OUTPUT_CAP_RUNS else 1024,
                        "persisted_llm_responses": len(llm_records),
                        "maximum_persisted_output_tokens": max(token_counts),
                        "all_final_responses_serialized_and_persisted": True,
                        "historical_failed_attempt_excluded_from_performance": run == 58,
                        "historical_failed_attempt": "0001" if run == 58 else None,
                        "final_attempt_for_run58": "0002" if run == 58 else None,
                        "analysis_classification": "SECONDARY_OPERATIONAL_DESCRIPTIVE_ONLY",
                    }
                )
            else:
                if entry.get("first_indication") != llm_endpoints["llm_first_raw_false_alarm_window"]:
                    raise RuntimeError(f"NORMAL LLM first raw false alarm conflicts with recomputation at run {run}")
                if entry.get("confirmed_detection") != llm_endpoints["llm_first_confirmed_false_alarm_window"]:
                    raise RuntimeError(f"NORMAL LLM confirmed false alarm conflicts with recomputation at run {run}")
        rows.append(base)

    run_frame = pd.DataFrame(rows, columns=RUN_LEVEL_COLUMNS)
    if len(run_frame) != 1000 or run_frame[["cohort", "simulationRun"]].duplicated().any():
        raise RuntimeError("Canonical run-level table violates one-row-per-run contract")
    h3_frame = pd.DataFrame(h3_rows).sort_values("simulationRun").reset_index(drop=True)
    if len(h3_frame) != 50:
        raise RuntimeError("H3 run table must contain all 50 TARGET LLM runs")
    audit_frame = pd.DataFrame(h3_audit).sort_values(
        ["simulationRun", "window_id", "evidence_index"], na_position="first"
    ).reset_index(drop=True)
    provenance_frame = pd.DataFrame(provenance_rows).sort_values("simulationRun").reset_index(drop=True)
    return run_frame, h3_frame, audit_frame, provenance_frame


def _bool_series(frame: pd.DataFrame, column: str) -> np.ndarray:
    if frame[column].isna().any():
        raise RuntimeError(f"Unexpected missing binary endpoint: {column}")
    return frame[column].astype(bool).to_numpy()


def proportion_row(
    detector: str,
    analysis_set: str,
    cohort: str,
    endpoint: str,
    values: np.ndarray,
) -> dict[str, Any]:
    binary = np.asarray(values, dtype=bool)
    total = len(binary)
    events = int(np.sum(binary))
    lower, upper = wilson_interval(events, total)
    row: dict[str, Any] = {
        "cohort": cohort,
        "detector": detector,
        "analysis_set": analysis_set,
        "endpoint": endpoint,
        "events": events,
        "runs_eligible": total,
        "proportion": events / total,
        "point_estimate_interpretation": (
            "DESCRIPTION_OF_COMPLETE_500_RUN_FORMAL_CORPUS"
            if analysis_set == "expanded"
            else "RUN_LEVEL_SAMPLE_ESTIMATE"
        ),
        "interval_primary": "WILSON_95",
        "interval_interpretation": (
            "MODEL_BASED_EXTRAPOLATION_TO_ANALOGOUS_TEP_TRAJECTORIES_NOT_UNCERTAINTY_OF_OBSERVED_CORPUS"
            if analysis_set == "expanded"
            else "RUN_LEVEL_BINOMIAL_PROPORTION_INTERVAL"
        ),
        "wilson_95_lower": lower,
        "wilson_95_upper": upper,
        "clopper_pearson_sensitivity_applicable": events in {0, total},
        "clopper_pearson_95_lower": None,
        "clopper_pearson_95_upper": None,
    }
    if events in {0, total}:
        cp_lower, cp_upper = clopper_pearson_interval(events, total)
        row["clopper_pearson_95_lower"] = cp_lower
        row["clopper_pearson_95_upper"] = cp_upper
    return row


def _flatten_descriptive(prefix: str, summary: dict[str, Any]) -> dict[str, Any]:
    return {
        f"{prefix}_conditional_n": summary["conditional_n"],
        f"{prefix}_mean": summary["mean"],
        f"{prefix}_sd": summary["sd"],
        f"{prefix}_median": summary["median"],
        f"{prefix}_q1": summary["q1"],
        f"{prefix}_q3": summary["q3"],
        f"{prefix}_iqr": summary["iqr"],
        f"{prefix}_minimum": summary["minimum"],
        f"{prefix}_maximum": summary["maximum"],
        f"{prefix}_mean_ci95_lower": summary["mean_ci"]["lower"],
        f"{prefix}_mean_ci95_upper": summary["mean_ci"]["upper"],
        f"{prefix}_mean_ci_method": summary["mean_ci"]["method"],
        f"{prefix}_mean_ci_fallback_reason": summary["mean_ci"]["fallback_reason"],
        f"{prefix}_median_ci95_lower": summary["median_ci"]["lower"],
        f"{prefix}_median_ci95_upper": summary["median_ci"]["upper"],
        f"{prefix}_median_ci_method": summary["median_ci"]["method"],
        f"{prefix}_median_ci_fallback_reason": summary["median_ci"]["fallback_reason"],
    }


def delay_row(
    detector: str,
    analysis_set: str,
    endpoint: str,
    frame: pd.DataFrame,
    detected_column: str,
    delay_column: str,
) -> dict[str, Any]:
    detected = _bool_series(frame, detected_column)
    delays = frame.loc[detected, delay_column]
    if delays.isna().any() or frame.loc[~detected, delay_column].notna().any():
        raise RuntimeError(f"Detection/delay null contract violated: {detector}/{endpoint}")
    summary = describe_values(delays.astype(float).tolist(), label=f"delay:{analysis_set}:{detector}:{endpoint}")
    return {
        "cohort": "target",
        "detector": detector,
        "analysis_set": analysis_set,
        "endpoint": endpoint,
        "total_runs": len(frame),
        "event_runs": int(np.sum(detected)),
        "point_estimate_interpretation": (
            "CONDITIONAL_DESCRIPTION_OF_COMPLETE_500_RUN_FORMAL_CORPUS"
            if analysis_set == "expanded"
            else "CONDITIONAL_RUN_LEVEL_SAMPLE_ESTIMATE"
        ),
        "bootstrap_interval_interpretation": (
            "MODEL_BASED_EXTRAPOLATION_TO_ANALOGOUS_TEP_TRAJECTORIES_NOT_UNCERTAINTY_OF_OBSERVED_CORPUS"
            if analysis_set == "expanded"
            else "RUN_LEVEL_BOOTSTRAP_INTERVAL"
        ),
        **_flatten_descriptive("delay_minutes", summary),
    }


def build_statistical_tables(
    repo_root: Path,
    run_frame: pd.DataFrame,
    h3_frame: pd.DataFrame,
    h3_audit: pd.DataFrame,
    provenance_frame: pd.DataFrame,
) -> dict[str, Any]:
    target_selected = set(
        int(value)
        for value in read_git_json(
            repo_root, "repo/experiments/tep/local_llm/config/formal_run_selection.json"
        )["selected_simulation_runs"]
    )
    normal_selected = set(
        int(value)
        for value in read_git_json(
            repo_root, "repo/experiments/tep/local_llm/config/formal_normal_holdout_selection.json"
        )["selected_simulation_runs"]
    )
    target_all = run_frame[run_frame["cohort"] == "target"].copy()
    normal_all = run_frame[run_frame["cohort"] == "normal_holdout"].copy()
    target_pair = target_all[target_all["simulationRun"].isin(target_selected)].sort_values("simulationRun").copy()
    normal_pair = normal_all[normal_all["simulationRun"].isin(normal_selected)].sort_values("simulationRun").copy()
    if len(target_pair) != 50 or len(normal_pair) != 50:
        raise RuntimeError("Paired analysis sets must contain exactly 50 runs per cohort")

    h1_rows: list[dict[str, Any]] = []
    for detector, analysis_set, frame, raw_col, confirmed_col in (
        ("LLM", "principal", target_pair, "llm_raw_post_onset", "llm_confirmed_post_onset"),
        ("DPCA", "paired", target_pair, "dpca_raw_post_onset", "dpca_confirmed_post_onset"),
    ):
        confirmed = _bool_series(frame, confirmed_col)
        h1_rows.extend(
            [
                proportion_row(detector, analysis_set, "target", "raw_post_onset_indication", _bool_series(frame, raw_col)),
                proportion_row(detector, analysis_set, "target", "confirmed_post_onset_detection", confirmed),
                proportion_row(detector, analysis_set, "target", "no_confirmed_post_onset_detection", ~confirmed),
            ]
        )
    table_b = pd.DataFrame(h1_rows)

    normal_rows: list[dict[str, Any]] = []
    for detector, analysis_set, frame, raw_col, confirmed_col in (
        ("LLM", "principal", normal_pair, "llm_any_raw_false_alarm", "llm_any_confirmed_false_alarm"),
        ("DPCA", "paired", normal_pair, "dpca_any_raw_false_alarm", "dpca_any_confirmed_false_alarm"),
    ):
        confirmed = _bool_series(frame, confirmed_col)
        normal_rows.extend(
            [
                proportion_row(detector, analysis_set, "normal_holdout", "any_raw_false_alarm", _bool_series(frame, raw_col)),
                proportion_row(detector, analysis_set, "normal_holdout", "any_confirmed_false_alarm", confirmed),
                proportion_row(detector, analysis_set, "normal_holdout", "no_confirmed_false_alarm", ~confirmed),
            ]
        )
    table_c = pd.DataFrame(normal_rows)

    paired_specs = [
        ("target", "raw_post_onset_indication", target_pair, "llm_raw_post_onset", "dpca_raw_post_onset", False),
        ("target", "confirmed_post_onset_detection", target_pair, "llm_confirmed_post_onset", "dpca_confirmed_post_onset", True),
        ("normal_holdout", "raw_false_alarm", normal_pair, "llm_any_raw_false_alarm", "dpca_any_raw_false_alarm", False),
        ("normal_holdout", "confirmed_false_alarm", normal_pair, "llm_any_confirmed_false_alarm", "dpca_any_confirmed_false_alarm", True),
    ]
    paired_rows: list[dict[str, Any]] = []
    for cohort, endpoint, frame, left_col, right_col, primary in paired_specs:
        summary = paired_binary_summary(
            _bool_series(frame, left_col),
            _bool_series(frame, right_col),
            label=f"paired_binary:{cohort}:{endpoint}",
        )
        paired_rows.append(
            {
                "cohort": cohort,
                "endpoint": endpoint,
                "classification": "PRIMARY" if primary else "SECONDARY",
                "p_value_family": "PRIMARY_CONFIRMED_BINARY" if primary else "SECONDARY_RAW_BINARY",
                "pairs": summary["pairs"],
                "llm0_dpca0": summary["llm0_dpca0"],
                "llm0_dpca1": summary["llm0_dpca1"],
                "llm1_dpca0": summary["llm1_dpca0"],
                "llm1_dpca1": summary["llm1_dpca1"],
                "concordant_pairs": summary["concordant_pairs"],
                "concordance": summary["concordance"],
                "dpca_only": summary["dpca_only"],
                "llm_only": summary["llm_only"],
                "paired_difference_llm_minus_dpca": summary["paired_proportion_difference_llm_minus_dpca"],
                "paired_difference_ci95_lower": summary["paired_difference_ci"]["lower"],
                "paired_difference_ci95_upper": summary["paired_difference_ci"]["upper"],
                "paired_difference_ci_method": summary["paired_difference_ci"]["method"],
                "paired_difference_ci_fallback_reason": summary["paired_difference_ci"]["fallback_reason"],
                "mcnemar_exact_two_sided_p_raw": summary["mcnemar"]["p_value"],
                "mcnemar_status": summary["mcnemar"]["status"],
                "mcnemar_exact_two_sided_p_holm_primary_family": None,
                "mcnemar_exact_two_sided_p_holm_secondary_raw_family": None,
            }
        )
    primary_indices = [index for index, row in enumerate(paired_rows) if row["classification"] == "PRIMARY"]
    adjusted = holm_adjust([paired_rows[index]["mcnemar_exact_two_sided_p_raw"] for index in primary_indices])
    for index, p_adjusted in zip(primary_indices, adjusted):
        paired_rows[index]["mcnemar_exact_two_sided_p_holm_primary_family"] = p_adjusted
    secondary_binary_indices = [
        index for index, row in enumerate(paired_rows) if row["classification"] == "SECONDARY"
    ]
    secondary_binary_adjusted = holm_adjust(
        [paired_rows[index]["mcnemar_exact_two_sided_p_raw"] for index in secondary_binary_indices]
    )
    for index, p_adjusted in zip(secondary_binary_indices, secondary_binary_adjusted):
        paired_rows[index]["mcnemar_exact_two_sided_p_holm_secondary_raw_family"] = p_adjusted
    paired_binary = pd.DataFrame(paired_rows)

    pre_rows: list[dict[str, Any]] = []
    for detector, analysis_set, frame, raw_col, confirmed_col in (
        ("LLM", "principal", target_pair, "llm_raw_pre_onset", "llm_confirmed_pre_onset"),
        ("DPCA", "paired", target_pair, "dpca_raw_pre_onset", "dpca_confirmed_pre_onset"),
        ("DPCA", "expanded", target_all, "dpca_raw_pre_onset", "dpca_confirmed_pre_onset"),
    ):
        pre_rows.extend(
            [
                proportion_row(detector, analysis_set, "target", "raw_pre_onset_false_alarm", _bool_series(frame, raw_col)),
                proportion_row(detector, analysis_set, "target", "confirmed_pre_onset_false_alarm", _bool_series(frame, confirmed_col)),
            ]
        )
    table_d = pd.DataFrame(pre_rows)

    delay_rows: list[dict[str, Any]] = []
    for detector, analysis_set, frame, raw_detected, raw_delay, confirmed_detected, confirmed_delay in (
        ("LLM", "principal", target_pair, "llm_raw_post_onset", "llm_raw_delay_minutes", "llm_confirmed_post_onset", "llm_confirmed_delay_minutes"),
        ("DPCA", "paired", target_pair, "dpca_raw_post_onset", "dpca_raw_delay_minutes", "dpca_confirmed_post_onset", "dpca_confirmed_delay_minutes"),
        ("DPCA", "expanded", target_all, "dpca_raw_post_onset", "dpca_raw_delay_minutes", "dpca_confirmed_post_onset", "dpca_confirmed_delay_minutes"),
    ):
        delay_rows.append(delay_row(detector, analysis_set, "raw_post_onset_indication", frame, raw_detected, raw_delay))
        delay_rows.append(delay_row(detector, analysis_set, "confirmed_post_onset_detection", frame, confirmed_detected, confirmed_delay))
    table_e = pd.DataFrame(delay_rows)

    paired_delay_rows: list[dict[str, Any]] = []
    for endpoint, llm_detected_col, dpca_detected_col, llm_delay_col, dpca_delay_col in (
        ("raw_post_onset_indication", "llm_raw_post_onset", "dpca_raw_post_onset", "llm_raw_delay_minutes", "dpca_raw_delay_minutes"),
        ("confirmed_post_onset_detection", "llm_confirmed_post_onset", "dpca_confirmed_post_onset", "llm_confirmed_delay_minutes", "dpca_confirmed_delay_minutes"),
    ):
        llm_detected = _bool_series(target_pair, llm_detected_col)
        dpca_detected = _bool_series(target_pair, dpca_detected_col)
        both = llm_detected & dpca_detected
        differences = (
            target_pair.loc[both, llm_delay_col].astype(float).to_numpy()
            - target_pair.loc[both, dpca_delay_col].astype(float).to_numpy()
        )
        if target_pair.loc[both, [llm_delay_col, dpca_delay_col]].isna().any().any():
            raise RuntimeError("Paired delay comparison contains missing delay among both-detected pairs")
        descriptive = describe_values(differences, label=f"paired_delay:{endpoint}")
        sign = exact_sign_test(differences)
        paired_delay_rows.append(
            {
                "cohort": "target",
                "endpoint": endpoint,
                "classification": "SECONDARY",
                "p_value_family": "SECONDARY_PAIRED_DELAY_SIGN_TESTS",
                "total_pairs": len(target_pair),
                "neither_detected": int(np.sum(~llm_detected & ~dpca_detected)),
                "llm_only": int(np.sum(llm_detected & ~dpca_detected)),
                "dpca_only": int(np.sum(~llm_detected & dpca_detected)),
                "both_detected": int(np.sum(both)),
                **_flatten_descriptive("difference_llm_minus_dpca_minutes", descriptive),
                "sign_test_positive": sign["positive"],
                "sign_test_negative": sign["negative"],
                "sign_test_ties": sign["ties"],
                "sign_test_binomial_denominator": sign["binomial_denominator"],
                "sign_test_exact_two_sided_p": sign["p_value"],
                "sign_test_exact_two_sided_p_holm_secondary_delay_family": None,
                "sign_test_status": sign["status"],
                "conditioning": "ONLY_PAIRS_WHERE_SAME_ENDPOINT_DEFINED_FOR_BOTH",
            }
        )
    paired_delays = pd.DataFrame(paired_delay_rows)
    delay_adjusted = holm_adjust(paired_delays["sign_test_exact_two_sided_p"].astype(float).tolist())
    paired_delays["sign_test_exact_two_sided_p_holm_secondary_delay_family"] = delay_adjusted

    expanded_rows: list[dict[str, Any]] = []
    for cohort, frame, raw_col, confirmed_col in (
        ("target", target_all, "dpca_raw_post_onset", "dpca_confirmed_post_onset"),
        ("normal_holdout", normal_all, "dpca_any_raw_false_alarm", "dpca_any_confirmed_false_alarm"),
    ):
        raw_name = "raw_post_onset_indication" if cohort == "target" else "any_raw_false_alarm"
        confirmed_name = "confirmed_post_onset_detection" if cohort == "target" else "any_confirmed_false_alarm"
        confirmed = _bool_series(frame, confirmed_col)
        expanded_rows.extend(
            [
                proportion_row("DPCA", "expanded", cohort, raw_name, _bool_series(frame, raw_col)),
                proportion_row("DPCA", "expanded", cohort, confirmed_name, confirmed),
                proportion_row("DPCA", "expanded", cohort, f"no_{confirmed_name}", ~confirmed),
            ]
        )
    dpca_expanded = pd.DataFrame(expanded_rows)

    run_scores = h3_frame["h3_run_score"].dropna().astype(float).tolist()
    macro = describe_values(run_scores, label="h3:macro_run_score")
    total_items = int(h3_frame["h3_evidence_items"].sum())
    verifiable_items = int(h3_frame["h3_verifiable_evidence_items"].sum())
    passing_items = int(h3_frame["h3_passing_evidence_items"].sum())
    h3_statistics = {
        "scope": "50 TARGET LLM final scientific attempts",
        "total_target_llm_runs": len(h3_frame),
        "applicable_runs": len(run_scores),
        "non_applicable_runs": len(h3_frame) - len(run_scores),
        "total_evidence_items": total_items,
        "verifiable_evidence_items": verifiable_items,
        "coverage": verifiable_items / total_items if total_items else None,
        "primary_macro_run_score": macro,
        "secondary_micro_item_score": passing_items / total_items if total_items else None,
        "secondary_micro_numerator_passing_items": passing_items,
        "secondary_micro_denominator_evidence_items": total_items,
        "observation_used_for_primary_score": False,
        "unsupported_process_claims": "NOT_CODED_NO_FROZEN_RULE_QUALITATIVE_AUDIT_ONLY",
        "resampling_unit": "simulationRun",
    }
    h3_table_rows = [
        {"metric": "total_target_llm_runs", "value": len(h3_frame), "denominator": 50, "classification": "PRIMARY_SCOPE"},
        {"metric": "applicable_runs", "value": len(run_scores), "denominator": 50, "classification": "PRIMARY"},
        {"metric": "non_applicable_runs", "value": len(h3_frame) - len(run_scores), "denominator": 50, "classification": "PRIMARY"},
        {"metric": "total_evidence_items", "value": total_items, "denominator": total_items, "classification": "AUDIT"},
        {"metric": "verifiable_evidence_items", "value": verifiable_items, "denominator": total_items, "classification": "AUDIT"},
        {"metric": "coverage", "value": h3_statistics["coverage"], "denominator": total_items, "classification": "PRIMARY"},
        {"metric": "macro_mean_run_score", "value": macro["mean"], "denominator": len(run_scores), "classification": "PRIMARY"},
        {"metric": "macro_mean_ci95_lower", "value": macro["mean_ci"]["lower"], "denominator": len(run_scores), "classification": "PRIMARY"},
        {"metric": "macro_mean_ci95_upper", "value": macro["mean_ci"]["upper"], "denominator": len(run_scores), "classification": "PRIMARY"},
        {"metric": "run_score_sd", "value": macro["sd"], "denominator": len(run_scores), "classification": "DESCRIPTIVE"},
        {"metric": "run_score_median", "value": macro["median"], "denominator": len(run_scores), "classification": "DESCRIPTIVE"},
        {"metric": "run_score_q1", "value": macro["q1"], "denominator": len(run_scores), "classification": "DESCRIPTIVE"},
        {"metric": "run_score_q3", "value": macro["q3"], "denominator": len(run_scores), "classification": "DESCRIPTIVE"},
        {"metric": "run_score_minimum", "value": macro["minimum"], "denominator": len(run_scores), "classification": "DESCRIPTIVE"},
        {"metric": "run_score_maximum", "value": macro["maximum"], "denominator": len(run_scores), "classification": "DESCRIPTIVE"},
        {"metric": "secondary_micro_item_score", "value": h3_statistics["secondary_micro_item_score"], "denominator": total_items, "classification": "SECONDARY_MICRO"},
    ]
    table_g = pd.DataFrame(h3_table_rows)

    primary_statistics = {
        "h1_target": table_b.to_dict(orient="records"),
        "normal_holdout_false_alarm": table_c.to_dict(orient="records"),
        "paired_binary": paired_binary.to_dict(orient="records"),
        "primary_mcnemar_family": {
            "members": ["target/confirmed_post_onset_detection", "normal_holdout/confirmed_false_alarm"],
            "adjustment": "Holm",
        },
        "secondary_raw_mcnemar_family": {
            "members": ["target/raw_post_onset_indication", "normal_holdout/raw_false_alarm"],
            "adjustment": "Holm",
        },
        "secondary_paired_delay_sign_test_family": {
            "members": ["target/raw_post_onset_indication", "target/confirmed_post_onset_detection"],
            "adjustment": "Holm",
        },
        "automatic_hypothesis_accept_reject": False,
    }
    campaign_manifest = read_json(repo_root / MANIFEST_REPO_PATH)
    incident_rows: list[dict[str, Any]] = []
    for item in campaign_manifest.get("historical_attempts", []):
        incident_rows.append(
            {
                "record_type": "HISTORICAL_ATTEMPT",
                "namespace": item.get("namespace"),
                "cohort": item.get("cohort"),
                "simulationRun": item.get("simulationRun"),
                "attempt_id": item.get("attempt_id"),
                "status": item.get("status"),
                "component": item.get("component"),
                "description": item.get("registered_error_message"),
                "superseded_by_complete": item.get("superseded_by_complete"),
                "invalidates_campaign": False,
                "scientific_result_effect": "NONE_FINAL_ATTEMPT_FROM_MANIFEST_ONLY",
            }
        )
    for item in campaign_manifest.get("non_invalidating_anomalies", []):
        incident_rows.append(
            {
                "record_type": "NON_INVALIDATING_ANOMALY",
                "namespace": None,
                "cohort": item.get("cohort"),
                "simulationRun": item.get("simulationRun"),
                "attempt_id": None,
                "status": "DOCUMENTED",
                "component": None,
                "description": item.get("observed"),
                "superseded_by_complete": None,
                "invalidates_campaign": bool(item.get("invalidates_campaign")),
                "scientific_result_effect": item.get("effect_on_validated_final_result", "NONE"),
            }
        )
    incidents = pd.DataFrame(incident_rows)
    return {
        "target_all": target_all,
        "normal_all": normal_all,
        "target_pair": target_pair,
        "normal_pair": normal_pair,
        "table_b": table_b,
        "table_c": table_c,
        "paired_binary": paired_binary,
        "primary_statistics": primary_statistics,
        "table_d": table_d,
        "table_e": table_e,
        "paired_delays": paired_delays,
        "dpca_expanded": dpca_expanded,
        "table_g": table_g,
        "h3_statistics": h3_statistics,
        "h3_audit": h3_audit,
        "provenance": provenance_frame,
        "incidents": incidents,
    }


def _figure_style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 140,
            "savefig.dpi": 180,
            "font.size": 9,
            "axes.titlesize": 11,
            "axes.labelsize": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


def _save_figure(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    if not path.exists() or path.stat().st_size < 1_000:
        raise RuntimeError(f"Figure generation failed: {path}")


def create_figures(output_root: Path, tables: dict[str, Any], h3_frame: pd.DataFrame) -> list[Path]:
    _figure_style()
    figure_root = output_root / "05_figures"
    paths: list[Path] = []

    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.axis("off")
    boxes = [
        (0.50, 0.83, "Formal corpus\n1,000 runs\n500 TARGET + 500 NORMAL"),
        (0.23, 0.51, "DPCA expanded\n1,000 runs\n500 + 500"),
        (0.77, 0.51, "LLM principal\n100 runs\n50 + 50"),
        (0.50, 0.16, "Paired comparison\n100 pairs total\n50 per cohort"),
    ]
    for x, y, text in boxes:
        ax.text(
            x,
            y,
            text,
            transform=ax.transAxes,
            ha="center",
            va="center",
            bbox={"boxstyle": "round,pad=0.7", "facecolor": "#e8f1f8", "edgecolor": "#3b6f8f"},
        )
    arrows = [
        ((0.46, 0.75), (0.28, 0.61)),
        ((0.54, 0.75), (0.72, 0.61)),
        ((0.28, 0.41), (0.44, 0.25)),
        ((0.72, 0.41), (0.56, 0.25)),
    ]
    for start, end in arrows:
        ax.annotate("", xy=end, xytext=start, xycoords="axes fraction", arrowprops={"arrowstyle": "->", "color": "#455a64"})
    ax.set_title("Formal analysis populations and inferential denominators")
    path = figure_root / "01_population_flow.png"
    _save_figure(fig, path)
    paths.append(path)

    confirmed = pd.concat(
        [
            tables["table_b"].query("endpoint == 'confirmed_post_onset_detection'"),
            tables["table_c"].query("endpoint == 'any_confirmed_false_alarm'"),
        ],
        ignore_index=True,
    )
    labels = [f"{row.cohort}\n{row.detector} ({row.analysis_set})" for row in confirmed.itertuples()]
    estimates = confirmed["proportion"].to_numpy(float)
    lowers = confirmed["wilson_95_lower"].to_numpy(float)
    uppers = confirmed["wilson_95_upper"].to_numpy(float)
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    positions = np.arange(len(labels))
    ax.errorbar(estimates, positions, xerr=[estimates - lowers, uppers - estimates], fmt="o", color="#24557a", capsize=4)
    ax.set_yticks(positions, labels)
    ax.set_xlim(-0.02, 1.02)
    ax.set_xlabel("Run-level proportion (Wilson 95% CI)")
    ax.set_title("Primary confirmed endpoints")
    ax.grid(axis="x", alpha=0.25)
    path = figure_root / "02_proportions_wilson.png"
    _save_figure(fig, path)
    paths.append(path)

    paired_primary = tables["paired_binary"]
    cell_columns = ["llm0_dpca0", "llm0_dpca1", "llm1_dpca0", "llm1_dpca1"]
    cell_labels = ["Neither", "DPCA only", "LLM only", "Both"]
    colors = ["#d9e3ea", "#f4a261", "#2a9d8f", "#416788"]
    fig, ax = plt.subplots(figsize=(10.5, 4.8))
    bottoms = np.zeros(len(paired_primary))
    x = np.arange(len(paired_primary))
    for column, label, color in zip(cell_columns, cell_labels, colors):
        values = paired_primary[column].to_numpy(int)
        ax.bar(x, values, bottom=bottoms, label=label, color=color)
        bottoms += values
    endpoint_labels = {
        ("target", "raw_post_onset_indication"): "TARGET\nraw indication",
        ("target", "confirmed_post_onset_detection"): "TARGET\nconfirmed",
        ("normal_holdout", "raw_false_alarm"): "NORMAL\nraw false alarm",
        ("normal_holdout", "confirmed_false_alarm"): "NORMAL\nconfirmed false alarm",
    }
    ax.set_xticks(x, [endpoint_labels[(r.cohort, r.endpoint)] for r in paired_primary.itertuples()])
    ax.set_ylabel("Paired simulationRuns (n=50)")
    ax.set_title("Paired concordance and discordance")
    ax.legend(ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    path = figure_root / "03_paired_concordance.png"
    _save_figure(fig, path)
    paths.append(path)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharey=True)
    target_pair = tables["target_pair"]
    for ax, endpoint_label, llm_column, dpca_column in (
        (axes[0], "Raw indication", "llm_raw_delay_minutes", "dpca_raw_delay_minutes"),
        (axes[1], "Confirmed detection", "llm_confirmed_delay_minutes", "dpca_confirmed_delay_minutes"),
    ):
        for detector, column, color in (
            ("LLM", llm_column, "#2a9d8f"),
            ("DPCA", dpca_column, "#416788"),
        ):
            values = np.sort(target_pair[column].dropna().astype(float).to_numpy())
            if len(values):
                ax.step(values, np.arange(1, len(values) + 1) / len(values), where="post", label=f"{detector} (n={len(values)})", color=color)
        ax.set_xlabel("Delay (minutes; conditional on event)")
        ax.set_title(endpoint_label)
        ax.grid(alpha=0.25)
        ax.legend()
    axes[0].set_ylabel("ECDF")
    fig.suptitle("Conditional TARGET delay distributions")
    path = figure_root / "04_delay_ecdf.png"
    _save_figure(fig, path)
    paths.append(path)

    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=False)
    for ax, endpoint_label, llm_column, dpca_column in (
        (axes[0], "Raw indication", "llm_raw_delay_minutes", "dpca_raw_delay_minutes"),
        (axes[1], "Confirmed detection", "llm_confirmed_delay_minutes", "dpca_confirmed_delay_minutes"),
    ):
        both = target_pair[llm_column].notna() & target_pair[dpca_column].notna()
        delay_pairs = target_pair.loc[both, ["simulationRun", llm_column, dpca_column]].copy()
        delay_pairs["difference"] = delay_pairs[llm_column] - delay_pairs[dpca_column]
        if len(delay_pairs):
            ax.scatter(np.arange(len(delay_pairs)), delay_pairs["difference"], color="#6a4c93", s=20)
            ax.set_xticks(np.arange(len(delay_pairs)), delay_pairs["simulationRun"].astype(str), rotation=90, fontsize=6)
        ax.axhline(0, color="black", linewidth=1, linestyle="--")
        ax.set_xlabel("TARGET simulationRun (both events)")
        ax.set_title(f"{endpoint_label} (n={len(delay_pairs)})")
        ax.grid(axis="y", alpha=0.25)
    axes[0].set_ylabel("LLM − DPCA delay (minutes)")
    axes[1].set_ylabel("LLM − DPCA delay (minutes)")
    fig.suptitle("Paired TARGET delay differences")
    path = figure_root / "05_paired_delay_differences.png"
    _save_figure(fig, path)
    paths.append(path)

    scores = h3_frame["h3_run_score"].dropna().astype(float)
    fig, ax = plt.subplots(figsize=(8, 4.8))
    if len(scores):
        bins = min(12, max(4, int(math.sqrt(len(scores)))))
        ax.hist(scores, bins=bins, color="#457b9d", edgecolor="white")
    ax.set_xlabel("H3 run_score (applicable TARGET LLM runs)")
    ax.set_ylabel("simulationRuns")
    ax.set_title("Distribution of run-level groundedness scores")
    ax.grid(axis="y", alpha=0.25)
    path = figure_root / "06_h3_run_score_distribution.png"
    _save_figure(fig, path)
    paths.append(path)

    dpca = tables["dpca_expanded"].query("endpoint in ['raw_post_onset_indication', 'confirmed_post_onset_detection', 'any_raw_false_alarm', 'any_confirmed_false_alarm']")
    fig, ax = plt.subplots(figsize=(9.5, 4.7))
    x = np.arange(len(dpca))
    estimates = dpca["proportion"].to_numpy(float)
    lower = dpca["wilson_95_lower"].to_numpy(float)
    upper = dpca["wilson_95_upper"].to_numpy(float)
    ax.errorbar(x, estimates, yerr=[estimates - lower, upper - estimates], fmt="o", capsize=5, color="#264653")
    expanded_labels = {
        ("target", "raw_post_onset_indication"): "TARGET\nraw indication",
        ("target", "confirmed_post_onset_detection"): "TARGET\nconfirmed",
        ("normal_holdout", "any_raw_false_alarm"): "NORMAL\nraw false alarm",
        ("normal_holdout", "any_confirmed_false_alarm"): "NORMAL\nconfirmed false alarm",
    }
    ax.set_xticks(x, [expanded_labels[(row.cohort, row.endpoint)] for row in dpca.itertuples()])
    ax.set_ylim(-0.02, 1.02)
    ax.set_ylabel("DPCA run-level proportion (Wilson 95% CI)")
    ax.set_title("Expanded DPCA context (500 runs per cohort)")
    ax.grid(axis="y", alpha=0.25)
    path = figure_root / "07_dpca_expanded.png"
    _save_figure(fig, path)
    paths.append(path)

    provenance = tables["provenance"]
    fig, ax = plt.subplots(figsize=(10, 3.7))
    base_phase = provenance["configuration_phase"] == "BASE_MAX_OUTPUT_TOKENS_768"
    ax.scatter(provenance.loc[base_phase, "simulationRun"], np.ones(base_phase.sum()), label="Base cap 768", color="#e76f51", s=34)
    ax.scatter(provenance.loc[~base_phase, "simulationRun"], np.ones((~base_phase).sum()), label="Effective cap 1024", color="#2a9d8f", s=34)
    incidents = tables["incidents"].dropna(subset=["simulationRun"]).copy()
    target_incidents = incidents[incidents["cohort"] == "target"].drop_duplicates(["simulationRun"])
    normal_incidents = incidents[incidents["cohort"] == "normal_holdout"].drop_duplicates(["simulationRun"])
    ax.scatter(target_incidents["simulationRun"], np.full(len(target_incidents), 0.72), marker="x", color="#6a4c93", s=42, label="TARGET operational incident")
    ax.scatter(normal_incidents["simulationRun"], np.full(len(normal_incidents), 0.52), marker="x", color="#f4a261", s=42, label="NORMAL operational incident")
    if 58 in provenance["simulationRun"].values:
        ax.annotate("run58 final attempt 0002", xy=(58, 1), xytext=(90, 1.18), arrowprops={"arrowstyle": "->", "color": "#444"})
    ax.text(490, 0.36, "Outer duration telemetry invalid for cost analysis (all 1,000)", ha="right", va="center", fontsize=8, color="#555")
    ax.set_yticks([1, 0.72, 0.52], ["TARGET LLM final runs", "TARGET incidents", "NORMAL incidents"])
    ax.set_xlabel("simulationRun")
    ax.set_ylim(0.28, 1.35)
    ax.set_title("Operational provenance of the 768→1024 amendment (descriptive only)")
    ax.legend(ncol=2, loc="upper right", fontsize=8)
    ax.grid(axis="x", alpha=0.2)
    path = figure_root / "08_provenance_incidents.png"
    _save_figure(fig, path)
    paths.append(path)

    return paths


def analysis_code_inventory(repo_root: Path, output_root: Path) -> tuple[str, list[dict[str, Any]]]:
    code_root = output_root / "code"
    files = sorted(path for path in code_root.rglob("*") if path.is_file() and "__pycache__" not in path.parts)
    inventory = [{"path": rel(repo_root, path), "sha256": sha256_file(path), "size_bytes": path.stat().st_size} for path in files]
    digest = hashlib.sha256()
    for item in inventory:
        digest.update(item["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(item["sha256"].encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest(), inventory


def materialize_full_analysis(
    repo_root: Path,
    initial_report: dict[str, Any],
    artifact_paths: dict[tuple[str, int, str], Path],
) -> None:
    if initial_report["gate_status"] != "PASS":
        raise RuntimeError("Integrity gate must pass before aggregate analysis")
    output_root = repo_root / "analysis" / "formal" / METHOD_FREEZE
    run_frame, h3_frame, h3_audit, provenance = build_run_level(repo_root, artifact_paths)
    tables = build_statistical_tables(repo_root, run_frame, h3_frame, h3_audit, provenance)

    write_csv(output_root / "01_run_level" / "run_level_endpoints.csv", run_frame)
    write_csv(output_root / "01_run_level" / "h3_run_scores.csv", h3_frame)
    write_csv(output_root / "02_primary" / "table_B_h1_target.csv", tables["table_b"])
    write_csv(output_root / "02_primary" / "table_C_false_alarm_normal.csv", tables["table_c"])
    write_csv(output_root / "02_primary" / "primary_paired_binary.csv", tables["paired_binary"])
    atomic_json(output_root / "02_primary" / "primary_statistics.json", tables["primary_statistics"])
    write_csv(output_root / "03_secondary" / "table_D_target_preonset.csv", tables["table_d"])
    write_csv(output_root / "03_secondary" / "table_E_h2_delays.csv", tables["table_e"])
    write_csv(output_root / "03_secondary" / "paired_delays.csv", tables["paired_delays"])
    write_csv(output_root / "03_secondary" / "dpca_expanded.csv", tables["dpca_expanded"])
    write_csv(output_root / "03_secondary" / "amendment_provenance.csv", tables["provenance"])
    write_csv(output_root / "03_secondary" / "incident_provenance.csv", tables["incidents"])
    write_csv(output_root / "04_h3" / "table_G_h3.csv", tables["table_g"])
    write_csv(output_root / "04_h3" / "h3_evidence_audit.csv", tables["h3_audit"])
    atomic_json(output_root / "04_h3" / "h3_statistics.json", tables["h3_statistics"])
    figures = create_figures(output_root, tables, h3_frame)
    if len(figures) != 8:
        raise RuntimeError("Exactly eight SAP-predefined figures are required")

    final_report, final_paths = validate_integrity(repo_root)
    if final_report["gate_status"] != "PASS":
        raise RuntimeError("Final input rehash failed after aggregate analysis")
    initial_hashes = {
        row["primary_artifact_path"]: row["primary_artifact_observed_sha256"]
        for row in initial_report["input_artifacts"]
    }
    final_hashes = {
        row["primary_artifact_path"]: row["primary_artifact_observed_sha256"]
        for row in final_report["input_artifacts"]
    }
    if initial_hashes != final_hashes or set(final_paths) != set(artifact_paths):
        raise RuntimeError("Input artifact inventory changed during analysis")

    environment = {
        "generated_at_utc": utc_now(),
        "source_repository": SOURCE_REPOSITORY,
        "source_main_commit": SOURCE_MAIN_COMMIT,
        "analysis_branch": ANALYSIS_BRANCH,
        "analysis_head_at_execution": initial_report["authority"]["analysis_head_at_validation"],
        "analysis_code_commit": None,
        "analysis_code_commit_policy": "The final commit cannot self-reference its own SHA; it is reported in Git branch history and the delivery report. Internal code identity is analysis_code_sha256.",
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
        "scipy_version": scipy.__version__,
        "matplotlib_version": matplotlib.__version__,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "linked_technical_git_blobs": initial_report["authority"]["linked_technical_sources"],
        "network_access_required": False,
        "scientific_inference_executed": False,
        "dpca_executed": False,
        "scientific_inputs_opened_read_only": True,
    }
    atomic_json(output_root / "06_audit" / "analysis_environment.json", environment)
    atomic_json(
        output_root / "06_audit" / "input_hash_validation.json",
        {
            "validation_before_statistics": {
                "status": initial_report["gate_status"],
                "timestamp_utc": initial_report["generated_at_utc"],
                "count": len(initial_report["input_artifacts"]),
            },
            "validation_after_statistics": {
                "status": final_report["gate_status"],
                "timestamp_utc": final_report["generated_at_utc"],
                "count": len(final_report["input_artifacts"]),
            },
            "input_results_modified": False,
            "inventories_identical": True,
            "artifacts": final_report["input_artifacts"],
        },
    )
    methods = {
        "authority": SAP_REPO_PATH,
        "method_freeze": METHOD_FREEZE,
        "inferential_unit": "simulationRun",
        "paired_cluster": "same simulationRun LLM-DPCA pair",
        "window_level_inference": False,
        "llm_confirmation": "FIRST_INDICATION_CONCURRENT_FULL_SAMPLE_REFRESH_V1; candidate k ANOMALY confirmed only by ANOMALY at k+4",
        "llm_onset_reset": True,
        "dpca_persistence": 3,
        "dpca_onset_reset": True,
        "proportion_interval_primary": "Wilson 95%",
        "boundary_sensitivity_interval": "Clopper-Pearson exact 95% when events=0 or events=n",
        "paired_binary_test": "exact two-sided McNemar using discordant pairs",
        "primary_p_value_adjustment": "Holm over TARGET confirmed detection and NORMAL confirmed false alarm",
        "secondary_p_value_adjustment": {
            "raw_paired_binary_family": "Holm over TARGET raw indication and NORMAL raw false alarm",
            "paired_delay_sign_test_family": "Holm over raw and confirmed TARGET paired-delay sign tests",
        },
        "bootstrap": {
            "replicates": BOOTSTRAP_REPLICATES,
            "base_seed": BOOTSTRAP_SEED,
            "rng_initialization": "Each interval initializes numpy.default_rng with the exact frozen seed 20260820",
            "interval": "BCa 95% preferred; percentile 95% fallback with reason",
            "unit": "whole simulationRun or indivisible paired run difference",
        },
        "sign_test": "exact two-sided binomial, exact-zero ties reported and excluded",
        "n_zero": "undefined/null; no interval",
        "n_one": "individual value; no SD/IQR/inferential interval",
        "non_detection_delay": None,
        "h3": {
            "scope": "50 TARGET LLM final attempts",
            "primary": "equal-weight macro mean of applicable run_scores",
            "observation_in_primary_score": False,
            "unsupported_process_claims": "qualitative audit only; no frozen automatic rule",
            "micro": "secondary only with explicit evidence-item denominator",
        },
        "automatic_hypothesis_accept_reject": False,
    }
    atomic_json(output_root / "06_audit" / "statistical_methods.json", methods)

    audit_text = f"""# Frozen SAP analysis audit

- Generated (UTC): `{utc_now()}`
- Source repository: `{SOURCE_REPOSITORY}`
- Source main commit: `{SOURCE_MAIN_COMMIT}`
- Analysis branch: `{ANALYSIS_BRANCH}`
- Method freeze: `{METHOD_FREEZE}`
- Final campaign manifest SHA-256: `{EXPECTED_FINAL_MANIFEST_SHA256}`
- SAP Git blob: `{EXPECTED_SAP_BLOB}`
- SAP canonical Git-blob SHA-256: `{initial_report['authority']['sap_sha256_canonical_git_blob']}`
- Six SAP-linked technical Git blobs: `PASS`
- Primary inputs rehashed before/after: `1,100 / 1,100`, zero mismatch
- Denominator gate: `PASS`
- Canonical run-level rows: `1,000`
- Bootstrap: `{BOOTSTRAP_REPLICATES:,}` replicates, base seed `{BOOTSTRAP_SEED}`
- Inferential/resampling unit: complete `simulationRun`; paired runs remain indivisible
- LLM or DPCA scientific execution: `NO`
- Input result mutation: `NO`

The final Git commit SHA is reported by branch history and the delivery report;
it cannot be embedded inside the commit that determines that same SHA. The
internal code identity is the composite `analysis_code_sha256` in
`ANALYSIS_MANIFEST.json`.

The first materialized analysis output was the integrity report and denominator
table. Aggregate computation proceeded only after that gate passed. Historical
attempts were not combined with final scientific attempts. The documented
TARGET run150 outer-status anomaly is non-invalidating and the frozen scientific
classification (`LLM=NOT_REQUIRED`) was retained.

This directory contains estimates and audit artifacts only. It does not state an
article conclusion, create a retrospective threshold, or automatically accept or
reject H1/H2/H3.
"""
    audit_path = output_root / "06_audit" / "ANALYSIS_AUDIT.md"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(audit_text, encoding="utf-8", newline="\n")

    code_sha, code_files = analysis_code_inventory(repo_root, output_root)
    output_files = sorted(
        path for path in output_root.rglob("*")
        if path.is_file()
        and path.name != "ANALYSIS_MANIFEST.json"
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
    )
    output_inventory = [
        {"path": rel(repo_root, path), "sha256": sha256_file(path), "size_bytes": path.stat().st_size}
        for path in output_files
    ]
    analysis_manifest = {
        "schema_version": "1.0.0",
        "generated_at_utc": utc_now(),
        "source_repository": SOURCE_REPOSITORY,
        "source_main_commit": SOURCE_MAIN_COMMIT,
        "analysis_branch": ANALYSIS_BRANCH,
        "final_campaign_manifest_sha256": EXPECTED_FINAL_MANIFEST_SHA256,
        "sap_git_blob": EXPECTED_SAP_BLOB,
        "sap_sha256_canonical_git_blob": initial_report["authority"]["sap_sha256_canonical_git_blob"],
        "sap_sha256_worktree_bytes": initial_report["authority"]["sap_sha256_worktree_bytes"],
        "method_freeze": METHOD_FREEZE,
        "linked_technical_git_blobs": initial_report["authority"]["linked_technical_sources"],
        "analysis_code_sha256": code_sha,
        "analysis_code_commit": None,
        "analysis_code_commit_policy": "Final commit SHA is intentionally external to this self-contained file to avoid an impossible Git self-reference; use branch history plus analysis_code_sha256.",
        "analysis_code_files": code_files,
        "python_version": platform.python_version(),
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
        "scipy_version": scipy.__version__,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "input_artifact_count": len(final_report["input_artifacts"]),
        "input_hash_validation_status": final_report["gate_status"],
        "input_results_modified": False,
        "outputs": output_inventory,
        "self_hash_policy": "ANALYSIS_MANIFEST.json is excluded from its own output hash inventory",
    }
    atomic_json(output_root / "ANALYSIS_MANIFEST.json", analysis_manifest)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--integrity-only", action="store_true")
    mode.add_argument("--full", action="store_true")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[4],
        help="Export repository root (defaults to the root containing analysis/)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    report, artifact_paths = materialize_integrity(repo_root)
    print(f"INTEGRITY_GATE={report['gate_status']}")
    print(f"PRIMARY_ARTIFACTS={len(report['input_artifacts'])}")
    print("DENOMINATOR_GATE=PASS")
    if args.integrity_only:
        print("AGGREGATE_STATISTICS_CALCULATED=NO")
        return 0
    materialize_full_analysis(repo_root, report, artifact_paths)
    print("STATISTICAL_ANALYSIS_EXECUTED=YES")
    print("INPUT_REHASH_AFTER_ANALYSIS=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

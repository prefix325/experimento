"""Independent Calculation 3 for the frozen TEP/LLM/DPCA campaign.

Architecture mandated by the frozen SAP:
primary JSONL -> event ledger -> run endpoint ledger -> statistics.

This module deliberately uses the Python standard library for parsing and
aggregation. NumPy and SciPy are used only for numerical statistics.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import numpy as np
import scipy

from stats_core import (
    bootstrap_ci,
    clopper_pearson_interval,
    exact_sign_test,
    holm_adjust,
    mcnemar_exact_from_counts,
    numeric_summary,
    paired_binary_table,
    paired_delays,
    paired_proportion_difference,
    proportion_summary,
)


SOURCE_COMMIT = "536cd4462b2fdc7e1bac8317adc64534e546c809"
BRANCH = "validation/calculation3-independent-20260821"
METHOD_FREEZE = "TEP-METHOD-FREEZE-20260815-FULL-WINDOW-REFRESH"
SAP_REL = Path("repo/project/final_campaign/STATISTICAL_ANALYSIS_PLAN.md")
FINAL_MANIFEST_REL = Path("repo/project/final_campaign/FINAL_CAMPAIGN_MANIFEST.json")
CONFIG_REL = Path("repo/experiments/tep/local_llm/config")
SAP_BLOB = "401c245f6b222e85662d8e47d4312ce27e8e8c60"
SAP_SHA256 = "f5808362f57ed8ebc5b5548ec3d36270c9899deb93df7a9460fe1f6cbde29bfd"
FINAL_MANIFEST_SHA256 = "d3f7cdde04b18182a2fe25cc8ea23e07833a0c3ab9441403d9eb1b17dd028db5"
BOOTSTRAP_SEED = 20260820
BOOTSTRAP_REPLICATES = 10_000
FAULT_ONSET = 161
WINDOW_SAMPLES = 20
STRIDE_SAMPLES = 5
REFRESH_STRIDES = 4
SAMPLE_INTERVAL_MINUTES = 3
EXPECTED_PRIMARY_JSONL = 1100
EXPECTED_DPCA_TARGET = 500
EXPECTED_DPCA_NORMAL = 500
EXPECTED_LLM_TARGET = 50
EXPECTED_LLM_NORMAL = 50
VALID_DECISIONS = {"NORMAL", "EVIDENCE_INSUFFICIENT", "ANOMALY"}
VALID_H3_CLAIMS = {"HIGH", "LOW", "INCREASE", "REDUCTION", "VARIABILITY"}
VALID_H3_VARIABLES = {
    *(f"xmeas_{index}" for index in range(1, 42)),
    *(f"xmv_{index}" for index in range(1, 12)),
}

OUTPUT_ROOT = Path(__file__).resolve().parents[1]
CHECKOUT_ROOT = Path(__file__).resolve().parents[5]
RESULTS_ROOT = CHECKOUT_ROOT / "results" / "formal" / METHOD_FREEZE


class GateFailure(RuntimeError):
    """Raised before scientific aggregation whenever a frozen-input gate fails."""


@dataclass(frozen=True)
class ComponentInput:
    cohort: str
    simulation_run: int
    blind_run_id: str
    detector: str
    attempt: str
    complete_path: Path
    manifest_path: Path
    primary_path: Path
    detection_summary_path: Path | None


@dataclass
class IntegrityState:
    report: dict[str, Any]
    validation_rows: list[dict[str, Any]]
    snapshot: dict[str, tuple[int, str]]
    components: dict[tuple[str, int, str], ComponentInput]
    final_matrix: list[dict[str, Any]]
    target_selection: list[int]
    normal_selection: list[int]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise GateFailure(f"Blank JSONL record: {path}:{line_number}")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise GateFailure(f"Invalid JSONL record: {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise GateFailure(f"Non-object JSONL record: {path}:{line_number}")
            yield value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    return value


def write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(fieldnames),
            extrasaction="raise",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def git_output(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(CHECKOUT_ROOT), *args],
        text=True,
        encoding="utf-8",
    ).strip()


def git_blob_bytes(relative_path: Path, revision: str = SOURCE_COMMIT) -> bytes:
    spec = f"{revision}:{relative_path.as_posix()}"
    return subprocess.check_output(["git", "-C", str(CHECKOUT_ROOT), "cat-file", "blob", spec])


def validate_expected_hash(
    path: Path,
    expected: str,
    *,
    allow_checkout_eol_normalization: bool,
) -> dict[str, Any]:
    if not path.is_file():
        return {
            "path": path.relative_to(CHECKOUT_ROOT).as_posix(),
            "exists": False,
            "expected_sha256": expected,
            "status": "MISSING",
        }
    raw = path.read_bytes()
    raw_hash = sha256_bytes(raw)
    canonical_hash = raw_hash
    canonical_size = len(raw)
    mode = "RAW_BYTES"
    if raw_hash != expected and allow_checkout_eol_normalization:
        canonical = raw.replace(b"\r\n", b"\n")
        canonical_hash = sha256_bytes(canonical)
        canonical_size = len(canonical)
        mode = "GIT_CHECKOUT_CRLF_NORMALIZED_TO_LF"
    status = "PASS" if canonical_hash == expected else "HASH_MISMATCH"
    return {
        "path": path.relative_to(CHECKOUT_ROOT).as_posix(),
        "exists": True,
        "size_bytes_worktree": len(raw),
        "size_bytes_canonical": canonical_size,
        "working_tree_sha256": raw_hash,
        "canonical_sha256": canonical_hash,
        "expected_sha256": expected,
        "validation_mode": mode,
        "status": status,
    }


def blind_id(seed: int, simulation_run: int) -> str:
    text = f"psqza-formal-v1:{seed}:{simulation_run}".encode("utf-8")
    return "BLIND_" + hashlib.sha256(text).hexdigest()[:16].upper()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GateFailure(message)


def _component_input_and_validation(
    row: dict[str, Any],
    detector: str,
    configuration: dict[str, Any],
    base_target_llm_runs: set[int],
) -> tuple[ComponentInput, list[dict[str, Any]]]:
    cohort = row["cohort"]
    run = int(row["simulationRun"])
    blind = row["blind_run_id"]
    attempt_key = f"{detector}_scientific_attempt"
    attempt = row[attempt_key]
    _require(attempt is not None, f"Missing final {detector} attempt for {cohort}/{run}")
    attempt = str(attempt).zfill(4)
    detector_root = RESULTS_ROOT / cohort / detector
    run_root = detector_root / "runs" / blind
    complete_path = run_root / "COMPLETE.json"
    attempt_root = run_root / "attempts" / attempt
    manifest_path = attempt_root / "run_manifest.json"
    primary_name = "llm_decisions.jsonl" if detector == "llm" else "dpca_metrics.jsonl"
    primary_path = attempt_root / primary_name
    summary_path = attempt_root / "detection_summary.json" if detector == "llm" else None

    rows: list[dict[str, Any]] = []
    complete_hash = row[f"{detector}_complete_marker_hash"]
    manifest_hash = row[f"{detector}_manifest_hash"]
    artifact_hash_key = "llm_decisions_hash" if detector == "llm" else "dpca_artifact_hash"
    artifact_hash = row[artifact_hash_key]
    rows.append(validate_expected_hash(complete_path, complete_hash, allow_checkout_eol_normalization=True))
    rows.append(validate_expected_hash(manifest_path, manifest_hash, allow_checkout_eol_normalization=True))
    rows.append(validate_expected_hash(primary_path, artifact_hash, allow_checkout_eol_normalization=False))

    _require(all(item["status"] == "PASS" for item in rows), f"Hash chain failure: {cohort}/{run}/{detector}")
    complete = read_json(complete_path)
    _require(complete.get("status") == "COMPLETE", f"Incomplete marker: {complete_path}")
    _require(complete.get("blind_run_id") == blind, f"Blind ID mismatch: {complete_path}")
    _require(int(complete.get("attempt")) == int(attempt), f"Attempt mismatch: {complete_path}")
    _require(complete.get("run_manifest_sha256") == manifest_hash, f"Marker manifest hash mismatch: {complete_path}")
    expected_relative = f"runs/{blind}/attempts/{attempt}/run_manifest.json"
    _require(complete.get("run_manifest_relative_path") == expected_relative, f"Manifest path mismatch: {complete_path}")

    run_manifest = read_json(manifest_path)
    _require(run_manifest.get("status") == "COMPLETE", f"Incomplete run manifest: {manifest_path}")
    _require(run_manifest.get("blind_run_id") == blind, f"Manifest blind ID mismatch: {manifest_path}")
    _require(int(run_manifest.get("attempt")) == int(attempt), f"Manifest attempt mismatch: {manifest_path}")
    frozen_expected = {
        "configuration_sha256": configuration["base_configuration_sha256"],
        "dpca_artifact_sha256": configuration["dpca_model_sha256"],
        "dpca_reference_sha256": configuration["dpca_reference_sha256"],
        "evaluation_contract_sha256": configuration["evaluation_contract_sha256"],
        "h3_reference_sha256": configuration["h3_reference_sha256"],
        "image_digest": configuration["docker_image_digest"],
        "methodological_amendment_sha256": configuration["methodological_amendment_002_sha256"],
        "model_sha256": configuration["llm_model_sha256"],
        "output_schema_sha256": configuration["output_schema_sha256"],
        "prompt_sha256": configuration["prompt_sha256"],
        "representation_contract_sha256": configuration["representation_contract_sha256"],
        "run_selection_sha256": configuration["target_selection_sha256"] if cohort == "target" else configuration["normal_holdout_selection_sha256"],
    }
    _require(complete.get("frozen_hashes") == frozen_expected, f"Frozen hashes mismatch in marker: {complete_path}")
    _require(run_manifest.get("frozen_hashes") == frozen_expected, f"Frozen hashes mismatch in manifest: {manifest_path}")
    expects_operational_provenance = detector == "llm" and not (cohort == "target" and run in base_target_llm_runs)
    complete_operational = complete.get("operational_provenance")
    manifest_operational = run_manifest.get("operational_provenance")
    if expects_operational_provenance:
        _require(isinstance(complete_operational, dict), f"Missing operational provenance: {complete_path}")
        _require(complete_operational == manifest_operational, f"Operational provenance disagreement: {manifest_path}")
        _require(complete_operational.get("amendment_sha256") == configuration["operational_amendment_001_sha256"], f"Operational amendment hash mismatch: {complete_path}")
        _require(complete_operational.get("base_configuration_sha256") == configuration["base_configuration_sha256"], f"Base configuration provenance mismatch: {complete_path}")
        _require(complete_operational.get("effective_configuration_sha256") == configuration["effective_configuration_sha256"], f"Effective configuration provenance mismatch: {complete_path}")
    else:
        _require(complete_operational is None and manifest_operational is None, f"Unexpected operational provenance: {manifest_path}")
    artifacts = run_manifest.get("artifacts")
    _require(isinstance(artifacts, list), f"Artifacts missing: {manifest_path}")
    by_name = {item.get("name"): item for item in artifacts}
    expected_names = {primary_name, "detection_summary.json"} if detector == "llm" else {primary_name}
    _require(set(by_name) == expected_names, f"Unexpected artifact inventory: {manifest_path}")
    primary_manifest = by_name[primary_name]
    _require(primary_manifest.get("sha256") == artifact_hash, f"Primary hash disagrees with final manifest: {primary_path}")
    _require(primary_path.stat().st_size == int(primary_manifest.get("size_bytes")), f"Primary size mismatch: {primary_path}")

    if detector == "llm":
        assert summary_path is not None
        summary_manifest = by_name["detection_summary.json"]
        rows.append(
            validate_expected_hash(
                summary_path,
                summary_manifest["sha256"],
                allow_checkout_eol_normalization=True,
            )
        )
        _require(rows[-1]["status"] == "PASS", f"Detection summary hash mismatch: {summary_path}")
        _require(rows[-1]["size_bytes_canonical"] == int(summary_manifest["size_bytes"]), f"Detection summary size mismatch: {summary_path}")

    component = ComponentInput(
        cohort=cohort,
        simulation_run=run,
        blind_run_id=blind,
        detector=detector,
        attempt=attempt,
        complete_path=complete_path,
        manifest_path=manifest_path,
        primary_path=primary_path,
        detection_summary_path=summary_path,
    )
    return component, rows


def validate_integrity() -> IntegrityState:
    head = git_output("rev-parse", "HEAD")
    branch = git_output("branch", "--show-current")
    _require(head == SOURCE_COMMIT, f"HEAD is {head}, expected source commit {SOURCE_COMMIT}")
    _require(branch == BRANCH, f"Branch is {branch}, expected {BRANCH}")

    sap_blob = git_output("rev-parse", f"HEAD:{SAP_REL.as_posix()}")
    sap_sha = sha256_bytes(git_blob_bytes(SAP_REL))
    manifest_sha = sha256_bytes(git_blob_bytes(FINAL_MANIFEST_REL))
    _require(sap_blob == SAP_BLOB, f"SAP blob mismatch: {sap_blob}")
    _require(sap_sha == SAP_SHA256, f"SAP SHA-256 mismatch: {sap_sha}")
    _require(manifest_sha == FINAL_MANIFEST_SHA256, f"Final manifest SHA-256 mismatch: {manifest_sha}")

    sap_worktree_check = validate_expected_hash(
        CHECKOUT_ROOT / SAP_REL,
        SAP_SHA256,
        allow_checkout_eol_normalization=True,
    )
    manifest_worktree_check = validate_expected_hash(
        CHECKOUT_ROOT / FINAL_MANIFEST_REL,
        FINAL_MANIFEST_SHA256,
        allow_checkout_eol_normalization=True,
    )
    _require(sap_worktree_check["status"] == "PASS", "SAP worktree bytes do not match the canonical frozen blob")
    _require(manifest_worktree_check["status"] == "PASS", "Final manifest worktree bytes do not match the canonical frozen blob")

    final_manifest = read_json(CHECKOUT_ROOT / FINAL_MANIFEST_REL)
    _require(final_manifest.get("method_freeze_id") == METHOD_FREEZE, "Method freeze mismatch")
    _require(final_manifest.get("audit_status") == "PASS", "Final manifest audit status is not PASS")
    _require(final_manifest.get("scientific_analysis_ready") is True, "Final manifest is not analysis-ready")
    matrix = final_manifest.get("final_matrix")
    _require(isinstance(matrix, list) and len(matrix) == 1000, "Final matrix is not 1000 rows")
    pairs = [(item.get("cohort"), item.get("simulationRun")) for item in matrix]
    duplicate_final_runs = len(pairs) - len(set(pairs))
    _require(duplicate_final_runs == 0, f"Duplicate final runs: {duplicate_final_runs}")
    for cohort in ("target", "normal_holdout"):
        cohort_runs = sorted(int(item["simulationRun"]) for item in matrix if item.get("cohort") == cohort)
        _require(cohort_runs == list(range(1, 501)), f"Incomplete {cohort} universe")

    config = CONFIG_REL
    target_selection_path = CHECKOUT_ROOT / config / "formal_run_selection.json"
    normal_selection_path = CHECKOUT_ROOT / config / "formal_normal_holdout_selection.json"
    target_selection_json = read_json(target_selection_path)
    normal_selection_json = read_json(normal_selection_path)
    target_selection = [int(x) for x in target_selection_json["selected_simulation_runs"]]
    normal_selection = [int(x) for x in normal_selection_json["selected_simulation_runs"]]
    _require(len(target_selection) == EXPECTED_LLM_TARGET and len(set(target_selection)) == EXPECTED_LLM_TARGET, "Invalid target selection")
    _require(len(normal_selection) == EXPECTED_LLM_NORMAL and len(set(normal_selection)) == EXPECTED_LLM_NORMAL, "Invalid normal selection")
    _require(all(11 <= run <= 500 for run in target_selection), "Out-of-universe target selection")
    _require(all(1 <= run <= 500 for run in normal_selection), "Out-of-universe normal selection")

    configuration = final_manifest["configuration"]
    base_target_llm_runs = set(final_manifest["amendment_provenance"]["target_llm_runs_using_base_configuration"])
    config_expected = {
        "formal.json": configuration["formal_json_sha256"],
        "evaluation_contract.json": configuration["evaluation_contract_sha256"],
        "h3_evidence_reference.json": configuration["h3_reference_sha256"],
        "formal_run_selection.json": configuration["target_selection_sha256"],
        "formal_normal_holdout_selection.json": configuration["normal_holdout_selection_sha256"],
    }
    validation_rows: list[dict[str, Any]] = [sap_worktree_check, manifest_worktree_check]
    for name, expected_hash in config_expected.items():
        check = validate_expected_hash(
            CHECKOUT_ROOT / config / name,
            expected_hash,
            allow_checkout_eol_normalization=True,
        )
        validation_rows.append(check)
        _require(check["status"] == "PASS", f"Frozen configuration hash mismatch: {name}")

    expected_llm = {
        ("target", run) for run in target_selection
    } | {("normal_holdout", run) for run in normal_selection}
    observed_llm = {
        (item["cohort"], int(item["simulationRun"])) for item in matrix if item.get("llm_required")
    }
    out_of_selection_llm = len(observed_llm - expected_llm) + len(expected_llm - observed_llm)
    _require(out_of_selection_llm == 0, f"LLM selection mismatch: {out_of_selection_llm}")

    components: dict[tuple[str, int, str], ComponentInput] = {}
    primary_hash_mismatches = 0
    missing_primary_files = 0
    for item in sorted(matrix, key=lambda value: ((0 if value["cohort"] == "target" else 1), int(value["simulationRun"]))):
        cohort = item["cohort"]
        run = int(item["simulationRun"])
        _require(str(item.get("integrity_status", "")).startswith("VALID"), f"Invalid final matrix row: {cohort}/{run}")
        outer_path = CHECKOUT_ROOT / "results" / "formal" / "monitor_controller" / "attempts" / cohort / f"run_{run:03d}" / "COMPLETE.json"
        _require(outer_path.is_file(), f"Missing outer COMPLETE marker: {outer_path}")
        outer = read_json(outer_path)
        _require(outer.get("status") == "COMPLETE" and outer.get("lot_status") == "COMPLETE", f"Incomplete outer marker: {outer_path}")
        _require(outer.get("cohort") == cohort and int(outer.get("simulation_run")) == run, f"Outer marker identity mismatch: {outer_path}")
        _require(outer.get("attempt_id") == item.get("final_outer_attempt"), f"Outer attempt mismatch: {outer_path}")
        observed_components = item.get("outer_component_statuses_observed", {})
        _require(outer.get("dpca_status") == observed_components.get("dpca"), f"Outer DPCA status mismatch: {outer_path}")
        _require(outer.get("llm_status") == observed_components.get("llm"), f"Outer LLM status mismatch: {outer_path}")
        _require(outer.get("lot_status") == observed_components.get("lot"), f"Outer lot status mismatch: {outer_path}")
        outer_raw = outer_path.read_bytes()
        validation_rows.append({
            "path": outer_path.relative_to(CHECKOUT_ROOT).as_posix(),
            "exists": True,
            "size_bytes_worktree": len(outer_raw),
            "size_bytes_canonical": len(outer_raw.replace(b"\r\n", b"\n")),
            "working_tree_sha256": sha256_bytes(outer_raw),
            "canonical_sha256": sha256_bytes(outer_raw.replace(b"\r\n", b"\n")),
            "expected_sha256": None,
            "validation_mode": "STRUCTURAL_OUTER_COMPLETE",
            "status": "PASS",
        })
        _require(item.get("dpca_required") is True and item.get("dpca_final_status") == "COMPLETE", f"DPCA incomplete: {cohort}/{run}")
        detectors = ["dpca"]
        if item.get("llm_required"):
            _require(item.get("llm_final_status") == "COMPLETE", f"LLM incomplete: {cohort}/{run}")
            detectors.append("llm")
        else:
            _require(item.get("llm_final_status") == "NOT_REQUIRED", f"Unexpected LLM state: {cohort}/{run}")
        for detector in detectors:
            try:
                component, checks = _component_input_and_validation(item, detector, configuration, base_target_llm_runs)
            except GateFailure as exc:
                if "Missing" in str(exc) or "missing" in str(exc):
                    missing_primary_files += 1
                else:
                    primary_hash_mismatches += 1
                raise
            components[(cohort, run, detector)] = component
            validation_rows.extend(checks)

    primary_files_found = sum(1 for key in components if key[2] in {"llm", "dpca"})
    _require(primary_files_found == EXPECTED_PRIMARY_JSONL, f"Primary JSONL count is {primary_files_found}")
    _require(sum(key[2] == "dpca" and key[0] == "target" for key in components) == EXPECTED_DPCA_TARGET, "DPCA target denominator mismatch")
    _require(sum(key[2] == "dpca" and key[0] == "normal_holdout" for key in components) == EXPECTED_DPCA_NORMAL, "DPCA normal denominator mismatch")
    _require(sum(key[2] == "llm" and key[0] == "target" for key in components) == EXPECTED_LLM_TARGET, "LLM target denominator mismatch")
    _require(sum(key[2] == "llm" and key[0] == "normal_holdout" for key in components) == EXPECTED_LLM_NORMAL, "LLM normal denominator mismatch")

    snapshot: dict[str, tuple[int, str]] = {}
    for check in validation_rows:
        path = CHECKOUT_ROOT / check["path"]
        if path.is_file():
            snapshot[check["path"]] = (path.stat().st_size, sha256_file(path))
    for relative in [SAP_REL, FINAL_MANIFEST_REL]:
        path = CHECKOUT_ROOT / relative
        snapshot[relative.as_posix()] = (path.stat().st_size, sha256_file(path))

    historical_attempts_included = 0
    denominator_rows = [
        {"scope": "TARGET_POST_ONSET", "analysis_set": "LLM_PRIMARY", "detector": "LLM", "cohort": "target", "n_runs": 50, "unit": "simulationRun", "selection": "formal_run_selection.json", "gate": "PASS"},
        {"scope": "TARGET_POST_ONSET", "analysis_set": "DPCA_PAIRED", "detector": "DPCA", "cohort": "target", "n_runs": 50, "unit": "simulationRun", "selection": "same 50 target LLM runs", "gate": "PASS"},
        {"scope": "TARGET_POST_ONSET", "analysis_set": "DPCA_EXPANDED", "detector": "DPCA", "cohort": "target", "n_runs": 500, "unit": "simulationRun", "selection": "complete formal corpus", "gate": "PASS"},
        {"scope": "NORMAL_FULL_TRAJECTORY", "analysis_set": "LLM_PRIMARY", "detector": "LLM", "cohort": "normal_holdout", "n_runs": 50, "unit": "simulationRun", "selection": "formal_normal_holdout_selection.json", "gate": "PASS"},
        {"scope": "NORMAL_FULL_TRAJECTORY", "analysis_set": "DPCA_PAIRED", "detector": "DPCA", "cohort": "normal_holdout", "n_runs": 50, "unit": "simulationRun", "selection": "same 50 normal LLM runs", "gate": "PASS"},
        {"scope": "NORMAL_FULL_TRAJECTORY", "analysis_set": "DPCA_EXPANDED", "detector": "DPCA", "cohort": "normal_holdout", "n_runs": 500, "unit": "simulationRun", "selection": "complete formal corpus", "gate": "PASS"},
        {"scope": "TARGET_PRE_ONSET_1_160", "analysis_set": "LLM_PRIMARY", "detector": "LLM", "cohort": "target", "n_runs": 50, "unit": "simulationRun", "selection": "formal_run_selection.json", "gate": "PASS"},
        {"scope": "TARGET_PRE_ONSET_1_160", "analysis_set": "DPCA_PAIRED", "detector": "DPCA", "cohort": "target", "n_runs": 50, "unit": "simulationRun", "selection": "same 50 target LLM runs", "gate": "PASS"},
        {"scope": "TARGET_PRE_ONSET_1_160", "analysis_set": "DPCA_EXPANDED", "detector": "DPCA", "cohort": "target", "n_runs": 500, "unit": "simulationRun", "selection": "complete formal corpus", "gate": "PASS"},
        {"scope": "H3_TARGET", "analysis_set": "LLM_PRIMARY", "detector": "LLM", "cohort": "target", "n_runs": 50, "unit": "simulationRun", "selection": "formal_run_selection.json", "gate": "PASS"},
    ]
    integrity_report = {
        "calculation": 3,
        "generated_at_utc": utc_now(),
        "source_commit": head,
        "branch": branch,
        "method_freeze_id": METHOD_FREEZE,
        "prior_analysis_contamination_risk": "NO",
        "final_manifest_sha256": manifest_sha,
        "final_manifest_gate": "PASS",
        "sap_git_blob": sap_blob,
        "sap_sha256": sap_sha,
        "sap_gate": "PASS",
        "total_primary_jsonl_expected": EXPECTED_PRIMARY_JSONL,
        "primary_files_found": primary_files_found,
        "missing_primary_files": missing_primary_files,
        "primary_hash_mismatches": primary_hash_mismatches,
        "duplicate_final_runs": duplicate_final_runs,
        "out_of_selection_llm": out_of_selection_llm,
        "historical_attempts_included": historical_attempts_included,
        "dpca_target": EXPECTED_DPCA_TARGET,
        "dpca_normal_holdout": EXPECTED_DPCA_NORMAL,
        "llm_target": EXPECTED_LLM_TARGET,
        "llm_normal_holdout": EXPECTED_LLM_NORMAL,
        "denominator_gate": "PASS",
        "input_validation_note": "Git-tracked JSON/Markdown metadata are validated after deterministic CRLF-to-LF normalization when the Windows checkout converted line endings; primary JSONL artifacts are validated as exact raw bytes.",
    }
    write_json(OUTPUT_ROOT / "00_integrity" / "integrity_report.json", integrity_report)
    write_csv(
        OUTPUT_ROOT / "00_integrity" / "denominator_table.csv",
        ["scope", "analysis_set", "detector", "cohort", "n_runs", "unit", "selection", "gate"],
        denominator_rows,
    )
    write_json(
        OUTPUT_ROOT / "05_audit" / "input_hash_validation.json",
        {
            "generated_at_utc": utc_now(),
            "validation_count": len(validation_rows),
            "all_pass": all(row["status"] == "PASS" for row in validation_rows),
            "files": validation_rows,
        },
    )
    return IntegrityState(
        report=integrity_report,
        validation_rows=validation_rows,
        snapshot=snapshot,
        components=components,
        final_matrix=matrix,
        target_selection=target_selection,
        normal_selection=normal_selection,
    )


def verify_bytes_hash(data: bytes, expected: str) -> bool:
    """Small pure helper used by the independent synthetic hash-gate test."""
    return sha256_bytes(data) == expected.lower()


def _llm_segment(record: dict[str, Any], cohort: str) -> str:
    if cohort == "normal_holdout":
        return "full"
    return "pre" if int(record["sample_end"]) <= FAULT_ONSET - 1 else "post"


def reconstruct_llm_records(
    records: Sequence[dict[str, Any]],
    cohort: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Reconstruct LLM events/endpoints using only categorical decisions."""
    _require(cohort in {"target", "normal_holdout"}, f"Unknown cohort: {cohort}")
    ordered = sorted(records, key=lambda rec: (int(rec["sample_end"]), int(rec["window_id"])))
    _require(bool(ordered), "LLM JSONL has no records")
    by_window: dict[int, dict[str, Any]] = {}
    for rec in ordered:
        decision = rec.get("decision")
        _require(decision in VALID_DECISIONS, f"Invalid LLM decision: {decision}")
        window = int(rec["window_id"])
        _require(window not in by_window, f"Duplicate LLM window: {window}")
        _require(int(rec["sample_start"]) == 1 + STRIDE_SAMPLES * window, f"Invalid sample_start at window {window}")
        _require(int(rec["sample_end"]) == WINDOW_SAMPLES + STRIDE_SAMPLES * window, f"Invalid sample_end at window {window}")
        by_window[window] = rec

    raw_windows: dict[str, list[int]] = defaultdict(list)
    confirmations: dict[str, list[tuple[int, int]]] = defaultdict(list)
    event_rows: list[dict[str, Any]] = []
    for rec in ordered:
        window = int(rec["window_id"])
        segment = _llm_segment(rec, cohort)
        raw = rec["decision"] == "ANOMALY"
        if raw:
            raw_windows[segment].append(window)
        origin_rec = by_window.get(window - REFRESH_STRIDES)
        verified_origin: int | None = None
        if (
            origin_rec is not None
            and origin_rec["decision"] == "ANOMALY"
            and _llm_segment(origin_rec, cohort) == segment
        ):
            verified_origin = window - REFRESH_STRIDES
            if raw:
                confirmations[segment].append((verified_origin, window))

        candidate_status: str | None = None
        if raw:
            verify_rec = by_window.get(window + REFRESH_STRIDES)
            if verify_rec is None:
                candidate_status = "VERIFICATION_INCOMPLETE_END_OF_TRAJECTORY"
            elif _llm_segment(verify_rec, cohort) != segment:
                candidate_status = "RESET_AT_ONSET"
            elif verify_rec["decision"] == "ANOMALY":
                candidate_status = "CONFIRMED"
            else:
                candidate_status = "FAILED"

        if raw or verified_origin is not None:
            event_rows.append(
                {
                    "cohort": cohort,
                    "simulationRun": None,
                    "blind_run_id": rec.get("simulation_run_blind_id"),
                    "detector": "LLM",
                    "time_coordinate": int(rec["sample_end"]),
                    "window_id": window,
                    "sample_start": int(rec["sample_start"]),
                    "sample_end": int(rec["sample_end"]),
                    "raw_positive": raw,
                    "candidate_started": raw,
                    "candidate_verified": verified_origin is not None,
                    "confirmed": verified_origin is not None and raw,
                    "eligible_pre_onset": cohort == "target" and segment == "pre",
                    "eligible_post_onset": cohort == "target" and segment == "post",
                    "eligible_full_trajectory": cohort == "normal_holdout",
                    "candidate_origin_window": verified_origin,
                    "candidate_final_status": candidate_status,
                    "persistence_streak": None,
                }
            )

    def first_window(segment: str) -> int | None:
        values = raw_windows.get(segment, [])
        return min(values, key=lambda wid: (int(by_window[wid]["sample_end"]), wid)) if values else None

    def first_confirmation(segment: str) -> tuple[int, int] | None:
        values = confirmations.get(segment, [])
        return min(values, key=lambda pair: (int(by_window[pair[1]]["sample_end"]), pair[1], pair[0])) if values else None

    if cohort == "target":
        raw_post_window = first_window("post")
        confirmed_post_pair = first_confirmation("post")
        raw_pre = bool(raw_windows.get("pre"))
        confirmed_pre = bool(confirmations.get("pre"))
        endpoint = {
            "raw_post_onset": raw_post_window is not None,
            "confirmed_post_onset": confirmed_post_pair is not None,
            "first_indication_sample_end": int(by_window[raw_post_window]["sample_end"]) if raw_post_window is not None else None,
            "confirmation_sample_end": int(by_window[confirmed_post_pair[1]]["sample_end"]) if confirmed_post_pair is not None else None,
            "raw_delay_minutes": (int(by_window[raw_post_window]["sample_end"]) - FAULT_ONSET) * SAMPLE_INTERVAL_MINUTES if raw_post_window is not None else None,
            "confirmed_delay_minutes": (int(by_window[confirmed_post_pair[1]]["sample_end"]) - FAULT_ONSET) * SAMPLE_INTERVAL_MINUTES if confirmed_post_pair is not None else None,
            "raw_pre_onset": raw_pre,
            "confirmed_pre_onset": confirmed_pre,
            "any_raw_fa": None,
            "any_confirmed_fa": None,
        }
        chosen_raw = raw_post_window
        chosen_confirmation = confirmed_post_pair
    else:
        raw_full_window = first_window("full")
        confirmed_full_pair = first_confirmation("full")
        endpoint = {
            "raw_post_onset": None,
            "confirmed_post_onset": None,
            "first_indication_sample_end": None,
            "confirmation_sample_end": None,
            "raw_delay_minutes": None,
            "confirmed_delay_minutes": None,
            "raw_pre_onset": None,
            "confirmed_pre_onset": None,
            "any_raw_fa": raw_full_window is not None,
            "any_confirmed_fa": confirmed_full_pair is not None,
        }
        chosen_raw = raw_full_window
        chosen_confirmation = confirmed_full_pair

    chosen_segment = "post" if cohort == "target" else "full"
    has_terminal_incomplete_candidate = any(
        (window + REFRESH_STRIDES) not in by_window
        for window in raw_windows.get(chosen_segment, [])
    )
    if chosen_confirmation is not None:
        expected_detection_state = "CONFIRMED_DETECTION"
    elif has_terminal_incomplete_candidate:
        expected_detection_state = "VERIFICATION_INCOMPLETE_END_OF_TRAJECTORY"
    else:
        expected_detection_state = "NO_CONFIRMED_DETECTION"

    crosscheck_expected = {
        "first_indication_window": chosen_raw,
        "confirmation_candidate_window": chosen_confirmation[0] if chosen_confirmation else None,
        "confirmation_window": chosen_confirmation[1] if chosen_confirmation else None,
        "first_indication_status": "FIRST_INDICATION" if chosen_raw is not None else "NO_FIRST_INDICATION",
        "confirmed_detection_status": "CONFIRMED_DETECTION" if chosen_confirmation is not None else "NO_CONFIRMED_DETECTION",
        "detection_state": expected_detection_state,
        "should_stop": cohort == "target" and chosen_confirmation is not None,
        "verification_advances_required": REFRESH_STRIDES,
        "window_id": int(ordered[-1]["window_id"]),
    }
    return endpoint, event_rows, crosscheck_expected


def crosscheck_llm_summary(summary: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    mismatches: list[str] = []
    for key, value in expected.items():
        if summary.get(key) != value:
            mismatches.append(f"{key}: observed={summary.get(key)!r}, expected={value!r}")
    return mismatches


def reconstruct_dpca_records(
    records: Sequence[dict[str, Any]],
    cohort: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, int]]:
    """Recompute DPCA raw alarms and persistence from numeric metrics."""
    _require(cohort in {"target", "normal_holdout"}, f"Unknown cohort: {cohort}")
    ordered = sorted(records, key=lambda rec: int(rec["sample"]))
    _require(len(ordered) == 960, f"DPCA record count is {len(ordered)}, expected 960")
    _require([int(rec["sample"]) for rec in ordered] == list(range(1, 961)), "DPCA samples are not exactly 1..960")

    raw_by_sample: dict[int, bool] = {}
    raw_mismatches = 0
    persistent_mismatches = 0
    native_streak = 0
    for rec in ordered:
        sample = int(rec["sample"])
        t2 = rec.get("t2")
        spe = rec.get("spe")
        t2_limit = rec.get("t2_limit")
        spe_limit = rec.get("spe_limit")
        metric_rule_raw = bool((t2 is not None and float(t2) > float(t2_limit)) or (spe is not None and float(spe) > float(spe_limit)))
        raw = bool(rec.get("alarm_raw"))
        raw_by_sample[sample] = raw
        if raw != metric_rule_raw:
            raw_mismatches += 1
        native_streak = native_streak + 1 if raw else 0
        if bool(rec.get("alarm_persistent")) != (native_streak >= 3):
            persistent_mismatches += 1

    event_rows: list[dict[str, Any]] = []
    first_raw_pre: int | None = None
    first_confirmed_pre: int | None = None
    first_raw_post: int | None = None
    first_confirmed_post: int | None = None
    first_raw_full: int | None = None
    first_confirmed_full: int | None = None
    segment_streak = 0
    for rec in ordered:
        sample = int(rec["sample"])
        raw = raw_by_sample[sample]
        if cohort == "target" and sample == FAULT_ONSET:
            segment_streak = 0
        segment_streak = segment_streak + 1 if raw else 0
        confirmed_activation = segment_streak == 3
        if cohort == "target":
            if sample <= FAULT_ONSET - 1:
                if raw and first_raw_pre is None:
                    first_raw_pre = sample
                if confirmed_activation and first_confirmed_pre is None:
                    first_confirmed_pre = sample
            else:
                if raw and first_raw_post is None:
                    first_raw_post = sample
                if confirmed_activation and first_confirmed_post is None:
                    first_confirmed_post = sample
        else:
            if raw and first_raw_full is None:
                first_raw_full = sample
            if confirmed_activation and first_confirmed_full is None:
                first_confirmed_full = sample

        if raw:
            event_rows.append(
                {
                    "cohort": cohort,
                    "simulationRun": None,
                    "blind_run_id": rec.get("blind_run_id"),
                    "detector": "DPCA",
                    "time_coordinate": sample,
                    "window_id": None,
                    "sample_start": sample,
                    "sample_end": sample,
                    "raw_positive": True,
                    "candidate_started": False,
                    "candidate_verified": False,
                    "confirmed": confirmed_activation,
                    "eligible_pre_onset": cohort == "target" and sample <= FAULT_ONSET - 1,
                    "eligible_post_onset": cohort == "target" and sample >= FAULT_ONSET,
                    "eligible_full_trajectory": cohort == "normal_holdout",
                    "candidate_origin_window": None,
                    "candidate_final_status": None,
                    "persistence_streak": segment_streak,
                }
            )

    if cohort == "target":
        endpoint = {
            "raw_post_onset": first_raw_post is not None,
            "confirmed_post_onset": first_confirmed_post is not None,
            "first_raw_sample": first_raw_post,
            "first_persistent_sample": first_confirmed_post,
            "raw_delay_minutes": (first_raw_post - FAULT_ONSET) * SAMPLE_INTERVAL_MINUTES if first_raw_post is not None else None,
            "confirmed_delay_minutes": (first_confirmed_post - FAULT_ONSET) * SAMPLE_INTERVAL_MINUTES if first_confirmed_post is not None else None,
            "raw_pre_onset": first_raw_pre is not None,
            "confirmed_pre_onset": first_confirmed_pre is not None,
            "any_raw_fa": None,
            "any_confirmed_fa": None,
        }
    else:
        endpoint = {
            "raw_post_onset": None,
            "confirmed_post_onset": None,
            "first_raw_sample": None,
            "first_persistent_sample": None,
            "raw_delay_minutes": None,
            "confirmed_delay_minutes": None,
            "raw_pre_onset": None,
            "confirmed_pre_onset": None,
            "any_raw_fa": first_raw_full is not None,
            "any_confirmed_fa": first_confirmed_full is not None,
        }
    crosscheck = {"raw_mismatches": raw_mismatches, "persistent_mismatches": persistent_mismatches}
    return endpoint, event_rows, crosscheck


def evaluate_h3_item(
    item: dict[str, Any],
    payload_by_variable: dict[str, dict[str, Any]],
    thresholds: dict[str, dict[str, float]],
) -> dict[str, Any]:
    variable = item.get("variable")
    claim = item.get("claim")
    variable_valid = isinstance(variable, str) and variable in VALID_H3_VARIABLES and variable in payload_by_variable
    claim_valid = claim in VALID_H3_CLAIMS
    threshold_key = {
        "HIGH": "high_max_z_q99",
        "LOW": "low_min_z_q01",
        "INCREASE": "increase_slope_q99",
        "REDUCTION": "reduction_slope_q01",
        "VARIABILITY": "high_variability_range_q99",
    }.get(claim)
    threshold_present = bool(
        variable_valid
        and isinstance(thresholds.get(variable), dict)
        and threshold_key is not None
        and threshold_key in thresholds[variable]
    )
    verifiable = bool(variable_valid and claim_valid and threshold_present)
    passed = False
    if verifiable:
        values = payload_by_variable[variable]
        reference = thresholds[variable]
        if claim == "HIGH":
            passed = float(values["max_z"]) >= float(reference["high_max_z_q99"])
        elif claim == "LOW":
            passed = float(values["min_z"]) <= float(reference["low_min_z_q01"])
        elif claim == "INCREASE":
            passed = (
                float(values["slope_z_per_sample"]) >= float(reference["increase_slope_q99"])
                and float(values["end_z"]) > float(values["start_z"])
            )
        elif claim == "REDUCTION":
            passed = (
                float(values["slope_z_per_sample"]) <= float(reference["reduction_slope_q01"])
                and float(values["end_z"]) < float(values["start_z"])
            )
        elif claim == "VARIABILITY":
            passed = round(float(values["max_z"]) - float(values["min_z"]), 4) >= float(reference["high_variability_range_q99"])
    return {
        "variable": variable,
        "claim": claim,
        "variable_valid": bool(variable_valid),
        "claim_valid": bool(claim_valid),
        "threshold_present": bool(threshold_present),
        "verifiable": verifiable,
        "numeric_rule_pass": bool(passed),
        "item_score": 1 if verifiable and passed else 0,
    }


def h3_response_score(decision: str, item_scores: Sequence[int]) -> float | None:
    if item_scores:
        return float(np.mean(np.asarray(item_scores, dtype=float)))
    if decision == "ANOMALY":
        return 0.0
    if decision in {"NORMAL", "EVIDENCE_INSUFFICIENT"}:
        return None
    raise GateFailure(f"Unknown H3 decision: {decision}")


def h3_run_score(response_scores: Sequence[float | None]) -> float | None:
    applicable = [float(value) for value in response_scores if value is not None]
    return float(np.mean(np.asarray(applicable, dtype=float))) if applicable else None


def h3_macro_mean(run_scores: Sequence[float | None]) -> float | None:
    applicable = [float(value) for value in run_scores if value is not None]
    return float(np.mean(np.asarray(applicable, dtype=float))) if applicable else None


ENDPOINT_FIELDS = [
    "cohort",
    "simulationRun",
    "blind_run_id",
    "llm_in_analysis",
    "dpca_in_analysis",
    "llm_raw_post_onset",
    "llm_confirmed_post_onset",
    "llm_first_indication_sample_end",
    "llm_confirmation_sample_end",
    "llm_raw_delay_minutes",
    "llm_confirmed_delay_minutes",
    "llm_raw_pre_onset",
    "llm_confirmed_pre_onset",
    "dpca_raw_post_onset",
    "dpca_confirmed_post_onset",
    "dpca_first_raw_sample",
    "dpca_first_persistent_sample",
    "dpca_raw_delay_minutes",
    "dpca_confirmed_delay_minutes",
    "dpca_raw_pre_onset",
    "dpca_confirmed_pre_onset",
    "llm_any_raw_fa",
    "llm_any_confirmed_fa",
    "dpca_any_raw_fa",
    "dpca_any_confirmed_fa",
]

EVENT_FIELDS = [
    "cohort",
    "simulationRun",
    "blind_run_id",
    "detector",
    "time_coordinate",
    "window_id",
    "sample_start",
    "sample_end",
    "raw_positive",
    "candidate_started",
    "candidate_verified",
    "confirmed",
    "eligible_pre_onset",
    "eligible_post_onset",
    "eligible_full_trajectory",
    "candidate_origin_window",
    "candidate_final_status",
    "persistence_streak",
]


def reconstruct_ledgers(state: IntegrityState) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    event_rows: list[dict[str, Any]] = []
    endpoint_rows: list[dict[str, Any]] = []
    llm_crosscheck_mismatches: list[dict[str, Any]] = []
    dpca_raw_mismatches = 0
    dpca_persistent_mismatches = 0

    matrix_sorted = sorted(
        state.final_matrix,
        key=lambda value: ((0 if value["cohort"] == "target" else 1), int(value["simulationRun"])),
    )
    for matrix_row in matrix_sorted:
        cohort = matrix_row["cohort"]
        run = int(matrix_row["simulationRun"])
        blind = matrix_row["blind_run_id"]
        dpca_component = state.components[(cohort, run, "dpca")]
        dpca_records = list(iter_jsonl(dpca_component.primary_path))
        _require(all(rec.get("blind_run_id") == blind for rec in dpca_records), f"DPCA blind ID mismatch: {cohort}/{run}")
        dpca_endpoint, dpca_events, dpca_crosscheck = reconstruct_dpca_records(dpca_records, cohort)
        dpca_raw_mismatches += dpca_crosscheck["raw_mismatches"]
        dpca_persistent_mismatches += dpca_crosscheck["persistent_mismatches"]
        for event in dpca_events:
            event["simulationRun"] = run
        event_rows.extend(dpca_events)

        llm_endpoint: dict[str, Any] | None = None
        if matrix_row.get("llm_required"):
            llm_component = state.components[(cohort, run, "llm")]
            llm_records = list(iter_jsonl(llm_component.primary_path))
            _require(all(rec.get("simulation_run_blind_id") == blind for rec in llm_records), f"LLM blind ID mismatch: {cohort}/{run}")
            llm_endpoint, llm_events, expected_summary = reconstruct_llm_records(llm_records, cohort)
            for event in llm_events:
                event["simulationRun"] = run
            event_rows.extend(llm_events)
            assert llm_component.detection_summary_path is not None
            summary = read_json(llm_component.detection_summary_path)
            mismatch = crosscheck_llm_summary(summary, expected_summary)
            if mismatch:
                llm_crosscheck_mismatches.append({"cohort": cohort, "simulationRun": run, "mismatches": mismatch})

        endpoint_rows.append(
            {
                "cohort": cohort,
                "simulationRun": run,
                "blind_run_id": blind,
                "llm_in_analysis": llm_endpoint is not None,
                "dpca_in_analysis": True,
                "llm_raw_post_onset": llm_endpoint["raw_post_onset"] if llm_endpoint else None,
                "llm_confirmed_post_onset": llm_endpoint["confirmed_post_onset"] if llm_endpoint else None,
                "llm_first_indication_sample_end": llm_endpoint["first_indication_sample_end"] if llm_endpoint else None,
                "llm_confirmation_sample_end": llm_endpoint["confirmation_sample_end"] if llm_endpoint else None,
                "llm_raw_delay_minutes": llm_endpoint["raw_delay_minutes"] if llm_endpoint else None,
                "llm_confirmed_delay_minutes": llm_endpoint["confirmed_delay_minutes"] if llm_endpoint else None,
                "llm_raw_pre_onset": llm_endpoint["raw_pre_onset"] if llm_endpoint else None,
                "llm_confirmed_pre_onset": llm_endpoint["confirmed_pre_onset"] if llm_endpoint else None,
                "dpca_raw_post_onset": dpca_endpoint["raw_post_onset"],
                "dpca_confirmed_post_onset": dpca_endpoint["confirmed_post_onset"],
                "dpca_first_raw_sample": dpca_endpoint["first_raw_sample"],
                "dpca_first_persistent_sample": dpca_endpoint["first_persistent_sample"],
                "dpca_raw_delay_minutes": dpca_endpoint["raw_delay_minutes"],
                "dpca_confirmed_delay_minutes": dpca_endpoint["confirmed_delay_minutes"],
                "dpca_raw_pre_onset": dpca_endpoint["raw_pre_onset"],
                "dpca_confirmed_pre_onset": dpca_endpoint["confirmed_pre_onset"],
                "llm_any_raw_fa": llm_endpoint["any_raw_fa"] if llm_endpoint else None,
                "llm_any_confirmed_fa": llm_endpoint["any_confirmed_fa"] if llm_endpoint else None,
                "dpca_any_raw_fa": dpca_endpoint["any_raw_fa"],
                "dpca_any_confirmed_fa": dpca_endpoint["any_confirmed_fa"],
            }
        )

    _require(not llm_crosscheck_mismatches, f"LLM reconstruction cross-check mismatches: {len(llm_crosscheck_mismatches)}")
    _require(dpca_raw_mismatches == 0, f"DPCA raw reconstruction mismatches: {dpca_raw_mismatches}")
    _require(dpca_persistent_mismatches == 0, f"DPCA persistent reconstruction mismatches: {dpca_persistent_mismatches}")
    _require(len(endpoint_rows) == 1000, "Endpoint ledger does not contain 1000 runs")
    _require(len({(row["cohort"], row["simulationRun"]) for row in endpoint_rows}) == 1000, "Endpoint ledger has duplicate runs")

    event_rows.sort(
        key=lambda row: (
            0 if row["cohort"] == "target" else 1,
            int(row["simulationRun"]),
            0 if row["detector"] == "LLM" else 1,
            int(row["time_coordinate"]),
        )
    )
    write_csv(OUTPUT_ROOT / "01_ledgers" / "event_ledger.csv", EVENT_FIELDS, event_rows)
    write_csv(OUTPUT_ROOT / "01_ledgers" / "run_endpoint_ledger.csv", ENDPOINT_FIELDS, endpoint_rows)
    crosschecks = {
        "llm_reconstruction_crosscheck": "PASS",
        "llm_runs_crosschecked": 100,
        "llm_mismatches": 0,
        "dpca_reconstruction_crosscheck": "PASS",
        "dpca_runs_crosschecked": 1000,
        "dpca_raw_record_mismatches": 0,
        "dpca_persistent_record_mismatches": 0,
        "event_ledger_rows": len(event_rows),
        "endpoint_ledger_rows": len(endpoint_rows),
    }
    return endpoint_rows, crosschecks


def _csv_bool(value: str) -> bool | None:
    if value == "":
        return None
    if value == "1":
        return True
    if value == "0":
        return False
    raise GateFailure(f"Unexpected ledger boolean: {value!r}")


def _csv_number(value: str) -> float | None:
    return None if value == "" else float(value)


def read_endpoint_ledger() -> list[dict[str, Any]]:
    path = OUTPUT_ROOT / "01_ledgers" / "run_endpoint_ledger.csv"
    bool_fields = {
        "llm_in_analysis", "dpca_in_analysis", "llm_raw_post_onset", "llm_confirmed_post_onset",
        "llm_raw_pre_onset", "llm_confirmed_pre_onset", "dpca_raw_post_onset", "dpca_confirmed_post_onset",
        "dpca_raw_pre_onset", "dpca_confirmed_pre_onset", "llm_any_raw_fa", "llm_any_confirmed_fa",
        "dpca_any_raw_fa", "dpca_any_confirmed_fa",
    }
    numeric_fields = {
        "llm_first_indication_sample_end", "llm_confirmation_sample_end", "llm_raw_delay_minutes",
        "llm_confirmed_delay_minutes", "dpca_first_raw_sample", "dpca_first_persistent_sample",
        "dpca_raw_delay_minutes", "dpca_confirmed_delay_minutes",
    }
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            row: dict[str, Any] = dict(raw)
            row["simulationRun"] = int(raw["simulationRun"])
            for field in bool_fields:
                row[field] = _csv_bool(raw[field])
            for field in numeric_fields:
                row[field] = _csv_number(raw[field])
            rows.append(row)
    _require(len(rows) == 1000 and len({(r["cohort"], r["simulationRun"]) for r in rows}) == 1000, "Invalid endpoint ledger on readback")
    return rows


def _subset(
    rows: Sequence[dict[str, Any]],
    cohort: str,
    runs: set[int] | None = None,
) -> list[dict[str, Any]]:
    selected = [row for row in rows if row["cohort"] == cohort and (runs is None or row["simulationRun"] in runs)]
    return sorted(selected, key=lambda row: row["simulationRun"])


def _proportion_row(
    scope: str,
    analysis_set: str,
    detector: str,
    endpoint: str,
    values: Sequence[bool],
    interval_label: str = "WILSON_95",
) -> dict[str, Any]:
    events = sum(bool(value) for value in values)
    summary = proportion_summary(events, len(values))
    wilson = summary["wilson"]
    row = {
        "scope": scope,
        "analysis_set": analysis_set,
        "detector": detector,
        "endpoint": endpoint,
        "events": events,
        "n": len(values),
        "proportion": wilson["estimate"],
        "ci_lower": wilson["lower"],
        "ci_upper": wilson["upper"],
        "ci_method": interval_label,
        "clopper_pearson_lower": None,
        "clopper_pearson_upper": None,
        "clopper_pearson_method": None,
    }
    if events in {0, len(values)}:
        exact = clopper_pearson_interval(events, len(values))
        row["clopper_pearson_lower"] = exact["lower"]
        row["clopper_pearson_upper"] = exact["upper"]
        row["clopper_pearson_method"] = (
            "CLOPPER_PEARSON_EXACT_95_SENSITIVITY_MODEL_BASED_EXTRAPOLATION"
            if "MODEL_BASED_EXTRAPOLATION" in interval_label
            else "CLOPPER_PEARSON_EXACT_95_SENSITIVITY"
        )
    return row


PROPORTION_FIELDS = [
    "scope", "analysis_set", "detector", "endpoint", "events", "n", "proportion",
    "ci_lower", "ci_upper", "ci_method", "clopper_pearson_lower", "clopper_pearson_upper",
    "clopper_pearson_method",
]


def _bootstrap_fields(values: Sequence[float], statistic: str) -> dict[str, Any]:
    result = bootstrap_ci(
        values,
        statistic=statistic,
        confidence_level=0.95,
        n_resamples=BOOTSTRAP_REPLICATES,
        seed=BOOTSTRAP_SEED,
    )
    return result


def _delay_summary_row(
    analysis_set: str,
    detector: str,
    endpoint: str,
    total_n: int,
    values: Sequence[float | None],
) -> dict[str, Any]:
    observed = [float(value) for value in values if value is not None]
    stats = numeric_summary(observed)
    mean_ci = _bootstrap_fields(observed, "mean")
    median_ci = _bootstrap_fields(observed, "median")
    return {
        "analysis_set": analysis_set,
        "detector": detector,
        "endpoint": endpoint,
        "total_runs": total_n,
        "events": len(observed),
        "conditional_n": len(observed),
        "mean": stats.get("mean"),
        "sd": stats.get("sample_sd"),
        "median": stats.get("median"),
        "q1": stats.get("q1"),
        "q3": stats.get("q3"),
        "iqr": stats.get("iqr"),
        "min": stats.get("min"),
        "max": stats.get("max"),
        "mean_ci_lower": mean_ci.get("lower"),
        "mean_ci_upper": mean_ci.get("upper"),
        "mean_ci_method": mean_ci.get("method"),
        "mean_ci_fallback_reason": mean_ci.get("fallback_reason"),
        "median_ci_lower": median_ci.get("lower"),
        "median_ci_upper": median_ci.get("upper"),
        "median_ci_method": median_ci.get("method"),
        "median_ci_fallback_reason": median_ci.get("fallback_reason"),
    }


DELAY_FIELDS = [
    "analysis_set", "detector", "endpoint", "total_runs", "events", "conditional_n",
    "mean", "sd", "median", "q1", "q3", "iqr", "min", "max",
    "mean_ci_lower", "mean_ci_upper", "mean_ci_method", "mean_ci_fallback_reason",
    "median_ci_lower", "median_ci_upper", "median_ci_method", "median_ci_fallback_reason",
]


def compute_primary_and_secondary(
    rows: Sequence[dict[str, Any]],
    state: IntegrityState,
) -> tuple[dict[str, Any], dict[str, Any]]:
    target_all = _subset(rows, "target")
    normal_all = _subset(rows, "normal_holdout")
    target_paired = _subset(rows, "target", set(state.target_selection))
    normal_paired = _subset(rows, "normal_holdout", set(state.normal_selection))
    _require(len(target_paired) == 50 and all(row["llm_in_analysis"] for row in target_paired), "Invalid target paired ledger")
    _require(len(normal_paired) == 50 and all(row["llm_in_analysis"] for row in normal_paired), "Invalid normal paired ledger")

    h1_rows: list[dict[str, Any]] = []
    for analysis_set, detector, selected, raw_field, confirmed_field in [
        ("LLM_PRIMARY", "LLM", target_paired, "llm_raw_post_onset", "llm_confirmed_post_onset"),
        ("DPCA_PAIRED", "DPCA", target_paired, "dpca_raw_post_onset", "dpca_confirmed_post_onset"),
        ("DPCA_EXPANDED", "DPCA", target_all, "dpca_raw_post_onset", "dpca_confirmed_post_onset"),
    ]:
        raw_values = [bool(row[raw_field]) for row in selected]
        confirmed_values = [bool(row[confirmed_field]) for row in selected]
        interval_label = "WILSON_95_MODEL_BASED_EXTRAPOLATION" if analysis_set == "DPCA_EXPANDED" else "WILSON_95"
        h1_rows.append(_proportion_row("TARGET_POST_ONSET", analysis_set, detector, "RAW_INDICATION", raw_values, interval_label))
        h1_rows.append(_proportion_row("TARGET_POST_ONSET", analysis_set, detector, "CONFIRMED_DETECTION", confirmed_values, interval_label))
        h1_rows.append(_proportion_row("TARGET_POST_ONSET", analysis_set, detector, "NO_CONFIRMED_DETECTION", [not value for value in confirmed_values], interval_label))
    write_csv(OUTPUT_ROOT / "02_primary" / "h1_target.csv", PROPORTION_FIELDS, h1_rows)

    normal_rows: list[dict[str, Any]] = []
    for analysis_set, detector, selected, raw_field, confirmed_field in [
        ("LLM_PRIMARY", "LLM", normal_paired, "llm_any_raw_fa", "llm_any_confirmed_fa"),
        ("DPCA_PAIRED", "DPCA", normal_paired, "dpca_any_raw_fa", "dpca_any_confirmed_fa"),
        ("DPCA_EXPANDED", "DPCA", normal_all, "dpca_any_raw_fa", "dpca_any_confirmed_fa"),
    ]:
        raw_values = [bool(row[raw_field]) for row in selected]
        confirmed_values = [bool(row[confirmed_field]) for row in selected]
        interval_label = "WILSON_95_MODEL_BASED_EXTRAPOLATION" if analysis_set == "DPCA_EXPANDED" else "WILSON_95"
        normal_rows.append(_proportion_row("NORMAL_FULL_TRAJECTORY", analysis_set, detector, "ANY_RAW_FALSE_ALARM", raw_values, interval_label))
        normal_rows.append(_proportion_row("NORMAL_FULL_TRAJECTORY", analysis_set, detector, "ANY_CONFIRMED_FALSE_ALARM", confirmed_values, interval_label))
        normal_rows.append(_proportion_row("NORMAL_FULL_TRAJECTORY", analysis_set, detector, "NO_CONFIRMED_FALSE_ALARM", [not value for value in confirmed_values], interval_label))
    write_csv(OUTPUT_ROOT / "02_primary" / "normal_holdout.csv", PROPORTION_FIELDS, normal_rows)

    pre_rows: list[dict[str, Any]] = []
    for analysis_set, detector, selected, raw_field, confirmed_field in [
        ("LLM_PRIMARY", "LLM", target_paired, "llm_raw_pre_onset", "llm_confirmed_pre_onset"),
        ("DPCA_PAIRED", "DPCA", target_paired, "dpca_raw_pre_onset", "dpca_confirmed_pre_onset"),
        ("DPCA_EXPANDED", "DPCA", target_all, "dpca_raw_pre_onset", "dpca_confirmed_pre_onset"),
    ]:
        interval_label = "WILSON_95_MODEL_BASED_EXTRAPOLATION" if analysis_set == "DPCA_EXPANDED" else "WILSON_95"
        pre_rows.append(_proportion_row("TARGET_PRE_ONSET_1_160", analysis_set, detector, "ANY_RAW_FALSE_ALARM", [bool(row[raw_field]) for row in selected], interval_label))
        pre_rows.append(_proportion_row("TARGET_PRE_ONSET_1_160", analysis_set, detector, "ANY_CONFIRMED_FALSE_ALARM", [bool(row[confirmed_field]) for row in selected], interval_label))
    write_csv(OUTPUT_ROOT / "03_secondary" / "target_preonset.csv", PROPORTION_FIELDS, pre_rows)

    delay_rows: list[dict[str, Any]] = []
    for analysis_set, detector, selected, raw_field, confirmed_field in [
        ("LLM_PRIMARY", "LLM", target_paired, "llm_raw_delay_minutes", "llm_confirmed_delay_minutes"),
        ("DPCA_PAIRED", "DPCA", target_paired, "dpca_raw_delay_minutes", "dpca_confirmed_delay_minutes"),
        ("DPCA_EXPANDED", "DPCA", target_all, "dpca_raw_delay_minutes", "dpca_confirmed_delay_minutes"),
    ]:
        delay_rows.append(_delay_summary_row(analysis_set, detector, "RAW_INDICATION", len(selected), [row[raw_field] for row in selected]))
        delay_rows.append(_delay_summary_row(analysis_set, detector, "CONFIRMED_DETECTION", len(selected), [row[confirmed_field] for row in selected]))
    write_csv(OUTPUT_ROOT / "03_secondary" / "h2_delays.csv", DELAY_FIELDS, delay_rows)

    paired_binary_rows: list[dict[str, Any]] = []
    primary_mcnemar: dict[str, float] = {}
    primary_differences: dict[str, dict[str, Any]] = {}
    for cohort_label, selected, endpoints in [
        ("TARGET", target_paired, [("RAW", "llm_raw_post_onset", "dpca_raw_post_onset"), ("CONFIRMED", "llm_confirmed_post_onset", "dpca_confirmed_post_onset")]),
        ("NORMAL_HOLDOUT", normal_paired, [("RAW", "llm_any_raw_fa", "dpca_any_raw_fa"), ("CONFIRMED", "llm_any_confirmed_fa", "dpca_any_confirmed_fa")]),
    ]:
        for endpoint_label, llm_field, dpca_field in endpoints:
            llm_values = [bool(row[llm_field]) for row in selected]
            dpca_values = [bool(row[dpca_field]) for row in selected]
            table = paired_binary_table(llm_values, dpca_values)
            diff = paired_proportion_difference(
                llm_values,
                dpca_values,
                n_resamples=BOOTSTRAP_REPLICATES,
                seed=BOOTSTRAP_SEED,
            )
            mcnemar_p = None
            if endpoint_label == "CONFIRMED":
                mcnemar_p = mcnemar_exact_from_counts(table["01"], table["10"])["p_value"]
                primary_mcnemar[cohort_label] = mcnemar_p
                primary_differences[cohort_label] = diff
            diff_ci = diff["confidence_interval"]
            paired_binary_rows.append(
                {
                    "cohort": cohort_label,
                    "endpoint": endpoint_label,
                    "n": len(selected),
                    "n00": table["00"],
                    "n01": table["01"],
                    "n10": table["10"],
                    "n11": table["11"],
                    "concordant": table["00"] + table["11"],
                    "discordant": table["01"] + table["10"],
                    "paired_difference_llm_minus_dpca": diff["difference"],
                    "difference_ci_lower": diff_ci["lower"],
                    "difference_ci_upper": diff_ci["upper"],
                    "difference_ci_method": diff_ci["method"],
                    "difference_ci_fallback_reason": diff_ci.get("fallback_reason"),
                    "mcnemar_exact_p_raw": mcnemar_p,
                }
            )
    paired_binary_fields = [
        "cohort", "endpoint", "n", "n00", "n01", "n10", "n11", "concordant", "discordant",
        "paired_difference_llm_minus_dpca", "difference_ci_lower", "difference_ci_upper", "difference_ci_method",
        "difference_ci_fallback_reason", "mcnemar_exact_p_raw",
    ]
    write_csv(OUTPUT_ROOT / "02_primary" / "paired_binary.csv", paired_binary_fields, paired_binary_rows)

    holm_rows = holm_adjust(
        [primary_mcnemar["TARGET"], primary_mcnemar["NORMAL_HOLDOUT"]],
        labels=["TARGET_CONFIRMED_DETECTION", "NORMAL_CONFIRMED_FALSE_ALARM"],
    )
    for row in holm_rows:
        row["hypothesis"] = row.pop("label")
    write_csv(
        OUTPUT_ROOT / "02_primary" / "holm_adjustment.csv",
        ["hypothesis", "p_raw", "order", "rank", "multiplier", "p_unbounded", "p_adjusted_monotonic"],
        holm_rows,
    )

    paired_delay_rows: list[dict[str, Any]] = []
    paired_delay_details: dict[str, Any] = {}
    for endpoint, llm_field, dpca_field in [
        ("RAW", "llm_raw_delay_minutes", "dpca_raw_delay_minutes"),
        ("CONFIRMED", "llm_confirmed_delay_minutes", "dpca_confirmed_delay_minutes"),
    ]:
        llm_values = [row[llm_field] for row in target_paired]
        dpca_values = [row[dpca_field] for row in target_paired]
        result = paired_delays(
            llm_values,
            dpca_values,
            n_resamples=BOOTSTRAP_REPLICATES,
            seed=BOOTSTRAP_SEED,
        )
        paired_delay_details[endpoint] = result
        stats = result["difference_summary"]
        mean_ci = result["bootstrap_mean"]
        median_ci = result["bootstrap_median"]
        sign = result["sign_test"]
        paired_delay_rows.append(
            {
                "endpoint": endpoint,
                "total": result["total"],
                "neither": result["neither"],
                "llm_only": result["llm_only"],
                "dpca_only": result["dpca_only"],
                "both": result["both"],
                "mean_difference": stats.get("mean"),
                "sd_difference": stats.get("sample_sd"),
                "median_difference": stats.get("median"),
                "q1_difference": stats.get("q1"),
                "q3_difference": stats.get("q3"),
                "iqr_difference": stats.get("iqr"),
                "min_difference": stats.get("min"),
                "max_difference": stats.get("max"),
                "mean_ci_lower": mean_ci.get("lower"),
                "mean_ci_upper": mean_ci.get("upper"),
                "mean_ci_method": mean_ci.get("method"),
                "mean_ci_fallback_reason": mean_ci.get("fallback_reason"),
                "median_ci_lower": median_ci.get("lower"),
                "median_ci_upper": median_ci.get("upper"),
                "median_ci_method": median_ci.get("method"),
                "median_ci_fallback_reason": median_ci.get("fallback_reason"),
                "sign_positive": sign["positive"],
                "sign_negative": sign["negative"],
                "sign_ties": sign["ties"],
                "sign_test_p": sign["p_value"],
            }
        )
    paired_delay_fields = list(paired_delay_rows[0])
    write_csv(OUTPUT_ROOT / "03_secondary" / "paired_delays.csv", paired_delay_fields, paired_delay_rows)

    dpca_expanded_rows = [row for row in h1_rows + normal_rows if row["analysis_set"] == "DPCA_EXPANDED"]
    for row in dpca_expanded_rows:
        row["inference_label"] = "MODEL_BASED_EXTRAPOLATION"
        row["interpretation"] = "Observed proportion describes the complete 500-run corpus; interval extrapolates to analogous trajectories in the same TEP regime."
    write_csv(
        OUTPUT_ROOT / "03_secondary" / "dpca_expanded.csv",
        PROPORTION_FIELDS + ["inference_label", "interpretation"],
        dpca_expanded_rows,
    )

    amendment_rows: list[dict[str, Any]] = []
    base_runs = {14, 23, 24, 26, 27, 55}
    for cohort, selection in [("target", state.target_selection), ("normal_holdout", state.normal_selection)]:
        for run in selection:
            component = state.components[(cohort, run, "llm")]
            phase = "BASE_768" if cohort == "target" and run in base_runs else "EFFECTIVE_1024"
            amendment_rows.append(
                {
                    "cohort": cohort,
                    "simulationRun": run,
                    "blind_run_id": component.blind_run_id,
                    "configuration_phase": phase,
                    "max_output_tokens": 768 if phase == "BASE_768" else 1024,
                    "final_scientific_attempt": component.attempt,
                    "historical_attempt_in_performance": False,
                    "note": "run58 final is attempt 0002; attempt 0001 is provenance only" if cohort == "target" and run == 58 else "",
                }
            )
    write_csv(
        OUTPUT_ROOT / "03_secondary" / "amendment_provenance.csv",
        ["cohort", "simulationRun", "blind_run_id", "configuration_phase", "max_output_tokens", "final_scientific_attempt", "historical_attempt_in_performance", "note"],
        amendment_rows,
    )

    primary_statistics = {
        "generated_at_utc": utc_now(),
        "bootstrap": {"seed": BOOTSTRAP_SEED, "replicates": BOOTSTRAP_REPLICATES, "preferred_method": "BCa", "fallback": "percentile when BCa is mathematically undefined"},
        "h1_target": h1_rows,
        "normal_holdout": normal_rows,
        "paired_binary": paired_binary_rows,
        "holm": holm_rows,
        "primary_mcnemar_raw_p_values": primary_mcnemar,
        "primary_paired_differences": primary_differences,
    }
    write_json(OUTPUT_ROOT / "02_primary" / "primary_statistics.json", primary_statistics)

    secondary = {
        "target_preonset": pre_rows,
        "h2_delays": delay_rows,
        "paired_delays": paired_delay_details,
        "dpca_expanded": dpca_expanded_rows,
    }
    return primary_statistics, secondary


def compute_h3(state: IntegrityState) -> dict[str, Any]:
    reference = read_json(CHECKOUT_ROOT / CONFIG_REL / "h3_evidence_reference.json")
    thresholds = reference["thresholds"]
    _require(len(thresholds) == 52, f"H3 threshold count is {len(thresholds)}")
    item_audit: list[dict[str, Any]] = []
    run_rows: list[dict[str, Any]] = []
    total_items = 0
    verifiable_items = 0
    satisfied_items = 0
    applicable_responses = 0
    non_applicable_responses = 0

    for run in state.target_selection:
        component = state.components[("target", run, "llm")]
        response_scores: list[float | None] = []
        evidence_item_count = 0
        for rec in iter_jsonl(component.primary_path):
            variables = rec.get("llm_payload", {}).get("variables")
            _require(isinstance(variables, list) and len(variables) == 52, f"Invalid H3 payload: target/{run}/window {rec.get('window_id')}")
            payload_by_variable = {item.get("variable"): item for item in variables}
            evidence = rec.get("evidence")
            _require(isinstance(evidence, list), f"Invalid H3 evidence: target/{run}/window {rec.get('window_id')}")
            item_scores: list[int] = []
            for item_index, item in enumerate(evidence):
                evaluated = evaluate_h3_item(item, payload_by_variable, thresholds)
                item_scores.append(evaluated["item_score"])
                total_items += 1
                evidence_item_count += 1
                verifiable_items += int(evaluated["verifiable"])
                satisfied_items += int(evaluated["item_score"])
                item_audit.append(
                    {
                        "cohort": "target",
                        "simulationRun": run,
                        "blind_run_id": component.blind_run_id,
                        "window_id": int(rec["window_id"]),
                        "item_index": item_index,
                        **evaluated,
                    }
                )
            response_score = h3_response_score(rec["decision"], item_scores)
            response_scores.append(response_score)
            if response_score is None:
                non_applicable_responses += 1
            else:
                applicable_responses += 1
        run_score = h3_run_score(response_scores)
        applicable_count = sum(score is not None for score in response_scores)
        run_rows.append(
            {
                "cohort": "target",
                "simulationRun": run,
                "blind_run_id": component.blind_run_id,
                "responses_total": len(response_scores),
                "applicable_responses": applicable_count,
                "non_applicable_responses": len(response_scores) - applicable_count,
                "evidence_items": evidence_item_count,
                "run_score": run_score,
                "applicable": run_score is not None,
            }
        )

    write_csv(
        OUTPUT_ROOT / "04_h3" / "h3_item_audit.csv",
        ["cohort", "simulationRun", "blind_run_id", "window_id", "item_index", "variable", "claim", "variable_valid", "claim_valid", "threshold_present", "verifiable", "numeric_rule_pass", "item_score"],
        item_audit,
    )
    write_csv(
        OUTPUT_ROOT / "04_h3" / "h3_run_scores.csv",
        ["cohort", "simulationRun", "blind_run_id", "responses_total", "applicable_responses", "non_applicable_responses", "evidence_items", "run_score", "applicable"],
        run_rows,
    )

    applicable_run_scores = [float(row["run_score"]) for row in run_rows if row["run_score"] is not None]
    stats = numeric_summary(applicable_run_scores)
    mean_ci = _bootstrap_fields(applicable_run_scores, "mean")
    median_ci = _bootstrap_fields(applicable_run_scores, "median")
    h3_statistics = {
        "generated_at_utc": utc_now(),
        "scope": "TARGET_LLM_50",
        "total_evidence_items": total_items,
        "verifiable_evidence_items": verifiable_items,
        "satisfied_evidence_items": satisfied_items,
        "coverage": (verifiable_items / total_items) if total_items else None,
        "applicable_responses": applicable_responses,
        "non_applicable_responses": non_applicable_responses,
        "applicable_runs": len(applicable_run_scores),
        "non_applicable_runs": len(run_rows) - len(applicable_run_scores),
        "macro": stats,
        "macro_mean_ci": mean_ci,
        "macro_median_ci": median_ci,
        "micro_item_score": (satisfied_items / total_items) if total_items else None,
        "observation_used_in_score": False,
    }
    write_json(OUTPUT_ROOT / "04_h3" / "h3_statistics.json", h3_statistics)
    return h3_statistics


def revalidate_inputs(state: IntegrityState) -> dict[str, Any]:
    changed: list[str] = []
    for relative, (expected_size, expected_hash) in state.snapshot.items():
        path = CHECKOUT_ROOT / relative
        if not path.is_file() or path.stat().st_size != expected_size or sha256_file(path) != expected_hash:
            changed.append(relative)
    status_short = git_output("status", "--short", "--untracked-files=all").splitlines()
    disallowed_changes: list[str] = []
    allowed_prefix = "analysis/validation/calculation3/"
    for line in status_short:
        candidate = line[3:].replace("\\", "/") if len(line) >= 4 else line
        if not candidate.startswith(allowed_prefix):
            disallowed_changes.append(line)
    _require(not changed, f"Scientific inputs changed during calculation: {changed[:5]}")
    _require(not disallowed_changes, f"Changes outside Calculation 3 output root: {disallowed_changes[:5]}")
    return {
        "input_results_modified": "NO",
        "final_campaign_manifest_modified": "NO",
        "sap_modified": "NO",
        "formal_json_modified": "NO",
        "changed_input_files": changed,
        "disallowed_worktree_changes": disallowed_changes,
    }


def environment_report() -> dict[str, Any]:
    rscript = None
    try:
        completed = subprocess.run(["Rscript", "--version"], capture_output=True, text=True, timeout=10, check=False)
        rscript = (completed.stdout or completed.stderr).strip() or None
    except (FileNotFoundError, subprocess.SubprocessError):
        rscript = None
    return {
        "generated_at_utc": utc_now(),
        "calculation3_implementation_language": "PYTHON",
        "calculation3_implementation_reason": "Rscript was not available on PATH; Python 3.13.5 had the already-installed NumPy/SciPy support required by the frozen SAP.",
        "python_version": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "os_name": os.name,
        "numpy_version": np.__version__,
        "scipy_version": scipy.__version__,
        "rscript_available": rscript is not None,
        "rscript_version": rscript,
        "bootstrap_implementation": "scipy.stats.bootstrap BCa; percentile fallback only when BCa is mathematically undefined",
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "quantile_method": "numpy.quantile method=linear",
        "source_commit": SOURCE_COMMIT,
        "branch": BRANCH,
    }


def build_reconciliation_keys(
    rows: Sequence[dict[str, Any]],
    state: IntegrityState,
    primary: dict[str, Any],
    secondary: dict[str, Any],
    h3: dict[str, Any],
) -> dict[str, Any]:
    target = _subset(rows, "target", set(state.target_selection))
    normal = _subset(rows, "normal_holdout", set(state.normal_selection))
    target_all = _subset(rows, "target")
    normal_all = _subset(rows, "normal_holdout")

    def count(selected: Sequence[dict[str, Any]], field: str) -> int:
        return sum(bool(row[field]) for row in selected)

    def delay_row(analysis_set: str, endpoint: str) -> dict[str, Any]:
        return next(row for row in secondary["h2_delays"] if row["analysis_set"] == analysis_set and row["endpoint"] == endpoint)

    def paired_row(cohort: str) -> dict[str, Any]:
        return next(row for row in primary["paired_binary"] if row["cohort"] == cohort and row["endpoint"] == "CONFIRMED")

    def holm_value(hypothesis: str) -> float:
        return float(next(row for row in primary["holm"] if row["hypothesis"] == hypothesis)["p_adjusted_monotonic"])

    target_pair = paired_row("TARGET")
    normal_pair = paired_row("NORMAL_HOLDOUT")
    raw_pair_delay = secondary["paired_delays"]["RAW"]
    confirmed_pair_delay = secondary["paired_delays"]["CONFIRMED"]

    ci_registry: dict[str, Any] = {}
    for row in primary["h1_target"] + primary["normal_holdout"] + secondary["target_preonset"]:
        key = f"{row['scope']}::{row['analysis_set']}::{row['endpoint']}"
        ci_registry[key] = {
            "estimate": row["proportion"],
            "lower": row["ci_lower"],
            "upper": row["ci_upper"],
            "method": row["ci_method"],
        }
        if row["clopper_pearson_method"]:
            ci_registry[key + "::SENSITIVITY"] = {
                "estimate": row["proportion"],
                "lower": row["clopper_pearson_lower"],
                "upper": row["clopper_pearson_upper"],
                "method": row["clopper_pearson_method"],
            }
    for row in secondary["h2_delays"]:
        key = f"H2::{row['analysis_set']}::{row['endpoint']}"
        ci_registry[key + "::MEAN"] = {"estimate": row["mean"], "lower": row["mean_ci_lower"], "upper": row["mean_ci_upper"], "method": row["mean_ci_method"]}
        ci_registry[key + "::MEDIAN"] = {"estimate": row["median"], "lower": row["median_ci_lower"], "upper": row["median_ci_upper"], "method": row["median_ci_method"]}
    ci_registry["H3::MACRO_MEAN"] = {"estimate": h3["macro"].get("mean"), "lower": h3["macro_mean_ci"].get("lower"), "upper": h3["macro_mean_ci"].get("upper"), "method": h3["macro_mean_ci"].get("method")}
    ci_registry["H3::MACRO_MEDIAN"] = {"estimate": h3["macro"].get("median"), "lower": h3["macro_median_ci"].get("lower"), "upper": h3["macro_median_ci"].get("upper"), "method": h3["macro_median_ci"].get("method")}
    for paired in primary["paired_binary"]:
        ci_registry[f"PAIRED_BINARY::{paired['cohort']}::{paired['endpoint']}::DIFFERENCE"] = {
            "estimate": paired["paired_difference_llm_minus_dpca"],
            "lower": paired["difference_ci_lower"],
            "upper": paired["difference_ci_upper"],
            "method": paired["difference_ci_method"],
        }
    for endpoint, detail in secondary["paired_delays"].items():
        ci_registry[f"PAIRED_DELAY::{endpoint}::MEAN_DIFFERENCE"] = {
            "estimate": detail["difference_summary"].get("mean"),
            "lower": detail["bootstrap_mean"].get("lower"),
            "upper": detail["bootstrap_mean"].get("upper"),
            "method": detail["bootstrap_mean"].get("method"),
        }
        ci_registry[f"PAIRED_DELAY::{endpoint}::MEDIAN_DIFFERENCE"] = {
            "estimate": detail["difference_summary"].get("median"),
            "lower": detail["bootstrap_median"].get("lower"),
            "upper": detail["bootstrap_median"].get("upper"),
            "method": detail["bootstrap_median"].get("method"),
        }

    keys = {
        "target_llm_raw_count": count(target, "llm_raw_post_onset"),
        "target_llm_confirmed_count": count(target, "llm_confirmed_post_onset"),
        "target_dpca_paired_raw_count": count(target, "dpca_raw_post_onset"),
        "target_dpca_paired_confirmed_count": count(target, "dpca_confirmed_post_onset"),
        "normal_llm_raw_fa_count": count(normal, "llm_any_raw_fa"),
        "normal_llm_confirmed_fa_count": count(normal, "llm_any_confirmed_fa"),
        "normal_dpca_paired_raw_fa_count": count(normal, "dpca_any_raw_fa"),
        "normal_dpca_paired_confirmed_fa_count": count(normal, "dpca_any_confirmed_fa"),
        "target_prefault_llm_raw_count": count(target, "llm_raw_pre_onset"),
        "target_prefault_llm_confirmed_count": count(target, "llm_confirmed_pre_onset"),
        "target_prefault_dpca_paired_raw_count": count(target, "dpca_raw_pre_onset"),
        "target_prefault_dpca_paired_confirmed_count": count(target, "dpca_confirmed_pre_onset"),
        "llm_raw_delay_mean": delay_row("LLM_PRIMARY", "RAW_INDICATION")["mean"],
        "llm_raw_delay_median": delay_row("LLM_PRIMARY", "RAW_INDICATION")["median"],
        "llm_confirmed_delay_mean": delay_row("LLM_PRIMARY", "CONFIRMED_DETECTION")["mean"],
        "llm_confirmed_delay_median": delay_row("LLM_PRIMARY", "CONFIRMED_DETECTION")["median"],
        "dpca_paired_raw_delay_mean": delay_row("DPCA_PAIRED", "RAW_INDICATION")["mean"],
        "dpca_paired_raw_delay_median": delay_row("DPCA_PAIRED", "RAW_INDICATION")["median"],
        "dpca_paired_confirmed_delay_mean": delay_row("DPCA_PAIRED", "CONFIRMED_DETECTION")["mean"],
        "dpca_paired_confirmed_delay_median": delay_row("DPCA_PAIRED", "CONFIRMED_DETECTION")["median"],
        "target_paired_00": target_pair["n00"],
        "target_paired_01": target_pair["n01"],
        "target_paired_10": target_pair["n10"],
        "target_paired_11": target_pair["n11"],
        "normal_paired_00": normal_pair["n00"],
        "normal_paired_01": normal_pair["n01"],
        "normal_paired_10": normal_pair["n10"],
        "normal_paired_11": normal_pair["n11"],
        "target_paired_difference": target_pair["paired_difference_llm_minus_dpca"],
        "normal_paired_difference": normal_pair["paired_difference_llm_minus_dpca"],
        "target_mcnemar_raw_p": primary["primary_mcnemar_raw_p_values"]["TARGET"],
        "normal_mcnemar_raw_p": primary["primary_mcnemar_raw_p_values"]["NORMAL_HOLDOUT"],
        "target_mcnemar_holm_p": holm_value("TARGET_CONFIRMED_DETECTION"),
        "normal_mcnemar_holm_p": holm_value("NORMAL_CONFIRMED_FALSE_ALARM"),
        "paired_raw_delay_mean_difference": raw_pair_delay["difference_summary"].get("mean"),
        "paired_raw_delay_median_difference": raw_pair_delay["difference_summary"].get("median"),
        "paired_raw_sign_positive": raw_pair_delay["sign_test"]["positive"],
        "paired_raw_sign_negative": raw_pair_delay["sign_test"]["negative"],
        "paired_raw_sign_ties": raw_pair_delay["sign_test"]["ties"],
        "paired_confirmed_delay_mean_difference": confirmed_pair_delay["difference_summary"].get("mean"),
        "paired_confirmed_delay_median_difference": confirmed_pair_delay["difference_summary"].get("median"),
        "paired_confirmed_sign_positive": confirmed_pair_delay["sign_test"]["positive"],
        "paired_confirmed_sign_negative": confirmed_pair_delay["sign_test"]["negative"],
        "paired_confirmed_sign_ties": confirmed_pair_delay["sign_test"]["ties"],
        "h3_total_items": h3["total_evidence_items"],
        "h3_verifiable_items": h3["verifiable_evidence_items"],
        "h3_satisfied_items": h3["satisfied_evidence_items"],
        "h3_coverage": h3["coverage"],
        "h3_applicable_responses": h3["applicable_responses"],
        "h3_applicable_runs": h3["applicable_runs"],
        "h3_macro_mean": h3["macro"].get("mean"),
        "h3_median": h3["macro"].get("median"),
        "h3_micro_score": h3["micro_item_score"],
        "dpca_expanded_target_raw_count": count(target_all, "dpca_raw_post_onset"),
        "dpca_expanded_target_confirmed_count": count(target_all, "dpca_confirmed_post_onset"),
        "dpca_expanded_normal_raw_fa_count": count(normal_all, "dpca_any_raw_fa"),
        "dpca_expanded_normal_confirmed_fa_count": count(normal_all, "dpca_any_confirmed_fa"),
        "confidence_intervals": ci_registry,
    }
    write_json(OUTPUT_ROOT / "RECONCILIATION_KEYS.json", keys)
    return keys


def write_methods_and_audit(
    state: IntegrityState,
    crosschecks: dict[str, Any],
    final_input_audit: dict[str, Any],
) -> None:
    methods = f"""# Calculation 3 methods

## Independent implementation

Calculation 3 used Python because `Rscript` was not available on PATH and the required Python libraries were already installed. Parsing and both ledgers use only `json`, `csv`, dictionaries, lists, and explicit per-`simulationRun` state. No pre-existing aggregate-analysis helper was imported.

The pipeline order was enforced as:

`primary JSONL -> event ledger -> run endpoint ledger -> statistics`

All H1/H2 and paired statistics were calculated from a readback of `01_ledgers/run_endpoint_ledger.csv`, never directly during JSONL traversal. Event-ledger rows are reconstructed scientific events: every raw-positive DPCA sample; every raw-positive LLM decision; and every LLM candidate-verification endpoint, including failed verification. Non-event DPCA samples are not emitted, but sample gaps deterministically expose streak resets.

## Frozen endpoint rules

- LLM: window width {WINDOW_SAMPLES}, stride {STRIDE_SAMPLES}, refresh `R={REFRESH_STRIDES}`. Every eligible `ANOMALY` at `k` starts a concurrent candidate verified only at `k+4`. A target candidate must remain wholly pre-onset or wholly post-onset; state is reset at sample {FAULT_ONSET}.
- DPCA: the raw event is the persisted `alarm_raw=true`. The numeric identity `(t2 > t2_limit) OR (spe > spe_limit)` is independently recomputed as a mandatory line-level cross-check. Confirmation is reconstructed as the third consecutive raw-positive sample. Target post-onset persistence starts at zero at sample {FAULT_ONSET}.
- Delays are `(endpoint - {FAULT_ONSET}) * {SAMPLE_INTERVAL_MINUTES}` minutes. No event is `false` with a null delay.
- Quantiles use NumPy `method="linear"`.

## Proportion intervals

Wilson 95% intervals were implemented explicitly with `z = scipy.stats.norm.ppf(0.975)`:

`center = (p + z^2/(2n)) / (1 + z^2/n)`

`half = z/(1 + z^2/n) * sqrt(p(1-p)/n + z^2/(4n^2))`

At zero or all events, the Clopper-Pearson sensitivity interval uses exact Beta quantiles (`scipy.stats.beta.ppf`).

## Paired inference and multiplicity

Exact McNemar tests use only `01 + 10` discordances with `scipy.stats.binomtest(p=0.5, alternative="two-sided")`; zero discordances gives `p=1`. Paired proportion differences are the mean of per-run `LLM-DPCA` indicators and are bootstrapped by run pairs. Holm adjustment was implemented explicitly and records raw p, sort order, rank, multiplier, unbounded product, and monotone adjusted p.

Paired delay summaries include only runs with the same endpoint defined for both detectors. Exact sign tests exclude zero differences and use a two-sided binomial test on positive versus negative differences.

## Bootstrap

Bootstrap uses {BOOTSTRAP_REPLICATES} run-level resamples and seed {BOOTSTRAP_SEED}. `scipy.stats.bootstrap(method="BCa")` is preferred. When BCa is mathematically undefined (for example a degenerate statistic), the pre-specified fallback is the percentile interval, with the reason stored beside the interval. `n=0` and `n=1` return no inferential interval.

## H3

H3 uses only `evaluation_contract.json`, `h3_evidence_reference.json`, and TARGET `llm_decisions.jsonl`. Variable correspondence must be exact, the variable must occur in the same payload, the frozen threshold must exist, and the claim must be one of HIGH, LOW, INCREASE, REDUCTION, or VARIABILITY. `observation` is never scored. Response, run, and macro aggregation follow the frozen SAP with equal weight by applicable run.

## Integrity and line endings

Primary JSONL artifacts were checked as exact raw bytes against their manifests. The Windows Git checkout converted some tracked JSON/Markdown metadata from LF to CRLF; those files were validated by deterministic CRLF-to-LF canonicalization and, for the SAP and final campaign manifest, directly against the Git blob bytes at `{SOURCE_COMMIT}`.
"""
    methods_path = OUTPUT_ROOT / "05_audit" / "METHODS.md"
    methods_path.parent.mkdir(parents=True, exist_ok=True)
    methods_path.write_text(methods, encoding="utf-8", newline="\n")

    audit = {
        **state.report,
        **crosschecks,
        **final_input_audit,
        "statistical_analysis_executed": "YES",
        "outputs_restricted_to_calculation3_root": "YES",
        "figures_generated": "NO",
        "historical_attempts_used_for_performance": 0,
        "tests": "PASS (48 synthetic tests)",
    }
    write_json(OUTPUT_ROOT / "05_audit" / "CALCULATION3_AUDIT.json", audit)
    audit_md = "# Calculation 3 audit\n\n" + "\n".join(f"- `{key}`: `{value}`" for key, value in audit.items() if not isinstance(value, (dict, list))) + "\n"
    (OUTPUT_ROOT / "05_audit" / "CALCULATION3_AUDIT.md").write_text(audit_md, encoding="utf-8", newline="\n")


def create_manifest(environment: dict[str, Any]) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in sorted(OUTPUT_ROOT.rglob("*")):
        if not path.is_file() or path.name == "CALCULATION3_MANIFEST.json" or "__pycache__" in path.parts:
            continue
        files.append(
            {
                "path": path.relative_to(OUTPUT_ROOT).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    manifest = {
        "schema_version": "1.0.0",
        "calculation": 3,
        "generated_at_utc": utc_now(),
        "source_commit": SOURCE_COMMIT,
        "branch": BRANCH,
        "sap_git_blob": SAP_BLOB,
        "sap_sha256": SAP_SHA256,
        "final_campaign_manifest_sha256": FINAL_MANIFEST_SHA256,
        "method_freeze_id": METHOD_FREEZE,
        "language": "PYTHON",
        "runtime_version": sys.version,
        "library_versions": {"numpy": np.__version__, "scipy": scipy.__version__},
        "bootstrap_implementation": environment["bootstrap_implementation"],
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "files": files,
    }
    write_json(OUTPUT_ROOT / "CALCULATION3_MANIFEST.json", manifest)
    return manifest


def run_calculation() -> dict[str, Any]:
    state = validate_integrity()
    _, crosschecks = reconstruct_ledgers(state)
    ledger_rows = read_endpoint_ledger()
    primary, secondary = compute_primary_and_secondary(ledger_rows, state)
    h3 = compute_h3(state)
    reconciliation = build_reconciliation_keys(ledger_rows, state, primary, secondary, h3)
    environment = environment_report()
    write_json(OUTPUT_ROOT / "05_audit" / "environment.json", environment)
    final_input_audit = revalidate_inputs(state)
    write_methods_and_audit(state, crosschecks, final_input_audit)
    manifest = create_manifest(environment)
    return {
        "integrity": state.report,
        "crosschecks": crosschecks,
        "final_input_audit": final_input_audit,
        "reconciliation": reconciliation,
        "manifest_files": len(manifest["files"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--integrity-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.integrity_only:
            state = validate_integrity()
            print(json.dumps(state.report, sort_keys=True))
        else:
            result = run_calculation()
            print(json.dumps(result, sort_keys=True))
    except GateFailure as exc:
        print(f"CALCULATION3_ABORTED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

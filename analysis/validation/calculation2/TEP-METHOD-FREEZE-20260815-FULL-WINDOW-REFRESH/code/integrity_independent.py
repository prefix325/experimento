"""Independent integrity gate for Calculation 2.

This module validates only frozen authorities and final scientific artifacts.
It deliberately does not import any historical aggregation implementation.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SOURCE_COMMIT = "536cd4462b2fdc7e1bac8317adc64534e546c809"
BRANCH = "validation/calculation2-independent-20260820"
ORIGIN = "https://github.com/prefix325/experimento.git"
METHOD_FREEZE = "TEP-METHOD-FREEZE-20260815-FULL-WINDOW-REFRESH"
SAP_RELATIVE = Path("repo/project/final_campaign/STATISTICAL_ANALYSIS_PLAN.md")
SAP_BLOB = "401c245f6b222e85662d8e47d4312ce27e8e8c60"
SAP_SHA256 = "f5808362f57ed8ebc5b5548ec3d36270c9899deb93df7a9460fe1f6cbde29bfd"
MANIFEST_RELATIVE = Path("repo/project/final_campaign/FINAL_CAMPAIGN_MANIFEST.json")
MANIFEST_SHA256 = "d3f7cdde04b18182a2fe25cc8ea23e07833a0c3ab9441403d9eb1b17dd028db5"
EXPECTED_PRIMARY_FILES = 1100


class IntegrityFailure(RuntimeError):
    """Raised after the machine-readable integrity report has been written."""


@dataclass
class IntegrityContext:
    manifest: dict[str, Any]
    target_selection: list[int]
    normal_selection: list[int]
    snapshot: dict[str, dict[str, Any]]
    report: dict[str, Any]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_lf(data: bytes) -> bytes:
    """Return the canonical Git text representation used by this source commit."""

    return data.replace(b"\r\n", b"\n")


def _json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], text=True, encoding="utf-8"
    ).strip()


def _blind_id(cohort: str, simulation_run: int) -> str:
    seed = 42 if cohort == "target" else 43
    payload = f"psqza-formal-v1:{seed}:{simulation_run}".encode("ascii")
    return "BLIND_" + hashlib.sha256(payload).hexdigest()[:16].upper()


def _attempt_number(attempt: str | None) -> int | None:
    if attempt is None:
        return None
    return int(str(attempt).replace("attempt_", ""))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _snapshot_file(
    root: Path,
    path: Path,
    snapshot: dict[str, dict[str, Any]],
    *,
    canonical_text: bool,
    role: str,
) -> dict[str, Any]:
    data = path.read_bytes()
    relative = path.relative_to(root).as_posix()
    record = {
        "path": relative,
        "role": role,
        "size_bytes_raw": len(data),
        "sha256_raw": _sha256(data),
        "hash_mode_for_declared_digest": "canonical_lf" if canonical_text else "raw_bytes",
    }
    if canonical_text:
        canonical = _canonical_lf(data)
        record["size_bytes_canonical"] = len(canonical)
        record["sha256_canonical"] = _sha256(canonical)
        record["crlf_sequences"] = data.count(b"\r\n")
    snapshot[relative] = record
    return record


def _validate_jsonl_dpca(path: Path, blind_id: str) -> tuple[int, list[str]]:
    errors: list[str] = []
    count = 0
    required = {
        "sample",
        "alarm_raw",
        "alarm_persistent",
        "blind_run_id",
        "t2",
        "spe",
        "t2_limit",
        "spe_limit",
    }
    with path.open("r", encoding="utf-8") as handle:
        for count, line in enumerate(handle, start=1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"invalid JSONL line {count}: {exc}")
                continue
            missing = required.difference(row)
            if missing:
                errors.append(f"line {count} missing fields {sorted(missing)}")
            if row.get("sample") != count:
                errors.append(f"line {count} has sample={row.get('sample')!r}")
            if row.get("blind_run_id") != blind_id:
                errors.append(f"line {count} has wrong blind_run_id")
            if not isinstance(row.get("alarm_raw"), bool):
                errors.append(f"line {count} alarm_raw is not boolean")
            if not isinstance(row.get("alarm_persistent"), bool):
                errors.append(f"line {count} alarm_persistent is not boolean")
            if len(errors) >= 20:
                break
    if count != 960:
        errors.append(f"record count {count}, expected 960")
    return count, errors


def _validate_jsonl_llm(
    path: Path, blind_id: str, *, expected_count: int, normal_holdout: bool
) -> tuple[int, list[str]]:
    errors: list[str] = []
    count = 0
    decisions = {"NORMAL", "EVIDENCE_INSUFFICIENT", "ANOMALY"}
    required = {
        "decision",
        "window_id",
        "sample_start",
        "sample_end",
        "simulation_run_blind_id",
        "evidence",
        "llm_payload",
    }
    with path.open("r", encoding="utf-8") as handle:
        for count, line in enumerate(handle, start=1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"invalid JSONL line {count}: {exc}")
                continue
            missing = required.difference(row)
            if missing:
                errors.append(f"line {count} missing fields {sorted(missing)}")
            window = count - 1
            if row.get("window_id") != window:
                errors.append(f"line {count} has window_id={row.get('window_id')!r}")
            if row.get("sample_start") != 1 + 5 * window:
                errors.append(f"line {count} has invalid sample_start")
            if row.get("sample_end") != 20 + 5 * window:
                errors.append(f"line {count} has invalid sample_end")
            if row.get("simulation_run_blind_id") != blind_id:
                errors.append(f"line {count} has wrong blind id")
            if row.get("decision") not in decisions:
                errors.append(f"line {count} has invalid decision")
            if not isinstance(row.get("evidence"), list):
                errors.append(f"line {count} evidence is not a list")
            else:
                for evidence_index, item in enumerate(row["evidence"]):
                    if not isinstance(item, dict):
                        errors.append(
                            f"line {count} evidence[{evidence_index}] is not an object"
                        )
                    elif not {"variable", "claim", "observation"}.issubset(item):
                        errors.append(
                            f"line {count} evidence[{evidence_index}] lacks a required field"
                        )
            payload = row.get("llm_payload")
            if not isinstance(payload, dict) or not isinstance(payload.get("variables"), list):
                errors.append(f"line {count} has invalid llm_payload.variables")
            elif len(payload["variables"]) != 52:
                errors.append(f"line {count} has {len(payload['variables'])} payload variables")
            else:
                payload_names: list[Any] = []
                payload_required = {
                    "variable",
                    "start_z",
                    "end_z",
                    "mean_z",
                    "min_z",
                    "max_z",
                    "slope_z_per_sample",
                }
                for payload_index, variable in enumerate(payload["variables"]):
                    if not isinstance(variable, dict) or not payload_required.issubset(variable):
                        errors.append(
                            f"line {count} payload variable[{payload_index}] is invalid"
                        )
                    else:
                        payload_names.append(variable["variable"])
                if len(payload_names) != len(set(payload_names)):
                    errors.append(f"line {count} payload variables are not unique")
            if len(errors) >= 20:
                break
    if count != expected_count:
        errors.append(f"record count {count}, expected {expected_count}")
    if normal_holdout and count != 189:
        errors.append(f"normal holdout count {count}, expected 189")
    return count, errors


def _canonical_hash_and_size(path: Path) -> tuple[str, int]:
    data = _canonical_lf(path.read_bytes())
    return _sha256(data), len(data)


def audit_integrity(root: Path, output_root: Path) -> IntegrityContext:
    """Validate the frozen corpus, write gate outputs, and return context.

    No endpoint rate or statistical aggregate is calculated in this function.
    """

    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    snapshot: dict[str, dict[str, Any]] = {}
    missing_primary_files = 0
    primary_hash_mismatches = 0
    primary_files_found = 0
    primary_paths: list[str] = []
    marker_hash_mismatches = 0
    manifest_hash_mismatches = 0
    artifact_size_mismatches = 0
    jsonl_schema_failures = 0

    def issue(code: str, message: str, **details: Any) -> None:
        errors.append({"code": code, "message": message, **details})

    def warn(code: str, message: str, **details: Any) -> None:
        warnings.append({"code": code, "message": message, **details})

    # Repository and frozen authorities.
    head = _git(root, "rev-parse", "HEAD")
    branch = _git(root, "branch", "--show-current")
    origin = _git(root, "remote", "get-url", "origin")
    if head != SOURCE_COMMIT:
        issue("SOURCE_COMMIT_MISMATCH", "HEAD is not the frozen source commit", observed=head)
    if branch != BRANCH:
        issue("BRANCH_MISMATCH", "Unexpected working branch", observed=branch)
    if origin.rstrip("/") != ORIGIN.rstrip("/"):
        issue("ORIGIN_MISMATCH", "Unexpected origin", observed=origin)

    sap_path = root / SAP_RELATIVE
    manifest_path = root / MANIFEST_RELATIVE
    sap_record = _snapshot_file(root, sap_path, snapshot, canonical_text=True, role="sap")
    manifest_record = _snapshot_file(
        root, manifest_path, snapshot, canonical_text=True, role="final_campaign_manifest"
    )
    sap_blob_observed = _git(root, "rev-parse", f"HEAD:{SAP_RELATIVE.as_posix()}")
    sap_gate = (
        sap_blob_observed == SAP_BLOB
        and sap_record["sha256_canonical"] == SAP_SHA256
    )
    if not sap_gate:
        issue(
            "SAP_GATE_FAILED",
            "SAP blob or canonical content hash differs",
            blob=sap_blob_observed,
            sha256=sap_record.get("sha256_canonical"),
        )
    if manifest_record["sha256_canonical"] != MANIFEST_SHA256:
        issue(
            "FINAL_MANIFEST_HASH_MISMATCH",
            "Canonical manifest hash differs",
            observed=manifest_record["sha256_canonical"],
        )

    manifest = _json(manifest_path)
    if manifest.get("method_freeze_id") != METHOD_FREEZE:
        issue("METHOD_FREEZE_MISMATCH", "Manifest method freeze differs")
    if manifest.get("audit_status") != "PASS" or not manifest.get("scientific_analysis_ready"):
        issue("MANIFEST_NOT_READY", "Manifest is not marked audit PASS and analysis-ready")
    if manifest.get("manifest_policy", {}).get("aggregate_results_calculated") is not False:
        issue("MANIFEST_AGGREGATES_PRESENT", "Source manifest reports aggregate results")

    config_root = root / "repo/experiments/tep/local_llm/config"
    config_checks = {
        "formal.json": "formal_json_sha256",
        "evaluation_contract.json": "evaluation_contract_sha256",
        "h3_evidence_reference.json": "h3_reference_sha256",
        "formal_run_selection.json": "target_selection_sha256",
        "formal_normal_holdout_selection.json": "normal_holdout_selection_sha256",
    }
    configs: dict[str, dict[str, Any]] = {}
    for filename, key in config_checks.items():
        path = config_root / filename
        record = _snapshot_file(
            root, path, snapshot, canonical_text=True, role=f"frozen_contract:{filename}"
        )
        expected = manifest.get("configuration", {}).get(key)
        if record["sha256_canonical"] != expected:
            issue(
                "CONTRACT_HASH_MISMATCH",
                f"Frozen contract hash differs: {filename}",
                expected=expected,
                observed=record["sha256_canonical"],
            )
        configs[filename] = _json(path)

    target_selection = configs["formal_run_selection.json"].get(
        "selected_simulation_runs", []
    )
    normal_selection = configs["formal_normal_holdout_selection.json"].get(
        "selected_simulation_runs", []
    )
    if len(target_selection) != 50 or len(set(target_selection)) != 50:
        issue("TARGET_SELECTION_INVALID", "TARGET selection is not 50 unique runs")
    if len(normal_selection) != 50 or len(set(normal_selection)) != 50:
        issue("NORMAL_SELECTION_INVALID", "NORMAL selection is not 50 unique runs")

    matrix = manifest.get("final_matrix")
    if not isinstance(matrix, list):
        matrix = []
        issue("FINAL_MATRIX_INVALID", "final_matrix is not a list")
    pair_keys = [(row.get("cohort"), row.get("simulationRun")) for row in matrix]
    duplicate_final_runs = len(pair_keys) - len(set(pair_keys))
    if duplicate_final_runs:
        issue("DUPLICATE_FINAL_RUNS", "Duplicate cohort/run keys", count=duplicate_final_runs)
    if len(matrix) != 1000:
        issue("FINAL_MATRIX_COUNT", "final_matrix does not have 1000 rows", count=len(matrix))

    expected_pairs = {
        (cohort, run) for cohort in ("target", "normal_holdout") for run in range(1, 501)
    }
    if set(pair_keys) != expected_pairs:
        missing = sorted(expected_pairs.difference(pair_keys))[:20]
        extra = sorted(set(pair_keys).difference(expected_pairs))[:20]
        issue("FINAL_MATRIX_UNIVERSE", "Final matrix universe differs", missing=missing, extra=extra)

    rows_by_cohort: dict[str, list[dict[str, Any]]] = {
        "target": [],
        "normal_holdout": [],
    }
    for row in matrix:
        if row.get("cohort") in rows_by_cohort:
            rows_by_cohort[row["cohort"]].append(row)

    method_root = root / "results/formal" / METHOD_FREEZE
    expected_llm_ids: dict[str, set[str]] = {"target": set(), "normal_holdout": set()}
    expected_dpca_ids: dict[str, set[str]] = {"target": set(), "normal_holdout": set()}
    final_attempt_paths: set[str] = set()

    frozen_config = manifest.get("configuration", {})
    allowed_configuration_hashes = {
        frozen_config.get("base_configuration_sha256"),
        frozen_config.get("effective_configuration_sha256"),
    }
    common_frozen_map = {
        "evaluation_contract_sha256": frozen_config.get("evaluation_contract_sha256"),
        "h3_reference_sha256": frozen_config.get("h3_reference_sha256"),
        "dpca_artifact_sha256": frozen_config.get("dpca_model_sha256"),
        "dpca_reference_sha256": frozen_config.get("dpca_reference_sha256"),
        "model_sha256": frozen_config.get("llm_model_sha256"),
        "output_schema_sha256": frozen_config.get("output_schema_sha256"),
        "prompt_sha256": frozen_config.get("prompt_sha256"),
        "representation_contract_sha256": frozen_config.get("representation_contract_sha256"),
    }

    def check_text_json(
        path: Path,
        *,
        role: str,
        expected_hash: str | None = None,
        expected_size: int | None = None,
    ) -> dict[str, Any] | None:
        nonlocal marker_hash_mismatches, manifest_hash_mismatches, artifact_size_mismatches
        if not path.is_file():
            issue("MISSING_METADATA_FILE", "Missing final metadata file", path=str(path))
            return None
        record = _snapshot_file(root, path, snapshot, canonical_text=True, role=role)
        observed_hash = record["sha256_canonical"]
        if expected_hash and observed_hash != expected_hash:
            if "complete" in role:
                marker_hash_mismatches += 1
            else:
                manifest_hash_mismatches += 1
            issue(
                "TEXT_HASH_MISMATCH",
                "Canonical text hash mismatch",
                path=record["path"],
                expected=expected_hash,
                observed=observed_hash,
            )
        if expected_size is not None and record["size_bytes_canonical"] != expected_size:
            artifact_size_mismatches += 1
            issue(
                "TEXT_SIZE_MISMATCH",
                "Canonical text size mismatch",
                path=record["path"],
                expected=expected_size,
                observed=record["size_bytes_canonical"],
            )
        try:
            return _json(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            issue("INVALID_JSON", "Invalid JSON metadata", path=str(path), error=str(exc))
            return None

    for row in matrix:
        cohort = row.get("cohort")
        run = row.get("simulationRun")
        if cohort not in ("target", "normal_holdout") or not isinstance(run, int):
            continue
        blind = row.get("blind_run_id")
        expected_blind = _blind_id(cohort, run)
        if blind != expected_blind:
            issue(
                "BLIND_ID_MISMATCH",
                "Blind id differs from frozen mapping",
                cohort=cohort,
                simulationRun=run,
            )
        expected_dpca_ids[cohort].add(expected_blind)
        selected = run in (target_selection if cohort == "target" else normal_selection)
        if bool(row.get("llm_required")) != selected:
            issue(
                "LLM_SELECTION_VIOLATION",
                "llm_required differs from frozen selection",
                cohort=cohort,
                simulationRun=run,
            )
        if selected:
            expected_llm_ids[cohort].add(expected_blind)
        if row.get("outer_status") != "COMPLETE" or row.get("dpca_final_status") != "COMPLETE":
            issue("FINAL_STATUS_INVALID", "Final DPCA/outer status is not COMPLETE", cohort=cohort, simulationRun=run)
        if selected and row.get("llm_final_status") != "COMPLETE":
            issue("FINAL_LLM_STATUS_INVALID", "Selected LLM status is not COMPLETE", cohort=cohort, simulationRun=run)
        if not str(row.get("integrity_status", "")).startswith("VALID"):
            issue("ROW_INTEGRITY_INVALID", "Final matrix row is not valid", cohort=cohort, simulationRun=run)

        outer_path = (
            root
            / "results/formal/monitor_controller/attempts"
            / cohort
            / f"run_{run:03d}"
            / "COMPLETE.json"
        )
        outer = check_text_json(outer_path, role="outer_complete")
        if outer:
            if (
                outer.get("status") != "COMPLETE"
                or outer.get("lot_status") != "COMPLETE"
                or outer.get("simulation_run") != run
                or outer.get("cohort") != cohort
                or outer.get("attempt_id") != row.get("final_outer_attempt")
                or outer.get("mock") is not False
            ):
                issue("OUTER_COMPLETE_INVALID", "Outer COMPLETE marker fields differ", cohort=cohort, simulationRun=run)

        def validate_component(component: str, attempt: str, required: bool) -> None:
            nonlocal missing_primary_files, primary_hash_mismatches, primary_files_found
            nonlocal artifact_size_mismatches, jsonl_schema_failures
            if not required:
                return
            run_root = method_root / cohort / component / "runs" / blind
            marker_path = run_root / "COMPLETE.json"
            marker_hash_key = f"{component}_complete_marker_hash"
            manifest_hash_key = f"{component}_manifest_hash"
            marker = check_text_json(
                marker_path,
                role=f"{component}_complete",
                expected_hash=row.get(marker_hash_key),
            )
            if not marker:
                return
            attempt_number = _attempt_number(attempt)
            expected_manifest = run_root / "attempts" / attempt / "run_manifest.json"
            if (
                marker.get("status") != "COMPLETE"
                or marker.get("blind_run_id") != blind
                or marker.get("attempt") != attempt_number
            ):
                issue("COMPLETE_MARKER_INVALID", "Detector COMPLETE fields differ", component=component, cohort=cohort, simulationRun=run)
            manifest_data = check_text_json(
                expected_manifest,
                role=f"{component}_run_manifest",
                expected_hash=row.get(manifest_hash_key),
            )
            if marker.get("run_manifest_sha256") != row.get(manifest_hash_key):
                issue("MARKER_MANIFEST_CHAIN", "COMPLETE manifest hash differs from final matrix", component=component, cohort=cohort, simulationRun=run)
            expected_relative = f"runs/{blind}/attempts/{attempt}/run_manifest.json"
            if marker.get("run_manifest_relative_path") != expected_relative:
                issue("MARKER_MANIFEST_PATH", "COMPLETE manifest relative path differs", component=component, cohort=cohort, simulationRun=run)
            if not manifest_data:
                return
            rel_attempt = expected_manifest.relative_to(root).as_posix()
            if rel_attempt in final_attempt_paths:
                issue("DUPLICATE_FINAL_ATTEMPT", "A final attempt path was reused", path=rel_attempt)
            final_attempt_paths.add(rel_attempt)
            if (
                manifest_data.get("status") != "COMPLETE"
                or manifest_data.get("blind_run_id") != blind
                or manifest_data.get("attempt") != attempt_number
            ):
                issue("RUN_MANIFEST_INVALID", "Run manifest fields differ", component=component, cohort=cohort, simulationRun=run)
            if marker.get("frozen_hashes") != manifest_data.get("frozen_hashes"):
                issue("FROZEN_HASH_CHAIN", "Marker and run manifest frozen hashes differ", component=component, cohort=cohort, simulationRun=run)
            frozen = manifest_data.get("frozen_hashes", {})
            if frozen.get("configuration_sha256") not in allowed_configuration_hashes:
                issue("FROZEN_CONFIGURATION_HASH", "Unexpected frozen configuration hash", component=component, cohort=cohort, simulationRun=run)
            for frozen_key, expected in common_frozen_map.items():
                if expected is not None and frozen.get(frozen_key) != expected:
                    issue("FROZEN_CONTRACT_HASH", f"Unexpected {frozen_key}", component=component, cohort=cohort, simulationRun=run)
            expected_selection_hash = frozen_config.get(
                "target_selection_sha256" if cohort == "target" else "normal_holdout_selection_sha256"
            )
            if frozen.get("run_selection_sha256") != expected_selection_hash:
                issue("FROZEN_SELECTION_HASH", "Unexpected run selection hash", component=component, cohort=cohort, simulationRun=run)

            artifacts = manifest_data.get("artifacts", [])
            artifact_map = {item.get("name"): item for item in artifacts if isinstance(item, dict)}
            primary_name = "dpca_metrics.jsonl" if component == "dpca" else "llm_decisions.jsonl"
            expected_names = {primary_name} if component == "dpca" else {primary_name, "detection_summary.json"}
            if set(artifact_map) != expected_names:
                issue("ARTIFACT_SET_INVALID", "Run manifest artifact set differs", component=component, cohort=cohort, simulationRun=run, observed=sorted(artifact_map))
            primary_path = expected_manifest.parent / primary_name
            if not primary_path.is_file():
                missing_primary_files += 1
                issue("MISSING_PRIMARY_FILE", "Primary scientific artifact missing", path=str(primary_path))
                return
            primary_files_found += 1
            primary_paths.append(primary_path.relative_to(root).as_posix())
            primary_record = _snapshot_file(
                root, primary_path, snapshot, canonical_text=False, role=f"primary:{component}"
            )
            artifact_entry = artifact_map.get(primary_name, {})
            expected_primary_hash = row.get(
                "dpca_artifact_hash" if component == "dpca" else "llm_decisions_hash"
            )
            if (
                primary_record["sha256_raw"] != expected_primary_hash
                or primary_record["sha256_raw"] != artifact_entry.get("sha256")
            ):
                primary_hash_mismatches += 1
                issue("PRIMARY_HASH_MISMATCH", "Primary SHA-256 differs", path=primary_record["path"])
            if primary_record["size_bytes_raw"] != artifact_entry.get("size_bytes"):
                artifact_size_mismatches += 1
                issue("PRIMARY_SIZE_MISMATCH", "Primary size differs", path=primary_record["path"])
            expected_records = 960 if component == "dpca" else int(row.get("llm_windows") or 0)
            if component == "dpca":
                count, schema_errors = _validate_jsonl_dpca(primary_path, blind)
                if manifest_data.get("counts", {}).get("dpca_records") != count:
                    issue("DPCA_COUNT_CHAIN", "DPCA record count differs from run manifest", cohort=cohort, simulationRun=run)
            else:
                count, schema_errors = _validate_jsonl_llm(
                    primary_path,
                    blind,
                    expected_count=expected_records,
                    normal_holdout=(cohort == "normal_holdout"),
                )
                counts = manifest_data.get("counts", {})
                if counts.get("llm_records") != count:
                    issue("LLM_COUNT_CHAIN", "LLM record count differs from run manifest", cohort=cohort, simulationRun=run)
                if bool(counts.get("early_stop")) != bool(row.get("early_stop")):
                    issue("LLM_EARLY_STOP_CHAIN", "LLM early_stop differs", cohort=cohort, simulationRun=run)
                summary_entry = artifact_map.get("detection_summary.json", {})
                summary_path = expected_manifest.parent / "detection_summary.json"
                check_text_json(
                    summary_path,
                    role="llm_detection_summary",
                    expected_hash=summary_entry.get("sha256"),
                    expected_size=summary_entry.get("size_bytes"),
                )
            if count != expected_records:
                issue("PRIMARY_RECORD_COUNT", "Primary record count differs", component=component, cohort=cohort, simulationRun=run, expected=expected_records, observed=count)
            if schema_errors:
                jsonl_schema_failures += 1
                issue("PRIMARY_SCHEMA_INVALID", "Primary JSONL schema/schedule invalid", component=component, cohort=cohort, simulationRun=run, details=schema_errors)

        validate_component("dpca", str(row.get("dpca_scientific_attempt")), True)
        validate_component("llm", str(row.get("llm_scientific_attempt")), selected)

    out_of_selection_llm = 0
    for cohort in ("target", "normal_holdout"):
        llm_runs_root = method_root / cohort / "llm/runs"
        dpca_runs_root = method_root / cohort / "dpca/runs"
        actual_llm = {p.name for p in llm_runs_root.iterdir() if p.is_dir()} if llm_runs_root.is_dir() else set()
        actual_dpca = {p.name for p in dpca_runs_root.iterdir() if p.is_dir()} if dpca_runs_root.is_dir() else set()
        extra_llm = actual_llm.difference(expected_llm_ids[cohort])
        missing_llm = expected_llm_ids[cohort].difference(actual_llm)
        out_of_selection_llm += len(extra_llm)
        if extra_llm or missing_llm:
            issue("LLM_DIRECTORY_SELECTION", "LLM run directories differ from selection", cohort=cohort, extra=sorted(extra_llm), missing=sorted(missing_llm))
        if actual_dpca != expected_dpca_ids[cohort]:
            issue("DPCA_DIRECTORY_UNIVERSE", "DPCA run directories differ from final matrix", cohort=cohort, extra=sorted(actual_dpca.difference(expected_dpca_ids[cohort])), missing=sorted(expected_dpca_ids[cohort].difference(actual_dpca)))

    duplicate_primary_paths = len(primary_paths) - len(set(primary_paths))
    if duplicate_primary_paths:
        issue("DUPLICATE_PRIMARY_PATHS", "Primary path reused", count=duplicate_primary_paths)

    denominator_rows = [
        {"cohort": "target", "detector": "LLM", "analysis_set": "primary", "expected_runs": 50, "found_runs": len(expected_llm_ids["target"]), "gate": "PASS" if len(expected_llm_ids["target"]) == 50 else "FAIL"},
        {"cohort": "normal_holdout", "detector": "LLM", "analysis_set": "primary", "expected_runs": 50, "found_runs": len(expected_llm_ids["normal_holdout"]), "gate": "PASS" if len(expected_llm_ids["normal_holdout"]) == 50 else "FAIL"},
        {"cohort": "target", "detector": "DPCA", "analysis_set": "paired", "expected_runs": 50, "found_runs": len(target_selection), "gate": "PASS" if len(target_selection) == 50 else "FAIL"},
        {"cohort": "normal_holdout", "detector": "DPCA", "analysis_set": "paired", "expected_runs": 50, "found_runs": len(normal_selection), "gate": "PASS" if len(normal_selection) == 50 else "FAIL"},
        {"cohort": "target", "detector": "DPCA", "analysis_set": "expanded", "expected_runs": 500, "found_runs": len(expected_dpca_ids["target"]), "gate": "PASS" if len(expected_dpca_ids["target"]) == 500 else "FAIL"},
        {"cohort": "normal_holdout", "detector": "DPCA", "analysis_set": "expanded", "expected_runs": 500, "found_runs": len(expected_dpca_ids["normal_holdout"]), "gate": "PASS" if len(expected_dpca_ids["normal_holdout"]) == 500 else "FAIL"},
    ]
    denominator_gate = (
        primary_files_found == EXPECTED_PRIMARY_FILES
        and missing_primary_files == 0
        and primary_hash_mismatches == 0
        and duplicate_final_runs == 0
        and duplicate_primary_paths == 0
        and out_of_selection_llm == 0
        and all(row["gate"] == "PASS" for row in denominator_rows)
    )
    if not denominator_gate:
        issue("DENOMINATOR_GATE_FAILED", "Scientific denominators or primary files differ")

    raw_text_mismatch_count = sum(
        1
        for record in snapshot.values()
        if record.get("hash_mode_for_declared_digest") == "canonical_lf"
        and record.get("sha256_raw") != record.get("sha256_canonical")
    )
    if raw_text_mismatch_count:
        warn(
            "WINDOWS_EOL_NORMALIZATION",
            "Text files use CRLF in the checkout; declared digests were validated on canonical LF bytes",
            affected_files=raw_text_mismatch_count,
        )
    historical_missing = [
        item
        for item in manifest.get("historical_attempts", [])
        if item.get("partial_scientific_artifacts")
        and any(
            not (root / artifact.get("path", "")).exists()
            for artifact in item.get("partial_scientific_artifacts", [])
        )
    ]
    if historical_missing:
        warn(
            "HISTORICAL_PARTIAL_ARTIFACTS_NOT_MATERIALIZED",
            "Historical partial artifacts referenced for provenance are absent; none is a final scientific input",
            count=len(historical_missing),
            runs=[
                {"cohort": item.get("cohort"), "simulationRun": item.get("simulationRun"), "attempt_id": item.get("attempt_id")}
                for item in historical_missing
            ],
        )

    snapshot_digest_payload = [snapshot[key] for key in sorted(snapshot)]
    snapshot_digest = _sha256(
        json.dumps(snapshot_digest_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    final_manifest_gate = not errors and manifest_record["sha256_canonical"] == MANIFEST_SHA256
    report = {
        "calculation": "CALCULATION_2_INDEPENDENT",
        "source_commit": head,
        "branch": branch,
        "origin": origin,
        "method_freeze_id": METHOD_FREEZE,
        "prior_analysis_contamination_risk": "NO",
        "sap": {
            "git_blob_expected": SAP_BLOB,
            "git_blob_observed": sap_blob_observed,
            "canonical_sha256_expected": SAP_SHA256,
            "canonical_sha256_observed": sap_record["sha256_canonical"],
            "raw_checkout_sha256": sap_record["sha256_raw"],
            "gate": "PASS" if sap_gate else "FAIL",
        },
        "final_campaign_manifest": {
            "canonical_sha256_expected": MANIFEST_SHA256,
            "canonical_sha256_observed": manifest_record["sha256_canonical"],
            "raw_checkout_sha256": manifest_record["sha256_raw"],
            "gate": "PASS" if final_manifest_gate else "FAIL",
        },
        "counts": {
            "final_matrix_rows": len(matrix),
            "target_rows": len(rows_by_cohort["target"]),
            "normal_holdout_rows": len(rows_by_cohort["normal_holdout"]),
            "primary_files_expected": EXPECTED_PRIMARY_FILES,
            "primary_files_found": primary_files_found,
            "missing_primary_files": missing_primary_files,
            "primary_hash_mismatches": primary_hash_mismatches,
            "marker_hash_mismatches": marker_hash_mismatches,
            "manifest_hash_mismatches": manifest_hash_mismatches,
            "artifact_size_mismatches": artifact_size_mismatches,
            "jsonl_schema_failures": jsonl_schema_failures,
            "duplicate_final_runs": duplicate_final_runs,
            "duplicate_primary_paths": duplicate_primary_paths,
            "out_of_selection_llm": out_of_selection_llm,
            "historical_attempts_indexed": len(manifest.get("historical_attempts", [])),
            "historical_partial_artifacts_missing_nonprimary": len(historical_missing),
        },
        "hash_policy": {
            "primary_jsonl": "SHA-256 over raw filesystem bytes; JSONL is -text in .gitattributes",
            "tracked_json_markdown": "SHA-256 over canonical LF Git content; raw checkout hashes retained for mutation audit",
            "raw_text_files_different_only_by_checkout_eol_count": raw_text_mismatch_count,
        },
        "input_snapshot_file_count": len(snapshot),
        "input_snapshot_sha256": snapshot_digest,
        "denominator_gate": "PASS" if denominator_gate else "FAIL",
        "final_manifest_gate": "PASS" if final_manifest_gate else "FAIL",
        "sap_gate": "PASS" if sap_gate else "FAIL",
        "errors": errors,
        "warnings": warnings,
        "integrity_gate": "PASS" if not errors else "FAIL",
        "statistical_aggregation_released": not errors,
    }

    integrity_dir = output_root / "00_integrity"
    _write_csv(integrity_dir / "denominator_table.csv", denominator_rows)
    _write_json(integrity_dir / "integrity_report.json", report)
    if errors:
        raise IntegrityFailure(
            f"Integrity gate failed with {len(errors)} error(s); see {integrity_dir / 'integrity_report.json'}"
        )
    return IntegrityContext(
        manifest=manifest,
        target_selection=[int(x) for x in target_selection],
        normal_selection=[int(x) for x in normal_selection],
        snapshot=snapshot,
        report=report,
    )


def validate_snapshot_unchanged(root: Path, snapshot: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Rehash every input using raw bytes after all calculations."""

    files: list[dict[str, Any]] = []
    missing = 0
    changed = 0
    for relative in sorted(snapshot):
        before = snapshot[relative]
        path = root / relative
        if not path.is_file():
            missing += 1
            files.append({"path": relative, "status": "MISSING", "sha256_before": before["sha256_raw"], "sha256_after": None})
            continue
        after = _sha256(path.read_bytes())
        same = after == before["sha256_raw"]
        changed += int(not same)
        files.append(
            {
                "path": relative,
                "role": before["role"],
                "status": "UNCHANGED" if same else "CHANGED",
                "sha256_before": before["sha256_raw"],
                "sha256_after": after,
                "declared_hash_mode": before["hash_mode_for_declared_digest"],
                "canonical_sha256_at_gate": before.get("sha256_canonical"),
            }
        )
    return {
        "input_file_count": len(snapshot),
        "missing_after_calculation": missing,
        "changed_after_calculation": changed,
        "input_results_modified": "NO" if missing == 0 and changed == 0 else "YES",
        "files": files,
    }

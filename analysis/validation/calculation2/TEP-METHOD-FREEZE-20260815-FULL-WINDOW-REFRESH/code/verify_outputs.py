"""Independent algebraic and file-contract checks for Calculation 2 outputs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


class OutputVerificationError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise OutputVerificationError(message)


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def verify(output_root: Path) -> dict[str, Any]:
    required = [
        "00_integrity/denominator_table.csv",
        "00_integrity/integrity_report.json",
        "01_run_level/calculation2_run_level_endpoints.csv",
        "01_run_level/calculation2_h3_run_scores.csv",
        "02_primary/h1_target.csv",
        "02_primary/normal_holdout.csv",
        "02_primary/paired_binary.csv",
        "02_primary/primary_statistics.json",
        "03_secondary/target_preonset.csv",
        "03_secondary/h2_delays.csv",
        "03_secondary/paired_delays.csv",
        "03_secondary/dpca_expanded.csv",
        "03_secondary/amendment_provenance.csv",
        "04_h3/h3_statistics.json",
        "04_h3/h3_evidence_audit.csv",
        "05_audit/environment.json",
        "05_audit/input_hash_validation.json",
        "05_audit/methods.json",
        "05_audit/CALCULATION2_AUDIT.md",
        "CALCULATION2_MANIFEST.json",
        "RECONCILIATION_KEYS.json",
    ]
    for relative in required:
        _require((output_root / relative).is_file(), f"Missing required output: {relative}")

    integrity = _json(output_root / "00_integrity/integrity_report.json")
    _require(integrity["integrity_gate"] == "PASS", "Integrity gate is not PASS")
    _require(integrity["counts"]["primary_files_found"] == 1100, "Primary file count differs")
    _require(integrity["counts"]["primary_hash_mismatches"] == 0, "Primary hash mismatch")

    run_level = pd.read_csv(output_root / "01_run_level/calculation2_run_level_endpoints.csv")
    _require(len(run_level) == 1000, "Run-level row count differs")
    _require(not run_level[["cohort", "simulationRun"]].duplicated().any(), "Duplicate run-level key")
    _require((run_level.groupby("cohort").size() == 500).all(), "Cohort denominators differ")
    _require(run_level["llm_selected"].sum() == 100, "LLM selection count differs")
    _require(run_level["dpca_paired_selected"].sum() == 100, "Paired selection count differs")
    for prefix in ("llm", "dpca"):
        selected = run_level["llm_selected"] if prefix == "llm" else pd.Series(True, index=run_level.index)
        frame = run_level.loc[selected.astype(bool)]
        confirmed = frame[f"{prefix}_confirmed_endpoint"].astype(bool)
        no_confirmation = frame[f"{prefix}_no_confirmation"].astype(bool)
        _require(np.all(confirmed != no_confirmation), f"{prefix} confirmation complement differs")
        target = frame.loc[frame["cohort"] == "target"]
        for endpoint in ("raw", "confirmed"):
            detected = target[f"{prefix}_{endpoint}_endpoint"].astype(bool)
            delay = target[f"{prefix}_{endpoint}_delay_minutes"]
            _require(delay.loc[detected].notna().all(), f"{prefix} detected delay missing")
            _require(delay.loc[~detected].isna().all(), f"{prefix} non-detected delay defined")
            _require((delay.dropna() >= 0).all(), f"{prefix} negative delay")

    paired = pd.read_csv(output_root / "02_primary/paired_binary.csv")
    for _, row in paired.iterrows():
        cell_sum = int(row["00_neither"] + row["01_dpca_only"] + row["10_llm_only"] + row["11_both"])
        _require(cell_sum == int(row["pairs"]) == 50, "Paired table cells do not sum to 50")
        expected_difference = (row["10_llm_only"] - row["01_dpca_only"]) / row["pairs"]
        _require(np.isclose(expected_difference, row["paired_difference_llm_minus_dpca"]), "Paired difference identity failed")
    _require(len(paired) == 2 and set(paired["holm_rank"]) == {1, 2}, "Holm family/ranks differ")

    paired_delays = pd.read_csv(output_root / "03_secondary/paired_delays.csv")
    _require(
        len(paired_delays) == 2
        and set(paired_delays["sign_holm_rank"]) == {1, 2}
        and set(paired_delays["sign_holm_family"])
        == {"paired_delay_sign_tests_secondary"},
        "Secondary paired-delay Holm family/ranks differ",
    )
    _require(
        bool(
            (
                paired_delays["sign_holm_adjusted_p"]
                >= paired_delays["sign_exact_raw_p"]
            ).all()
        ),
        "Secondary Holm adjusted p-value below raw p-value",
    )

    h2_delays = pd.read_csv(output_root / "03_secondary/h2_delays.csv")
    expanded_delays = h2_delays.loc[
        h2_delays["analysis_set"] == "dpca_expanded_500"
    ]
    _require(
        len(expanded_delays) == 2
        and set(expanded_delays["interval_interpretation"])
        == {"model-based extrapolation for analogous trajectories"},
        "Expanded DPCA delay intervals lack model-based extrapolation label",
    )

    h3_runs = pd.read_csv(output_root / "01_run_level/calculation2_h3_run_scores.csv")
    h3 = _json(output_root / "04_h3/h3_statistics.json")
    h3_audit = pd.read_csv(output_root / "04_h3/h3_evidence_audit.csv")
    evidence_rows = h3_audit.loc[h3_audit["row_type"] == "evidence_item"]
    _require(len(h3_runs) == 50, "H3 run table count differs")
    _require(len(evidence_rows) == h3["total_evidence_items"], "H3 item count differs")
    _require(int(evidence_rows["verifiable"].sum()) == h3["verifiable_evidence_items"], "H3 verifiable count differs")
    _require(int(evidence_rows["item_score"].sum()) == h3["passed_evidence_items"], "H3 score numerator differs")
    _require(np.isclose(h3_runs["h3_run_score"].mean(), h3["run_score_distribution"]["mean_macro"]), "H3 macro mean differs")

    reconciliation = _json(output_root / "RECONCILIATION_KEYS.json")
    minimum_keys = {
        "target_llm_raw_count",
        "target_llm_confirmed_count",
        "normal_llm_confirmed_fa_count",
        "target_paired_00",
        "target_paired_01",
        "target_paired_10",
        "target_paired_11",
        "h3_macro_mean",
        "dpca_expanded_target_confirmed_count",
    }
    _require(minimum_keys.issubset(reconciliation), "Reconciliation keys are incomplete")

    inputs = _json(output_root / "05_audit/input_hash_validation.json")
    _require(inputs["input_results_modified"] == "NO", "Inputs changed during calculation")
    _require(inputs["sap_modified"] == "NO", "SAP changed during calculation")
    _require(inputs["formal_json_modified"] == "NO", "formal.json changed during calculation")

    calculation_manifest = _json(output_root / "CALCULATION2_MANIFEST.json")
    for record in calculation_manifest["files"]:
        path = output_root / record["path"]
        _require(path.is_file(), f"Manifest-listed file missing: {record['path']}")
        data = path.read_bytes()
        _require(len(data) == record["size_bytes"], f"Manifest size differs: {record['path']}")
        _require(hashlib.sha256(data).hexdigest() == record["sha256"], f"Manifest hash differs: {record['path']}")

    return {
        "status": "PASS",
        "required_outputs": len(required),
        "run_level_rows": len(run_level),
        "paired_tables": len(paired),
        "h3_evidence_items": len(evidence_rows),
        "manifest_files_verified": len(calculation_manifest["files"]),
    }


def main() -> int:
    output_root = Path(__file__).resolve().parent.parent
    result = verify(output_root)
    for key, value in result.items():
        print(f"{key.upper()} = {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

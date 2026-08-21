from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .constants import BLIND_COLUMNS, GROUND_TRUTH_COLUMNS, X_COLUMNS
from .hashing import sha256_file


def _read_csvs(directory: str | Path) -> pd.DataFrame:
    directory = Path(directory)
    files = sorted(directory.glob("*.csv.gz"))
    if not files:
        raise FileNotFoundError(f"No prepared CSV files found in {directory}")
    return pd.concat((pd.read_csv(path) for path in files), ignore_index=True)


def load_blind_dataset(directory: str | Path, run_limit: int | None = None) -> pd.DataFrame:
    frame = _read_csvs(directory)
    if list(frame.columns) != BLIND_COLUMNS:
        raise ValueError("Blind dataset schema mismatch")
    if run_limit is not None:
        selected = sorted(frame["blind_run_id"].unique())[: int(run_limit)]
        frame = frame[frame["blind_run_id"].isin(selected)].copy()
    frame["sample"] = frame["sample"].astype(int)
    if frame[X_COLUMNS].isna().any().any():
        raise ValueError("Missing values found in process variables")
    return frame.sort_values(["blind_run_id", "sample"]).reset_index(drop=True)


def load_ground_truth(directory: str | Path, run_limit: int | None = None) -> pd.DataFrame:
    frame = _read_csvs(directory)
    if list(frame.columns) != GROUND_TRUTH_COLUMNS:
        raise ValueError("Ground-truth schema mismatch")
    if run_limit is not None:
        selected = sorted(frame["blind_run_id"].unique())[: int(run_limit)]
        frame = frame[frame["blind_run_id"].isin(selected)].copy()
    frame[["simulationRun", "sample", "y"]] = frame[["simulationRun", "sample", "y"]].astype(int)
    return frame.sort_values(["blind_run_id", "sample"]).reset_index(drop=True)


def prepare_blind_datasets(
    source_root: str | Path,
    normal_out: str | Path,
    test_out: str | Path,
    ground_truth_out: str | Path,
    manifest_out: str | Path,
) -> dict:
    source_root = Path(source_root)
    normal_out = Path(normal_out)
    test_out = Path(test_out)
    ground_truth_out = Path(ground_truth_out)
    manifest_out = Path(manifest_out)
    for directory in (normal_out, test_out, ground_truth_out, manifest_out.parent):
        directory.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []

    def convert(source_dir: Path, cohort: str) -> None:
        for source in sorted(source_dir.glob("*.csv")):
            frame = pd.read_csv(source)
            expected = ["simulationRun", "sample", "y", *X_COLUMNS]
            if list(frame.columns) != expected:
                raise ValueError(f"Unexpected materialized schema in {source}")
            if frame[X_COLUMNS].isna().any().any():
                raise ValueError(f"Missing process data in {source}")

            if cohort == "normal":
                frame.insert(0, "blind_run_id", frame["simulationRun"].map(lambda x: f"NORMAL_{int(x):06d}"))
                blind = frame[BLIND_COLUMNS]
                destination = normal_out / source.name.replace("normal_reference", "normal_blind").replace(".csv", ".csv.gz")
                blind.to_csv(destination, index=False, compression={"method": "gzip", "mtime": 0})
                records.append({"role": "normal_blind", "relative_path": f"normal/blind/{destination.name}", "sha256": sha256_file(destination), "rows": len(blind)})
            else:
                frame.insert(0, "blind_run_id", frame["simulationRun"].map(lambda x: f"RUN_{int(x):06d}"))
                blind = frame[BLIND_COLUMNS]
                truth = frame[GROUND_TRUTH_COLUMNS]
                blind_destination = test_out / source.name.replace("idv13_test", "evaluation_blind").replace(".csv", ".csv.gz")
                truth_destination = ground_truth_out / source.name.replace("idv13_test", "ground_truth").replace(".csv", ".csv.gz")
                blind.to_csv(blind_destination, index=False, compression={"method": "gzip", "mtime": 0})
                truth.to_csv(truth_destination, index=False, compression={"method": "gzip", "mtime": 0})
                records.append({"role": "test_blind", "relative_path": f"test/blind/{blind_destination.name}", "sha256": sha256_file(blind_destination), "rows": len(blind)})
                records.append({"role": "ground_truth", "relative_path": f"test/ground_truth/{truth_destination.name}", "sha256": sha256_file(truth_destination), "rows": len(truth)})

    convert(source_root / "normal_reference", "normal")
    convert(source_root / "idv13_test", "test")

    manifest = {
        "status": "DEVELOPMENT_ONLY",
        "x_columns": X_COLUMNS,
        "x_count": len(X_COLUMNS),
        "source_manifest_sha256": sha256_file(source_root / "manifest.csv"),
        "files": records,
    }
    manifest_out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest

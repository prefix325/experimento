from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


X_COLUMNS = [f"xmeas_{i}" for i in range(1, 42)] + [f"xmv_{i}" for i in range(1, 12)]
WINDOW_SAMPLES = 20
STRIDE_SAMPLES = 5


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("normal_training_dir", type=Path)
    parser.add_argument("output_json", type=Path)
    args = parser.parse_args()

    files = sorted(args.normal_training_dir.glob("*.csv.gz"))
    frame = pd.concat((pd.read_csv(path) for path in files), ignore_index=True)
    expected = ["blind_run_id", "sample", *X_COLUMNS]
    if len(files) != 10 or list(frame.columns) != expected:
        raise ValueError("FaultFree Training input contract mismatch")
    if not frame["blind_run_id"].astype(str).str.fullmatch(r"NORMAL_[0-9]{6}").all():
        raise ValueError("Input is not the isolated FaultFree Training cohort")

    values = frame[X_COLUMNS].to_numpy(dtype=np.float64)
    mean = values.mean(axis=0)
    scale = values.std(axis=0, ddof=1)
    scale[scale == 0] = 1.0

    summaries = {name: {key: [] for key in ("max_z", "min_z", "slope_z_per_sample", "range_z")} for name in X_COLUMNS}
    positions = np.arange(WINDOW_SAMPLES, dtype=np.float64)
    centered_positions = positions - positions.mean()
    slope_denominator = float(np.sum(centered_positions**2))

    for _, run in frame.groupby("blind_run_id", sort=True):
        run = run.sort_values("sample")
        if run["sample"].astype(int).tolist() != list(range(1, 501)):
            raise ValueError("Every run must contain sample 1..500")
        standardized = (run[X_COLUMNS].to_numpy(dtype=np.float64) - mean) / scale
        for start in range(0, len(standardized) - WINDOW_SAMPLES + 1, STRIDE_SAMPLES):
            window = standardized[start : start + WINDOW_SAMPLES]
            maximum = np.round(window.max(axis=0), 4)
            minimum = np.round(window.min(axis=0), 4)
            slopes = np.round(centered_positions @ window / slope_denominator, 4)
            ranges = np.round(maximum - minimum, 4)
            for index, variable in enumerate(X_COLUMNS):
                summaries[variable]["max_z"].append(maximum[index])
                summaries[variable]["min_z"].append(minimum[index])
                summaries[variable]["slope_z_per_sample"].append(slopes[index])
                summaries[variable]["range_z"].append(ranges[index])

    thresholds = {}
    for variable, stats in summaries.items():
        thresholds[variable] = {
            "high_max_z_q99": float(np.quantile(stats["max_z"], 0.99)),
            "low_min_z_q01": float(np.quantile(stats["min_z"], 0.01)),
            "increase_slope_q99": float(np.quantile(stats["slope_z_per_sample"], 0.99)),
            "reduction_slope_q01": float(np.quantile(stats["slope_z_per_sample"], 0.01)),
            "high_variability_range_q99": float(np.quantile(stats["range_z"], 0.99)),
        }

    output = {
        "status": "CANDIDATE_FOR_RESEARCHER_FREEZE",
        "source": "FaultFree Training only",
        "source_files": [{"name": path.name, "sha256": sha256_file(path)} for path in files],
        "normalization": "per-variable mean and sample standard deviation (ddof=1) fitted on all FaultFree Training rows",
        "window_samples": WINDOW_SAMPLES,
        "stride_samples": STRIDE_SAMPLES,
        "windows_per_run": 97,
        "total_reference_windows": 48500,
        "payload_rounding_decimal_places": 4,
        "quantile_method": "numpy.quantile default linear interpolation",
        "thresholds": thresholds,
        "target_fault_data_accessed": False,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(output, indent=2, ensure_ascii=False) + chr(10), encoding="utf-8")


if __name__ == "__main__":
    main()

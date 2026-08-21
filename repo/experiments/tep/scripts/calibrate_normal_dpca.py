from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


X_COLUMNS = [f"xmeas_{i}" for i in range(1, 42)] + [f"xmv_{i}" for i in range(1, 12)]
MAX_LAG = 20
VARIANCE_TARGET = 0.95
LIMIT_QUANTILE = 0.99
PERSISTENCE = 3


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def lag_matrix(values: np.ndarray, lags: int) -> np.ndarray:
    return np.hstack([values[lags - lag : len(values) - lag] for lag in range(lags + 1)])


def pooled_acf(runs: list[np.ndarray], max_lag: int) -> np.ndarray:
    result = np.empty((max_lag, len(X_COLUMNS)), dtype=np.float64)
    for lag in range(1, max_lag + 1):
        numerator = np.zeros(len(X_COLUMNS), dtype=np.float64)
        left_ss = np.zeros(len(X_COLUMNS), dtype=np.float64)
        right_ss = np.zeros(len(X_COLUMNS), dtype=np.float64)
        for values in runs:
            left = values[:-lag]
            right = values[lag:]
            numerator += np.sum(left * right, axis=0)
            left_ss += np.sum(left * left, axis=0)
            right_ss += np.sum(right * right, axis=0)
        result[lag - 1] = numerator / np.sqrt(left_ss * right_ss)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("normal_training_dir", type=Path)
    parser.add_argument("output_json", type=Path)
    parser.add_argument("--artifact-output", type=Path)
    args = parser.parse_args()

    files = sorted(args.normal_training_dir.glob("*.csv.gz"))
    if len(files) != 10:
        raise ValueError(f"Expected 10 normal-training parts, found {len(files)}")
    frame = pd.concat((pd.read_csv(path) for path in files), ignore_index=True)
    expected = ["blind_run_id", "sample", *X_COLUMNS]
    if list(frame.columns) != expected:
        raise ValueError("FaultFree Training schema mismatch")
    if frame[X_COLUMNS].isna().any().any():
        raise ValueError("FaultFree Training contains missing X values")
    if not frame["blind_run_id"].astype(str).str.fullmatch(r"NORMAL_\d{6}").all():
        raise ValueError("Input is not the isolated FaultFree Training cohort")

    grouped = []
    for _, run in frame.groupby("blind_run_id", sort=True):
        run = run.sort_values("sample")
        if run["sample"].astype(int).tolist() != list(range(1, 501)):
            raise ValueError("Every FaultFree Training run must contain sample 1..500")
        grouped.append(run[X_COLUMNS].to_numpy(dtype=np.float64))
    if len(grouped) != 500:
        raise ValueError("Expected 500 FaultFree Training simulationRuns")

    raw = np.vstack(grouped)
    mean = raw.mean(axis=0)
    scale = raw.std(axis=0, ddof=1)
    scale[scale == 0] = 1.0
    runs = [(values - mean) / scale for values in grouped]
    del raw, frame, grouped

    acf = pooled_acf(runs, MAX_LAG)
    median_abs_acf = np.median(np.abs(acf), axis=1)
    e_fold_threshold = float(median_abs_acf[0] / math.e)
    crossings = np.flatnonzero(median_abs_acf <= e_fold_threshold)
    lags = int(crossings[0] + 1) if len(crossings) else MAX_LAG
    capped = not len(crossings)

    dimension = len(X_COLUMNS) * (lags + 1)
    gram = np.zeros((dimension, dimension), dtype=np.float64)
    observations = 0
    matrices = []
    for values in runs:
        matrix = lag_matrix(values, lags)
        gram += matrix.T @ matrix
        observations += len(matrix)
        matrices.append(matrix)
    covariance = gram / max(observations - 1, 1)
    eigenvalues_all, eigenvectors_all = np.linalg.eigh(covariance)
    order = np.argsort(eigenvalues_all)[::-1]
    eigenvalues_all = np.maximum(eigenvalues_all[order], 0.0)
    eigenvectors_all = eigenvectors_all[:, order]
    cumulative = np.cumsum(eigenvalues_all) / np.sum(eigenvalues_all)
    n_components = int(np.searchsorted(cumulative, VARIANCE_TARGET) + 1)
    loadings = eigenvectors_all[:, :n_components]
    eigenvalues = np.maximum(eigenvalues_all[:n_components], 1e-12)

    t2_parts = []
    spe_parts = []
    for matrix in matrices:
        scores = matrix @ loadings
        reconstructed = scores @ loadings.T
        t2_parts.append(np.sum((scores**2) / eigenvalues, axis=1))
        spe_parts.append(np.sum((matrix - reconstructed) ** 2, axis=1))
    t2 = np.concatenate(t2_parts)
    spe = np.concatenate(spe_parts)

    artifact = None
    if args.artifact_output is not None:
        args.artifact_output.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            args.artifact_output,
            mean=mean,
            scale=scale,
            lags=np.asarray([lags], dtype=np.int64),
            loadings=loadings,
            eigenvalues=eigenvalues,
            t2_limit=np.asarray([float(np.quantile(t2, LIMIT_QUANTILE))], dtype=np.float64),
            spe_limit=np.asarray([float(np.quantile(spe, LIMIT_QUANTILE))], dtype=np.float64),
            persistence=np.asarray([PERSISTENCE], dtype=np.int64),
        )
        artifact = {
            "file": args.artifact_output.name,
            "format": "NumPy NPZ with allow_pickle=false",
            "sha256": sha256_file(args.artifact_output),
            "contents": ["mean", "scale", "lags", "loadings", "eigenvalues", "t2_limit", "spe_limit", "persistence"],
        }

    output = {
        "status": "CANDIDATE_FOR_RESEARCHER_FREEZE",
        "input_cohort": "FaultFree Training only",
        "input_directory": str(args.normal_training_dir.resolve()),
        "input_files": [
            {"name": path.name, "sha256": sha256_file(path)} for path in files
        ],
        "validation": {
            "simulation_runs": len(runs),
            "samples_per_run": 500,
            "x_columns": len(X_COLUMNS),
            "rows": len(runs) * 500,
            "target_fault_data_accessed": False,
        },
        "normalization": {
            "method": "per-variable FaultFree Training mean and sample standard deviation (ddof=1)",
            "zero_scale_replacement": 1.0,
        },
        "lag_selection": {
            "procedure": "For lags 1..20, compute within-run pooled autocorrelation for each standardized X variable; aggregate by median absolute autocorrelation; select the smallest lag at or below lag-1 median divided by e; if no crossing exists, cap at 20 and flag capped=true.",
            "maximum_lag_samples": MAX_LAG,
            "median_absolute_acf_by_lag": {
                str(index + 1): float(value) for index, value in enumerate(median_abs_acf)
            },
            "e_fold_threshold": e_fold_threshold,
            "selected_lags": lags,
            "capped": capped,
        },
        "model": {
            "lag_vector_order": "current sample, lag 1, ..., lag L; within each block xmeas_1..xmeas_41 then xmv_1..xmv_11",
            "lagged_dimension": dimension,
            "reference_observations": observations,
            "component_rule": "smallest component count reaching at least 0.95 cumulative variance",
            "variance_target": VARIANCE_TARGET,
            "n_components": n_components,
            "cumulative_variance": float(cumulative[n_components - 1]),
            "limit_method": "empirical quantile on the same FaultFree Training reference scores",
            "threshold_quantile": LIMIT_QUANTILE,
            "t2_limit": float(np.quantile(t2, LIMIT_QUANTILE)),
            "spe_q_limit": float(np.quantile(spe, LIMIT_QUANTILE)),
            "alarm_rule": "raw exceedance when T2 > t2_limit OR SPE/Q > spe_q_limit",
            "persistence_consecutive_exceedances": PERSISTENCE,
        },
        "frozen_artifact": artifact,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

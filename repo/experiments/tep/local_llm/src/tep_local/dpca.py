from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .constants import X_COLUMNS


def _lag_matrix(values: np.ndarray, lags: int) -> np.ndarray:
    if len(values) <= lags:
        return np.empty((0, values.shape[1] * (lags + 1)))
    return np.vstack([
        np.concatenate([values[index - lag] for lag in range(lags + 1)])
        for index in range(lags, len(values))
    ])


@dataclass
class DPCAModel:
    lags: int
    loadings: np.ndarray
    eigenvalues: np.ndarray
    t2_limit: float
    spe_limit: float
    persistence: int

    @classmethod
    def fit(
        cls,
        standardized_normal: pd.DataFrame,
        lags: int,
        n_components: int | None,
        variance_target: float,
        threshold_quantile: float,
        persistence: int,
    ) -> "DPCAModel":
        matrices = []
        for _, run in standardized_normal.groupby("blind_run_id", sort=True):
            matrices.append(_lag_matrix(run.sort_values("sample")[X_COLUMNS].to_numpy(dtype=np.float64), lags))
        training = np.vstack([matrix for matrix in matrices if len(matrix)])
        if not len(training):
            raise ValueError("Not enough normal observations for DPCA")

        _, singular, vt = np.linalg.svd(training, full_matrices=False)
        eigenvalues_all = (singular**2) / max(len(training) - 1, 1)
        if n_components is None:
            cumulative = np.cumsum(eigenvalues_all) / np.sum(eigenvalues_all)
            count = int(np.searchsorted(cumulative, variance_target) + 1)
        else:
            count = int(n_components)
        count = max(1, min(count, len(eigenvalues_all)))
        loadings = vt[:count].T
        eigenvalues = np.maximum(eigenvalues_all[:count], 1e-12)

        scores = training @ loadings
        reconstructed = scores @ loadings.T
        t2 = np.sum((scores**2) / eigenvalues, axis=1)
        spe = np.sum((training - reconstructed) ** 2, axis=1)
        return cls(
            lags=lags,
            loadings=loadings,
            eigenvalues=eigenvalues,
            t2_limit=float(np.quantile(t2, threshold_quantile)),
            spe_limit=float(np.quantile(spe, threshold_quantile)),
            persistence=int(persistence),
        )

    def score(self, standardized: pd.DataFrame) -> pd.DataFrame:
        records: list[dict] = []
        for blind_run_id, run in standardized.groupby("blind_run_id", sort=True):
            run = run.sort_values("sample").reset_index(drop=True)
            values = run[X_COLUMNS].to_numpy(dtype=np.float64)
            consecutive = 0
            for index, sample in enumerate(run["sample"].astype(int)):
                if index < self.lags:
                    records.append({"blind_run_id": blind_run_id, "sample": sample, "t2": None, "spe": None, "alarm_raw": False, "alarm_persistent": False})
                    continue
                vector = np.concatenate([values[index - lag] for lag in range(self.lags + 1)])
                score = vector @ self.loadings
                reconstructed = score @ self.loadings.T
                t2 = float(np.sum((score**2) / self.eigenvalues))
                spe = float(np.sum((vector - reconstructed) ** 2))
                raw = t2 > self.t2_limit or spe > self.spe_limit
                consecutive = consecutive + 1 if raw else 0
                records.append({
                    "blind_run_id": blind_run_id,
                    "sample": sample,
                    "t2": t2,
                    "spe": spe,
                    "alarm_raw": bool(raw),
                    "alarm_persistent": bool(consecutive >= self.persistence),
                })
        return pd.DataFrame.from_records(records)

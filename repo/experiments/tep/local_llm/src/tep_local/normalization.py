from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .constants import X_COLUMNS


@dataclass(frozen=True)
class Standardizer:
    mean: np.ndarray
    scale: np.ndarray

    @classmethod
    def fit(cls, normal: pd.DataFrame) -> "Standardizer":
        values = normal[X_COLUMNS].to_numpy(dtype=np.float64)
        mean = values.mean(axis=0)
        scale = values.std(axis=0, ddof=1)
        scale[scale == 0] = 1.0
        return cls(mean=mean, scale=scale)

    def transform_values(self, values: np.ndarray) -> np.ndarray:
        return (np.asarray(values, dtype=np.float64) - self.mean) / self.scale

    def transform_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        result.loc[:, X_COLUMNS] = self.transform_values(result[X_COLUMNS].to_numpy())
        return result

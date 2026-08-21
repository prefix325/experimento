from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import pandas as pd


@dataclass(frozen=True)
class CausalWindow:
    blind_run_id: str
    window_id: int
    sample_start: int
    sample_end: int
    frame: pd.DataFrame


def iter_causal_windows(
    frame: pd.DataFrame,
    window_samples: int,
    stride_samples: int,
    max_windows_per_run: int | None = None,
) -> Iterator[CausalWindow]:
    if window_samples <= 0 or stride_samples <= 0:
        raise ValueError("Window and stride must be positive")

    for blind_run_id, run in frame.groupby("blind_run_id", sort=True):
        run = run.sort_values("sample").reset_index(drop=True)
        emitted = 0
        for start in range(0, len(run) - window_samples + 1, stride_samples):
            if max_windows_per_run is not None and emitted >= max_windows_per_run:
                break
            window = run.iloc[start : start + window_samples].copy()
            yield CausalWindow(
                blind_run_id=str(blind_run_id),
                window_id=emitted,
                sample_start=int(window["sample"].iloc[0]),
                sample_end=int(window["sample"].iloc[-1]),
                frame=window,
            )
            emitted += 1

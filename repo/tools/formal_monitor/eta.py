from __future__ import annotations

from statistics import median


def robust_completed_duration_seconds(completed_durations: list[float], recent_limit: int = 10) -> float | None:
    valid = [float(value) for value in completed_durations if float(value) >= 0]
    if not valid:
        return None
    return float(median(valid[-recent_limit:]))


def estimate_total_eta_seconds(completed_durations: list[float], remaining_batches: int) -> float | None:
    typical = robust_completed_duration_seconds(completed_durations)
    if typical is None:
        return None
    return typical * max(0, int(remaining_batches))


def estimate_current_batch_eta_seconds(elapsed_seconds: float, windows_completed: int, window_total_max: int) -> float | None:
    if windows_completed <= 0 or window_total_max <= 0:
        return None
    seconds_per_window = max(0.0, float(elapsed_seconds)) / int(windows_completed)
    return seconds_per_window * max(0, int(window_total_max) - int(windows_completed))


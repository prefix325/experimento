import pandas as pd

from tep_local.windowing import iter_causal_windows


def test_causal_windows_never_include_future_samples():
    frame = pd.DataFrame({
        "blind_run_id": ["RUN_000001"] * 30,
        "sample": list(range(1, 31)),
        "value": list(range(1, 31)),
    })
    windows = list(iter_causal_windows(frame, window_samples=20, stride_samples=5))
    assert [(window.sample_start, window.sample_end) for window in windows] == [(1, 20), (6, 25), (11, 30)]
    for window in windows:
        assert int(window.frame["sample"].max()) == window.sample_end
        assert all(window.frame["sample"] <= window.sample_end)


def test_window_limit_is_per_run():
    frame = pd.concat([
        pd.DataFrame({"blind_run_id": [run] * 30, "sample": range(1, 31)})
        for run in ["RUN_000001", "RUN_000002"]
    ], ignore_index=True)
    windows = list(iter_causal_windows(frame, 20, 5, max_windows_per_run=1))
    assert len(windows) == 2
    assert {window.blind_run_id for window in windows} == {"RUN_000001", "RUN_000002"}

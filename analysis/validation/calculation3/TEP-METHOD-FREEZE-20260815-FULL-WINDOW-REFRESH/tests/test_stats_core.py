"""Purely synthetic tests for the independent Calculation 3 statistics."""

from __future__ import annotations

import math
from pathlib import Path
import sys

import numpy as np
import pytest


CODE_DIRECTORY = Path(__file__).resolve().parents[1] / "code"
sys.path.insert(0, str(CODE_DIRECTORY))

from stats_core import (  # noqa: E402
    DEFAULT_BOOTSTRAP_REPLICATES,
    bootstrap_ci,
    clopper_pearson_interval,
    exact_sign_test,
    holm_adjust,
    mcnemar_exact,
    mcnemar_exact_from_counts,
    numeric_summary,
    paired_binary_table,
    paired_delays,
    paired_proportion_difference,
    proportion_summary,
    wilson_interval,
)


def test_wilson_uses_explicit_formula() -> None:
    interval = wilson_interval(5, 10)

    z = 1.959963984540054
    p_hat = 0.5
    denominator = 1.0 + z**2 / 10
    expected_center = (p_hat + z**2 / 20) / denominator
    expected_half_width = (
        z
        / denominator
        * math.sqrt(p_hat * (1.0 - p_hat) / 10 + z**2 / 400)
    )

    assert interval["z"] == pytest.approx(z)
    assert interval["lower"] == pytest.approx(expected_center - expected_half_width)
    assert interval["upper"] == pytest.approx(expected_center + expected_half_width)
    assert interval["method"] == "Wilson score"


def test_wilson_empty_denominator_is_explicitly_undefined() -> None:
    interval = wilson_interval(0, 0)

    assert interval["estimate"] is None
    assert interval["lower"] is None
    assert interval["upper"] is None


@pytest.mark.parametrize(
    ("events", "expected_lower", "expected_upper"),
    [
        (0, 0.0, 1.0 - 0.025 ** (1.0 / 10.0)),
        (10, 0.025 ** (1.0 / 10.0), 1.0),
    ],
)
def test_clopper_pearson_beta_quantiles_at_extremes(
    events: int, expected_lower: float, expected_upper: float
) -> None:
    interval = clopper_pearson_interval(events, 10)

    assert interval["lower"] == pytest.approx(expected_lower)
    assert interval["upper"] == pytest.approx(expected_upper)
    assert "Beta quantiles" in interval["method"]


def test_proportion_summary_adds_exact_interval_only_at_extremes() -> None:
    assert proportion_summary(0, 7)["clopper_pearson"] is not None
    assert proportion_summary(7, 7)["clopper_pearson"] is not None
    assert proportion_summary(3, 7)["clopper_pearson"] is None
    assert proportion_summary(0, 0)["clopper_pearson"] is None


def test_numeric_summary_empty_and_singleton() -> None:
    empty = numeric_summary([])
    singleton = numeric_summary([7.5])

    assert empty == {
        "n": 0,
        "mean": None,
        "sample_sd": None,
        "median": None,
        "q1": None,
        "q3": None,
        "iqr": None,
        "min": None,
        "max": None,
        "quantile_method": "NumPy linear",
    }
    assert singleton["n"] == 1
    assert singleton["sample_sd"] is None
    for key in ("mean", "median", "q1", "q3", "min", "max"):
        assert singleton[key] == 7.5
    assert singleton["iqr"] is None


def test_numeric_summary_uses_numpy_linear_quantiles_and_sample_sd() -> None:
    summary = numeric_summary([0.0, 10.0])

    assert summary["q1"] == 2.5
    assert summary["median"] == 5.0
    assert summary["q3"] == 7.5
    assert summary["iqr"] == 5.0
    assert summary["sample_sd"] == pytest.approx(math.sqrt(50.0))
    assert summary["quantile_method"] == "NumPy linear"


def test_bootstrap_mean_is_reproducible_and_defaults_to_10k() -> None:
    synthetic_values = [1.0, 2.0, 4.0, 8.0, 9.0, 13.0, 17.0]
    first = bootstrap_ci(synthetic_values, "mean", seed=314159)
    second = bootstrap_ci(synthetic_values, "mean", seed=314159)

    assert first == second
    assert first["replicates"] == DEFAULT_BOOTSTRAP_REPLICATES == 10_000
    assert first["estimate"] == pytest.approx(np.mean(synthetic_values))
    assert first["lower"] < first["estimate"] < first["upper"]
    assert first["method"] == "BCa"
    assert first["implementation"] == "scipy.stats.bootstrap"
    assert first["fallback_reason"] is None


def test_bootstrap_median_is_reproducible() -> None:
    synthetic_values = [1.0, 2.0, 4.0, 7.0, 11.0, 16.0, 22.0, 29.0]
    first = bootstrap_ci(synthetic_values, "median", seed=271828)
    second = bootstrap_ci(synthetic_values, "median", seed=271828)

    assert first == second
    assert first["estimate"] == pytest.approx(9.0)
    assert first["lower"] <= first["estimate"] <= first["upper"]
    assert first["method"] == "BCa"


def test_bootstrap_documents_percentile_fallback_for_degenerate_bca() -> None:
    interval = bootstrap_ci([2.0, 2.0, 2.0, 2.0], "mean", seed=42)

    assert interval["method"] == "percentile"
    assert interval["implementation"] == "explicit NumPy paired-index resampling"
    assert interval["fallback_reason"] is not None
    assert "BCa" in interval["fallback_reason"]
    assert interval["estimate"] == interval["lower"] == interval["upper"] == 2.0


def test_bootstrap_empty_and_singleton_are_well_defined_edge_cases() -> None:
    empty = bootstrap_ci([], "mean", n_resamples=19, seed=1)
    singleton = bootstrap_ci([4.0], "median", n_resamples=19, seed=1)

    assert empty["method"] == "undefined"
    assert empty["estimate"] is None
    assert singleton["method"] == "undefined"
    assert singleton["fallback_reason"] == "singleton sample has no inferential interval under the SAP"
    assert singleton["estimate"] == 4.0
    assert singleton["lower"] is None
    assert singleton["upper"] is None


def test_paired_binary_table_orientation_and_exact_mcnemar() -> None:
    first = [0, 0, 0, 0, 1, 1]
    second = [1, 1, 1, 1, 1, 0]

    table = paired_binary_table(first, second)
    test = mcnemar_exact(first, second)

    assert table == {"n": 6, "00": 0, "01": 4, "10": 1, "11": 1}
    assert test["discordant"] == 5
    assert test["p_value"] == pytest.approx(0.375)
    assert "binomtest" in test["method"]


def test_mcnemar_no_discordances_has_p_one() -> None:
    test = mcnemar_exact_from_counts(0, 0)

    assert test["discordant"] == 0
    assert test["p_value"] == 1.0


def test_exact_sign_test_excludes_ties() -> None:
    test = exact_sign_test([2.0, 1.0, 4.0, 9.0, 0.0])

    assert test["positive"] == 4
    assert test["negative"] == 0
    assert test["ties"] == 1
    assert test["non_ties"] == 4
    assert test["p_value"] == pytest.approx(0.125)
    assert "binomtest" in test["method"]


def test_exact_sign_test_all_ties_has_p_one() -> None:
    test = exact_sign_test([0.0, 0.0])

    assert test["non_ties"] == 0
    assert test["p_value"] == 1.0


def test_holm_exposes_sorted_intermediates_and_monotonic_adjustment() -> None:
    rows = holm_adjust(
        [0.01, 0.04, 0.03], labels=["target", "secondary", "normal"]
    )

    assert [row["label"] for row in rows] == ["target", "normal", "secondary"]
    assert [row["order"] for row in rows] == [1, 3, 2]
    assert [row["rank"] for row in rows] == [1, 2, 3]
    assert [row["multiplier"] for row in rows] == [3, 2, 1]
    assert [row["p_unbounded"] for row in rows] == pytest.approx([0.03, 0.06, 0.04])
    assert [row["p_adjusted_monotonic"] for row in rows] == pytest.approx(
        [0.03, 0.06, 0.06]
    )


def test_holm_caps_adjusted_p_but_retains_unbounded_value() -> None:
    rows = holm_adjust([0.8, 0.9])

    assert rows[0]["p_unbounded"] == pytest.approx(1.6)
    assert rows[0]["p_adjusted_monotonic"] == 1.0
    assert rows[1]["p_adjusted_monotonic"] == 1.0


def test_paired_proportion_difference_resamples_run_differences() -> None:
    result = paired_proportion_difference(
        [1, 1, 0, 1, 0, 1],
        [0, 1, 0, 0, 1, 1],
        n_resamples=999,
        seed=123,
    )

    assert result["n"] == 6
    assert result["llm_events"] == 4
    assert result["dpca_events"] == 3
    assert result["difference"] == pytest.approx(1.0 / 6.0)
    interval = result["confidence_interval"]
    assert interval["unit"] == "paired simulationRun"
    assert interval["lower"] <= result["difference"] <= interval["upper"]


def test_paired_delays_tracks_availability_differences_and_ties() -> None:
    result = paired_delays(
        [10.0, None, 30.0, None, 50.0, 70.0],
        [5.0, 20.0, None, None, 50.0, 80.0],
        n_resamples=999,
        seed=456,
    )

    assert result["total"] == 6
    assert result["neither"] == 1
    assert result["llm_only"] == 1
    assert result["dpca_only"] == 1
    assert result["both"] == 3
    assert result["difference_direction"] == "LLM - DPCA"
    summary = result["difference_summary"]
    assert summary["mean"] == pytest.approx(-5.0 / 3.0)
    assert summary["median"] == 0.0
    assert summary["min"] == -10.0
    assert summary["max"] == 5.0
    assert result["sign_test"]["positive"] == 1
    assert result["sign_test"]["negative"] == 1
    assert result["sign_test"]["ties"] == 1
    assert result["sign_test"]["p_value"] == 1.0


def test_paired_delays_never_imputes_missing_endpoints() -> None:
    result = paired_delays(
        [None, 12.0, None],
        [9.0, None, None],
        n_resamples=99,
        seed=7,
    )

    assert result["both"] == 0
    assert result["difference_summary"]["n"] == 0
    assert result["difference_summary"]["mean"] is None
    assert result["bootstrap_mean"]["method"] == "undefined"
    assert result["bootstrap_median"]["method"] == "undefined"
    assert result["sign_test"]["p_value"] == 1.0


@pytest.mark.parametrize(
    "call",
    [
        lambda: wilson_interval(2, 1),
        lambda: clopper_pearson_interval(-1, 2),
        lambda: paired_binary_table([0, 1], [0]),
        lambda: holm_adjust([0.2, 1.1]),
        lambda: numeric_summary([float("nan")]),
        lambda: paired_delays([float("nan")], [1.0]),
    ],
)
def test_invalid_inputs_fail_loudly(call) -> None:
    with pytest.raises((TypeError, ValueError)):
        call()

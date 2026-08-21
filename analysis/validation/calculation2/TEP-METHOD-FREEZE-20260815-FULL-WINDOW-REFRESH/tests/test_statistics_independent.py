"""Synthetic tests for the independent Calculation 2 statistics module."""

from __future__ import annotations

import importlib.util
from math import sqrt
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import beta, norm


MODULE_PATH = Path(__file__).resolve().parents[1] / "code" / "statistics_independent.py"
SPEC = importlib.util.spec_from_file_location("calculation2_statistics_independent", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
stats = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stats)


def test_wilson_implements_score_formula() -> None:
    lower, upper = stats.wilson_interval(5, 10)
    z = norm.ppf(0.975)
    center = (0.5 + z**2 / 20) / (1 + z**2 / 10)
    half_width = z * sqrt(0.5 * 0.5 / 10 + z**2 / 400) / (1 + z**2 / 10)
    assert lower == pytest.approx(center - half_width)
    assert upper == pytest.approx(center + half_width)


def test_clopper_pearson_handles_both_extremes() -> None:
    lower_zero, upper_zero = stats.clopper_pearson_interval(0, 10)
    lower_full, upper_full = stats.clopper_pearson_interval(10, 10)
    assert lower_zero == 0.0
    assert upper_zero == pytest.approx(beta.ppf(0.975, 1, 10))
    assert lower_full == pytest.approx(beta.ppf(0.025, 10, 1))
    assert upper_full == 1.0


def test_proportion_summary_n_zero_is_explicitly_undefined() -> None:
    result = stats.proportion_summary(0, 0)
    assert result["events"] == 0
    assert result["denominator"] == 0
    assert result["proportion"] is None
    assert result["wilson"] == {"lower": None, "upper": None}
    assert result["clopper_pearson"] == {"lower": None, "upper": None}


def test_numeric_summary_n_zero_and_n_one() -> None:
    assert stats.summarize_numeric([]) == {
        "n": 0,
        "mean": None,
        "sd": None,
        "median": None,
        "q1": None,
        "q3": None,
        "iqr": None,
        "min": None,
        "max": None,
    }
    singleton = stats.summarize_numeric([7.5])
    assert singleton["n"] == 1
    assert singleton["sd"] is None
    for field in ("mean", "median", "min", "max"):
        assert singleton[field] == 7.5
    assert singleton["q1"] is None
    assert singleton["q3"] is None
    assert singleton["iqr"] is None


def test_mcnemar_exact_uses_only_discordant_pairs() -> None:
    result = stats.mcnemar_exact(llm_only=8, dpca_only=1)
    # 2 * P[Binomial(9, .5) <= 1] = 2 * (C(9,0)+C(9,1)) / 2^9.
    assert result["discordant_pairs"] == 9
    assert result["p_value"] == pytest.approx(20 / 512)
    assert result["zero_discordance"] is False


def test_mcnemar_zero_discordance_has_p_one() -> None:
    result = stats.mcnemar_exact(0, 0)
    assert result["zero_discordance"] is True
    assert result["p_value"] == 1.0


def test_exact_sign_test_excludes_ties() -> None:
    result = stats.sign_test_exact([2.0, 1.0, 0.25, -3.0, 0.0])
    assert result["positive"] == 3
    assert result["negative"] == 1
    assert result["ties"] == 1
    assert result["binomial_n"] == 4
    assert result["p_value"] == pytest.approx(10 / 16)


def test_exact_sign_test_all_ties_has_p_one() -> None:
    result = stats.sign_test_exact([0.0, 0.0])
    assert result["binomial_n"] == 0
    assert result["ties"] == 2
    assert result["p_value"] == 1.0


def test_holm_is_step_down_monotone_and_preserves_input_order() -> None:
    result = stats.holm_adjust({"first": 0.01, "second": 0.04, "third": 0.03})
    by_name = {record["hypothesis"]: record for record in result}
    assert [record["hypothesis"] for record in result] == ["first", "second", "third"]
    assert by_name["first"] == {
        "hypothesis": "first",
        "raw_p": 0.01,
        "rank": 1,
        "multiplier": 3,
        "adjusted_p": pytest.approx(0.03),
    }
    assert by_name["third"]["rank"] == 2
    assert by_name["third"]["multiplier"] == 2
    assert by_name["third"]["adjusted_p"] == pytest.approx(0.06)
    # The final raw p times one is .04, but monotonicity retains .06.
    assert by_name["second"]["rank"] == 3
    assert by_name["second"]["adjusted_p"] == pytest.approx(0.06)


def test_bootstrap_bca_is_seed_reproducible() -> None:
    values = [1.0, 2.0, 4.0, 8.0, 16.0]
    first = stats.bootstrap_interval(values, resamples=800, seed=1234, method="bca")
    second = stats.bootstrap_interval(values, resamples=800, seed=1234, method="bca")
    assert first == second
    assert first["method_used"] == "bca"
    assert first["fallback_reason"] is None
    assert first["estimate"] == pytest.approx(np.mean(values))
    assert first["ci_lower"] <= first["estimate"] <= first["ci_upper"]


def test_bootstrap_n_one_has_no_inferential_interval_under_sap() -> None:
    result = stats.bootstrap_interval([4.0], resamples=100, seed=7, method="bca")
    assert result["method_used"] is None
    assert "SAP prohibits" in result["fallback_reason"]
    assert result["estimate"] == 4.0
    assert result["ci_lower"] is None
    assert result["ci_upper"] is None


def test_empty_bootstrap_reports_undefined_without_inventing_values() -> None:
    result = stats.bootstrap_interval([], resamples=100, seed=7)
    assert result["n"] == 0
    assert result["estimate"] is None
    assert result["ci_lower"] is None
    assert result["ci_upper"] is None
    assert result["method_used"] is None
    assert result["fallback_reason"] == "interval undefined: empty sample"


def test_paired_bootstrap_resamples_run_pairs() -> None:
    # Every paired difference is one. Independent marginal resampling would
    # not preserve this invariant, whereas paired resampling must.
    result = stats.paired_bootstrap_interval(
        [10.0, 20.0, 30.0],
        [9.0, 19.0, 29.0],
        resamples=250,
        seed=19,
    )
    assert result["pairs"] == 3
    assert result["direction"] == "LLM - DPCA"
    assert result["estimate"] == 1.0
    assert result["ci_lower"] == 1.0
    assert result["ci_upper"] == 1.0
    assert result["method_used"] == "percentile"
    assert result["fallback_reason"] is not None


def test_paired_binary_table_uses_declared_cell_orientation() -> None:
    llm = [0, 0, 1, 1, 1]
    dpca = [0, 1, 0, 1, 0]
    result = stats.paired_binary_counts(llm, dpca)
    assert result == {
        "00": 1,
        "01": 1,
        "10": 2,
        "11": 1,
        "pairs": 5,
        "paired_difference": pytest.approx(0.2),
    }


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda: stats.wilson_interval(2, 1), "events cannot exceed denominator"),
        (lambda: stats.clopper_pearson_interval(-1, 5), "events must be non-negative"),
        (lambda: stats.paired_bootstrap_interval([1], [1, 2]), "same number of pairs"),
        (lambda: stats.paired_binary_counts([0, 2], [0, 1]), "must be 0/1"),
    ],
)
def test_invalid_inputs_fail_loudly(call, message: str) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        call()

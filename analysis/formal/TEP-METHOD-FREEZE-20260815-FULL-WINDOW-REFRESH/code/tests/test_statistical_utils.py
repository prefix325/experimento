from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest


CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT))

from statistical_utils import (  # noqa: E402
    clopper_pearson_interval,
    describe_values,
    exact_mcnemar,
    exact_sign_test,
    holm_adjust,
    paired_binary_summary,
    wilson_interval,
)


def test_wilson_interval_known_value() -> None:
    lower, upper = wilson_interval(5, 10)
    assert lower == pytest.approx(0.2365930905)
    assert upper == pytest.approx(0.7634069095)


def test_wilson_boundary_is_not_degenerate() -> None:
    lower, upper = wilson_interval(0, 10)
    assert lower == pytest.approx(0.0)
    assert upper == pytest.approx(0.2775327999)


def test_clopper_pearson_boundaries() -> None:
    lower, upper = clopper_pearson_interval(0, 10)
    assert lower == 0.0
    assert upper == pytest.approx(1 - 0.025 ** (1 / 10))
    lower_full, upper_full = clopper_pearson_interval(10, 10)
    assert lower_full == pytest.approx(0.025 ** (1 / 10))
    assert upper_full == 1.0


def test_exact_mcnemar_uses_only_discordants() -> None:
    result = exact_mcnemar(llm_only=1, dpca_only=9)
    assert result["discordant_pairs"] == 10
    assert result["p_value"] == pytest.approx(0.021484375)


def test_exact_mcnemar_zero_discordants_is_direct() -> None:
    result = exact_mcnemar(0, 0)
    assert result["p_value"] == 1.0
    assert result["status"] == "NO_DISCORDANT_PAIRS"


def test_holm_adjustment_preserves_original_order() -> None:
    assert holm_adjust([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])


def test_paired_bootstrap_resamples_run_differences() -> None:
    result = paired_binary_summary(
        [1, 1, 0, 0],
        [0, 1, 0, 1],
        label="synthetic-paired",
        replicates=500,
        seed=20260820,
    )
    assert result["pairs"] == 4
    assert result["llm_only"] == 1
    assert result["dpca_only"] == 1
    assert result["paired_proportion_difference_llm_minus_dpca"] == 0.0
    assert result["paired_difference_ci"]["replicates"] == 500


def test_bootstrap_is_reproducible_at_exact_frozen_seed() -> None:
    first = paired_binary_summary(
        [1, 0, 1, 0, 1], [0, 0, 1, 1, 0], label="first-label", replicates=300, seed=20260820
    )
    second = paired_binary_summary(
        [1, 0, 1, 0, 1], [0, 0, 1, 1, 0], label="second-label", replicates=300, seed=20260820
    )
    assert first["paired_difference_ci"] == second["paired_difference_ci"]


def test_sign_test_excludes_exact_ties() -> None:
    result = exact_sign_test([-2, -1, 0, 0, 3])
    assert result["positive"] == 1
    assert result["negative"] == 2
    assert result["ties"] == 2
    assert result["binomial_denominator"] == 3
    assert result["p_value"] == 1.0


def test_n_zero_is_undefined_without_interval() -> None:
    result = describe_values([], label="n-zero", replicates=100)
    assert result["conditional_n"] == 0
    assert result["mean"] is None
    assert result["mean_ci"]["method"] == "UNDEFINED"


def test_n_one_has_value_but_no_dispersion_or_interval() -> None:
    result = describe_values([7.0], label="n-one", replicates=100)
    assert result["conditional_n"] == 1
    assert result["mean"] == 7.0
    assert result["median"] == 7.0
    assert result["sd"] is None
    assert result["iqr"] is None
    assert result["mean_ci"]["lower"] is None
    assert result["mean_ci"]["method"] == "NO_INFERENTIAL_INTERVAL"


def test_invalid_counts_are_rejected() -> None:
    with pytest.raises(ValueError):
        wilson_interval(2, 1)
    with pytest.raises(ValueError):
        clopper_pearson_interval(0, 0)

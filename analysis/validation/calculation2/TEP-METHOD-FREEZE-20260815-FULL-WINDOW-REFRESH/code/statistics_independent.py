"""Independent statistical primitives for Calculation 2.

The functions in this module operate only on already materialized run-level
values.  They intentionally expose intermediate quantities (counts, ranks,
bootstrap method and fallback reason) so the analysis can write an auditable
record without depending on a third-party high-level statistics API.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from math import comb, sqrt
from operator import index
from typing import Any

import numpy as np
from scipy.stats import beta, norm


DEFAULT_CONFIDENCE = 0.95
DEFAULT_BOOTSTRAP_RESAMPLES = 10_000
DEFAULT_BOOTSTRAP_SEED = 20_260_820

Statistic = Callable[[np.ndarray], float]


def _count(value: Any, name: str) -> int:
    """Return an integer count, rejecting floats and negative values."""

    try:
        result = index(value)
    except TypeError as exc:
        raise TypeError(f"{name} must be an integer") from exc
    if result < 0:
        raise ValueError(f"{name} must be non-negative")
    return int(result)


def _validate_binomial_counts(events: Any, denominator: Any) -> tuple[int, int]:
    events_i = _count(events, "events")
    denominator_i = _count(denominator, "denominator")
    if events_i > denominator_i:
        raise ValueError("events cannot exceed denominator")
    return events_i, denominator_i


def _alpha(confidence: float) -> float:
    confidence_f = float(confidence)
    if not np.isfinite(confidence_f) or not 0.0 < confidence_f < 1.0:
        raise ValueError("confidence must be finite and strictly between 0 and 1")
    return 1.0 - confidence_f


def wilson_interval(
    events: int,
    denominator: int,
    confidence: float = DEFAULT_CONFIDENCE,
) -> tuple[float | None, float | None]:
    """Two-sided Wilson score interval for a binomial proportion.

    For ``denominator == 0`` the estimand is undefined, so ``(None, None)``
    is returned.  Otherwise this implements the score formula directly:

    ``(p + z^2/(2n) +/- z*sqrt(p(1-p)/n + z^2/(4n^2))) / (1 + z^2/n)``.
    """

    events_i, denominator_i = _validate_binomial_counts(events, denominator)
    alpha = _alpha(confidence)
    if denominator_i == 0:
        return None, None

    p_hat = events_i / denominator_i
    z = float(norm.ppf(1.0 - alpha / 2.0))
    z_squared = z * z
    scale = 1.0 + z_squared / denominator_i
    center = (p_hat + z_squared / (2.0 * denominator_i)) / scale
    half_width = (
        z
        * sqrt(
            p_hat * (1.0 - p_hat) / denominator_i
            + z_squared / (4.0 * denominator_i * denominator_i)
        )
        / scale
    )
    lower = 0.0 if events_i == 0 else max(0.0, center - half_width)
    upper = 1.0 if events_i == denominator_i else min(1.0, center + half_width)
    return lower, upper


def clopper_pearson_interval(
    events: int,
    denominator: int,
    confidence: float = DEFAULT_CONFIDENCE,
) -> tuple[float | None, float | None]:
    """Two-sided equal-tail Clopper--Pearson interval via Beta quantiles."""

    events_i, denominator_i = _validate_binomial_counts(events, denominator)
    alpha = _alpha(confidence)
    if denominator_i == 0:
        return None, None

    lower = (
        0.0
        if events_i == 0
        else float(beta.ppf(alpha / 2.0, events_i, denominator_i - events_i + 1))
    )
    upper = (
        1.0
        if events_i == denominator_i
        else float(beta.ppf(1.0 - alpha / 2.0, events_i + 1, denominator_i - events_i))
    )
    return lower, upper


def proportion_summary(
    events: int,
    denominator: int,
    confidence: float = DEFAULT_CONFIDENCE,
) -> dict[str, Any]:
    """Summarize one binomial endpoint, including both interval families.

    Clopper--Pearson is always computed so the same schema also covers the
    required sensitivity analysis at ``0/n`` and ``n/n``.  With ``n=0``, the
    proportion and all bounds are explicitly ``None``.
    """

    events_i, denominator_i = _validate_binomial_counts(events, denominator)
    wilson_lower, wilson_upper = wilson_interval(events_i, denominator_i, confidence)
    cp_lower, cp_upper = clopper_pearson_interval(events_i, denominator_i, confidence)
    return {
        "events": events_i,
        "denominator": denominator_i,
        "proportion": None if denominator_i == 0 else events_i / denominator_i,
        "confidence_level": float(confidence),
        "wilson": {"lower": wilson_lower, "upper": wilson_upper},
        "clopper_pearson": {"lower": cp_lower, "upper": cp_upper},
        "extreme_count": denominator_i > 0 and events_i in (0, denominator_i),
    }


def _as_finite_vector(values: Sequence[float] | np.ndarray, name: str) -> np.ndarray:
    if isinstance(values, np.ndarray):
        array = np.asarray(values, dtype=float)
    else:
        array = np.asarray(list(values), dtype=float)
    if array.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    if array.size and not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must contain only finite values")
    return array


def summarize_numeric(values: Sequence[float] | np.ndarray) -> dict[str, float | int | None]:
    """Descriptive summary with sample SD and linear sample quantiles."""

    array = _as_finite_vector(values, "values")
    n = int(array.size)
    empty = {
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
    if n == 0:
        return empty

    if n == 1:
        value = float(array[0])
        return {
            "n": 1,
            "mean": value,
            "sd": None,
            "median": value,
            "q1": None,
            "q3": None,
            "iqr": None,
            "min": value,
            "max": value,
        }

    q1, median, q3 = np.quantile(array, [0.25, 0.5, 0.75], method="linear")
    return {
        "n": n,
        "mean": float(np.mean(array)),
        "sd": float(np.std(array, ddof=1)),
        "median": float(median),
        "q1": float(q1),
        "q3": float(q3),
        "iqr": float(q3 - q1),
        "min": float(np.min(array)),
        "max": float(np.max(array)),
    }


def _two_sided_binomial_half(successes: int, trials: int) -> float:
    """Exact two-sided p-value for Binomial(trials, 0.5).

    Symmetry at p=0.5 makes the two-sided probability twice the tail at
    ``min(successes, trials-successes)``.  The sum is evaluated with integer
    combinations before conversion to float.
    """

    successes_i, trials_i = _validate_binomial_counts(successes, trials)
    if trials_i == 0:
        return 1.0
    tail_limit = min(successes_i, trials_i - successes_i)
    tail_numerator = sum(comb(trials_i, k) for k in range(tail_limit + 1))
    return min(1.0, 2.0 * tail_numerator / (2**trials_i))


def mcnemar_exact(llm_only: int, dpca_only: int) -> dict[str, int | float | str | bool]:
    """Exact bilateral McNemar test from the two discordant cell counts.

    The names encode the Calculation 2 paired-table convention: ``10`` is
    LLM only and ``01`` is DPCA only.  Concordant cells do not enter the test.
    """

    llm_only_i = _count(llm_only, "llm_only")
    dpca_only_i = _count(dpca_only, "dpca_only")
    discordant = llm_only_i + dpca_only_i
    return {
        "llm_only": llm_only_i,
        "dpca_only": dpca_only_i,
        "discordant_pairs": discordant,
        "zero_discordance": discordant == 0,
        "p_value": _two_sided_binomial_half(llm_only_i, discordant),
        "method": "exact two-sided binomial, p=0.5",
    }


# Descriptive alias retained to make call sites read naturally.
exact_mcnemar = mcnemar_exact


def sign_test_exact(
    differences: Sequence[float] | np.ndarray,
    *,
    zero_tolerance: float = 0.0,
) -> dict[str, int | float | str]:
    """Exact bilateral sign test; zero differences are excluded as ties."""

    array = _as_finite_vector(differences, "differences")
    tolerance = float(zero_tolerance)
    if not np.isfinite(tolerance) or tolerance < 0.0:
        raise ValueError("zero_tolerance must be finite and non-negative")

    positive = int(np.count_nonzero(array > tolerance))
    negative = int(np.count_nonzero(array < -tolerance))
    ties = int(array.size - positive - negative)
    binomial_n = positive + negative
    return {
        "positive": positive,
        "negative": negative,
        "ties": ties,
        "binomial_n": binomial_n,
        "p_value": _two_sided_binomial_half(positive, binomial_n),
        "method": "exact two-sided binomial sign test, p=0.5; ties excluded",
    }


exact_sign_test = sign_test_exact


def holm_adjust(
    p_values: Mapping[str, float] | Sequence[float],
    labels: Sequence[str] | None = None,
) -> list[dict[str, str | int | float]]:
    """Apply Holm's step-down adjustment explicitly.

    Returned records stay in input order while ``rank`` records the stable
    ascending raw-p ordering.  Adjusted values use the cumulative maximum of
    ``(m-rank+1) * p`` so they are monotone in ranked order.
    """

    if isinstance(p_values, Mapping):
        if labels is not None:
            raise ValueError("labels must be omitted when p_values is a mapping")
        names = [str(key) for key in p_values]
        raw_values = [float(value) for value in p_values.values()]
    else:
        raw_values = [float(value) for value in p_values]
        if labels is None:
            names = [str(position) for position in range(len(raw_values))]
        else:
            names = [str(label) for label in labels]
            if len(names) != len(raw_values):
                raise ValueError("labels and p_values must have equal length")

    for raw_p in raw_values:
        if not np.isfinite(raw_p) or not 0.0 <= raw_p <= 1.0:
            raise ValueError("every p-value must be finite and in [0, 1]")

    family_size = len(raw_values)
    ranked_indices = sorted(range(family_size), key=lambda position: (raw_values[position], position))
    records: list[dict[str, str | int | float] | None] = [None] * family_size
    running_adjusted = 0.0
    for zero_based_rank, original_position in enumerate(ranked_indices):
        rank = zero_based_rank + 1
        multiplier = family_size - zero_based_rank
        single_step = min(1.0, raw_values[original_position] * multiplier)
        running_adjusted = max(running_adjusted, single_step)
        records[original_position] = {
            "hypothesis": names[original_position],
            "raw_p": raw_values[original_position],
            "rank": rank,
            "multiplier": multiplier,
            "adjusted_p": min(1.0, running_adjusted),
        }

    return [record for record in records if record is not None]


def _evaluate_statistic(statistic: Statistic, values: np.ndarray) -> float:
    estimate = np.asarray(statistic(values), dtype=float)
    if estimate.ndim != 0:
        raise ValueError("statistic must return one scalar")
    result = float(estimate)
    if not np.isfinite(result):
        raise ValueError("statistic must return a finite scalar")
    return result


def _percentile_bounds(
    replicates: np.ndarray,
    alpha: float,
) -> tuple[float, float]:
    lower, upper = np.quantile(replicates, [alpha / 2.0, 1.0 - alpha / 2.0], method="linear")
    return float(lower), float(upper)


def _bca_bounds(
    values: np.ndarray,
    estimate: float,
    replicates: np.ndarray,
    statistic: Statistic,
    alpha: float,
) -> tuple[tuple[float, float] | None, str | None]:
    """Return BCa bounds or a precise reason that BCa is undefined."""

    n = int(values.size)
    if n < 2:
        return None, "BCa undefined: fewer than two observations for jackknife"

    less = int(np.count_nonzero(replicates < estimate))
    equal = int(np.count_nonzero(replicates == estimate))
    # Mid-rank handling prevents arbitrary bias from discrete bootstrap ties.
    bias_probability = (less + 0.5 * equal) / int(replicates.size)
    if not 0.0 < bias_probability < 1.0:
        return None, "BCa undefined: bias-correction probability is on a boundary"
    bias_correction = float(norm.ppf(bias_probability))

    jackknife = np.empty(n, dtype=float)
    for omitted in range(n):
        jackknife[omitted] = _evaluate_statistic(statistic, np.delete(values, omitted))
    jackknife_center = float(np.mean(jackknife))
    centered = jackknife_center - jackknife
    sum_squares = float(np.sum(centered * centered))
    if sum_squares <= np.finfo(float).eps:
        return None, "BCa undefined: jackknife acceleration has zero denominator"
    acceleration = float(np.sum(centered**3) / (6.0 * sum_squares**1.5))

    requested_probabilities = (alpha / 2.0, 1.0 - alpha / 2.0)
    adjusted_probabilities: list[float] = []
    for probability in requested_probabilities:
        normal_quantile = float(norm.ppf(probability))
        denominator = 1.0 - acceleration * (bias_correction + normal_quantile)
        if abs(denominator) <= np.finfo(float).eps:
            return None, "BCa undefined: adjusted-quantile denominator is zero"
        adjusted = float(
            norm.cdf(
                bias_correction
                + (bias_correction + normal_quantile) / denominator
            )
        )
        if not np.isfinite(adjusted) or not 0.0 <= adjusted <= 1.0:
            return None, "BCa undefined: adjusted quantile is outside [0, 1]"
        adjusted_probabilities.append(adjusted)

    if adjusted_probabilities[0] > adjusted_probabilities[1]:
        return None, "BCa undefined: adjusted quantiles are reversed"
    bounds = np.quantile(replicates, adjusted_probabilities, method="linear")
    return (float(bounds[0]), float(bounds[1])), None


def bootstrap_interval(
    values: Sequence[float] | np.ndarray,
    statistic: Statistic = np.mean,
    *,
    confidence: float = DEFAULT_CONFIDENCE,
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    seed: int | None = DEFAULT_BOOTSTRAP_SEED,
    method: str = "bca",
) -> dict[str, Any]:
    """Run-level nonparametric bootstrap interval.

    ``method='bca'`` computes bias correction and delete-one jackknife
    acceleration explicitly.  When either is mathematically undefined, the
    same bootstrap replicates are used for a percentile interval and the
    reason is retained in ``fallback_reason``.
    """

    array = _as_finite_vector(values, "values")
    alpha = _alpha(confidence)
    resamples_i = _count(resamples, "resamples")
    if resamples_i == 0:
        raise ValueError("resamples must be positive")
    requested_method = method.casefold()
    if requested_method not in {"bca", "percentile"}:
        raise ValueError("method must be 'bca' or 'percentile'")

    n = int(array.size)
    base: dict[str, Any] = {
        "n": n,
        "estimate": None,
        "confidence_level": float(confidence),
        "ci_lower": None,
        "ci_upper": None,
        "requested_method": requested_method,
        "method_used": None,
        "fallback_reason": None,
        "resamples": resamples_i,
        "seed": seed,
    }
    if n == 0:
        base["fallback_reason"] = "interval undefined: empty sample"
        return base
    if n == 1:
        base["estimate"] = _evaluate_statistic(statistic, array)
        base["fallback_reason"] = (
            "interval undefined: one observation; SAP prohibits inferential CI for n=1"
        )
        return base

    estimate = _evaluate_statistic(statistic, array)
    generator = np.random.default_rng(seed)
    replicates = np.empty(resamples_i, dtype=float)
    for replicate in range(resamples_i):
        sample_indices = generator.integers(0, n, size=n)
        replicates[replicate] = _evaluate_statistic(statistic, array[sample_indices])

    fallback_reason: str | None = None
    if requested_method == "bca":
        bounds, fallback_reason = _bca_bounds(array, estimate, replicates, statistic, alpha)
        if bounds is None:
            bounds = _percentile_bounds(replicates, alpha)
            method_used = "percentile"
        else:
            method_used = "bca"
    else:
        bounds = _percentile_bounds(replicates, alpha)
        method_used = "percentile"

    base.update(
        {
            "estimate": estimate,
            "ci_lower": bounds[0],
            "ci_upper": bounds[1],
            "method_used": method_used,
            "fallback_reason": fallback_reason,
        }
    )
    return base


def paired_bootstrap_interval(
    llm_values: Sequence[float] | np.ndarray,
    dpca_values: Sequence[float] | np.ndarray,
    statistic: Statistic = np.mean,
    *,
    confidence: float = DEFAULT_CONFIDENCE,
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    seed: int | None = DEFAULT_BOOTSTRAP_SEED,
    method: str = "bca",
) -> dict[str, Any]:
    """Bootstrap an LLM-minus-DPCA statistic while preserving run pairs.

    Resampling pairwise differences by row is equivalent to drawing paired
    indices and ensures that the inferential unit remains the simulation run.
    Missing/undefined delays must be filtered by the caller to the intersection
    where both endpoints are defined; non-finite values are rejected here.
    """

    llm = _as_finite_vector(llm_values, "llm_values")
    dpca = _as_finite_vector(dpca_values, "dpca_values")
    if llm.size != dpca.size:
        raise ValueError("llm_values and dpca_values must contain the same number of pairs")
    result = bootstrap_interval(
        llm - dpca,
        statistic,
        confidence=confidence,
        resamples=resamples,
        seed=seed,
        method=method,
    )
    result["pairs"] = int(llm.size)
    result["direction"] = "LLM - DPCA"
    return result


bootstrap_paired = paired_bootstrap_interval


def paired_binary_counts(
    llm_detected: Sequence[bool | int] | np.ndarray,
    dpca_detected: Sequence[bool | int] | np.ndarray,
) -> dict[str, int | float]:
    """Construct the auditable 00/01/10/11 table for matched binary runs."""

    llm = _as_finite_vector(llm_detected, "llm_detected")
    dpca = _as_finite_vector(dpca_detected, "dpca_detected")
    if llm.size != dpca.size:
        raise ValueError("llm_detected and dpca_detected must have equal length")
    if np.any((llm != 0.0) & (llm != 1.0)) or np.any((dpca != 0.0) & (dpca != 1.0)):
        raise ValueError("paired binary values must be 0/1 or boolean")

    cell_00 = int(np.count_nonzero((llm == 0.0) & (dpca == 0.0)))
    cell_01 = int(np.count_nonzero((llm == 0.0) & (dpca == 1.0)))
    cell_10 = int(np.count_nonzero((llm == 1.0) & (dpca == 0.0)))
    cell_11 = int(np.count_nonzero((llm == 1.0) & (dpca == 1.0)))
    return {
        "00": cell_00,
        "01": cell_01,
        "10": cell_10,
        "11": cell_11,
        "pairs": int(llm.size),
        "paired_difference": None if llm.size == 0 else float(np.mean(llm - dpca)),
    }


def paired_binary_analysis(
    llm_detected: Sequence[bool | int] | np.ndarray,
    dpca_detected: Sequence[bool | int] | np.ndarray,
    *,
    confidence: float = DEFAULT_CONFIDENCE,
    resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    seed: int | None = DEFAULT_BOOTSTRAP_SEED,
    bootstrap_method: str = "bca",
) -> dict[str, Any]:
    """Paired binary table, exact McNemar test, and paired bootstrap CI."""

    cells = paired_binary_counts(llm_detected, dpca_detected)
    return {
        **cells,
        "mcnemar": mcnemar_exact(int(cells["10"]), int(cells["01"])),
        "bootstrap": paired_bootstrap_interval(
            llm_detected,
            dpca_detected,
            confidence=confidence,
            resamples=resamples,
            seed=seed,
            method=bootstrap_method,
        ),
    }


__all__ = [
    "DEFAULT_BOOTSTRAP_RESAMPLES",
    "DEFAULT_BOOTSTRAP_SEED",
    "DEFAULT_CONFIDENCE",
    "bootstrap_interval",
    "bootstrap_paired",
    "clopper_pearson_interval",
    "exact_mcnemar",
    "exact_sign_test",
    "holm_adjust",
    "mcnemar_exact",
    "paired_binary_analysis",
    "paired_binary_counts",
    "paired_bootstrap_interval",
    "proportion_summary",
    "sign_test_exact",
    "summarize_numeric",
    "wilson_interval",
]

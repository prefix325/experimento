"""Statistical primitives frozen by the formal campaign SAP.

All resampling functions operate on complete run-level observations (or paired
run-level differences).  No window-level resampling is exposed by this module.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
from scipy.stats import beta, binom, norm


ALPHA = 0.05
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20_260_820


def _finite_float(value: float | np.floating[Any]) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Statistic must be finite")
    return result


def wilson_interval(events: int, total: int, alpha: float = ALPHA) -> tuple[float, float]:
    """Two-sided Wilson score interval for a binomial proportion."""
    if total <= 0 or events < 0 or events > total:
        raise ValueError("Require 0 <= events <= total and total > 0")
    z = float(norm.ppf(1.0 - alpha / 2.0))
    p = events / total
    z2_n = z * z / total
    center = (p + z * z / (2.0 * total)) / (1.0 + z2_n)
    half = z * math.sqrt(p * (1.0 - p) / total + z * z / (4.0 * total**2)) / (
        1.0 + z2_n
    )
    lower = 0.0 if events == 0 else max(0.0, center - half)
    upper = 1.0 if events == total else min(1.0, center + half)
    return lower, upper


def clopper_pearson_interval(
    events: int, total: int, alpha: float = ALPHA
) -> tuple[float, float]:
    """Two-sided equal-tail Clopper-Pearson exact interval."""
    if total <= 0 or events < 0 or events > total:
        raise ValueError("Require 0 <= events <= total and total > 0")
    lower = 0.0 if events == 0 else float(beta.ppf(alpha / 2.0, events, total - events + 1))
    upper = 1.0 if events == total else float(
        beta.ppf(1.0 - alpha / 2.0, events + 1, total - events)
    )
    return lower, upper


def exact_mcnemar(llm_only: int, dpca_only: int) -> dict[str, Any]:
    """Exact two-sided McNemar test using only discordant pairs."""
    if llm_only < 0 or dpca_only < 0:
        raise ValueError("Discordant counts must be non-negative")
    discordant = llm_only + dpca_only
    if discordant == 0:
        return {
            "llm_only": llm_only,
            "dpca_only": dpca_only,
            "discordant_pairs": 0,
            "p_value": 1.0,
            "status": "NO_DISCORDANT_PAIRS",
        }
    p_value = min(1.0, 2.0 * float(binom.cdf(min(llm_only, dpca_only), discordant, 0.5)))
    return {
        "llm_only": llm_only,
        "dpca_only": dpca_only,
        "discordant_pairs": discordant,
        "p_value": p_value,
        "status": "EXACT_BINOMIAL_TWO_SIDED",
    }


def holm_adjust(p_values: Sequence[float]) -> list[float]:
    """Holm step-down adjusted p-values, returned in original order."""
    values = [float(value) for value in p_values]
    if any(not 0.0 <= value <= 1.0 for value in values):
        raise ValueError("p-values must lie in [0, 1]")
    order = sorted(range(len(values)), key=values.__getitem__)
    adjusted = [0.0] * len(values)
    running = 0.0
    m = len(values)
    for rank, index in enumerate(order):
        running = max(running, (m - rank) * values[index])
        adjusted[index] = min(1.0, running)
    return adjusted


def exact_sign_test(differences: Sequence[float]) -> dict[str, Any]:
    """Exact two-sided sign test; exact zero differences are excluded."""
    values = np.asarray(differences, dtype=float)
    if values.ndim != 1 or np.any(~np.isfinite(values)):
        raise ValueError("differences must be a finite one-dimensional sequence")
    positives = int(np.sum(values > 0))
    negatives = int(np.sum(values < 0))
    ties = int(np.sum(values == 0))
    non_ties = positives + negatives
    if non_ties == 0:
        p_value = 1.0
        status = "ALL_TIES"
    else:
        p_value = min(1.0, 2.0 * float(binom.cdf(min(positives, negatives), non_ties, 0.5)))
        status = "EXACT_BINOMIAL_TWO_SIDED_TIES_EXCLUDED"
    return {
        "positive": positives,
        "negative": negatives,
        "ties": ties,
        "binomial_denominator": non_ties,
        "p_value": p_value,
        "status": status,
    }


def _bootstrap_distribution(
    values: np.ndarray,
    statistic: Callable[[np.ndarray], float],
    replicates: int,
    seed: int,
    label: str,
) -> np.ndarray:
    # The frozen SAP names seed 20260820 explicitly. Each interval starts a
    # fresh generator at that exact seed; ``label`` is retained in the public
    # call for an auditable statistic identity, not for changing the RNG seed.
    if not label:
        raise ValueError("bootstrap label must be non-empty")
    rng = np.random.default_rng(seed)
    n = len(values)
    result = np.empty(replicates, dtype=float)
    batch = 500
    for start in range(0, replicates, batch):
        count = min(batch, replicates - start)
        indices = rng.integers(0, n, size=(count, n))
        for offset, sample in enumerate(values[indices]):
            result[start + offset] = _finite_float(statistic(sample))
    return result


def bootstrap_interval(
    values: Sequence[float],
    statistic: Callable[[np.ndarray], float],
    *,
    label: str,
    replicates: int = BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
    alpha: float = ALPHA,
) -> dict[str, Any]:
    """BCa interval with a recorded percentile fallback when BCa is undefined."""
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or np.any(~np.isfinite(array)):
        raise ValueError("values must be a finite one-dimensional sequence")
    n = len(array)
    if n == 0:
        return {
            "estimate": None,
            "lower": None,
            "upper": None,
            "method": "UNDEFINED",
            "fallback_reason": "N_ZERO",
            "replicates": 0,
            "seed": seed,
        }
    estimate = _finite_float(statistic(array))
    if n == 1:
        return {
            "estimate": estimate,
            "lower": None,
            "upper": None,
            "method": "NO_INFERENTIAL_INTERVAL",
            "fallback_reason": "N_ONE",
            "replicates": 0,
            "seed": seed,
        }
    if replicates <= 0:
        raise ValueError("replicates must be positive")

    boot = _bootstrap_distribution(array, statistic, replicates, seed, label)
    percentile = tuple(float(x) for x in np.quantile(boot, [alpha / 2.0, 1.0 - alpha / 2.0]))

    jackknife = np.asarray(
        [_finite_float(statistic(np.delete(array, index))) for index in range(n)], dtype=float
    )
    jack_mean = float(np.mean(jackknife))
    deltas = jack_mean - jackknife
    denominator = 6.0 * float(np.sum(deltas**2)) ** 1.5
    fallback_reason: str | None = None
    if denominator == 0.0 or not math.isfinite(denominator):
        fallback_reason = "BCa_ACCELERATION_UNDEFINED_DEGENERATE_JACKKNIFE"
    else:
        acceleration = float(np.sum(deltas**3)) / denominator
        less = float(np.sum(boot < estimate))
        equal = float(np.sum(boot == estimate))
        probability = (less + 0.5 * equal) / replicates
        probability = min(1.0 - 0.5 / replicates, max(0.5 / replicates, probability))
        bias = float(norm.ppf(probability))
        z_low, z_high = norm.ppf([alpha / 2.0, 1.0 - alpha / 2.0])

        adjusted: list[float] = []
        for z_alpha in (float(z_low), float(z_high)):
            term = bias + z_alpha
            divisor = 1.0 - acceleration * term
            if divisor == 0.0:
                fallback_reason = "BCa_ADJUSTED_QUANTILE_UNDEFINED"
                break
            quantile = float(norm.cdf(bias + term / divisor))
            if not math.isfinite(quantile) or not 0.0 <= quantile <= 1.0:
                fallback_reason = "BCa_ADJUSTED_QUANTILE_OUT_OF_RANGE"
                break
            adjusted.append(quantile)
        if fallback_reason is None:
            lower, upper = (float(x) for x in np.quantile(boot, adjusted))
            return {
                "estimate": estimate,
                "lower": lower,
                "upper": upper,
                "method": "BCa_95",
                "fallback_reason": None,
                "replicates": replicates,
                "seed": seed,
                "resampling_unit": "simulationRun",
            }

    return {
        "estimate": estimate,
        "lower": percentile[0],
        "upper": percentile[1],
        "method": "PERCENTILE_95_FALLBACK",
        "fallback_reason": fallback_reason,
        "replicates": replicates,
        "seed": seed,
        "resampling_unit": "simulationRun",
    }


def describe_values(
    values: Sequence[float],
    *,
    label: str,
    replicates: int = BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """SAP-prespecified descriptive and bootstrap summaries."""
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or np.any(~np.isfinite(array)):
        raise ValueError("values must be a finite one-dimensional sequence")
    n = len(array)
    if n == 0:
        return {
            "conditional_n": 0,
            "mean": None,
            "sd": None,
            "median": None,
            "q1": None,
            "q3": None,
            "iqr": None,
            "minimum": None,
            "maximum": None,
            "mean_ci": bootstrap_interval([], np.mean, label=f"{label}:mean", replicates=replicates, seed=seed),
            "median_ci": bootstrap_interval([], np.median, label=f"{label}:median", replicates=replicates, seed=seed),
        }
    mean = float(np.mean(array))
    median = float(np.median(array))
    if n == 1:
        q1 = q3 = iqr = sd = None
    else:
        q1, q3 = (float(x) for x in np.quantile(array, [0.25, 0.75]))
        iqr = q3 - q1
        sd = float(np.std(array, ddof=1))
    return {
        "conditional_n": n,
        "mean": mean,
        "sd": sd,
        "median": median,
        "q1": q1,
        "q3": q3,
        "iqr": iqr,
        "minimum": float(np.min(array)),
        "maximum": float(np.max(array)),
        "mean_ci": bootstrap_interval(
            array, np.mean, label=f"{label}:mean", replicates=replicates, seed=seed
        ),
        "median_ci": bootstrap_interval(
            array, np.median, label=f"{label}:median", replicates=replicates, seed=seed
        ),
    }


def paired_binary_summary(
    llm: Sequence[bool | int],
    dpca: Sequence[bool | int],
    *,
    label: str,
    replicates: int = BOOTSTRAP_REPLICATES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Run-paired 2x2 table, exact McNemar, and paired bootstrap effect CI."""
    left = np.asarray(llm, dtype=int)
    right = np.asarray(dpca, dtype=int)
    if left.shape != right.shape or left.ndim != 1 or np.any(~np.isin(left, [0, 1])) or np.any(~np.isin(right, [0, 1])):
        raise ValueError("llm and dpca must be same-length binary vectors")
    n = len(left)
    if n == 0:
        raise ValueError("paired binary comparison requires at least one pair")
    n00 = int(np.sum((left == 0) & (right == 0)))
    n01 = int(np.sum((left == 0) & (right == 1)))
    n10 = int(np.sum((left == 1) & (right == 0)))
    n11 = int(np.sum((left == 1) & (right == 1)))
    differences = left.astype(float) - right.astype(float)
    interval = bootstrap_interval(
        differences,
        np.mean,
        label=f"{label}:paired_difference",
        replicates=replicates,
        seed=seed,
    )
    return {
        "pairs": n,
        "llm0_dpca0": n00,
        "llm0_dpca1": n01,
        "llm1_dpca0": n10,
        "llm1_dpca1": n11,
        "concordant_pairs": n00 + n11,
        "concordance": (n00 + n11) / n,
        "dpca_only": n01,
        "llm_only": n10,
        "paired_proportion_difference_llm_minus_dpca": float(np.mean(differences)),
        "paired_difference_ci": interval,
        "mcnemar": exact_mcnemar(n10, n01),
    }

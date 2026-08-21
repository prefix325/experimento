"""Independent statistical primitives for Calculation 3.

This module is intentionally free of project-data access and aggregation logic.
Every public function operates only on values supplied by its caller and returns
plain, JSON-serializable dictionaries.

Bootstrap intervals prefer SciPy's bias-corrected and accelerated (BCa)
implementation.  When BCa is mathematically undefined or produces non-finite
bounds, the implementation falls back to an explicitly resampled percentile
interval and records the reason in ``fallback_reason``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import math
import warnings

import numpy as np
from scipy.stats import beta, binomtest, bootstrap as scipy_bootstrap, norm


DEFAULT_CONFIDENCE_LEVEL = 0.95
DEFAULT_BOOTSTRAP_REPLICATES = 10_000
DEFAULT_BOOTSTRAP_SEED = 20_260_820


__all__ = [
    "DEFAULT_BOOTSTRAP_REPLICATES",
    "DEFAULT_BOOTSTRAP_SEED",
    "DEFAULT_CONFIDENCE_LEVEL",
    "bootstrap_ci",
    "clopper_pearson_interval",
    "exact_sign_test",
    "holm_adjust",
    "mcnemar_exact",
    "mcnemar_exact_from_counts",
    "numeric_summary",
    "paired_binary_table",
    "paired_delays",
    "paired_proportion_difference",
    "proportion_summary",
    "wilson_interval",
]


def _validate_confidence_level(confidence_level: float) -> float:
    if isinstance(confidence_level, (bool, np.bool_)):
        raise TypeError("confidence_level must be a real number")
    try:
        value = float(confidence_level)
    except (TypeError, ValueError) as exc:
        raise TypeError("confidence_level must be a real number") from exc
    if not math.isfinite(value) or not 0.0 < value < 1.0:
        raise ValueError("confidence_level must be strictly between 0 and 1")
    return value


def _validate_nonnegative_integer(value: int, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value, (int, np.integer)
    ):
        raise TypeError(f"{name} must be an integer")
    integer = int(value)
    if integer < 0:
        raise ValueError(f"{name} must be non-negative")
    return integer


def _validate_binomial_counts(events: int, n: int) -> tuple[int, int]:
    events_value = _validate_nonnegative_integer(events, "events")
    n_value = _validate_nonnegative_integer(n, "n")
    if events_value > n_value:
        raise ValueError("events cannot exceed n")
    return events_value, n_value


def _validate_bootstrap_configuration(
    n_resamples: int, seed: int
) -> tuple[int, int]:
    resamples_value = _validate_nonnegative_integer(n_resamples, "n_resamples")
    if resamples_value == 0:
        raise ValueError("n_resamples must be at least 1")
    seed_value = _validate_nonnegative_integer(seed, "seed")
    return resamples_value, seed_value


def _finite_numeric_array(values: Sequence[float], name: str) -> np.ndarray:
    try:
        raw_values = list(values)
    except TypeError as exc:
        raise TypeError(f"{name} must be a one-dimensional sequence") from exc

    converted: list[float] = []
    for index, value in enumerate(raw_values):
        if isinstance(value, (bool, np.bool_)):
            raise TypeError(f"{name}[{index}] must be numeric, not boolean")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"{name}[{index}] must be numeric") from exc
        if not math.isfinite(number):
            raise ValueError(f"{name}[{index}] must be finite")
        converted.append(number)
    return np.asarray(converted, dtype=float)


def _binary_array(values: Sequence[bool | int], name: str) -> np.ndarray:
    try:
        raw_values = list(values)
    except TypeError as exc:
        raise TypeError(f"{name} must be a one-dimensional sequence") from exc

    converted: list[int] = []
    for index, value in enumerate(raw_values):
        if isinstance(value, (bool, np.bool_)):
            converted.append(int(value))
            continue
        if isinstance(value, (int, np.integer)) and int(value) in (0, 1):
            converted.append(int(value))
            continue
        raise ValueError(f"{name}[{index}] must be boolean or integer 0/1")
    return np.asarray(converted, dtype=np.int8)


def wilson_interval(
    events: int,
    n: int,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
) -> dict[str, float | int | str | None]:
    """Return a Wilson score interval using the explicit analytic formula.

    For :math:`p = x/n` and the two-sided normal quantile ``z``, the center is
    ``(p + z**2/(2*n)) / (1 + z**2/n)`` and the half-width is
    ``z/(1 + z**2/n) * sqrt(p*(1-p)/n + z**2/(4*n**2))``.
    An empty denominator has no estimand and therefore returns ``None`` for the
    estimate and interval endpoints.
    """

    events_value, n_value = _validate_binomial_counts(events, n)
    confidence = _validate_confidence_level(confidence_level)
    alpha = 1.0 - confidence
    z = float(norm.ppf(1.0 - alpha / 2.0))

    if n_value == 0:
        return {
            "estimate": None,
            "lower": None,
            "upper": None,
            "method": "Wilson score",
            "confidence_level": confidence,
            "z": z,
        }

    proportion = events_value / n_value
    z_squared = z * z
    denominator = 1.0 + z_squared / n_value
    center = (proportion + z_squared / (2.0 * n_value)) / denominator
    half_width = (
        z
        / denominator
        * math.sqrt(
            proportion * (1.0 - proportion) / n_value
            + z_squared / (4.0 * n_value * n_value)
        )
    )

    lower = float(max(0.0, center - half_width))
    upper = float(min(1.0, center + half_width))
    if abs(lower) < 1e-15:
        lower = 0.0
    if abs(upper - 1.0) < 1e-15:
        upper = 1.0
    return {
        "estimate": float(proportion),
        "lower": lower,
        "upper": upper,
        "method": "Wilson score",
        "confidence_level": confidence,
        "z": z,
    }


def clopper_pearson_interval(
    events: int,
    n: int,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
) -> dict[str, float | int | str | None]:
    """Return the two-sided exact Clopper-Pearson interval via Beta quantiles."""

    events_value, n_value = _validate_binomial_counts(events, n)
    confidence = _validate_confidence_level(confidence_level)
    alpha = 1.0 - confidence

    if n_value == 0:
        estimate: float | None = None
        lower: float | None = None
        upper: float | None = None
    else:
        estimate = events_value / n_value
        lower = (
            0.0
            if events_value == 0
            else float(beta.ppf(alpha / 2.0, events_value, n_value - events_value + 1))
        )
        upper = (
            1.0
            if events_value == n_value
            else float(
                beta.ppf(
                    1.0 - alpha / 2.0,
                    events_value + 1,
                    n_value - events_value,
                )
            )
        )

    return {
        "estimate": estimate,
        "lower": lower,
        "upper": upper,
        "method": "Clopper-Pearson exact (Beta quantiles)",
        "confidence_level": confidence,
    }


def proportion_summary(
    events: int,
    n: int,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
) -> dict[str, object]:
    """Summarize a binomial proportion and its SAP-required intervals.

    Clopper-Pearson is included as an extreme-count sensitivity interval only
    when ``events`` is zero or equals a positive ``n``.
    """

    events_value, n_value = _validate_binomial_counts(events, n)
    confidence = _validate_confidence_level(confidence_level)
    wilson = wilson_interval(events_value, n_value, confidence)
    exact = (
        clopper_pearson_interval(events_value, n_value, confidence)
        if n_value > 0 and events_value in (0, n_value)
        else None
    )
    return {
        "events": events_value,
        "n": n_value,
        "proportion": None if n_value == 0 else float(events_value / n_value),
        "wilson": wilson,
        "clopper_pearson": exact,
    }


def numeric_summary(values: Sequence[float]) -> dict[str, float | int | str | None]:
    """Return descriptive statistics using NumPy's linear quantiles.

    ``sample_sd`` uses ``ddof=1`` and is undefined for ``n < 2``. All numeric
    fields except ``n`` are undefined for ``n = 0``. For ``n = 1``, the sole
    observed value is reported for location and extrema; ``sample_sd`` and
    ``iqr`` remain ``None`` under the SAP's degenerate-case rule.
    """

    array = _finite_numeric_array(values, "values")
    n_value = int(array.size)
    if n_value == 0:
        return {
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

    q1, median, q3 = np.quantile(
        array, [0.25, 0.50, 0.75], method="linear"
    ).tolist()
    return {
        "n": n_value,
        "mean": float(np.mean(array)),
        "sample_sd": None if n_value == 1 else float(np.std(array, ddof=1)),
        "median": float(median),
        "q1": float(q1),
        "q3": float(q3),
        "iqr": None if n_value == 1 else float(q3 - q1),
        "min": float(np.min(array)),
        "max": float(np.max(array)),
        "quantile_method": "NumPy linear",
    }


def _resolve_statistic(
    statistic: str | Callable[[np.ndarray], float],
) -> tuple[Callable[[np.ndarray], float], str]:
    if statistic == "mean":
        return lambda sample: float(np.mean(sample)), "mean"
    if statistic == "median":
        return lambda sample: float(np.median(sample)), "median"
    if callable(statistic):
        name = getattr(statistic, "__name__", "callable")

        def checked_statistic(sample: np.ndarray) -> float:
            value = float(statistic(sample))
            if not math.isfinite(value):
                raise ValueError("statistic must return a finite scalar")
            return value

        return checked_statistic, str(name)
    raise ValueError("statistic must be 'mean', 'median', or a callable")


def _percentile_bootstrap_bounds(
    array: np.ndarray,
    statistic_function: Callable[[np.ndarray], float],
    statistic_name: str,
    confidence_level: float,
    n_resamples: int,
    seed: int,
) -> tuple[float, float]:
    """Compute a deterministic percentile fallback with paired index draws."""

    generator = np.random.default_rng(seed)
    bootstrap_statistics = np.empty(n_resamples, dtype=float)
    batch_size = min(1_000, n_resamples)

    for start in range(0, n_resamples, batch_size):
        stop = min(start + batch_size, n_resamples)
        indices = generator.integers(
            0, array.size, size=(stop - start, array.size), endpoint=False
        )
        samples = array[indices]
        if statistic_name == "mean":
            bootstrap_statistics[start:stop] = np.mean(samples, axis=1)
        elif statistic_name == "median":
            bootstrap_statistics[start:stop] = np.median(samples, axis=1)
        else:
            bootstrap_statistics[start:stop] = np.asarray(
                [statistic_function(sample) for sample in samples], dtype=float
            )

    if not np.all(np.isfinite(bootstrap_statistics)):
        raise ValueError("bootstrap statistic produced a non-finite value")

    alpha = 1.0 - confidence_level
    lower, upper = np.quantile(
        bootstrap_statistics,
        [alpha / 2.0, 1.0 - alpha / 2.0],
        method="linear",
    ).tolist()
    return float(lower), float(upper)


def bootstrap_ci(
    values: Sequence[float],
    statistic: str | Callable[[np.ndarray], float] = "mean",
    *,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    n_resamples: int = DEFAULT_BOOTSTRAP_REPLICATES,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> dict[str, float | int | str | None]:
    """Return a reproducible scalar bootstrap confidence interval.

    SciPy BCa is attempted first. A singleton is reported without an
    inferential interval, as required by the SAP. For a degenerate jackknife,
    a SciPy error, or non-finite BCa endpoints with at least two observations,
    an explicit percentile bootstrap is used with the same configured seed
    and replicate count. Empty samples have no estimand and are reported as
    ``method='undefined'`` without resampling.
    """

    array = _finite_numeric_array(values, "values")
    confidence = _validate_confidence_level(confidence_level)
    resamples, seed_value = _validate_bootstrap_configuration(n_resamples, seed)
    statistic_function, statistic_name = _resolve_statistic(statistic)

    if array.size == 0:
        return {
            "estimate": None,
            "lower": None,
            "upper": None,
            "method": "undefined",
            "implementation": None,
            "statistic": statistic_name,
            "confidence_level": confidence,
            "replicates": resamples,
            "seed": seed_value,
            "fallback_reason": "empty sample has no estimand",
        }

    estimate = float(statistic_function(array))
    if not math.isfinite(estimate):
        raise ValueError("statistic must return a finite scalar")

    if array.size == 1:
        return {
            "estimate": estimate,
            "lower": None,
            "upper": None,
            "method": "undefined",
            "implementation": None,
            "statistic": statistic_name,
            "confidence_level": confidence,
            "replicates": resamples,
            "seed": seed_value,
            "fallback_reason": "singleton sample has no inferential interval under the SAP",
        }

    fallback_reason: str | None = None
    if array.size >= 2:
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                result = scipy_bootstrap(
                    (array,),
                    statistic_function,
                    vectorized=False,
                    paired=False,
                    confidence_level=confidence,
                    n_resamples=resamples,
                    method="BCa",
                    rng=np.random.default_rng(seed_value),
                )
            lower = float(result.confidence_interval.low)
            upper = float(result.confidence_interval.high)
            if math.isfinite(lower) and math.isfinite(upper):
                return {
                    "estimate": estimate,
                    "lower": lower,
                    "upper": upper,
                    "method": "BCa",
                    "implementation": "scipy.stats.bootstrap",
                    "statistic": statistic_name,
                    "confidence_level": confidence,
                    "replicates": resamples,
                    "seed": seed_value,
                    "fallback_reason": None,
                }
            warning_text = "; ".join(str(item.message) for item in caught)
            fallback_reason = "BCa produced non-finite bounds"
            if warning_text:
                fallback_reason = f"{fallback_reason}: {warning_text}"
        except (FloatingPointError, RuntimeError, ValueError, ZeroDivisionError) as exc:
            fallback_reason = f"BCa failed: {type(exc).__name__}: {exc}"

    lower, upper = _percentile_bootstrap_bounds(
        array,
        statistic_function,
        statistic_name,
        confidence,
        resamples,
        seed_value,
    )
    return {
        "estimate": estimate,
        "lower": lower,
        "upper": upper,
        "method": "percentile",
        "implementation": "explicit NumPy paired-index resampling",
        "statistic": statistic_name,
        "confidence_level": confidence,
        "replicates": resamples,
        "seed": seed_value,
        "fallback_reason": fallback_reason,
    }


def paired_binary_table(
    first: Sequence[bool | int], second: Sequence[bool | int]
) -> dict[str, int]:
    """Return a paired 2x2 table, with keys interpreted as ``first, second``."""

    first_array = _binary_array(first, "first")
    second_array = _binary_array(second, "second")
    if first_array.size != second_array.size:
        raise ValueError("paired binary sequences must have equal length")

    return {
        "n": int(first_array.size),
        "00": int(np.sum((first_array == 0) & (second_array == 0))),
        "01": int(np.sum((first_array == 0) & (second_array == 1))),
        "10": int(np.sum((first_array == 1) & (second_array == 0))),
        "11": int(np.sum((first_array == 1) & (second_array == 1))),
    }


def mcnemar_exact_from_counts(n01: int, n10: int) -> dict[str, float | int | str]:
    """Run exact two-sided McNemar inference from discordant-pair counts."""

    n01_value = _validate_nonnegative_integer(n01, "n01")
    n10_value = _validate_nonnegative_integer(n10, "n10")
    discordant = n01_value + n10_value
    p_value = (
        1.0
        if discordant == 0
        else float(
            binomtest(
                k=n01_value,
                n=discordant,
                p=0.5,
                alternative="two-sided",
            ).pvalue
        )
    )
    return {
        "01": n01_value,
        "10": n10_value,
        "discordant": discordant,
        "p_value": p_value,
        "method": "exact McNemar via scipy.stats.binomtest",
        "alternative": "two-sided",
    }


def mcnemar_exact(
    first: Sequence[bool | int], second: Sequence[bool | int]
) -> dict[str, float | int | str]:
    """Build the complete paired table and run exact two-sided McNemar."""

    table = paired_binary_table(first, second)
    inference = mcnemar_exact_from_counts(table["01"], table["10"])
    return {
        **table,
        "discordant": inference["discordant"],
        "p_value": inference["p_value"],
        "method": inference["method"],
        "alternative": inference["alternative"],
    }


def exact_sign_test(
    differences: Sequence[float], *, zero_tolerance: float = 0.0
) -> dict[str, float | int | str]:
    """Run the exact two-sided sign test after excluding zero-valued ties."""

    array = _finite_numeric_array(differences, "differences")
    if isinstance(zero_tolerance, (bool, np.bool_)):
        raise TypeError("zero_tolerance must be numeric")
    try:
        tolerance = float(zero_tolerance)
    except (TypeError, ValueError) as exc:
        raise TypeError("zero_tolerance must be numeric") from exc
    if not math.isfinite(tolerance) or tolerance < 0.0:
        raise ValueError("zero_tolerance must be finite and non-negative")

    positives = int(np.sum(array > tolerance))
    negatives = int(np.sum(array < -tolerance))
    ties = int(array.size - positives - negatives)
    non_ties = positives + negatives
    p_value = (
        1.0
        if non_ties == 0
        else float(
            binomtest(
                k=positives,
                n=non_ties,
                p=0.5,
                alternative="two-sided",
            ).pvalue
        )
    )
    return {
        "positive": positives,
        "negative": negatives,
        "ties": ties,
        "non_ties": non_ties,
        "p_value": p_value,
        "method": "exact sign test via scipy.stats.binomtest",
        "alternative": "two-sided",
    }


def holm_adjust(
    p_values: Sequence[float], labels: Sequence[str] | None = None
) -> list[dict[str, float | int | str]]:
    """Apply Holm's step-down adjustment and expose every intermediate value.

    Rows are returned in ascending raw-p order (stable for ties).  ``order`` is
    the hypothesis' one-based position in the input, while ``rank`` is its
    one-based position after sorting by raw p-value.
    """

    try:
        raw_values = list(p_values)
    except TypeError as exc:
        raise TypeError("p_values must be a sequence") from exc

    converted: list[float] = []
    for index, raw_value in enumerate(raw_values):
        if isinstance(raw_value, (bool, np.bool_)):
            raise TypeError(f"p_values[{index}] must be numeric")
        try:
            p_value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"p_values[{index}] must be numeric") from exc
        if not math.isfinite(p_value) or not 0.0 <= p_value <= 1.0:
            raise ValueError(f"p_values[{index}] must be between 0 and 1")
        converted.append(p_value)

    if labels is None:
        label_values = [f"H{index + 1}" for index in range(len(converted))]
    else:
        label_values = list(labels)
        if len(label_values) != len(converted):
            raise ValueError("labels and p_values must have equal length")
        if not all(isinstance(label, str) for label in label_values):
            raise TypeError("every label must be a string")

    indexed = sorted(
        enumerate(zip(converted, label_values, strict=True)),
        key=lambda item: (item[1][0], item[0]),
    )
    family_size = len(indexed)
    running_maximum = 0.0
    rows: list[dict[str, float | int | str]] = []

    for zero_based_rank, (original_index, (p_raw, label)) in enumerate(indexed):
        rank = zero_based_rank + 1
        multiplier = family_size - zero_based_rank
        p_unbounded = p_raw * multiplier
        running_maximum = max(running_maximum, p_unbounded)
        adjusted = min(1.0, running_maximum)
        rows.append(
            {
                "label": label,
                "p_raw": p_raw,
                "order": original_index + 1,
                "rank": rank,
                "multiplier": multiplier,
                "p_unbounded": float(p_unbounded),
                "p_adjusted_monotonic": float(adjusted),
            }
        )
    return rows


def paired_proportion_difference(
    llm: Sequence[bool | int],
    dpca: Sequence[bool | int],
    *,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    n_resamples: int = DEFAULT_BOOTSTRAP_REPLICATES,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> dict[str, object]:
    """Estimate ``mean(LLM_i - DPCA_i)`` with paired-run bootstrap inference."""

    llm_array = _binary_array(llm, "llm")
    dpca_array = _binary_array(dpca, "dpca")
    if llm_array.size != dpca_array.size:
        raise ValueError("paired binary sequences must have equal length")

    differences = llm_array.astype(float) - dpca_array.astype(float)
    interval = bootstrap_ci(
        differences.tolist(),
        "mean",
        confidence_level=confidence_level,
        n_resamples=n_resamples,
        seed=seed,
    )
    interval["unit"] = "paired simulationRun"
    return {
        "n": int(llm_array.size),
        "llm_events": int(np.sum(llm_array)),
        "dpca_events": int(np.sum(dpca_array)),
        "difference": interval["estimate"],
        "confidence_interval": interval,
    }


def _optional_finite_number(value: float | None, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):
        raise TypeError(f"{name} must be numeric or None")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be numeric or None") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite or None")
    return number


def paired_delays(
    llm_delays: Sequence[float | None],
    dpca_delays: Sequence[float | None],
    *,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
    n_resamples: int = DEFAULT_BOOTSTRAP_REPLICATES,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> dict[str, object]:
    """Summarize paired delays without imputing absent endpoints.

    Only runs with both endpoints contribute to ``LLM - DPCA`` differences.
    Missing values remain missing and instead contribute to the explicit
    ``neither``, ``llm_only``, or ``dpca_only`` counts.
    """

    llm_values = list(llm_delays)
    dpca_values = list(dpca_delays)
    if len(llm_values) != len(dpca_values):
        raise ValueError("paired delay sequences must have equal length")

    total = len(llm_values)
    neither = 0
    llm_only = 0
    dpca_only = 0
    differences: list[float] = []

    for index, (llm_raw, dpca_raw) in enumerate(
        zip(llm_values, dpca_values, strict=True)
    ):
        llm_value = _optional_finite_number(llm_raw, f"llm_delays[{index}]")
        dpca_value = _optional_finite_number(dpca_raw, f"dpca_delays[{index}]")
        if llm_value is None and dpca_value is None:
            neither += 1
        elif llm_value is not None and dpca_value is None:
            llm_only += 1
        elif llm_value is None and dpca_value is not None:
            dpca_only += 1
        else:
            assert llm_value is not None and dpca_value is not None
            differences.append(llm_value - dpca_value)

    mean_interval = bootstrap_ci(
        differences,
        "mean",
        confidence_level=confidence_level,
        n_resamples=n_resamples,
        seed=seed,
    )
    mean_interval["unit"] = "paired simulationRun with both endpoints"
    median_interval = bootstrap_ci(
        differences,
        "median",
        confidence_level=confidence_level,
        n_resamples=n_resamples,
        seed=seed,
    )
    median_interval["unit"] = "paired simulationRun with both endpoints"

    return {
        "total": total,
        "neither": neither,
        "llm_only": llm_only,
        "dpca_only": dpca_only,
        "both": len(differences),
        "difference_direction": "LLM - DPCA",
        "difference_summary": numeric_summary(differences),
        "bootstrap_mean": mean_interval,
        "bootstrap_median": median_interval,
        "sign_test": exact_sign_test(differences),
    }

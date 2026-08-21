"""Named bootstrap façade for the independent Calculation 2 implementation."""

from statistics_independent import (
    DEFAULT_BOOTSTRAP_RESAMPLES,
    DEFAULT_BOOTSTRAP_SEED,
    bootstrap_interval,
    paired_bootstrap_interval,
)

__all__ = [
    "DEFAULT_BOOTSTRAP_RESAMPLES",
    "DEFAULT_BOOTSTRAP_SEED",
    "bootstrap_interval",
    "paired_bootstrap_interval",
]

# Local LLM + DPCA experiment infrastructure

Status: `DEVELOPMENT_ONLY`.

This directory contains the reproducible engineering layer for local, causal,
target-fault-blind TEP anomaly experiments. It does not freeze the scientific
protocol. Smoke and pilot configuration values are explicitly `PROVISIONAL`.

The inference container receives only blind process variables and causal time
metadata. Ground truth is mounted only in a separate evaluation invocation.
DPCA output is never included in the LLM payload.

Operational entry points live at the repository root under `scripts/`.
Documentation lives under `docs/`.

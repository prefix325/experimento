# Reproducibility memorial

This document is append-only. It records changes after the original METHOD FREEZE without rewriting that historical state.

## 2026-08-14 — monitor implementation worktree

- Base freeze commit: `c5ec02ecfff54845262238cd02558ea98f21b14d`.
- Base `formal.json` SHA-256: `921954a9b8b5822b096259ac7746beab2373200fe095c686740ba51f093a464c`.
- Original `formal.json` was not modified.
- The three-consecutive-ANOMALY rule was rejected before scientific execution.
- Methodological amendment 001 defines FIRST_INDICATION plus confirmation at the first FULL WINDOW REFRESH (`k+4`).
- Technical amendment 001 adds a localhost monitor, one-run batch adapter, persisted resume, stop controls, operational telemetry and isolated mock mode.
- The failed CPU-only technical acceptance is not converted into approval. GPU/offload/timeout remain pending.
- No scientific inference, formal execution, DPCA experiment, FaultFree Testing access or IDV(13) X access occurred during this implementation.
- Worktree changes remain uncommitted pending researcher review.

## 2026-08-15 — authoritative refreeze implementation

- Authoritative method: `TEP-METHOD-FREEZE-20260815-FULL-WINDOW-REFRESH`.
- Original freeze history and amendments were preserved; amendment 002 supersedes the LLM confirmation semantics only.
- `formal.json` refrozen SHA-256 before technical acceptance: `c8affff60f9e64af02698ef1b03a0ea4a2fdf07d8ef73d52de1e38bba7bf2a66`.
- Regression suite: 94 passed; PowerShell static parse passed; no real inference in tests.
- Single technical-acceptance attempt: FAIL before inference, `inference_count=0`; network-none PASS; GPU/offload evidence FAIL; no retry.
- Local gate remains `REAL START BLOCKED`; formal scientific execution did not start.
- No IDV(13) X or FaultFree Testing access occurred.

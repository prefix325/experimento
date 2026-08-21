# Frozen SAP analysis implementation

This directory contains the purpose-built, auditable implementation of the
formal campaign SAP at:

`repo/project/final_campaign/STATISTICAL_ANALYSIS_PLAN.md`

It does not import or consume the legacy aggregate output of `evaluation.py`.
The implementation reads only the final attempts selected by
`FINAL_CAMPAIGN_MANIFEST.json` and never writes below `results/` or `repo/`.

## Required execution order

From the export repository root:

```powershell
python analysis/formal/TEP-METHOD-FREEZE-20260815-FULL-WINDOW-REFRESH/code/run_frozen_sap_analysis.py --integrity-only
python -m pytest analysis/formal/TEP-METHOD-FREEZE-20260815-FULL-WINDOW-REFRESH/code/tests -q
python analysis/formal/TEP-METHOD-FREEZE-20260815-FULL-WINDOW-REFRESH/code/run_frozen_sap_analysis.py --full
```

The first command writes only `00_integrity/integrity_report.json` and
`00_integrity/denominator_table.csv`. If any authority, count, selection,
uniqueness, status, size, or hash gate fails, it exits before calculating an
aggregate statistic. `--full` independently repeats the same gate.

## Frozen semantics implemented

- Inferential and bootstrap unit: complete `simulationRun`.
- LLM confirmation: concurrent candidate-specific `k`/`k+4` full-window refresh,
  with pre/post-onset segmentation and no cross-onset confirmation.
- DPCA: raw alarm plus persistence 3 recomputed from `alarm_raw`, resetting the
  persistence counter at sample 161 for TARGET post-onset endpoints.
- Non-detection delays remain null.
- Proportions: Wilson 95%; boundary sensitivity: exact Clopper-Pearson.
- Paired binary endpoints: exact two-sided McNemar and run-paired bootstrap.
- Primary p-values: Holm adjustment across the two frozen confirmed contrasts.
- Delays: 10,000 run-level bootstrap replicates, base seed 20260820, BCa with a
  recorded percentile fallback when BCa is mathematically undefined.
- Paired delay sign test: exact two-sided, exact-zero ties reported/excluded.
- H3: frozen structured evidence rules, response-equal run scores, run-equal
  macro aggregation. `observation` is audit-only. Unsupported process claims
  remain unclassified because no frozen automatic codebook exists.

Each deterministic bootstrap interval initializes `numpy.default_rng` with the
exact frozen seed `20260820`. Analysis labels identify the statistic in audit
records but do not alter the seed.

## Tests

Synthetic tests cover Wilson, Clopper-Pearson, exact McNemar, Holm, paired
bootstrap, sign-test ties, the LLM `k`/`k+4` rule, onset reset, DPCA persistence,
H3 item/response/run aggregation, `n=0`, `n=1`, and null non-detection delays.
They do not access campaign results.

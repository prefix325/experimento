# Calculation 2 — independent implementation

This directory contains a clean-room implementation of the frozen TEP/LLM/DPCA
statistical analysis plan. It was created from the frozen source commit and does
not import the historical aggregation module or any prior analysis tree.

## Execution order

1. `integrity_independent.py` validates the repository, frozen authorities,
   selections, final attempts, manifests, sizes, hashes, JSONL schedules, and
   denominators. It writes only `00_integrity/` and aborts on any error.
2. `calculate_endpoints.py` reconstructs LLM and DPCA endpoints from the primary
   JSONL files, one `simulationRun` at a time.
3. `h3_independent.py` evaluates structured evidence against the frozen numeric
   thresholds for the same persisted window.
4. `run_calculation2.py` first materializes the run-level CSV, reloads that CSV,
   and only then produces aggregate statistics and audit files.

The primary inputs are read-only. LLM inference, DPCA fitting/inference, tuning,
threshold changes, endpoint changes, and historical-attempt pooling are absent.

## Reproduce

From the repository root:

```powershell
python -B analysis/validation/calculation2/TEP-METHOD-FREEZE-20260815-FULL-WINDOW-REFRESH/code/run_calculation2.py
python -B -m pytest analysis/validation/calculation2/TEP-METHOD-FREEZE-20260815-FULL-WINDOW-REFRESH/tests -q -p no:cacheprovider
```

The runner uses 10,000 bootstrap replicates and base seed `20260820`.

## Windows hash policy

The checkout converts tracked JSON and Markdown files from LF to CRLF while Git
reports a clean tree. Their declared frozen SHA-256 values therefore apply to
the canonical LF Git content. Primary `*.jsonl` files are marked `-text` and are
validated directly over raw filesystem bytes. Both raw checkout hashes and
canonical hashes are retained in the audit so any calculation-time mutation is
detectable.

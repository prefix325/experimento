# CALCULATION 2 audit

## Independence and source

- Source commit: `536cd4462b2fdc7e1bac8317adc64534e546c809`
- Branch: `validation/calculation2-independent-20260820`
- Prior-analysis contamination risk: `NO`
- Historical aggregation implementation imported: `NO`
- Prior analysis trees inspected: `NO`

## Frozen gates

- FINAL_CAMPAIGN_MANIFEST canonical SHA-256: `d3f7cdde04b18182a2fe25cc8ea23e07833a0c3ab9441403d9eb1b17dd028db5` — `PASS`
- SAP Git blob: `401c245f6b222e85662d8e47d4312ce27e8e8c60`
- SAP canonical SHA-256: `f5808362f57ed8ebc5b5548ec3d36270c9899deb93df7a9460fe1f6cbde29bfd` — `PASS`
- Primary JSONL: `1100` found; `0` hash mismatches
- Denominator gate: `PASS`

Tracked JSON/Markdown files use CRLF in this Windows checkout. Their frozen
digests were checked against explicitly normalized LF bytes, while raw checkout
hashes were retained and rechecked after calculation. Primary JSONL hashes were
checked directly over raw bytes.

## Reconstruction cross-checks

- LLM: `PASS` across `100` final runs; `detection_summary.json` used only as audit.
- DPCA: `PASS` across 1,000 full trajectories and 500 TARGET post-onset reset reconstructions.

## Statistical execution

- Aggregation source: `01_run_level/calculation2_run_level_endpoints.csv` only.
- Bootstrap: 10,000 run-level replicates, seed 20260820, BCa preferred with pre-specified percentile fallback.
- Multiplicity: the two primary McNemar p-values and the two secondary paired-delay sign-test p-values are Holm-adjusted in separate, explicitly labeled families.
- Tests: `synthetic suite executed separately before commit`.
- Inputs modified during calculation: `NO`.
- LLM inference executed: `NO`.
- DPCA inference/fitting executed: `NO`.

## Provenance limitations

Two JSONL files from non-final historical partial attempts are referenced by the
campaign manifest but are not materialized in this clone. They are not among the
1,100 final primary artifacts, were not used in performance calculations, and do
not alter the final-corpus integrity gate. The 768→1024 amendment output is
strictly descriptive provenance and contains no subgroup efficacy analysis.

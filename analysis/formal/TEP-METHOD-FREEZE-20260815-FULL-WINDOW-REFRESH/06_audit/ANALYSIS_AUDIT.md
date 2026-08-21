# Frozen SAP analysis audit

- Generated (UTC): `2026-08-21T02:16:24.255198+00:00`
- Source repository: `prefix325/experimento`
- Source main commit: `536cd4462b2fdc7e1bac8317adc64534e546c809`
- Analysis branch: `analysis/formal-sap-results-20260820`
- Method freeze: `TEP-METHOD-FREEZE-20260815-FULL-WINDOW-REFRESH`
- Final campaign manifest SHA-256: `d3f7cdde04b18182a2fe25cc8ea23e07833a0c3ab9441403d9eb1b17dd028db5`
- SAP Git blob: `401c245f6b222e85662d8e47d4312ce27e8e8c60`
- SAP canonical Git-blob SHA-256: `f5808362f57ed8ebc5b5548ec3d36270c9899deb93df7a9460fe1f6cbde29bfd`
- Six SAP-linked technical Git blobs: `PASS`
- Primary inputs rehashed before/after: `1,100 / 1,100`, zero mismatch
- Denominator gate: `PASS`
- Canonical run-level rows: `1,000`
- Bootstrap: `10,000` replicates, base seed `20260820`
- Inferential/resampling unit: complete `simulationRun`; paired runs remain indivisible
- LLM or DPCA scientific execution: `NO`
- Input result mutation: `NO`

The final Git commit SHA is reported by branch history and the delivery report;
it cannot be embedded inside the commit that determines that same SHA. The
internal code identity is the composite `analysis_code_sha256` in
`ANALYSIS_MANIFEST.json`.

The first materialized analysis output was the integrity report and denominator
table. Aggregate computation proceeded only after that gate passed. Historical
attempts were not combined with final scientific attempts. The documented
TARGET run150 outer-status anomaly is non-invalidating and the frozen scientific
classification (`LLM=NOT_REQUIRED`) was retained.

This directory contains estimates and audit artifacts only. It does not state an
article conclusion, create a retrospective threshold, or automatically accept or
reject H1/H2/H3.

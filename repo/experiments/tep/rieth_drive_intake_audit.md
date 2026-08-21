# Rieth TEP Drive intake audit

Status: `PROVISIONAL` / `PARTIALLY_DIRECTLY_AUDITED`.

## Files supplied for the active experiment

The researcher supplied three Harvard Dataverse V1 Rieth TEP files through Google Drive:

- `TEP_FaultFree_Training.RData` — 24,678,017 bytes — SHA-256 `12d1055b852763fac09ef36bd7c9612a800c8bf7b6f75f344d12119206f9e940`.
- `TEP_FaultFree_Testing.RData` — 47,327,663 bytes — SHA-256 `4f45afafa469793eeb7203fb9ed10ed0b1724c73c9c95537f15a0889ade0ebd4`.
- `TEP_Faulty_Testing.RData` — 836,882,037 bytes — visible and downloadable in Drive, but not downloaded into the current runtime because the connector imposes a 256 MiB raw-download ceiling.

The source dataset remains Rieth et al. (2017), Harvard Dataverse V1, DOI `10.7910/DVN/6C3JR1`.

## Direct schema checks completed

The two fault-free RData files were downloaded directly from the researcher-supplied Drive folder. Their R object names were verified as `fault_free_training` and `fault_free_testing`. Binary inspection also verified the canonical metadata names `faultNumber`, `simulationRun`, `sample` and the process-variable naming family from `xmeas_1` through `xmeas_41` and `xmv_1` through `xmv_11`.

Independent reproducibility code for the same Rieth dataset removes the first three columns and treats the remaining columns as the observation matrix. Accordingly, the active X contract retains all 52 process variables: 41 XMEAS plus 11 XMV. No target-informed feature selection is applied.

## X and y contract

`X` contains exactly all 52 process variables:

- `xmeas_1` ... `xmeas_41`;
- `xmv_1` ... `xmv_11`.

The following are metadata, not X: `faultNumber`, `simulationRun`, `sample`.

`y` is an evaluation-side binary target named `is_anomaly`:

- fault-free rows: `0`;
- IDV(13) testing rows with `sample <= 160`: `0`;
- IDV(13) testing rows with `sample >= 161`: `1`.

The pre-formal methodological decision is `fault_onset_sample = 161`: the source-derived index is 1..960, samples 1..160 are the 160 normal observations, and the fault is introduced after sample 160. The previous derived rule, `sample >= 160`, was an off-by-one and has been retained in provenance records rather than silently overwritten. `y`, `faultNumber`, and the IDV(13) identity are withheld from the LLM and DPCA in the primary target-fault-blind condition.

## Current engineering excerpt

A reproducible builder is versioned at `experiments/tep/scripts/build_rieth_idv13_excerpt.py`. The pilot defaults to simulation runs 1–10, retains every sample within those runs and retains all 52 X variables. It produces aligned `X`, `y`, metadata and a joined audit table.

The 1–10 run selection is an engineering pilot only. The final number/selection of independent runs remains a MECAI methodological decision and must not be interpreted as the final scientific sample.

## Remaining direct audit

The only source file not yet binary-audited inside the current runtime is `TEP_Faulty_Testing.RData`, due solely to the connector download-size ceiling. Before final experiment execution, its R object name, exact schema, missingness, IDV(13) run coverage and row counts must be directly validated by the builder or an equivalent controlled runtime.

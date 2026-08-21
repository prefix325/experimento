# Rieth TEP dataset intake

Status: `PROPOSED` / `PENDING_DIRECT_AUDIT`.

## Role in the research

The current researcher preference is to use a published, versioned benchmark dataset rather than generate new Tennessee Eastman Process simulations in MATLAB/Simulink. The primary dataset candidate is:

- Cory A. Rieth; Ben D. Amsel; Randy Tran; Maia B. Cook (2017), *Additional Tennessee Eastman Process Simulation Data for Anomaly Detection Evaluation*.
- Harvard Dataverse, Version 1.
- DOI: `10.7910/DVN/6C3JR1`.
- Focal fault for the present study: `IDV(13)`.

The previously inspected Ricker `idv13.zip` is retained as a historical/reference artifact and is not the current candidate for the primary experimental dataset.

## Expected structure to verify directly

Published secondary documentation of the Rieth dataset describes four R data files/objects separating fault-free/faulty and training/testing data. The tabular structure is reported as 55 columns: `faultNumber`, `simulationRun`, `sample`, plus 52 Tennessee Eastman process variables. Multiple independent simulation runs are provided, and fault labels are available for evaluation.

These details are not frozen by this note. Before the dataset contract is finalized, the Harvard Dataverse V1 files must be downloaded directly and audited for exact filenames, byte sizes, checksums, object names, row counts, column names, data types, missingness, sampling interval, run counts, and fault-onset convention.

## Experimental use proposed for IDV(13)

The detector input must remain target-fault-blind. The LLM and DPCA must not receive the `faultNumber`, IDV(13) name, fault description, onset label, or any feature selection derived from the target fault. Those fields may be retained outside the detector input for evaluation and provenance.

Normal runs are candidates for constructing the frozen normal reference. IDV(13) runs are candidates for causal progressive-window evaluation. Exact partitioning of runs, use of training versus testing subsets, window policy, DPCA fitting set, and leakage controls require MECAI methodological review before being frozen.

## MECAI review required

MECAI should evaluate and issue orientation on:

1. whether Rieth V1 is methodologically adequate as the primary benchmark for H1-H3;
2. which Rieth subset should provide the normal reference and which should provide the unseen IDV(13) evaluation trajectories;
3. how to avoid leakage from `faultNumber`, onset metadata, post-fault statistics, and target-informed feature selection;
4. whether all 52 process variables should be admitted to the primary condition or whether any exclusion is justified independently of IDV(13);
5. the number and selection of independent runs required for pilot and final evaluation;
6. the exact relationship between ground truth, DPCA alarm timing, and LLM detection timing.

No item in this file is `ACCEPTED`; this is an intake and routing record for the active `RESEARCH_FLOW`.

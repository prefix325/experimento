# Tennessee Eastman Process experiment workspace

Status: `PROVISIONAL`.

This directory holds the reproducibility layer for the TEP/IDV(13) study. Raw-source provenance, the experimental data contract, prepared datasets and scripts must remain separable.

Current source of interest:
- University of Washington / N. Lawrence Ricker Tennessee Eastman archive.
- IDV(13) package: `https://depts.washington.edu/control/LARRY/TE/IDVs/idv13.zip`.

Current methodological rule:
- The primary LLM condition is target-fault-blind.
- The LLM may receive process knowledge and normal-operation reference information.
- It must not receive the IDV(13) label/description, hidden simulator flags, fault-derived feature selection, post-fault reference data, or DPCA output in the primary condition.

No raw `.dat` file, archive content, dimensions, hashes or column ordering are considered frozen until the binary archive and official format documentation are directly audited.

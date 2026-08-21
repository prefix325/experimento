# IDV(13) data contract

Status: `PROPOSED`.

This file records the current data-use boundary for the first experiment. It is intentionally conservative until the official ZIP and format documentation are directly audited.

`y.dat` is treated as the primary candidate source for plant observations. It should provide the measured process variables used to assess whether the LLM can recognize departure from normal operation.

`u.dat` is treated as a candidate secondary source for manipulated/control variables. Whether these variables are exposed to the LLM in the primary condition remains an open methodological decision.

`r.dat` is preserved for reproducibility and controller-context analysis, but it is not part of the primary LLM input unless a later reviewed protocol explicitly admits it.

The primary LLM condition must not receive the IDV(13) label or description, the true fault-onset timestamp, hidden simulator flags or internal kinetic variables, post-fault information when constructing the normal reference, feature selection derived from IDV(13) labels or post-fault statistics, or DPCA outputs.

The normal reference must be frozen from pre-fault data before the evaluated fault trajectory. Converted CSV files may be created only after column order, sampling and file dimensions are verified from the source archive and its documentation. Raw source files remain immutable and every derived file must be reproducible from code.

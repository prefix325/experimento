# Representation contract

Status: `CONCEPTUALLY_FROZEN_CANDIDATE`. This is a pre-formal contract; `methodology_frozen` remains false.

The contract was fixed from the MECAI methodological decision and the current implementation. No LLM response, smoke/pilot outcome, or target-fault behavior was used to choose it. The machine-readable authority is `experiments/tep/local_llm/config/representation_contract.json`.

## Input and normal reference

The detector uses all 52 anonymized process variables, in the fixed order `xmeas_1..xmeas_41` followed by `xmv_1..xmv_11`. There is no feature selection. Every variable receives the same normalization and the same summary fields.

Normalization is fitted exclusively on all 250,000 rows of FaultFree Training (500 runs × 500 samples). For each variable, the code computes the arithmetic training mean and the sample standard deviation with `ddof=1`, then applies `z = (x - mean) / std`. A zero standard deviation is replaced by 1.0. FaultFree Testing and IDV13 do not participate in this fit.

## Causal window

Within each blind run, rows are sorted by ascending `sample`. Complete 20-sample windows are emitted at row starts 0, 5, 10, and so forth. Partial windows are not emitted. With the approved three-minute cadence, the window is nominally 60 minutes and a new evaluation occurs every 15 minutes. Precisely, the timestamp difference between the first and twentieth observations is 19 intervals, or 57 minutes; “60 minutes” denotes 20 sampled observations at a three-minute cadence.

The model receives only the three-minute sampling interval, the representation identifier, and the ordered summaries for all 52 variables. It does not receive `simulationRun`, `blind_run_id`, `window_id`, `sample_start`, `sample_end`, or another run/position identifier. The opaque run identifier and timing fields remain in the internal scientific record for logs, checkpoints, response association, evaluation, trajectory reconstruction, and audit.

## Per-variable statistics

For each variable, the current code sends:

- `variable`: anonymized identifier;
- `start_z`: first standardized value in the window;
- `end_z`: last standardized value in the window;
- `mean_z`: arithmetic mean of the 20 standardized values;
- `min_z`: minimum standardized value;
- `max_z`: maximum standardized value;
- `slope_z_per_sample`: OLS slope of standardized value against positions 0 through 19.

Every numeric statistic is converted to a Python float and rounded with `round(value, 4)`. No raw time series and no unstandardized X value are delivered. The payload is serialized with sorted JSON keys and Unicode preserved.

## Prompt envelope and withheld information

In addition to the payload, the prompt states only that the process is a generic multivariate industrial process, that the 52 variables are anonymized and normal-reference-standardized, that the allowed states are `NORMAL`, `EVIDENCE_INSUFFICIENT`, and `ANOMALY`, and that the model must not name a fault. It requires evidence to cite payload variable identifiers, to use one structured claim (`HIGH`, `LOW`, `INCREASE`, `REDUCTION`, or `VARIABILITY`), to conform to the JSON schema, and to keep `confidence: null`.

The payload excludes `faultNumber`, `simulationRun`, `blind_run_id`, `y`, the IDV identity and description, ground truth, DPCA/T²/SPE-Q outputs, future observations, raw unstandardized measurements, and absolute temporal position. The prompt supplies no TEP/Tennessee Eastman name, IDV designation, fault description, process topology, or variable semantics. The leakage validator fails closed on prohibited keys and text patterns.

## Alignment with current code

The current `Standardizer`, causal window generator, and `build_payload` implementation match this statistical contract. Window and stride are configuration values rather than hard-coded constants; the approved values are recorded in `formal.candidate.json`. The blocked `formal.json` was not changed.

Implementation hashes, exact field meanings, and the no-target-selection guarantees are recorded in the machine-readable contract.

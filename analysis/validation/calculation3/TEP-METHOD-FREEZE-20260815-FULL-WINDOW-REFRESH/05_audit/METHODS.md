# Calculation 3 methods

## Independent implementation

Calculation 3 used Python because `Rscript` was not available on PATH and the required Python libraries were already installed. Parsing and both ledgers use only `json`, `csv`, dictionaries, lists, and explicit per-`simulationRun` state. No pre-existing aggregate-analysis helper was imported.

The pipeline order was enforced as:

`primary JSONL -> event ledger -> run endpoint ledger -> statistics`

All H1/H2 and paired statistics were calculated from a readback of `01_ledgers/run_endpoint_ledger.csv`, never directly during JSONL traversal. Event-ledger rows are reconstructed scientific events: every raw-positive DPCA sample; every raw-positive LLM decision; and every LLM candidate-verification endpoint, including failed verification. Non-event DPCA samples are not emitted, but sample gaps deterministically expose streak resets.

## Frozen endpoint rules

- LLM: window width 20, stride 5, refresh `R=4`. Every eligible `ANOMALY` at `k` starts a concurrent candidate verified only at `k+4`. A target candidate must remain wholly pre-onset or wholly post-onset; state is reset at sample 161.
- DPCA: the raw event is the persisted `alarm_raw=true`. The numeric identity `(t2 > t2_limit) OR (spe > spe_limit)` is independently recomputed as a mandatory line-level cross-check. Confirmation is reconstructed as the third consecutive raw-positive sample. Target post-onset persistence starts at zero at sample 161.
- Delays are `(endpoint - 161) * 3` minutes. No event is `false` with a null delay.
- Quantiles use NumPy `method="linear"`.

## Proportion intervals

Wilson 95% intervals were implemented explicitly with `z = scipy.stats.norm.ppf(0.975)`:

`center = (p + z^2/(2n)) / (1 + z^2/n)`

`half = z/(1 + z^2/n) * sqrt(p(1-p)/n + z^2/(4n^2))`

At zero or all events, the Clopper-Pearson sensitivity interval uses exact Beta quantiles (`scipy.stats.beta.ppf`).

## Paired inference and multiplicity

Exact McNemar tests use only `01 + 10` discordances with `scipy.stats.binomtest(p=0.5, alternative="two-sided")`; zero discordances gives `p=1`. Paired proportion differences are the mean of per-run `LLM-DPCA` indicators and are bootstrapped by run pairs. Holm adjustment was implemented explicitly and records raw p, sort order, rank, multiplier, unbounded product, and monotone adjusted p.

Paired delay summaries include only runs with the same endpoint defined for both detectors. Exact sign tests exclude zero differences and use a two-sided binomial test on positive versus negative differences.

## Bootstrap

Bootstrap uses 10000 run-level resamples and seed 20260820. `scipy.stats.bootstrap(method="BCa")` is preferred. When BCa is mathematically undefined (for example a degenerate statistic), the pre-specified fallback is the percentile interval, with the reason stored beside the interval. `n=0` and `n=1` return no inferential interval.

## H3

H3 uses only `evaluation_contract.json`, `h3_evidence_reference.json`, and TARGET `llm_decisions.jsonl`. Variable correspondence must be exact, the variable must occur in the same payload, the frozen threshold must exist, and the claim must be one of HIGH, LOW, INCREASE, REDUCTION, or VARIABILITY. `observation` is never scored. Response, run, and macro aggregation follow the frozen SAP with equal weight by applicable run.

## Integrity and line endings

Primary JSONL artifacts were checked as exact raw bytes against their manifests. The Windows Git checkout converted some tracked JSON/Markdown metadata from LF to CRLF; those files were validated by deterministic CRLF-to-LF canonicalization and, for the SAP and final campaign manifest, directly against the Git blob bytes at `536cd4462b2fdc7e1bac8317adc64534e546c809`.

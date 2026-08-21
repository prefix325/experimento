# Experiment architecture

Status: `DEVELOPMENT_ONLY`; scientific protocol not frozen.

## Trust and data boundary

The downloaded workflow artifact is a preparation source and includes `y`.
Online preparation deterministically creates three physically separate roles:

- `data/normal/blind`: normal-reference metadata plus exactly 52 process variables;
- `data/test/blind`: neutral run IDs, causal sample index and exactly 52 variables;
- `data/test/ground_truth`: neutral ID, original run metadata and `y`, evaluator only.

The detector invocation mounts only the two blind directories and the model,
all read-only. The evaluation invocation runs later, without the model or blind
feature mounts, and receives ground truth read-only plus raw results. Results are
the sole read-write experiment volume.

## Detector separation

DPCA is fitted only on the normal reference. It emits T² and SPE/Q records to
`raw_dpca`. Its values are never passed to prompt construction or the LLM runtime.

The LLM receives a causal, configurable window representation with a neutral run
identifier. A fail-closed validator rejects prohibited keys and text before every
request. `llama.cpp` constrains output with JSON Schema. Each request records prompt
and model hashes, tokens, timestamps, latency, decision, evidence and summary.

## Offline evidence

Every detector run requires Docker `--network none`. Inside the container the
application attempts DNS resolution and external HTTPS access and requires both
to fail. It also verifies that normal data, test data and model mounts reject
writes while the results mount accepts writes. These checks are persisted under
the run's `logs` directory.

Host network disconnection remains an additional runbook control. The supported
claim is narrow: local inference without data externalization during the formal
run, evidenced by isolated mounts, no application network, failed probes, frozen
hashes and auditable logs.

## Provisional choices

Smoke/pilot currently use 20-sample windows, stride 5, summary-statistics
representation, Qwen2.5-7B-Instruct Q4_K_M, greedy decoding, two DPCA lags,
95% retained variance, 0.99 empirical limits and persistence 3. None is a final
scientific choice. `formal.json` remains fail-closed until those choices are
explicitly frozen.

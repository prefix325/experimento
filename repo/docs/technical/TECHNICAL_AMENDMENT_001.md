# Technical amendment 001 — process monitor and one-run batches

This amendment adds operational control without changing scientific model, prompt, representation, normalization, window, stride, run selection or DPCA parameters.

- `batch_size_runs = 1`
- `resume_unit = simulationRun COMPLETE`
- monitor bind: `127.0.0.1`
- default telemetry interval: 2 seconds
- disk state is authoritative
- mock mode is isolated and mandatory
- clean and forced stop semantics are persisted
- LLM and DPCA statuses remain separate

The one-run adapter calls the existing scientific pipeline by explicit cohort/detector/run ordinal. It does not implement scientific computations. Formal execution remains blocked by `formal.json`, missing successful technical acceptance and full preflight.

The failed CPU-only technical acceptance remains historical evidence. This amendment does not add `--gpus all`, change `n_gpu_layers`, change timeout, rebuild an image or approve a new acceptance. Those items require a distinct authorized post-freeze technical decision.

Machine-readable record: `experiments/tep/local_llm/config/post_freeze_technical_amendment_001.json`.

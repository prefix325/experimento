# TEP Formal Process Monitor runbook

Status: implementation conformance PASS; technical GPU acceptance FAIL; real scientific execution remains blocked.

## Architecture

```text
localhost UI (127.0.0.1)
        |
        v
monitor state/controller ----> operational telemetry
        |                       (never scientific input)
        v
one-run batch adapter
        |
        v
existing checkpointed scientific executor
        |
        v
Docker --network none ----> LLM and DPCA
```

The monitor does not implement prompts, representation, normalization, model calls, DPCA scoring, run selection or hypothesis evaluation. The reusable `tep_local.detection` module owns the amended TARGET early-stop state machine; the executor writes its events into internal records.

## Current gate state

The UI displays `REAL START BLOCKED`. The current blockers are:

- `TECHNICAL_ACCEPTANCE_PENDING_OR_FAILED`;
- `GPU_OFFLOAD_ACCEPTANCE_PENDING_OR_FAILED`;
- `LOCAL_EXECUTION_NOT_AUTHORIZED`.

`formal.json` keeps `scientific_execution_permitted=false`. Network-none acceptance passed independently, but does not override the GPU failure. The real start button is disabled. Mock mode remains available.

## Start the UI

From the repository root:

```powershell
.\scripts\run_formal_monitor.ps1
```

The server binds only to `http://127.0.0.1:8765`. It contains no CDN, analytics, remote fonts or internet dependency.

Double-clicking `START_PSQZA_FORMAL_MONITOR.bat` starts the localhost server, waits for `/api/state`, and opens the URL. It never invokes a detector or model by itself.

## Mock mode

Interactive mock:

```powershell
.\scripts\run_formal_monitor.ps1 -Mock -StateDirectory "$env:TEMP\MOCK_PSQZA_FORMAL_MONITOR"
```

Deterministic 50-run simulation without starting a server:

```powershell
.\scripts\run_formal_monitor.ps1 -Mock -SimulateOnly -StateDirectory "$env:TEMP\MOCK_PSQZA_FORMAL_MONITOR"
```

The selected mock state directory must have a basename beginning with `MOCK` and must not be under `results/formal`. Mock mode never opens datasets, a GGUF, llama-server or a formal manifest for writing.

## Persisted state and restart

Disk is authoritative. Each cohort/run has append-only attempt directories and only a valid completion condition creates `COMPLETE.json`. A stale `RUNNING` attempt is converted to `PARTIAL` on restart; the same simulationRun is then selected again from its beginning. COMPLETE runs are skipped.

The batch adapter accepts exactly one run ordinal, cohort and detector. The real plan contains 1,000 lots: all 500 TARGET and all 500 NORMAL HOLDOUT simulationRuns. Each lot requires DPCA; the 50 frozen LLM selections per cohort additionally require LLM. Scientific computation remains in `run_formal_batch_offline.ps1` and `tep_local.pipeline`; the monitor never resumes within an inference.

## Stop controls

- **PARAR APÓS ESTE LOTE**: sets `STOPPING`, lets the current batch reach a valid COMPLETE state, persists it, starts no next batch and records `STOPPED_CLEAN`.
- **PARAR AGORA**: requests controlled process/container termination, preserves existing logs, does not create COMPLETE, records `PARTIAL` or `ABORTED`, and sets `STOPPED_FORCED`.
- Abrupt shutdown recovery treats stale RUNNING state as interrupted and restarts that run from the beginning.

## Progress and ETA

Total progress is `COMPLETE batches / total batches`. Window progress is `current window / maximum possible windows`; 189 is a maximum for TARGET because confirmation may stop LLM early. ETA uses the median of up to the ten most recent COMPLETE batch durations. PARTIAL, ABORTED, FAILED and RUNNING attempts never enter ETA.

## Telemetry

Operational telemetry is written every configured refresh interval as JSONL and includes time, state, cohort, run, attempt, window progress, detection state, CPU/RAM/GPU and VRAM. It is explicitly marked `operational_only` and must never enter prompts, DPCA, or H1/H2/H3.

## Preconditions before future real use

Before enabling real start, a separately authorized post-freeze process must provide a committed amendment, rebuilt image and hashes, successful normal-only technical acceptance, scientific execution permission, and full commit/image/model/dataset/selection validation. GPU exposure/offload and request timeout remain unresolved by this monitor implementation.

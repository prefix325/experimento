# Codex prompt — implement amended freeze, technical acceptance and one-click monitor

Use this prompt in the local Codex workspace rooted at:

`X:\PSQZA_TEP_LOCAL\repo`

---

The scientific method has now passed the governed methodology gate.

AUTHORITATIVE METHOD FREEZE:

`TEP-METHOD-FREEZE-20260815-FULL-WINDOW-REFRESH`

Governance chain already approved:

- MECAI orientation: `mecai:tep:full-window-refresh:20260815T0046-0300`
- researcher decision: `APPROVED`
- research delta: `research-delta:tep-full-window-refresh:20260815T0051-0300` — `ADMITTED`
- BANCA: `banca:tep:full-window-refresh:20260815T0053-0300` — `PASS_WITH_WARNINGS`

Your task is now ENGINEERING CONFORMANCE, not scientific redesign.

ROOT:

`X:\PSQZA_TEP_LOCAL\repo`

Do not use the internet.
Do not push or merge.
Do not access the target/faulty dataset during implementation or technical acceptance.
Do not access FaultFree Testing during implementation or technical acceptance.
Do not start the formal scientific experiment automatically.
Do not run the 50 formal target runs during this task.
Do not tune any scientific rule from model output.
Do not change W, stride, model, prompt semantics, DPCA fitting/persistence, run selection, target onset or H1/H2/H3 meaning outside the frozen amendment.

You MAY modify the local implementation and its formal configuration/manifests as necessary to conform to the new freeze, because the previous freeze is superseded specifically for the confirmation/evaluation/early-stop semantics described below.

==================================================
0. PROTECT THE WORKSPACE
==================================================

First:

- print the current branch;
- run `git status --short`;
- identify any pre-existing uncommitted changes;
- do not overwrite unrelated user work;
- inspect before modifying.

Record the pre-change commit and working-tree state in the final report.

Do not delete historical results or old freeze manifests. New freeze/conformance evidence must be additive or clearly versioned.

==================================================
1. IMPLEMENT THE FROZEN CONFIRMATION MACHINE
==================================================

Frozen representation:

- W = 20 samples
- stride S = 5 samples
- causal timestamp = window endpoint
- R = ceil(W / S)
- therefore current R = 4 strides

IMPORTANT:

R must be DERIVED from W and S.
Do not create an independently tunable `confirmation_offset=4` scientific parameter.
If a cached/serialized derived value is useful technically, validate it against ceil(W/S) at load time and fail closed on mismatch.

Raw LLM output remains exactly categorical:

- NORMAL
- EVIDÊNCIA_INSUFICIENTE / existing canonical English enum if the code uses it
- ANOMALIA / existing canonical English enum if the code uses it

Do not add probability, confidence, logprob or anomaly score.

Candidate semantics:

Every eligible ANOMALIA may create a candidate.

Examples:

k   -> verify k+4
k+1 -> verify k+5
k+2 -> verify k+6
k+3 -> verify k+7

Candidates coexist.

FIRST_INDICATION:
first eligible post-onset raw ANOMALIA.

CONFIRMED_DETECTION:
first candidate whose own verification window k+R is also ANOMALIA.

If candidate k reaches k+R and output is not ANOMALIA:

- mark only candidate k as VERIFICATION_FAILED;
- do not cancel other pending candidates.

If k+R lies after trajectory end:

- VERIFICATION_INCOMPLETE_END_OF_TRAJECTORY for that candidate.

If no post-onset ANOMALIA:

- NO_FIRST_INDICATION
- NO_CONFIRMED_DETECTION

Never label k and k+4 statistically independent.
Use wording such as FULL_SAMPLE_REFRESH / FULL_WINDOW_REFRESH.

Likely files to inspect include, when present:

- experiments/tep/local_llm/src/tep_local/detection.py
- experiments/tep/local_llm/src/tep_local/evaluation.py
- experiments/tep/local_llm/src/tep_local/pipeline.py
- experiments/tep/local_llm/src/tep_local/checkpoint.py
- experiments/tep/local_llm/src/tep_local/cli.py
- scripts/common.ps1
- scripts/run_formal_batch_offline.ps1
- formal configuration/manifests
- tests associated with these components

Use actual repository structure if paths differ.

==================================================
2. ONSET / H1 / H2 / NORMAL FALSE ALARMS
==================================================

Evaluator-only onset remains sample 161.
The LLM must never receive onset, target identity or ground truth.

Pre-onset candidate state cannot cross the onset boundary.
Reset evaluator confirmation candidates at onset.

Pre-onset ANOMALIA remains false indication.

Delay formula:

`delay_minutes = (decision_sample - 161) * 3`

Preserve separately:

- first_indication_delay
- confirmed_detection_delay

H1 must preserve both:

- FIRST_INDICATION incidence
- CONFIRMED_DETECTION incidence

Normal controls:

- no LLM early stop;
- full trajectory;
- same candidate machine for confirmed false alarms;
- record at minimum:
  - raw_anomaly_window_rate
  - raw_false_alarm_run_incidence
  - confirmed_false_alarm_run_incidence
  - time_to_first_confirmed_false_alarm when present

Do not invent an alarm-episode clustering rule.

==================================================
3. PRESERVE DPCA
==================================================

Do NOT refit or alter frozen DPCA semantics.

Frozen DPCA remains:

- lags = 5
- augmented dimension = 312
- PCs = 150
- T² limit = 196.83346394039964
- SPE/Q limit = 27.09260011679274
- persistence = 3 consecutive exceedances

LLM early stop must NOT stop required DPCA processing.

Primary reporting must preserve:

- raw detector layer
- native operational-system layer

Do not add a common confirmation layer as primary analysis.

==================================================
4. H3
==================================================

Preserve H3 as PROCESS-EVIDENCE GROUNDEDNESS.

Do not call it internal causal faithfulness.

The evaluator may deterministically check whether:

- cited variable exists;
- cited direction/trend is supported;
- cited deviation/magnitude is compatible with supplied representation;
- unsupported process claims occur.

Do not use target outcomes to tune H3 thresholds or rules.

==================================================
5. COMPUTE-SAVING EARLY STOP
==================================================

TARGET LLM:

Early stop is permitted only after first CONFIRMED_DETECTION has been fully written to durable output together with all required raw outputs/evidence for:

- FIRST_INDICATION;
- confirmation horizon.

Do NOT early-stop on:

- FIRST_INDICATION alone;
- a pending candidate;
- VERIFICATION_FAILED;
- VERIFICATION_INCOMPLETE_END_OF_TRAJECTORY.

NORMAL LLM:

Never early-stop because of confirmation.

DPCA:

Continue required trajectory independently.

==================================================
6. COMPONENT COMPLETION / DURABLE RESUME
==================================================

Audit and implement explicit or semantically equivalent component states:

- llm_status
- dpca_status
- lot_status

Overall COMPLETE is valid only when all scientific components required for that lot are complete.

A confirmed LLM early stop may make the LLM component complete.
It must NOT make the whole lot COMPLETE while required DPCA output is incomplete.

Preserve durable resume:

- COMPLETE on disk is source of truth;
- COMPLETE.json remains immutable after successful completion;
- orphan RUNNING becomes PARTIAL/recoverable;
- PARTIAL/ABORTED/FAILED work is rerun safely according to existing controller policy;
- an abrupt shutdown must not invalidate already complete runs;
- do not infer completion from UI memory alone.

==================================================
7. TESTS — NO REAL LLM INFERENCE YET
==================================================

Before technical acceptance, execute only unit/integration/MOCK/synthetic tests.

Add regression coverage for at least:

1. R derived from W/S = 4.
2. k ANOMALIA + k+4 ANOMALIA -> confirmation.
3. k ANOMALIA + k+4 NORMAL -> only candidate k fails.
4. k and k+1 both start candidates and remain concurrent.
5. k fails but k+1 later confirms.
6. end-of-trajectory incomplete candidate.
7. no indication.
8. pre-onset candidate cannot cross onset.
9. FIRST_INDICATION and CONFIRMED_DETECTION are separate.
10. both H2 delays are correct.
11. normal trajectory never confirmation-early-stops.
12. target LLM early-stops only after confirmation.
13. DPCA continues after LLM early stop.
14. lot cannot become COMPLETE while DPCA required/incomplete.
15. COMPLETE survives controller restart.
16. orphan RUNNING recovery.
17. Stop After Current.
18. Stop Now leaves non-COMPLETE recoverable state.

Use synthetic fixtures only for the new confirmation-state tests.

Do not access FaultFree Testing or target data merely to test code paths.

==================================================
8. FORMAL CONFIG / RE-FREEZE LOCAL IMPLEMENTATION
==================================================

Inspect the current formal configuration and manifests.

If `formal.json` or equivalent encodes the superseded three-consecutive-overlapping-window LLM rule, update it to conform to the new method freeze.

Requirements:

- preserve all unrelated frozen values;
- version the confirmation policy explicitly;
- encode full-sample-refresh semantics rather than a tunable arbitrary offset;
- preserve previous historical manifests/results;
- recompute affected hashes/manifests after changes;
- create a new local implementation-conformance/freeze manifest containing:
  - source Git commit/diff identity;
  - hashes of changed formal files;
  - W, S and derived R;
  - model hash;
  - representation/evaluation contract hashes;
  - DPCA reference hashes;
  - confirmation policy id;
  - early-stop policy id;
  - lot-completion policy id;
  - test results;
  - ZERO_NEW_LLM_INFERENCE up to this point.

Do not represent the local implementation as conformant unless the regression suite passes.

==================================================
9. MONITOR / ONE-CLICK WINDOWS LAUNCHER
==================================================

Inspect the existing monitor first.

Expected existing elements may include:

- tools/formal_monitor/
- scripts/run_formal_monitor.ps1
- scripts/run_formal_batch_offline.ps1

Preserve the current architecture if it already works.
Do not rebuild a parallel monitor unnecessarily.

The UI must show at minimum:

- overall run progress;
- current simulationRun;
- current window progress where applicable;
- elapsed time;
- ETA;
- CPU;
- RAM;
- GPU;
- VRAM;
- LLM component status;
- DPCA component status;
- lot status;
- current gate state;
- Start/Resume;
- Stop After Current;
- Stop Now.

If the existing UI supports a bounded session-run count, preserve it. If not and it can be added without changing scientific semantics, add a technical `runs_this_session` control with a convenient default of 5 so the machine can process a small batch and stop cleanly. This is a controller convenience only and must not change the frozen 50-run scientific selection or results.

Create or repair exactly this root launcher:

`X:\PSQZA_TEP_LOCAL\repo\START_PSQZA_FORMAL_MONITOR.bat`

The BAT must:

- locate ROOT with `%~dp0`;
- `cd /d` to ROOT;
- invoke PowerShell `-NoProfile`;
- use process-local `ExecutionPolicy Bypass` only if needed;
- start `scripts\run_formal_monitor.ps1` or the canonical monitor launcher;
- wait until `127.0.0.1:8765` responds;
- open `http://127.0.0.1:8765` in the default browser;
- NOT start inference automatically;
- display a clear error and `pause` on startup failure;
- require no Internet/CDN/external service.

Double-clicking the BAT must only open the monitor.

==================================================
10. GATE MODEL
==================================================

The UI/controller must expose or derive these gates:

- methodological_gate = PASS
- implementation_conformance = PASS/FAIL
- technical_acceptance = PASS/FAIL/PENDING
- gpu_offload_acceptance = PASS/FAIL/PENDING
- scientific_execution_authorized = true only when all required gates pass

Before technical acceptance passes:

`REAL START BLOCKED`

The monitor may still launch and MOCK may still run.

Do not enable REAL merely because the method freeze exists.

==================================================
11. POST-FREEZE TECHNICAL ACCEPTANCE — ONE SAFE INFERENCE
==================================================

After all implementation/MOCK tests pass, execute ONE bounded technical-acceptance LLM inference.

This is not scientific inference.

Input must be a fixed synthetic 52-variable normal-like representation created specifically for technical acceptance.
Do not derive it from FaultFree Testing or the target dataset.
Do not inspect either dataset.

The acceptance must exercise the actual formal container/runtime path as closely as possible.

The real Docker command must include:

- GPU exposure: `--gpus all` (or exact equivalent proving NVIDIA GPU availability);
- `--network none`;
- model mounted read-only;
- acceptance input/code mounted read-only where applicable;
- only the acceptance result/log destination writable.

Capture the exact docker command.

Capture llama.cpp startup/runtime logs sufficient to establish:

- CUDA backend discovered;
- NVIDIA GPU identified;
- model layers actually offloaded to GPU;
- inference completed;
- output parsed according to the existing categorical JSON/output contract;
- measured elapsed time and throughput.

Fail closed if GPU initialization/offload is not observed.
Do not silently fall back to CPU.

If GPU/offload is not visible shortly after initialization, terminate the acceptance rather than allowing an hours-long CPU run.

Use one model inference only for this acceptance. Do not retry with changed prompts/parameters if it fails. Report failure and stop.

A reasonable hard timeout may remain as a safety ceiling, but the acceptance should use early GPU-detection failure so CPU fallback is caught before the full timeout.

Acceptance result directory should be a new timestamped path under the existing technical-acceptance results convention.

Record a machine-readable PASS/FAIL artifact including:

- exact docker command;
- container/image identity;
- model hash;
- network mode;
- GPU identity;
- offloaded layer evidence;
- elapsed time;
- prompt/input hash;
- output hash;
- parser result;
- ZERO_TARGET_ACCESS;
- ZERO_FAULTFREE_TESTING_ACCESS;
- inference_count = 1;
- acceptance verdict.

==================================================
12. ENABLE REAL START ONLY AFTER PASS
==================================================

If and only if ALL of the following are true:

- implementation regression suite PASS;
- method/config conformance PASS;
- technical acceptance PASS;
- CUDA/GPU offload PASS;
- offline/network-none acceptance PASS;
- durable monitor/controller tests PASS;

then update the LOCAL gate state so the monitor can show:

`REAL START READY`

Do NOT press Start.
Do NOT initiate the formal target/normal runs.

The user must still initiate the formal execution by clicking Start/Resume in the monitor.

If any gate fails, leave:

`REAL START BLOCKED`

and report the exact blocker.

==================================================
13. FINAL OUTPUT
==================================================

Return a structured report with:

1. IMPLEMENTATION SUMMARY
2. CHANGED FILES
3. CURRENT vs FROZEN METHOD CONFORMANCE MATRIX
4. REGRESSION TEST RESULTS
5. FORMAL CONFIG / NEW LOCAL FREEZE MANIFEST
6. MONITOR STATUS
7. exact launcher path:
   `X:\PSQZA_TEP_LOCAL\repo\START_PSQZA_FORMAL_MONITOR.bat`
8. final BAT contents
9. monitor URL
10. TECHNICAL ACCEPTANCE RESULT
11. exact Docker command used
12. CUDA/GPU/offload evidence
13. elapsed time / throughput
14. FINAL GATE TABLE
15. NO-UNAUTHORIZED-EXECUTION ATTESTATION

The attestation must state:

- implementation_completed=true/false
- ZERO_NEW_LLM_INFERENCE_BEFORE_ACCEPTANCE=true/false
- technical_acceptance_inference_count=<integer>
- target_dataset_accessed=true/false
- faultfree_testing_accessed=true/false
- formal_scientific_execution_started=true/false
- gpu_offload_observed=true/false
- network_none_observed=true/false
- real_start_ready=true/false
- formal_runs_started=true/false
- files_modified=true/false
- git_commit_created=true/false
- git_push_performed=true/false

Success for this task means:

- code conforms to the amended freeze;
- monitor opens by one BAT click;
- one safe technical acceptance proves actual GPU/offline execution;
- REAL START is ready but the formal experiment has NOT started.

---

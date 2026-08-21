# File inventory

This inventory is append-only and lists the process-monitor addition relative to METHOD FREEZE commit `c5ec02ecfff54845262238cd02558ea98f21b14d`.

## Post-freeze amendments

- `experiments/tep/local_llm/config/post_freeze_methodological_amendment_001.json`
- `experiments/tep/local_llm/config/post_freeze_technical_amendment_001.json`
- `experiments/tep/local_llm/config/post_freeze_methodological_amendment_002.json`
- `experiments/tep/local_llm/config/post_freeze_technical_amendment_002.json`
- `docs/technical/METHODOLOGICAL_AMENDMENT_001.md`
- `docs/technical/TECHNICAL_AMENDMENT_001.md`
- `docs/technical/METHODOLOGICAL_AMENDMENT_002.md`
- `docs/technical/TECHNICAL_AMENDMENT_002.md`

## Scientific executor support

- `experiments/tep/local_llm/src/tep_local/detection.py` — single authoritative full-window-refresh state machine.
- `experiments/tep/local_llm/src/tep_local/amendments.py` — fail-closed amendment validation.
- `experiments/tep/local_llm/src/tep_local/pipeline.py` — consumes the amendment; early stop only for TARGET LLM.
- `experiments/tep/local_llm/src/tep_local/evaluation.py` — evaluates TARGET with the amendment and normal holdout over its full trajectory.
- `experiments/tep/local_llm/src/tep_local/cli.py` — explicit amendment, detector and DPCA batch arguments.
- `experiments/tep/local_llm/src/tep_local/checkpoint.py` — amendment hash joins the resume contract.
- `scripts/run_formal_batch_offline.ps1` — gated single detector/cohort/run adapter.
- `scripts/common.ps1` — passes the methodological amendment to future formal detector calls.
- `experiments/tep/local_llm/src/tep_local/confirmation_evaluation.py` — H1/H2 and normal false-alarm evaluation using the concurrent candidate machine.
- `experiments/tep/local_llm/src/tep_local/technical_acceptance.py` — fixed synthetic 52-variable, network-none, GPU-required acceptance.

## Monitor

- `tools/formal_monitor/monitor.py`
- `tools/formal_monitor/state.py`
- `tools/formal_monitor/process_control.py`
- `tools/formal_monitor/resource_monitor.py`
- `tools/formal_monitor/eta.py`
- `tools/formal_monitor/mock_mode.py`
- `tools/formal_monitor/real_mode.py` — click-triggered 1,000-lot plan; no automatic scientific start.
- `tools/formal_monitor/gates.py` — fail-closed live gate derivation.
- `tools/formal_monitor/templates/index.html`
- `tools/formal_monitor/static/style.css`
- `tools/formal_monitor/static/app.js`
- `scripts/run_formal_monitor.ps1`
- `scripts/run_post_refreeze_technical_acceptance.ps1`
- `START_PSQZA_FORMAL_MONITOR.bat`
- `docs/technical/MONITOR_RUNBOOK.md`

## Tests

- `experiments/tep/local_llm/tests/test_full_window_refresh.py`
- `experiments/tep/local_llm/tests/test_evaluation_contract.py`
- `tools/formal_monitor/tests/test_monitor.py`
- `experiments/tep/local_llm/tests/test_synthetic_acceptance.py`

## External additive evidence

- `X:/PSQZA_TEP_LOCAL/manifests/method_refreeze_implementation_conformance_20260815_pre_acceptance.json`
- `X:/PSQZA_TEP_LOCAL/manifests/method_refreeze_implementation_conformance_20260815.json`
- `X:/PSQZA_TEP_LOCAL/results/technical_acceptance/post-refreeze-synthetic-gpu-acceptance-20260815T045357Z/`

Mock-generated state and telemetry live only in explicitly marked temporary `MOCK*` directories and are not scientific artifacts.

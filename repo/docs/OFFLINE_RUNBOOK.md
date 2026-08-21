# Formal offline runbook

Status: pre-freeze candidate only. Do not execute this runbook until a researcher
has copied an approved candidate to `formal.json`, set both freeze gates to true,
and independently verified every recorded hash.

## Required preflight

1. Confirm Docker Desktop is healthy and `X:\PSQZA_TEP_LOCAL` is available.
2. Disable Wi-Fi, Ethernet, VPNs, and all other external routes.
3. Verify the approved Git commit, dataset hashes, model hash, image digest,
   `formal.json`, prompt, schema, representation contract, evaluation contract,
   both LLM run selections, DPCA reference/model, and H3 reference.
4. Confirm `methodology_frozen=true` and
   `scientific_execution_permitted=true`. The candidate deliberately has both
   gates false and must abort.
5. Record the immutable Docker image digest in `DOCKER_IMAGE_DIGEST`.

## Start and manual blocks

After formal authorization, the wrapper remains the authoritative entry point:

    Set-Location X:\PSQZA_TEP_LOCAL\repo
    .\scripts\run_formal_offline.ps1

The wrapper accepts `-RunBlock` with one-based ordinals within each frozen
50-run LLM selection, for example:

    .\scripts\run_formal_offline.ps1 -RunBlock '1-10'

A block changes only which selected LLM runs are attempted in each cohort.
`formal_run_selection.json` controls LLM target (seed 42; 50 of runs 11..500),
and `formal_normal_holdout_selection.json` controls LLM normal-holdout (seed 43;
50 of runs 1..500). DPCA independently evaluates all 500 target runs and all
500 normal-holdout runs, resuming only those not already complete.

## Checkpoint layout and interruption

DPCA and LLM checkpoints are separate:

- `results/formal/<experiment-id>/<cohort>/dpca/runs/<blind_id>/attempts/NNNN/`
- `results/formal/<experiment-id>/<cohort>/llm/runs/<blind_id>/attempts/NNNN/`

Here, `<cohort>` is `target` or `normal_holdout`.

Each attempt begins as `PARTIAL`. On failure it becomes `FAILED`; a later resume
creates a new numbered attempt and preserves the earlier directory. A successful
attempt writes its artifact, hashes and sizes it in `run_manifest.json`, and
writes `COMPLETE.json` last. Completed runs are immutable.

To interrupt, stop the foreground process normally (Ctrl+C). Do not edit or
delete partial attempts. On restart, use the exact same approved configuration,
model, image, prompt, schema, contracts, selection, DPCA reference/model, and H3
reference. Any hash mismatch aborts resume. The pipeline validates every
completed manifest and artifact before skipping it.

Resume into the exact directory printed by the first invocation:

    .\scripts\run_formal_offline.ps1 -RunBlock '11-20' -ResultsDirectory 'X:\PSQZA_TEP_LOCAL\results\formal\<experiment-id>'

The wrapper rejects a resume directory outside `results\formal`. It creates
separate `target` and `normal_holdout` roots and does not invoke evaluation until
both detector cohorts have valid completion markers.

`checkpoint_summary.json` reports completed and remaining counts separately for
DPCA/500 and LLM/50. `detectors_complete.json` is created only when both cohorts
are complete. Evaluation must read only artifacts protected by valid COMPLETE
markers.

The formal wrapper performs no download, installation, package update, GitHub
access, or online version check. Every application container must use
`--network none`. Re-enable connectivity only after all experiment containers
have stopped and outputs have been archived.

## Post-freeze technical acceptance

This is a separate, non-scientific command and must not be run until the
researcher explicitly authorizes the post-freeze technical gate:

    .\scripts\run_post_freeze_technical_acceptance.ps1 -ResearcherAuthorized

It performs exactly one inference on a deterministic causal window from
FaultFree Training. It never mounts FaultFree Testing or IDV(13), does not
release `scientific_execution_permitted`, and may only validate startup, frozen
hashes, network/mount isolation, schema-conforming JSON, and the claim enum.
Its response must not be used to change methodology.

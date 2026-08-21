# Methodological amendment 001 — full-window refresh confirmation

Base METHOD FREEZE: `c5ec02ecfff54845262238cd02558ea98f21b14d`  
Base `formal.json` SHA-256: `921954a9b8b5822b096259ac7746beab2373200fe095c686740ba51f093a464c`

The previously discussed rule of three consecutive `ANOMALY` decisions was rejected before scientific execution. It is not the operative rule.

For TARGET LLM runs, the first `ANOMALY` while SEARCHING is `FIRST_INDICATION` at window `k`. Windows `k+1`, `k+2` and `k+3` are retained as verification observations but cannot confirm detection. With a 20-sample causal window and stride 5, four advances replace all observations: `20 / 5 = 4`. Window `k+4` is therefore the first FULL WINDOW REFRESH.

- If `decision(k+4) == ANOMALY`, record `CONFIRMED_DETECTION`; TARGET LLM may stop after persisting the batch.
- Otherwise record `VERIFICATION_FAILED`; do not start an overlapping candidate, and resume SEARCHING at `k+5`.
- If `k+4` does not exist, preserve the first indication and record `VERIFICATION_INCOMPLETE_END_OF_TRAJECTORY`.
- If no indication occurs, record `NO_DETECTION` after the full trajectory.
- Normal holdout never early-stops, including after any `ANOMALY`; every such decision is counted as a false-alarm opportunity over the complete trajectory, without applying the TARGET confirmation rule.
- DPCA completion is independent of LLM early stop.

H1 now counts TARGET confirmed detections and no-detection runs under this rule, while normal-holdout false alarms use all raw `ANOMALY` opportunities. H2 distinguishes first indication from confirmation and anchors confirmed delay to `k+4`. H3 evidence rules and normal-reference thresholds are unchanged; TARGET aggregation ends at the confirmed window only when early stop applies.

Machine-readable record: `experiments/tep/local_llm/config/post_freeze_methodological_amendment_001.json`.

# Methodological amendment 002 — authoritative full-window refresh

The authoritative freeze is `TEP-METHOD-FREEZE-20260815-FULL-WINDOW-REFRESH`.

The LLM confirmation horizon is derived, never independently tuned: `R = ceil(W/S) = ceil(20/5) = 4`. Every eligible `ANOMALY` starts a concurrent candidate at window `k`; only that candidate is checked at `k+R`. A non-anomaly fails only the candidate due at that window. Pending candidates coexist, and candidates beyond trajectory end are recorded individually as incomplete.

Evaluator state resets at sample 161. FIRST_INDICATION and CONFIRMED_DETECTION, including their delays from sample 161, remain separate. Normal holdout uses the same machine but never confirmation-early-stops. DPCA and H3 PROCESS-EVIDENCE GROUNDEDNESS are unchanged.

Machine-readable authority: `experiments/tep/local_llm/config/post_freeze_methodological_amendment_002.json`.

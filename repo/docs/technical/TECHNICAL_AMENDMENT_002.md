# Technical amendment 002 — refreeze acceptance and monitor

The localhost monitor now plans 1,000 durable lots: 500 TARGET and 500 NORMAL HOLDOUT. DPCA is required for every lot; LLM is additionally required only for the 50 frozen selections in each cohort. A lot cannot become COMPLETE while a required component is incomplete. The default `runs_this_session=5` is operational only.

The one-click launcher is `START_PSQZA_FORMAL_MONITOR.bat`; it opens the UI without starting inference.

The single authorized synthetic GPU acceptance was attempted once at `post-refreeze-synthetic-gpu-acceptance-20260815T045357Z`. Network isolation passed, but CUDA/device/layer-offload evidence did not appear before the fail-closed startup deadline. The runtime was terminated before any inference request (`inference_count=0`), no retry was performed, and REAL START remains blocked.

Machine-readable record: `experiments/tep/local_llm/config/post_freeze_technical_amendment_002.json`.

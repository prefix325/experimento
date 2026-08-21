# Protocol audit — closest antecedents

Status: `PROVISIONAL`
Date: 2026-08-13
Branch: `branch:local-llm-idv13`

This targeted audit tests whether the current candidate gap survives comparison with the nearest known protocols. It is not a systematic review and does not authorize a novelty claim. Consensus was retried and remained unavailable because the monthly search quota is exhausted; multi-index verification is still pending.

## Findings

**AAD-LLM — Russell-Gilbert et al., IEEE BigData 2024, DOI 10.1109/BigData62323.2024.10825679.** This is the strongest direct antecedent. It uses a frozen Llama 3 8B as the primary anomaly detector, a normal comparison dataset, consecutive windows and multivariate prompts without fine-tuning on the target dataset. However, on SKAB the anomaly labels are used in a Mann–Whitney test to select the input variables. Its domain context also contains expert rules, acceptable ranges, feature-selection guidance and causal relations. The normal comparison set is adaptively updated with windows classified as non-anomalous, and the paper evaluates static retrospective datasets rather than controlled online onset.

**RAAD-LLM — Russell-Gilbert et al., arXiv:2503.02800v3.** This extends AAD-LLM with frozen Llama 3.1 8B, Ollama and RAG for z-score comparisons. It retains expert domain rules/causal relations, label-guided feature selection on SKAB, a first-window normal baseline and adaptive updates. The paper again uses static datasets and identifies online anomaly detection as future work. Therefore local execution, frozen LLMs, normal comparison windows and industrial multivariate anomaly detection cannot be claimed as standalone novelty.

**FaultExplainer — Khan et al., Computers & Chemical Engineering 199 (2025) 109152, DOI 10.1016/j.compchemeng.2025.109152.** It is a direct TEP antecedent, but PCA/T² performs primary detection and selects contributing variables before GPT-4o/o1 explains or diagnoses the event. It does not test an independent fault-blind LLM detector.

**Adjust to reality — Zhao et al., Control Engineering Practice 164 (2025) 106406.** It evaluates TEP and a real thermal power plant under zero-shot fault diagnosis, but the LLM explicitly constructs semantic knowledge for seen and unseen fault categories and the method performs test-time semantic adjustment. This blocks any broad claim of “first LLM zero-shot diagnosis on TEP”, but it is not target-fault blind.

**AKT — Zhao et al., Journal of Process Control (2025) 103534.** It fine-tunes the LLM with domain diagnosis reports and uses unseen-fault text descriptions in cross-modal diagnosis. It is industrial zero-shot diagnosis, but not a frozen normal-only detector.

**SAGE — Kang et al., arXiv:2605.05725.** It is conceptually close because it synthesizes in-context examples from normal-reference segments without real anomalous examples or anomaly-type labels. It is nevertheless univariate and analyzer-mediated rather than a single general-purpose LLM directly monitoring multivariate industrial telemetry.

SigLLM (arXiv:2405.14755) and AnomLLM (arXiv:2410.05440) already establish direct zero-shot LLM anomaly-detection research in general time series, so the contribution cannot be framed at that broad level.

## Candidate gap after audit

The gap survives only under a stricter **target-fault-blind** contract: no IDV(13) labels, descriptions, semantic attributes, expert failure signatures, hidden simulator flags or fault-derived feature selection; a normal reference frozen before fault onset; causal progressive windows; simulator-controlled onset as ground truth; DPCA as an independent comparator not exposed to the LLM; explicit `EVIDÊNCIA_INSUFICIENTE`; and independent scoring of evidence coherence.

The local/offline condition remains an operational constraint, not the novelty claim.

## Consequences for H1–H3

H1 must mean target-fault-blind zero-shot, not merely absence of fine-tuning. H2 requires a pre-fault baseline frozen before onset so gradual drift cannot be absorbed into adaptive normality. H3 must score cited variables/trends against observed trajectories independently of any fault-specific rules supplied to the model.

## Decision

**GO, WITH NARROWED GAP.** The study remains scientifically defensible as a candidate program under the restrictions above. Originality remains provisional until a reproducible multi-index review is completed.

## Immediate next step

Freeze the Tennessee Eastman Process lineage and experimental run contract: exact simulator/dataset source, observable-variable inventory, sampling interval, healthy-reference period, IDV(13) onset, total horizon, replicate/seed policy and the exact observables exposed to LLM and DPCA.

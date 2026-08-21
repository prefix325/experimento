# Scoping synthesis — zero-shot LLM fault detection in multivariate industrial systems

Status: `PROVISIONAL`

Date: 2026-08-13

Research branch: `branch:local-llm-idv13`

## Objective

Evaluate whether the current research question occupies a defensible literature gap: a general-purpose LLM acting as a direct anomaly detector in a multivariate industrial process, zero-shot with respect to the target fault, contextualized by process/normal-operation knowledge, evaluated causally over progressive windows, and compared with an independent statistical detector.

This is a scoping synthesis, not a systematic review and not a novelty claim.

## Search scope

Queries covered combinations of: LLM; large language model; zero-shot; anomaly detection; fault detection; fault diagnosis; time series; multivariate; industrial; Tennessee Eastman Process; normal operation; normal-only; fault-blind; local LLM.

Consensus search was unavailable because the connected monthly quota was exhausted. The scoping therefore used direct publisher/arXiv discovery and must later be complemented by a reproducible systematic search.

## Gap matrix

| Work | Domain / data | Zero-shot meaning | LLM role | Direct multivariate industrial detector? | Normal-only / fault-blind? | Main distinction from this study |
|---|---|---|---|---|---|---|
| Alnegheimish et al., *Large language models can be zero-shot anomaly detectors for time series?* (arXiv:2405.14755) | Time-series anomaly benchmarks | No task-specific training in evaluated zero-shot pipelines | Direct detector / forecast-assisted detector | No; evaluated principally as general TSAD, not TEP multivariate industrial process monitoring | No normal-reference industrial protocol equivalent | Establishes that direct zero-shot LLM TSAD already exists; novelty cannot be claimed at that level |
| Dong et al., *Can LLMs Serve As Time Series Anomaly Detectors?* (arXiv:2408.03475) | Time-series anomaly detection | Zero/few-shot prompting and later fine-tuning experiments | Direct detector and explainer | Not a TEP multivariate industrial study | No equivalent fault-blind normal-operation protocol | Shows strong dependence on prompting/model architecture and that direct use can fail |
| Zhou & Yu, *Can LLMs Understand Time Series Anomalies?* (arXiv:2410.05440) | Time-series anomaly benchmarks | Zero-shot and few-shot evaluation | Direct anomaly reasoning/detection evaluation | No TEP industrial multivariate focus | No equivalent normal-reference plant protocol | Important negative-control evidence: LLM behavior varies substantially and reasoning prompts do not guarantee improvement |
| Russell-Gilbert et al., *AAD-LLM: Adaptive Anomaly Detection Using Large Language Models* (arXiv:2411.00914) | Real plastics manufacturing + SKAB multivariate sensor benchmark | Frozen pretrained Llama 3 8B; no training/fine-tuning on applied dataset | Direct anomaly detector over statistical summaries and domain context | **Yes, explicitly explores multivariate anomaly detection** | Uses normal baseline, but not fault-blind in our stricter sense: feature selection uses anomaly labels and domain context includes expert failure-mode correlations, acceptable ranges and causal rules | Closest antecedent. Our remaining distinction must be fault-blindness to the target failure, no label-based feature selection, no fault-specific semantic rules, controlled gradual onset, causal detection delay and independent DPCA comparison |
| Khan et al., *FaultExplainer* (Computers & Chemical Engineering, 2025, DOI 10.1016/j.compchemeng.2025.109152) | Tennessee Eastman Process | Scenario may omit historical root-cause knowledge | LLM explains faults after PCA/T² detection and contribution analysis | No: primary detection is statistical | No: LLM receives PCA-selected evidence and plant description | Direct TEP antecedent, but LLM is explainer rather than independent primary detector |
| Zhao et al., *Align knowledge with time-series* (Journal of Process Control, 2025, DOI 10.1016/j.jprocont.2025.103534) | Real thermal power plant | Diagnosis of unseen fault classes | LLM supplies/learns semantic fault knowledge; cross-modal alignment | Industrial zero-shot diagnosis, but not a frozen direct detector | No: LLM is fine-tuned on domain diagnosis reports and fault semantics | Zero-shot refers to unseen fault classes, not ignorance of target-fault semantics |
| Zhao et al., *Adjust to reality: LLM-driven test-time semantic adjustment for zero-shot fault diagnosis* (2025, ScienceDirect PII S0967066125001698) | TEP + real thermal power plant | Diagnosis of unseen fault classes | LLM annotates/adjusts semantic fault knowledge | Uses TEP and zero-shot fault diagnosis, but not as a fault-blind direct LLM detector | No: semantic fault knowledge is explicitly modeled and test-time adjusted | Critical counterexample to broad novelty claims involving “LLM + TEP + zero-shot” |
| *Enhanced Fault Diagnosis Using Large Language Models and Probabilistic Label Fusion* (IFAC-PapersOnLine, 2025, DOI 10.1016/j.ifacol.2025.09.401) | Tennessee Eastman Process | Not zero-shot | Fine-tuned LLaMA3 generates pseudo-labels combined with a classifier | No | No | Shows TEP + LLM diagnosis with explicit fine-tuning and label fusion |
| Zhang et al., *LLM-TSFD* (Expert Systems with Applications, 2025, DOI 10.1016/j.eswa.2024.125861) | Industrial time series / steel metallurgy | Not the same fault-zero-shot protocol | Human-in-the-loop task-driven diagnosis framework | Industrial multivariate context, but not isolated fault-blind general-purpose LLM detection | No | Must remain in related-work matrix because it places LLMs inside industrial time-series diagnosis workflows |
| Lin et al., *FD-LLM: Large language model for fault diagnosis of complex equipment* (Advanced Engineering Informatics, 2025, article 103208) | Complex equipment | Not the same zero-shot protocol | Multimodal LLM adapted/aligned for fault diagnosis | Industrial diagnosis, but domain/modal adaptation is central | No | Demonstrates that direct LLM fault diagnosis exists but with adaptation/training |
| Kang et al., *SAGE* (arXiv:2605.05725) | Univariate TSAD | Uses synthetic in-context examples derived from normal-reference segments, without real anomalous examples/labels | Multi-agent detector grounded by specialized numerical analyzers | No; univariate and analyzer-mediated | Partially: normal-reference construction is close | Closest normal-reference conceptual antecedent, but not a single general-purpose LLM directly monitoring multivariate industrial process data |
| Hidalgo-Castelo et al., *Local LLMs for Industrial Supervision and Control* (Electronics, 2026, DOI 10.3390/electronics15122547) | Real industrial supervision | Not fault-zero-shot detection | Local LLM for operational context and supervision | No | No | Establishes that local/cloud-independent industrial LLM deployment itself is not novel |
| Chen et al., *Cognitive fault diagnosis in Tennessee Eastman Process using learning in the model space* (Computers & Chemical Engineering, 2014, DOI 10.1016/j.compchemeng.2014.03.015) | TEP | Unknown fault detection without prior fault signature | Non-LLM one-class/model-space learner | Yes, as non-LLM unknown-fault detection | Uses healthy/normal regime | Establishes that normal-only unknown-fault detection in TEP is not novel in itself |
| *An effective zero-shot learning approach for intelligent fault detection using 1D CNN* (Applied Intelligence, 2023, DOI 10.1007/s10489-022-04342-1) | TEP | Fault classes without training samples | CNN-based zero-shot detector | Yes, non-LLM | Not equivalent | Establishes that zero-shot TEP fault detection predates LLM approaches |
| Liu et al., *Knowledge Distillation-Based Zero-Shot Learning for Process Fault Diagnosis* (Advanced Intelligent Systems, 2025, DOI 10.1002/aisy.202400828) | TEP + sour-water treatment | Unknown fault detection/isolation | Teacher-student non-LLM architecture | Yes, non-LLM | Student receives only normal-condition knowledge after transfer | Particularly important normal-only zero-shot industrial antecedent; proposed contribution must be LLM-specific |

## Full-text audit update — AAD-LLM

AAD-LLM materially narrows the candidate gap and must be treated as the closest currently identified antecedent. The paper uses a frozen pretrained Llama 3 8B without fine-tuning on the applied dataset, constructs a normal baseline using statistical process control, creates windowed statistical summaries, adds domain context, and maps the LLM output to anomaly/non-anomaly. It explicitly states that multivariate anomaly detection is explored even though each variable is processed independently before all variables are represented in the prompts.

The protocol is nevertheless distinguishable from the current TEP/IDV(13) proposal in several scientifically material ways:

1. AAD-LLM uses anomaly labels to select features in the SKAB evaluation; the current study must prohibit target-fault labels from selecting the LLM input variables.
2. AAD-LLM's domain context includes expert rules, acceptable operating ranges, failure-mode correlations and causal relationships; the current primary condition must exclude semantic knowledge specific to IDV(13) or its signature.
3. AAD-LLM defines zero-shot primarily as no training/fine-tuning on the applied dataset; the current study defines zero-shot more strictly with respect to the **target fault**.
4. AAD-LLM evaluates static datasets retrospectively and explicitly leaves online/data-stream detection as future work; the current protocol is designed around causal progressive windows and detection delay from a controlled onset.
5. AAD-LLM updates its normal comparison set adaptively after non-anomalous classifications; the current primary experiment should freeze the normal reference before the fault trial to avoid contamination by the model's own decisions.
6. AAD-LLM does not use a simulator-controlled fault-onset ground truth or an independent DPCA comparator; both are central to the proposed TEP experiment.
7. AAD-LLM's binary mapping can depend on known domain-specific correlation rules; the current primary condition should require the LLM to infer abnormality without a rule encoding the target-fault signature.

Consequently, the research should no longer be presented simply as “zero-shot LLM anomaly detection in multivariate industry.” That territory already has a strong antecedent. The scientific distinction must be expressed as **target-fault-blind zero-shot detection of a controlled gradual fault in a multivariate industrial process, using only normal/process context and measuring causal detection emergence relative to true onset and an independent statistical reference**.

## Provisional synthesis

The scoping search does **not** support broad novelty claims such as:

- first zero-shot fault detector;
- first zero-shot detector on TEP;
- first LLM time-series anomaly detector;
- first LLM multivariate industrial anomaly detector;
- first LLM in industrial fault diagnosis;
- first local LLM in industry;
- first normal-only unknown-fault detector in TEP.

The defensible candidate gap is now narrower. In the searched literature, no work was found that simultaneously combines all of the following characteristics:

1. a general-purpose frozen LLM acting as the primary detector;
2. multivariate industrial process telemetry as the primary observation space;
3. zero-shot status specifically with respect to the target fault: no target-fault examples, labels, descriptions, semantic attributes, failure-mode rules or label-driven feature selection;
4. preparation/context limited to generic process knowledge and a pre-fault normal-operation reference;
5. a normal reference frozen before the fault trial rather than adaptively contaminated by test-time predictions;
6. causal progressive windows that measure when sufficient evidence accumulates after controlled gradual fault onset;
7. simulator-controlled onset as ground truth;
8. an independent statistical detector such as DPCA used as comparator rather than teacher/oracle;
9. explicit abstention (`EVIDÊNCIA_INSUFICIENTE`) and evidence-coherence evaluation;
10. verifiable local/offline execution as an operational constraint.

This intersection is therefore a **candidate research gap**, not yet an established originality claim. A systematic search and full-text verification of the closest antecedents—especially AAD-LLM, SAGE, FaultExplainer, the two Zhao zero-shot diagnosis works, and normal-only non-LLM TEP studies—remain mandatory.

## Implications for the current hypotheses

H1 remains meaningful only under the stricter target-fault-blind definition. A generic claim that a frozen LLM can perform zero-shot multivariate industrial anomaly detection is already substantially addressed by AAD-LLM.

H2 becomes a stronger differentiator because AAD-LLM is retrospective/static, while the current study asks when detection emerges relative to a known fault onset in causal progressive windows.

H3 remains necessary because AAD-LLM itself reports comparison/calculation errors and depends on manually structured domain context; evidence coherence is therefore an independent scientific question rather than a cosmetic explanation feature.

## Decision boundary

Do not promote the candidate gap to an accepted novelty statement until the closest papers have been fetched in full, their experimental protocols have been compared field-by-field, and the search strategy is reproducible across at least two scholarly indexes/providers.

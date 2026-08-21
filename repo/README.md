# PSQZA Research

Canonical GitHub-native research state operated under the VERAS academic project boundary, with VERSA as its non-conversational control plane. PSQZA is the sole conversational interface; MECAI advises; BANCA evaluates researcher-approved frozen academic snapshots, admits write packages read-only and validates resulting diffs; VERSA owns routing, state, authorization, gates and the internal `RESTRICTED_WRITE_EXECUTION` capability. Git commits and hashes are canonical.

The repository is the persistent research-state repository for VERAS. It does not define or duplicate the VERAS agents. The canonical agent package lives in `prefix325/agentes/active/specialized/VERAS`; `project/checkpoint.json` records the exact governance binding used by the current research state.

The repository maintains a structured research graph and four integrated LaTeX deliverables: pre-project, article, dissertation, and doctoral agenda. The doctoral agenda is not a formal thesis. PDFs are derived build artifacts. Historical proposal content remains `PROVISIONAL` until separately accepted.

Literature discovery and evidence are stored under `literature/`. Consensus is a VERAS/VERSA-governed read-only provider for search and fetched paper records. Search results are candidates, fetched records remain provisional, and full-text locators plus claim acceptance require separate verification.

## Continuous research flow

Academic exploration is modeled as a continuous `RESEARCH_FLOW`, not as a sequence of repository-administration conversations. `project/session_state.json` stores the active scientific branch, current question, open threads and return policy. Internal literature, orientation, evidence, validation, projection and persistence routes are background effects; after they finish, PSQZA resumes the same scientific branch unless the researcher explicitly changes it.

`project/research_ledger.jsonl` is an append-only journal of research-significant events. Findings, evidence, questions, hypotheses, contradictions, method decisions, results, limitations, contribution candidates, writing fragments and supersessions can be captured as `DISCUSSED`, `PROPOSED` or `PROVISIONAL` without being represented as accepted science. A correction does not rewrite prior history: a later `SUPERSESSION` event points to the event it replaces.

The ledger and the research graph have different roles. The ledger preserves how the investigation evolved; `project/research_graph.json` represents the current structured scientific state. Accepted-state promotion and frozen scientific deltas continue to use the formal MECAI/researcher/BANCA path.

Provisional writing fragments may target any of the four products. `tools/render_live_writing.py` deterministically compiles active, non-superseded fragments into `writing/compiled/` working drafts for the pre-project, article, dissertation and doctoral agenda. These Markdown drafts are continuity artifacts only. Canonical deliverables remain the governed LaTeX trees under `deliverables/`.

## Cross-chat continuity

`project/checkpoint.json` is the bootstrap entrypoint. A new PSQZA chat pins the current research repository commit and the exact VERAS governance binding, validates the checkpoint, reads current state, the research graph, the active session state, the research ledger and the document projection map, then reads `history_conversation/index.json`. It loads the latest summary and only additional relevant summaries within the configured context budget.

Operational summaries are created through `/resumo_operacional` as `history_conversation/YYMMDDHHMMSS_breve_resumo_da_conversacao.md`. The filename, metadata, index and checkpoint are schema-governed. Formal route records may be stored under `history_conversation/routes/` so the user can inspect what was formally routed among PSQZA, MECAI, BANCA and the VERSA control plane.

Conversation summaries are continuity records. They do not independently promote academic content to `ACCEPTED`. Current structured state, provenance, evidence and explicit decisions remain authoritative.

## VERAS 3 execution model

Current route contracts do not model a separate Git-executor persona. Restricted Git execution is an internal VERSA capability and is represented as `RESTRICTED_WRITE_EXECUTION` only after BANCA write admission. BANCA validates the resulting diff afterward; VERSA cannot admit or validate its own effect.

Route traces created before VERAS 3 may contain the former executor component. Those records are preserved as historical evidence, marked `LEGACY_PRE_VERAS_3`, and validated only through the legacy compatibility branch of the route contract. They do not authorize current routing or execution.

## Checkpoint commit semantics

`generated_from_commit` identifies the repository state summarized by the checkpoint. `commit_lineage.source_state_commit` must refer to the same scientific source state. The commit containing the checkpoint is not embedded inside the file because that would create unstable self-reference; it is derived from Git history or the exact pinned repository commit used during bootstrap.

From checkpoint schema `1.2.0`, `governance_binding` records the exact `prefix325/agentes` commit, VERAS path/version, component-lock provenance, VERSA control-plane identity and restricted-execution capability expected by the research state. Schema `1.3.0` additionally binds `research_ledger`, `session_state` and `document_projection_map` into mandatory bootstrap continuity.

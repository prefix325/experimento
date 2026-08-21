# VERAS / VERSA governance

This repository is the persistent research-state repository of the VERAS academic project unit. VERAS is the project boundary; VERSA is its non-conversational control plane. PSQZA owns user dialogue; MECAI advises; BANCA evaluates researcher-approved frozen snapshots, admits write packages read-only and validates resulting diffs. GitHub commits and hashes are canonical.

VERSA owns routing, state, authorization, gates, scientific-tool governance and the internal `RESTRICTED_WRITE_EXECUTION` capability. Restricted execution is not a persona or a separate agent route. It may run only after BANCA admits the exact write package, and BANCA must validate the resulting diff. VERSA cannot admit, expand or validate its own execution.

The active VERAS package is resolved from `prefix325/agentes/active/specialized/VERAS` at an exact pinned commit. `project/checkpoint.json` records that governance binding so the research state can verify which VERAS generation and component-lock provenance it expects.

Consensus is an external read-only research tool governed by VERSA. Only public academic or safely anonymized queries are permitted. VERSA records requester, purpose, sanitized query, filters, budgets, returned ids, fetched ids, limitations, and disposition. Search results require fetch before citation and remain provisional. Consensus has no direct Git, LaTeX, research-state, submission, or publication authority.

Literature persistence uses `literature/queries`, `literature/records`, `literature/evidence`, and `literature/syntheses`. Formal BANCA literature audits use a separately recorded query.

Pre-VERAS-3 route traces are retained only as historical provenance. Their former executor component has no current authority and cannot be used as a routing or write target by current contracts.

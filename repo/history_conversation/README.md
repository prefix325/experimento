# Conversation History

This directory stores versioned operational summaries created by the governed `/resumo_operacional` route.

## Naming

Each summary uses the transaction start time in `America/Sao_Paulo`:

`YYMMDDHHMMSS_breve_resumo_da_conversacao.md`

The full filename must match `^[0-9]{12}_[a-z0-9]+(?:_[a-z0-9]+)*\.md$`. Slugs are short lowercase ASCII phrases separated by underscores.

## Purpose

Summaries allow a new PSQZA chat to restore relevant conversational context from GitHub. They record subjects, decisions, proposals, formal persona records, VERSA control-plane activity, evidence discussed, affected academic objects, unresolved items and next actions. They do not contain private model reasoning.

Operational history is subordinate to current structured academic state. A summary does not itself accept a problem, question, method, claim, reference, result or contribution. Status and provenance remain explicit.

## Index and routes

`index.json` lists every summary by exact filename and metadata. In schema `1.1.0`, `personas` contains only conversational/academic projections (PSQZA, MECAI and BANCA); VERSA is recorded separately under `control_components`; components that existed only in older architectures are retained under `legacy_components` for provenance and have no current authority.

Formal internal transit records may be stored under `routes/` and referenced by index entries. New route records follow the VERAS 3 model. Pre-VERAS-3 traces remain historical, explicitly marked as legacy, and must not be used as templates for current execution.

The bootstrap always reads the index, then loads the latest and only additional relevant summaries within its context budget. `project/checkpoint.json` additionally binds the research state to an exact VERAS package commit/version.

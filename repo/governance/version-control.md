# Version-Control Governance

`main` is the accepted current repository state, but individual scientific entities retain explicit statuses. Changes use purpose-specific branches and pull requests. Direct writes to `main` are prohibited by procedure.

VERSA classifies changes as `ORDINARY`, `PROVISIONAL`, `MATERIAL`, or `REJECTED`. Ordinary reversible changes may merge after all gates. Provisional material may be committed with provenance but cannot support accepted claims. Material scientific, institutional, privacy, financial, or irreversible changes require user authorization. Rejections are traced; useful forensic material may be quarantined.

Git stores source, code, specifications, structured results, decisions, bibliography, and suitable assets. Git LFS requires specific authorization when billing or quotas may be affected. Releases may preserve immutable milestone snapshots. Sensitive or restricted data requires a separate decision. Google Drive and Overleaf are non-canonical. Every merge records base, head, changed paths, validation, and rollback ref.

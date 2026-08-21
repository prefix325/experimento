# Academic Writing

Canonical writing lives under `deliverables/` as LaTeX source. Stable filenames are required. Git history, tags, and releases preserve versions; names such as `final`, `latest`, `v2`, and dated duplicates are prohibited.

`writing/compiled/` contains deterministic live working drafts generated from active, non-superseded `project/research_ledger.jsonl` writing fragments. They exist to preserve and continuously compile prose during exploration. They are not canonical LaTeX, scientific acceptance, frozen milestones, or submission-ready artifacts. Use `python tools/render_live_writing.py` to regenerate them and `python tools/render_live_writing.py --check` to verify that committed drafts match the ledger.

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import OrderedDict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "project" / "research_ledger.jsonl"
OUTPUT_DIR = ROOT / "writing" / "compiled"

DOCUMENTS = OrderedDict([
    ("PREPROJECT", ("preproject.md", "Pré-projeto")),
    ("ARTICLE", ("article.md", "Artigo científico")),
    ("DISSERTATION", ("dissertation.md", "Dissertação")),
    ("DOCTORAL_AGENDA", ("doctoral-agenda.md", "Agenda de doutorado")),
])


def load_events() -> list[dict]:
    events: list[dict] = []
    for number, raw in enumerate(LEDGER.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            events.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at line {number}: {exc}") from exc
    return events


def active_events(events: list[dict]) -> list[dict]:
    superseded: set[str] = set()
    for event in events:
        if event.get("event_type") == "SUPERSESSION" and event.get("status") != "REJECTED":
            superseded.update(event.get("supersedes", []))
    return [
        event for event in events
        if event.get("event_id") not in superseded
        and event.get("status") not in {"REJECTED", "SUPERSEDED"}
    ]


def render_document(document: str, title: str, events: list[dict]) -> str:
    sections: OrderedDict[str, list[tuple[dict, dict]]] = OrderedDict()
    for event in events:
        for fragment in event.get("writing_fragments", []):
            if fragment.get("document") != document:
                continue
            sections.setdefault(fragment["section"], []).append((event, fragment))

    lines = [
        f"# Live Working Draft — {title}",
        "",
        "> Gerado deterministically from active, non-superseded research-ledger fragments. This file is provisional working prose, not canonical LaTeX, scientific acceptance, or submission-ready content.",
        "",
    ]
    if not sections:
        lines.extend(["_No active projected fragments._", ""])
        return "\n".join(lines)

    for section, fragments in sections.items():
        lines.extend([f"## {section}", ""])
        for event, fragment in fragments:
            lines.append(f"<!-- source_event={event['event_id']} status={event['status']} language={fragment['language']} -->")
            lines.append(fragment["text"].strip())
            lines.append("")
    return "\n".join(lines)


def build_outputs() -> dict[Path, str]:
    events = active_events(load_events())
    return {
        OUTPUT_DIR / filename: render_document(document, title, events)
        for document, (filename, title) in DOCUMENTS.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    outputs = build_outputs()
    if args.check:
        mismatches = []
        for path, expected in outputs.items():
            if not path.exists() or path.read_text(encoding="utf-8") != expected:
                mismatches.append(path.relative_to(ROOT).as_posix())
        if mismatches:
            print(json.dumps({"status": "FAIL", "mismatches": mismatches}, indent=2))
            return 1
        print(json.dumps({"status": "PASS", "outputs": len(outputs)}, indent=2))
        return 0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path, content in outputs.items():
        path.write_text(content, encoding="utf-8")
    print(json.dumps({"status": "PASS", "outputs": [p.relative_to(ROOT).as_posix() for p in outputs]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

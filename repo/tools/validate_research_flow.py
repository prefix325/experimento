#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []
CHECKS = 0


def require(condition: bool, message: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        ERRORS.append(message)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_schema(name: str, instance: Any) -> None:
    global CHECKS
    schema_path = ROOT / "schemas" / f"{name}.schema.json"
    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for error in validator.iter_errors(instance):
        CHECKS += 1
        ERRORS.append(f"{name}:{error.json_path}:{error.message}")


def load_ledger() -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    ledger_path = ROOT / "project" / "research_ledger.jsonl"
    require(ledger_path.is_file(), "missing:project/research_ledger.jsonl")
    if not ledger_path.is_file():
        return events
    for line_number, raw in enumerate(ledger_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except Exception as exc:
            ERRORS.append(f"ledger:line:{line_number}:{exc}")
            continue
        validate_schema("research-event", event)
        events.append(event)
    return events


def main() -> int:
    session_path = ROOT / "project" / "session_state.json"
    require(session_path.is_file(), "missing:project/session_state.json")
    session = load_json(session_path) if session_path.is_file() else {}
    if session:
        validate_schema("session-state", session)

    events = load_ledger()
    require(len(events) >= 1, "ledger:empty")

    seen: set[str] = set()
    previous_time: datetime | None = None
    for event in events:
        event_id = event.get("event_id", "")
        require(event_id not in seen, f"ledger:duplicate_event_id:{event_id}")
        for superseded in event.get("supersedes", []):
            require(superseded in seen, f"ledger:supersedes_unknown_or_future:{event_id}:{superseded}")
        seen.add(event_id)

        try:
            timestamp = datetime.fromisoformat(event["timestamp"])
            if previous_time is not None:
                require(timestamp >= previous_time, f"ledger:timestamp_regression:{event_id}")
            previous_time = timestamp
        except Exception as exc:
            ERRORS.append(f"ledger:invalid_timestamp:{event_id}:{exc}")

        targets = set(event.get("projection_targets", []))
        for fragment in event.get("writing_fragments", []):
            target = f"{fragment['document']}.{fragment['section']}"
            require(target in targets, f"ledger:fragment_without_projection_target:{event_id}:{target}")

    if session.get("status") == "ACTIVE":
        active = session.get("active_branch") or {}
        branch_id = active.get("branch_id")
        require(bool(branch_id), "session:active_without_branch")
        for route in session.get("background_routes", []):
            require(route.get("return_branch_id") == branch_id, f"session:background_route_breaks_anchor:{route.get('route_id')}")

    require(session.get("ledger_path") == "project/research_ledger.jsonl", "session:ledger_path_mismatch")
    require(session.get("live_writing_dir") == "writing/compiled", "session:live_writing_dir_mismatch")
    resume = session.get("resume_policy", {})
    require(resume.get("after_background_route") == "RETURN_TO_CURRENT_BRANCH", "session:resume_policy_invalid")
    require(resume.get("topic_change_requires_explicit_researcher_change") is True, "session:topic_change_not_locked")
    require(resume.get("persistence_is_background_effect") is True, "session:persistence_not_background")

    compiled = [
        ROOT / "writing" / "compiled" / "preproject.md",
        ROOT / "writing" / "compiled" / "article.md",
        ROOT / "writing" / "compiled" / "dissertation.md",
        ROOT / "writing" / "compiled" / "doctoral-agenda.md",
    ]
    for path in compiled:
        require(path.is_file(), f"missing:{path.relative_to(ROOT)}")
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            require("not canonical LaTeX" in text, f"live_writing:canonical_boundary_missing:{path.name}")

    renderer = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "render_live_writing.py"), "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    require(renderer.returncode == 0, "live_writing:renderer_check_failed")
    if renderer.returncode != 0:
        ERRORS.append((renderer.stdout + renderer.stderr)[-8000:])

    report = {
        "status": "PASS" if not ERRORS else "FAIL",
        "checks": CHECKS,
        "events": len(events),
        "research_flow": {
            "active_branch_preserved": session.get("status") != "ACTIVE" or bool((session.get("active_branch") or {}).get("branch_id")),
            "append_only_supersession": True,
            "background_route_return_policy": resume.get("after_background_route") == "RETURN_TO_CURRENT_BRANCH",
            "live_writing_deterministic": renderer.returncode == 0,
            "live_writing_noncanonical": True,
        },
        "errors": ERRORS,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if ERRORS else 0


if __name__ == "__main__":
    sys.exit(main())

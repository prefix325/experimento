#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []
checks = 0


def require(condition: bool, message: str) -> None:
    global checks
    checks += 1
    if not condition:
        errors.append(message)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


registry = {
    "project/orientations": "orientation",
    "project/orientation_decisions": "orientation-decision",
    "project/research_deltas": "research-delta",
    "project/banca_opinions": "opinion",
}
validators: dict[str, Draft202012Validator] = {}

for directory_name, schema_name in registry.items():
    directory = ROOT / directory_name
    schema_path = ROOT / "schemas" / f"{schema_name}.schema.json"
    require(directory.is_dir(), f"registry_directory_missing:{directory_name}")
    require((directory / "README.md").is_file(), f"registry_readme_missing:{directory_name}")
    require(schema_path.is_file(), f"registry_schema_missing:{schema_name}")
    if schema_path.is_file():
        schema = load(schema_path)
        try:
            Draft202012Validator.check_schema(schema)
            validators[schema_name] = Draft202012Validator(schema)
        except Exception as exc:
            errors.append(f"registry_schema_invalid:{schema_name}:{exc}")

records: dict[str, dict[str, dict[str, Any]]] = {name: {} for name in registry.values()}
id_fields = {
    "orientation": "orientation_id",
    "orientation-decision": "decision_id",
    "research-delta": "delta_id",
    "opinion": "opinion_id",
}

for directory_name, schema_name in registry.items():
    directory = ROOT / directory_name
    validator = validators.get(schema_name)
    if validator is None or not directory.is_dir():
        continue
    for path in directory.glob("*.json"):
        record = load(path)
        for error in validator.iter_errors(record):
            errors.append(f"registry_record:{path.relative_to(ROOT)}:{error.json_path}:{error.message}")
        record_id = record.get(id_fields[schema_name])
        require(isinstance(record_id, str) and bool(record_id), f"registry_record_id:{path.relative_to(ROOT)}")
        if isinstance(record_id, str):
            require(record_id not in records[schema_name], f"registry_duplicate_id:{schema_name}:{record_id}")
            records[schema_name][record_id] = record

for decision in records["orientation-decision"].values():
    if records["orientation"]:
        require(decision["orientation_id"] in records["orientation"], f"decision_orientation_missing:{decision['decision_id']}")

for delta in records["research-delta"].values():
    require(bool(delta.get("orientation_decision_id")), f"delta_decision_missing:{delta['delta_id']}")
    require(bool(delta.get("approved_action_ids")), f"delta_approved_actions_missing:{delta['delta_id']}")
    if records["orientation-decision"]:
        decision = records["orientation-decision"].get(delta["orientation_decision_id"])
        require(decision is not None, f"delta_decision_not_registered:{delta['delta_id']}")
        if decision is not None:
            require(decision["decision"] in {"APPROVED", "PARTIALLY_APPROVED"}, f"delta_decision_not_admissible:{delta['delta_id']}")
            require(set(delta["approved_action_ids"]) == set(decision["approved_action_ids"]), f"delta_action_set_mismatch:{delta['delta_id']}")

case_script = ROOT / "tests/operator_cases/admin_market_orientation/run_case.py"
if case_script.is_file():
    case = subprocess.run([sys.executable, str(case_script)], cwd=ROOT, text=True, capture_output=True, check=False)
    require(case.returncode == 0, "operator_admin_case_failed")
    if case.returncode != 0:
        errors.append(case.stdout[-12000:] + case.stderr[-12000:])

report = {
    "status": "PASS" if not errors else "FAIL",
    "checks": checks,
    "errors": errors,
    "registry": {
        "orientation_records": len(records["orientation"]),
        "decision_records": len(records["orientation-decision"]),
        "delta_records": len(records["research-delta"]),
        "opinion_records": len(records["opinion"]),
        "operator_fixture_executed": case_script.is_file(),
    },
}
print(json.dumps(report, ensure_ascii=False, indent=2))
sys.exit(1 if errors else 0)

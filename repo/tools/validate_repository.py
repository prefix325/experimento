#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import json
import re
import subprocess
import sys
from typing import Any

from jsonschema import Draft202012Validator


root = Path(__file__).resolve().parents[1]
errors: list[str] = []
checks = 0
docs = ["preproject", "article", "dissertation", "doctoral-agenda"]


def require(condition: bool, message: str) -> None:
    global checks
    checks += 1
    if not condition:
        errors.append(message)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


for path in root.rglob("*.json"):
    checks += 1
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"json:{path.relative_to(root)}:{exc}")

schema_names = [
    "document-manifest",
    "document-projection-map",
    "academic-turn",
    "orientation-decision",
    "research-delta",
    "document-projection-plan",
    "cross-document-consistency",
    "evidence-coverage",
    "consensus-query",
    "consensus-paper",
    "literature-evidence",
    "conversation-summary",
    "conversation-history-index",
    "route-trace",
    "checkpoint",
]
schemas: dict[str, dict[str, Any]] = {}
for schema_name in schema_names:
    path = root / "schemas" / f"{schema_name}.schema.json"
    checks += 1
    try:
        schema = load(path)
        Draft202012Validator.check_schema(schema)
        schemas[schema_name] = schema
    except Exception as exc:
        errors.append(f"schema:{schema_name}:{exc}")

manifest_schema = schemas["document-manifest"]
for deliverable in docs:
    manifest_path = root / "deliverables" / deliverable / "manifest.json"
    tex_path = root / "deliverables" / deliverable / "main.tex"
    manifest = load(manifest_path)
    tex = tex_path.read_text(encoding="utf-8")
    checks += 1
    for error in Draft202012Validator(manifest_schema).iter_errors(manifest):
        errors.append(f"manifest:{deliverable}:{error.message}")
    require("\\documentclass" in tex, f"tex:{deliverable}:documentclass")
    require("\\begin{document}" in tex, f"tex:{deliverable}:begin")
    require("\\end{document}" in tex, f"tex:{deliverable}:end")
    require("bibliography.bib" in tex or "\\printbibliography" in tex, f"tex:{deliverable}:bibliography")
    require("\\placeholder" not in tex, f"tex:{deliverable}:unresolved_placeholder")
    if manifest["status"] in {"FROZEN", "SUBMITTED"}:
        require("[PENDENTE:" not in tex, f"tex:{deliverable}:pending_marker_in_frozen_document")

required_paths = [
    "literature/README.md",
    "literature/queries/README.md",
    "literature/records/README.md",
    "literature/evidence/README.md",
    "literature/syntheses/README.md",
    "history_conversation/README.md",
    "history_conversation/index.json",
    "history_conversation/routes/README.md",
    "project/checkpoint.json",
    "project/current_state.md",
    "project/research_graph.json",
    "project/document_projection_map.json",
    "project/academic_turns/README.md",
    "project/orientation_decisions/README.md",
    "project/research_deltas/README.md",
    "project/projection_plans/README.md",
    "project/consistency_reports/README.md",
    "project/evidence_coverage/README.md",
    "deliverables/shared/latex/research_state.tex",
    "tools/render_documents.py",
]
for rel in required_paths:
    require((root / rel).exists(), f"missing:{rel}")

projection_map = load(root / "project/document_projection_map.json")
for error in Draft202012Validator(schemas["document-projection-map"]).iter_errors(projection_map):
    errors.append(f"projection_map:{error.json_path}:{error.message}")
    checks += 1
require(set(projection_map["documents"]) == {"PREPROJECT", "ARTICLE", "DISSERTATION", "DOCTORAL_AGENDA"}, "projection_map:document_inventory")
require(projection_map["generated_file"] == "deliverables/shared/latex/research_state.tex", "projection_map:generated_file")

renderer = subprocess.run(
    [sys.executable, str(root / "tools/render_documents.py"), "--check"],
    cwd=root,
    text=True,
    capture_output=True,
    check=False,
)
require(renderer.returncode == 0, "document_renderer_check_failed")
if renderer.returncode != 0:
    errors.append(renderer.stdout[-8000:] + renderer.stderr[-8000:])

record_directories = {
    "project/academic_turns": "academic-turn",
    "project/orientation_decisions": "orientation-decision",
    "project/research_deltas": "research-delta",
    "project/projection_plans": "document-projection-plan",
    "project/consistency_reports": "cross-document-consistency",
    "project/evidence_coverage": "evidence-coverage",
}
for rel, schema_name in record_directories.items():
    validator = Draft202012Validator(schemas[schema_name])
    directory = root / rel
    for record_path in directory.glob("*.json"):
        checks += 1
        record = load(record_path)
        for error in validator.iter_errors(record):
            errors.append(f"record:{record_path.relative_to(root)}:{error.message}")

index = load(root / "history_conversation/index.json")
checks += 1
for error in Draft202012Validator(schemas["conversation-history-index"]).iter_errors(index):
    errors.append(f"history_index:{error.message}")

checkpoint = load(root / "project/checkpoint.json")
checks += 1
for error in Draft202012Validator(schemas["checkpoint"]).iter_errors(checkpoint):
    errors.append(f"checkpoint:{error.message}")

if checkpoint.get("schema_version") == "1.1.0":
    lineage = checkpoint.get("commit_lineage", {})
    require(checkpoint.get("generated_from_commit") == lineage.get("source_state_commit"), "checkpoint:generated_from_commit_lineage_mismatch")
    require(lineage.get("source_state_role") == "STATE_SUMMARIZED_BY_CHECKPOINT", "checkpoint:invalid_source_state_role")
    require(lineage.get("checkpoint_container_commit_policy") == "DERIVE_FROM_GIT_HISTORY", "checkpoint:invalid_container_commit_policy")
    require(lineage.get("self_reference_prohibited") is True, "checkpoint:self_reference_not_prohibited")

for key in ["current_state", "research_graph", "history_index"]:
    require((root / checkpoint[key]).exists(), f"checkpoint_missing:{key}:{checkpoint[key]}")
require(checkpoint["latest_conversation_summary"] == index["latest"], "checkpoint:latest_summary_mismatch")

filename_re = re.compile(r"^[0-9]{12}_[a-z0-9]+(?:_[a-z0-9]+)*\.md$")
record_paths: set[str] = set()
for record in index["records"]:
    require(record["filename"] == Path(record["path"]).name, f"history_record:{record['id']}:filename_path_mismatch")
    require(bool(filename_re.fullmatch(record["filename"])), f"history_record:{record['id']}:invalid_filename")
    require(record["path"] not in record_paths, f"history_record:{record['id']}:duplicate_path")
    record_paths.add(record["path"])
    summary_path = root / record["path"]
    require(summary_path.exists(), f"history_record:{record['id']}:missing_summary")
    if summary_path.exists():
        text = summary_path.read_text(encoding="utf-8")
        require(text.startswith("---"), f"history_record:{record['id']}:missing_front_matter")
        require("OPERATIONAL_CONVERSATION_SUMMARY" in text, f"history_record:{record['id']}:missing_record_type")
        require("private_reasoning_included: false" in text, f"history_record:{record['id']}:privacy_flag")

if index["latest"] is not None:
    require(index["latest"] in record_paths, "history_index:latest_not_in_records")

route_validator = Draft202012Validator(schemas["route-trace"])
for route_path in (root / "history_conversation/routes").glob("*.json"):
    checks += 1
    route = load(route_path)
    for error in route_validator.iter_errors(route):
        errors.append(f"route:{route_path.name}:{error.message}")

state = (root / "project/current_state.md").read_text(encoding="utf-8")
require("PROVISIONAL" in state, "state:not_provisional")
require("doctoral" in state.lower(), "state:no_doctoral_agenda")

doctoral = (root / "deliverables/doctoral-agenda/main.tex").read_text(encoding="utf-8").lower()
require("não constitui tese" in doctoral, "doctoral:formal_tese_boundary_missing")
require("projeto doutoral formal" in doctoral, "doctoral:formal_project_boundary_missing")

shared_state = (root / "deliverables/shared/latex/research_state.tex").read_text(encoding="utf-8")
for macro in (
    "ResearchQuestionPT",
    "ResearchQuestionEN",
    "ResearchHypothesisPT",
    "ResearchHypothesisEN",
    "ResearchMethodPT",
    "ResearchMethodEN",
    "ResearchLimitationsPT",
    "ResearchLimitationsEN",
):
    require(f"\\newcommand{{\\{macro}}}" in shared_state, f"shared_state:missing_macro:{macro}")

report = {
    "status": "PASS" if not errors else "FAIL",
    "checks": checks,
    "errors": errors,
    "academic_transaction": {
        "projection_map": True,
        "deterministic_renderer": True,
        "canonical_shared_state": True,
        "placeholder_rejection": True,
        "transaction_record_validation": True,
        "researcher_decision_validation": True,
        "doctoral_boundary": True,
    },
}
print(json.dumps(report, ensure_ascii=False, indent=2))
sys.exit(1 if errors else 0)

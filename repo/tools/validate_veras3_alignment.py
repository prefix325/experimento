#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
errors: list[str] = []
checks = 0


def require(condition: bool, message: str) -> None:
    global checks
    checks += 1
    if not condition:
        errors.append(message)


def load(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


checkpoint = load("project/checkpoint.json")
require(checkpoint.get("schema_version") == "1.3.0", "checkpoint:not_schema_1_3_0")
lineage = checkpoint.get("commit_lineage", {})
require(checkpoint.get("generated_from_commit") == lineage.get("source_state_commit"), "checkpoint:source_state_mismatch")

binding = checkpoint.get("governance_binding", {})
require(binding.get("agent_suite_repository") == "prefix325/agentes", "binding:wrong_agent_suite_repository")
require(binding.get("veras_path") == "active/specialized/VERAS", "binding:wrong_veras_path")
require(binding.get("veras_package_version") == "3.0.0", "binding:wrong_veras_version")
require(binding.get("control_plane") == "VERSA", "binding:wrong_control_plane")
require(binding.get("execution_capability") == "RESTRICTED_WRITE_EXECUTION", "binding:wrong_execution_capability")
require(binding.get("legacy_route_policy") == "PRESERVE_PRE_VERAS_3_AS_HISTORICAL_ONLY", "binding:wrong_legacy_policy")
require(isinstance(binding.get("agent_suite_commit"), str) and len(binding["agent_suite_commit"]) >= 40, "binding:missing_agent_suite_commit")

require(checkpoint.get("research_ledger") == "project/research_ledger.jsonl", "checkpoint:missing_research_ledger")
require(checkpoint.get("session_state") == "project/session_state.json", "checkpoint:missing_session_state")
require(checkpoint.get("document_projection_map") == "project/document_projection_map.json", "checkpoint:missing_document_projection_map")
for path in [checkpoint.get("research_ledger"), checkpoint.get("session_state"), checkpoint.get("document_projection_map")]:
    require(isinstance(path, str) and (ROOT / path).exists(), f"checkpoint:missing_research_flow_path:{path}")

always_load = set(checkpoint.get("bootstrap_policy", {}).get("always_load", []))
for required in [
    "project/checkpoint.json",
    "project/current_state.md",
    "project/research_graph.json",
    "project/session_state.json",
    "project/research_ledger.jsonl",
    "project/document_projection_map.json",
    "history_conversation/index.json",
]:
    require(required in always_load, f"checkpoint:bootstrap_missing:{required}")

index = load("history_conversation/index.json")
require(index.get("schema_version") == "1.1.0", "history_index:not_schema_1_1_0")
current_personas = {"PSQZA", "MECAI", "BANCA"}
for record in index.get("records", []):
    require(set(record.get("personas", [])) <= current_personas, f"history_index:{record.get('id')}:non_persona_actor")
    require(set(record.get("control_components", [])) <= {"VERSA"}, f"history_index:{record.get('id')}:invalid_control_component")
    require(isinstance(record.get("legacy_components"), list), f"history_index:{record.get('id')}:missing_legacy_components")

for route_path in (ROOT / "history_conversation/routes").glob("*.json"):
    route = json.loads(route_path.read_text(encoding="utf-8"))
    generation = route.get("architecture_generation")
    require(generation in {"VERAS_3", "LEGACY_PRE_VERAS_3"}, f"route:{route_path.name}:unknown_generation")
    serialized = json.dumps(route, ensure_ascii=False)
    if generation == "VERAS_3":
        require("TERRA_VERSA" not in serialized, f"route:{route_path.name}:legacy_executor_in_current_route")
        require(route.get("governance_binding", {}).get("control_plane") == "VERSA", f"route:{route_path.name}:missing_governance_binding")
        for entry in route.get("entries", []):
            if entry.get("capability") == "RESTRICTED_WRITE_EXECUTION":
                require(entry.get("source") == "VERSA" and entry.get("target") == "VERSA", f"route:{route_path.name}:execution_not_internal_to_versa")
    else:
        require(route.get("schema_version") == "1.0.0", f"route:{route_path.name}:legacy_schema_mismatch")

active_contracts = [
    "schemas/route-trace.schema.json",
    "schemas/conversation-summary.schema.json",
    "schemas/conversation-history-index.schema.json",
    "governance/versa.md",
]
for rel in active_contracts:
    text = (ROOT / rel).read_text(encoding="utf-8")
    require("TERRA_VERSA" not in text, f"active_contract:{rel}:legacy_executor_reference")

report = {"status": "PASS" if not errors else "FAIL", "checks": checks, "errors": errors}
print(json.dumps(report, ensure_ascii=False, indent=2))
sys.exit(1 if errors else 0)

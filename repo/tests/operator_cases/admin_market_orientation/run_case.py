#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


CASE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[3]
BUNDLE = CASE / "registration_bundle.json"
errors: list[str] = []
checks = 0


def require(condition: bool, message: str) -> None:
    global checks
    checks += 1
    if not condition:
        errors.append(message)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_record(record_name: str, schema_name: str, record: dict[str, Any]) -> None:
    schema_path = ROOT / "schemas" / f"{schema_name}.schema.json"
    require(schema_path.is_file(), f"registry_schema_missing:{schema_name}")
    if not schema_path.is_file():
        return
    schema = load(schema_path)
    for error in Draft202012Validator(schema).iter_errors(record):
        errors.append(f"record_schema:{record_name}:{error.json_path}:{error.message}")


data = load(BUNDLE)
records = data["records"]

schema_map = {
    "academic_turn": "academic-turn",
    "orientation": "orientation",
    "orientation_decision": "orientation-decision",
    "research_delta": "research-delta",
    "banca_opinion": "opinion",
    "projection_plan": "document-projection-plan",
    "consistency": "cross-document-consistency",
    "evidence_coverage": "evidence-coverage",
}

require(data["canonical_research_mutation"] is False, "fixture_must_not_mutate_canonical_research")
require(set(records) == set(schema_map), "registration_record_inventory")
for record_name, schema_name in schema_map.items():
    validate_record(record_name, schema_name, records[record_name])

turn = records["academic_turn"]
orientation = records["orientation"]
decision = records["orientation_decision"]
delta = records["research_delta"]
opinion = records["banca_opinion"]
plan = records["projection_plan"]
consistency = records["consistency"]
coverage = records["evidence_coverage"]

require(turn["requires_mecai"] is True and turn["requires_banca"] is True, "academic_turn_requires_roles")
require(orientation["requires_user_decision"] is True, "orientation_requires_researcher_decision")
require(decision["decision"] == "PARTIALLY_APPROVED", "decision_is_partial")
require(decision["orientation_id"] == orientation["orientation_id"], "decision_orientation_link")
require(delta.get("orientation_decision_id") == decision["decision_id"], "delta_decision_link")
require(set(delta.get("approved_action_ids", [])) == set(decision["approved_action_ids"]), "delta_approved_actions_exact")
require("ADMIN-A5" not in json.dumps(delta), "rejected_action_excluded_from_delta")

approved = set(decision["approved_action_ids"])
for change in delta["proposed_changes"]:
    action_refs = {item for item in change.get("source_record_ids", []) if item.startswith("ADMIN-A")}
    require(bool(action_refs), f"change_without_action_reference:{change['entity_id']}")
    require(action_refs.issubset(approved), f"unapproved_action_in_change:{change['entity_id']}")

require(opinion["outcome"] in {"PASS", "PASS_WITH_WARNINGS"}, "banca_delta_pass")
require(plan["opinion_id"] == opinion["opinion_id"], "plan_opinion_link")
require(plan["delta_id"] == delta["delta_id"], "plan_delta_link")
require(set(item["document"] for item in plan["documents"]) == {"ARTICLE", "PREPROJECT", "DISSERTATION", "DOCTORAL_AGENDA"}, "four_document_projection")
require(consistency["verdict"] == "PASS", "consistency_pass")
require(all(consistency["invariants"].values()), "all_consistency_invariants_pass")
require(coverage["accepted_claims_without_accepted_evidence"] == 0, "no_unsupported_accepted_claim")
require(any(item["claim_status"] == "REJECTED" for item in coverage["claims"]), "causal_overclaim_recorded_as_rejected")

literature = data["literature"]
require(len(literature) >= 8, "literature_minimum_eight_records")
require(all(item["status"] == "PROVISIONAL_FETCHED" for item in literature), "literature_kept_provisional")
require(any("Kotler" in item["authors"] for item in literature), "kotler_present")
require(min(item["year"] for item in literature) <= 1994, "classic_literature_present")
require(max(item["year"] for item in literature) >= 2024, "recent_literature_present")
require(len({item["journal"] for item in literature}) >= 6, "literature_source_diversity")

article = (CASE / "article.md").read_text(encoding="utf-8")
project = (CASE / "research_project.md").read_text(encoding="utf-8")
masters = (CASE / "masters_reflection.md").read_text(encoding="utf-8")
doctoral = (CASE / "doctoral_preagenda.md").read_text(encoding="utf-8")
article_words = len(article.split())
project_words = len(project.split())

require(2600 <= article_words <= 3400, f"article_page_proxy:{article_words}")
require(900 <= project_words <= 1400, f"project_page_proxy:{project_words}")
require(article_words == data["deliverables"]["article"]["word_count"], "article_word_count_registered")
require(project_words == data["deliverables"]["research_project"]["word_count"], "project_word_count_registered")
require("não apresenta resultados empíricos" in article.lower(), "article_no_fabricated_results_disclosure")
require("hipóteses são provisórias" in project.lower(), "project_provisional_hypotheses")
require("não deve prometer causalidade" in masters.lower(), "masters_causal_limit")
require("não constitui tese" in doctoral.lower(), "doctoral_not_thesis")
require("ADMIN-A5" not in article and "ADMIN-A5" not in project, "rejected_action_not_rendered")

report = {
    "case_id": data["case_id"],
    "status": "PASS" if not errors else "FAIL",
    "checks": checks,
    "errors": errors,
    "page_proxies": {
        "article_words": article_words,
        "article_target_pages": 8,
        "research_project_words": project_words,
        "research_project_target_pages": 4,
    },
    "automatic_registration": {
        "records_expected": len(schema_map),
        "records_present": len(records),
        "orientation_to_decision": decision["orientation_id"] == orientation["orientation_id"],
        "decision_to_delta": delta.get("orientation_decision_id") == decision["decision_id"],
        "delta_to_opinion": plan["opinion_id"] == opinion["opinion_id"],
        "four_document_projection": len(plan["documents"]) == 4,
    },
}
print(json.dumps(report, ensure_ascii=False, indent=2))
sys.exit(1 if errors else 0)

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "local_llm" / "config"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_temporal_contract_uses_onset_161():
    contract = load_json(ROOT / "rieth_idv13_dataset_contract.json")
    assert contract["y"]["fault_onset_sample"] == 161
    assert contract["y"]["idv13_test_rule"] == "0 for sample 1..160; 1 for sample 161..960"
    assert contract["y"]["temporal_correction"]["previous_fault_onset_sample"] == 160


def test_representation_contract_is_symmetric_and_normal_only():
    contract = load_json(CONFIG / "representation_contract.json")
    assert contract["variables"]["count"] == 52
    assert contract["window"]["window_samples"] == 20
    assert contract["window"]["stride_samples"] == 5
    assert contract["window"]["evaluation_interval_minutes"] == 15
    assert contract["normal_reference"]["idv13_used_for_fit_or_selection"] is False
    assert set(contract["payload"]["top_level_fields"]) == {
        "sample_interval_minutes", "representation", "variables"
    }
    assert "blind_run_id" in contract["payload"]["metadata_not_delivered"]
    assert set(contract["payload"]["per_variable_fields"]) == {
        "variable", "start_z", "end_z", "mean_z", "min_z", "max_z", "slope_z_per_sample"
    }


def test_dpca_and_h3_references_are_faultfree_training_only():
    dpca = load_json(CONFIG / "dpca_reference.json")
    assert dpca["validation"]["target_fault_data_accessed"] is False
    assert dpca["lag_selection"]["selected_lags"] == 5
    assert dpca["model"]["n_components"] == 150
    assert dpca["model"]["threshold_quantile"] == 0.99
    h3 = load_json(CONFIG / "h3_evidence_reference.json")
    assert h3["target_fault_data_accessed"] is False
    assert len(h3["thresholds"]) == 52


def test_evaluation_is_refrozen_and_historical_candidate_remains_unfrozen():
    evaluation = load_json(CONFIG / "evaluation_contract.json")
    assert evaluation["fault_onset_sample"] == 161
    assert evaluation["h2"]["refresh_strides"]["derived_value"] == 4
    assert evaluation["h2"]["refresh_strides"]["independently_tunable"] is False
    assert evaluation["h2"]["confirmation_policy_id"] == "FIRST_INDICATION_CONCURRENT_FULL_SAMPLE_REFRESH_V1"
    assert evaluation["h2"]["dpca_persistence"]["count"] == 3
    assert evaluation["dataset_roles"]["llm_target"]["simulation_runs"] == 50
    assert evaluation["dataset_roles"]["llm_normal_holdout"]["simulation_runs"] == 50
    assert evaluation["dataset_roles"]["dpca_target"]["simulation_runs"] == 500
    assert evaluation["dataset_roles"]["dpca_normal_holdout"]["simulation_runs"] == 500
    candidate = load_json(CONFIG / "formal.candidate.json")
    assert candidate["status"] == "CANDIDATE_FOR_RESEARCHER_FREEZE"
    assert candidate["methodology_frozen"] is False
    assert candidate["scientific_execution_permitted"] is False
    scope = candidate["formal_scope"]
    assert scope["llm_target_run_limit"] == 50
    assert scope["llm_normal_holdout_run_limit"] == 50
    assert scope["dpca_target_run_limit"] == 500
    assert scope["dpca_normal_holdout_run_limit"] == 500
    assert "normal_run_limit" not in candidate
    assert "test_run_limit" not in candidate
    assert candidate["llm"]["n_gpu_layers"] == 0
    assert candidate["llm"]["n_gpu_layers_status"] == "OPERATIONAL_FROZEN_CANDIDATE"
    assert candidate["dpca"]["target_formal_runs"] == 500
    assert candidate["dpca"]["normal_holdout_formal_runs"] == 500
    assert candidate["checkpoint_resume"]["enabled"] is True
    assert candidate["run_selections"]["llm_target"]["seed"] == 42
    assert candidate["run_selections"]["llm_normal_holdout"]["seed"] == 43


def test_historical_candidate_is_preserved_and_refrozen_formal_stays_blocked():
    candidate = load_json(CONFIG / "formal.candidate.json")
    assert candidate["status"] == "CANDIDATE_FOR_RESEARCHER_FREEZE"
    assert candidate["methodology_frozen"] is False
    formal_path = CONFIG / "formal.json"
    formal = load_json(formal_path)
    assert formal["status"] == "FORMAL_REFROZEN_FULL_WINDOW_REFRESH"
    assert formal["method_freeze_id"] == "TEP-METHOD-FREEZE-20260815-FULL-WINDOW-REFRESH"
    assert formal["methodology_frozen"] is True
    assert formal["scientific_execution_permitted"] is False


def test_formal_wrapper_has_explicit_second_gate():
    wrapper = (ROOT.parents[1] / "scripts" / "run_formal_offline.ps1").read_text(encoding="utf-8")
    assert "scientific_execution_permitted -ne $true" in wrapper
    assert "scientific_execution_permitted is false" in wrapper


def test_h3_schema_requires_structured_claim_enum():
    schema = load_json(CONFIG / "output_schema.json")
    evidence = schema["properties"]["evidence"]["items"]
    assert evidence["required"] == ["variable", "claim", "observation"]
    assert evidence["properties"]["claim"]["enum"] == [
        "HIGH", "LOW", "INCREASE", "REDUCTION", "VARIABILITY"
    ]


def test_faultfree_testing_audit_is_exact():
    audit = load_json(ROOT / "rieth_faultfree_testing_audit.json")
    assert audit["source"]["hash_matches"] is True
    assert audit["source"]["observed_sha256"] == "4f45afafa469793eeb7203fb9ed10ed0b1724c73c9c95537f15a0889ade0ebd4"
    assert audit["r_audit"]["simulation_runs"] == 500
    assert audit["r_audit"]["samples_per_run"] == 960
    assert audit["r_audit"]["x_count"] == 52
    assert audit["llm_inference_executed"] is False

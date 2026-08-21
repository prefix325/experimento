from pathlib import Path

import pandas as pd

from tep_local.selection import (
    apply_blind_mapping_all,
    apply_run_selection,
    load_run_selection,
    parse_run_block,
    reproduce_selection,
)


CONFIG = Path(__file__).resolve().parents[1] / "config" / "formal_run_selection.json"
NORMAL_CONFIG = Path(__file__).resolve().parents[1] / "config" / "formal_normal_holdout_selection.json"


def test_formal_selection_is_reproducible_and_excludes_development_runs():
    selection = load_run_selection(CONFIG)
    selected = selection["selected_simulation_runs"]
    assert selected == reproduce_selection(42)
    assert len(selected) == len(set(selected)) == 50
    assert not set(range(1, 11)).intersection(selected)
    assert selection["selected_list_sha256"] == "2c4cf612fe72162dcd1b27f1f90dfc8145f9086fc5c0a6ac9239518655978adf"


def test_normal_holdout_selection_seed_43_is_reproducible():
    selection = load_run_selection(NORMAL_CONFIG)
    selected = selection["selected_simulation_runs"]
    assert selection["seed"] == 43
    assert selected == reproduce_selection(43, 1, 500, 50)
    assert len(selected) == len(set(selected)) == 50
    assert min(selected) >= 1 and max(selected) <= 500
    assert selection["selected_list_sha256"] == (
        "fa86d617142fd5d853f92370c4aa9f10603f74b0e2f440df59c03c15248f84e6"
    )


def test_mapping_is_internal_and_blind_ids_are_not_source_ids():
    selection = load_run_selection(CONFIG)
    frame = pd.DataFrame({
        "blind_run_id": [f"RUN_{run:06d}" for run in selection["selected_simulation_runs"]],
        "sample": [1] * 50,
    })
    selected, ordered = apply_run_selection(frame, selection)
    assert len(ordered) == 50
    assert all(value.startswith("BLIND_") for value in ordered)
    assert not any(value.startswith("RUN_") for value in selected["blind_run_id"])
    assert parse_run_block("1-3,10", ordered) == [ordered[0], ordered[1], ordered[2], ordered[9]]


def test_dpca_mapping_preserves_complete_500_run_universe():
    frame = pd.DataFrame({
        "blind_run_id": [f"RUN_{run:06d}" for run in range(1, 501)],
        "sample": [1] * 500,
    })
    mapped, ordered = apply_blind_mapping_all(frame, 42)
    assert len(ordered) == len(set(ordered)) == 500
    assert mapped["blind_run_id"].nunique() == 500
    assert all(value.startswith("BLIND_") for value in ordered)


def test_normal_holdout_namespace_uses_the_same_opaque_mapping():
    selection = load_run_selection(NORMAL_CONFIG)
    selected_runs = selection["selected_simulation_runs"]
    frame = pd.DataFrame({
        "blind_run_id": [f"NORMAL_HOLDOUT_{run:06d}" for run in selected_runs],
        "sample": [1] * 50,
    })
    mapped, ordered = apply_run_selection(frame, selection)
    assert list(mapped["blind_run_id"]) == sorted(ordered)
    assert all(not value.startswith("NORMAL_HOLDOUT_") for value in mapped["blind_run_id"])

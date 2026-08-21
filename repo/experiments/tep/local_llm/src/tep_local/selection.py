from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

import pandas as pd

from .hashing import sha256_file


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def reproduce_selection(
    seed: int = 42,
    eligible_first: int = 11,
    eligible_last: int = 500,
    sample_size: int = 50,
) -> list[int]:
    eligible = list(range(int(eligible_first), int(eligible_last) + 1))
    return sorted(random.Random(seed).sample(eligible, int(sample_size)))


def blind_id_for_run(simulation_run: int, seed: int = 42) -> str:
    value = f"psqza-formal-v1:{seed}:{int(simulation_run)}".encode("utf-8")
    return "BLIND_" + hashlib.sha256(value).hexdigest()[:16].upper()


def _source_to_blind(
    available: set[str], simulation_runs: list[int], seed: int
) -> dict[str, str]:
    candidates = []
    for prefix in ("RUN_", "NORMAL_HOLDOUT_"):
        mapping = {
            f"{prefix}{simulation_run:06d}": blind_id_for_run(simulation_run, seed)
            for simulation_run in simulation_runs
        }
        if set(mapping).issubset(available):
            candidates.append(mapping)
    if len(candidates) != 1:
        raise RuntimeError("Blind dataset must contain exactly one supported complete run-ID namespace")
    return candidates[0]


def load_run_selection(path: str | Path, expected_file_sha256: str | None = None) -> dict[str, Any]:
    path = Path(path)
    observed_file_hash = sha256_file(path)
    if expected_file_sha256 is not None and observed_file_hash != expected_file_sha256:
        raise RuntimeError("Formal run-selection hash mismatch")
    selection = json.loads(path.read_text(encoding="utf-8"))
    selected = selection.get("selected_simulation_runs")
    universe = selection.get("eligible_universe") or {}
    first = int(universe.get("first", -1))
    last = int(universe.get("last", -1))
    sample_size = int(selection.get("sample_size", -1))
    if int(universe.get("count", -1)) != last - first + 1:
        raise RuntimeError("Formal run-selection universe count mismatch")
    if selected != reproduce_selection(int(selection.get("seed", -1)), first, last, sample_size):
        raise RuntimeError("Formal run selection does not reproduce from its declared procedure")
    if len(selected) != sample_size or len(set(selected)) != sample_size or any(run < first or run > last for run in selected):
        raise RuntimeError("Formal run selection violates the eligible universe")
    if canonical_sha256(selected) != selection.get("selected_list_sha256"):
        raise RuntimeError("Formal selected-list hash mismatch")
    mapping = [
        {"simulationRun": run, "blind_run_id": blind_id_for_run(run, int(selection["seed"]))}
        for run in selected
    ]
    if canonical_sha256(mapping) != selection.get("blind_mapping_sha256"):
        raise RuntimeError("Formal blind mapping hash mismatch")
    selection["file_sha256"] = observed_file_hash
    selection["mapping"] = mapping
    return selection


def apply_run_selection(frame: pd.DataFrame, selection: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    available = set(frame["blind_run_id"].astype(str).unique())
    selected_runs = [int(item["simulationRun"]) for item in selection["mapping"]]
    source_to_blind = _source_to_blind(available, selected_runs, int(selection["seed"]))
    selected = frame[frame["blind_run_id"].isin(source_to_blind)].copy()
    selected["blind_run_id"] = selected["blind_run_id"].map(source_to_blind)
    ordered_blind_ids = [item["blind_run_id"] for item in selection["mapping"]]
    if set(selected["blind_run_id"].unique()) != set(ordered_blind_ids):
        raise RuntimeError("Blind mapping failed")
    return selected.sort_values(["blind_run_id", "sample"]).reset_index(drop=True), ordered_blind_ids


def apply_blind_mapping_all(frame: pd.DataFrame, seed: int = 42) -> tuple[pd.DataFrame, list[str]]:
    available = set(frame["blind_run_id"].astype(str).unique())
    source_to_blind = _source_to_blind(available, list(range(1, 501)), seed)
    mapped = frame[frame["blind_run_id"].isin(source_to_blind)].copy()
    mapped["blind_run_id"] = mapped["blind_run_id"].map(source_to_blind)
    ordered = [blind_id_for_run(simulation_run, seed) for simulation_run in range(1, 501)]
    return mapped.sort_values(["blind_run_id", "sample"]).reset_index(drop=True), ordered


def apply_selection_to_ground_truth(truth: pd.DataFrame, selection: dict[str, Any]) -> pd.DataFrame:
    mapping = {int(item["simulationRun"]): item["blind_run_id"] for item in selection["mapping"]}
    selected = truth[truth["simulationRun"].isin(mapping)].copy()
    selected["blind_run_id"] = selected["simulationRun"].map(mapping)
    if set(selected["blind_run_id"].unique()) != set(mapping.values()):
        raise RuntimeError("Ground-truth selection mapping failed")
    return selected.sort_values(["blind_run_id", "sample"]).reset_index(drop=True)


def apply_blind_mapping_to_ground_truth(truth: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    expected = set(range(1, 501))
    observed = set(truth["simulationRun"].astype(int).unique())
    if not expected.issubset(observed):
        raise RuntimeError("Ground truth does not contain the complete 500-run DPCA universe")
    mapped = truth[truth["simulationRun"].isin(expected)].copy()
    mapped["blind_run_id"] = mapped["simulationRun"].map(
        lambda value: blind_id_for_run(int(value), seed)
    )
    return mapped.sort_values(["blind_run_id", "sample"]).reset_index(drop=True)


def parse_run_block(specification: str | None, ordered_blind_ids: list[str]) -> list[str]:
    if not specification:
        return list(ordered_blind_ids)
    ordinals: set[int] = set()
    for item in specification.split(","):
        token = item.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start, end = int(start_text), int(end_text)
            if start > end:
                raise ValueError("Run-block range must be ascending")
            ordinals.update(range(start, end + 1))
        else:
            ordinals.add(int(token))
    if not ordinals or min(ordinals) < 1 or max(ordinals) > len(ordered_blind_ids):
        raise ValueError("Run-block ordinals are outside the formal selection")
    return [ordered_blind_ids[index - 1] for index in sorted(ordinals)]

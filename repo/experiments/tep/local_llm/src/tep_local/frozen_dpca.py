from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .constants import X_COLUMNS
from .dpca import DPCAModel
from .hashing import sha256_file
from .normalization import Standardizer


@dataclass(frozen=True)
class FrozenDPCA:
    standardizer: Standardizer
    model: DPCAModel
    reference_sha256: str
    artifact_sha256: str


def _scalar(archive: Any, key: str, cast):
    value = np.asarray(archive[key])
    if value.shape != (1,):
        raise RuntimeError(f"Frozen DPCA scalar {key} has invalid shape")
    return cast(value[0])


def load_frozen_dpca(
    reference_path: str | Path,
    artifact_path: str | Path,
    expected_reference_sha256: str,
    expected_artifact_sha256: str,
    expected_parameters: dict[str, Any],
) -> FrozenDPCA:
    reference_path = Path(reference_path)
    artifact_path = Path(artifact_path)
    observed_reference_hash = sha256_file(reference_path)
    observed_artifact_hash = sha256_file(artifact_path)
    if observed_reference_hash != expected_reference_sha256:
        raise RuntimeError("Frozen DPCA reference hash mismatch")
    if observed_artifact_hash != expected_artifact_sha256:
        raise RuntimeError("Frozen DPCA artifact hash mismatch")

    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    if reference.get("input_cohort") != "FaultFree Training only":
        raise RuntimeError("Frozen DPCA reference is not normal-only")
    if reference.get("validation", {}).get("target_fault_data_accessed") is not False:
        raise RuntimeError("Frozen DPCA reference lacks target-fault-blind provenance")
    declared_artifact = reference.get("frozen_artifact") or {}
    if declared_artifact.get("sha256") != observed_artifact_hash:
        raise RuntimeError("Frozen DPCA artifact does not match its reference declaration")

    required = {"mean", "scale", "lags", "loadings", "eigenvalues", "t2_limit", "spe_limit", "persistence"}
    with np.load(artifact_path, allow_pickle=False) as archive:
        if set(archive.files) != required:
            raise RuntimeError("Frozen DPCA artifact keys mismatch")
        mean = np.asarray(archive["mean"], dtype=np.float64).copy()
        scale = np.asarray(archive["scale"], dtype=np.float64).copy()
        loadings = np.asarray(archive["loadings"], dtype=np.float64).copy()
        eigenvalues = np.asarray(archive["eigenvalues"], dtype=np.float64).copy()
        lags = _scalar(archive, "lags", int)
        t2_limit = _scalar(archive, "t2_limit", float)
        spe_limit = _scalar(archive, "spe_limit", float)
        persistence = _scalar(archive, "persistence", int)

    n_components = int(expected_parameters["n_components"])
    expected_dimension = len(X_COLUMNS) * (lags + 1)
    if mean.shape != (len(X_COLUMNS),) or scale.shape != (len(X_COLUMNS),):
        raise RuntimeError("Frozen DPCA normalizer shape mismatch")
    if loadings.shape != (expected_dimension, n_components) or eigenvalues.shape != (n_components,):
        raise RuntimeError("Frozen DPCA PCA shape mismatch")
    if np.any(scale <= 0) or np.any(eigenvalues <= 0):
        raise RuntimeError("Frozen DPCA contains invalid scales or eigenvalues")

    checks = {
        "lags": (lags, int(expected_parameters["lags"])),
        "persistence": (persistence, int(expected_parameters["alarm_persistence"])),
        "t2_limit": (t2_limit, float(expected_parameters["t2_limit"])),
        "spe_q_limit": (spe_limit, float(expected_parameters["spe_q_limit"])),
    }
    for name, (observed, expected) in checks.items():
        if isinstance(expected, float):
            matches = math.isclose(observed, expected, rel_tol=0.0, abs_tol=1e-12)
        else:
            matches = observed == expected
        if not matches:
            raise RuntimeError(f"Frozen DPCA parameter mismatch: {name}")

    for array in (mean, scale, loadings, eigenvalues):
        array.flags.writeable = False
    return FrozenDPCA(
        standardizer=Standardizer(mean=mean, scale=scale),
        model=DPCAModel(
            lags=lags,
            loadings=loadings,
            eigenvalues=eigenvalues,
            t2_limit=t2_limit,
            spe_limit=spe_limit,
            persistence=persistence,
        ),
        reference_sha256=observed_reference_hash,
        artifact_sha256=observed_artifact_hash,
    )

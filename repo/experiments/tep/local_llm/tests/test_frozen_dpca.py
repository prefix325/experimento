import json
from pathlib import Path

import numpy as np
import pytest

from tep_local.constants import X_COLUMNS
from tep_local.frozen_dpca import load_frozen_dpca
from tep_local.hashing import sha256_file


def create_reference(tmp_path: Path):
    artifact = tmp_path / "model.npz"
    lags = 1
    components = 2
    np.savez(
        artifact,
        mean=np.zeros(len(X_COLUMNS)),
        scale=np.ones(len(X_COLUMNS)),
        lags=np.asarray([lags], dtype=np.int64),
        loadings=np.zeros((len(X_COLUMNS) * (lags + 1), components)),
        eigenvalues=np.ones(components),
        t2_limit=np.asarray([10.0]),
        spe_limit=np.asarray([20.0]),
        persistence=np.asarray([3], dtype=np.int64),
    )
    artifact_hash = sha256_file(artifact)
    reference = tmp_path / "reference.json"
    reference.write_text(json.dumps({
        "input_cohort": "FaultFree Training only",
        "validation": {"target_fault_data_accessed": False},
        "frozen_artifact": {"sha256": artifact_hash},
    }), encoding="utf-8")
    return reference, artifact, artifact_hash


def test_frozen_dpca_loads_without_refitting(tmp_path):
    reference, artifact, artifact_hash = create_reference(tmp_path)
    frozen = load_frozen_dpca(
        reference, artifact, sha256_file(reference), artifact_hash,
        {"lags": 1, "n_components": 2, "t2_limit": 10.0, "spe_q_limit": 20.0, "alarm_persistence": 3},
    )
    assert frozen.model.lags == 1
    assert frozen.model.t2_limit == 10.0
    assert frozen.standardizer.mean.flags.writeable is False


def test_frozen_dpca_reference_hash_mismatch_aborts(tmp_path):
    reference, artifact, artifact_hash = create_reference(tmp_path)
    with pytest.raises(RuntimeError, match="reference hash mismatch"):
        load_frozen_dpca(
            reference, artifact, "0" * 64, artifact_hash,
            {"lags": 1, "n_components": 2, "t2_limit": 10.0, "spe_q_limit": 20.0, "alarm_persistence": 3},
        )

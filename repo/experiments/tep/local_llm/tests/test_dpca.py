import numpy as np
import pandas as pd

from tep_local.constants import X_COLUMNS
from tep_local.dpca import DPCAModel
from tep_local.normalization import Standardizer


def _frame(run_id: str, rows: int, seed: int, shift: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    values = rng.normal(loc=shift, scale=1.0, size=(rows, len(X_COLUMNS)))
    frame = pd.DataFrame(values, columns=X_COLUMNS)
    frame.insert(0, "sample", np.arange(1, rows + 1))
    frame.insert(0, "blind_run_id", run_id)
    return frame


def test_dpca_trains_on_supplied_normal_reference_and_scores_each_sample():
    normal = pd.concat([_frame("NORMAL_000001", 80, 1), _frame("NORMAL_000002", 80, 2)], ignore_index=True)
    test = _frame("RUN_000001", 60, 3, shift=2.0)
    scaler = Standardizer.fit(normal)
    model = DPCAModel.fit(
        scaler.transform_frame(normal),
        lags=2,
        n_components=None,
        variance_target=0.9,
        threshold_quantile=0.99,
        persistence=2,
    )
    scores = model.score(scaler.transform_frame(test))
    assert len(scores) == 60
    assert scores.iloc[:2]["t2"].isna().all()
    assert scores.iloc[2:]["t2"].notna().all()
    assert scores.iloc[2:]["spe"].notna().all()
    assert model.t2_limit > 0
    assert model.spe_limit >= 0

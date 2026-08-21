from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def load_config(path: str | Path, require_frozen: bool = False) -> dict[str, Any]:
    path = Path(path)
    raw = path.read_bytes()
    config = json.loads(raw)
    if require_frozen and config.get("methodology_frozen") is not True:
        raise ValueError("Formal configuration is not methodologically frozen")
    return config


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def config_sha256(config: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(config)).hexdigest()


def validate_development_config(config: dict[str, Any]) -> None:
    required_positive = ["window_samples", "stride_samples", "sample_interval_minutes"]
    for key in required_positive:
        value = config.get(key)
        if not isinstance(value, int) or value <= 0:
            raise ValueError(f"{key} must be a positive integer")

    dpca = config["dpca"]
    if not isinstance(dpca.get("lags"), int) or dpca["lags"] < 0:
        raise ValueError("dpca.lags must be a non-negative integer")
    if not 0 < float(dpca["variance_target"]) <= 1:
        raise ValueError("dpca.variance_target must be in (0, 1]")
    if not 0 < float(dpca["threshold_quantile"]) < 1:
        raise ValueError("dpca.threshold_quantile must be in (0, 1)")
    if int(dpca["alarm_persistence"]) <= 0:
        raise ValueError("dpca.alarm_persistence must be positive")

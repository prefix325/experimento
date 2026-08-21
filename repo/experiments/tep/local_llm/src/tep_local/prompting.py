from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .constants import X_COLUMNS
from .leakage import validate_llm_payload
from .windowing import CausalWindow


def build_payload(window: CausalWindow, representation: str, sample_interval_minutes: int) -> dict:
    variables = []
    for variable in X_COLUMNS:
        values = window.frame[variable].to_numpy(dtype=float)
        slope = float(np.polyfit(np.arange(len(values), dtype=float), values, 1)[0]) if len(values) > 1 else 0.0
        variables.append({
            "variable": variable,
            "start_z": round(float(values[0]), 4),
            "end_z": round(float(values[-1]), 4),
            "mean_z": round(float(values.mean()), 4),
            "min_z": round(float(values.min()), 4),
            "max_z": round(float(values.max()), 4),
            "slope_z_per_sample": round(slope, 4),
        })
    payload = {
        "sample_interval_minutes": int(sample_interval_minutes),
        "representation": representation,
        "variables": variables,
    }
    validate_llm_payload(payload)
    return payload


def render_prompt(payload: dict, template_path: str | Path) -> str:
    validate_llm_payload(payload)
    template = Path(template_path).read_text(encoding="utf-8")
    prompt = template.format(payload_json=json.dumps(payload, sort_keys=True, ensure_ascii=False))
    validate_llm_payload({"rendered_prompt": prompt})
    return prompt

from __future__ import annotations

import json
import re
from typing import Any

from .constants import (
    LLM_FORBIDDEN_IDENTIFIER_KEYS,
    LLM_FORBIDDEN_TEMPORAL_KEYS,
    PROHIBITED_KEYS,
    PROHIBITED_TEXT_PATTERNS,
)


class LeakageError(ValueError):
    pass


def _walk(value: Any, path: str = "$"):
    if isinstance(value, dict):
        for key, child in value.items():
            yield path, key, child
            yield from _walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]")


def validate_llm_payload(payload: dict[str, Any]) -> None:
    violations: list[str] = []
    for path, key, _ in _walk(payload):
        normalized = str(key).strip().lower()
        if normalized in PROHIBITED_KEYS:
            violations.append(f"prohibited key {key!r} at {path}")
        if normalized in LLM_FORBIDDEN_TEMPORAL_KEYS:
            violations.append(f"absolute temporal key {key!r} at {path}")
        if normalized in LLM_FORBIDDEN_IDENTIFIER_KEYS:
            violations.append(f"internal identifier key {key!r} at {path}")

    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    for pattern in PROHIBITED_TEXT_PATTERNS:
        if re.search(pattern, serialized, flags=re.IGNORECASE):
            violations.append(f"prohibited text pattern {pattern!r}")

    if violations:
        raise LeakageError("LLM payload leakage detected: " + "; ".join(violations))

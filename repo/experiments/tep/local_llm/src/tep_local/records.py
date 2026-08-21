from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_internal_llm_record(
    *,
    experiment_id: str,
    window,
    payload: dict[str, Any],
    prompt_hash: str,
    model_hash: str | None,
    usage: dict[str, Any],
    inference_start: str,
    inference_end: str,
    latency_ms: int,
    output: dict[str, Any],
    sample_interval_minutes: int,
) -> dict[str, Any]:
    return {
        "experiment_id": experiment_id,
        "simulation_run_blind_id": window.blind_run_id,
        "window_id": int(window.window_id),
        "sample_start": int(window.sample_start),
        "sample_end": int(window.sample_end),
        "relative_time": (int(window.sample_end) - 1) * int(sample_interval_minutes),
        "prompt_hash": prompt_hash,
        "model_hash": model_hash,
        "input_token_count": usage.get("prompt_tokens"),
        "output_token_count": usage.get("completion_tokens"),
        "inference_start": inference_start,
        "inference_end": inference_end,
        "latency_ms": int(latency_ms),
        "llm_payload": payload,
        "decision": output["decision"],
        "evidence": output["evidence"],
        "summary": output["summary"],
    }


def append_jsonl(path: str | Path, record: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]

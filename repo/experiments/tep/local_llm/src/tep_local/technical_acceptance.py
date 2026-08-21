from __future__ import annotations

import json
import os
import re
import time
import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .constants import X_COLUMNS
from .hashing import sha256_file, sha256_text
from .llm_runtime import LlamaServer
from .offline import verify_mount_permissions, verify_network_none
from .prompting import render_prompt


STATUS = "POST_FREEZE_OPERATIONAL_AMENDMENT_SYNTHETIC_ACCEPTANCE"


def validate_acceptance_config(config: dict[str, Any]) -> None:
    if config.get("status") != "FORMAL_REFROZEN_FULL_WINDOW_REFRESH":
        raise RuntimeError("Acceptance requires the refrozen formal configuration")
    if config.get("methodology_frozen") is not True:
        raise RuntimeError("Acceptance requires methodology_frozen=true")
    if config.get("scientific_execution_permitted") is not False:
        raise RuntimeError(
            "Acceptance must run before scientific execution is authorized"
        )
    if int(config["llm"]["n_gpu_layers"]) == 0:
        raise RuntimeError("Acceptance requires nonzero GPU offload")


def fixed_synthetic_payload(config: dict[str, Any]) -> dict[str, Any]:
    variables = []
    for index, variable in enumerate(X_COLUMNS):
        offset = round(((index % 7) - 3) * 0.025, 4)
        variables.append({
            "variable": variable,
            "start_z": offset,
            "end_z": offset,
            "mean_z": offset,
            "min_z": offset,
            "max_z": offset,
            "slope_z_per_sample": 0.0,
        })
    return {
        "sample_interval_minutes": int(
            config["sample_interval_minutes"]
        ),
        "representation": config["representation"],
        "variables": variables,
    }


def gpu_offload_evidence(log_text: str) -> dict[str, Any]:
    lower = log_text.lower()
    cpu_fallback = (
        "no usable gpu found" in lower
        or "gpu-layers option will be ignored" in lower
    )
    cuda_backend = any(
        token in lower
        for token in (
            "ggml_cuda",
            "cuda0",
            "cuda :",
            "cuda backend",
        )
    )
    gpu_identified = any(
        token in lower
        for token in (
            "nvidia",
            "geforce",
            "device 0:",
        )
    )
    patterns = (
        r"offloaded\s+(\d+)\s*/\s*(\d+)\s+layers",
        r"offloading\s+(\d+)\s+repeating layers",
        r"offloaded\s+(\d+)\s+layers",
    )
    matches: list[tuple[int, int | None]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, lower):
            values = [int(value) for value in match.groups()]
            matches.append(
                (values[0], values[1] if len(values) > 1 else None)
            )
    offloaded_layers = max(
        (value[0] for value in matches), default=0
    )
    return {
        "cuda_backend_discovered": cuda_backend,
        "gpu_identified": gpu_identified,
        "offloaded_layers": offloaded_layers,
        "offload_observed": offloaded_layers > 0,
        "cpu_fallback_warning": cpu_fallback,
        "pass": (
            cuda_backend
            and gpu_identified
            and offloaded_layers > 0
            and not cpu_fallback
        ),
    }


def acceptance_startup_validator(log_text: str, elapsed_seconds: float) -> bool | None:
    evidence = gpu_offload_evidence(log_text)
    if evidence["pass"]:
        return True
    if evidence["cpu_fallback_warning"]:
        return False
    if "model loaded" in log_text.lower() and not evidence["offload_observed"]:
        return False
    return None


def _artifact_hashes(config_root: Path, config: dict[str, Any]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for name, specification in config["artifacts"].items():
        path = config_root / specification["file"]
        digest = sha256_file(path)
        if digest != specification["sha256"]:
            raise RuntimeError(f"Frozen artifact hash mismatch: {name}")
        observed[name] = digest
    return observed


def run_technical_acceptance(
    config: dict[str, Any],
    results_dir: str | Path,
    model_dir: str | Path,
    prompt_path: str | Path,
    schema_path: str | Path,
    operational_amendment: dict[str, Any],
) -> dict[str, Any]:
    validate_acceptance_config(config)
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    destination = results_dir / "technical_acceptance.json"
    inference_count = 0
    started = time.monotonic()
    base = {
        "status": STATUS,
        "method_freeze_id": config["method_freeze_id"],
        "scientific_result": False,
        "methodology_changes_permitted": False,
        "methodological_logic_changed": operational_amendment[
            "methodological_logic_changed"
        ],
        "target_informed_tuning": operational_amendment["target_informed_tuning"],
        "inference_runtime_parameter_changed": operational_amendment[
            "inference_runtime_parameter_changed"
        ],
        "changed_parameter": operational_amendment["changed_parameter"],
        "requested_max_output_tokens": int(config["llm"]["max_output_tokens"]),
        "base_formal_sha256": operational_amendment["base_formal_sha256"],
        "base_configuration_sha256": operational_amendment[
            "base_configuration_sha256"
        ],
        "effective_configuration_sha256": operational_amendment[
            "effective_configuration_sha256"
        ],
        "operational_amendment_id": operational_amendment["amendment_id"],
        "operational_amendment_sha256": operational_amendment["_sha256"],
        "input_source": "FIXED_SYNTHETIC_52_VARIABLE_NORMAL_LIKE_V1",
        "ZERO_TARGET_ACCESS": True,
        "ZERO_FAULTFREE_TESTING_ACCESS": True,
        "formal_scientific_execution_started": False,
        "docker_command": (
            base64.b64decode(os.environ["TECHNICAL_ACCEPTANCE_DOCKER_COMMAND_B64"]).decode("utf-8")
            if os.environ.get("TECHNICAL_ACCEPTANCE_DOCKER_COMMAND_B64")
            else None
        ),
        "container_image_id": os.environ.get("DOCKER_IMAGE_ID"),
        "container_image_digest": os.environ.get(
            "DOCKER_IMAGE_DIGEST"
        ),
        "network_mode": "none",
    }
    try:
        network = verify_network_none(
            results_dir / "network_check.json"
        )
        config_root = Path(schema_path).parent
        permissions = verify_mount_permissions(
            [model_dir, config_root], results_dir
        )
        verified = _artifact_hashes(config_root, config)
        prompt_path = Path(prompt_path)
        schema_path = Path(schema_path)
        payload = fixed_synthetic_payload(config)
        prompt = render_prompt(payload, prompt_path)
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        model_path = Path(model_dir) / config["llm"]["model_file"]
        model_hash = sha256_file(model_path)
        if model_hash != config["llm"]["model_sha256"]:
            raise RuntimeError("Frozen model hash mismatch")
        runtime_started = time.monotonic()
        with LlamaServer(
            model_path,
            config["llm"],
            results_dir / "logs",
            startup_validator=acceptance_startup_validator,
        ) as runtime:
            startup_seconds = time.monotonic() - runtime_started
            log_text = runtime.startup_log_text()
            offload = gpu_offload_evidence(log_text)
            if not offload["pass"]:
                raise RuntimeError(
                    "GPU initialization/offload evidence missing; CPU fallback prohibited"
                )
            inference_count = 1
            inference_started = time.monotonic()
            output, usage, latency_ms = runtime.infer(prompt, schema)
            inference_seconds = time.monotonic() - inference_started
        output_text = json.dumps(
            output,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        completion_tokens = int(usage.get("completion_tokens", 0))
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        finish_reason = usage.get("finish_reason")
        if finish_reason == "length":
            raise RuntimeError("Synthetic acceptance reached max_output_tokens")
        result = {
            **base,
            "verdict": "PASS",
            "inference_count": inference_count,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "network_none_verified": network[
                "network_none_verified"
            ],
            "mount_permissions": permissions,
            "frozen_artifacts_verified": verified,
            "model_sha256": model_hash,
            "prompt_input_sha256": sha256_text(prompt),
            "synthetic_payload_sha256": sha256_text(
                json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
            ),
            "output_sha256": sha256_text(output_text),
            "output_parser_result": "PASS",
            "finish_reason": finish_reason,
            "categorical_decision": output["decision"],
            "gpu_offload": offload,
            "startup_seconds": round(startup_seconds, 3),
            "inference_elapsed_seconds": round(
                inference_seconds, 3
            ),
            "request_latency_ms": latency_ms,
            "throughput": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "prompt_tokens_per_request_second": (
                    round(prompt_tokens / inference_seconds, 3)
                    if inference_seconds
                    else None
                ),
                "completion_tokens_per_request_second": (
                    round(
                        completion_tokens / inference_seconds, 3
                    )
                    if inference_seconds
                    else None
                ),
            },
            "elapsed_seconds": round(
                time.monotonic() - started, 3
            ),
        }
        destination.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return result
    except BaseException as exc:
        startup_log = results_dir / "llama-server.log"
        startup_text = (
            startup_log.read_text(encoding="utf-8", errors="replace")
            if startup_log.is_file()
            else ""
        )
        failure = {
            **base,
            "verdict": "FAIL",
            "inference_count": inference_count,
            "inference_stage": (
                "STARTED" if inference_count else "NOT_STARTED"
            ),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "error": f"{type(exc).__name__}: {exc}",
            "gpu_offload": gpu_offload_evidence(startup_text),
            "startup_log_sha256": (
                sha256_text(startup_text) if startup_text else None
            ),
            "elapsed_seconds": round(
                time.monotonic() - started, 3
            ),
        }
        destination.write_text(
            json.dumps(failure, indent=2, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )
        raise

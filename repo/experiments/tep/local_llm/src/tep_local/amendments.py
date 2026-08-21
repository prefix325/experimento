from __future__ import annotations

import json
from copy import deepcopy
from math import ceil
from pathlib import Path
from typing import Any

from .hashing import sha256_file
from .config import config_sha256


class AmendmentError(RuntimeError):
    pass


def load_operational_amendment(
    amendment_path: str | Path,
    formal_config_path: str | Path,
    formal_config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    amendment_path = Path(amendment_path)
    formal_config_path = Path(formal_config_path)
    amendment = json.loads(amendment_path.read_text(encoding="utf-8"))
    if amendment.get("amendment_type") != "POST_FREEZE_OPERATIONAL_AMENDMENT":
        raise AmendmentError("Unexpected operational amendment type")
    if amendment.get("status") != "AUTHORIZED_FOR_TECHNICAL_MATERIALIZATION":
        raise AmendmentError("Operational amendment is not authorized for materialization")
    if amendment.get("method_freeze_id") != formal_config.get("method_freeze_id"):
        raise AmendmentError("Operational amendment method-freeze mismatch")
    if sha256_file(formal_config_path) != amendment.get("base_formal_sha256"):
        raise AmendmentError("Operational amendment base formal.json hash mismatch")
    if config_sha256(formal_config) != amendment.get("base_configuration_sha256"):
        raise AmendmentError("Operational amendment base configuration hash mismatch")
    required_flags = {
        "methodological_logic_changed": False,
        "target_informed_tuning": False,
        "inference_runtime_parameter_changed": True,
    }
    for name, expected in required_flags.items():
        if amendment.get(name) is not expected:
            raise AmendmentError(f"Invalid operational amendment flag: {name}")
    if amendment.get("changed_parameter") != "/llm/max_output_tokens":
        raise AmendmentError("Operational amendment may change only max_output_tokens")
    if int(amendment.get("from", -1)) != 768 or int(amendment.get("to", -1)) != 1024:
        raise AmendmentError("Unexpected max_output_tokens amendment values")
    if int(formal_config["llm"]["max_output_tokens"]) != int(amendment["from"]):
        raise AmendmentError("Operational amendment before-value differs from formal.json")
    effective = deepcopy(formal_config)
    effective["llm"]["max_output_tokens"] = int(amendment["to"])
    if config_sha256(effective) != amendment.get("effective_configuration_sha256"):
        raise AmendmentError("Operational amendment effective configuration hash mismatch")
    amendment["_sha256"] = sha256_file(amendment_path)
    amendment["_path"] = str(amendment_path)
    return effective, amendment


def load_methodological_amendment(
    amendment_path: str | Path,
    formal_config_path: str | Path,
    formal_config: dict[str, Any],
) -> dict[str, Any]:
    amendment_path = Path(amendment_path)
    formal_config_path = Path(formal_config_path)
    amendment = json.loads(amendment_path.read_text(encoding="utf-8"))
    if amendment.get("amendment_type") != "POST_FREEZE_METHODOLOGICAL_AMENDMENT":
        raise AmendmentError("Unexpected methodological amendment type")
    if amendment.get("scientific_parameters_changed") is not True:
        raise AmendmentError("Methodological amendment must declare scientific_parameters_changed=true")
    if amendment.get("llm_inference_performed") is not False:
        raise AmendmentError("Methodological amendment must be inference-free at registration")
    if amendment.get("method_freeze_id") != (
        "TEP-METHOD-FREEZE-20260815-FULL-WINDOW-REFRESH"
    ):
        raise AmendmentError("Unexpected authoritative method-freeze id")
    if sha256_file(formal_config_path) != amendment.get(
        "refrozen_formal_sha256"
    ):
        raise AmendmentError(
            "Refrozen formal.json hash differs from methodological amendment"
        )
    frozen = amendment.get("frozen_parameters", {})
    if int(frozen.get("window_samples", -1)) != int(formal_config["window_samples"]):
        raise AmendmentError("Frozen window_samples differs from amendment")
    if int(frozen.get("stride_samples", -1)) != int(formal_config["stride_samples"]):
        raise AmendmentError("Frozen stride_samples differs from amendment")
    rule = amendment.get("new_rule", {})
    if rule.get("name") != (
        "FIRST_INDICATION_CONCURRENT_FULL_SAMPLE_REFRESH_V1"
    ):
        raise AmendmentError("Unsupported methodological amendment rule")
    expected_advances = ceil(
        int(formal_config["window_samples"])
        / int(formal_config["stride_samples"])
    )
    if int(rule.get("derived_refresh_strides", -1)) != expected_advances:
        raise AmendmentError("Amendment verification advances do not match window/stride")
    if rule.get("candidate_concurrency") is not True:
        raise AmendmentError("Concurrent confirmation candidates are required")
    if rule.get("derived_value_independently_tunable") is not False:
        raise AmendmentError("Derived refresh strides cannot be independently tunable")
    amendment["_sha256"] = sha256_file(amendment_path)
    amendment["_path"] = str(amendment_path)
    return amendment

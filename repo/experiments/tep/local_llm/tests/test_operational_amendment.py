import json
from pathlib import Path

from tep_local.amendments import load_operational_amendment
from tep_local.config import config_sha256
from tep_local.hashing import sha256_file


CONFIG = Path(__file__).resolve().parents[1] / "config"


def _differences(before, after, path=""):
    if isinstance(before, dict) and isinstance(after, dict):
        differences = []
        for key in sorted(set(before) | set(after)):
            differences.extend(
                _differences(before.get(key), after.get(key), f"{path}/{key}")
            )
        return differences
    return [] if before == after else [(path, before, after)]


def test_operational_amendment_is_exactly_one_runtime_parameter_overlay():
    formal_path = CONFIG / "formal.json"
    amendment_path = CONFIG / "post_freeze_operational_amendment_001.json"
    base = json.loads(formal_path.read_text(encoding="utf-8"))

    effective, amendment = load_operational_amendment(
        amendment_path, formal_path, base
    )

    assert sha256_file(formal_path) == amendment["base_formal_sha256"]
    assert config_sha256(base) == amendment["base_configuration_sha256"]
    assert config_sha256(effective) == amendment["effective_configuration_sha256"]
    assert _differences(base, effective) == [
        ("/llm/max_output_tokens", 768, 1024)
    ]
    assert amendment["methodological_logic_changed"] is False
    assert amendment["target_informed_tuning"] is False
    assert amendment["inference_runtime_parameter_changed"] is True

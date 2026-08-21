import json
from pathlib import Path

from tep_local.technical_acceptance import (
    acceptance_startup_validator,
    fixed_synthetic_payload,
    gpu_offload_evidence,
    validate_acceptance_config,
)


REPO = Path(__file__).resolve().parents[4]
FORMAL = (
    REPO
    / "experiments"
    / "tep"
    / "local_llm"
    / "config"
    / "formal.json"
)


def formal_config():
    return json.loads(FORMAL.read_text(encoding="utf-8"))


def test_synthetic_acceptance_payload_is_fixed_and_has_52_variables():
    config = formal_config()
    first = fixed_synthetic_payload(config)
    second = fixed_synthetic_payload(config)
    assert first == second
    assert len(first["variables"]) == 52
    assert {
        item["variable"] for item in first["variables"]
    } == {
        *(f"xmeas_{index}" for index in range(1, 42)),
        *(f"xmv_{index}" for index in range(1, 12)),
    }
    assert "simulationRun" not in json.dumps(first)
    assert "sample_end" not in json.dumps(first)


def test_acceptance_requires_refrozen_blocked_config_and_gpu_layers():
    config = formal_config()
    validate_acceptance_config(config)
    config["llm"]["n_gpu_layers"] = 0
    try:
        validate_acceptance_config(config)
    except RuntimeError as exc:
        assert "GPU offload" in str(exc)
    else:
        raise AssertionError("CPU-only acceptance was not rejected")


def test_gpu_offload_log_must_show_cuda_gpu_and_layers():
    log = (
        "ggml_cuda_init: found 1 CUDA devices\n"
        "device 0: NVIDIA GeForce RTX 4060\n"
        "load_tensors: offloaded 29/29 layers to GPU\n"
    )
    evidence = gpu_offload_evidence(log)
    assert evidence["pass"] is True
    assert evidence["offloaded_layers"] == 29


def test_cpu_fallback_log_fails_closed():
    log = (
        "warning: no usable GPU found\n"
        "warning: --gpu-layers option will be ignored\n"
    )
    evidence = gpu_offload_evidence(log)
    assert evidence["pass"] is False
    assert evidence["cpu_fallback_warning"] is True


def test_startup_validator_does_not_preempt_slow_model_loading():
    assert acceptance_startup_validator("initializing", 44.9) is None
    assert acceptance_startup_validator("loading model", 45.0) is None
    assert acceptance_startup_validator("loading model", 299.0) is None


def test_startup_validator_still_fails_immediately_on_cpu_fallback():
    assert acceptance_startup_validator("no usable GPU found", 1.0) is False


def test_startup_validator_rejects_loaded_model_with_zero_offloaded_layers():
    log = (
        "device_info: - CUDA0: NVIDIA GeForce RTX 4060\n"
        "load_tensors: offloaded 0/29 layers to GPU\n"
        "llama_server: model loaded\n"
    )
    assert acceptance_startup_validator(log, 60.0) is False

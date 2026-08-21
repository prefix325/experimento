import pytest

from tep_local.technical_acceptance import validate_acceptance_config


def test_technical_acceptance_requires_frozen_but_scientifically_blocked_config():
    validate_acceptance_config({
        "status": "FORMAL_REFROZEN_FULL_WINDOW_REFRESH",
        "methodology_frozen": True,
        "scientific_execution_permitted": False,
        "llm": {"n_gpu_layers": -1},
    })
    with pytest.raises(RuntimeError):
        validate_acceptance_config({
            "status": "FORMAL_REFROZEN_FULL_WINDOW_REFRESH",
            "methodology_frozen": True,
            "scientific_execution_permitted": True,
            "llm": {"n_gpu_layers": -1},
        })

import json

import pytest

from tep_local.llm_runtime import LlamaServer, validate_llm_output


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


def runtime(tmp_path):
    return LlamaServer(
        tmp_path / "model.gguf",
        {
            "port": 8080,
            "context_size": 4096,
            "n_gpu_layers": -1,
            "temperature": 0.0,
            "seed": 42,
            "max_output_tokens": 16,
            "request_timeout_seconds": 1,
        },
        tmp_path / "logs",
    )


def test_server_command_adds_dedicated_detailed_logging_only(tmp_path):
    subject = runtime(tmp_path)

    assert subject.command() == [
        "/app/llama-server",
        "--model", str(tmp_path / "model.gguf"),
        "--host", "127.0.0.1",
        "--port", "8080",
        "--ctx-size", "4096",
        "--n-gpu-layers", "-1",
        "--seed", "42",
        "--metrics",
        "--no-webui",
        "--log-file", str(tmp_path / "llama-server.log"),
        "--verbosity", "4",
        "--log-timestamps",
    ]


def test_startup_log_text_preserves_all_three_raw_sources(tmp_path):
    subject = runtime(tmp_path)
    subject.log_dir.mkdir(parents=True)
    subject.dedicated_log_path.write_text("CUDA0 model buffer\n", encoding="utf-8")
    subject.stdout_path.write_text("raw stdout\n", encoding="utf-8")
    subject.stderr_path.write_text("raw stderr\n", encoding="utf-8")

    captured = subject.startup_log_text()

    assert "CUDA0 model buffer" in captured
    assert "raw stdout" in captured
    assert "raw stderr" in captured


def test_output_limit_is_recorded(monkeypatch, tmp_path):
    body = {
        "choices": [{"finish_reason": "length", "message": {"content": '{"decision":'}}],
        "usage": {"completion_tokens": 16},
    }
    monkeypatch.setattr("tep_local.llm_runtime.requests.post", lambda *args, **kwargs: FakeResponse(body))
    subject = runtime(tmp_path)
    subject.log_dir.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="max_output_tokens"):
        subject.infer("prompt", {})

    failure = json.loads((subject.log_dir / "failed_llm_responses.jsonl").read_text())
    assert failure["reason"] == "output_token_limit"
    assert failure["response"]["usage"]["completion_tokens"] == 16


def test_invalid_json_is_recorded(monkeypatch, tmp_path):
    body = {
        "choices": [{"finish_reason": "stop", "message": {"content": "not-json"}}],
        "usage": {},
    }
    monkeypatch.setattr("tep_local.llm_runtime.requests.post", lambda *args, **kwargs: FakeResponse(body))
    subject = runtime(tmp_path)
    subject.log_dir.mkdir(parents=True)

    with pytest.raises(json.JSONDecodeError):
        subject.infer("prompt", {})

    failure = json.loads((subject.log_dir / "failed_llm_responses.jsonl").read_text())
    assert failure["reason"] == "invalid_json"


def test_effective_output_ceiling_and_finish_reason_are_auditable(
    monkeypatch, tmp_path
):
    observed = {}
    body = {
        "choices": [{
            "finish_reason": "stop",
            "message": {"content": json.dumps({
                "decision": "NORMAL",
                "evidence": [],
                "summary": "synthetic",
                "confidence": None,
            })},
        }],
        "usage": {"completion_tokens": 12},
    }

    def fake_post(*args, **kwargs):
        observed.update(kwargs["json"])
        return FakeResponse(body)

    monkeypatch.setattr("tep_local.llm_runtime.requests.post", fake_post)
    subject = runtime(tmp_path)
    subject.config["max_output_tokens"] = 1024

    _, usage, _ = subject.infer("synthetic prompt", {})

    assert observed["max_tokens"] == 1024
    assert usage["finish_reason"] == "stop"


def test_structured_evidence_claim_enum():
    validate_llm_output({
        "decision": "ANOMALY",
        "evidence": [{"variable": "xmeas_1", "claim": "INCREASE", "observation": "rising"}],
        "summary": "departure",
        "confidence": None,
    })
    with pytest.raises(ValueError, match="evidence claim"):
        validate_llm_output({
            "decision": "ANOMALY",
            "evidence": [{"variable": "xmeas_1", "claim": "TREND", "observation": "rising"}],
            "summary": "departure",
            "confidence": None,
        })

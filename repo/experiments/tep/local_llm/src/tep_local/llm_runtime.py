from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

import requests

from .constants import DECISIONS, EVIDENCE_CLAIMS


class LlamaServer:
    def __init__(
        self,
        model_path: str | Path,
        config: dict[str, Any],
        log_dir: str | Path,
        startup_validator: Callable[[str, float], bool | None] | None = None,
    ):
        self.model_path = Path(model_path)
        self.config = config
        self.log_dir = Path(log_dir)
        self.process: subprocess.Popen | None = None
        self.stdout_handle = None
        self.stderr_handle = None
        self.stdout_path = self.log_dir / "llama-server.stdout.log"
        self.stderr_path = self.log_dir / "llama-server.stderr.log"
        self.dedicated_log_path = self.log_dir.parent / "llama-server.log"
        self.base_url = f"http://127.0.0.1:{int(config['port'])}"
        self.startup_validator = startup_validator

    def command(self) -> list[str]:
        return [
            os.environ.get("LLAMA_SERVER_BIN", "/app/llama-server"),
            "--model", str(self.model_path),
            "--host", "127.0.0.1",
            "--port", str(self.config["port"]),
            "--ctx-size", str(self.config["context_size"]),
            "--n-gpu-layers", str(self.config["n_gpu_layers"]),
            "--seed", str(self.config["seed"]),
            "--metrics",
            "--no-webui",
            "--log-file", str(self.dedicated_log_path),
            "--verbosity", "4",
            "--log-timestamps",
        ]

    def startup_log_text(self) -> str:
        for handle in (self.stdout_handle, self.stderr_handle):
            if handle is not None:
                handle.flush()
        sections = []
        for label, path in (
            ("llama-server.log", self.dedicated_log_path),
            ("llama-server.stdout.log", self.stdout_path),
            ("llama-server.stderr.log", self.stderr_path),
        ):
            if path.is_file():
                sections.append(
                    f"[{label}]\n"
                    + path.read_text(encoding="utf-8", errors="replace")
                )
        return "\n".join(sections)

    def __enter__(self) -> "LlamaServer":
        if not self.model_path.is_file():
            raise FileNotFoundError(f"Model file not found: {self.model_path}")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.stdout_handle = self.stdout_path.open("w", encoding="utf-8")
        self.stderr_handle = self.stderr_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            self.command(),
            stdout=self.stdout_handle,
            stderr=self.stderr_handle,
            text=True,
        )
        startup_started = time.monotonic()
        deadline = startup_started + 300
        last_error = None
        try:
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError(f"llama-server exited early with code {self.process.returncode}")
                if self.startup_validator is not None:
                    log_text = self.startup_log_text()
                    verdict = self.startup_validator(
                        log_text, time.monotonic() - startup_started
                    )
                    if verdict is False:
                        raise RuntimeError("llama-server startup rejected by fail-closed validator")
                try:
                    response = requests.get(f"{self.base_url}/health", timeout=2)
                    if response.status_code == 200:
                        if self.startup_validator is not None:
                            final_log = self.startup_log_text()
                            if self.startup_validator(
                                final_log, time.monotonic() - startup_started
                            ) is not True:
                                raise RuntimeError("llama-server became healthy without required startup evidence")
                        return self
                except requests.RequestException as exc:
                    last_error = exc
                time.sleep(1)
            raise TimeoutError(f"llama-server did not become healthy: {last_error}")
        except BaseException:
            self._shutdown()
            raise

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._shutdown()

    def _shutdown(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.stdout_handle:
            self.stdout_handle.close()
        if self.stderr_handle:
            self.stderr_handle.close()

    def infer(self, prompt: str, schema: dict[str, Any]) -> tuple[dict, dict, int]:
        request = {
            "model": self.model_path.name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": float(self.config["temperature"]),
            "seed": int(self.config["seed"]),
            "max_tokens": int(self.config["max_output_tokens"]),
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "anomaly_decision", "strict": True, "schema": schema},
            },
        }
        started = time.monotonic()
        response = requests.post(
            f"{self.base_url}/v1/chat/completions",
            json=request,
            timeout=int(self.config["request_timeout_seconds"]),
        )
        latency_ms = int((time.monotonic() - started) * 1000)
        response.raise_for_status()
        body = response.json()
        finish_reason = body["choices"][0].get("finish_reason")
        if finish_reason == "length":
            self._record_failed_response("output_token_limit", body)
            raise RuntimeError("LLM output reached max_output_tokens before completing JSON")
        content = body["choices"][0]["message"]["content"]
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            self._record_failed_response("invalid_json", body)
            raise
        validate_llm_output(parsed)
        usage = dict(body.get("usage", {}))
        usage["finish_reason"] = finish_reason
        return parsed, usage, latency_ms

    def _record_failed_response(self, reason: str, body: dict[str, Any]) -> None:
        path = self.log_dir / "failed_llm_responses.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"reason": reason, "response": body}, ensure_ascii=False) + "\n")


def validate_llm_output(value: dict[str, Any]) -> None:
    if set(value) != {"decision", "evidence", "summary", "confidence"}:
        raise ValueError("LLM output keys do not match the required schema")
    if value["decision"] not in DECISIONS:
        raise ValueError("Invalid LLM decision")
    if not isinstance(value["evidence"], list):
        raise ValueError("LLM evidence must be a list")
    for item in value["evidence"]:
        if set(item) != {"variable", "claim", "observation"}:
            raise ValueError("Invalid evidence item")
        if not all(isinstance(item[key], str) for key in item):
            raise ValueError("Invalid evidence item")
        if item["claim"] not in EVIDENCE_CLAIMS:
            raise ValueError("Invalid evidence claim")
    if not isinstance(value["summary"], str):
        raise ValueError("LLM summary must be text")
    if value["confidence"] is not None:
        raise ValueError("Confidence must remain null")

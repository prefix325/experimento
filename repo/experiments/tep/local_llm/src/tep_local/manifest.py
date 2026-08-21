from __future__ import annotations

import json
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import psutil

from . import __version__
from .config import config_sha256
from .hashing import sha256_file


def create_run_manifest(results_dir: str | Path, config: dict, prompt_path: str | Path) -> dict:
    results_dir = Path(results_dir)
    manifest = {
        "experiment_id": os.environ.get("EXPERIMENT_ID"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": config["status"],
        "scientific_inference_permitted": False,
        "git_commit": os.environ.get("GIT_COMMIT"),
        "git_dirty": os.environ.get("GIT_DIRTY"),
        "docker_version": os.environ.get("DOCKER_VERSION"),
        "docker_image_id": os.environ.get("DOCKER_IMAGE_ID"),
        "docker_image_digest": os.environ.get("DOCKER_IMAGE_DIGEST"),
        "python_version": platform.python_version(),
        "pipeline_version": __version__,
        "llm_runtime": config["llm"]["runtime"],
        "llm_runtime_version": os.environ.get("LLAMA_CPP_VERSION"),
        "model_name": "Qwen/Qwen2.5-7B-Instruct-GGUF",
        "model_file": config["llm"]["model_file"],
        "model_sha256": os.environ.get("MODEL_SHA256"),
        "model_quantization": "Q4_K_M",
        "dataset_sha256": os.environ.get("DATASET_SHA256"),
        "configuration_sha256": config_sha256(config),
        "prompt_template_sha256": sha256_file(prompt_path),
        "cpu": os.environ.get("HOST_CPU"),
        "ram": os.environ.get("HOST_RAM"),
        "gpu": os.environ.get("HOST_GPU"),
        "vram": os.environ.get("HOST_VRAM"),
        "nvidia_driver": os.environ.get("NVIDIA_DRIVER"),
        "cuda_runtime": os.environ.get("CUDA_RUNTIME"),
        "container_visible_ram_bytes": psutil.virtual_memory().total,
        "window_samples": config["window_samples"],
        "stride_samples": config["stride_samples"],
        "dpca_parameters": config["dpca"],
        "network_mode": "none",
    }
    destination = results_dir / "manifest.json"
    destination.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    human = results_dir / "manifest.md"
    human.write_text("# Run manifest\n\n" + "\n".join(f"- **{key}**: `{value}`" for key, value in manifest.items()) + "\n", encoding="utf-8")
    return manifest


def llama_cpp_version(binary: str | Path = "/app/llama-server") -> str:
    process = subprocess.run([str(binary), "--version"], text=True, capture_output=True, check=True)
    return (process.stdout or process.stderr).strip()

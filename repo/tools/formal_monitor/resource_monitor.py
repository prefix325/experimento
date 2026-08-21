from __future__ import annotations

import json
import os
import subprocess
import re
from dataclasses import asdict, dataclass
from typing import Callable


@dataclass(frozen=True)
class ResourceSnapshot:
    host_cpu_percent: float | None
    experiment_cpu_percent: float | None
    host_ram_used_bytes: int | None
    host_ram_total_bytes: int | None
    container_ram_used_bytes: int | None
    container_ram_limit_bytes: int | None
    gpu_util_percent: float | None
    vram_used_mib: int | None
    vram_total_mib: int | None
    gpu_name: str | None

    def to_dict(self) -> dict:
        return asdict(self)


class ResourceMonitor:
    def __init__(self, container_name: str | None = None, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None:
        self.container_name = container_name
        self.runner = runner

    def snapshot(self) -> ResourceSnapshot:
        host_cpu = host_used = host_total = None
        try:
            import psutil  # type: ignore

            host_cpu = float(psutil.cpu_percent(interval=None))
            memory = psutil.virtual_memory()
            host_used, host_total = int(memory.used), int(memory.total)
        except (ImportError, OSError):
            pass

        gpu_util = vram_used = vram_total = None
        gpu_name = None
        try:
            result = self.runner(
                [
                    "nvidia-smi",
                    "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=3,
                check=True,
            )
            parts = [part.strip() for part in result.stdout.splitlines()[0].split(",")]
            gpu_name, gpu_util, vram_used, vram_total = parts[0], float(parts[1]), int(parts[2]), int(parts[3])
        except (OSError, subprocess.SubprocessError, IndexError, ValueError):
            pass

        experiment_cpu = container_used = container_limit = None
        if self.container_name:
            try:
                result = self.runner(
                    ["docker", "stats", "--no-stream", "--format", "{{json .}}", self.container_name],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=True,
                )
                value = json.loads(result.stdout)
                experiment_cpu = float(str(value["CPUPerc"]).rstrip("%"))
                container_used, container_limit = _parse_memory_usage(value["MemUsage"])
            except (OSError, subprocess.SubprocessError, KeyError, ValueError, json.JSONDecodeError):
                pass
        return ResourceSnapshot(
            host_cpu,
            experiment_cpu,
            host_used,
            host_total,
            container_used,
            container_limit,
            gpu_util,
            vram_used,
            vram_total,
            gpu_name,
        )


def _parse_memory_usage(value: str) -> tuple[int | None, int | None]:
    try:
        used, limit = (part.strip() for part in value.split("/", 1))
        return _size_to_bytes(used), _size_to_bytes(limit)
    except (ValueError, AttributeError):
        return None, None


def _size_to_bytes(value: str) -> int:
    units = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}
    match = re.fullmatch(r"\s*([0-9.]+)\s*(B|KiB|MiB|GiB)\s*", value)
    if not match:
        raise ValueError(f"Unsupported memory size: {value}")
    return int(float(match.group(1)) * units[match.group(2)])


def monitor_process_rss_bytes() -> int | None:
    try:
        import psutil  # type: ignore

        return int(psutil.Process(os.getpid()).memory_info().rss)
    except (ImportError, OSError):
        return None

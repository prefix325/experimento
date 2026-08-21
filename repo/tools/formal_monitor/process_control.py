from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .gates import GateReport, require_real_start


_EXCEPTION_LINE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Interrupt):\s+.+$"
)


def final_causal_stderr(stderr: str) -> str | None:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    exceptions = [line for line in lines if _EXCEPTION_LINE.match(line)]
    if exceptions:
        return exceptions[-1]
    return lines[-1] if lines else None


@dataclass(frozen=True)
class FormalBatchCommand:
    argv: list[str]
    simulation_run_ordinal: int
    results_directory: Path
    component: str
    run_event_id: str | None = None
    diagnostic_directory: Path | None = None


@dataclass(frozen=True)
class ScientificActivityReport:
    active: bool
    docker_engine_available: bool
    processes: tuple[str, ...] = ()
    containers: tuple[str, ...] = ()


def inspect_scientific_activity(
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> ScientificActivityReport:
    """Inspect process/container liveness without starting scientific work."""
    processes: list[str] = []
    try:
        import psutil  # type: ignore

        for process in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = str(process.info.get("name") or "")
                command = " ".join(process.info.get("cmdline") or [])
            except (OSError, psutil.Error):
                continue
            lowered = command.lower()
            if (
                "run_formal_batch_offline.ps1" in lowered
                or re.search(r"(?:^|\s)run-detectors(?:\s|$)", lowered)
                or re.search(r"(?:^|\s)-m\s+tep_local(?:\s|$)", lowered)
                or name.lower().startswith("llama-server")
            ):
                processes.append(f"pid={process.info.get('pid')} {name} {command}")
    except (ImportError, OSError):
        pass

    containers: list[str] = []
    docker_available = False
    try:
        result = runner(
            [
                "docker",
                "ps",
                "--format",
                "{{.ID}}|{{.Image}}|{{.Command}}|{{.Names}}",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        docker_available = True
        for line in result.stdout.splitlines():
            lowered = line.lower()
            if (
                "psqza-tep-local" in lowered
                or "run-detectors" in lowered
                or "tep-formal-batch" in lowered
            ):
                containers.append(line)
    except (OSError, subprocess.SubprocessError):
        pass
    return ScientificActivityReport(
        active=bool(processes or containers),
        docker_engine_available=docker_available,
        processes=tuple(processes),
        containers=tuple(containers),
    )


class FormalCommandBuilder:
    """Adapter only: scientific work remains in run_formal_offline.ps1 and the container."""

    def __init__(self, repo_root: str | Path) -> None:
        self.repo_root = Path(repo_root).resolve()

    def one_batch(
        self,
        simulation_run_ordinal: int,
        results_directory: str | Path,
        *,
        cohort: str = "target",
        detector: str = "llm",
        run_event_id: str | None = None,
        diagnostic_directory: str | Path | None = None,
    ) -> FormalBatchCommand:
        ordinal = int(simulation_run_ordinal)
        if ordinal <= 0:
            raise ValueError("simulation_run_ordinal must be positive")
        results = Path(results_directory).resolve()
        if cohort not in {"target", "normal_holdout"} or detector not in {"llm", "dpca"}:
            raise ValueError("Unsupported formal batch cohort/detector")
        script = self.repo_root / "scripts" / "run_formal_batch_offline.ps1"
        return FormalBatchCommand(
            argv=[
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-RunOrdinal",
                str(ordinal),
                "-Cohort",
                cohort,
                "-Detector",
                detector,
                "-ResultsDirectory",
                str(results),
            ],
            simulation_run_ordinal=ordinal,
            results_directory=results,
            component=detector,
            run_event_id=run_event_id,
            diagnostic_directory=(
                Path(diagnostic_directory).resolve()
                if diagnostic_directory is not None
                else None
            ),
        )


class RealProcessController:
    def __init__(
        self,
        gate_report: GateReport,
        *,
        directory_preparer: Callable[[Path], None] | None = None,
    ) -> None:
        self.gate_report = gate_report
        self._directory_preparer = directory_preparer or self._create_directory
        self.process: subprocess.Popen | None = None
        self.last_exit_code: int | None = None
        self.last_pid: int | None = None
        self.stdout_path: Path | None = None
        self.stderr_path: Path | None = None
        self._stdout_handle = None
        self._stderr_handle = None
        self._reader_threads: list[threading.Thread] = []
        self._log_close_lock = threading.Lock()

    @staticmethod
    def _create_directory(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def prepare(self, command: FormalBatchCommand) -> Path:
        """Create and validate operational output paths without starting a process."""
        require_real_start(self.gate_report)
        cwd = command.results_directory.parent
        for path in (cwd, command.results_directory):
            self._directory_preparer(path)
            if not path.is_dir():
                raise NotADirectoryError(
                    f"Formal operational directory is unavailable: {path}"
                )
        return cwd

    @staticmethod
    def _tee_stream(stream, handle, console) -> None:
        try:
            for line in iter(stream.readline, ""):
                handle.write(line)
                handle.flush()
                if console is not None:
                    console.write(line)
                    console.flush()
        finally:
            stream.close()

    def _close_logs(self) -> None:
        with self._log_close_lock:
            threads = self._reader_threads
            self._reader_threads = []
            handles = (self._stdout_handle, self._stderr_handle)
            self._stdout_handle = None
            self._stderr_handle = None
            for thread in threads:
                thread.join(timeout=5)
            for handle in handles:
                if handle is not None and not handle.closed:
                    handle.flush()
                    handle.close()

    def start(self, command: FormalBatchCommand) -> None:
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("A formal batch process is already running")
        self.last_exit_code = None
        self.last_pid = None
        cwd = self.prepare(command)
        if command.diagnostic_directory is not None:
            command.diagnostic_directory.mkdir(parents=True, exist_ok=True)
            self.stdout_path = command.diagnostic_directory / f"{command.component}.stdout.log"
            self.stderr_path = command.diagnostic_directory / f"{command.component}.stderr.log"
            (command.diagnostic_directory / f"{command.component}.command.json").write_text(
                json.dumps(
                    {
                        "run_event_id": command.run_event_id,
                        "component": command.component,
                        "argv": command.argv,
                        "cwd": str(cwd),
                        "cwd_exists": cwd.is_dir(),
                        "results_directory": str(command.results_directory),
                        "results_directory_exists": command.results_directory.is_dir(),
                    },
                    indent=2,
                    ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )
            self._stdout_handle = self.stdout_path.open("w", encoding="utf-8", newline="\n")
            self._stderr_handle = self.stderr_path.open("w", encoding="utf-8", newline="\n")
        try:
            self.process = subprocess.Popen(
                command.argv,
                cwd=str(cwd),
                stdout=subprocess.PIPE if self._stdout_handle is not None else None,
                stderr=subprocess.PIPE if self._stderr_handle is not None else None,
                text=True,
                bufsize=1,
            )
        except BaseException:
            self._close_logs()
            raise
        self.last_pid = self.process.pid
        if self._stdout_handle is not None and self.process.stdout is not None:
            self._reader_threads.append(threading.Thread(
                target=self._tee_stream,
                args=(self.process.stdout, self._stdout_handle, sys.stdout),
                name=f"formal-{command.component}-stdout",
                daemon=True,
            ))
        if self._stderr_handle is not None and self.process.stderr is not None:
            self._reader_threads.append(threading.Thread(
                target=self._tee_stream,
                args=(self.process.stderr, self._stderr_handle, sys.stderr),
                name=f"formal-{command.component}-stderr",
                daemon=True,
            ))
        for thread in self._reader_threads:
            thread.start()

    def wait(self) -> int:
        if self.process is None:
            raise RuntimeError("No formal batch process is running")
        self.last_exit_code = int(self.process.wait())
        self._close_logs()
        return self.last_exit_code

    def captured_stderr(self) -> str:
        if self.stderr_path is None or not self.stderr_path.is_file():
            return ""
        return self.stderr_path.read_text(encoding="utf-8", errors="replace")

    def first_causal_stderr(self) -> str | None:
        return final_causal_stderr(self.captured_stderr())

    def stop_now(self, timeout_seconds: int = 30) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.last_exit_code = int(self.process.wait(timeout=timeout_seconds))
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.last_exit_code = int(self.process.wait(timeout=5))
        self._close_logs()

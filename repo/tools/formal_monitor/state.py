from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from .process_control import final_causal_stderr


BATCH_STATES = {
    "PENDING", "STARTING", "RUNNING", "COMPLETE", "PARTIAL",
    "ABORTED", "FAILED", "FAILED_TO_START",
}
GLOBAL_STATES = {"BLOCKED", "READY", "RUNNING", "STOPPING", "STOPPED", "ERROR"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        value, indent=2, sort_keys=True, ensure_ascii=False
    ) + "\n"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def serialized_store_access(method):
    """Use one re-entrant lock for store reads and complete mutations."""
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self._mutation_lock:
            return method(self, *args, **kwargs)
    return locked


@dataclass
class MonitorState:
    schema_version: str = "1.0.0"
    mode: str = "REAL_BLOCKED"
    global_status: str = "BLOCKED"
    gate_reasons: list[str] = field(default_factory=list)
    cohort: str = "target"
    total_batches: int = 50
    runs_this_session: int = 5
    current_simulation_run: int | None = None
    current_attempt_id: str | None = None
    current_run_event_id: str | None = None
    completed_batches: int = 0
    window_completed: int = 0
    window_total_max: int = 189
    detection_state: str = "SEARCHING"
    verification_advance: int = 0
    verification_advances_required: int = 4
    first_indication_window: int | None = None
    confirmation_window: int | None = None
    llm_status: str = "PENDING"
    dpca_status: str = "PENDING"
    lot_status: str = "PENDING"
    last_llm_decision: str | None = None
    stop_request: str = "NONE"
    stop_outcome: str | None = None
    active_batch_seconds: float = 0.0
    accumulated_active_seconds: float = 0.0
    completed_durations_seconds: list[float] = field(default_factory=list)
    eta_batch_seconds: float | None = None
    eta_total_seconds: float | None = None
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MonitorState":
        allowed = cls.__dataclass_fields__
        return cls(**{key: item for key, item in value.items() if key in allowed})


class StateStore:
    def __init__(self, root: str | Path, *, mock: bool, now: Callable[[], str] = utc_now) -> None:
        self.root = Path(root).resolve()
        self.mock = bool(mock)
        self.now = now
        if self.mock and not self.root.name.upper().startswith("MOCK"):
            raise ValueError("Mock state directory must be explicitly marked MOCK")
        normalized = str(self.root).replace("\\", "/").lower()
        if self.mock and "/results/formal" in normalized:
            raise ValueError("Mock mode may never use results/formal")
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "monitor_state.json"
        self.attempts_root = self.root / "attempts"
        self.telemetry_path = self.root / "MOCK_OPERATIONAL_TELEMETRY.jsonl" if self.mock else self.root / "operational_telemetry.jsonl"
        self.events_path = self.root / "operational_events.jsonl"
        self.latest_error_path = self.root / "latest_error.json"
        self._mutation_lock = threading.RLock()
        self._event_lock = threading.Lock()

    @contextmanager
    def mutation(self):
        """Serialize a complete state read-modify-write cycle."""
        with self._mutation_lock:
            yield

    def new_run_event_id(self) -> str:
        return "run-event-" + uuid.uuid4().hex

    @staticmethod
    def _validate_operational_details(details: dict[str, Any]) -> None:
        forbidden = {"ground_truth", "faultnumber", "fault_number", "y"}
        for key, value in details.items():
            if str(key).lower() in forbidden:
                raise ValueError(f"Forbidden scientific field in operational log: {key}")
            if isinstance(value, dict):
                StateStore._validate_operational_details(value)

    @serialized_store_access
    def append_event(
        self,
        event_type: str,
        message: str,
        *,
        state: MonitorState | None = None,
        run_event_id: str | None = None,
        component: str | None = None,
        level: str = "INFO",
        exit_code: int | None = None,
        log_path: str | None = None,
        details: dict[str, Any] | None = None,
        attempt_dir: Path | None = None,
    ) -> dict[str, Any]:
        safe_details = details or {}
        self._validate_operational_details(safe_details)
        record = {
            "event_id": "event-" + uuid.uuid4().hex,
            "run_event_id": run_event_id or (
                state.current_run_event_id if state else None
            ),
            "timestamp": self.now(),
            "level": level,
            "event_type": event_type,
            "message": message,
            "cohort": state.cohort if state else None,
            "simulation_run": state.current_simulation_run if state else None,
            "attempt_id": state.current_attempt_id if state else None,
            "component": component,
            "exit_code": exit_code,
            "log_path": log_path,
            "details": safe_details,
            "operational_only": True,
            "mock": self.mock,
        }
        encoded = json.dumps(record, sort_keys=True, ensure_ascii=False)
        with self._event_lock:
            with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            if attempt_dir is not None:
                attempt_events = attempt_dir / "operational_events.jsonl"
                with attempt_events.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(encoded + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
        print("[FORMAL_MONITOR_EVENT] " + encoded, flush=True)
        return record

    @serialized_store_access
    def recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self.events_path.is_file():
            return []
        lines = self.events_path.read_text(encoding="utf-8").splitlines()
        records = []
        for line in lines[-max(1, int(limit)):]:
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
        return records

    @serialized_store_access
    def latest_error(self) -> dict[str, Any] | None:
        if not self.latest_error_path.is_file():
            return None
        try:
            return json.loads(self.latest_error_path.read_text(encoding="utf-8"))
        except ValueError:
            return None

    @staticmethod
    def _diagnostic_text(path: Path, limit: int | None = 262_144) -> str:
        value = path.read_text(encoding="utf-8", errors="replace")
        if limit is None or len(value) <= limit:
            return value
        return "[display truncated; raw file preserved]\n" + value[-limit:]

    def latest_error_diagnostic(self) -> dict[str, Any] | None:
        error = self.latest_error()
        if error is None or error.get("component") not in {"dpca", "llm"}:
            return error
        try:
            trace_path = Path(str(error["log_path"])).resolve()
            trace_path.relative_to(self.root)
        except (KeyError, OSError, ValueError):
            return error
        logs = trace_path.parent / "logs"
        component = str(error["component"])
        stderr_path = logs / f"{component}.stderr.log"
        stdout_path = logs / f"{component}.stdout.log"
        command_path = logs / f"{component}.command.json"
        if stderr_path.is_file():
            stderr = self._diagnostic_text(stderr_path, limit=None)
            error["component_stderr_path"] = str(stderr_path)
            error["component_stderr"] = stderr
            error["first_causal_stderr"] = final_causal_stderr(stderr)
        if stdout_path.is_file():
            error["component_stdout_path"] = str(stdout_path)
            error["component_stdout"] = self._diagnostic_text(stdout_path)
        if command_path.is_file():
            error["component_command_path"] = str(command_path)
            error["component_command"] = self._diagnostic_text(command_path)
        return error

    @serialized_store_access
    def record_error(
        self,
        *,
        state: MonitorState,
        run_event_id: str | None,
        error_type: str,
        message: str,
        traceback_text: str,
        component: str | None,
        exit_code: int | None,
        attempt_dir: Path | None,
    ) -> dict[str, Any]:
        diagnostic_root = attempt_dir or (self.root / "errors")
        diagnostic_root.mkdir(parents=True, exist_ok=True)
        trace_name = f"{run_event_id or 'unassigned'}-traceback.log"
        trace_path = diagnostic_root / trace_name
        trace_path.write_text(traceback_text, encoding="utf-8")
        error = {
            "error_summary": "Formal operational component failed",
            "error_type": error_type,
            "message": message,
            "timestamp": self.now(),
            "status": "ACTIVE",
            "historical": False,
            "run_event_id": run_event_id,
            "simulation_run": state.current_simulation_run,
            "cohort": state.cohort,
            "component": component,
            "exit_code": exit_code,
            "log_path": str(trace_path),
            "traceback": traceback_text,
            "operational_only": True,
        }
        atomic_json(self.latest_error_path, error)
        if attempt_dir is not None:
            atomic_json(attempt_dir / "error.json", error)
        self.append_event(
            "ERROR",
            message,
            state=state,
            run_event_id=run_event_id,
            component=component,
            level="ERROR",
            exit_code=exit_code,
            log_path=str(trace_path),
            details={"error_type": error_type},
            attempt_dir=attempt_dir,
        )
        return error

    @serialized_store_access
    def resolve_latest_error(
        self,
        *,
        resolution_event_id: str,
        resolution_run_event_id: str,
        resolved_at: str,
    ) -> dict[str, Any] | None:
        error = self.latest_error()
        if error is None:
            return None
        error.update({
            "status": "RESOLVED/HISTORICAL",
            "historical": True,
            "resolved_at": resolved_at,
            "resolution_event_id": resolution_event_id,
            "resolution_run_event_id": resolution_run_event_id,
        })
        atomic_json(self.latest_error_path, error)
        return error

    @serialized_store_access
    def load(self) -> MonitorState:
        if not self.state_path.exists():
            state = MonitorState(mode="MOCK" if self.mock else "REAL_BLOCKED")
            self.save(state)
            return state
        return MonitorState.from_dict(json.loads(self.state_path.read_text(encoding="utf-8")))

    @serialized_store_access
    def read(self) -> MonitorState:
        """Read existing state without creating or persisting anything."""
        return MonitorState.from_dict(
            json.loads(self.state_path.read_text(encoding="utf-8"))
        )

    @serialized_store_access
    def save(self, state: MonitorState) -> None:
        if state.global_status not in GLOBAL_STATES:
            raise ValueError(f"Invalid global state: {state.global_status}")
        state.updated_at = self.now()
        atomic_json(self.state_path, state.to_dict())

    @serialized_store_access
    def update_state(self, state: MonitorState, **fields: Any) -> None:
        """Apply and persist state fields as one serialized mutation."""
        unknown = [key for key in fields if not hasattr(state, key)]
        if unknown:
            raise AttributeError(f"Unknown monitor state field(s): {', '.join(unknown)}")
        for key, value in fields.items():
            setattr(state, key, value)
        self.save(state)

    def _run_root(self, cohort: str, simulation_run: int) -> Path:
        return self.attempts_root / cohort / f"run_{int(simulation_run):03d}"

    def _attempts(self, cohort: str, simulation_run: int) -> list[Path]:
        root = self._run_root(cohort, simulation_run)
        return sorted(path for path in root.glob("attempt_[0-9][0-9][0-9][0-9]") if path.is_dir()) if root.exists() else []

    @serialized_store_access
    def status_of(self, cohort: str, simulation_run: int) -> str:
        complete = self._run_root(cohort, simulation_run) / "COMPLETE.json"
        if complete.exists():
            return "COMPLETE"
        attempts = self._attempts(cohort, simulation_run)
        if not attempts:
            return "PENDING"
        status = json.loads((attempts[-1] / "status.json").read_text(encoding="utf-8"))["status"]
        if status not in BATCH_STATES:
            raise ValueError(f"Invalid persisted batch state: {status}")
        return status

    @serialized_store_access
    def latest_attempt_status(
        self, cohort: str, simulation_run: int
    ) -> dict[str, Any] | None:
        attempts = self._attempts(cohort, simulation_run)
        if not attempts:
            return None
        status_path = attempts[-1] / "status.json"
        if not status_path.is_file():
            return None
        return json.loads(status_path.read_text(encoding="utf-8"))

    @serialized_store_access
    def next_attempt_id(self, cohort: str, simulation_run: int) -> str:
        if self.status_of(cohort, simulation_run) == "COMPLETE":
            raise RuntimeError("A COMPLETE batch is immutable")
        return f"attempt_{len(self._attempts(cohort, simulation_run)) + 1:04d}"

    @serialized_store_access
    def completed_components(self, cohort: str, simulation_run: int) -> set[str]:
        completed: set[str] = set()
        for attempt in self._attempts(cohort, simulation_run):
            status_path = attempt / "status.json"
            if not status_path.is_file():
                continue
            value = json.loads(status_path.read_text(encoding="utf-8"))
            for component in ("dpca", "llm"):
                if value.get(f"{component}_status") in {
                    "COMPLETE",
                    "STOPPED_EARLY",
                    "NOT_REQUIRED",
                }:
                    completed.add(component)
        return completed

    @serialized_store_access
    def completed_runs(self, cohort: str, run_order: list[int]) -> list[int]:
        return [run for run in run_order if self.status_of(cohort, run) == "COMPLETE"]

    @serialized_store_access
    def completed_durations(self, cohort: str, run_order: list[int]) -> list[float]:
        durations: list[float] = []
        for run in run_order:
            if self.status_of(cohort, run) != "COMPLETE":
                continue
            marker = json.loads((self._run_root(cohort, run) / "COMPLETE.json").read_text(encoding="utf-8"))
            attempt = self._run_root(cohort, run) / marker["attempt_id"] / "status.json"
            value = json.loads(attempt.read_text(encoding="utf-8"))
            durations.append(float(value["duration_seconds"]))
        return durations

    @serialized_store_access
    def next_pending(self, cohort: str, run_order: list[int]) -> int | None:
        for run in run_order:
            if self.status_of(cohort, run) != "COMPLETE":
                return run
        return None

    @serialized_store_access
    def begin_attempt(
        self,
        state: MonitorState,
        simulation_run: int,
        *,
        run_event_id: str | None = None,
    ) -> Path:
        if self.status_of(state.cohort, simulation_run) == "COMPLETE":
            raise RuntimeError("A COMPLETE batch is immutable")
        attempt_id = self.next_attempt_id(state.cohort, simulation_run)
        directory = self._run_root(state.cohort, simulation_run) / attempt_id
        directory.mkdir(parents=True, exist_ok=False)
        status = {
            "status": "STARTING",
            "cohort": state.cohort,
            "simulation_run": int(simulation_run),
            "attempt_id": attempt_id,
            "run_event_id": run_event_id,
            "process_started": False,
            "started_at": self.now(),
            "mock": self.mock,
        }
        atomic_json(directory / "status.json", status)
        state.current_simulation_run = int(simulation_run)
        state.current_attempt_id = attempt_id
        state.current_run_event_id = run_event_id
        state.global_status = "RUNNING"
        state.stop_outcome = None
        state.window_completed = 0
        state.detection_state = "SEARCHING"
        state.verification_advance = 0
        state.first_indication_window = None
        state.confirmation_window = None
        state.llm_status = "PENDING"
        state.dpca_status = "PENDING"
        state.lot_status = "STARTING"
        state.last_llm_decision = None
        state.active_batch_seconds = 0.0
        self.save(state)
        return directory

    @serialized_store_access
    def update_attempt(self, state: MonitorState, attempt_dir: Path, **fields: Any) -> None:
        status_path = attempt_dir / "status.json"
        status = json.loads(status_path.read_text(encoding="utf-8"))
        status.update(fields)
        atomic_json(status_path, status)
        for key, value in fields.items():
            if hasattr(state, key):
                setattr(state, key, value)
        self.save(state)

    @serialized_store_access
    def complete_attempt(
        self,
        state: MonitorState,
        attempt_dir: Path,
        *,
        completion_reason: str,
        duration_seconds: float,
        llm_status: str | None = None,
        dpca_status: str = "COMPLETE",
    ) -> None:
        if completion_reason not in {
            "CONFIRMED_DETECTION",
            "NO_FIRST_INDICATION",
            "NO_CONFIRMED_DETECTION",
            "VERIFICATION_INCOMPLETE_END_OF_TRAJECTORY",
            "NORMAL_TRAJECTORY_COMPLETE",
            "COMPONENTS_COMPLETE",
        }:
            raise ValueError("Invalid COMPLETE condition")
        effective_llm = llm_status or (
            "STOPPED_EARLY"
            if completion_reason == "CONFIRMED_DETECTION"
            else "COMPLETE"
        )
        if (
            effective_llm not in {"COMPLETE", "STOPPED_EARLY", "NOT_REQUIRED"}
            or dpca_status != "COMPLETE"
        ):
            raise RuntimeError(
                "Lot cannot become COMPLETE until required LLM and DPCA components are complete"
            )
        status = json.loads((attempt_dir / "status.json").read_text(encoding="utf-8"))
        status.update({
            "status": "COMPLETE",
            "completion_reason": completion_reason,
            "ended_at": self.now(),
            "duration_seconds": float(duration_seconds),
            "llm_status": effective_llm,
            "dpca_status": dpca_status,
            "lot_status": "COMPLETE",
        })
        atomic_json(attempt_dir / "status.json", status)
        marker = {
            "status": "COMPLETE",
            "cohort": state.cohort,
            "simulation_run": state.current_simulation_run,
            "attempt_id": state.current_attempt_id,
            "completion_reason": completion_reason,
            "completed_at": self.now(),
            "mock": self.mock,
            "llm_status": effective_llm,
            "dpca_status": dpca_status,
            "lot_status": "COMPLETE",
        }
        atomic_json(self._run_root(state.cohort, int(state.current_simulation_run)) / "COMPLETE.json", marker)
        state.completed_batches += 1
        state.completed_durations_seconds.append(float(duration_seconds))
        state.accumulated_active_seconds += float(duration_seconds)
        state.active_batch_seconds = float(duration_seconds)
        state.eta_batch_seconds = 0.0
        state.llm_status = effective_llm
        state.dpca_status = dpca_status
        state.lot_status = "COMPLETE"
        state.current_simulation_run = None
        state.current_attempt_id = None
        state.current_run_event_id = None
        state.global_status = "STOPPED" if state.stop_request == "AFTER_CURRENT" else "READY"
        if state.stop_request == "AFTER_CURRENT":
            state.stop_outcome = "STOPPED_CLEAN"
            state.stop_request = "NONE"
        self.save(state)

    @serialized_store_access
    def abort_current(self, state: MonitorState, attempt_dir: Path, *, status: str = "ABORTED") -> None:
        if status not in {"PARTIAL", "ABORTED", "FAILED", "FAILED_TO_START"}:
            raise ValueError(
                "Interrupted attempt must be PARTIAL, ABORTED, FAILED or FAILED_TO_START"
            )
        value = json.loads((attempt_dir / "status.json").read_text(encoding="utf-8"))
        value.update({"status": status, "ended_at": self.now(), "complete": False})
        for field in ("llm_status", "dpca_status", "lot_status"):
            if value.get(field) in {"RUNNING", "STARTING"}:
                value[field] = status
        atomic_json(attempt_dir / "status.json", value)
        state.global_status = "STOPPED"
        state.stop_outcome = "STOPPED_FORCED"
        state.stop_request = "NONE"
        if state.llm_status in {"RUNNING", "STARTING"}:
            state.llm_status = status
        if state.dpca_status in {"RUNNING", "STARTING"}:
            state.dpca_status = status
        state.lot_status = status
        state.current_simulation_run = None
        state.current_attempt_id = None
        state.current_run_event_id = None
        self.save(state)

    @serialized_store_access
    def recover_orphans(self, state: MonitorState) -> list[Path]:
        recovered: list[Path] = []
        recovered_statuses: list[str] = []
        for status_path in self.attempts_root.glob("*/*/attempt_*/status.json") if self.attempts_root.exists() else []:
            value = json.loads(status_path.read_text(encoding="utf-8"))
            if value.get("status") in {"STARTING", "RUNNING"}:
                recovered_status = (
                    "PARTIAL" if value.get("process_started") is True
                    else "FAILED_TO_START"
                )
                value.update({
                    "status": recovered_status,
                    "complete": False,
                    "recovered_after_abrupt_shutdown": True,
                    "ended_at": self.now(),
                })
                atomic_json(status_path, value)
                recovered.append(status_path.parent)
                recovered_statuses.append(recovered_status)
        if recovered or state.global_status in {"RUNNING", "STOPPING"}:
            state_status = (
                "PARTIAL" if "PARTIAL" in recovered_statuses
                else "FAILED_TO_START"
            )
            state.global_status = "STOPPED"
            state.stop_outcome = "STOPPED_FORCED"
            state.stop_request = "NONE"
            state.current_simulation_run = None
            state.current_attempt_id = None
            state.current_run_event_id = None
            state.llm_status = state_status
            state.dpca_status = state_status
            state.lot_status = state_status
            self.save(state)
        return recovered

    @serialized_store_access
    def append_telemetry(self, record: dict[str, Any]) -> None:
        record = {"timestamp": self.now(), **record, "operational_only": True, "mock": self.mock}
        with self.telemetry_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.append_event(
            "WINDOW_PROGRESS",
            "Operational window state persisted",
            run_event_id=record.get("run_event_id"),
            component="llm",
            details={
                key: record.get(key)
                for key in (
                    "cohort", "simulation_run", "window_completed",
                    "window_total", "detection_state", "verification_advance",
                    "last_llm_decision",
                )
                if key in record
            },
        )

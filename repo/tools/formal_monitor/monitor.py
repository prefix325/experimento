from __future__ import annotations

import argparse
import json
import tempfile
import threading
from functools import wraps
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .eta import estimate_total_eta_seconds
from .gates import GateReport, inspect_static_gates
from .llm_progress import LLMProgressReader
from .mock_mode import MockExperiment
from .process_control import (
    ScientificActivityReport,
    inspect_scientific_activity,
)
from .real_mode import FORMAL_RESULTS_ID, RealExperiment
from .resource_monitor import ResourceMonitor, monitor_process_rss_bytes
from .state import StateStore


BIND_HOST = "127.0.0.1"
ROOT = Path(__file__).resolve().parent
RESUMABLE_STOP_OUTCOMES = {"SESSION_LIMIT_REACHED", "STOPPED_CLEAN"}
NON_RESUMABLE_COMPONENT_STATES = {
    "STARTING", "RUNNING", "FAILED", "FAILED_TO_START", "ABORTED", "PARTIAL",
}


def serialized_application_mutation(method):
    """Keep each HTTP-triggered read-modify-write cycle under the store RLock."""
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self.store.mutation():
            return method(self, *args, **kwargs)
    return locked


def real_start_is_enabled(
    gates: GateReport,
    state,
    *,
    mock: bool,
    current_error_active: bool = False,
    worker_active: bool = False,
) -> bool:
    if not gates.ready or mock or current_error_active or worker_active:
        return False
    if state.stop_request != "NONE":
        return False
    if any(
        value is not None
        for value in (
            state.current_simulation_run,
            state.current_attempt_id,
            state.current_run_event_id,
        )
    ):
        return False
    if any(
        value in NON_RESUMABLE_COMPONENT_STATES
        for value in (state.llm_status, state.dpca_status, state.lot_status)
    ):
        return False
    if state.global_status == "READY":
        return state.stop_outcome != "STOPPED_FORCED"
    if state.global_status != "STOPPED" or state.stop_outcome not in RESUMABLE_STOP_OUTCOMES:
        return False
    if state.stop_outcome == "SESSION_LIMIT_REACHED":
        return (
            state.completed_batches > 0
            and state.lot_status == "COMPLETE"
            and state.dpca_status == "COMPLETE"
            and state.llm_status in {"COMPLETE", "NOT_REQUIRED", "STOPPED_EARLY"}
        )
    return True


def _recoverable_stop_now_error(error: dict[str, Any] | None) -> bool:
    if not error:
        return True
    if error.get("status") != "ACTIVE" or error.get("historical") is True:
        return True
    traceback_text = str(error.get("traceback", "")).replace("\\", "/")
    return (
        error.get("operational_only") is True
        and error.get("error_type") == "ValueError"
        and str(error.get("message")) == "I/O operation on closed file."
        and "tools/formal_monitor/process_control.py" in traceback_text
        and "_close_logs" in traceback_text
    )


def operational_revalidation_is_enabled(
    state,
    error: dict[str, Any] | None,
    *,
    mock: bool,
    worker_active: bool,
) -> bool:
    if mock or worker_active:
        return False
    active_error = bool(
        error
        and error.get("status") == "ACTIVE"
        and error.get("historical") is not True
    )
    if state.global_status == "ERROR":
        return active_error
    forced_abort = (
        state.global_status == "STOPPED"
        and state.stop_outcome == "STOPPED_FORCED"
        and state.stop_request == "NONE"
        and state.lot_status == "ABORTED"
        and "ABORTED" in {state.dpca_status, state.llm_status}
        and state.current_simulation_run is None
        and state.current_attempt_id is None
        and state.current_run_event_id is None
    )
    return forced_abort and _recoverable_stop_now_error(error)


class MonitorApplication:
    def __init__(
        self,
        repo_root: Path,
        workspace_root: Path,
        state_root: Path,
        *,
        mock: bool,
        scientific_activity_probe: Callable[
            [], ScientificActivityReport
        ] = inspect_scientific_activity,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.workspace_root = workspace_root.resolve()
        self.mock = bool(mock)
        self.scientific_activity_probe = scientific_activity_probe
        self.gates = inspect_static_gates(self.repo_root, self.workspace_root)
        self.store = StateStore(state_root, mock=self.mock)
        self.mock_experiment = MockExperiment(self.store) if self.mock else None
        self.real_experiment = (
            None if self.mock else RealExperiment(
                self.store, self.repo_root, self.workspace_root, self.gates
            )
        )
        self.resources = ResourceMonitor()
        self.llm_progress = (
            None
            if self.mock
            else LLMProgressReader(
                self.repo_root,
                self.workspace_root,
                FORMAL_RESULTS_ID,
            )
        )
        self.worker: threading.Thread | None = None
        persisted = self.store.load()
        if persisted.global_status == "ERROR" and self.store.latest_error() is None:
            message = (
                persisted.gate_reasons[0]
                if persisted.gate_reasons
                else "Persisted monitor error without prior diagnostic log"
            )
            self.store.record_error(
                state=persisted,
                run_event_id="legacy-error-state",
                error_type="PersistedMonitorError",
                message=message,
                traceback_text=(
                    "Traceback unavailable: failure predates persistent operational logging.\n"
                ),
                component="controller",
                exit_code=None,
                attempt_dir=None,
            )

    def snapshot(self) -> dict[str, Any]:
        state = self.store.read()
        error_diagnostic = self.store.latest_error_diagnostic()
        current_error_active = bool(
            error_diagnostic
            and error_diagnostic.get("status") == "ACTIVE"
            and error_diagnostic.get("historical") is not True
        )
        worker_active = bool(self.worker and self.worker.is_alive())
        remaining = max(0, state.total_batches - state.completed_batches)
        response_state = state.to_dict()
        response_state["eta_total_seconds"] = estimate_total_eta_seconds(
            state.completed_durations_seconds, remaining
        )
        if (
            self.llm_progress is not None
            and state.current_simulation_run is not None
            and state.current_attempt_id is not None
            and state.llm_status in {"STARTING", "RUNNING"}
        ):
            command_path = (
                self.store.attempts_root
                / state.cohort
                / f"run_{state.current_simulation_run:03d}"
                / state.current_attempt_id
                / "logs"
                / "llm.command.json"
            )
            try:
                not_before = command_path.stat().st_mtime
            except OSError:
                not_before = None
            progress = self.llm_progress.read(
                state.cohort,
                state.current_simulation_run,
                not_before=not_before,
            )
            response_state.update(progress.response_fields())
        resources = self.resources.snapshot().to_dict()
        return {
            **response_state,
            "formal_execution_blocked": not self.gates.ready,
            "real_start_enabled": real_start_is_enabled(
                self.gates,
                state,
                mock=self.mock,
                current_error_active=current_error_active,
                worker_active=worker_active,
            ),
            "current_error_active": current_error_active,
            "operational_revalidation_enabled": operational_revalidation_is_enabled(
                state,
                error_diagnostic,
                mock=self.mock,
                worker_active=worker_active,
            ),
            "mock_start_enabled": self.mock,
            "progress_total_percent": round(100 * state.completed_batches / state.total_batches, 2) if state.total_batches else 0.0,
            "progress_batch_percent": round(100 * state.window_completed / state.window_total_max, 2) if state.window_total_max else 0.0,
            "resources": resources,
            "monitor_rss_bytes": monitor_process_rss_bytes(),
            "telemetry_operational_only": True,
            "operational_events": self.store.recent_events(100),
            "error_diagnostic": error_diagnostic,
        }

    @serialized_application_mutation
    def start_or_resume(
        self, runs_this_session: int | None = None
    ) -> None:
        state = self.store.load()
        run_event_id = self.store.new_run_event_id()
        latest_error = self.store.latest_error()
        current_error_active = bool(
            latest_error
            and latest_error.get("status") == "ACTIVE"
            and latest_error.get("historical") is not True
        )
        worker_active = bool(self.worker and self.worker.is_alive())
        if not self.mock and not real_start_is_enabled(
            self.gates,
            state,
            mock=False,
            current_error_active=current_error_active,
            worker_active=worker_active,
        ):
            self.store.append_event(
                "START_REJECTED_OPERATIONAL_STATE",
                "Start/Resume rejected by the operational state machine",
                state=state,
                run_event_id=run_event_id,
                component="controller",
                level="ERROR",
            )
            raise RuntimeError(
                "START BLOCKED: operational state is not safely resumable; revalidate recovery state"
            )
        if not self.mock:
            activity = self.scientific_activity_probe()
            if activity.active:
                raise RuntimeError(
                    "START BLOCKED: scientific process/container is already active"
                )
            if not activity.docker_engine_available:
                raise RuntimeError(
                    "START BLOCKED: Docker Desktop/engine is unavailable"
                )
        self.store.append_event(
            "START_REQUESTED",
            "Start/Resume requested",
            state=state,
            run_event_id=run_event_id,
            details={"runs_this_session": int(runs_this_session or 5)},
        )
        if not self.mock and not self.gates.ready:
            self.store.append_event(
                "ERROR",
                "Formal gate rejected Start/Resume",
                state=state,
                run_event_id=run_event_id,
                component="gate",
                level="ERROR",
                details={"gate_reasons": self.gates.reasons},
            )
            raise RuntimeError("FORMAL EXECUTION BLOCKED: " + ", ".join(self.gates.reasons))
        if self.worker and self.worker.is_alive():
            self.store.append_event(
                "START_IGNORED",
                "Start/Resume ignored because a worker is already active",
                state=state,
                run_event_id=run_event_id,
                level="WARNING",
            )
            return
        session_limit = int(runs_this_session or 5)
        if session_limit <= 0:
            raise RuntimeError("runs_this_session must be positive")
        state.runs_this_session = session_limit
        self.store.save(state)
        self.store.append_event(
            "GATE_VALIDATED",
            "Formal operational gate validated",
            state=state,
            run_event_id=run_event_id,
            component="gate",
            details={"gate_status": self.gates.status, "checks": self.gates.checks},
        )

        def run() -> None:
            if self.mock:
                assert self.mock_experiment is not None
                self.mock_experiment.run_all(max_runs=session_limit)
            else:
                assert self.real_experiment is not None
                self.real_experiment.run_all(
                    max_runs=session_limit,
                    run_event_id=run_event_id,
                )

        self.worker = threading.Thread(target=run, name="formal-monitor-mock", daemon=True)
        self.worker.start()

    @serialized_application_mutation
    def revalidate_operational(self) -> dict:
        if self.mock:
            raise RuntimeError("Operational revalidation is only available in real mode")
        if self.worker and self.worker.is_alive():
            raise RuntimeError("Cannot revalidate while a monitor worker is active")
        state = self.store.load()
        latest_error = self.store.latest_error()
        if not operational_revalidation_is_enabled(
            state,
            latest_error,
            mock=False,
            worker_active=False,
        ):
            raise RuntimeError("No unresolved operational error requires revalidation")
        activity = self.scientific_activity_probe()
        if activity.active:
            raise RuntimeError(
                "Cannot revalidate while a scientific process/container is active"
            )
        run_event_id = self.store.new_run_event_id()
        self.store.append_event(
            "OPERATIONAL_REVALIDATION_REQUESTED",
            "Operational gate and directory revalidation requested",
            state=state,
            run_event_id=run_event_id,
            component="controller",
            details={"process_started": False},
        )
        self.gates = inspect_static_gates(self.repo_root, self.workspace_root)
        assert self.real_experiment is not None
        report = self.real_experiment.revalidate_operational(
            self.gates,
            run_event_id=run_event_id,
        )
        report["docker_engine_available"] = activity.docker_engine_available
        return report

    @serialized_application_mutation
    def stop_after_current(self) -> None:
        if self.mock_experiment:
            self.mock_experiment.request_stop_after_current()
        elif self.real_experiment:
            self.real_experiment.request_stop_after_current()

    @serialized_application_mutation
    def stop_now(self) -> None:
        if self.mock_experiment:
            self.mock_experiment.request_stop_now()
        elif self.real_experiment:
            self.real_experiment.request_stop_now()


class MonitorHandler(BaseHTTPRequestHandler):
    app: MonitorApplication

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            self._send(HTTPStatus.OK, "text/html; charset=utf-8", (ROOT / "templates" / "index.html").read_bytes())
        elif path == "/static/style.css":
            self._send(HTTPStatus.OK, "text/css; charset=utf-8", (ROOT / "static" / "style.css").read_bytes())
        elif path == "/static/app.js":
            self._send(HTTPStatus.OK, "application/javascript; charset=utf-8", (ROOT / "static" / "app.js").read_bytes())
        elif path == "/static/diagnostics.css":
            self._send(HTTPStatus.OK, "text/css; charset=utf-8", (ROOT / "static" / "diagnostics.css").read_bytes())
        elif path == "/api/state":
            self._send(HTTPStatus.OK, "application/json", json.dumps(self.app.snapshot()).encode("utf-8"))
        else:
            self._send(HTTPStatus.NOT_FOUND, "text/plain", b"Not found")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/action/start":
                length = int(self.headers.get("Content-Length", "0"))
                body = (
                    json.loads(self.rfile.read(length))
                    if length
                    else {}
                )
                self.app.start_or_resume(body.get("runs_this_session"))
            elif path == "/api/action/stop-after-current":
                self.app.stop_after_current()
            elif path == "/api/action/stop-now":
                self.app.stop_now()
            elif path == "/api/action/revalidate":
                self.app.revalidate_operational()
            else:
                self._send(HTTPStatus.NOT_FOUND, "text/plain", b"Not found")
                return
            self._send(HTTPStatus.OK, "application/json", json.dumps(self.app.snapshot()).encode("utf-8"))
        except RuntimeError as exc:
            self._send(HTTPStatus.CONFLICT, "application/json", json.dumps({"error": str(exc)}).encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        return


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local TEP formal process monitor")
    parser.add_argument("--mock", action="store_true", help="Use isolated synthetic runs; never invoke Docker or datasets")
    parser.add_argument("--simulate-only", action="store_true", help="Run the deterministic mock to completion and exit")
    parser.add_argument("--host", default=BIND_HOST)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--state-dir")
    parser.add_argument("--repo-root", default=str(ROOT.parents[1]))
    parser.add_argument("--workspace-root", default=str(ROOT.parents[2]))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.host != BIND_HOST:
        raise SystemExit("Monitor binding is restricted to 127.0.0.1")
    if args.simulate_only and not args.mock:
        raise SystemExit("--simulate-only requires --mock")
    state_dir = Path(args.state_dir) if args.state_dir else (
        Path(tempfile.gettempdir()) / "PSQZA_FORMAL_MONITOR_MOCK"
        if args.mock
        else Path(args.workspace_root) / "results" / "formal" / "monitor_controller"
    )
    app = MonitorApplication(Path(args.repo_root), Path(args.workspace_root), state_dir, mock=args.mock)
    if args.simulate_only:
        assert app.mock_experiment is not None
        result = app.mock_experiment.run_all()
        print(json.dumps({"state_dir": str(state_dir.resolve()), "state": result.to_dict()}, indent=2))
        return
    MonitorHandler.app = app
    server = ThreadingHTTPServer((BIND_HOST, args.port), MonitorHandler)
    print(f"Formal monitor listening on http://{BIND_HOST}:{args.port} (mock={args.mock})")
    server.serve_forever()


if __name__ == "__main__":
    main()

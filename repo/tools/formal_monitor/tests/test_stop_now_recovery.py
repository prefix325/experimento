from __future__ import annotations

import hashlib
import json
import sys
import threading
from pathlib import Path

import pytest

from tools.formal_monitor.gates import GateReport
from tools.formal_monitor.monitor import MonitorApplication
from tools.formal_monitor.process_control import (
    FormalBatchCommand,
    RealProcessController,
    ScientificActivityReport,
)
from tools.formal_monitor.real_mode import RealExperiment
from tools.formal_monitor.state import StateStore


REPO = Path(__file__).resolve().parents[3]


def ready_gate() -> GateReport:
    return GateReport(True, "REAL START READY", [], {"all": True}, {})


class RecordingHandle:
    def __init__(self) -> None:
        self.closed = False
        self.flush_count = 0
        self.close_count = 0

    def flush(self) -> None:
        if self.closed:
            raise ValueError("I/O operation on closed file.")
        self.flush_count += 1

    def close(self) -> None:
        if self.closed:
            raise ValueError("I/O operation on closed file.")
        self.closed = True
        self.close_count += 1


def test_close_logs_is_safe_from_two_threads():
    controller = RealProcessController(ready_gate())
    stdout = RecordingHandle()
    stderr = RecordingHandle()
    controller._stdout_handle = stdout
    controller._stderr_handle = stderr
    barrier = threading.Barrier(2)
    failures = []

    def close():
        try:
            barrier.wait()
            controller._close_logs()
        except BaseException as exc:
            failures.append(exc)

    threads = [threading.Thread(target=close) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert failures == []
    assert stdout.flush_count == stdout.close_count == 1
    assert stderr.flush_count == stderr.close_count == 1
    assert controller._stdout_handle is None
    assert controller._stderr_handle is None


def test_close_logs_is_idempotent_across_repeated_calls():
    controller = RealProcessController(ready_gate())
    stdout = RecordingHandle()
    controller._stdout_handle = stdout

    controller._close_logs()
    controller._close_logs()
    controller._close_logs()

    assert stdout.flush_count == 1
    assert stdout.close_count == 1
    assert controller._reader_threads == []


def test_stop_now_and_wait_do_not_raise_closed_file(tmp_path):
    diagnostics = tmp_path / "diagnostics"
    results = tmp_path / "results" / "target"
    results.parent.mkdir(parents=True)
    command = FormalBatchCommand(
        argv=[sys.executable, "-c", "import time; time.sleep(30)"],
        simulation_run_ordinal=402,
        results_directory=results,
        component="dpca",
        diagnostic_directory=diagnostics,
    )
    controller = RealProcessController(ready_gate())
    controller.start(command)
    failures = []

    def wait():
        try:
            controller.wait()
        except BaseException as exc:
            failures.append(exc)

    waiter = threading.Thread(target=wait)
    waiter.start()
    controller.stop_now(timeout_seconds=5)
    waiter.join(timeout=10)

    assert waiter.is_alive() is False
    assert failures == []
    assert controller.last_exit_code is not None
    assert controller._stdout_handle is None
    assert controller._stderr_handle is None


class StopNowController:
    last_exit_code = None
    last_pid = 4402

    def __init__(self, gate_report):
        self.gate_report = gate_report
        self.started = threading.Event()
        self.stopped = threading.Event()

    def start(self, command):
        self.started.set()

    def wait(self):
        self.stopped.wait(timeout=10)
        self.last_exit_code = 1
        return 1

    def stop_now(self):
        self.last_exit_code = 1
        self.stopped.set()


def test_intentional_stop_now_preserves_aborted_attempt_without_active_error(
    tmp_path,
):
    store = StateStore(tmp_path / "real-controller", mock=False)
    experiment = RealExperiment(
        store,
        REPO,
        tmp_path,
        ready_gate(),
        controller_factory=StopNowController,
    )
    outcome = []
    worker = threading.Thread(
        target=lambda: outcome.append(
            experiment.run_one(run_event_id="run-event-stop-now")
        )
    )
    worker.start()
    assert experiment.controller.started.wait(timeout=10)

    experiment.request_stop_now()
    worker.join(timeout=10)

    attempt = store.attempts_root / "target" / "run_001" / "attempt_0001"
    status = json.loads((attempt / "status.json").read_text(encoding="utf-8"))
    assert outcome == ["ABORTED"]
    assert status["status"] == "ABORTED"
    assert status["process_started"] is True
    assert status["dpca_status"] == "ABORTED"
    assert status["llm_status"] == "NOT_REQUIRED"
    assert status["lot_status"] == "ABORTED"
    assert store.latest_error() is None
    assert not (attempt.parent / "COMPLETE.json").exists()
    assert "STOP_NOW_COMPLETED" in {
        event["event_type"] for event in store.recent_events()
    }


def tree_digest(root: Path) -> str:
    lines = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        lines.append(
            f"{path.relative_to(root).as_posix()}|"
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}"
        )
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def forced_stop_application(tmp_path, monkeypatch, activity):
    workspace = tmp_path / "workspace"
    state_root = workspace / "results" / "formal" / "monitor_controller"
    store = StateStore(state_root, mock=False)
    for run in range(1, 402):
        marker = (
            store.attempts_root
            / "target"
            / f"run_{run:03d}"
            / "COMPLETE.json"
        )
        marker.parent.mkdir(parents=True)
        marker.write_text("{}\n", encoding="utf-8")
    state = store.load()
    state.cohort = "target"
    attempt = store.begin_attempt(
        state, 402, run_event_id="run-event-forced-stop"
    )
    store.update_attempt(
        state,
        attempt,
        status="RUNNING",
        process_started=True,
        dpca_status="RUNNING",
        llm_status="NOT_REQUIRED",
        lot_status="RUNNING",
    )
    store.record_error(
        state=state,
        run_event_id="run-event-forced-stop",
        error_type="ValueError",
        message="I/O operation on closed file.",
        traceback_text=(
            "Traceback (most recent call last):\n"
            "  File \"X:\\repo\\tools\\formal_monitor\\process_control.py\", "
            "line 142, in _close_logs\n"
            "ValueError: I/O operation on closed file.\n"
        ),
        component="dpca",
        exit_code=1,
        attempt_dir=attempt,
    )
    store.abort_current(state, attempt, status="ABORTED")
    monkeypatch.setattr(
        "tools.formal_monitor.monitor.inspect_static_gates",
        lambda repo, root: ready_gate(),
    )
    app = MonitorApplication(
        REPO,
        workspace,
        state_root,
        mock=False,
        scientific_activity_probe=lambda: activity,
    )
    return app, attempt


class RecoveryController:
    last_exit_code = 0
    last_pid = 9402

    def __init__(self, gate_report):
        self.gate_report = gate_report
        self.started_components = []

    def prepare(self, command):
        command.results_directory.mkdir(parents=True, exist_ok=True)
        return command.results_directory.parent

    def start(self, command):
        self.started_components.append(command.component)

    def wait(self):
        return 0

    def stop_now(self):
        return None


def test_forced_stop_revalidation_preserves_attempt_and_plans_attempt_0002(
    tmp_path, monkeypatch
):
    activity = ScientificActivityReport(
        active=False, docker_engine_available=True
    )
    app, attempt_0001 = forced_stop_application(
        tmp_path, monkeypatch, activity
    )
    before = tree_digest(attempt_0001)
    controller = RecoveryController(ready_gate())
    app.real_experiment.controller = controller

    assert app.snapshot()["operational_revalidation_enabled"] is True
    report = app.revalidate_operational()

    recovered = app.store.load()
    assert report["process_started"] is False
    assert report["component"] == "dpca"
    assert report["planned_attempt_id"] == "attempt_0002"
    assert report["partial_results_reused"] is False
    assert report["docker_engine_available"] is True
    assert recovered.global_status == "READY"
    assert recovered.dpca_status == "PENDING"
    assert recovered.llm_status == "NOT_REQUIRED"
    assert recovered.lot_status == "PENDING"
    assert app.store.latest_error()["status"] == "RESOLVED/HISTORICAL"
    assert tree_digest(attempt_0001) == before

    assert app.real_experiment.run_one(
        run_event_id="run-event-attempt-0002"
    ) == "COMPONENTS_COMPLETE"
    attempt_0002 = attempt_0001.parent / "attempt_0002"
    second_status = json.loads(
        (attempt_0002 / "status.json").read_text(encoding="utf-8")
    )
    assert controller.started_components == ["dpca"]
    assert second_status["attempt_id"] == "attempt_0002"
    assert second_status["dpca_status"] == "COMPLETE"
    assert second_status["llm_status"] == "NOT_REQUIRED"
    assert tree_digest(attempt_0001) == before
    second_events = [
        json.loads(line)
        for line in (attempt_0002 / "operational_events.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert not any(
        event["event_type"] == "COMPONENT_REUSED_IMMUTABLE"
        and event["component"] == "dpca"
        for event in second_events
    )


def test_forced_stop_revalidation_is_blocked_by_active_scientific_process(
    tmp_path, monkeypatch
):
    activity = ScientificActivityReport(
        active=True,
        docker_engine_available=True,
        processes=("pid=9402 powershell run_formal_batch_offline.ps1",),
    )
    app, attempt = forced_stop_application(tmp_path, monkeypatch, activity)
    before = tree_digest(attempt)

    with pytest.raises(RuntimeError, match="scientific process/container"):
        app.revalidate_operational()

    assert app.store.load().global_status == "STOPPED"
    assert app.store.latest_error()["status"] == "ACTIVE"
    assert tree_digest(attempt) == before

import json
import sys
from pathlib import Path

import pytest

from tools.formal_monitor.gates import GateReport
from tools.formal_monitor.monitor import MonitorApplication, real_start_is_enabled
from tools.formal_monitor.process_control import FormalBatchCommand, RealProcessController
from tools.formal_monitor.real_mode import RealExperiment
from tools.formal_monitor.state import MonitorState, StateStore


REPO = Path(__file__).resolve().parents[3]
WORKSPACE = REPO.parent


def ready_gate() -> GateReport:
    return GateReport(True, "REAL START READY", [], {"all": True}, {})


def test_startup_failure_before_process_is_durable_and_not_partial_or_complete(tmp_path):
    class FailingController:
        last_exit_code = None
        last_pid = None

        def __init__(self, gate_report):
            self.gate_report = gate_report

        def start(self, command):
            raise OSError(267, "invalid directory")

        def wait(self):
            raise AssertionError("wait must not run when process creation failed")

        def stop_now(self):
            return None

    store = StateStore(tmp_path / "real-controller", mock=False)
    experiment = RealExperiment(
        store,
        REPO,
        WORKSPACE,
        ready_gate(),
        controller_factory=FailingController,
    )

    assert experiment.run_one(run_event_id="run-event-test") == "FAILED"

    attempt = store.attempts_root / "target" / "run_001" / "attempt_0001"
    status = json.loads((attempt / "status.json").read_text())
    assert status["status"] == "FAILED_TO_START"
    assert status["process_started"] is False
    assert not (attempt.parent / "COMPLETE.json").exists()
    assert store.status_of("target", 1) == "FAILED_TO_START"
    error = store.latest_error()
    assert error is not None
    assert error["error_type"] == "OSError"
    assert error["component"] == "dpca"
    assert error["exit_code"] is None
    assert Path(error["log_path"]).is_file()
    event_types = [event["event_type"] for event in store.recent_events()]
    assert event_types == [
        "LOT_SELECTED", "COMPONENT_START_REQUESTED", "ERROR"
    ]


def test_exit_one_preserves_error_and_exposes_causal_dpca_logs(tmp_path):
    class ExitOneController:
        last_exit_code = 1
        last_pid = 5501

        def __init__(self, gate_report):
            self.gate_report = gate_report
            self.stderr_path = None

        def start(self, command):
            logs = command.diagnostic_directory
            assert logs is not None
            logs.mkdir(parents=True, exist_ok=True)
            self.stderr_path = logs / "dpca.stderr.log"
            self.stderr_path.write_text(
                "Configuration hash mismatch for formal.json\n",
                encoding="utf-8",
            )
            (logs / "dpca.stdout.log").write_text("", encoding="utf-8")
            (logs / "dpca.command.json").write_text(
                json.dumps({"argv": command.argv}), encoding="utf-8"
            )

        def wait(self):
            return 1

        def first_causal_stderr(self):
            return "Configuration hash mismatch for formal.json"

        def stop_now(self):
            return None

    store = StateStore(tmp_path / "real-controller", mock=False)
    experiment = RealExperiment(
        store,
        REPO,
        tmp_path,
        ready_gate(),
        controller_factory=ExitOneController,
    )

    final_state = experiment.run_all(
        max_runs=1, run_event_id="run-event-exit-one"
    )

    attempt = store.attempts_root / "target" / "run_001" / "attempt_0001"
    status = json.loads((attempt / "status.json").read_text())
    assert final_state.global_status == "ERROR"
    assert status["status"] == "FAILED"
    assert status["dpca_status"] == "FAILED"
    assert status["lot_status"] == "FAILED"
    assert not (attempt.parent / "COMPLETE.json").exists()
    error = store.latest_error()
    assert "Configuration hash mismatch" in error["message"]
    diagnostic = store.latest_error_diagnostic()
    assert diagnostic["first_causal_stderr"] == (
        "Configuration hash mismatch for formal.json"
    )
    assert diagnostic["component_stderr_path"].endswith("dpca.stderr.log")
    assert diagnostic["component_stdout"] == ""
    events = store.recent_events()
    assert [event["event_type"] for event in events] == [
        "LOT_SELECTED",
        "COMPONENT_START_REQUESTED",
        "COMPONENT_STARTED",
        "COMPONENT_FINISHED",
        "ERROR",
    ]
    assert events[-2]["level"] == "ERROR"


def test_missing_cwd_is_created_before_mocked_popen(tmp_path, monkeypatch):
    observed = {}

    class FakeProcess:
        pid = 4312
        stdout = None
        stderr = None

        def poll(self):
            return None

    def fake_popen(argv, **kwargs):
        observed["argv"] = argv
        observed["cwd"] = Path(kwargs["cwd"])
        assert observed["cwd"].is_dir()
        return FakeProcess()

    monkeypatch.setattr(
        "tools.formal_monitor.process_control.subprocess.Popen", fake_popen
    )
    results = tmp_path / "missing" / "method-freeze" / "target"
    command = FormalBatchCommand(
        argv=["mock-formal-command"],
        simulation_run_ordinal=1,
        results_directory=results,
        component="dpca",
    )
    controller = RealProcessController(ready_gate())

    controller.start(command)

    assert observed["cwd"] == results.parent
    assert results.parent.is_dir()
    assert results.is_dir()
    assert controller.last_pid == 4312


def test_directory_creation_failure_is_failed_to_start_and_skips_popen(
    tmp_path, monkeypatch
):
    popen_called = False

    def forbidden_popen(*args, **kwargs):
        nonlocal popen_called
        popen_called = True
        raise AssertionError("Popen must not be called")

    def fail_directory_creation(path):
        raise PermissionError(f"cannot create {path}")

    monkeypatch.setattr(
        "tools.formal_monitor.process_control.subprocess.Popen", forbidden_popen
    )
    store = StateStore(tmp_path / "real-controller", mock=False)
    experiment = RealExperiment(
        store,
        REPO,
        tmp_path,
        ready_gate(),
        controller_factory=lambda gate: RealProcessController(
            gate, directory_preparer=fail_directory_creation
        ),
    )

    assert experiment.run_one(run_event_id="run-event-mkdir-failure") == "FAILED"

    attempt = store.attempts_root / "target" / "run_001" / "attempt_0001"
    status = json.loads((attempt / "status.json").read_text())
    assert status["status"] == "FAILED_TO_START"
    assert status["process_started"] is False
    assert popen_called is False


def test_popen_exception_after_cwd_preparation_is_failed_to_start(
    tmp_path, monkeypatch
):
    def fail_popen(*args, **kwargs):
        assert Path(kwargs["cwd"]).is_dir()
        raise OSError(267, "mocked Popen failure")

    monkeypatch.setattr(
        "tools.formal_monitor.process_control.subprocess.Popen", fail_popen
    )
    store = StateStore(tmp_path / "real-controller", mock=False)
    experiment = RealExperiment(store, REPO, tmp_path, ready_gate())

    assert experiment.run_one(run_event_id="run-event-popen-failure") == "FAILED"

    attempt = store.attempts_root / "target" / "run_001" / "attempt_0001"
    status = json.loads((attempt / "status.json").read_text())
    assert status["status"] == "FAILED_TO_START"
    assert status["process_started"] is False


def test_monitor_restart_preserves_persisted_error_even_when_gate_is_ready(tmp_path):
    store = StateStore(tmp_path / "real-controller", mock=False)
    state = store.load()
    state.global_status = "ERROR"
    state.gate_reasons = ["FORMAL_BATCH_FAILED: startup"]
    store.save(state)

    restarted = RealExperiment(store, REPO, WORKSPACE, ready_gate())

    assert restarted.state.global_status == "ERROR"
    assert restarted.state.gate_reasons == ["FORMAL_BATCH_FAILED: startup"]
    assert store.load().global_status == "ERROR"


def test_monitor_restart_preserves_resumable_session_limit_stop(tmp_path):
    store = StateStore(tmp_path / "real-controller", mock=False)
    state = store.load()
    state.global_status = "STOPPED"
    state.stop_outcome = "SESSION_LIMIT_REACHED"
    state.completed_batches = 1
    state.llm_status = "NOT_REQUIRED"
    state.dpca_status = "COMPLETE"
    state.lot_status = "COMPLETE"
    store.save(state)
    complete = store.attempts_root / "target" / "run_001" / "COMPLETE.json"
    complete.parent.mkdir(parents=True)
    complete.write_text("{}\n", encoding="utf-8")

    restarted = RealExperiment(store, REPO, WORKSPACE, ready_gate())

    assert restarted.state.global_status == "STOPPED"
    assert restarted.state.stop_outcome == "SESSION_LIMIT_REACHED"
    assert restarted.state.completed_batches == 1
    assert real_start_is_enabled(ready_gate(), restarted.state, mock=False) is True


def test_unresolved_error_disables_start_and_server_rejects_it(tmp_path):
    state = MonitorState(global_status="ERROR")
    assert real_start_is_enabled(ready_gate(), state, mock=False) is False
    state.global_status = "READY"
    assert real_start_is_enabled(ready_gate(), state, mock=False) is True

    app = MonitorApplication(
        REPO, WORKSPACE, tmp_path / "real-monitor", mock=False
    )
    persisted = app.store.load()
    persisted.global_status = "ERROR"
    app.store.save(persisted)
    with pytest.raises(RuntimeError, match="revalidate"):
        app.start_or_resume(1)
    assert app.worker is None


def test_ready_state_enables_real_start():
    state = MonitorState(global_status="READY")

    assert real_start_is_enabled(ready_gate(), state, mock=False) is True


def test_error_state_disables_real_start():
    state = MonitorState(global_status="ERROR")

    assert real_start_is_enabled(ready_gate(), state, mock=False) is False


def test_running_state_disables_real_start():
    state = MonitorState(global_status="RUNNING", lot_status="RUNNING")

    assert real_start_is_enabled(ready_gate(), state, mock=False) is False


def test_session_limit_after_complete_lot_enables_real_start():
    state = MonitorState(
        global_status="STOPPED",
        stop_outcome="SESSION_LIMIT_REACHED",
        completed_batches=1,
        llm_status="NOT_REQUIRED",
        dpca_status="COMPLETE",
        lot_status="COMPLETE",
    )

    assert real_start_is_enabled(ready_gate(), state, mock=False) is True


def test_clean_stop_without_active_lot_enables_real_start():
    state = MonitorState(
        global_status="STOPPED",
        stop_outcome="STOPPED_CLEAN",
    )

    assert real_start_is_enabled(ready_gate(), state, mock=False) is True


@pytest.mark.parametrize("stop_outcome", ["STOPPED_FORCED", None])
def test_forced_or_inconsistent_stop_disables_real_start(stop_outcome):
    state = MonitorState(
        global_status="STOPPED",
        stop_outcome=stop_outcome,
        lot_status="ABORTED" if stop_outcome == "STOPPED_FORCED" else "PENDING",
    )

    assert real_start_is_enabled(ready_gate(), state, mock=False) is False


def test_active_error_disables_otherwise_resumable_session_limit():
    state = MonitorState(
        global_status="STOPPED",
        stop_outcome="SESSION_LIMIT_REACHED",
        completed_batches=1,
        llm_status="NOT_REQUIRED",
        dpca_status="COMPLETE",
        lot_status="COMPLETE",
    )

    assert real_start_is_enabled(
        ready_gate(), state, mock=False, current_error_active=True
    ) is False


def test_operational_revalidation_sets_ready_without_popen_and_keeps_history(
    tmp_path, monkeypatch
):
    def forbidden_popen(*args, **kwargs):
        raise AssertionError("Operational revalidation must not call Popen")

    monkeypatch.setattr(
        "tools.formal_monitor.process_control.subprocess.Popen", forbidden_popen
    )
    store = StateStore(tmp_path / "real-controller", mock=False)
    state = store.load()
    state.global_status = "ERROR"
    state.gate_reasons = ["FORMAL_BATCH_FAILED: historical"]
    store.save(state)
    store.record_error(
        state=state,
        run_event_id="historical-error",
        error_type="OSError",
        message="historical startup failure",
        traceback_text="historical traceback",
        component="controller",
        exit_code=None,
        attempt_dir=None,
    )
    experiment = RealExperiment(store, REPO, tmp_path, ready_gate())

    report = experiment.revalidate_operational(
        ready_gate(), run_event_id="revalidation-test"
    )

    recovered = store.load()
    assert report["cwd_exists"] is True
    assert report["results_directory_exists"] is True
    assert report["process_started"] is False
    assert recovered.global_status == "READY"
    assert recovered.current_simulation_run is None
    assert recovered.current_attempt_id is None
    error = store.latest_error()
    assert error["status"] == "RESOLVED/HISTORICAL"
    assert error["historical"] is True
    assert error["message"] == "historical startup failure"


@pytest.mark.parametrize("exit_code", [0, 7])
def test_process_controller_persists_raw_streams_and_unambiguous_exit_code(
    tmp_path, exit_code
):
    results = tmp_path / "existing" / "target"
    results.parent.mkdir(parents=True)
    diagnostics = tmp_path / "diagnostics"
    command = FormalBatchCommand(
        argv=[
            sys.executable,
            "-c",
            (
                "import sys; print('raw stdout'); "
                "print('raw stderr', file=sys.stderr); "
                f"raise SystemExit({exit_code})"
            ),
        ],
        simulation_run_ordinal=1,
        results_directory=results,
        component="dpca",
        run_event_id="run-event-streams",
        diagnostic_directory=diagnostics,
    )
    controller = RealProcessController(ready_gate())

    controller.start(command)
    observed = controller.wait()

    assert observed == exit_code
    assert controller.last_exit_code == exit_code
    assert controller.last_exit_code is not None
    assert (diagnostics / "dpca.stdout.log").read_text().strip() == "raw stdout"
    assert (diagnostics / "dpca.stderr.log").read_text().strip() == "raw stderr"
    assert controller.first_causal_stderr() == "raw stderr"
    metadata = json.loads((diagnostics / "dpca.command.json").read_text())
    assert metadata["run_event_id"] == "run-event-streams"


def test_llm_diagnostic_exposes_full_raw_stderr_command_and_final_exception(tmp_path):
    store = StateStore(tmp_path / "real-controller", mock=False)
    state = store.load()
    state.cohort = "target"
    attempt = store.begin_attempt(
        state, 58, run_event_id="run-event-llm-diagnostic"
    )
    logs = attempt / "logs"
    logs.mkdir()
    raw_stderr = (
        "Traceback (most recent call last):\n"
        "  File \"pipeline.py\", line 1, in run\n"
        "RuntimeError: LLM output reached max_output_tokens before completing JSON\n"
    )
    (logs / "llm.stderr.log").write_text(raw_stderr, encoding="utf-8")
    (logs / "llm.stdout.log").write_text("", encoding="utf-8")
    command = {"component": "llm", "argv": ["powershell", "llm"]}
    (logs / "llm.command.json").write_text(
        json.dumps(command), encoding="utf-8"
    )
    store.record_error(
        state=state,
        run_event_id="run-event-llm-diagnostic",
        error_type="RuntimeError",
        message="llm failed",
        traceback_text="monitor traceback",
        component="llm",
        exit_code=1,
        attempt_dir=attempt,
    )

    diagnostic = store.latest_error_diagnostic()

    assert diagnostic["component_stderr"] == raw_stderr
    assert diagnostic["first_causal_stderr"] == (
        "RuntimeError: LLM output reached max_output_tokens before completing JSON"
    )
    assert json.loads(diagnostic["component_command"]) == command
    assert diagnostic["component_command_path"].endswith("llm.command.json")


def test_component_resume_reuses_complete_dpca_and_starts_only_llm_attempt_0002(
    tmp_path,
):
    started_components = []

    class RecordingController:
        last_exit_code = 0
        last_pid = 8802

        def __init__(self, gate_report):
            self.gate_report = gate_report

        def start(self, command):
            started_components.append(command.component)

        def wait(self):
            return 0

        def stop_now(self):
            return None

    store = StateStore(tmp_path / "real-controller", mock=False)
    for run in range(1, 58):
        complete = store.attempts_root / "target" / f"run_{run:03d}" / "COMPLETE.json"
        complete.parent.mkdir(parents=True)
        complete.write_text("{}\n", encoding="utf-8")
    failed = store.attempts_root / "target" / "run_058" / "attempt_0001"
    failed.mkdir(parents=True)
    (failed / "status.json").write_text(
        json.dumps({
            "status": "FAILED",
            "dpca_status": "COMPLETE",
            "llm_status": "FAILED",
            "lot_status": "FAILED",
        }) + "\n",
        encoding="utf-8",
    )
    experiment = RealExperiment(
        store,
        REPO,
        tmp_path,
        ready_gate(),
        controller_factory=RecordingController,
    )

    assert experiment.run_one(run_event_id="run-event-resume-58") == (
        "COMPONENTS_COMPLETE"
    )

    assert started_components == ["llm"]
    second = failed.parent / "attempt_0002" / "status.json"
    status = json.loads(second.read_text())
    assert status["dpca_status"] == "COMPLETE"
    assert status["llm_status"] == "COMPLETE"
    events = [
        json.loads(line)
        for line in (failed.parent / "attempt_0002" / "operational_events.jsonl")
        .read_text()
        .splitlines()
    ]
    assert any(
        event["event_type"] == "COMPONENT_REUSED_IMMUTABLE"
        and event["component"] == "dpca"
        for event in events
    )


@pytest.mark.parametrize("forbidden", ["ground_truth", "faultNumber", "y"])
def test_operational_log_rejects_scientific_fields(tmp_path, forbidden):
    store = StateStore(tmp_path / "operational", mock=False)

    with pytest.raises(ValueError, match="Forbidden scientific field"):
        store.append_event(
            "TEST",
            "should fail",
            state=MonitorState(),
            details={forbidden: "forbidden"},
        )


def test_diagnostics_ui_has_summary_details_and_no_prohibited_fields():
    html = (
        REPO / "tools" / "formal_monitor" / "templates" / "index.html"
    ).read_text(encoding="utf-8")
    javascript = (
        REPO / "tools" / "formal_monitor" / "static" / "app.js"
    ).read_text(encoding="utf-8")

    assert "LOGS / DIAGNÓSTICO" in html
    assert "ERROR SUMMARY" in html
    assert "VER DETALHES" in html
    assert 'id="error-first-causal"' in html
    assert 'id="error-component-stderr"' in html
    assert 'id="error-component-stdout"' in html
    assert 'id="error-component-command"' in html
    assert 'id="error-status"' in html
    assert 'id="revalidate"' in html
    assert "REVALIDAR / LIMPAR ERRO OPERACIONAL" in html
    assert 'id="operational-events"' in html
    combined = (html + javascript).lower()
    assert "ground_truth" not in combined
    assert "faultnumber" not in combined

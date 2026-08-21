import json
from pathlib import Path

import pytest

from tools.formal_monitor.eta import estimate_total_eta_seconds, robust_completed_duration_seconds
from tools.formal_monitor.gates import GateReport, inspect_static_gates
from tools.formal_monitor.mock_mode import MockExperiment
from tools.formal_monitor.monitor import BIND_HOST
from tools.formal_monitor.process_control import FormalCommandBuilder
from tools.formal_monitor.real_mode import RealExperiment, build_formal_lots
from tools.formal_monitor.state import StateStore


REPO = Path(__file__).resolve().parents[3]
WORKSPACE = REPO.parent


def mock_experiment(tmp_path, *, cohort="target", runs=(1,), windows=189):
    store = StateStore(tmp_path / "MOCK_state", mock=True)
    experiment = MockExperiment(store, cohort=cohort, total_runs=max(runs), window_total=windows)
    experiment.run_order = list(runs)
    experiment.state.total_batches = len(runs)
    store.save(experiment.state)
    return experiment


def test_target_confirmed_detection_completes_early(tmp_path):
    experiment = mock_experiment(tmp_path, runs=(2,))
    assert experiment.run_one() == "CONFIRMED_DETECTION"
    assert experiment.store.status_of("target", 2) == "COMPLETE"
    assert experiment.state.window_completed == 8
    assert experiment.state.llm_status == "STOPPED_EARLY"
    assert experiment.state.dpca_status == "COMPLETE"
    assert experiment.state.lot_status == "COMPLETE"


def test_no_detection_completes_at_natural_end(tmp_path):
    experiment = mock_experiment(tmp_path, runs=(1,), windows=12)
    assert experiment.run_one() == "NO_FIRST_INDICATION"
    assert experiment.state.window_completed == 12
    assert experiment.store.status_of("target", 1) == "COMPLETE"


def test_normal_holdout_never_stops_early(tmp_path):
    experiment = mock_experiment(tmp_path, cohort="normal_holdout", runs=(2,), windows=12)
    assert experiment.run_one() == "NORMAL_TRAJECTORY_COMPLETE"
    assert experiment.state.window_completed == 12


def test_lot_cannot_complete_while_dpca_is_incomplete(tmp_path):
    experiment = mock_experiment(tmp_path, runs=(1,), windows=8)
    attempt = experiment.store.begin_attempt(experiment.state, 1)
    with pytest.raises(RuntimeError, match="DPCA"):
        experiment.store.complete_attempt(
            experiment.state,
            attempt,
            completion_reason="NO_FIRST_INDICATION",
            duration_seconds=8,
            llm_status="COMPLETE",
            dpca_status="RUNNING",
        )
    assert experiment.store.status_of("target", 1) != "COMPLETE"


def test_partial_is_never_complete_and_restarts_same_run(tmp_path):
    experiment = mock_experiment(tmp_path, runs=(1, 2), windows=8)
    attempt = experiment.store.begin_attempt(experiment.state, 1)
    experiment.store.abort_current(experiment.state, attempt, status="PARTIAL")
    assert experiment.store.status_of("target", 1) == "PARTIAL"
    assert experiment.store.next_pending("target", [1, 2]) == 1
    assert not (attempt.parent / "COMPLETE.json").exists()


def test_stop_now_aborts_current_and_does_not_complete(tmp_path):
    experiment = mock_experiment(tmp_path, runs=(1,), windows=20)

    def stop_at_third_window(current, window_id):
        if window_id == 2:
            current.request_stop_now()

    assert experiment.run_one(window_hook=stop_at_third_window) == "ABORTED"
    assert experiment.store.status_of("target", 1) == "ABORTED"
    assert experiment.state.stop_outcome == "STOPPED_FORCED"
    assert experiment.state.completed_batches == 0


def test_mock_can_persist_failed_without_complete(tmp_path):
    experiment = mock_experiment(tmp_path, runs=(1,), windows=20)

    def fail_at_third_window(current, window_id):
        if window_id == 2:
            current.fail_current()

    assert experiment.run_one(window_hook=fail_at_third_window) == "FAILED"
    assert experiment.store.status_of("target", 1) == "FAILED"
    assert experiment.state.global_status == "ERROR"
    assert experiment.state.completed_batches == 0


def test_stop_after_current_finishes_one_batch_and_starts_no_next(tmp_path):
    experiment = mock_experiment(tmp_path, runs=(1, 2), windows=10)

    def request_clean_stop(current, window_id):
        if window_id == 2:
            current.request_stop_after_current()

    experiment.run_one(window_hook=request_clean_stop)
    assert experiment.store.status_of("target", 1) == "COMPLETE"
    assert experiment.store.status_of("target", 2) == "PENDING"
    assert experiment.state.stop_outcome == "STOPPED_CLEAN"


def test_runs_this_session_limits_controller_only(tmp_path):
    experiment = mock_experiment(
        tmp_path, runs=(1, 2, 3), windows=6
    )
    experiment.run_all(max_runs=2)
    assert experiment.state.completed_batches == 2
    assert experiment.store.status_of("target", 3) == "PENDING"
    assert experiment.state.stop_outcome == "SESSION_LIMIT_REACHED"


def test_reboot_recovery_marks_unstarted_attempt_failed_to_start(tmp_path):
    root = tmp_path / "MOCK_reboot"
    store = StateStore(root, mock=True)
    first = MockExperiment(store, total_runs=2, window_total=10)
    store.begin_attempt(first.state, 1)
    recovered = MockExperiment(StateStore(root, mock=True), total_runs=2, window_total=10)
    assert recovered.store.status_of("target", 1) == "FAILED_TO_START"
    assert recovered.store.next_pending("target", [1, 2]) == 1


def test_reboot_recovery_marks_started_attempt_partial_and_restarts_it(tmp_path):
    root = tmp_path / "MOCK_reboot_started"
    store = StateStore(root, mock=True)
    first = MockExperiment(store, total_runs=2, window_total=10)
    attempt = store.begin_attempt(first.state, 1)
    store.update_attempt(
        first.state,
        attempt,
        status="RUNNING",
        process_started=True,
    )

    recovered = MockExperiment(
        StateStore(root, mock=True), total_runs=2, window_total=10
    )

    assert recovered.store.status_of("target", 1) == "PARTIAL"
    assert recovered.store.next_pending("target", [1, 2]) == 1


def test_next_batch_and_total_progress_use_only_complete(tmp_path):
    experiment = mock_experiment(tmp_path, runs=(1, 2), windows=5)
    experiment.run_one()
    assert experiment.state.completed_batches == 1
    assert experiment.store.next_pending("target", [1, 2]) == 2
    assert 100 * experiment.state.completed_batches / experiment.state.total_batches == 50


def test_eta_uses_only_supplied_complete_durations():
    assert robust_completed_duration_seconds([100, 80, 120]) == 100
    assert estimate_total_eta_seconds([100, 80, 120], 4) == 400
    assert estimate_total_eta_seconds([], 4) is None


def test_mock_directory_is_isolated_from_formal_results(tmp_path):
    with pytest.raises(ValueError, match="marked MOCK"):
        StateStore(tmp_path / "ordinary", mock=True)
    with pytest.raises(ValueError, match="results/formal"):
        StateStore(tmp_path / "results" / "formal" / "MOCK", mock=True)


def test_monitor_is_localhost_only_and_real_button_starts_disabled():
    assert BIND_HOST == "127.0.0.1"
    html = (REPO / "tools" / "formal_monitor" / "templates" / "index.html").read_text(encoding="utf-8")
    assert '<button id="start" disabled>' in html
    assert "ANOMALY persistence" not in html
    assert "Full-window verification" in html
    assert 'id="lot-status"' in html
    assert 'id="runs-this-session"' in html


def test_current_real_gate_is_internally_consistent_without_dataset_access():
    report = inspect_static_gates(REPO, WORKSPACE)
    assert report.status == ("REAL START READY" if report.ready else "REAL START BLOCKED")
    assert bool(report.reasons) is (not report.ready)


def test_real_plan_covers_four_frozen_detector_cohorts():
    lots = build_formal_lots(REPO / "experiments" / "tep" / "local_llm" / "config")
    assert len(lots) == 1000
    assert sum(lot.cohort == "target" for lot in lots) == 500
    assert sum(lot.cohort == "normal_holdout" for lot in lots) == 500
    assert sum(lot.llm_ordinal is not None and lot.cohort == "target" for lot in lots) == 50
    assert sum(lot.llm_ordinal is not None and lot.cohort == "normal_holdout" for lot in lots) == 50
    assert sum(lot.dpca_ordinal > 0 for lot in lots) == 1000


def test_real_controller_does_not_start_before_explicit_run_one(tmp_path):
    started = []

    class FakeController:
        def __init__(self, gate_report):
            self.gate_report = gate_report

        def start(self, command):
            started.append(command)

        def wait(self):
            status = json.loads(
                (
                    store.attempts_root / "target" / "run_001" /
                    "attempt_0001" / "status.json"
                ).read_text()
            )
            assert status["status"] == "RUNNING"
            assert status["process_started"] is True
            return 0

        def stop_now(self):
            return None

    gate = GateReport(True, "REAL START READY", [], {"all": True}, {})
    store = StateStore(tmp_path / "real-state", mock=False)
    experiment = RealExperiment(
        store, REPO, WORKSPACE, gate, controller_factory=FakeController
    )
    assert started == []
    assert experiment.run_one() == "COMPONENTS_COMPLETE"
    assert len(started) == 1
    assert started[0].argv[started[0].argv.index("-Detector") + 1] == "dpca"
    assert store.status_of("target", 1) == "COMPLETE"


def test_process_controller_builds_exactly_one_batch_command(tmp_path):
    command = FormalCommandBuilder(REPO).one_batch(
        7,
        tmp_path / "formal-run",
        cohort="target",
        detector="llm",
    )
    assert command.simulation_run_ordinal == 7
    assert command.argv[command.argv.index("-RunOrdinal") + 1] == "7"
    assert command.argv[command.argv.index("-Detector") + 1] == "llm"
    assert command.argv[command.argv.index("-Cohort") + 1] == "target"


def test_mock_telemetry_is_operational_and_explicitly_mock(tmp_path):
    experiment = mock_experiment(tmp_path, runs=(1,), windows=3)
    experiment.run_one()
    lines = experiment.store.telemetry_path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    assert record["operational_only"] is True
    assert record["mock"] is True
    assert "prompt" not in record
    assert "evidence" not in record

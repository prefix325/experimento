from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from tep_local.detection import FullWindowRefreshTracker

from .eta import estimate_current_batch_eta_seconds, estimate_total_eta_seconds
from .state import MonitorState, StateStore


@dataclass(frozen=True)
class MockScenario:
    name: str
    anomalies: frozenset[int]


def scenario_for_run(simulation_run: int, window_total: int = 189) -> MockScenario:
    cycle = int(simulation_run) % 4
    if cycle == 1:
        return MockScenario("NO_DETECTION", frozenset())
    if cycle == 2:
        return MockScenario("CONFIRMED_DETECTION", frozenset({3, 7}))
    if cycle == 3:
        return MockScenario("VERIFICATION_FAILED", frozenset({2}))
    return MockScenario("END_INCOMPLETE", frozenset({window_total - 2}))


class MockExperiment:
    def __init__(self, store: StateStore, *, cohort: str = "target", total_runs: int = 50, window_total: int = 189) -> None:
        if not store.mock:
            raise ValueError("MockExperiment requires a mock StateStore")
        self.store = store
        self.cohort = cohort
        self.run_order = list(range(1, int(total_runs) + 1))
        self.window_total = int(window_total)
        self.state = store.load()
        self.state.mode = "MOCK"
        self.state.cohort = cohort
        self.state.total_batches = len(self.run_order)
        self.state.window_total_max = self.window_total
        self.state.gate_reasons = ["REAL_FORMAL_EXECUTION_BLOCKED", "MOCK_MODE_ONLY"]
        self.state.global_status = "READY"
        self.store.recover_orphans(self.state)
        self.state.completed_batches = len(self.store.completed_runs(self.cohort, self.run_order))
        self.state.completed_durations_seconds = self.store.completed_durations(self.cohort, self.run_order)
        self.state.accumulated_active_seconds = sum(self.state.completed_durations_seconds)
        if self.state.global_status == "STOPPED":
            self.state.global_status = "READY"
        self._current_attempt: Path | None = None
        self.store.save(self.state)

    def request_stop_after_current(self) -> None:
        self.state.stop_request = "AFTER_CURRENT"
        self.state.global_status = "STOPPING" if self._current_attempt else "STOPPED"
        if self._current_attempt is None:
            self.state.stop_outcome = "STOPPED_CLEAN"
        self.store.save(self.state)

    def request_stop_now(self) -> None:
        self.state.stop_request = "NOW"
        self.state.global_status = "STOPPING"
        self.store.save(self.state)
        if self._current_attempt is None:
            self.state.global_status = "STOPPED"
            self.state.stop_outcome = "STOPPED_FORCED"
            self.state.stop_request = "NONE"
            self.store.save(self.state)

    def fail_current(self) -> None:
        if self._current_attempt is None:
            raise RuntimeError("No mock batch is currently running")
        self.store.abort_current(self.state, self._current_attempt, status="FAILED")
        self._current_attempt = None
        self.state.global_status = "ERROR"
        self.state.stop_outcome = None
        self.store.save(self.state)

    def run_one(self, *, window_hook: Callable[["MockExperiment", int], None] | None = None) -> str | None:
        simulation_run = self.store.next_pending(self.cohort, self.run_order)
        if simulation_run is None:
            self.state.global_status = "STOPPED"
            self.state.stop_outcome = "ALL_BATCHES_COMPLETE"
            self.store.save(self.state)
            return None
        self._current_attempt = self.store.begin_attempt(self.state, simulation_run)
        self.store.update_attempt(
            self.state,
            self._current_attempt,
            status="RUNNING",
            process_started=True,
            llm_status="RUNNING",
            dpca_status="RUNNING",
            lot_status="RUNNING",
        )
        tracker = FullWindowRefreshTracker(20, 5, target=self.cohort == "target")
        scenario = scenario_for_run(simulation_run, self.window_total)
        completion_reason = ""
        for window_id in range(self.window_total):
            decision = "ANOMALY" if window_id in scenario.anomalies else "NORMAL"
            update = tracker.observe(window_id, decision)
            elapsed = float(window_id + 1)
            self.state.window_completed = window_id + 1
            self.state.active_batch_seconds = elapsed
            self.state.last_llm_decision = decision
            self.state.detection_state = update.detection_state
            self.state.verification_advance = update.verification_advance
            self.state.first_indication_window = update.first_indication_window
            self.state.confirmation_window = update.confirmation_window
            self.state.eta_batch_seconds = estimate_current_batch_eta_seconds(
                elapsed, self.state.window_completed, self.window_total
            )
            self.store.update_attempt(
                self.state,
                self._current_attempt,
                window_completed=self.state.window_completed,
                detection_state=update.detection_state,
                verification_advance=update.verification_advance,
                first_indication_window=update.first_indication_window,
                confirmation_window=update.confirmation_window,
                last_llm_decision=decision,
            )
            self.store.append_telemetry({
                "global_status": self.state.global_status,
                "cohort": self.cohort,
                "simulation_run": simulation_run,
                "attempt_id": self.state.current_attempt_id,
                "window_completed": self.state.window_completed,
                "window_total_max": self.window_total,
                "detection_state": update.detection_state,
                "verification_advance": update.verification_advance,
                "host_cpu_percent": 25.0,
                "experiment_cpu_percent": 12.5,
                "host_ram_used_bytes": 8 * 1024**3,
                "container_ram_used_bytes": 2 * 1024**3,
                "gpu_util_percent": 0.0,
                "vram_used_mib": 0,
                "vram_total_mib": 8188,
            })
            if window_hook:
                window_hook(self, window_id)
            if self._current_attempt is None and self.state.global_status == "ERROR":
                return "FAILED"
            if self.state.stop_request == "NOW":
                assert self._current_attempt is not None
                self.store.abort_current(self.state, self._current_attempt, status="ABORTED")
                self._current_attempt = None
                return "ABORTED"
            if update.should_stop:
                completion_reason = "CONFIRMED_DETECTION"
                break
        final_detection = tracker.finalize()
        self.state.detection_state = final_detection.detection_state
        if self.cohort == "normal_holdout":
            completion_reason = "NORMAL_TRAJECTORY_COMPLETE"
        elif not completion_reason:
            completion_reason = final_detection.detection_state
        duration = float(self.state.window_completed)
        self.store.complete_attempt(
            self.state,
            self._current_attempt,
            completion_reason=completion_reason,
            duration_seconds=duration,
            dpca_status="COMPLETE",
        )
        self._current_attempt = None
        remaining = len(self.run_order) - self.state.completed_batches
        self.state.eta_total_seconds = estimate_total_eta_seconds(self.state.completed_durations_seconds, remaining)
        self.store.save(self.state)
        return completion_reason

    def run_all(self, max_runs: int | None = None) -> MonitorState:
        started = 0
        while self.store.next_pending(self.cohort, self.run_order) is not None:
            if max_runs is not None and started >= int(max_runs):
                self.state.global_status = "STOPPED"
                self.state.stop_outcome = "SESSION_LIMIT_REACHED"
                self.store.save(self.state)
                break
            self.run_one()
            started += 1
            if self.state.stop_outcome in {"STOPPED_CLEAN", "STOPPED_FORCED"}:
                break
        if self.state.completed_batches == len(self.run_order):
            self.state.global_status = "STOPPED"
            self.state.stop_outcome = "ALL_BATCHES_COMPLETE"
            self.store.save(self.state)
        return self.state

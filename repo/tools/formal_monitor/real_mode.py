from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .gates import GateReport
from .process_control import FormalCommandBuilder, RealProcessController
from .state import MonitorState, StateStore


FORMAL_RESULTS_ID = "TEP-METHOD-FREEZE-20260815-FULL-WINDOW-REFRESH"


@dataclass(frozen=True)
class FormalLot:
    cohort: str
    simulation_run: int
    llm_ordinal: int | None
    dpca_ordinal: int


def build_formal_lots(config_root: Path) -> list[FormalLot]:
    lots: list[FormalLot] = []
    for cohort, selection_name in (
        ("target", "formal_run_selection.json"),
        ("normal_holdout", "formal_normal_holdout_selection.json"),
    ):
        selection = json.loads((config_root / selection_name).read_text(encoding="utf-8"))
        llm_ordinals = {
            int(simulation_run): ordinal
            for ordinal, simulation_run in enumerate(selection["selected_simulation_runs"], start=1)
        }
        lots.extend(
            FormalLot(cohort, simulation_run, llm_ordinals.get(simulation_run), simulation_run)
            for simulation_run in range(1, 501)
        )
    return lots


class RealExperiment:
    """Durable 1000-lot controller; no process starts before start/resume."""

    def __init__(
        self,
        store: StateStore,
        repo_root: Path,
        workspace_root: Path,
        gate_report: GateReport,
        controller_factory: Callable[[GateReport], RealProcessController] = RealProcessController,
    ) -> None:
        if store.mock:
            raise ValueError("RealExperiment requires a non-mock StateStore")
        self.store = store
        self.repo_root = repo_root
        self.workspace_root = workspace_root
        self.gate_report = gate_report
        self.builder = FormalCommandBuilder(repo_root)
        self.controller = controller_factory(gate_report)
        self.lots = build_formal_lots(
            repo_root / "experiments" / "tep" / "local_llm" / "config"
        )
        self.state = store.load()
        had_persisted_error = self.state.global_status == "ERROR"
        self.state.mode = "REAL_READY" if gate_report.ready else "REAL_BLOCKED"
        self.state.total_batches = len(self.lots)
        if not had_persisted_error:
            self.state.gate_reasons = gate_report.reasons
        self.store.recover_orphans(self.state)
        self.state.completed_batches = sum(
            self.store.status_of(lot.cohort, lot.simulation_run) == "COMPLETE"
            for lot in self.lots
        )
        # A monitor restart must not erase the last operational failure.  The
        # gate may still be READY while the persisted execution state is ERROR;
        # those are separate facts and the UI needs both for diagnosis.
        if not had_persisted_error:
            if not gate_report.ready:
                self.state.global_status = "BLOCKED"
            elif self.state.global_status != "STOPPED":
                self.state.global_status = "READY"
        self._current_attempt: Path | None = None
        self._stop_now = False
        self._current_component: str | None = None
        self._component_process_started = False
        self._lot_process_started = False
        self._run_event_id: str | None = None
        self.store.save(self.state)

    def _next_lot(self) -> FormalLot | None:
        return next(
            (
                lot for lot in self.lots
                if self.store.status_of(lot.cohort, lot.simulation_run) != "COMPLETE"
            ),
            None,
        )

    @staticmethod
    def _llm_status_for_lot(
        lot: FormalLot, completed_components: set[str]
    ) -> str:
        if lot.llm_ordinal is None:
            return "NOT_REQUIRED"
        return "COMPLETE" if "llm" in completed_components else "PENDING"

    def _command_for(
        self,
        lot: FormalLot,
        detector: str,
        ordinal: int,
        *,
        diagnostic_directory: Path | None = None,
    ):
        results = (
            self.workspace_root / "results" / "formal" /
            FORMAL_RESULTS_ID / lot.cohort
        )
        return self.builder.one_batch(
            ordinal,
            results,
            cohort=lot.cohort,
            detector=detector,
            run_event_id=self._run_event_id,
            diagnostic_directory=diagnostic_directory,
        )

    def revalidate_operational(
        self,
        gate_report: GateReport,
        *,
        run_event_id: str,
    ) -> dict:
        """Revalidate gates and output paths without starting scientific work."""
        if self._current_attempt is not None:
            raise RuntimeError("Cannot revalidate while a formal attempt is active")
        self.state = self.store.load()
        self.gate_report = gate_report
        self.controller.gate_report = gate_report
        lot = self._next_lot()
        if lot is None:
            raise RuntimeError("No pending formal lot exists")
        forced_stop_recovery = (
            self.state.global_status == "STOPPED"
            and self.state.stop_outcome == "STOPPED_FORCED"
        )
        if forced_stop_recovery:
            attempt_status = self.store.latest_attempt_status(
                lot.cohort, lot.simulation_run
            )
            if not attempt_status or (
                attempt_status.get("status") != "ABORTED"
                or attempt_status.get("process_started") is not True
                or self.store.status_of(lot.cohort, lot.simulation_run)
                != "ABORTED"
            ):
                raise RuntimeError(
                    "Forced-stop recovery requires a preserved ABORTED attempt"
                )
        self._run_event_id = run_event_id
        completed_components = self.store.completed_components(
            lot.cohort, lot.simulation_run
        )
        if "dpca" in completed_components and lot.llm_ordinal is not None:
            component = "llm"
            ordinal = lot.llm_ordinal
        else:
            component = "dpca"
            ordinal = lot.dpca_ordinal
        command = self._command_for(lot, component, ordinal)
        try:
            cwd = self.controller.prepare(command)
        except BaseException as exc:
            self.state.global_status = "ERROR"
            self.state.gate_reasons = [
                f"OPERATIONAL_REVALIDATION_FAILED: {exc}"
            ]
            self.store.save(self.state)
            self.store.append_event(
                "OPERATIONAL_REVALIDATION_FAILED",
                str(exc),
                state=self.state,
                run_event_id=run_event_id,
                component="controller",
                level="ERROR",
                details={"process_started": False},
            )
            self._run_event_id = None
            raise

        self.state.mode = "REAL_READY"
        self.state.global_status = "READY"
        self.state.gate_reasons = []
        self.state.cohort = lot.cohort
        self.state.current_simulation_run = None
        self.state.current_attempt_id = None
        self.state.current_run_event_id = None
        self.state.window_completed = 0
        self.state.llm_status = self._llm_status_for_lot(
            lot, completed_components
        )
        self.state.dpca_status = (
            "COMPLETE" if "dpca" in completed_components else "PENDING"
        )
        self.state.lot_status = "PENDING"
        self.state.stop_request = "NONE"
        self.state.stop_outcome = "OPERATIONAL_ERROR_RESOLVED"
        self.state.active_batch_seconds = 0.0
        self._stop_now = False
        self._current_component = None
        self._component_process_started = False
        self._lot_process_started = False
        self.store.save(self.state)
        event = self.store.append_event(
            "OPERATIONAL_REVALIDATION_PASS",
            "Operational error cleared after gates and directories passed",
            state=self.state,
            run_event_id=run_event_id,
            component="controller",
            details={
                "gate_status": gate_report.status,
                "cwd": str(cwd),
                "cwd_exists": cwd.is_dir(),
                "results_directory": str(command.results_directory),
                "results_directory_exists": command.results_directory.is_dir(),
                "command": command.argv,
                "component": component,
                "reused_components": sorted(completed_components),
                "planned_attempt_id": self.store.next_attempt_id(
                    lot.cohort, lot.simulation_run
                ),
                "partial_results_reused": False,
                "process_started": False,
            },
        )
        self.store.resolve_latest_error(
            resolution_event_id=event["event_id"],
            resolution_run_event_id=run_event_id,
            resolved_at=event["timestamp"],
        )
        self._run_event_id = None
        return {
            "gate_status": gate_report.status,
            "cwd": str(cwd),
            "cwd_exists": cwd.is_dir(),
            "results_directory": str(command.results_directory),
            "results_directory_exists": command.results_directory.is_dir(),
            "command": command.argv,
            "component": component,
            "reused_components": sorted(completed_components),
            "planned_attempt_id": self.store.next_attempt_id(
                lot.cohort, lot.simulation_run
            ),
            "partial_results_reused": False,
            "process_started": False,
        }

    def request_stop_after_current(self) -> None:
        self.store.append_event(
            "STOP_AFTER_CURRENT_REQUESTED",
            "Stop after current lot requested",
            state=self.state,
            run_event_id=self._run_event_id,
        )
        self.state.stop_request = "AFTER_CURRENT"
        self.state.global_status = "STOPPING" if self._current_attempt else "STOPPED"
        if self._current_attempt is None:
            self.state.stop_outcome = "STOPPED_CLEAN"
        self.store.save(self.state)

    def request_stop_now(self) -> None:
        self.store.append_event(
            "STOP_NOW_REQUESTED",
            "Immediate stop requested",
            state=self.state,
            run_event_id=self._run_event_id,
            component=self._current_component,
            level="WARNING",
            attempt_dir=self._current_attempt,
        )
        self._stop_now = True
        self.state.stop_request = "NOW"
        self.state.global_status = "STOPPING"
        self.store.save(self.state)
        self.controller.stop_now()

    def _run_component(self, lot: FormalLot, detector: str, ordinal: int) -> None:
        command = self._command_for(
            lot,
            detector,
            ordinal,
            diagnostic_directory=(
                self._current_attempt / "logs"
                if self._current_attempt is not None
                else None
            ),
        )
        self._current_component = detector
        self._component_process_started = False
        assert self._current_attempt is not None
        self.store.update_attempt(
            self.state,
            self._current_attempt,
            **{f"{detector}_status": "STARTING", "lot_status": "STARTING"},
        )
        self.store.append_event(
            "LLM_MODEL_LOAD_START" if detector == "llm" else "COMPONENT_START_REQUESTED",
            f"{detector.upper()} process launch requested",
            state=self.state,
            run_event_id=self._run_event_id,
            component=detector,
            log_path=str(self._current_attempt / "logs"),
            details={"argv": command.argv},
            attempt_dir=self._current_attempt,
        )
        self.controller.start(command)
        self._component_process_started = True
        self._lot_process_started = True
        self.store.update_attempt(
            self.state,
            self._current_attempt,
            status="RUNNING",
            process_started=True,
            **{f"{detector}_status": "RUNNING", "lot_status": "RUNNING"},
        )
        self.store.append_event(
            "COMPONENT_STARTED",
            f"{detector.upper()} process started",
            state=self.state,
            run_event_id=self._run_event_id,
            component=detector,
            log_path=str(self._current_attempt / "logs"),
            details={"pid": getattr(self.controller, "last_pid", None)},
            attempt_dir=self._current_attempt,
        )
        exit_code = self.controller.wait()
        self.store.append_event(
            "COMPONENT_FINISHED",
            f"{detector.upper()} process exited with {exit_code}",
            state=self.state,
            run_event_id=self._run_event_id,
            component=detector,
            level=(
                "WARNING" if self._stop_now
                else "ERROR" if exit_code != 0
                else "INFO"
            ),
            exit_code=exit_code,
            log_path=str(self._current_attempt / "logs"),
            attempt_dir=self._current_attempt,
        )
        if self._stop_now:
            raise InterruptedError("STOP_NOW")
        if exit_code != 0:
            stderr_reader = getattr(self.controller, "first_causal_stderr", None)
            causal_stderr = stderr_reader() if callable(stderr_reader) else None
            suffix = (
                f"; causal stderr: {causal_stderr}"
                if causal_stderr
                else ""
            )
            raise RuntimeError(
                f"Formal {lot.cohort} {detector} batch exited with "
                f"{exit_code}{suffix}"
            )

    def run_one(self, *, run_event_id: str | None = None) -> str | None:
        lot = self._next_lot()
        if lot is None:
            self.state.global_status = "STOPPED"
            self.state.stop_outcome = "ALL_BATCHES_COMPLETE"
            self.store.save(self.state)
            return None
        self.state.cohort = lot.cohort
        completed_components = self.store.completed_components(
            lot.cohort, lot.simulation_run
        )
        self._run_event_id = run_event_id or self.store.new_run_event_id()
        self._lot_process_started = False
        self._current_attempt = self.store.begin_attempt(
            self.state,
            lot.simulation_run,
            run_event_id=self._run_event_id,
        )
        try:
            self.state.llm_status = self._llm_status_for_lot(
                lot, completed_components
            )
            self.state.dpca_status = (
                "COMPLETE" if "dpca" in completed_components else "PENDING"
            )
            self.store.update_attempt(
                self.state,
                self._current_attempt,
                llm_status=self.state.llm_status,
                dpca_status=self.state.dpca_status,
                lot_status="STARTING",
            )
            self.store.append_event(
                "LOT_SELECTED",
                "Formal lot selected",
                state=self.state,
                run_event_id=self._run_event_id,
                details={
                    "simulation_run": lot.simulation_run,
                    "cohort": lot.cohort,
                    "llm_required": lot.llm_ordinal is not None,
                    "reused_components": sorted(completed_components),
                },
                attempt_dir=self._current_attempt,
            )
            if "dpca" not in completed_components:
                self._run_component(lot, "dpca", lot.dpca_ordinal)
                self.state.dpca_status = "COMPLETE"
                self.store.update_attempt(
                    self.state, self._current_attempt, dpca_status="COMPLETE"
                )
            else:
                self.store.append_event(
                    "COMPONENT_REUSED_IMMUTABLE",
                    "DPCA COMPLETE reused from a preserved earlier attempt",
                    state=self.state,
                    run_event_id=self._run_event_id,
                    component="dpca",
                    details={"action": "REUSED_IMMUTABLE"},
                    attempt_dir=self._current_attempt,
                )
            if lot.llm_ordinal is not None and "llm" not in completed_components:
                self.state.llm_status = "RUNNING"
                self.store.update_attempt(self.state, self._current_attempt, llm_status="RUNNING")
                self._run_component(lot, "llm", lot.llm_ordinal)
                self.state.llm_status = "COMPLETE"
                self.store.update_attempt(self.state, self._current_attempt, llm_status="COMPLETE")
            if self._stop_now:
                raise InterruptedError("STOP_NOW")
            self.store.complete_attempt(
                self.state,
                self._current_attempt,
                completion_reason="COMPONENTS_COMPLETE",
                duration_seconds=float(self.state.active_batch_seconds),
                llm_status=self.state.llm_status,
                dpca_status="COMPLETE",
            )
            self.store.append_event(
                "COMPLETE",
                "Formal lot completed durably",
                run_event_id=self._run_event_id,
                component="lot",
                details={
                    "simulation_run": lot.simulation_run,
                    "cohort": lot.cohort,
                    "completion_reason": "COMPONENTS_COMPLETE",
                },
                attempt_dir=self._current_attempt,
            )
            self._current_attempt = None
            self._current_component = None
            return "COMPONENTS_COMPLETE"
        except BaseException as exc:
            trace = traceback.format_exc()
            failed_to_start = not self._lot_process_started
            if self._stop_now:
                aborted_attempt = self._current_attempt
                if aborted_attempt is not None:
                    self.store.abort_current(
                        self.state, aborted_attempt, status="ABORTED"
                    )
                    self.store.append_event(
                        "STOP_NOW_COMPLETED",
                        "Manual interruption persisted as ABORTED",
                        state=self.state,
                        run_event_id=self._run_event_id,
                        component=self._current_component,
                        level="WARNING",
                        details={
                            "simulation_run": lot.simulation_run,
                            "attempt_id": aborted_attempt.name,
                            "status": "ABORTED",
                            "process_started": self._lot_process_started,
                        },
                        attempt_dir=aborted_attempt,
                    )
                    self._current_attempt = None
                self._current_component = None
                return "ABORTED"
            self.store.record_error(
                state=self.state,
                run_event_id=self._run_event_id,
                error_type=type(exc).__name__,
                message=str(exc),
                traceback_text=trace,
                component=self._current_component,
                exit_code=getattr(self.controller, "last_exit_code", None),
                attempt_dir=self._current_attempt,
            )
            if self._current_attempt is not None:
                status = (
                    "ABORTED" if self._stop_now
                    else "FAILED_TO_START" if failed_to_start
                    else "FAILED"
                )
                self.store.abort_current(self.state, self._current_attempt, status=status)
                self._current_attempt = None
            self.state.global_status = "ERROR"
            self.state.gate_reasons = [f"FORMAL_BATCH_FAILED: {exc}"]
            self.store.save(self.state)
            self._current_component = None
            return "FAILED"

    def run_all(
        self,
        max_runs: int = 5,
        *,
        run_event_id: str | None = None,
    ) -> MonitorState:
        started = 0
        while self._next_lot() is not None and started < int(max_runs):
            outcome = self.run_one(run_event_id=run_event_id)
            started += 1
            if outcome in {"FAILED", "ABORTED"} or self.state.stop_outcome in {"STOPPED_CLEAN", "STOPPED_FORCED"}:
                break
        if (
            started >= int(max_runs)
            and self._next_lot() is not None
            and self.state.global_status != "ERROR"
        ):
            self.state.global_status = "STOPPED"
            self.state.stop_outcome = "SESSION_LIMIT_REACHED"
            self.store.save(self.state)
        return self.state

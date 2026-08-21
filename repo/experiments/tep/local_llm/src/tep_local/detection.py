from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from math import ceil
from typing import Any


class DetectionState(str, Enum):
    SEARCHING = "SEARCHING"
    VERIFYING = "VERIFYING"
    CONFIRMED_DETECTION = "CONFIRMED_DETECTION"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    VERIFICATION_INCOMPLETE_END_OF_TRAJECTORY = "VERIFICATION_INCOMPLETE_END_OF_TRAJECTORY"
    NO_FIRST_INDICATION = "NO_FIRST_INDICATION"
    NO_CONFIRMED_DETECTION = "NO_CONFIRMED_DETECTION"
    NORMAL_TRAJECTORY_COMPLETE = "NORMAL_TRAJECTORY_COMPLETE"


@dataclass(frozen=True)
class DetectionUpdate:
    detection_state: str
    window_id: int | None
    first_indication_window: int | None
    confirmation_window: int | None
    confirmation_candidate_window: int | None
    verification_advance: int
    verification_advances_required: int
    pending_candidate_windows: tuple[int, ...]
    candidate_events: tuple[dict[str, Any], ...]
    event: str | None
    first_indication_status: str
    confirmed_detection_status: str
    should_stop: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def full_window_refresh_advances(window_samples: int, stride_samples: int) -> int:
    if window_samples <= 0 or stride_samples <= 0:
        raise ValueError("window_samples and stride_samples must be positive")
    return ceil(window_samples / stride_samples)


class FullWindowRefreshTracker:
    """Concurrent full-sample-refresh candidates over chronological windows."""

    def __init__(self, window_samples: int, stride_samples: int, *, target: bool) -> None:
        self.window_samples = int(window_samples)
        self.stride_samples = int(stride_samples)
        self.target = bool(target)
        self.advances_required = full_window_refresh_advances(
            self.window_samples, self.stride_samples
        )
        self.state = DetectionState.SEARCHING
        self.first_indication_window: int | None = None
        self.confirmation_window: int | None = None
        self.confirmation_candidate_window: int | None = None
        self.last_window_id: int | None = None
        self.pending_candidates: dict[int, int] = {}
        self.failed_candidate_windows: list[int] = []
        self.incomplete_candidate_windows: list[int] = []
        self.confirmed_candidate_windows: list[int] = []
        self._final_update: DetectionUpdate | None = None

    def _statuses(self) -> tuple[str, str]:
        first = (
            "FIRST_INDICATION"
            if self.first_indication_window is not None
            else "NO_FIRST_INDICATION"
        )
        confirmed = (
            "CONFIRMED_DETECTION"
            if self.confirmation_window is not None
            else "NO_CONFIRMED_DETECTION"
        )
        return first, confirmed

    def _update(
        self,
        window_id: int | None,
        *,
        event: str | None = None,
        events: list[dict[str, Any]] | None = None,
        verification_advance: int = 0,
        should_stop: bool = False,
    ) -> DetectionUpdate:
        first_status, confirmed_status = self._statuses()
        return DetectionUpdate(
            detection_state=self.state.value,
            window_id=window_id,
            first_indication_window=self.first_indication_window,
            confirmation_window=self.confirmation_window,
            confirmation_candidate_window=self.confirmation_candidate_window,
            verification_advance=int(verification_advance),
            verification_advances_required=self.advances_required,
            pending_candidate_windows=tuple(sorted(self.pending_candidates)),
            candidate_events=tuple(events or ()),
            event=event,
            first_indication_status=first_status,
            confirmed_detection_status=confirmed_status,
            should_stop=bool(should_stop),
        )

    def observe(
        self,
        window_id: int,
        decision: str,
        *,
        eligible: bool = True,
    ) -> DetectionUpdate:
        window_id = int(window_id)
        if self._final_update is not None:
            raise RuntimeError("No windows may be observed after trajectory finalization")
        if self.last_window_id is not None and window_id != self.last_window_id + 1:
            raise ValueError(
                "Detection windows must be observed exactly once in chronological order"
            )
        if decision not in {"NORMAL", "EVIDENCE_INSUFFICIENT", "ANOMALY"}:
            raise ValueError(f"Unsupported LLM decision: {decision}")
        if self.target and self.confirmation_window is not None:
            raise RuntimeError("No TARGET windows may be observed after confirmed detection")
        self.last_window_id = window_id

        if not eligible:
            if self.pending_candidates:
                raise RuntimeError(
                    "Ineligible boundary requires empty confirmation candidates"
                )
            self.state = DetectionState.SEARCHING
            return self._update(window_id, event="INELIGIBLE_OBSERVATION")

        events: list[dict[str, Any]] = []
        due = [
            candidate
            for candidate, verify_at in self.pending_candidates.items()
            if verify_at == window_id
        ]
        confirmed_now = False
        failed_now = False
        for candidate in sorted(due):
            del self.pending_candidates[candidate]
            if decision == "ANOMALY":
                self.confirmed_candidate_windows.append(candidate)
                events.append(
                    {
                        "event": "CONFIRMED_DETECTION",
                        "candidate_window": candidate,
                        "verification_window": window_id,
                        "refresh": "FULL_SAMPLE_REFRESH",
                    }
                )
                if self.confirmation_window is None:
                    self.confirmation_window = window_id
                    self.confirmation_candidate_window = candidate
                confirmed_now = True
            else:
                self.failed_candidate_windows.append(candidate)
                events.append(
                    {
                        "event": "VERIFICATION_FAILED",
                        "candidate_window": candidate,
                        "verification_window": window_id,
                        "decision": decision,
                    }
                )
                failed_now = True

        first_now = False
        if decision == "ANOMALY" and not (self.target and confirmed_now):
            self.pending_candidates[window_id] = (
                window_id + self.advances_required
            )
            events.append(
                {
                    "event": "CANDIDATE_STARTED",
                    "candidate_window": window_id,
                    "verification_window": window_id + self.advances_required,
                }
            )
            if self.first_indication_window is None:
                self.first_indication_window = window_id
                first_now = True

        if self.confirmation_window is not None:
            self.state = DetectionState.CONFIRMED_DETECTION
        elif self.pending_candidates:
            self.state = DetectionState.VERIFYING
        elif failed_now:
            self.state = DetectionState.VERIFICATION_FAILED
        else:
            self.state = DetectionState.SEARCHING

        if confirmed_now:
            event = "CONFIRMED_DETECTION"
        elif first_now:
            event = "FIRST_INDICATION"
        elif failed_now:
            event = "VERIFICATION_FAILED"
        elif decision == "ANOMALY":
            event = "CANDIDATE_STARTED"
        elif self.pending_candidates:
            event = "VERIFICATION_OBSERVATION"
        else:
            event = None
        if due:
            advance = self.advances_required
        elif self.pending_candidates:
            advance = max(
                window_id - candidate for candidate in self.pending_candidates
            )
        else:
            advance = 0
        return self._update(
            window_id,
            event=event,
            events=events,
            verification_advance=advance,
            should_stop=self.target and confirmed_now,
        )

    def finalize(self) -> DetectionUpdate:
        if self._final_update is not None:
            return self._final_update
        events: list[dict[str, Any]] = []
        for candidate, verification_window in sorted(
            self.pending_candidates.items()
        ):
            self.incomplete_candidate_windows.append(candidate)
            events.append(
                {
                    "event": "VERIFICATION_INCOMPLETE_END_OF_TRAJECTORY",
                    "candidate_window": candidate,
                    "verification_window": verification_window,
                }
            )
        self.pending_candidates.clear()
        if self.confirmation_window is not None:
            self.state = DetectionState.CONFIRMED_DETECTION
            event = "CONFIRMED_DETECTION"
        elif self.first_indication_window is None:
            self.state = DetectionState.NO_FIRST_INDICATION
            event = "NO_FIRST_INDICATION"
        elif events:
            self.state = (
                DetectionState.VERIFICATION_INCOMPLETE_END_OF_TRAJECTORY
            )
            event = "VERIFICATION_INCOMPLETE_END_OF_TRAJECTORY"
        else:
            self.state = DetectionState.NO_CONFIRMED_DETECTION
            event = "NO_CONFIRMED_DETECTION"
        if not self.target and self.first_indication_window is None:
            self.state = DetectionState.NORMAL_TRAJECTORY_COMPLETE
            event = "NORMAL_TRAJECTORY_COMPLETE"
        self._final_update = self._update(
            self.last_window_id,
            event=event,
            events=events,
            should_stop=(
                self.target and self.confirmation_window is not None
            ),
        )
        return self._final_update

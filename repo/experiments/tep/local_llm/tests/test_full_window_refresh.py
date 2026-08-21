import json
from pathlib import Path

from tep_local.amendments import load_methodological_amendment
from tep_local.detection import (
    DetectionState,
    FullWindowRefreshTracker,
    full_window_refresh_advances,
)


REPO = Path(__file__).resolve().parents[4]
CONFIG = REPO / "experiments" / "tep" / "local_llm" / "config"


def test_refresh_is_derived_as_ceil_w_over_s():
    assert full_window_refresh_advances(20, 5) == 4
    assert full_window_refresh_advances(20, 6) == 4


def test_candidate_confirms_at_its_own_k_plus_r():
    tracker = FullWindowRefreshTracker(20, 5, target=True)
    first = tracker.observe(10, "ANOMALY")
    assert first.event == "FIRST_INDICATION"
    for window_id in (11, 12, 13):
        assert not tracker.observe(window_id, "NORMAL").should_stop
    confirmed = tracker.observe(14, "ANOMALY")
    assert confirmed.event == "CONFIRMED_DETECTION"
    assert confirmed.confirmation_candidate_window == 10
    assert confirmed.confirmation_window == 14
    assert confirmed.should_stop


def test_failed_candidate_does_not_cancel_other_pending_candidate():
    tracker = FullWindowRefreshTracker(20, 5, target=True)
    tracker.observe(0, "ANOMALY")
    concurrent = tracker.observe(1, "ANOMALY")
    assert concurrent.pending_candidate_windows == (0, 1)
    tracker.observe(2, "NORMAL")
    tracker.observe(3, "NORMAL")
    failed = tracker.observe(4, "NORMAL")
    assert failed.event == "VERIFICATION_FAILED"
    assert failed.pending_candidate_windows == (1,)
    confirmed = tracker.observe(5, "ANOMALY")
    assert confirmed.event == "CONFIRMED_DETECTION"
    assert confirmed.confirmation_candidate_window == 1


def test_every_eligible_anomaly_starts_concurrent_candidate():
    tracker = FullWindowRefreshTracker(20, 5, target=False)
    for window_id in range(4):
        update = tracker.observe(window_id, "ANOMALY")
    assert update.pending_candidate_windows == (0, 1, 2, 3)
    assert not update.should_stop


def test_incomplete_candidates_are_recorded_individually():
    tracker = FullWindowRefreshTracker(20, 5, target=True)
    tracker.observe(0, "NORMAL")
    tracker.observe(1, "ANOMALY")
    tracker.observe(2, "ANOMALY")
    final = tracker.finalize()
    assert final.detection_state == (
        "VERIFICATION_INCOMPLETE_END_OF_TRAJECTORY"
    )
    assert tracker.incomplete_candidate_windows == [1, 2]
    assert final.confirmed_detection_status == "NO_CONFIRMED_DETECTION"


def test_no_anomaly_records_both_negative_statuses():
    tracker = FullWindowRefreshTracker(20, 5, target=True)
    for window_id in range(8):
        tracker.observe(window_id, "NORMAL")
    final = tracker.finalize()
    assert final.detection_state == DetectionState.NO_FIRST_INDICATION
    assert final.first_indication_status == "NO_FIRST_INDICATION"
    assert final.confirmed_detection_status == "NO_CONFIRMED_DETECTION"


def test_pre_onset_ineligible_anomaly_cannot_start_candidate():
    tracker = FullWindowRefreshTracker(20, 5, target=True)
    tracker.observe(0, "ANOMALY", eligible=False)
    tracker.observe(1, "ANOMALY", eligible=False)
    tracker.observe(2, "NORMAL", eligible=True)
    tracker.observe(3, "NORMAL", eligible=True)
    tracker.observe(4, "NORMAL", eligible=True)
    crossed = tracker.observe(5, "ANOMALY", eligible=True)
    assert crossed.event == "FIRST_INDICATION"
    assert crossed.first_indication_window == 5
    assert crossed.confirmation_window is None


def test_normal_tracks_confirmation_but_never_early_stops():
    tracker = FullWindowRefreshTracker(20, 5, target=False)
    decisions = {
        0: "ANOMALY",
        1: "ANOMALY",
        4: "ANOMALY",
        5: "ANOMALY",
    }
    for window_id in range(10):
        update = tracker.observe(
            window_id, decisions.get(window_id, "NORMAL")
        )
        assert not update.should_stop
    assert tracker.confirmed_candidate_windows == [0, 1]


def test_methodological_amendment_matches_refrozen_formal():
    formal_path = CONFIG / "formal.json"
    formal = json.loads(formal_path.read_text(encoding="utf-8"))
    amendment = load_methodological_amendment(
        CONFIG / "post_freeze_methodological_amendment_002.json",
        formal_path,
        formal,
    )
    assert amendment["scientific_parameters_changed"] is True
    assert amendment["new_rule"]["derived_refresh_strides"] == 4
    assert amendment["new_rule"]["candidate_concurrency"] is True

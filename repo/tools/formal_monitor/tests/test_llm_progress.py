from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from tools.formal_monitor.llm_progress import (
    LLMProgressReader,
    THEORETICAL_MAX_WINDOWS,
)


RESULTS_ID = "TEST-FORMAL-RESULTS"


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def configured_reader(tmp_path, simulation_run=14):
    repo = tmp_path / "repo"
    workspace = tmp_path / "workspace"
    config = repo / "experiments" / "tep" / "local_llm" / "config"
    write_json(config / "formal_run_selection.json", {
        "seed": 42,
        "selected_simulation_runs": [simulation_run],
    })
    write_json(config / "formal_normal_holdout_selection.json", {
        "seed": 43,
        "selected_simulation_runs": [10],
    })
    reader = LLMProgressReader(repo, workspace, RESULTS_ID)
    blind_id = reader._blind_id(simulation_run, 42)
    attempt = (
        workspace
        / "results"
        / "formal"
        / RESULTS_ID
        / "target"
        / "llm"
        / "runs"
        / blind_id
        / "attempts"
        / "0001"
    )
    write_json(attempt / "status.json", {
        "status": "PARTIAL",
        "blind_run_id": blind_id,
        "attempt": 1,
    })
    return reader, attempt


def record(
    window_id: int,
    *,
    decision: str = "NORMAL",
    first_indication_window=None,
    confirmation_window=None,
    should_stop: bool = False,
):
    confirmed = confirmation_window is not None
    return {
        "window_id": window_id,
        "decision": decision,
        "latency_ms": 1000 + window_id,
        "detection": {
            "window_id": window_id,
            "detection_state": (
                "CONFIRMED_DETECTION" if confirmed else
                "FIRST_INDICATION" if first_indication_window is not None else
                "SEARCHING"
            ),
            "first_indication_window": first_indication_window,
            "confirmation_window": confirmation_window,
            "confirmed_detection_status": (
                "CONFIRMED_DETECTION" if confirmed else
                "NO_CONFIRMED_DETECTION"
            ),
            "verification_advance": 0,
            "verification_advances_required": 4,
            "should_stop": should_stop,
        },
    }


def write_records(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(item) + "\n" for item in records),
        encoding="utf-8",
    )


def test_zero_persisted_windows_reports_zero_of_189(tmp_path):
    reader, _ = configured_reader(tmp_path)

    progress = reader.read("target", 14)

    assert progress.completed_windows == 0
    assert progress.current_window == 0
    assert progress.max_windows == THEORETICAL_MAX_WINDOWS == 189
    assert progress.response_fields()["progress_batch_percent"] == 0


def test_one_persisted_window_reports_one_of_189(tmp_path):
    reader, attempt = configured_reader(tmp_path)
    write_records(attempt / "llm_decisions.jsonl", [record(0)])

    progress = reader.read("target", 14)

    assert progress.completed_windows == 1
    assert progress.current_window == 1
    assert progress.max_windows == 189
    assert progress.last_llm_decision == "NORMAL"
    assert progress.source == "llm_decisions.jsonl"
    assert progress.response_fields()["progress_batch_percent"] == 0.53


def test_sixty_one_persisted_windows_reports_sixty_one_of_189(tmp_path):
    reader, attempt = configured_reader(tmp_path)
    write_records(
        attempt / "llm_decisions.jsonl",
        [record(window_id) for window_id in range(61)],
    )

    progress = reader.read("target", 14)

    assert progress.completed_windows == 61
    assert progress.current_window == 61
    assert progress.max_windows == 189
    assert progress.last_llm_decision == "NORMAL"
    assert progress.response_fields()["progress_batch_percent"] == 32.28


def test_early_stop_at_sixty_one_is_terminally_coherent(tmp_path):
    reader, attempt = configured_reader(tmp_path)
    records = [record(window_id) for window_id in range(60)]
    records.append(record(
        60,
        decision="ANOMALY",
        first_indication_window=55,
        confirmation_window=60,
        should_stop=True,
    ))
    write_records(attempt / "llm_decisions.jsonl", records)

    progress = reader.read("target", 14)

    assert progress.completed_windows == 61
    assert progress.current_window == 61
    assert progress.last_llm_decision == "ANOMALY"
    assert progress.first_indication_window == 55
    assert progress.confirmation_window == 60
    assert progress.confirmed_detection is True
    assert progress.detection_state == "CONFIRMED_DETECTION"
    assert progress.early_stop is True
    assert progress.eta_seconds == 0


def test_concurrent_read_ignores_partial_tail_and_never_blocks_writer(tmp_path):
    reader, attempt = configured_reader(tmp_path)
    decisions = attempt / "llm_decisions.jsonl"
    decisions.touch()
    original_status = (attempt / "status.json").read_bytes()
    writer_done = threading.Event()
    failures = []

    def writer():
        try:
            with decisions.open("ab", buffering=0) as handle:
                for window_id in range(61):
                    encoded = (json.dumps(record(window_id)) + "\n").encode()
                    split = len(encoded) // 2
                    handle.write(encoded[:split])
                    time.sleep(0.0005)
                    handle.write(encoded[split:])
        except BaseException as exc:
            failures.append(exc)
        finally:
            writer_done.set()

    thread = threading.Thread(target=writer)
    thread.start()
    observed = []
    deadline = time.monotonic() + 10
    while not writer_done.is_set() and time.monotonic() < deadline:
        observed.append(reader.read("target", 14).completed_windows)
    thread.join(timeout=2)

    assert writer_done.is_set()
    assert failures == []
    assert observed == sorted(observed)
    assert all(0 <= value <= 61 for value in observed)
    assert reader.read("target", 14).completed_windows == 61
    assert (attempt / "status.json").read_bytes() == original_status


def test_ui_renders_explicit_live_progress_fields():
    repo = Path(__file__).resolve().parents[3]
    html = (repo / "tools" / "formal_monitor" / "templates" / "index.html").read_text(
        encoding="utf-8"
    )
    javascript = (repo / "tools" / "formal_monitor" / "static" / "app.js").read_text(
        encoding="utf-8"
    )

    assert 'id="completed-windows"' in html
    assert 'id="early-stop"' in html
    assert "s.completed_windows ?? s.window_completed" in javascript
    assert "s.current_window ?? s.window_completed" in javascript
    assert "s.max_windows ?? s.window_total_max" in javascript

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

import pytest

from tools.formal_monitor import state as state_module
from tools.formal_monitor.monitor import MonitorApplication, MonitorHandler
from tools.formal_monitor.state import MonitorState, StateStore, atomic_json


REPO = Path(__file__).resolve().parents[3]
WORKSPACE = REPO.parent


def test_concurrent_api_state_reads_never_persist(tmp_path, monkeypatch):
    app = MonitorApplication(
        REPO, WORKSPACE, tmp_path / "MOCK_read_only_api", mock=True
    )
    before = app.store.state_path.read_bytes()
    writes = 0

    def forbidden_save(*args, **kwargs):
        nonlocal writes
        writes += 1
        raise AssertionError("GET /api/state must not persist monitor state")

    monkeypatch.setattr(app.store, "save", forbidden_save)

    class ReadOnlyHandler(MonitorHandler):
        pass

    ReadOnlyHandler.app = app
    server = ThreadingHTTPServer(("127.0.0.1", 0), ReadOnlyHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    url = f"http://127.0.0.1:{server.server_port}/api/state"
    try:
        with ThreadPoolExecutor(max_workers=12) as executor:
            payloads = list(
                executor.map(
                    lambda _: json.loads(urlopen(url, timeout=10).read()),
                    range(48),
                )
            )
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=10)

    assert len(payloads) == 48
    assert all(payload["mock_start_enabled"] is True for payload in payloads)
    assert writes == 0
    assert app.store.state_path.read_bytes() == before


def test_store_writers_are_serialized_by_one_reentrant_lock(
    tmp_path, monkeypatch
):
    store = StateStore(tmp_path / "real-controller", mock=False)
    store.save(MonitorState())
    real_atomic_json = state_module.atomic_json
    guard = threading.Lock()
    active = 0
    maximum_active = 0

    def observed_atomic_json(path, value):
        nonlocal active, maximum_active
        if Path(path) == store.state_path:
            with guard:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.005)
            try:
                real_atomic_json(path, value)
            finally:
                with guard:
                    active -= 1
        else:
            real_atomic_json(path, value)

    monkeypatch.setattr(state_module, "atomic_json", observed_atomic_json)
    barrier = threading.Barrier(16)

    def writer(index):
        barrier.wait()
        store.save(MonitorState(completed_batches=index))

    with ThreadPoolExecutor(max_workers=16) as executor:
        list(executor.map(writer, range(16)))

    assert maximum_active == 1
    assert json.loads(store.state_path.read_text(encoding="utf-8"))[
        "completed_batches"
    ] in range(16)


def test_atomic_json_uses_unique_same_directory_temporaries(
    tmp_path, monkeypatch
):
    destination = tmp_path / "monitor_state.json"
    real_replace = state_module.os.replace
    sources = []
    source_guard = threading.Lock()
    replace_guard = threading.Lock()

    def recording_replace(source, target):
        with source_guard:
            sources.append(Path(source))
        with replace_guard:
            real_replace(source, target)

    monkeypatch.setattr(state_module.os, "replace", recording_replace)
    with ThreadPoolExecutor(max_workers=16) as executor:
        list(
            executor.map(
                lambda index: atomic_json(destination, {"writer": index}),
                range(64),
            )
        )

    assert len(sources) == 64
    assert len(set(sources)) == 64
    assert all(path.parent == destination.parent for path in sources)
    assert all(path.name.startswith(".monitor_state.json.") for path in sources)
    assert all(path.name.endswith(".tmp") for path in sources)
    assert destination.with_name(destination.name + ".tmp") not in sources
    assert json.loads(destination.read_text(encoding="utf-8"))[
        "writer"
    ] in range(64)


def test_replace_keeps_monitor_state_valid_during_writer_stress(tmp_path):
    store = StateStore(tmp_path / "real-controller", mock=False)
    store.save(MonitorState(completed_batches=0))
    stop = threading.Event()
    corruptions = []

    def reader():
        while not stop.is_set():
            try:
                value = store.read()
                if not isinstance(value.completed_batches, int):
                    corruptions.append(value.completed_batches)
            except (OSError, ValueError) as exc:
                corruptions.append(exc)

    readers = [threading.Thread(target=reader) for _ in range(8)]
    for thread in readers:
        thread.start()
    try:
        for index in range(200):
            store.save(MonitorState(completed_batches=index))
    finally:
        stop.set()
        for thread in readers:
            thread.join(timeout=10)

    assert corruptions == []
    assert json.loads(store.state_path.read_text(encoding="utf-8"))[
        "completed_batches"
    ] == 199


def test_failed_writer_removes_only_its_own_temporary(tmp_path, monkeypatch):
    destination = tmp_path / "monitor_state.json"
    foreign = tmp_path / ".monitor_state.json.foreign.tmp"
    foreign.write_text("foreign writer", encoding="utf-8")

    def failing_replace(source, target):
        raise PermissionError("simulated replace failure")

    monkeypatch.setattr(state_module.os, "replace", failing_replace)
    with pytest.raises(PermissionError, match="simulated"):
        atomic_json(destination, {"writer": "failing"})

    assert foreign.read_text(encoding="utf-8") == "foreign writer"
    assert list(tmp_path.glob(".monitor_state.json.*.tmp")) == [foreign]


def test_failed_to_start_remains_recoverable_without_process_start(tmp_path):
    store = StateStore(tmp_path / "real-controller", mock=False)
    state = store.load()
    attempt = store.begin_attempt(state, 150, run_event_id="run-event-150")
    store.abort_current(state, attempt, status="FAILED_TO_START")

    status = json.loads((attempt / "status.json").read_text(encoding="utf-8"))
    assert status["status"] == "FAILED_TO_START"
    assert status["process_started"] is False
    assert not (attempt.parent / "COMPLETE.json").exists()
    assert store.next_pending("target", [150, 151]) == 150

"""Living state owners and atomic heartbeat writes fence competing pools."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from pinterest_automation import runtime_state

pytestmark = pytest.mark.unit


@pytest.fixture
def files(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_state, "RUNTIME_DIR", tmp_path)
    for constant, leaf in (
        ("SUPERVISOR_LOCK_FILE", "supervisor.lock"),
        ("SUPERVISOR_STATE_FILE", "supervisor.json"),
        ("SUPERVISOR_STOP_FILE", "supervisor.stop"),
    ):
        monkeypatch.setattr(runtime_state, constant, tmp_path / leaf)
    return tmp_path


def _write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def _foreign(pid=999999):
    return {
        "pid": pid,
        "started_at": 1234.5,
        "lease_id": "another-owner",
        "heartbeat_at": time.time(),
        "worker_count": 2,
    }


def test_fresh_state_blocks_acquisition_even_when_lock_file_is_missing(files, monkeypatch):
    state = _foreign()
    _write(runtime_state.SUPERVISOR_STATE_FILE, state)
    monkeypatch.setattr(runtime_state, "_process_alive", lambda pid: True)
    monkeypatch.setattr(runtime_state, "_process_matches_lease", lambda pid, started: True)

    with pytest.raises(RuntimeError, match="already running with PID 999999"):
        runtime_state.SupervisorLease(3).acquire()

    assert json.loads(runtime_state.SUPERVISOR_STATE_FILE.read_text()) == state
    assert not runtime_state.SUPERVISOR_LOCK_FILE.exists()


def test_living_state_blocks_despite_stale_dead_lock(files, monkeypatch):
    _write(runtime_state.SUPERVISOR_LOCK_FILE, _foreign(111111))
    _write(runtime_state.SUPERVISOR_STATE_FILE, _foreign(222222))
    monkeypatch.setattr(runtime_state, "_process_alive", lambda pid: pid == 222222)
    monkeypatch.setattr(runtime_state, "_process_matches_lease", lambda pid, started: True)

    with pytest.raises(RuntimeError, match="already running with PID 222222"):
        runtime_state.SupervisorLease(3).acquire()

    assert json.loads(runtime_state.SUPERVISOR_STATE_FILE.read_text())["pid"] == 222222


@pytest.mark.parametrize("leaf", ["supervisor.lock", "supervisor.json"])
def test_unreadable_owner_record_fails_closed_without_truncation(files, monkeypatch, leaf):
    path = files / leaf
    _write(path, _foreign())
    original = path.read_bytes()
    read = Path.read_text

    def unavailable(target, *args, **kwargs):
        if target == path:
            raise PermissionError("simulated sharing violation")
        return read(target, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unavailable)

    with pytest.raises(RuntimeError, match="Cannot verify"):
        runtime_state.SupervisorLease(3).acquire()

    assert path.read_bytes() == original


def test_malformed_state_is_not_treated_as_an_absent_owner(files):
    runtime_state.SUPERVISOR_STATE_FILE.write_text("{", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Cannot verify"):
        runtime_state.SupervisorLease(3).acquire()

    assert runtime_state.SUPERVISOR_STATE_FILE.read_text() == "{"
    assert not runtime_state.SUPERVISOR_LOCK_FILE.exists()


def test_same_pid_second_lease_cannot_replace_first_instance(files):
    first, second = runtime_state.SupervisorLease(3), runtime_state.SupervisorLease(2)
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match=f"already running with PID {os.getpid()}"):
            second.acquire()
        assert first.lease_id != second.lease_id
        assert json.loads(runtime_state.SUPERVISOR_STATE_FILE.read_text())["lease_id"] == first.lease_id
    finally:
        first.release()


@pytest.mark.parametrize("missing", ["SUPERVISOR_LOCK_FILE", "SUPERVISOR_STATE_FILE"])
def test_exact_owner_heartbeat_repairs_one_missing_record(files, missing):
    lease = runtime_state.SupervisorLease(3)
    lease.acquire()
    try:
        getattr(runtime_state, missing).unlink()
        lease.heartbeat()
        for path in (runtime_state.SUPERVISOR_LOCK_FILE, runtime_state.SUPERVISOR_STATE_FILE):
            assert json.loads(path.read_text())["lease_id"] == lease.lease_id
    finally:
        lease.release()


def test_displaced_heartbeat_refuses_overwrite_and_release_preserves_foreign_files(files):
    lease = runtime_state.SupervisorLease(3)
    lease.acquire()
    other = _foreign()
    for path in (runtime_state.SUPERVISOR_LOCK_FILE, runtime_state.SUPERVISOR_STATE_FILE):
        _write(path, other)
    _write(runtime_state.SUPERVISOR_STOP_FILE, {"pid": other["pid"]})
    before = {
        p: p.read_bytes()
        for p in (
            runtime_state.SUPERVISOR_LOCK_FILE,
            runtime_state.SUPERVISOR_STATE_FILE,
            runtime_state.SUPERVISOR_STOP_FILE,
        )
    }

    with pytest.raises(runtime_state.SupervisorOwnershipLostError):
        lease.heartbeat()
    lease.release()

    assert lease._owned is False
    assert {p: p.read_bytes() for p in before} == before


def test_both_records_missing_revokes_ownership_instead_of_reacquiring(files):
    lease = runtime_state.SupervisorLease(3)
    lease.acquire()
    runtime_state.SUPERVISOR_LOCK_FILE.unlink()
    runtime_state.SUPERVISOR_STATE_FILE.unlink()

    with pytest.raises(runtime_state.SupervisorOwnershipLostError):
        lease.heartbeat()

    assert not runtime_state.SUPERVISOR_LOCK_FILE.exists()
    assert not runtime_state.SUPERVISOR_STATE_FILE.exists()


def test_release_does_not_delete_foreign_records_when_read_is_denied(files, monkeypatch):
    lease = runtime_state.SupervisorLease(3)
    lease.acquire()
    original = runtime_state.SUPERVISOR_LOCK_FILE.read_bytes()
    read = Path.read_text

    def denied(path, *args, **kwargs):
        if path == runtime_state.SUPERVISOR_STATE_FILE:
            raise PermissionError("uninspectable state")
        return read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied)
    lease.release()

    assert runtime_state.SUPERVISOR_LOCK_FILE.read_bytes() == original
    assert runtime_state.SUPERVISOR_STATE_FILE.exists()


def test_unique_atomic_temps_preserve_each_target_and_legacy_temp(files, monkeypatch):
    legacy = files / "supervisor.tmp"
    legacy.write_text("another writer's temporary", encoding="utf-8")
    seen = []
    replace = Path.replace

    def observed(path, target):
        seen.append((path.name, target.name))
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", observed)
    lease = runtime_state.SupervisorLease(3)
    lease.acquire()
    try:
        lease.heartbeat()
        assert len({name for name, target in seen}) == len(seen)
        assert any(name.startswith(".supervisor.lock.") for name, target in seen)
        assert any(name.startswith(".supervisor.json.") for name, target in seen)
        assert legacy.read_text() == "another writer's temporary"
    finally:
        lease.release()


def test_failed_atomic_replacement_keeps_last_valid_json_and_never_direct_writes(files, monkeypatch):
    lease = runtime_state.SupervisorLease(3)
    lease.acquire()
    before = runtime_state.SUPERVISOR_STATE_FILE.read_bytes()
    replace = Path.replace

    def denied(path, target):
        if target == runtime_state.SUPERVISOR_STATE_FILE:
            raise PermissionError("simulated Windows reader")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", denied)
    monkeypatch.setattr(runtime_state.time, "sleep", lambda delay: None)
    with pytest.raises(PermissionError):
        lease.heartbeat()

    assert runtime_state.SUPERVISOR_STATE_FILE.read_bytes() == before
    assert not list(files.glob(".supervisor.*.tmp"))
    assert lease._owned is True
    lease.release()


def test_parallel_heartbeats_are_serialized_and_preserve_valid_state(files):
    lease = runtime_state.SupervisorLease(3)
    lease.acquire()
    failures = []

    def beat():
        try:
            for _ in range(5):
                lease.heartbeat()
        except Exception as error:
            failures.append(error)

    threads = [threading.Thread(target=beat) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert not failures
    assert not any(thread.is_alive() for thread in threads)
    assert json.loads(runtime_state.SUPERVISOR_STATE_FILE.read_text())["lease_id"] == lease.lease_id
    assert not list(files.glob(".supervisor.*.tmp"))
    lease.release()


def test_targeted_legacy_stop_uses_verified_process_fingerprint(files, monkeypatch):
    _write(runtime_state.SUPERVISOR_STATE_FILE, _foreign(111111))
    original = runtime_state.SUPERVISOR_STATE_FILE.read_bytes()
    monkeypatch.setattr(
        psutil,
        "Process",
        lambda pid: SimpleNamespace(
            create_time=lambda: 1234.25,
            cmdline=lambda: ["python.exe", r"C:\Rankstein\run_autonomous.py", "run", "--workers", "2"],
        ),
    )

    result = runtime_state.request_supervisor_stop(target_pid=222222, expected_start=1234.25)

    request = json.loads(runtime_state.SUPERVISOR_STOP_FILE.read_text())
    assert result["success"] is True
    assert request["pid"] == 222222
    assert request["expected_start"] == 1234.25
    assert runtime_state.SUPERVISOR_STATE_FILE.read_bytes() == original
    legacy_lease = runtime_state.SupervisorLease(2)
    legacy_lease.pid = 222222
    assert legacy_lease.stop_requested() is True


@pytest.mark.parametrize(
    "created,command",
    [
        (1236.25, ["python.exe", "run_autonomous.py", "run"]),
        (1234.25, ["python.exe", "unrelated.py", "run"]),
        (1234.25, ["python.exe", "run_autonomous.py", "stop"]),
    ],
)
def test_targeted_stop_rejects_reused_or_wrong_process_without_overwriting_request(
    files, monkeypatch, created, command
):
    _write(runtime_state.SUPERVISOR_STOP_FILE, {"pid": 111111})
    original = runtime_state.SUPERVISOR_STOP_FILE.read_bytes()
    monkeypatch.setattr(
        psutil, "Process", lambda pid: SimpleNamespace(create_time=lambda: created, cmdline=lambda: command)
    )

    with pytest.raises(ValueError, match="no longer matches"):
        runtime_state.request_supervisor_stop(target_pid=222222, expected_start=1234.25)

    assert runtime_state.SUPERVISOR_STOP_FILE.read_bytes() == original


def test_targeted_stop_fails_closed_when_process_access_is_denied(files, monkeypatch):
    def denied(pid):
        raise psutil.AccessDenied(pid)

    monkeypatch.setattr(psutil, "Process", denied)
    with pytest.raises(psutil.AccessDenied):
        runtime_state.request_supervisor_stop(target_pid=222222, expected_start=1234.25)
    assert not runtime_state.SUPERVISOR_STOP_FILE.exists()


def test_targeted_stop_fingerprint_prevents_reused_pid_consuming_old_request(files, monkeypatch):
    _write(runtime_state.SUPERVISOR_STOP_FILE, {"pid": os.getpid(), "expected_start": 1234.25})
    monkeypatch.setattr(psutil, "Process", lambda pid: SimpleNamespace(create_time=lambda: 2234.25))
    assert runtime_state.SupervisorLease(3).stop_requested() is False


def test_default_stop_api_remains_compatible_with_current_owner(files):
    lease = runtime_state.SupervisorLease(3)
    lease.acquire()
    try:
        result = runtime_state.request_supervisor_stop()
        assert result["success"] is True
        assert result["pid"] == lease.pid
        assert lease.stop_requested() is True
    finally:
        lease.release()

"""A frozen owner must never be replaced by a second account session pool."""

import json
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import psutil
import pytest

from pinterest_automation import runtime_state


@pytest.fixture
def isolated_lease_files(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_state, "RUNTIME_DIR", tmp_path)
    for name, leaf in (
        ("SUPERVISOR_LOCK_FILE", "supervisor.lock"),
        ("SUPERVISOR_STATE_FILE", "supervisor.json"),
        ("SUPERVISOR_STOP_FILE", "supervisor.stop"),
    ):
        monkeypatch.setattr(runtime_state, name, tmp_path / leaf)
    return tmp_path


@pytest.mark.unit
def test_stale_heartbeat_keeps_living_original_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_state, "RUNTIME_DIR", tmp_path)
    for name, leaf in (
        ("SUPERVISOR_LOCK_FILE", "supervisor.lock"),
        ("SUPERVISOR_STATE_FILE", "supervisor.json"),
        ("SUPERVISOR_STOP_FILE", "supervisor.stop"),
    ):
        monkeypatch.setattr(runtime_state, name, tmp_path / leaf)
    old_start = time.time() - 500
    lock = {"pid": 999999, "started_at": old_start}
    runtime_state.SUPERVISOR_LOCK_FILE.write_text(json.dumps(lock), encoding="utf-8")
    runtime_state.SUPERVISOR_STATE_FILE.write_text(
        json.dumps({"pid": 999999, "heartbeat_at": old_start, "worker_count": 3}), encoding="utf-8"
    )
    monkeypatch.setattr(runtime_state, "_process_alive", lambda pid: True)
    monkeypatch.setattr(psutil, "Process", lambda pid: SimpleNamespace(create_time=lambda: old_start - 1))

    with pytest.raises(RuntimeError, match="already running with PID 999999"):
        runtime_state.SupervisorLease(3).acquire()

    assert json.loads(runtime_state.SUPERVISOR_LOCK_FILE.read_text(encoding="utf-8")) == lock


@pytest.mark.unit
def test_reused_pid_does_not_claim_old_supervisor_lease(monkeypatch):
    monkeypatch.setattr(psutil, "Process", lambda pid: SimpleNamespace(create_time=lambda: 2000))
    assert runtime_state._process_matches_lease(999999, 1000) is False


@pytest.mark.unit
def test_owner_identity_fails_closed_when_process_cannot_be_inspected(monkeypatch):
    def inaccessible(pid):
        raise psutil.AccessDenied(pid)

    monkeypatch.setattr(psutil, "Process", inaccessible)
    assert runtime_state._process_matches_lease(999999, 1000) is True


@pytest.mark.unit
@pytest.mark.parametrize("error_code,expected_alive", [(5, True), (87, False)])
def test_windows_owner_liveness_distinguishes_access_denied_from_missing_pid(
    monkeypatch, error_code, expected_alive
):
    import ctypes

    kernel = SimpleNamespace(OpenProcess=Mock(return_value=None), CloseHandle=Mock())
    monkeypatch.setattr(ctypes, "WinDLL", Mock(return_value=kernel), raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: error_code, raising=False)
    monkeypatch.setattr(runtime_state, "os", SimpleNamespace(name="nt"))
    assert runtime_state._process_alive(999999) is expected_alive
    kernel.CloseHandle.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize("error,expected_alive", [(PermissionError(), True), (ProcessLookupError(), False)])
def test_posix_owner_liveness_distinguishes_permission_denied_from_missing_pid(
    monkeypatch, error, expected_alive
):
    kill = Mock(side_effect=error)
    monkeypatch.setattr(runtime_state, "os", SimpleNamespace(name="posix", kill=kill))
    assert runtime_state._process_alive(999999) is expected_alive
    kill.assert_called_once_with(999999, 0)


@pytest.mark.unit
def test_concurrent_start_cannot_remove_newly_acquired_lease(isolated_lease_files, monkeypatch):
    first = runtime_state.SupervisorLease(3)
    second = runtime_state.SupervisorLease(3)
    first.pid, second.pid = 1001, 1002
    first_read = threading.Event()
    finish_first = threading.Event()
    second_attempting = threading.Event()
    second_read = threading.Event()
    results = {}
    original_read = runtime_state._read_lease_json

    def observed_read(path):
        if path == runtime_state.SUPERVISOR_LOCK_FILE:
            if threading.current_thread().name == "first":
                first_read.set()
                assert finish_first.wait(5), "first acquisition was never released by test"
            elif threading.current_thread().name == "second":
                second_read.set()
        return original_read(path)

    def acquire(name, lease):
        if name == "second":
            second_attempting.set()
        try:
            lease.acquire()
            results[name] = "acquired"
        except RuntimeError as exc:
            results[name] = str(exc)

    monkeypatch.setattr(runtime_state, "_read_lease_json", observed_read)
    monkeypatch.setattr(runtime_state, "_process_alive", lambda pid: True)
    monkeypatch.setattr(runtime_state, "_process_matches_lease", lambda pid, started: True)
    workers = [
        threading.Thread(target=acquire, args=("first", first), name="first"),
        threading.Thread(target=acquire, args=("second", second), name="second"),
    ]
    workers[0].start()
    try:
        assert first_read.wait(5)
        workers[1].start()
        assert second_attempting.wait(5)
        # The second contender cannot even read the lease until the first has
        # completed its read/remove/exclusive-create critical section.
        assert not second_read.wait(0.2)
    finally:
        finish_first.set()
        for worker in workers:
            if worker.ident is not None:
                worker.join(5)
    assert not any(worker.is_alive() for worker in workers)
    assert results["first"] == "acquired"
    assert "already running with PID 1001" in results["second"]
    assert first._owned is True
    assert second._owned is False
    assert original_read(runtime_state.SUPERVISOR_LOCK_FILE)["pid"] == 1001
    first.release()
    assert (isolated_lease_files / "supervisor.lock.guard").exists()


@pytest.mark.unit
def test_acquisition_guard_is_released_when_holder_process_dies(isolated_lease_files):
    script = """
import importlib.util
import sys
import time
import types
from pathlib import Path

root = Path(sys.argv[1])
# This test measures the OS lease lock, not browser-package cold startup.
# Load the real runtime module with only its DATA_DIR dependency stubbed.
package = types.ModuleType('pinterest_automation')
package.__path__ = []
config = types.ModuleType('pinterest_automation.config')
config.DATA_DIR = root
sys.modules['pinterest_automation'] = package
sys.modules['pinterest_automation.config'] = config
spec = importlib.util.spec_from_file_location('pinterest_automation.runtime_state', sys.argv[2])
runtime_state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime_state)
runtime_state.SUPERVISOR_LOCK_FILE = root / 'supervisor.lock'
with runtime_state._lease_state_guard():
    (root / 'guard-held').write_text('ready', encoding='utf-8')
    while True:
        time.sleep(1)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(isolated_lease_files), runtime_state.__file__],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not (isolated_lease_files / "guard-held").exists():
            if process.poll() is not None:
                pytest.fail(f"guard holder failed: {process.stderr.read()}")
            if time.monotonic() >= deadline:
                pytest.fail("guard holder did not acquire the isolated lock")
            time.sleep(0.02)
        process.kill()
        process.wait(timeout=5)
        with runtime_state._lease_state_guard():
            assert (isolated_lease_files / "supervisor.lock.guard").exists()
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        process.stderr.close()

"""Cross-process state for the Pinterest supervisor."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .config import DATA_DIR

RUNTIME_DIR = DATA_DIR / "runtime"
SUPERVISOR_LOCK_FILE = RUNTIME_DIR / "supervisor.lock"
SUPERVISOR_STATE_FILE = RUNTIME_DIR / "supervisor.json"
SUPERVISOR_STOP_FILE = RUNTIME_DIR / "supervisor.stop"


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_uint32,
        ]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except (OSError, SystemError):
        return False
    return True


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def supervisor_status(max_age_seconds: float = 120.0) -> dict:
    state = _read_json(SUPERVISOR_STATE_FILE)
    lock = _read_json(SUPERVISOR_LOCK_FILE)
    pid = int(state.get("pid") or lock.get("pid") or 0)
    heartbeat_at = float(state.get("heartbeat_at") or 0)
    heartbeat_age = max(0.0, time.time() - heartbeat_at) if heartbeat_at else None
    running = _process_alive(pid) and heartbeat_age is not None and heartbeat_age <= max_age_seconds
    return {
        "running": running,
        "pid": pid or None,
        "heartbeat_age_seconds": round(heartbeat_age, 1) if heartbeat_age is not None else None,
        "started_at": state.get("started_at"),
        "worker_count": state.get("worker_count"),
    }


def request_supervisor_stop() -> dict:
    status = supervisor_status()
    if not status["running"]:
        return {"success": False, "error": "Supervisor not running", **status}
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"pid": status["pid"], "requested_at": time.time()}
    SUPERVISOR_STOP_FILE.write_text(json.dumps(payload), encoding="utf-8")
    return {"success": True, "message": "Supervisor shutdown requested", **status}


class SupervisorLease:
    """Exclusive process lease with a machine-readable heartbeat."""

    def __init__(self, worker_count: int):
        self.pid = os.getpid()
        self.worker_count = worker_count
        self.started_at = time.time()
        self._owned = False

    def acquire(self) -> None:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        existing = _read_json(SUPERVISOR_LOCK_FILE)
        existing_pid = int(existing.get("pid") or 0)
        if existing_pid and _process_alive(existing_pid):
            raise RuntimeError(f"Pinterest supervisor already running with PID {existing_pid}")

        for stale in (SUPERVISOR_LOCK_FILE, SUPERVISOR_STATE_FILE, SUPERVISOR_STOP_FILE):
            try:
                stale.unlink()
            except FileNotFoundError:
                pass

        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        descriptor = os.open(SUPERVISOR_LOCK_FILE, flags)
        try:
            os.write(
                descriptor,
                json.dumps({"pid": self.pid, "started_at": self.started_at}).encode("utf-8"),
            )
        finally:
            os.close(descriptor)
        self._owned = True
        self.heartbeat()

    def heartbeat(self) -> None:
        if not self._owned:
            return
        payload = {
            "pid": self.pid,
            "started_at": self.started_at,
            "heartbeat_at": time.time(),
            "worker_count": self.worker_count,
        }
        temporary = SUPERVISOR_STATE_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        try:
            temporary.replace(SUPERVISOR_STATE_FILE)
        except OSError:
            # Windows readers can briefly block an atomic replace. A direct
            # write keeps the lease observable and the next heartbeat retries
            # the atomic path.
            SUPERVISOR_STATE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def stop_requested(self) -> bool:
        request = _read_json(SUPERVISOR_STOP_FILE)
        return bool(request and int(request.get("pid") or 0) == self.pid)

    def release(self) -> None:
        if not self._owned:
            return
        for path in (SUPERVISOR_STOP_FILE, SUPERVISOR_STATE_FILE, SUPERVISOR_LOCK_FILE):
            data = _read_json(path)
            if not data or int(data.get("pid") or 0) == self.pid:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
        self._owned = False

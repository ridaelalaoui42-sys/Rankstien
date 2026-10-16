"""Cross-process state for the Pinterest supervisor."""

from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .config import DATA_DIR

logger = logging.getLogger("rankstein.runtime_state")

RUNTIME_DIR = DATA_DIR / "runtime"
SUPERVISOR_LOCK_FILE = RUNTIME_DIR / "supervisor.lock"
SUPERVISOR_STATE_FILE = RUNTIME_DIR / "supervisor.json"
SUPERVISOR_STOP_FILE = RUNTIME_DIR / "supervisor.stop"
_LEASE_THREAD_GUARD = threading.RLock()


class SupervisorOwnershipLostError(RuntimeError):
    """The running pool no longer owns its recorded supervisor lease."""


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Publish complete JSON with a unique temp for this target and writer.

    Windows readers can briefly deny replacement. Retry only the atomic rename;
    never truncate the last valid state or share another writer's temporary file.
    """
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.{os.getpid()}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
        for attempt in range(4):
            try:
                temporary.replace(path)
                return
            except OSError:
                if attempt == 3:
                    raise
                time.sleep(0.02 * (2**attempt))
    finally:
        try:
            temporary.unlink()
        except OSError:
            # Only this call's uncommitted temp can remain; never remove a shared
            # legacy supervisor.tmp or another owner's state to recover a write.
            pass


@contextmanager
def _lease_state_guard():
    """Serialize lease changes with an OS lock released on process exit.

    Keep the guard file in place: unlinking it could give waiting contenders
    different inodes and let both enter the lease's read/remove/create section.
    Closing the descriptor releases the OS lock, including on process exit.
    """
    guard_file = SUPERVISOR_LOCK_FILE.with_name(SUPERVISOR_LOCK_FILE.name + ".guard")
    _LEASE_THREAD_GUARD.acquire()
    try:
        descriptor = os.open(guard_file, os.O_CREAT | os.O_RDWR)
    except BaseException:
        _LEASE_THREAD_GUARD.release()
        raise
    locked = False
    try:
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"0")
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX)
        locked = True
        yield
    finally:
        try:
            if locked:
                os.lseek(descriptor, 0, os.SEEK_SET)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            try:
                os.close(descriptor)
            finally:
                _LEASE_THREAD_GUARD.release()


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
            # An elevated owner can be alive even though this process cannot
            # query it. Refuse a competing pool when liveness is uninspectable.
            return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (OSError, SystemError):
        return False
    return True


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _read_lease_json(path: Path) -> dict | None:
    """Ownership reads fail closed; an unreadable file is not an absent owner."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    value = json.loads(text)
    if not isinstance(value, dict) or isinstance(value.get("pid"), bool):
        raise ValueError(f"Invalid supervisor ownership record: {path.name}")
    pid = value.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        raise ValueError(f"Invalid supervisor owner PID: {path.name}")
    started = value.get("started_at")
    if started is not None and (
        isinstance(started, bool)
        or not isinstance(started, (int, float))
        or not math.isfinite(started)
        or started <= 0
    ):
        raise ValueError(f"Invalid supervisor owner start: {path.name}")
    return value


def _process_matches_lease(pid: int, lease_started_at: float) -> bool:
    """A stale heartbeat does not revoke ownership from a living original process."""
    try:
        import psutil

        process = psutil.Process(pid)
        # A newer process with the same PID cannot be the recorded lease owner.
        return not lease_started_at or process.create_time() <= lease_started_at + 1.0
    except ImportError:
        return True
    except psutil.NoSuchProcess:
        return False
    except psutil.Error:
        # Refuse takeover when permissions prevent proving that the owner exited.
        return True


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


def supervisor_admission_status() -> dict:
    """Read whether a new supervisor may try to acquire the maintained lease.

    A living owner remains exclusive while draining or doing worker-zero
    maintenance, regardless of heartbeat age or its command line. This check
    never creates or removes runtime files; acquire() remains the atomic gate
    if another owner arrives after the read.
    """
    try:
        records = [_read_lease_json(path) for path in (SUPERVISOR_LOCK_FILE, SUPERVISOR_STATE_FILE)]
        owners = {}
        for record in records:
            if record is None:
                continue
            pid = record["pid"]
            if _process_alive(pid) and _process_matches_lease(pid, float(record.get("started_at") or 0)):
                identity = (pid, record.get("started_at"), record.get("lease_id"))
                owners[identity] = record
    except (OSError, ValueError, TypeError) as exc:
        return {"can_start": False, "reason": "ownership_unverified", "cause": type(exc).__name__}
    if not owners:
        return {"can_start": True, "reason": "no_live_owner", "pid": None}
    if len(owners) > 1:
        return {
            "can_start": False,
            "reason": "conflicting_owners",
            "pids": sorted({record["pid"] for record in owners.values()}),
        }
    owner = next(iter(owners.values()))
    worker_count = owner.get("worker_count")
    return {
        "can_start": False,
        "reason": "maintenance" if worker_count == 0 else "live_owner",
        "pid": owner["pid"],
        "worker_count": worker_count,
    }


def request_supervisor_stop(*, target_pid: int | None = None, expected_start: float | None = None) -> dict:
    """Request a drain, optionally for an independently verified legacy owner.

    An explicit target requires its process creation timestamp (not the later
    lease-construction timestamp). The command must be run_autonomous.py run.
    The JSON remains compatible with older stop_requested implementations.
    """
    if target_pid is None:
        status = supervisor_status()
        if not status["running"]:
            return {"success": False, "error": "Supervisor not running", **status}
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with _lease_state_guard():
        if target_pid is None:
            if expected_start is not None:
                raise ValueError("An expected process start requires an explicit target PID")
            status = supervisor_status()
            if not status["running"]:
                return {"success": False, "error": "Supervisor not running", **status}
            payload = {"pid": status["pid"], "requested_at": time.time()}
        else:
            if (
                isinstance(target_pid, bool)
                or not isinstance(target_pid, int)
                or target_pid <= 0
                or isinstance(expected_start, bool)
                or not isinstance(expected_start, (int, float))
                or not math.isfinite(expected_start)
                or expected_start <= 0
            ):
                raise ValueError("An explicit stop requires a positive PID and process creation timestamp")
            import psutil

            process = psutil.Process(target_pid)
            created = process.create_time()
            command = process.cmdline()
            script_index = next(
                (
                    index
                    for index, argument in enumerate(command)
                    if Path(argument).name.casefold() == "run_autonomous.py"
                ),
                None,
            )
            if (
                abs(created - expected_start) > 1.0
                or script_index is None
                or command[script_index + 1 : script_index + 2] != ["run"]
            ):
                raise ValueError("Explicit stop target no longer matches the verified supervisor process")
            status = {"running": True, "pid": target_pid, "process_started_at": created}
            payload = {"pid": target_pid, "requested_at": time.time(), "expected_start": created}
        _atomic_write_json(SUPERVISOR_STOP_FILE, payload)
    return {"success": True, "message": "Supervisor shutdown requested", **status}


class SupervisorLease:
    """Exclusive process lease with a machine-readable heartbeat."""

    def __init__(self, worker_count: int):
        self.pid = os.getpid()
        self.worker_count = worker_count
        self.started_at = time.time()
        self.lease_id = uuid.uuid4().hex
        self._owned = False

    def acquire(self) -> None:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        with _lease_state_guard():
            self._acquire_locked()

    def _acquire_locked(self) -> None:
        if self._owned:
            self._heartbeat_locked()
            return
        try:
            records = [_read_lease_json(path) for path in (SUPERVISOR_LOCK_FILE, SUPERVISOR_STATE_FILE)]
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError("Cannot verify existing Pinterest supervisor ownership") from exc
        for existing in records:
            if existing is None:
                continue
            existing_pid = existing["pid"]
            if self._record_is_ours(existing):
                continue  # Retry a partial acquisition by this exact lease only.
            if _process_alive(existing_pid) and _process_matches_lease(
                existing_pid, float(existing.get("started_at") or 0)
            ):
                raise RuntimeError(f"Pinterest supervisor already running with PID {existing_pid}")
        # Keep a valid lock present throughout replacement; never create an
        # absent-lock admission window while an old state record still exists.
        _atomic_write_json(SUPERVISOR_LOCK_FILE, self._ownership_payload())
        _atomic_write_json(SUPERVISOR_STATE_FILE, self._heartbeat_payload())
        self._owned = True
        try:
            SUPERVISOR_STOP_FILE.unlink()
        except FileNotFoundError:
            pass

    def _ownership_payload(self) -> dict:
        return {"pid": self.pid, "started_at": self.started_at, "lease_id": self.lease_id}

    def _heartbeat_payload(self) -> dict:
        return {**self._ownership_payload(), "heartbeat_at": time.time(), "worker_count": self.worker_count}

    def _record_is_ours(self, record: dict) -> bool:
        return (
            record.get("pid") == self.pid
            and record.get("started_at") == self.started_at
            and record.get("lease_id") == self.lease_id
        )

    def _assert_ownership_locked(self) -> tuple[dict | None, dict | None]:
        lock = _read_lease_json(SUPERVISOR_LOCK_FILE)
        state = _read_lease_json(SUPERVISOR_STATE_FILE)
        if not any((lock, state)) or any(
            record is not None and not self._record_is_ours(record) for record in (lock, state)
        ):
            self._owned = False
            raise SupervisorOwnershipLostError(f"Pinterest supervisor PID {self.pid} lost lease ownership")
        return lock, state

    def _heartbeat_locked(self) -> None:
        lock, _ = self._assert_ownership_locked()
        if lock is None:
            _atomic_write_json(SUPERVISOR_LOCK_FILE, self._ownership_payload())
        _atomic_write_json(SUPERVISOR_STATE_FILE, self._heartbeat_payload())

    def heartbeat(self) -> None:
        if not self._owned:
            return
        with _lease_state_guard():
            self._heartbeat_locked()

    def stop_requested(self) -> bool:
        request = _read_json(SUPERVISOR_STOP_FILE)
        if not request or int(request.get("pid") or 0) != self.pid:
            return False
        expected = request.get("expected_start")
        if expected is not None:
            try:
                import psutil

                return abs(psutil.Process(self.pid).create_time() - float(expected)) <= 1.0
            except ImportError:
                return False
            except (psutil.Error, TypeError, ValueError):
                return False
        return True

    def release(self) -> None:
        if not self._owned:
            return
        with _lease_state_guard():
            try:
                self._assert_ownership_locked()
            except (SupervisorOwnershipLostError, OSError, ValueError, TypeError):
                logger.warning(
                    "Preserving supervisor files because PID %s cannot prove current ownership", self.pid
                )
                self._owned = False
                return
            for path in (SUPERVISOR_STOP_FILE, SUPERVISOR_STATE_FILE, SUPERVISOR_LOCK_FILE):
                data = _read_json(path)
                owned = (
                    (data.get("pid") == self.pid)
                    if path == SUPERVISOR_STOP_FILE
                    else self._record_is_ours(data)
                )
                if owned:
                    try:
                        path.unlink()
                    except FileNotFoundError:
                        pass
            self._owned = False

"""Persistent, fail-closed pauses for accounts requiring a human to sign in.

Only configured handles, reason codes and timestamps are stored here. Browser
profiles, credentials, cookies and rate-limit budgets never enter this file.
"""

from __future__ import annotations

import logging
import math
import os
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from . import runtime_state
from .config import DATA_DIR, get_config

logger = logging.getLogger("rankstein.account_recovery")
RECOVERY_STATE_FILE = Path(
    os.environ.get("PINTEREST_ACCOUNT_RECOVERY_FILE")
    or DATA_DIR / "runtime" / "pinterest_account_recovery.json"
)
_REASONS = {"human_verification", "authentication_required", "owner_mismatch"}
_OWNER = re.compile(r"[0-9]{10,22}")


class AccountRecoveryStateError(RuntimeError):
    """Account admission must remain closed while pause state is unreadable."""


def _configured_accounts() -> set[str]:
    accounts = set(get_config().accounts)
    if not accounts or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", key) for key in accounts):
        raise AccountRecoveryStateError("Configured Pinterest account handles are unavailable or invalid")
    return accounts


def _account(account: str) -> str:
    if not isinstance(account, str) or account not in _configured_accounts():
        raise ValueError("A configured Pinterest account handle is required")
    return account


def _load_state() -> dict:
    import json

    try:
        raw = RECOVERY_STATE_FILE.read_bytes()
    except FileNotFoundError:
        return {"version": 1, "accounts": {}}
    try:
        if len(raw) > 262144:
            raise ValueError("Pause state exceeds its byte limit")
        state = json.loads(raw)
        if not isinstance(state, dict) or type(state.get("version")) is not int or state["version"] != 1:
            raise ValueError("Unsupported pause state")
        records = state.get("accounts")
        if not isinstance(records, dict) or not set(records).issubset(_configured_accounts()):
            raise ValueError("Unknown account in pause state")
        for record in records.values():
            if not isinstance(record, dict) or record.get("reason") not in _REASONS:
                raise ValueError("Invalid manual authentication reason")
            stamp = record.get("required_at")
            if (
                isinstance(stamp, bool)
                or not isinstance(stamp, (int, float))
                or not math.isfinite(stamp)
                or stamp <= 0
                or not re.fullmatch(r"[0-9a-f]{32}", str(record.get("pause_id", "")))
            ):
                raise ValueError("Invalid manual authentication record")
        return state
    except (ValueError, TypeError, UnicodeError) as exc:
        raise AccountRecoveryStateError("Pinterest account pause state is invalid") from exc


def paused_accounts() -> set[str]:
    """Return paused configured handles; unreadable state pauses every account."""
    accounts = _configured_accounts()
    try:
        return set(_load_state()["accounts"])
    except (OSError, AccountRecoveryStateError):
        logger.error("Pinterest account pause state unavailable; pausing all configured accounts")
        return accounts


def _prepare_guard() -> None:
    RECOVERY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    runtime_state.SUPERVISOR_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)


def require_manual_auth(account: str, reason: str = "human_verification") -> dict:
    """Persist a manual pause, without changing queue/circuit/rate-limit state."""
    account = _account(account)
    if reason not in _REASONS:
        raise ValueError("Use a recognized manual authentication reason code")
    _prepare_guard()
    with runtime_state._lease_state_guard():
        state = _load_state()
        # Repeated worker observations do not invalidate an active human's proof.
        record = state["accounts"].get(account)
        if record is None:
            record = {"reason": reason, "required_at": time.time(), "pause_id": uuid.uuid4().hex}
            state["accounts"][account] = record
            state["updated_at"] = time.time()
            runtime_state._atomic_write_json(RECOVERY_STATE_FILE, state)
        return {"account_handle": account, "paused": True, **record}


def clear_manual_auth_after_owner_verification(
    account: str,
    actual_owner_id: str,
    expected_owner_id: str,
    *,
    expected_pause_id: str | None = None,
) -> bool:
    """Clear exactly this pause after the caller has verified and closed its session."""
    account = _account(account)
    if (
        not isinstance(actual_owner_id, str)
        or not isinstance(expected_owner_id, str)
        or not _OWNER.fullmatch(actual_owner_id)
        or actual_owner_id != expected_owner_id
    ):
        raise ValueError("Authenticated Pinterest owner does not exactly match the expected owner")
    _prepare_guard()
    with runtime_state._lease_state_guard():
        state = _load_state()
        record = state["accounts"].get(account)
        if record is None:
            raise ValueError("Account is not awaiting manual authentication")
        if expected_pause_id is not None and record["pause_id"] != expected_pause_id:
            raise AccountRecoveryStateError("Manual authentication pause changed during verification")
        del state["accounts"][account]
        state["updated_at"] = time.time()
        runtime_state._atomic_write_json(RECOVERY_STATE_FILE, state)
    return True


@contextmanager
def account_profile_guard(account: str):
    """Hold the shared OS account guard through profile launch, use and close.

    Callers must not nest this guard or launch another owner for the same
    profile. Worker admission additionally checks ``paused_accounts``.
    """
    account = _account(account)
    _prepare_guard()
    path = RECOVERY_STATE_FILE.with_name(f"pinterest_account_recovery.{account}.guard")
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR)
    locked = False
    try:
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"0")
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:
            raise AccountRecoveryStateError("Another manual recovery owns this account") from exc
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
            os.close(descriptor)


@contextmanager
def manual_recovery_lease(account: str):
    """Require a persisted pause and hold the account guard until Chrome closes."""
    with account_profile_guard(account):
        with runtime_state._lease_state_guard():
            state = _load_state()
            record = state["accounts"].get(account)
            if record is None:
                raise ValueError("Pause the account before opening interactive recovery")
            pause_id = record["pause_id"]
        yield pause_id

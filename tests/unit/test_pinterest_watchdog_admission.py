"""Watchdog startup respects living supervisor and maintenance leases."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from pinterest_automation import runtime_state
from scripts.ops import rankstein_campaign_watchdog as watchdog

pytestmark = pytest.mark.unit


@pytest.fixture
def runtime_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(runtime_state, "RUNTIME_DIR", tmp_path)
    for constant, leaf in (
        ("SUPERVISOR_LOCK_FILE", "supervisor.lock"),
        ("SUPERVISOR_STATE_FILE", "supervisor.json"),
        ("SUPERVISOR_STOP_FILE", "supervisor.stop"),
    ):
        monkeypatch.setattr(runtime_state, constant, tmp_path / leaf)
    monkeypatch.setattr(runtime_state, "_process_alive", lambda pid: True)
    monkeypatch.setattr(runtime_state, "_process_matches_lease", lambda pid, started: True)
    return tmp_path


def _record(pid: int = 12345, workers: int = 3) -> dict:
    return {
        "pid": pid,
        "started_at": 1000.0,
        "lease_id": f"owner-{pid}",
        "heartbeat_at": 1001.0,
        "worker_count": workers,
    }


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _snapshot(root: Path) -> dict:
    return {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in root.iterdir()}


@pytest.mark.parametrize("leaf", ["supervisor.lock", "supervisor.json"])
@pytest.mark.parametrize("workers", [0, 3])
def test_living_owner_blocks_with_stale_heartbeat_and_either_record(
    runtime_files: Path, leaf: str, workers: int
) -> None:
    _write(runtime_files / leaf, _record(workers=workers))
    _write(runtime_state.SUPERVISOR_STOP_FILE, {"pid": 12345, "requested_at": 1002.0})
    before = _snapshot(runtime_files)

    status = runtime_state.supervisor_admission_status()

    assert status["can_start"] is False
    assert status["reason"] == ("maintenance" if workers == 0 else "live_owner")
    assert status["pid"] == 12345
    assert _snapshot(runtime_files) == before


def test_maintenance_without_command_match_blocks_and_does_not_write(runtime_files: Path) -> None:
    owner = _record(workers=0)
    _write(runtime_state.SUPERVISOR_LOCK_FILE, {k: v for k, v in owner.items() if k != "worker_count"})
    _write(runtime_state.SUPERVISOR_STATE_FILE, owner)
    before = _snapshot(runtime_files)

    assert runtime_state.supervisor_admission_status() == {
        "can_start": False,
        "reason": "maintenance",
        "pid": 12345,
        "worker_count": 0,
    }
    assert _snapshot(runtime_files) == before


@pytest.mark.parametrize("live,original", [(False, True), (True, False)])
def test_proven_dead_or_reused_pid_permits_acquisition_attempt_without_cleanup(
    runtime_files: Path, monkeypatch: pytest.MonkeyPatch, live: bool, original: bool
) -> None:
    _write(runtime_state.SUPERVISOR_STATE_FILE, _record())
    monkeypatch.setattr(runtime_state, "_process_alive", lambda pid: live)
    monkeypatch.setattr(runtime_state, "_process_matches_lease", lambda pid, started: original)
    before = _snapshot(runtime_files)

    assert runtime_state.supervisor_admission_status()["can_start"] is True
    assert _snapshot(runtime_files) == before


def test_absent_ownership_records_permit_attempt_without_guard_creation(runtime_files: Path) -> None:
    assert runtime_state.supervisor_admission_status() == {
        "can_start": True,
        "reason": "no_live_owner",
        "pid": None,
    }
    assert list(runtime_files.iterdir()) == []


def test_living_state_is_not_hidden_by_dead_lock(
    runtime_files: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(runtime_state.SUPERVISOR_LOCK_FILE, _record(11111))
    _write(runtime_state.SUPERVISOR_STATE_FILE, _record(22222, workers=0))
    monkeypatch.setattr(runtime_state, "_process_alive", lambda pid: pid == 22222)

    assert runtime_state.supervisor_admission_status()["reason"] == "maintenance"


def test_conflicting_living_owners_fail_closed(runtime_files: Path) -> None:
    _write(runtime_state.SUPERVISOR_LOCK_FILE, _record(11111))
    _write(runtime_state.SUPERVISOR_STATE_FILE, _record(22222))

    assert runtime_state.supervisor_admission_status() == {
        "can_start": False,
        "reason": "conflicting_owners",
        "pids": [11111, 22222],
    }


@pytest.mark.parametrize("leaf", ["supervisor.lock", "supervisor.json"])
def test_malformed_or_unreadable_ownership_blocks(
    runtime_files: Path, monkeypatch: pytest.MonkeyPatch, leaf: str
) -> None:
    path = runtime_files / leaf
    path.write_text("{", encoding="utf-8")
    assert runtime_state.supervisor_admission_status()["can_start"] is False
    original_read = Path.read_text

    def denied(target: Path, *args, **kwargs):
        if target == path:
            raise PermissionError("simulated inspection failure")
        return original_read(target, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied)
    assert runtime_state.supervisor_admission_status() == {
        "can_start": False,
        "reason": "ownership_unverified",
        "cause": "PermissionError",
    }


def test_process_inspection_error_is_not_permission_to_start(
    runtime_files: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(runtime_state.SUPERVISOR_STATE_FILE, _record())
    monkeypatch.setattr(runtime_state, "_process_alive", Mock(side_effect=PermissionError()))

    assert runtime_state.supervisor_admission_status()["can_start"] is False


@pytest.mark.parametrize(
    ("code", "output"),
    [
        (1, "inspection timed out"),
        (0, "not JSON"),
        (0, "[]"),
        (0, '{"can_start": "yes", "reason": "no_live_owner"}'),
        (0, '{"can_start": true}'),
    ],
)
def test_watchdog_probe_failure_never_authorizes_start(
    monkeypatch: pytest.MonkeyPatch, code: int, output: str
) -> None:
    monkeypatch.setattr(watchdog, "_run", lambda args, timeout: (code, output))

    assert watchdog._pinterest_admission() == {
        "can_start": False,
        "reason": "ownership_unverified",
    }


@pytest.mark.parametrize("can_start", [True, False])
def test_watchdog_reads_maintained_admission_protocol(
    monkeypatch: pytest.MonkeyPatch, can_start: bool
) -> None:
    expected = {"can_start": can_start, "reason": "no_live_owner" if can_start else "maintenance"}
    run = Mock(return_value=(0, json.dumps(expected)))
    monkeypatch.setattr(watchdog, "_run", run)

    assert watchdog._pinterest_admission() == expected
    assert "supervisor_admission_status" in run.call_args.args[0][-1]
    assert run.call_args.kwargs["timeout"] == 30


@pytest.fixture
def isolated_watchdog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(watchdog, "RANKSTEIN", tmp_path)
    monkeypatch.setattr(watchdog, "_port_open", lambda port: True)

    def process_match(needle: str) -> bool:
        assert needle != "run_autonomous.py", "Pinterest admission must use the lease"
        return True

    monkeypatch.setattr(watchdog, "_ps_contains", process_match)
    monkeypatch.setattr(watchdog, "_file_age_minutes", lambda path: 0)
    monkeypatch.setattr(watchdog, "_health_json", lambda: {"ok": True})
    monkeypatch.setattr(watchdog, "_latest_report", lambda: {})
    start = Mock(return_value=99999)
    monkeypatch.setattr(watchdog, "_start_background", start)
    return start


@pytest.mark.parametrize(
    ("reason", "exit_code"),
    [("live_owner", 0), ("maintenance", 0), ("ownership_unverified", 1), ("conflicting_owners", 1)],
)
def test_watchdog_does_not_launch_over_owner_or_uncertainty(
    isolated_watchdog, monkeypatch: pytest.MonkeyPatch, reason: str, exit_code: int
) -> None:
    monkeypatch.setattr(watchdog, "_pinterest_admission", lambda: {"can_start": False, "reason": reason})

    assert watchdog.main() == exit_code
    isolated_watchdog.assert_not_called()


def test_watchdog_still_starts_when_no_live_owner(isolated_watchdog, monkeypatch) -> None:
    monkeypatch.setattr(
        watchdog, "_pinterest_admission", lambda: {"can_start": True, "reason": "no_live_owner"}
    )

    assert watchdog.main() == 0
    isolated_watchdog.assert_called_once()
    assert isolated_watchdog.call_args.args[0][-1] == "run"
    assert isolated_watchdog.call_args.args[1] == "automation.log"


def test_pinterest_maintenance_preserves_other_campaign_startups(isolated_watchdog, monkeypatch) -> None:
    monkeypatch.setattr(
        watchdog, "_pinterest_admission", lambda: {"can_start": False, "reason": "maintenance"}
    )
    monkeypatch.setattr(watchdog, "_ps_contains", lambda needle: False)

    assert watchdog.main() == 0
    assert [call.args[1] for call in isolated_watchdog.call_args_list] == ["remasterer.log", "articles.log"]

"""A failed heartbeat must not hide a stop request or permit displaced workers."""

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from pinterest_automation.runtime_state import SupervisorOwnershipLostError
from pinterest_automation.supervisor import AutonomousSupervisor


@pytest.mark.asyncio
async def test_stop_request_precedes_even_an_unwritable_heartbeat():
    supervisor = object.__new__(AutonomousSupervisor)
    supervisor._shutdown_event = asyncio.Event()
    supervisor._lease = SimpleNamespace(
        stop_requested=Mock(return_value=True), heartbeat=Mock(side_effect=PermissionError("busy"))
    )
    await asyncio.wait_for(supervisor._control_loop(), timeout=1)
    assert supervisor._shutdown_event.is_set()
    supervisor._lease.heartbeat.assert_not_called()


@pytest.mark.asyncio
async def test_displaced_supervisor_stops_acquiring_work():
    supervisor = object.__new__(AutonomousSupervisor)
    supervisor._shutdown_event = asyncio.Event()
    supervisor._lease = SimpleNamespace(
        stop_requested=Mock(return_value=False),
        heartbeat=Mock(side_effect=SupervisorOwnershipLostError("different owner")),
    )
    await asyncio.wait_for(supervisor._control_loop(), timeout=1)
    assert supervisor._shutdown_event.is_set()
    supervisor._lease.heartbeat.assert_called_once()


@pytest.mark.asyncio
async def test_transient_heartbeat_error_still_honors_next_stop_request():
    supervisor = object.__new__(AutonomousSupervisor)
    supervisor._shutdown_event = asyncio.Event()
    supervisor._lease = SimpleNamespace(
        stop_requested=Mock(side_effect=[False, True]), heartbeat=Mock(side_effect=PermissionError("busy"))
    )
    await asyncio.wait_for(supervisor._control_loop(), timeout=3)
    assert supervisor._shutdown_event.is_set()
    supervisor._lease.heartbeat.assert_called_once()


@pytest.mark.asyncio
async def test_ownership_loss_during_drain_still_closes_sessions(monkeypatch):
    from unittest.mock import AsyncMock

    supervisor = object.__new__(AutonomousSupervisor)
    supervisor._shutdown_event = asyncio.Event()
    supervisor.config = SimpleNamespace(worker_count=1, graceful_shutdown_seconds=1)
    supervisor._lease = SimpleNamespace(
        acquire=Mock(),
        release=Mock(),
        stop_requested=Mock(return_value=False),
        heartbeat=Mock(side_effect=SupervisorOwnershipLostError("different owner")),
    )
    supervisor.health = SimpleNamespace(
        heartbeat=Mock(return_value=SimpleNamespace(all_ok=True)),
        start_monitoring=AsyncMock(),
        config=SimpleNamespace(heartbeat_interval_seconds=30),
    )
    supervisor._health_reporter = AsyncMock()
    supervisor._cleanup = AsyncMock()

    async def finish_when_stopping(_worker_id):
        await supervisor._shutdown_event.wait()

    supervisor._queue_worker = finish_when_stopping
    real_loop = asyncio.get_running_loop()
    monkeypatch.setattr(real_loop, "add_signal_handler", Mock())
    await asyncio.wait_for(supervisor.run(startup_draft_maintenance=False), timeout=6)
    supervisor._cleanup.assert_awaited_once()
    supervisor._lease.release.assert_called_once()
    assert supervisor._running is False


@pytest.mark.asyncio
async def test_shutdown_during_dequeue_returns_new_lease_before_session(monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr("pinterest_automation.supervisor.paused_accounts", lambda: set())

    supervisor = object.__new__(AutonomousSupervisor)
    supervisor._shutdown_event = asyncio.Event()
    supervisor._session_generation = 0
    supervisor._account_locks = {}
    supervisor._lease = SimpleNamespace(started_at=123)
    supervisor.health = SimpleNamespace(get_snapshot=Mock(return_value={}))
    supervisor._blocking_health_issues = Mock(return_value={})
    supervisor._default_account_handle = Mock(return_value="rida")
    supervisor._account_handle_for_job = Mock(side_effect=AssertionError("must not process"))
    supervisor.queue = SimpleNamespace(release_async=AsyncMock())
    driver = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr("pinterest_automation.supervisor.PinterestDriver", lambda: driver)

    async def claim_while_stopping(**_kwargs):
        supervisor._shutdown_event.set()
        return SimpleNamespace(id="late-claim")

    supervisor.queue.dequeue_async = claim_while_stopping
    await asyncio.wait_for(supervisor._queue_worker(0), timeout=2)
    supervisor.queue.release_async.assert_awaited_once_with("late-claim", delay_seconds=0)
    supervisor._account_handle_for_job.assert_not_called()


@pytest.mark.asyncio
async def test_manual_auth_pause_excludes_account_before_dequeue(monkeypatch):
    from unittest.mock import AsyncMock

    supervisor = object.__new__(AutonomousSupervisor)
    supervisor._shutdown_event = asyncio.Event()
    supervisor._session_generation = 0
    supervisor._account_locks = {}
    supervisor._lease = SimpleNamespace(started_at=123)
    supervisor.config = SimpleNamespace(watch_interval_seconds=0)
    supervisor.health = SimpleNamespace(get_snapshot=Mock(return_value={}))
    supervisor._blocking_health_issues = Mock(return_value={})
    supervisor._default_account_handle = Mock(return_value="rida")
    driver = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr("pinterest_automation.supervisor.PinterestDriver", lambda: driver)
    monkeypatch.setattr("pinterest_automation.supervisor.paused_accounts", lambda: {"med"})

    async def nothing_eligible(**kwargs):
        assert kwargs["locked_keys"] == {"med"}
        supervisor._shutdown_event.set()
        return None

    supervisor.queue = SimpleNamespace(dequeue_async=nothing_eligible)
    await supervisor._queue_worker(0)
    driver.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_manual_pause_arriving_during_claim_releases_without_browser(monkeypatch):
    from unittest.mock import AsyncMock

    supervisor = object.__new__(AutonomousSupervisor)
    supervisor._shutdown_event = asyncio.Event()
    supervisor._session_generation = 0
    supervisor._account_locks = {}
    supervisor._lease = SimpleNamespace(started_at=123)
    supervisor.config = SimpleNamespace(watch_interval_seconds=0)
    supervisor.health = SimpleNamespace(get_snapshot=Mock(return_value={}))
    supervisor._blocking_health_issues = Mock(return_value={})
    supervisor._default_account_handle = Mock(return_value="rida")
    supervisor._account_handle_for_job = Mock(return_value="med")
    driver = SimpleNamespace(close=AsyncMock(), ensure_logged_in=AsyncMock())
    monkeypatch.setattr("pinterest_automation.supervisor.PinterestDriver", lambda: driver)
    monkeypatch.setattr("pinterest_automation.supervisor.paused_accounts", Mock(side_effect=[set(), {"med"}]))

    async def claim(**_kwargs):
        return SimpleNamespace(id="paused-mid-claim", next_retry_at=None)

    async def release(*_args, **_kwargs):
        supervisor._shutdown_event.set()

    supervisor.queue = SimpleNamespace(dequeue_async=claim, release_async=AsyncMock(side_effect=release))
    await supervisor._queue_worker(0)
    supervisor.queue.release_async.assert_awaited_once_with("paused-mid-claim", delay_seconds=60.0)
    driver.ensure_logged_in.assert_not_called()

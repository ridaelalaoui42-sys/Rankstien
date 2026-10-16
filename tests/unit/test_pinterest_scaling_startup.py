from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


def _cached_config(*, workers: int = 2, sessions: int = 2):
    return SimpleNamespace(
        supervisor=SimpleNamespace(worker_count=workers),
        browser=SimpleNamespace(max_sessions=sessions),
    )


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("explicit_queue_only", [False, True])
async def test_queue_only_applies_concurrency_before_config_and_skips_campaign_boot(
    monkeypatch, explicit_queue_only
):
    import run_autonomous as runner

    config = _cached_config()
    monkeypatch.setenv("PINTEREST_MAX_WORKERS", "3")
    monkeypatch.setenv("PINTEREST_MAX_SESSIONS", "3")
    if not explicit_queue_only:
        monkeypatch.setenv("RANKSTEIN_QUEUE_ONLY", "1")
    for name in (
        "RANKSTEIN_ENQUEUE_UNPINNED_POSTS",
        "RANKSTEIN_ENQUEUE_REMASTER_FOLDER",
        "RANKSTEIN_ENABLE_REMASTER_SIPHON",
    ):
        monkeypatch.setenv(name, "1")
    monkeypatch.delenv("RANKSTEIN_SKIP_SUPERVISOR_ARTICLES", raising=False)

    def read_config():
        assert runner.os.environ["PINTEREST_WORKER_COUNT"] == "3"
        assert runner.os.environ["PINTEREST_MAX_SESSIONS"] == "3"
        return config

    monkeypatch.setattr(runner, "get_config", read_config)
    for name in ("enqueue_backlog", "enqueue_batch", "_process_running"):
        monkeypatch.setattr(runner, name, Mock(side_effect=AssertionError(f"unexpected {name}")))
    monkeypatch.setattr(runner._subprocess, "Popen", Mock(side_effect=AssertionError("unexpected process")))
    monkeypatch.setattr(
        runner.agent_memory, "log_event", Mock(side_effect=AssertionError("unexpected memory"))
    )
    supervisor = SimpleNamespace(run=AsyncMock())

    def build_supervisor(*, worker_count):
        assert worker_count == config.supervisor.worker_count == 3
        assert config.browser.max_sessions == 3
        return supervisor

    monkeypatch.setattr(runner, "AutonomousSupervisor", build_supervisor)
    await runner.run_supervisor(SimpleNamespace(workers=3, queue_only=explicit_queue_only))

    supervisor.run.assert_awaited_once_with(startup_draft_maintenance=False)


@pytest.mark.unit
def test_worker_selection_respects_existing_caps_and_updates_cached_config(monkeypatch):
    import run_autonomous as runner

    config = _cached_config(workers=10, sessions=10)
    monkeypatch.setattr(runner, "get_config", lambda: config)
    monkeypatch.setenv("PINTEREST_MAX_WORKERS", "3")
    monkeypatch.setenv("PINTEREST_MAX_SESSIONS", "2")

    workers = runner._configure_pinterest_workers(SimpleNamespace(workers=20))

    assert workers == config.supervisor.worker_count == 3
    assert config.browser.max_sessions == 2
    assert runner.os.environ["PINTEREST_MAX_WORKERS"] == "3"
    assert runner.os.environ["PINTEREST_MAX_SESSIONS"] == "2"


@pytest.mark.unit
def test_no_explicit_worker_count_keeps_two_worker_default(monkeypatch):
    import run_autonomous as runner

    config = _cached_config()
    monkeypatch.setattr(runner, "get_config", lambda: config)
    workers = runner._configure_pinterest_workers(SimpleNamespace(workers=None))

    assert workers == config.supervisor.worker_count == 2
    assert config.browser.max_sessions == 2
    assert "PINTEREST_MAX_WORKERS" not in runner.os.environ


@pytest.mark.unit
def test_configuration_supports_serialized_config_sections(monkeypatch):
    import run_autonomous as runner

    config = SimpleNamespace(supervisor={"worker_count": 2}, browser={"max_sessions": 2})
    monkeypatch.setattr(runner, "get_config", lambda: config)
    monkeypatch.setenv("PINTEREST_MAX_WORKERS", "3")
    assert runner._configure_pinterest_workers(SimpleNamespace(workers=3)) == 3
    assert config.supervisor["worker_count"] == 3
    assert config.browser["max_sessions"] == 3


@pytest.mark.unit
@pytest.mark.parametrize("workers", [0, -1])
def test_invalid_explicit_workers_fail_before_loading_config(monkeypatch, workers):
    import run_autonomous as runner

    get_config = Mock()
    monkeypatch.setattr(runner, "get_config", get_config)
    with pytest.raises(ValueError, match="must be positive"):
        runner._configure_pinterest_workers(SimpleNamespace(workers=workers))
    get_config.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize(
    "arguments",
    [
        ["run", "--queue-only", "--workers", "3"],
        ["--workers", "3", "run", "--queue-only"],
    ],
)
def test_run_cli_accepts_queue_only_and_worker_count(monkeypatch, arguments):
    import run_autonomous as runner

    boot = AsyncMock()
    monkeypatch.setattr(runner, "run_supervisor", boot)
    monkeypatch.setattr(sys, "argv", ["run_autonomous.py", *arguments])
    runner.main()

    boot.assert_awaited_once()
    args = boot.await_args.args[0]
    assert args.command == "run"
    assert args.queue_only is True
    assert args.workers == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_full_boot_configures_workers_before_backlog(monkeypatch):
    import run_autonomous as runner

    config = _cached_config()
    monkeypatch.setattr(runner, "get_config", lambda: config)
    monkeypatch.setenv("PINTEREST_MAX_WORKERS", "3")
    monkeypatch.setenv("RANKSTEIN_SKIP_SUPERVISOR_ARTICLES", "1")
    monkeypatch.setattr(runner.agent_memory, "log_event", Mock())

    def enqueue_backlog():
        assert config.supervisor.worker_count == 3
        assert config.browser.max_sessions == 3
        return 0

    backlog = Mock(side_effect=enqueue_backlog)
    monkeypatch.setattr(runner, "enqueue_backlog", backlog)
    supervisor = SimpleNamespace(run=AsyncMock())
    monkeypatch.setattr(runner, "AutonomousSupervisor", Mock(return_value=supervisor))
    await runner.run_supervisor(SimpleNamespace(workers=3, queue_only=False))

    backlog.assert_called_once_with()
    supervisor.run.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("maintenance", [False, True])
async def test_supervisor_startup_draft_maintenance_is_optional(monkeypatch, maintenance):
    import pinterest_automation.supervisor as module

    purge = AsyncMock(return_value={})
    monkeypatch.setitem(
        sys.modules,
        "scripts.ops.clear_pinterest_drafts",
        SimpleNamespace(clear_all_accounts_drafts=purge),
    )
    supervisor = object.__new__(module.AutonomousSupervisor)
    supervisor.config = SimpleNamespace(worker_count=3)
    supervisor._lease = Mock()
    supervisor._shutdown_event = SimpleNamespace(clear=Mock(), wait=AsyncMock())
    supervisor.health = SimpleNamespace(
        heartbeat=Mock(return_value=SimpleNamespace(all_ok=True)),
        config=SimpleNamespace(heartbeat_interval_seconds=30),
        start_monitoring=AsyncMock(),
    )
    supervisor._control_loop = AsyncMock()
    supervisor._health_reporter = AsyncMock()
    supervisor._queue_worker = AsyncMock()
    supervisor._cleanup = AsyncMock()
    monkeypatch.setattr(module.asyncio, "get_running_loop", Mock(return_value=Mock()))
    monkeypatch.setattr(module.asyncio, "sleep", AsyncMock())

    if maintenance:
        await supervisor.run()
        purge.assert_awaited_once_with()
    else:
        await supervisor.run(startup_draft_maintenance=False)
        purge.assert_not_called()
    assert supervisor._queue_worker.call_count == 3
    assert [call.args[0] for call in supervisor._queue_worker.call_args_list] == [0, 1, 2]
    supervisor._lease.release.assert_called_once_with()


@pytest.mark.unit
def test_supervisor_constructor_respects_explicit_worker_cap(monkeypatch):
    import pinterest_automation.supervisor as module

    config = _cached_config()
    monkeypatch.setattr(module, "get_config", lambda: config)
    for name in (
        "get_health_monitor",
        "get_job_queue",
        "get_circuit_breaker",
        "get_rate_limiter",
        "get_session_pool",
        "SupervisorLease",
    ):
        monkeypatch.setattr(module, name, Mock())
    monkeypatch.setenv("PINTEREST_MAX_WORKERS", "3")
    supervisor = module.AutonomousSupervisor(worker_count=10)

    assert supervisor.config.worker_count == 3
    module.SupervisorLease.assert_called_once_with(3)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_shutdown_drains_inflight_worker_and_renews_lease_before_closing_pool(monkeypatch):
    import pinterest_automation.supervisor as module

    supervisor = object.__new__(module.AutonomousSupervisor)
    supervisor.config = SimpleNamespace(worker_count=1, graceful_shutdown_seconds=10)
    supervisor._shutdown_event = asyncio.Event()
    supervisor._driver = None
    worker_started = asyncio.Event()
    finish_allowed = asyncio.Event()
    drain_heartbeat_renewed = asyncio.Event()
    history = []
    drain_heartbeats = 0

    def heartbeat():
        nonlocal drain_heartbeats
        if supervisor._shutdown_event.is_set():
            drain_heartbeats += 1
            if drain_heartbeats >= 2:
                drain_heartbeat_renewed.set()

    async def worker(_worker_id):
        worker_started.set()
        await finish_allowed.wait()
        history.append("worker_finished")

    async def background(*_args):
        await supervisor._shutdown_event.wait()

    async def close_pool():
        assert history == ["worker_finished"]
        history.append("pool_closed")

    def release_lease():
        assert history == ["worker_finished", "pool_closed"]
        history.append("lease_released")

    supervisor._lease = SimpleNamespace(
        acquire=Mock(), heartbeat=Mock(side_effect=heartbeat), release=Mock(side_effect=release_lease)
    )
    supervisor.pool = SimpleNamespace(close_all=AsyncMock(side_effect=close_pool))
    supervisor.health = SimpleNamespace(
        heartbeat=Mock(return_value=SimpleNamespace(all_ok=True)),
        config=SimpleNamespace(heartbeat_interval_seconds=30),
        start_monitoring=background,
    )
    supervisor._queue_worker = worker
    supervisor._control_loop = background
    supervisor._health_reporter = background

    # Keep the real event loop and drain waits, only compress startup staggering.
    original_sleep = asyncio.sleep

    async def fast_startup_sleep(delay):
        await original_sleep(0 if delay == 2 else delay)

    monkeypatch.setattr(module.asyncio, "sleep", fast_startup_sleep)
    monkeypatch.setattr(asyncio.get_running_loop(), "add_signal_handler", lambda *_args: None)
    run_task = asyncio.create_task(supervisor.run(startup_draft_maintenance=False))
    try:
        await asyncio.wait_for(worker_started.wait(), timeout=5)
        supervisor._shutdown_event.set()
        await asyncio.wait_for(drain_heartbeat_renewed.wait(), timeout=5)

        assert drain_heartbeats >= 2
        assert not run_task.done()
        assert history == []
        supervisor.pool.close_all.assert_not_called()
        supervisor._lease.release.assert_not_called()

        finish_allowed.set()
        await asyncio.wait_for(run_task, timeout=5)
        assert history == ["worker_finished", "pool_closed", "lease_released"]
        supervisor.pool.close_all.assert_awaited_once_with()
        supervisor._lease.release.assert_called_once_with()
        assert supervisor.is_running is False
    finally:
        finish_allowed.set()
        supervisor._shutdown_event.set()
        if not run_task.done():
            run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)

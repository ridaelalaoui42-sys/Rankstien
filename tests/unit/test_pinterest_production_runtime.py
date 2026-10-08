from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pinterest_automation.job_queue import JobQueue


def _isolated_session_pool():
    from pinterest_automation.session_pool import SessionPool

    pool = object.__new__(SessionPool)
    pool.config = SimpleNamespace(
        browser=SimpleNamespace(session_ttl_minutes=60, max_sessions=2),
        accounts={},
    )
    pool._sessions = {}
    pool._session_counter = 0
    pool._dict_lock = asyncio.Lock()
    pool._granular_locks = {}
    pool._playwright = None
    pool._playwright_lock = asyncio.Lock()
    return pool


def _fake_session(*, in_use: bool = False):
    from pinterest_automation.session_pool import SessionInfo

    return SessionInfo(
        context=SimpleNamespace(pages=[object()], close=AsyncMock()),
        page=SimpleNamespace(is_closed=lambda: False),
        playwright=None,
        session_id="rida",
        account_handle="rida",
        browser_type="chromium",
        in_use=in_use,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_direct_upload_uses_running_supervisor_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pinterest_automation.mcp_integration as integration

    queue = SimpleNamespace(
        enqueue_pin_upload_async=AsyncMock(return_value="priority-job"),
        get_job_outcome_async=AsyncMock(
            return_value={
                "state": "completed",
                "result": {
                    "success": True,
                    "pin_id": "1148488342513342877",
                    "pin_url": "https://www.pinterest.com/pin/1148488342513342877/",
                },
                "errors": [],
            }
        ),
    )
    monkeypatch.setattr(integration, "supervisor_status", lambda: {"running": True})
    monkeypatch.setattr(integration, "get_job_queue", lambda: queue)
    monkeypatch.setattr(
        integration,
        "get_config",
        lambda: SimpleNamespace(accounts={"media": object()}, default_board="Aperitivos"),
    )
    driver = pytest.fail
    monkeypatch.setattr(integration, "PinterestDriver", driver)

    result = await integration.upload_pin_via_driver(
        image_path="pin.jpg",
        title="Calabacin",
        description="Receta",
        link="https://example.com/calabacin",
        board_name="Aperitivos",
        domain_handle="recetagenial",
        account_handle="media",
    )

    assert result["success"] is True
    assert result["method"] == "supervisor_queue"
    assert result["job_id"] == "priority-job"
    assert queue.enqueue_pin_upload_async.await_args.kwargs["priority"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_direct_upload_wait_extends_through_scheduled_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pinterest_automation.mcp_integration as integration

    retry_at = time.time() + 0.08

    async def job_outcome(_job_id: str) -> dict:
        if time.time() < retry_at:
            return {"state": "pending", "result": None, "errors": []}
        return {
            "state": "completed",
            "result": {
                "success": True,
                "pin_id": "1148488342513342878",
                "pin_url": "https://www.pinterest.com/pin/1148488342513342878/",
            },
            "errors": [],
        }

    queue = SimpleNamespace(
        enqueue_pin_upload_async=AsyncMock(return_value="deferred-priority-job"),
        get_job_outcome_async=job_outcome,
        list_pending_async=AsyncMock(
            return_value=[
                SimpleNamespace(id="deferred-priority-job", next_retry_at=retry_at),
            ]
        ),
    )
    monkeypatch.setattr(integration, "supervisor_status", lambda: {"running": True})
    monkeypatch.setattr(integration, "get_job_queue", lambda: queue)
    monkeypatch.setattr(
        integration,
        "get_config",
        lambda: SimpleNamespace(accounts={"media": object()}, default_board="Aperitivos"),
    )
    monkeypatch.setattr(integration, "PinterestDriver", pytest.fail)
    # A legacy fixed 20ms deadline would return pending before the scheduled
    # retry. The retry-aware waiter remains attached, within this hard cap.
    monkeypatch.setenv("PINTEREST_DIRECT_QUEUE_WAIT_SECONDS", "0.02")
    monkeypatch.setenv("PINTEREST_DIRECT_QUEUE_MAX_WAIT_SECONDS", "0.5")
    monkeypatch.setenv("PINTEREST_DIRECT_QUEUE_RETRY_MARGIN_SECONDS", "0.05")
    monkeypatch.setenv("PINTEREST_DIRECT_QUEUE_POLL_SECONDS", "0.01")

    result = await integration.upload_pin_via_driver(
        image_path="pin.jpg",
        title="Calabacin",
        description="Receta",
        link="https://example.com/calabacin",
        board_name="Aperitivos",
        domain_handle="recetagenial",
        account_handle="media",
    )

    assert time.time() >= retry_at
    assert result["success"] is True
    assert result["job_id"] == "deferred-priority-job"
    assert queue.enqueue_pin_upload_async.await_args.kwargs["priority"] == 1
    assert queue.list_pending_async.await_count >= 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_direct_upload_scheduled_retry_stops_at_hard_wait_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pinterest_automation.mcp_integration as integration

    clock = SimpleNamespace(monotonic=0.0, wall=1_000.0, sleeps=[])
    loop = SimpleNamespace(time=lambda: clock.monotonic)

    async def fake_sleep(seconds: float) -> None:
        clock.sleeps.append(seconds)
        clock.monotonic += seconds
        clock.wall += seconds

    queue = SimpleNamespace(
        enqueue_pin_upload_async=AsyncMock(return_value="capped-priority-job"),
        get_job_outcome_async=AsyncMock(
            return_value={
                "found": True,
                "state": "retry",
                "next_retry_at": 1_100.0,
                "result": None,
                "errors": [],
            }
        ),
    )
    monkeypatch.setattr(integration, "supervisor_status", lambda: {"running": True})
    monkeypatch.setattr(integration, "get_job_queue", lambda: queue)
    monkeypatch.setattr(
        integration,
        "get_config",
        lambda: SimpleNamespace(accounts={"media": object()}, default_board="Aperitivos"),
    )
    monkeypatch.setattr(integration, "PinterestDriver", pytest.fail)
    monkeypatch.setattr(
        integration,
        "asyncio",
        SimpleNamespace(get_running_loop=lambda: loop, sleep=fake_sleep),
    )
    monkeypatch.setattr(integration, "time", SimpleNamespace(time=lambda: clock.wall))
    monkeypatch.setenv("PINTEREST_DIRECT_QUEUE_WAIT_SECONDS", "1")
    monkeypatch.setenv("PINTEREST_DIRECT_QUEUE_MAX_WAIT_SECONDS", "2")
    monkeypatch.setenv("PINTEREST_DIRECT_QUEUE_RETRY_MARGIN_SECONDS", "0")
    monkeypatch.setenv("PINTEREST_DIRECT_QUEUE_POLL_SECONDS", "10")

    result = await integration.upload_pin_via_driver(
        image_path="pin.jpg",
        title="Calabacin",
        description="Receta",
        link="https://example.com/calabacin",
        board_name="Aperitivos",
        domain_handle="recetagenial",
        account_handle="media",
    )

    assert result == {
        "success": False,
        "pending": True,
        "job_id": "capped-priority-job",
        "method": "supervisor_queue",
        "next_retry_at": 1_100.0,
        "error": "Queued upload did not finish within bounded 2s wait",
    }
    assert clock.monotonic == 2.0
    assert clock.sleeps == [2.0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_direct_upload_default_hard_wait_cap_is_five_minutes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pinterest_automation.mcp_integration as integration

    clock = SimpleNamespace(monotonic=0.0, wall=1_000.0, sleeps=[])
    loop = SimpleNamespace(time=lambda: clock.monotonic)

    async def fake_sleep(seconds: float) -> None:
        clock.sleeps.append(seconds)
        clock.monotonic += seconds
        clock.wall += seconds

    queue = SimpleNamespace(
        enqueue_pin_upload_async=AsyncMock(return_value="deferred-priority-job"),
        get_job_outcome_async=AsyncMock(
            return_value={
                "found": True,
                "state": "pending",
                "next_retry_at": 10_000.0,
                "result": None,
                "errors": [],
            }
        ),
    )
    monkeypatch.setattr(integration, "supervisor_status", lambda: {"running": True})
    monkeypatch.setattr(integration, "get_job_queue", lambda: queue)
    monkeypatch.setattr(
        integration,
        "get_config",
        lambda: SimpleNamespace(accounts={"media": object()}, default_board="Aperitivos"),
    )
    monkeypatch.setattr(integration, "PinterestDriver", pytest.fail)
    monkeypatch.setattr(
        integration,
        "asyncio",
        SimpleNamespace(get_running_loop=lambda: loop, sleep=fake_sleep),
    )
    monkeypatch.setattr(integration, "time", SimpleNamespace(time=lambda: clock.wall))
    monkeypatch.setenv("PINTEREST_DIRECT_QUEUE_WAIT_SECONDS", "1")
    monkeypatch.delenv("PINTEREST_DIRECT_QUEUE_MAX_WAIT_SECONDS", raising=False)
    monkeypatch.setenv("PINTEREST_DIRECT_QUEUE_RETRY_MARGIN_SECONDS", "0")
    monkeypatch.setenv("PINTEREST_DIRECT_QUEUE_POLL_SECONDS", "120")

    result = await integration.upload_pin_via_driver(
        image_path="pin.jpg",
        title="Calabacin",
        description="Receta",
        link="https://example.com/calabacin",
        board_name="Aperitivos",
        domain_handle="recetagenial",
        account_handle="media",
    )

    assert result["pending"] is True
    assert result["next_retry_at"] == 10_000.0
    assert clock.monotonic == 300.0
    assert sum(clock.sleeps) == 300.0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_direct_upload_reports_deleted_queue_job_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pinterest_automation.mcp_integration as integration

    clock = SimpleNamespace(monotonic=0.0, wall=1_000.0, sleeps=[])
    loop = SimpleNamespace(time=lambda: clock.monotonic)

    async def fake_sleep(seconds: float) -> None:
        clock.sleeps.append(seconds)
        clock.monotonic += seconds
        clock.wall += seconds

    queue = SimpleNamespace(
        enqueue_pin_upload_async=AsyncMock(return_value="deleted-priority-job"),
        get_job_outcome_async=AsyncMock(
            return_value={
                "found": False,
                "state": "missing",
                "result": None,
                "errors": [],
            }
        ),
        list_pending_async=AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(integration, "supervisor_status", lambda: {"running": True})
    monkeypatch.setattr(integration, "get_job_queue", lambda: queue)
    monkeypatch.setattr(
        integration,
        "get_config",
        lambda: SimpleNamespace(accounts={"media": object()}, default_board="Aperitivos"),
    )
    monkeypatch.setattr(integration, "PinterestDriver", pytest.fail)
    monkeypatch.setattr(
        integration,
        "asyncio",
        SimpleNamespace(get_running_loop=lambda: loop, sleep=fake_sleep),
    )
    monkeypatch.setattr(integration, "time", SimpleNamespace(time=lambda: clock.wall))
    monkeypatch.setenv("PINTEREST_DIRECT_QUEUE_WAIT_SECONDS", "1")
    monkeypatch.setenv("PINTEREST_DIRECT_QUEUE_MAX_WAIT_SECONDS", "2")
    monkeypatch.setenv("PINTEREST_DIRECT_QUEUE_RETRY_MARGIN_SECONDS", "0")
    monkeypatch.setenv("PINTEREST_DIRECT_QUEUE_POLL_SECONDS", "10")

    result = await integration.upload_pin_via_driver(
        image_path="pin.jpg",
        title="Calabacin",
        description="Receta",
        link="https://example.com/calabacin",
        board_name="Aperitivos",
        domain_handle="recetagenial",
        account_handle="media",
    )

    assert result["success"] is False
    assert result["job_id"] == "deleted-priority-job"
    assert result["method"] == "supervisor_queue"
    assert clock.monotonic <= 2.0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_direct_upload_returns_terminal_supervisor_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pinterest_automation.mcp_integration as integration

    queue = SimpleNamespace(
        enqueue_pin_upload_async=AsyncMock(return_value="dead-priority-job"),
        get_job_outcome_async=AsyncMock(
            return_value={
                "state": "dead",
                "result": None,
                "errors": ["Pinterest rejected the upload"],
            }
        ),
    )
    monkeypatch.setattr(integration, "supervisor_status", lambda: {"running": True})
    monkeypatch.setattr(integration, "get_job_queue", lambda: queue)
    monkeypatch.setattr(
        integration,
        "get_config",
        lambda: SimpleNamespace(accounts={"media": object()}, default_board="Aperitivos"),
    )
    monkeypatch.setattr(integration, "PinterestDriver", pytest.fail)

    result = await integration.upload_pin_via_driver(
        image_path="pin.jpg",
        title="Calabacin",
        description="Receta",
        domain_handle="recetagenial",
        account_handle="media",
    )

    assert result["success"] is False
    assert result.get("pending") is not True
    assert result["job_id"] == "dead-priority-job"
    assert result["error"] == "Pinterest rejected the upload"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unhealthy_driver_close_retires_session() -> None:
    from pinterest_automation.pinterest_driver import PinterestDriver

    pool = SimpleNamespace(release=AsyncMock(), retire=AsyncMock())
    session = SimpleNamespace()
    driver = object.__new__(PinterestDriver)
    driver.pool = pool
    driver._session = session

    await driver.close(healthy=False)

    pool.release.assert_awaited_once_with(session, healthy=False)
    pool.retire.assert_awaited_once_with(session)
    assert driver._session is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_pool_waits_for_same_account_lease_instead_of_creating_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pinterest_automation.session_pool as session_pool_module

    pool = _isolated_session_pool()
    existing = _fake_session(in_use=True)
    pool._sessions[existing.session_id] = existing
    create_session = AsyncMock(side_effect=AssertionError("duplicate profile launch"))
    pool._create_session = create_session
    # Keep the regression bounded while leaving enough scheduler margin for
    # heavily loaded Windows CI hosts. The behavior under test is reuse versus
    # duplicate profile creation, not a sub-200 ms timing guarantee.
    monkeypatch.setattr(session_pool_module, "SESSION_ACQUIRE_TIMEOUT_SECONDS", 2.0)
    monkeypatch.setattr(session_pool_module, "SESSION_ACQUIRE_POLL_SECONDS", 0.005)

    async def release_existing() -> None:
        await asyncio.sleep(0.02)
        await pool.release(existing)

    release_task = asyncio.create_task(release_existing())
    acquired = await pool.acquire("rida")
    await release_task

    assert acquired is existing
    assert existing.in_use is True
    create_session.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_pool_fails_closed_while_same_account_lease_remains_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pinterest_automation.session_pool as session_pool_module

    pool = _isolated_session_pool()
    existing = _fake_session(in_use=True)
    pool._sessions[existing.session_id] = existing
    create_session = AsyncMock(side_effect=AssertionError("duplicate profile launch"))
    pool._create_session = create_session
    monkeypatch.setattr(session_pool_module, "SESSION_ACQUIRE_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(session_pool_module, "SESSION_ACQUIRE_POLL_SECONDS", 0.005)

    with pytest.raises(RuntimeError, match="refusing to launch a duplicate persistent context"):
        await pool.acquire("rida")

    assert pool._sessions["rida"] is existing
    create_session.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stale_session_retire_cannot_remove_newer_generation() -> None:
    pool = _isolated_session_pool()
    stale = _fake_session(in_use=False)
    current = _fake_session(in_use=False)
    pool._sessions[current.session_id] = current

    await pool.retire(stale)

    assert pool._sessions["rida"] is current
    assert stale.closed is True
    stale.context.close.assert_awaited_once()
    current.context.close.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_supervisor_releases_driver_before_account_unlock() -> None:
    from pinterest_automation.supervisor import AutonomousSupervisor

    account_lock = asyncio.Lock()
    await account_lock.acquire()
    observations = []

    class RotatedDriver:
        async def close(self, healthy: bool = True) -> None:
            observations.append((healthy, account_lock.locked()))

    released = await AutonomousSupervisor._release_driver_before_account_unlock(
        RotatedDriver(),
        account_lock,
        lock_acquired=True,
        healthy=True,
    )

    assert released is True
    assert observations == [(True, True)]
    assert account_lock.locked() is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cancelled_pin_upload_drains_shared_and_response_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.scripts.pinterest_batch_core as batch_core
    import pinterest_automation.pinterest_driver as driver_module
    from pinterest_automation.pinterest_driver import PinterestDriver

    image = tmp_path / "pin.jpg"
    image.write_bytes(b"image")
    shared_started = asyncio.Event()
    shared_cleaned = asyncio.Event()
    response_started = asyncio.Event()
    response_cleaned = asyncio.Event()

    async def blocked_shared_upload(*args, **kwargs):
        shared_started.set()
        try:
            await asyncio.Future()
        finally:
            shared_cleaned.set()

    class TrackingResponseEvent:
        async def wait(self) -> None:
            response_started.set()
            try:
                await asyncio.Future()
            finally:
                response_cleaned.set()

    limiter = SimpleNamespace(
        can_execute=lambda operation: True,
        record_execution=lambda operation: None,
    )
    driver = object.__new__(PinterestDriver)
    driver.account_handle = "media"
    driver.config = SimpleNamespace(default_board="Aperitivos")
    driver.circuit = SimpleNamespace(can_execute=lambda operation: True)
    driver._session = None
    driver._pin_create_data = {}
    driver._pin_create_event = None
    driver._response_handler = None
    driver._acquire_session = AsyncMock(return_value=SimpleNamespace(page=object()))
    driver.info = lambda *args, **kwargs: None

    def setup_interception(page) -> None:
        driver._pin_create_data = {"pin_id": None, "pin_url": None}
        driver._pin_create_event = TrackingResponseEvent()

    driver._setup_pin_interception = setup_interception
    monkeypatch.setattr(batch_core, "create_pin_from_fields", blocked_shared_upload)
    monkeypatch.setattr(driver_module, "get_rate_limiter", lambda domain_handle=None: limiter)
    monkeypatch.setattr(
        driver_module,
        "resolve_account_board_name",
        lambda board_name, account_handle: board_name,
    )

    upload = asyncio.create_task(
        driver.create_pin(
            image_path=str(image),
            title="Recipe",
            description="Description",
            link="https://example.com/recipe",
            board_name="Aperitivos",
            account_handle="media",
            domain_handle="recetagenial",
        )
    )
    await asyncio.wait_for(shared_started.wait(), timeout=1)
    await asyncio.wait_for(response_started.wait(), timeout=1)
    upload.cancel()

    with pytest.raises(asyncio.CancelledError):
        await upload

    assert shared_cleaned.is_set()
    assert response_cleaned.is_set()


@pytest.mark.unit
def test_routing_selects_one_uploader_and_bounds_cross_saves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pinterest_automation.routing import (
        account_cohort,
        cross_save_targets,
        select_upload_account,
    )

    config = SimpleNamespace(accounts={"a": object(), "b": object(), "c": object()})
    monkeypatch.setenv("PINTEREST_DOMAIN_ACCOUNT_MAP", '{"blog":["b","a"]}')
    monkeypatch.setenv("PINTEREST_CROSS_SAVE_LIMIT", "1")

    assert account_cohort("blog", config=config) == ["b", "a"]
    assert select_upload_account("blog", "asset", config=config) in {"a", "b"}
    assert len(cross_save_targets("blog", "a", config=config)) == 1


@pytest.mark.unit
def test_cross_saves_are_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from pinterest_automation.routing import cross_save_targets

    config = SimpleNamespace(accounts={"a": object(), "b": object()})
    monkeypatch.delenv("PINTEREST_CROSS_SAVE_LIMIT", raising=False)

    assert cross_save_targets("blog", "a", config=config) == []


@pytest.mark.unit
def test_article_campaign_enqueues_one_upload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pinterest_automation.campaign as campaign

    image = tmp_path / "recipe.png"
    image.write_bytes(b"image")
    queue = JobQueue(db_file=tmp_path / "jobs.db")
    config = SimpleNamespace(
        accounts={"a": object(), "b": object()},
        boards={},
        default_board="Aperitivos",
    )
    monkeypatch.setattr(campaign, "get_config", lambda: config)
    monkeypatch.setattr(campaign, "get_job_queue", lambda: queue)

    result = campaign.create_pinterest_campaign(
        slug="recipe",
        title="Recipe",
        excerpt="A useful excerpt",
        domain_handle="blog",
        domain_url="blog.example",
        image_path=str(image),
    )

    assert result["success"] is True
    assert result["jobs_created"] == 1
    pending = queue.list_pending()
    assert len(pending) == 1
    assert pending[0].payload["domain_handle"] == "blog"
    assert pending[0].payload["account_handle"] in {"a", "b"}
    assert pending[0].payload["alt_text"] == (
        "Foto vertical de Recipe, receta terminada y lista para servir."
    )


@pytest.mark.unit
def test_supervisor_lease_is_visible_cross_process_style(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pinterest_automation.runtime_state as runtime_state

    monkeypatch.setattr(runtime_state, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(runtime_state, "SUPERVISOR_LOCK_FILE", tmp_path / "supervisor.lock")
    monkeypatch.setattr(runtime_state, "SUPERVISOR_STATE_FILE", tmp_path / "supervisor.json")
    monkeypatch.setattr(runtime_state, "SUPERVISOR_STOP_FILE", tmp_path / "supervisor.stop")

    lease = runtime_state.SupervisorLease(worker_count=2)
    lease.acquire()
    try:
        status = runtime_state.supervisor_status(max_age_seconds=10)
        assert status["running"] is True
        assert status["worker_count"] == 2
    finally:
        lease.release()

    assert runtime_state.supervisor_status(max_age_seconds=10)["running"] is False


@pytest.mark.unit
def test_supervisor_heartbeat_survives_windows_replace_contention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pinterest_automation.runtime_state as runtime_state

    state_file = tmp_path / "supervisor.json"
    monkeypatch.setattr(runtime_state, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(runtime_state, "SUPERVISOR_LOCK_FILE", tmp_path / "supervisor.lock")
    monkeypatch.setattr(runtime_state, "SUPERVISOR_STATE_FILE", state_file)
    monkeypatch.setattr(runtime_state, "SUPERVISOR_STOP_FILE", tmp_path / "supervisor.stop")

    lease = runtime_state.SupervisorLease(worker_count=2)
    lease.acquire()
    original_replace = Path.replace

    def blocked_replace(path: Path, target: Path) -> Path:
        if path == state_file.with_suffix(".tmp"):
            raise OSError("simulated Windows file-sharing contention")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", blocked_replace)
    try:
        lease.heartbeat()
        state = json.loads(state_file.read_text(encoding="utf-8"))
        assert state["pid"] == lease.pid
        assert state["worker_count"] == 2
        assert not state_file.with_suffix(".tmp").exists()
    finally:
        lease.release()

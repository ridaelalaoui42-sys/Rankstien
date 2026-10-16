"""Network failures before authentication must preserve account and job retries."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture(autouse=True)
def _isolated_upload_preflight_and_recovery_state(monkeypatch, tmp_path):
    import pinterest_automation.account_recovery as recovery_module
    import pinterest_automation.supervisor as supervisor_module

    monkeypatch.setattr(recovery_module, "RECOVERY_STATE_FILE", tmp_path / "account_recovery.json")
    # Network-deferral scenarios intentionally use fake/missing image bytes;
    # actual media acceptance is covered separately before browser acquisition.
    monkeypatch.setattr(supervisor_module, "validate_pin_upload_image", lambda *_: {"ok": True})


@pytest.fixture
def login_driver():
    from pinterest_automation.pinterest_driver import PinterestDriver

    page = SimpleNamespace(url="about:blank", goto=AsyncMock())
    session = SimpleNamespace(page=page, context=object(), failure_count=0)
    driver = object.__new__(PinterestDriver)
    driver.account_handle = "blocked"
    driver.config = SimpleNamespace(browser=SimpleNamespace(navigation_timeout_ms=1000))
    driver.circuit = SimpleNamespace(
        can_execute=Mock(return_value=True), record_failure=Mock(), record_success=Mock()
    )
    driver.info = Mock()
    driver.error = Mock()
    driver._acquire_session = AsyncMock(return_value=session)
    driver._has_auth_cookies = AsyncMock(return_value=True)
    return SimpleNamespace(driver=driver, page=page, session=session)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "network_code",
    [
        "ERR_NAME_NOT_RESOLVED",
        "ERR_INTERNET_DISCONNECTED",
        "ERR_NETWORK_CHANGED",
        "ERR_CONNECTION_CLOSED",
        "ERR_CONNECTION_RESET",
        "ERR_CONNECTION_REFUSED",
        "ERR_CONNECTION_ABORTED",
        "ERR_CONNECTION_TIMED_OUT",
        "ERR_TIMED_OUT",
        "ERR_EMPTY_RESPONSE",
        "ERR_ADDRESS_UNREACHABLE",
        "ERR_PROXY_CONNECTION_FAILED",
        "ERR_TUNNEL_CONNECTION_FAILED",
        "ERR_DNS_TIMED_OUT",
    ],
)
@pytest.mark.parametrize("has_cookies", [True, False])
async def test_transport_failure_before_auth_does_not_poison_login_circuit(
    login_driver, network_code, has_cookies
):
    from pinterest_automation.pinterest_driver import PinterestNavigationUnavailableError

    harness = login_driver
    harness.driver._has_auth_cookies.return_value = has_cookies
    harness.page.goto.side_effect = RuntimeError(
        f"Page.goto: net::{network_code} at https://private.invalid/?email=private@example.invalid"
    )
    with pytest.raises(PinterestNavigationUnavailableError) as caught:
        await harness.driver.ensure_logged_in("blocked")
    assert caught.value.network_code == network_code
    assert "private" not in str(caught.value)
    assert "https://" not in str(caught.value)
    assert harness.session.failure_count == 0
    harness.driver.circuit.record_failure.assert_not_called()
    harness.driver.circuit.record_success.assert_not_called()
    harness.driver.error.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("has_cookies", [True, False])
@pytest.mark.parametrize("timeout_type", ["playwright", "builtin"])
async def test_navigation_timeout_is_not_an_authentication_failure(login_driver, has_cookies, timeout_type):
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    from pinterest_automation.pinterest_driver import PinterestNavigationUnavailableError

    harness = login_driver
    harness.driver._has_auth_cookies.return_value = has_cookies
    error = PlaywrightTimeoutError if timeout_type == "playwright" else TimeoutError
    harness.page.goto.side_effect = error("https://private.invalid/?email=private@example.invalid timed out")
    with pytest.raises(PinterestNavigationUnavailableError, match="NAVIGATION_TIMEOUT") as caught:
        await harness.driver.ensure_logged_in("blocked")
    assert "private" not in str(caught.value)
    assert harness.session.failure_count == 0
    harness.driver.circuit.record_failure.assert_not_called()
    harness.driver.error.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 502, 503, 504, 599])
async def test_navigation_http_outage_is_not_accepted_from_creator_url(login_driver, status):
    from pinterest_automation.pinterest_driver import PinterestNavigationUnavailableError

    harness = login_driver

    async def goto_creator(*_args, **_kwargs):
        harness.page.url = "https://www.pinterest.com/pin-creation-tool/"
        return SimpleNamespace(status=status)

    harness.page.goto.side_effect = goto_creator
    with pytest.raises(PinterestNavigationUnavailableError, match=f"HTTP_{status}"):
        await harness.driver.ensure_logged_in("blocked")
    assert harness.session.failure_count == 0
    harness.driver.circuit.record_failure.assert_not_called()
    harness.driver.circuit.record_success.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize("retry_after", ["3600", " 31536000 ", "3600.5"])
async def test_navigation_honors_numeric_retry_after(login_driver, status, retry_after):
    from pinterest_automation.pinterest_driver import PinterestNavigationUnavailableError

    login_driver.page.goto.return_value = SimpleNamespace(status=status, headers={"Retry-After": retry_after})
    with pytest.raises(PinterestNavigationUnavailableError) as caught:
        await login_driver.driver.ensure_logged_in("blocked")
    assert caught.value.retry_after_seconds == float(retry_after)
    assert caught.value.network_code == f"HTTP_{status}"
    login_driver.driver.circuit.record_failure.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 503])
async def test_navigation_honors_http_date_retry_after(login_driver, monkeypatch, status):
    import pinterest_automation.pinterest_driver as driver_module

    now = datetime(2026, 10, 15, 12, 0, tzinfo=UTC).timestamp()
    monkeypatch.setattr(driver_module, "time", SimpleNamespace(time=lambda: now))
    future = format_datetime(datetime.fromtimestamp(now + 7200, tz=UTC), usegmt=True)
    login_driver.page.goto.return_value = SimpleNamespace(status=status, headers={"retry-after": future})
    with pytest.raises(driver_module.PinterestNavigationUnavailableError) as caught:
        await login_driver.driver.ensure_logged_in("blocked")
    assert caught.value.retry_after_seconds == 7200
    assert future not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "retry_after",
    [
        None,
        "",
        "broken header",
        "-10",
        "nan",
        "inf",
        "-inf",
        "1e999",
        "1_000",
        "+3600",
        "1e3",
        "Wed, 01 Jan 2020 00:00:00 GMT",
    ],
)
async def test_navigation_ignores_invalid_or_expired_retry_after(login_driver, monkeypatch, retry_after):
    import pinterest_automation.pinterest_driver as driver_module

    monkeypatch.setattr(driver_module, "time", SimpleNamespace(time=lambda: 1792065600.0))
    login_driver.page.goto.return_value = SimpleNamespace(status=429, headers={"retry-after": retry_after})
    with pytest.raises(driver_module.PinterestNavigationUnavailableError) as caught:
        await login_driver.driver.ensure_logged_in("blocked")
    assert caught.value.retry_after_seconds == 0
    login_driver.driver.circuit.record_failure.assert_not_called()


@pytest.mark.asyncio
async def test_successful_navigation_preserves_response_and_options(login_driver):
    response = SimpleNamespace(status=200)
    login_driver.page.goto.return_value = response
    actual = await login_driver.driver._navigate_for_login(
        login_driver.page, "https://www.pinterest.com/login/", timeout=1000, wait_until="domcontentloaded"
    )
    assert actual is response
    login_driver.page.goto.assert_awaited_once_with(
        "https://www.pinterest.com/login/", timeout=1000, wait_until="domcontentloaded"
    )


@pytest.mark.asyncio
async def test_navigation_cancellation_propagates_without_authentication_failure(login_driver):
    login_driver.page.goto.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await login_driver.driver.ensure_logged_in("blocked")
    assert login_driver.session.failure_count == 0
    login_driver.driver.circuit.record_failure.assert_not_called()


@pytest.mark.asyncio
async def test_second_creator_navigation_keeps_transport_classification(login_driver, monkeypatch):
    import pinterest_automation.pinterest_driver as driver_module

    harness = login_driver
    harness.page.goto.side_effect = [None, RuntimeError("Page.goto: net::ERR_NAME_NOT_RESOLVED")]
    monkeypatch.setattr(driver_module, "asyncio", SimpleNamespace(sleep=AsyncMock()))
    with pytest.raises(driver_module.PinterestNavigationUnavailableError):
        await harness.driver.ensure_logged_in("blocked")
    assert harness.page.goto.await_count == 2
    harness.driver.circuit.record_failure.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", ["Security challenge", "Page.goto: net::ERR_CERT_AUTHORITY_INVALID"])
async def test_other_login_errors_keep_existing_auth_failure_behavior(login_driver, error):
    harness = login_driver
    harness.page.goto.side_effect = RuntimeError(error)
    assert await harness.driver.ensure_logged_in("blocked") is False
    harness.driver.circuit.record_failure.assert_called_once_with("pinterest_login:blocked")
    assert harness.session.failure_count == 1


@pytest.mark.asyncio
async def test_network_deferral_preserves_longer_account_and_job_deadlines(monkeypatch):
    import pinterest_automation.supervisor as supervisor_module
    from pinterest_automation.pinterest_driver import PinterestNavigationUnavailableError

    monkeypatch.setattr(supervisor_module, "time", SimpleNamespace(time=lambda: 1000.0))
    supervisor = object.__new__(supervisor_module.AutonomousSupervisor)
    supervisor.queue = SimpleNamespace(release_async=AsyncMock(), retry_or_fail_async=AsyncMock())
    supervisor._account_cooldowns = {"blocked": 3000.0, "healthy": 4000.0}
    job = SimpleNamespace(id="blocked-pin", next_retry_at=5000.0)
    await supervisor._defer_navigation_unavailable_job(
        job, "blocked", PinterestNavigationUnavailableError("ERR_NAME_NOT_RESOLVED")
    )
    supervisor.queue.release_async.assert_awaited_once_with("blocked-pin", delay_seconds=4000.0)
    supervisor.queue.retry_or_fail_async.assert_not_awaited()
    assert supervisor._account_cooldowns == {"blocked": 5000.0, "healthy": 4000.0}


@pytest.mark.asyncio
@pytest.mark.parametrize("job_retry_at, expected_retry_at", [(None, 8200.0), (10000.0, 10000.0)])
async def test_network_deferral_honors_server_retry_after_and_longer_job_deadline(
    monkeypatch, job_retry_at, expected_retry_at
):
    import pinterest_automation.supervisor as supervisor_module
    from pinterest_automation.pinterest_driver import PinterestNavigationUnavailableError

    monkeypatch.setattr(supervisor_module, "time", SimpleNamespace(time=lambda: 1000.0))
    supervisor = object.__new__(supervisor_module.AutonomousSupervisor)
    supervisor.queue = SimpleNamespace(release_async=AsyncMock(), retry_or_fail_async=AsyncMock())
    supervisor._account_cooldowns = {"blocked": 3000.0, "healthy": 4000.0}
    job = SimpleNamespace(id="blocked-pin", next_retry_at=job_retry_at)
    await supervisor._defer_navigation_unavailable_job(
        job, "blocked", PinterestNavigationUnavailableError("HTTP_429", retry_after_seconds=7200)
    )
    supervisor.queue.release_async.assert_awaited_once_with(
        "blocked-pin", delay_seconds=expected_retry_at - 1000.0
    )
    assert supervisor._account_cooldowns == {"blocked": expected_retry_at, "healthy": 4000.0}
    supervisor.queue.retry_or_fail_async.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_failure", [True, False])
async def test_single_job_defers_network_and_actual_auth_unavailability(
    monkeypatch, transport_failure, caplog
):
    import pinterest_automation.supervisor as supervisor_module
    from pinterest_automation.pinterest_driver import PinterestNavigationUnavailableError

    configured = SimpleNamespace(accounts={"blocked": object()})
    monkeypatch.setattr(supervisor_module, "get_config", lambda: configured)
    supervisor = object.__new__(supervisor_module.AutonomousSupervisor)
    driver = SimpleNamespace(ensure_logged_in=AsyncMock(return_value=False))
    if transport_failure:
        driver.ensure_logged_in.side_effect = PinterestNavigationUnavailableError("ERR_NAME_NOT_RESOLVED")
    supervisor._get_driver = AsyncMock(return_value=driver)
    supervisor.queue = SimpleNamespace(release_async=AsyncMock(), retry_or_fail_async=AsyncMock())
    job = SimpleNamespace(
        id="blocked-pin", type="pin_upload", payload={"account_handle": "blocked"}, next_retry_at=None
    )
    assert await supervisor._process_job(job) is False
    supervisor.queue.retry_or_fail_async.assert_not_awaited()
    assert supervisor.queue.release_async.await_args.kwargs["delay_seconds"] >= 300
    assert (
        "Pinterest navigation unavailable" in caplog.text
        if transport_failure
        else ("Pinterest authentication unavailable" in caplog.text)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("job_type", ["pin_upload", "pin_save"])
@pytest.mark.parametrize("transport_failure", [True, False])
async def test_worker_account_deferral_preserves_final_attempt_and_other_account_progress(
    monkeypatch, tmp_path, job_type, transport_failure
):
    import pinterest_automation.job_queue as queue_module
    import pinterest_automation.supervisor as supervisor_module
    from pinterest_automation.job_queue import Job, JobQueue
    from pinterest_automation.pinterest_driver import PinterestNavigationUnavailableError

    for name in ("QUEUE_FILE", "DLQ_FILE", "COMPLETED_FILE"):
        monkeypatch.setattr(queue_module, name, tmp_path / f"{name}.absent.json")
    configured = SimpleNamespace(
        accounts={"blocked": object(), "healthy": object()}, default_board="Chocolate"
    )
    monkeypatch.setattr(queue_module, "get_config", lambda: configured)
    monkeypatch.setattr(supervisor_module, "get_config", lambda: configured)
    monkeypatch.setenv("PINTEREST_DEFAULT_ACCOUNT_HANDLE", "blocked")
    queue = JobQueue(db_file=tmp_path / "jobs.db")
    for account in ("blocked", "healthy"):
        image = tmp_path / f"{account}.jpg"
        image.write_bytes(b"test image")
        queue.enqueue(
            Job(
                id=account,
                type=job_type,
                attempt=2 if account == "blocked" else 0,
                max_attempts=3,
                payload={
                    "account_handle": account,
                    "domain_handle": "test_domain",
                    "image_path": str(image),
                    "title": "Recipe",
                    "description": "Recipe description",
                    "pin_url": "https://www.pinterest.com/pin/123456789012345678/",
                    "board_name": "Chocolate",
                },
            )
        )
    limiter = SimpleNamespace(
        can_execute=Mock(return_value=True), wait_async=AsyncMock(), record_failure=Mock()
    )
    monkeypatch.setattr(supervisor_module, "get_rate_limiter", lambda **_kwargs: limiter)
    supervisor = object.__new__(supervisor_module.AutonomousSupervisor)
    supervisor.config = SimpleNamespace(worker_count=1, watch_interval_seconds=0.001)
    supervisor.queue = queue
    supervisor.health = SimpleNamespace(get_snapshot=lambda: SimpleNamespace(checks={}))
    supervisor._shutdown_event = asyncio.Event()
    supervisor._session_generation = 0
    supervisor._account_locks = {}
    supervisor._lease = SimpleNamespace(started_at=time.time())
    supervisor._log_success = Mock()
    supervisor._enqueue_cross_save = AsyncMock()
    closed = []

    class Driver:
        async def ensure_logged_in(self, account_handle=None):
            if account_handle == "blocked":
                if transport_failure:
                    raise PinterestNavigationUnavailableError("ERR_NAME_NOT_RESOLVED")
                return False
            return True

        async def close(self, healthy=True):
            closed.append(healthy)

        async def create_pin(self, **kwargs):
            supervisor._shutdown_event.set()
            return {"success": True, "pin_id": "123456789012345678"}

        save_pin = create_pin

    monkeypatch.setattr(supervisor_module, "PinterestDriver", Driver)
    worker_asyncio = SimpleNamespace(
        **{name: getattr(asyncio, name) for name in dir(asyncio) if not name.startswith("__")}
    )
    worker_asyncio.sleep = AsyncMock()
    monkeypatch.setattr(supervisor_module, "asyncio", worker_asyncio)
    started = time.time()
    await asyncio.wait_for(supervisor._queue_worker(1), timeout=5)
    blocked = next(job for job in queue.list_pending() if job.id == "blocked")
    assert blocked.attempt == 2
    assert blocked.next_retry_at >= started + 300
    assert blocked.error_log == []
    assert Path(blocked.payload["image_path"]).exists()
    assert queue.get_stats()["dlq_size"] == 0
    assert queue.get_job_outcome("healthy")["state"] == "completed"
    assert supervisor._account_cooldowns["blocked"] >= started + 300
    assert "healthy" not in supervisor._account_cooldowns
    assert supervisor._account_locks["blocked"].locked() is False
    assert False in closed
    limiter.record_failure.assert_not_called()

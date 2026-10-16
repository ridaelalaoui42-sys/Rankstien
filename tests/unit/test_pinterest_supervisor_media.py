"""Bad source files must not monopolize an otherwise healthy Pinterest account."""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image

from pinterest_automation.job_queue import Job, JobQueue
from pinterest_automation.supervisor import AutonomousSupervisor


@pytest.fixture
def isolated_queue(tmp_path, monkeypatch):
    import pinterest_automation.job_queue as queue_module

    # A temporary DB alone does not isolate the legacy migration entrypoints.
    for name in ("QUEUE_FILE", "DLQ_FILE", "COMPLETED_FILE"):
        monkeypatch.setattr(queue_module, name, tmp_path / f"{name}.absent.json")
    monkeypatch.setattr(queue_module, "get_config", lambda: SimpleNamespace(default_board="Aperitivos"))
    return JobQueue(db_file=tmp_path / "queue.sqlite3")


def _job(path, *, job_id, **kwargs):
    return Job(
        id=job_id,
        payload={
            "image_path": str(path),
            "title": f"Receta {job_id}",
            "description": "Receta de prueba",
            "link": f"https://example.invalid/{job_id}",
            "board_name": "Aperitivos",
            "account_handle": "media",
            "domain_handle": "test_domain",
        },
        **kwargs,
    )


def _supervisor(queue):
    supervisor = object.__new__(AutonomousSupervisor)
    supervisor.config = SimpleNamespace(watch_interval_seconds=0.01)
    supervisor.queue = queue
    supervisor.health = SimpleNamespace(get_snapshot=lambda: SimpleNamespace(checks={}))
    supervisor._shutdown_event = asyncio.Event()
    supervisor._session_generation = 0
    supervisor._account_locks = {}
    supervisor._account_cooldowns = {}
    supervisor._lease = SimpleNamespace(started_at=time.time())
    supervisor._default_account_handle = lambda: "media"
    supervisor._account_handle_for_job = lambda job: job.payload["account_handle"]
    supervisor._log_success = Mock()
    supervisor._enqueue_cross_save = AsyncMock()
    return supervisor


@pytest.mark.asyncio
async def test_poisoned_thumbnail_enters_dlq_before_browser_and_next_valid_job_completes(
    tmp_path, monkeypatch, isolated_queue
):
    import pinterest_automation.supervisor as supervisor_module

    poison = tmp_path / "thumbnail.jpg"
    Image.new("RGB", (150, 150), "red").save(poison, format="WEBP")
    original = poison.read_bytes()
    valid = tmp_path / "remaster.jpg"
    Image.new("RGB", (1000, 1500), "green").save(valid, format="JPEG")
    bad = _job(poison, job_id="poison", priority=1, attempt=1, max_attempts=5, error_log=["prior error"])
    good = _job(valid, job_id="valid", priority=2)
    assert isolated_queue.enqueue(bad) == bad.id
    assert isolated_queue.enqueue(good) == good.id

    supervisor = _supervisor(isolated_queue)
    driver = SimpleNamespace(
        ensure_logged_in=AsyncMock(return_value=True),
        create_pin=AsyncMock(
            return_value={
                "success": True,
                "pin_id": "1148488342519999999",
                "pin_url": "https://www.pinterest.com/pin/1148488342519999999/",
            }
        ),
        close=AsyncMock(),
    )
    limiter = SimpleNamespace(can_execute=Mock(return_value=True), wait_async=AsyncMock())
    rate_factory = Mock(return_value=limiter)
    monkeypatch.setattr(supervisor_module, "PinterestDriver", lambda: driver)
    monkeypatch.setattr(supervisor_module, "get_rate_limiter", rate_factory)
    monkeypatch.setattr(supervisor_module, "paused_accounts", lambda: set())
    monkeypatch.setattr(supervisor_module, "get_config", lambda: SimpleNamespace(default_board="Aperitivos"))
    # Source cleanup is independently covered; preserve both fixture files here.
    monkeypatch.setattr(isolated_queue, "image_path_already_queued_async", AsyncMock(return_value=True))
    real_fail = isolated_queue.fail_async
    real_complete = isolated_queue.complete_async

    async def record_poison(job_id, error):
        assert job_id == bad.id
        driver.ensure_logged_in.assert_not_awaited()
        driver.create_pin.assert_not_awaited()
        rate_factory.assert_not_called()
        assert supervisor._account_locks == {}
        assert supervisor._account_cooldowns == {}
        await real_fail(job_id, error)

    async def finish(job_id, result):
        await real_complete(job_id, result)
        supervisor._shutdown_event.set()

    monkeypatch.setattr(isolated_queue, "fail_async", record_poison)
    monkeypatch.setattr(isolated_queue, "complete_async", finish)
    await asyncio.wait_for(supervisor._queue_worker(0), timeout=6)

    with isolated_queue._conn() as connection:
        row = connection.execute("SELECT job_json FROM dlq WHERE id = ?", (bad.id,)).fetchone()
        retained = json.loads(row["job_json"])
    assert retained["payload"] == bad.payload
    assert retained["status"] == "dead"
    assert retained["attempt"] == 2  # Existing attempt plus this lease, never reset.
    assert retained["max_attempts"] == 5
    assert retained["error_log"][0] == "prior error"
    assert "unsupported_format" in retained["error_log"][-1]
    assert "WEBP" in retained["error_log"][-1] and "150x150" in retained["error_log"][-1]
    assert poison.read_bytes() == original
    assert isolated_queue.get_job_outcome(good.id)["state"] == "completed"
    driver.ensure_logged_in.assert_awaited_once_with("media")
    assert driver.create_pin.await_args.kwargs["image_path"] == str(valid)
    assert supervisor._account_cooldowns == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("future_delay", [0, 600])
async def test_invalid_quality_configuration_releases_without_dlq_or_consuming_attempt(
    tmp_path, monkeypatch, isolated_queue, future_delay
):
    import pinterest_automation.supervisor as supervisor_module

    monkeypatch.setenv("RANKSTEIN_REMASTER_MIN_IMAGE_WIDTH", "invalid")
    before = time.time()
    # Model an already claimed job, including a later dependency retry deadline.
    job = _job(
        tmp_path / "original.jpg",
        job_id="configuration-blocked",
        status="processing",
        attempt=4,
        max_attempts=7,
        next_retry_at=before + future_delay,
        error_log=["prior dependency issue"],
    )
    isolated_queue.enqueue(job)
    supervisor = _supervisor(isolated_queue)
    supervisor._get_driver = AsyncMock(side_effect=AssertionError("No browser for bad configuration"))
    fail = AsyncMock(side_effect=AssertionError("Configuration must not enter DLQ"))
    monkeypatch.setattr(isolated_queue, "fail_async", fail)
    monkeypatch.setattr(
        supervisor_module, "get_rate_limiter", Mock(side_effect=AssertionError("No rate use"))
    )

    assert await supervisor._process_job(job) is False
    pending = isolated_queue.list_pending()
    assert len(pending) == 1
    retained = pending[0]
    assert retained.id == job.id and retained.status == "pending"
    assert retained.payload == job.payload
    assert retained.attempt == 3 and retained.max_attempts == 7
    assert retained.error_log == job.error_log
    # The two wall-clock reads can round by a microsecond when the retained
    # deadline is subtracted and then reconstructed by the queue.
    assert retained.next_retry_at >= before + max(60, future_delay) - 0.001
    assert isolated_queue.get_stats()["dlq_size"] == 0
    supervisor._get_driver.assert_not_awaited()
    assert supervisor._account_cooldowns == {}
    assert supervisor._account_locks == {}


@pytest.mark.asyncio
async def test_direct_processing_rejects_missing_file_before_constructing_driver(tmp_path, isolated_queue):
    job = _job(tmp_path / "missing.jpg", job_id="missing", status="processing", attempt=1)
    isolated_queue.enqueue(job)
    supervisor = _supervisor(isolated_queue)
    supervisor._get_driver = AsyncMock(side_effect=AssertionError("Missing source must not open browser"))

    assert await supervisor._process_job(job) is False
    supervisor._get_driver.assert_not_awaited()
    assert isolated_queue.get_stats()["dlq_size"] == 1
    assert supervisor._account_cooldowns == {}


@pytest.mark.asyncio
async def test_save_jobs_do_not_require_an_upload_image(monkeypatch):
    import pinterest_automation.supervisor as supervisor_module

    monkeypatch.setattr(
        supervisor_module,
        "validate_pin_upload_image",
        Mock(side_effect=AssertionError("A save has no local upload image")),
    )
    supervisor = object.__new__(AutonomousSupervisor)
    assert await supervisor._validate_upload_media(Job(type="pin_save", payload={})) is True

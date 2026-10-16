"""Production completion and throughput reporting agree on Pinterest proof."""

import asyncio
import json
import sys
import unicodedata
from html import escape
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import urlencode

import pytest

from pinterest_automation.supervisor import AutonomousSupervisor
from scripts.dev.observe_pinterest_workers import verified_pin


@pytest.fixture(autouse=True)
def _isolated_manual_recovery_state(monkeypatch, tmp_path):
    import pinterest_automation.account_recovery as recovery_module

    monkeypatch.setattr(recovery_module, "RECOVERY_STATE_FILE", tmp_path / "account_recovery.json")


@pytest.mark.asyncio
async def test_unavailable_publish_preserves_final_attempt_and_other_account_progress(monkeypatch, tmp_path):
    import time

    import pinterest_automation.job_queue as queue_module
    import pinterest_automation.supervisor as supervisor_module
    from pinterest_automation.job_queue import Job, JobQueue

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
        image.write_bytes(b"source image")
        queue.enqueue(
            Job(
                id=account,
                type="pin_upload",
                attempt=2 if account == "blocked" else 0,
                max_attempts=3,
                payload={
                    "account_handle": account,
                    "domain_handle": "test_domain",
                    "image_path": str(image),
                    "title": "Recipe",
                    "description": "Recipe description",
                    "board_name": "Chocolate",
                },
            )
        )
    limiter = SimpleNamespace(
        can_execute=Mock(return_value=True), wait_async=AsyncMock(), record_failure=Mock()
    )
    monkeypatch.setattr(supervisor_module, "get_rate_limiter", lambda **_kwargs: limiter)
    supervisor = object.__new__(AutonomousSupervisor)
    supervisor.config = SimpleNamespace(worker_count=1, watch_interval_seconds=0.001)
    supervisor.queue = queue
    supervisor.health = SimpleNamespace(get_snapshot=lambda: SimpleNamespace(checks={}))
    supervisor._shutdown_event = asyncio.Event()
    supervisor._session_generation = 0
    supervisor._account_locks = {}
    supervisor._lease = SimpleNamespace(started_at=time.time())
    supervisor._log_success = Mock()
    supervisor._enqueue_cross_save = AsyncMock()

    class Driver:
        async def ensure_logged_in(self, account_handle=None):
            return True

        async def close(self, healthy=True):
            pass

        async def create_pin(self, **kwargs):
            if kwargs["account_handle"] == "blocked":
                return {
                    "success": False,
                    "error_code": "pinterest_publish_unavailable",
                    "error": "Publish is still disabled",
                    "uncertain": False,
                }
            supervisor._shutdown_event.set()
            return {"success": True, "pin_id": "123456789012345678"}

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
    limiter.record_failure.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"success": True, "pin_id": "1082904672940181452"}, True),
        ({"success": True, "pin_url": "https://www.pinterest.com/pin/1082904672940181452/"}, True),
        ({"success": True, "pin_url": "https://pinterest.com/pin/1082904672940181452/?view=1"}, True),
        ({"success": True, "pin_url": "https://example.invalid/pin/failure"}, False),
        ({"success": True, "pin_url": "https://www.pinterest.com/pin/"}, False),
        ({"success": True, "pin_url": "https://www.pinterest.com/pin/123"}, False),
        ({"success": True, "pin_url": "http://www.pinterest.com/pin/1082904672940181452/"}, False),
        (
            {"success": True, "pin_url": "https://www.pinterest.com@evil.example/pin/1082904672940181452/"},
            False,
        ),
        ({"success": True, "pin_url": "https://[invalid/pin/1082904672940181452/"}, False),
        ({"success": True, "pin_url": "https://www.pinterest.com/pin/1082904672940181452/extra"}, False),
        ({"success": "true", "pin_id": "1082904672940181452"}, False),
        ({"success": False, "pin_id": "1082904672940181452"}, False),
        ({"success": True}, False),
    ],
)
def test_upload_and_observer_proof_are_consistent(result, expected):
    assert AutonomousSupervisor.is_verified_upload(result) is expected
    assert bool(verified_pin(result)) is expected


@pytest.mark.unit
@pytest.mark.asyncio
async def test_single_job_path_retries_unverified_success_and_keeps_image(tmp_path):
    image = tmp_path / "remaster.jpg"
    image.write_bytes(b"source-image")
    driver = SimpleNamespace(
        ensure_logged_in=AsyncMock(return_value=True),
        create_pin=AsyncMock(return_value={"success": True, "pin_url": "https://www.pinterest.com/pin/"}),
    )
    supervisor = object.__new__(AutonomousSupervisor)
    supervisor._get_driver = AsyncMock(return_value=driver)
    supervisor.queue = SimpleNamespace(complete_async=AsyncMock(), retry_or_fail_async=AsyncMock())
    job = SimpleNamespace(
        id="unverified-job",
        type="pin_upload",
        payload={
            "image_path": str(image),
            "title": "Recipe",
            "description": "Recipe steps",
            "board_name": "Chocolate",
        },
    )

    assert await supervisor._process_job(job) is False

    supervisor.queue.complete_async.assert_not_awaited()
    supervisor.queue.retry_or_fail_async.assert_awaited_once_with(
        job.id, "Unverified Pinterest upload: success result has no valid pin_id or pin_url"
    )
    assert image.exists()


@pytest.fixture
def interception():
    from pinterest_automation.pinterest_driver import PinterestDriver

    driver = object.__new__(PinterestDriver)
    driver._response_handler = None
    driver.info = Mock()
    page = SimpleNamespace(on=Mock(), remove_listener=Mock())
    driver._setup_pin_interception(page)
    return driver, page


def _creation_response(
    *,
    path="/resource/PinResource/create/",
    status=200,
    data=None,
    host="www.pinterest.com",
    method="POST",
    post_data=None,
):
    return SimpleNamespace(
        url=f"https://{host}{path}",
        status=status,
        request=SimpleNamespace(method=method, post_data=post_data),
        json=AsyncMock(
            return_value=data
            if data is not None
            else {"resource_response": {"status": "success", "data": {"id": "1082904672940181452"}}}
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"path": "/resource/PinResource/update/"},
        {"path": "/resource/PinResource/delete/"},
        {"path": "/resource/PinResource/get/"},
        {"path": "/graphql/"},
        {"path": "/v3/pins/1082904672940181452/"},
        {"host": "www.pinterest.com.evil.invalid"},
        {"status": 500},
        {"status": 429},
        {"data": {"resource_response": {"status": "failure", "data": {"id": "1082904672940181452"}}}},
        {"data": {"resource_response": {"error": "failed", "data": {"id": "1082904672940181452"}}}},
        {"data": {"resource_response": {"data": {"id": "1082904672940181452", "is_draft": True}}}},
        {"data": {"resource_response": {"data": {"id": "1082904672940181452", "is_published": False}}}},
        {"data": {"resource_response": {"data": {"id": "1082904672940181452", "status": "draft"}}}},
        {"data": {"resource_response": {"data": {"board": {"id": "1082904672940181452"}}}}},
    ],
)
async def test_interception_rejects_noncreation_error_draft_and_unrelated_ids(interception, response):
    driver, _page = interception
    await driver._response_handler(_creation_response(**response))
    assert driver._pin_create_data["pin_id"] is None
    assert not driver._pin_create_event.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/resource/PinResource/create/", "/v3/pins/"])
@pytest.mark.parametrize("host", ["www.pinterest.com", "es.pinterest.com"])
async def test_successful_create_response_is_only_a_candidate(interception, path, host):
    driver, _page = interception
    await driver._response_handler(_creation_response(path=path, host=host))
    assert driver._pin_create_data["pin_id"] == "1082904672940181452"
    assert driver._pin_create_event.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("story", [False, True])
async def test_api_candidate_cannot_complete_or_cancel_shared_uploader_before_publication(
    interception, story
):
    driver, page = interception
    started = asyncio.Event()
    finish_publish = asyncio.Event()
    cancelled = False

    async def uploader(*_args):
        nonlocal cancelled
        started.set()
        try:
            await finish_publish.wait()
            return "1082904672940181999"
        except asyncio.CancelledError:
            cancelled = True
            raise

    task = asyncio.create_task(
        driver._shared_pin_upload_attempt(
            uploader,
            page,
            Path("pin.jpg"),
            "Recipe",
            "https://example.test/recipe",
            "Description",
            "Chocolate",
            "rida",
        )
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        await driver._response_handler(_story_response() if story else _creation_response())
        await asyncio.sleep(0)
        assert not task.done()
        assert cancelled is False
        finish_publish.set()
        assert await asyncio.wait_for(task, timeout=1) == "1082904672940181999"
        assert cancelled is False
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("story", [False, True])
async def test_old_response_callback_cannot_write_into_restarted_interception(interception, story):
    driver, page = interception
    reading = asyncio.Event()
    finish_response = asyncio.Event()
    response = _story_response() if story else _creation_response()

    async def delayed_json():
        reading.set()
        await finish_response.wait()
        return response.json.return_value

    response.json.side_effect = delayed_json
    task = asyncio.create_task(driver._response_handler(response))
    try:
        await asyncio.wait_for(reading.wait(), timeout=1)
        driver._setup_pin_interception(page)
        finish_response.set()
        await asyncio.wait_for(task, timeout=1)
        assert driver._pin_create_data["pin_id"] is None
        assert not driver._pin_create_event.is_set()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def _story_response(*, route="/v3/storypins/", form=True, options=None, **response_options):
    posted = {"options": {"url": route, **(options or {})}, "context": {}}
    raw = json.dumps(posted)
    data = {
        "resource_response": {
            "status": "success",
            "code": 0,
            "message": "Success",
            "endpoint_name": "sanitized_endpoint",
            "http_status": 200,
            "data": {
                "node_id": "opaque_node",
                "image_signature": "opaque_signature",
                "id": "1082904672940441493",
                "story_pin_data_id": "opaque_story_data",
                "image_square_url": "https://example.invalid/image.jpg",
            },
        }
    }
    return _creation_response(
        path=response_options.pop("path", "/resource/ApiResource/create/"),
        host=response_options.pop("host", "es.pinterest.com"),
        post_data=response_options.pop("post_data", urlencode({"data": raw}) if form else raw),
        data=response_options.pop("data", data),
        **response_options,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["pinterest.com", "www.pinterest.com", "es.pinterest.com"])
@pytest.mark.parametrize("form", [True, False])
async def test_observed_story_create_data_id_is_only_a_candidate(interception, host, form):
    driver, _page = interception
    await driver._response_handler(_story_response(host=host, form=form))
    assert driver._pin_create_data["pin_id"] == "1082904672940441493"
    assert driver._pin_create_event.is_set()
    assert driver._pin_create_data["pin_url"] == "https://www.pinterest.com/pin/1082904672940441493/"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "options",
    [
        {"route": "/v3/storypins/drafts/"},
        {"route": "/v3/storypins/drafts/1082904672940441493/"},
        {"route": "/v3/storypins/1082904672940441493/"},
        {"route": "/v3/storypins///"},
        {"route": "/v3/storypins/?draft=true"},
        {"route": "https://example.invalid/v3/storypins/"},
        {"path": "/resource/ApiResource/update/"},
        {"path": "/resource/ApiResource/delete/"},
        {"method": "GET"},
        {"status": 429},
        {"status": 500},
        {"host": "es.pinterest.com.evil.invalid"},
        {"host": "notpinterest.com"},
        {"post_data": "not valid request data"},
        {"post_data": json.dumps({"options": {}})},
        {"post_data": "data=%7B%7D&data=%7B%7D"},
        {"options": {"is_draft": True}},
        {"options": {"data": {"is_draft": True}}},
        {"options": {"data": {"status": "draft"}}},
        {"data": {"resource_response": {"status": "failure", "data": {"id": "1082904672940441493"}}}},
        {
            "data": {
                "resource_response": {
                    "status": "success",
                    "http_status": 500,
                    "data": {"id": "1082904672940441493"},
                }
            }
        },
        {
            "data": {
                "resource_response": {
                    "status": "success",
                    "error": "failed",
                    "data": {"id": "1082904672940441493"},
                }
            }
        },
        {
            "data": {
                "resource_response": {
                    "status": "success",
                    "data": {"id": "1082904672940441493", "is_draft": True},
                }
            }
        },
        {"data": {"resource_response": {"status": "success", "data": {"node_id": "1082904672940441493"}}}},
        {
            "data": {
                "resource_response": {
                    "status": "success",
                    "data": {"story_pin_data_id": "1082904672940441493"},
                }
            }
        },
        {"data": {"status": "success", "data": {"id": "1082904672940441493"}}},
    ],
)
async def test_story_candidate_rejects_other_operations_routes_states_and_id_fields(interception, options):
    driver, _page = interception
    await driver._response_handler(_story_response(**options))
    assert driver._pin_create_data["pin_id"] is None
    assert not driver._pin_create_event.is_set()


def _public_metadata(**overrides):
    fields = {
        "og:url": "https://www.pinterest.com/pin/1082904672940441493/",
        "canonical": "https://www.pinterest.com/pin/1082904672940441493/",
        "og:title": "Recipe",
        "pinterestapp:source": "https://example.test/recipe",
        "pinterestapp:pinner": "https://www.pinterest.com/Recetagenial/",
    }
    fields.update(overrides)
    tags = []
    for name, value in fields.items():
        if value is None:
            continue
        if name == "canonical":
            tags.append(f'<link rel="canonical" href="{escape(value, quote=True)}">')
        else:
            tags.append(f'<meta property="{name}" content="{escape(value, quote=True)}">')
    return "<html><head>" + "".join(tags) + "</head><body></body></html>"


def _candidate_page(driver, body=None, *, status=200, url=None, username="Recetagenial"):
    driver._pin_create_data["pin_id"] = "1082904672940441493"
    driver._public_username = Mock(return_value=username)
    driver._verify_recent_public_pin = AsyncMock(side_effect=AssertionError("No profile discovery"))
    response = SimpleNamespace(
        status=status,
        url=url or "https://www.pinterest.com/pin/1082904672940441493/",
        text=AsyncMock(return_value=body if body is not None else _public_metadata()),
    )
    request = SimpleNamespace(get=AsyncMock(return_value=response))
    return SimpleNamespace(context=SimpleNamespace(request=request)), response


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["www.pinterest.com", "es.pinterest.com"])
@pytest.mark.parametrize("streamed", [False, True])
async def test_candidate_fetches_only_exact_public_pin_with_all_required_metadata(
    interception, host, streamed
):
    driver, _page = interception
    url = f"https://{host}/pin/1082904672940441493/"
    body = _public_metadata(**{"og:url": url, "canonical": url})
    if streamed:
        tags = body.partition("<head>")[2].partition("</head>")[0]
        body = "<html><head></head><body>" + tags + "</body></html>"
    page, _response = _candidate_page(driver, body, url=url)
    result = await driver._verify_intercepted_public_pin(
        page, title="Recipe", link="https://example.test/recipe", account_handle="rida"
    )
    assert result == "1082904672940441493"
    page.context.request.get.assert_awaited_once_with(
        "https://www.pinterest.com/pin/1082904672940441493/", timeout=30000, fail_on_status_code=False
    )
    driver._verify_recent_public_pin.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"og:url": None},
        {"canonical": None},
        {"og:title": None},
        {"pinterestapp:source": None},
        {"pinterestapp:pinner": None},
        {"og:url": "https://www.pinterest.com/pin/1082904672940181999/"},
        {"canonical": "https://www.pinterest.com/pin/1082904672940181999/"},
        {"og:url": "https://www.pinterest.com.evil.invalid/pin/1082904672940441493/"},
        {"canonical": "http://www.pinterest.com/pin/1082904672940441493/"},
        {"og:title": "Recipe with extra words"},
        {"pinterestapp:source": "https://example.test/recipe-other"},
        {"pinterestapp:source": "https://example.test/recipe/"},
        {"pinterestapp:source": "https://other.test/?next=https://example.test/recipe"},
        {"pinterestapp:pinner": "https://www.pinterest.com/AnotherAccount/"},
        {"pinterestapp:pinner": "https://www.pinterest.com/Recetagenial/boards/"},
        {"pinterestapp:pinner": "https://www.pinterest.com/Recetagenial//"},
        {"pinterestapp:pinner": "https://pinterest.com.evil.invalid/Recetagenial/"},
    ],
)
async def test_candidate_rejects_missing_mismatched_or_substring_public_fields(interception, overrides):
    driver, _page = interception
    body = _public_metadata(**overrides).replace(
        "</body>", "Recipe https://example.test/recipe https://www.pinterest.com/Recetagenial/</body>"
    )
    page, _response = _candidate_page(driver, body)
    assert (
        await driver._verify_intercepted_public_pin(
            page, title="Recipe", link="https://example.test/recipe", account_handle="rida"
        )
        is None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "draft_only",
        "body_head_metadata",
        "conflicting_meta",
        "failed_http",
        "redirected_id",
        "no_username",
    ],
)
async def test_candidate_cannot_use_draft_json_body_metadata_or_another_public_page(interception, case):
    driver, _page = interception
    body = _public_metadata()
    if case == "draft_only":
        body = '<html><head></head><body>{"id":"1082904672940441493","title":"Recipe","link":"https://example.test/recipe","is_draft":true}</body></html>'
    elif case == "body_head_metadata":
        tags = body.partition("<head>")[2].partition("</head>")[0]
        tags = "<head>" + tags + "</head>"
        body = "<html><head></head><body>" + tags + "</body></html>"
    elif case == "conflicting_meta":
        body = body.replace("</head>", '<meta property="og:title" content="Another recipe"></head>')
    page, _response = _candidate_page(
        driver,
        body,
        status=404 if case == "failed_http" else 200,
        url="https://www.pinterest.com/pin/1082904672940181999/" if case == "redirected_id" else None,
        username="" if case == "no_username" else "Recetagenial",
    )
    assert (
        await driver._verify_intercepted_public_pin(
            page, title="Recipe", link="https://example.test/recipe", account_handle="rida"
        )
        is None
    )
    if case == "no_username":
        page.context.request.get.assert_not_awaited()
    driver._verify_recent_public_pin.assert_not_awaited()


@pytest.mark.asyncio
async def test_candidate_title_normalizes_only_case_whitespace_nfc_and_truncation(interception):
    driver, _page = interception
    title = unicodedata.normalize("NFD", "Helado de pistacho fácil " + "delicioso " * 12)
    public_title = unicodedata.normalize("NFC", title[:100]).upper().replace(" ", "  ")
    link = "https://example.test/recipe?source=pin&variant=1"
    page, _response = _candidate_page(
        driver, _public_metadata(**{"og:title": public_title, "pinterestapp:source": link})
    )
    assert (
        await driver._verify_intercepted_public_pin(page, title=title, link=link, account_handle="rida")
        == "1082904672940441493"
    )


@pytest.mark.asyncio
async def test_public_candidate_read_from_old_interception_generation_is_discarded(interception):
    driver, _page = interception
    page, response = _candidate_page(driver)
    page.on, page.remove_listener = Mock(), Mock()

    async def restarted_body():
        driver._setup_pin_interception(page)
        return _public_metadata()

    response.text.side_effect = restarted_body
    assert (
        await driver._verify_intercepted_public_pin(
            page, title="Recipe", link="https://example.test/recipe", account_handle="rida"
        )
        is None
    )


@pytest.mark.asyncio
async def test_public_candidate_cancellation_propagates_without_success(interception):
    driver, _page = interception
    page, _response = _candidate_page(driver)
    page.context.request.get.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await driver._verify_intercepted_public_pin(
            page, title="Recipe", link="https://example.test/recipe", account_handle="rida"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("public_matches", [True, False])
async def test_observed_story_candidate_overrides_timeout_only_after_exact_public_proof(
    interception, monkeypatch, public_matches
):
    class UncertainPublish(RuntimeError):
        error_code = "pinterest_publish_uncertain"

    monkeypatch.setitem(
        sys.modules,
        "backend.scripts.pinterest_batch_core",
        SimpleNamespace(PinCreationError=UncertainPublish),
    )
    driver, _page = interception
    source = "https://example.test/recipe" if public_matches else "https://example.test/other-recipe"
    page, _response = _candidate_page(driver, _public_metadata(**{"pinterestapp:source": source}))
    driver._pin_create_data["pin_id"] = None
    driver._recover_draft_capacity = AsyncMock(side_effect=AssertionError("No cleanup after publication"))

    async def uncertain_upload(*_args):
        await driver._response_handler(_story_response())
        raise UncertainPublish("Publish returned no UI Pin ID")

    uploader = AsyncMock(side_effect=uncertain_upload)
    args = (
        uploader,
        page,
        Path("pin.jpg"),
        "Recipe",
        "https://example.test/recipe",
        "Description",
        "Aperitivos",
        "rida",
    )
    if public_matches:
        assert await driver._shared_pin_upload_with_capacity_recovery(*args) == ("1082904672940441493", None)
    else:
        with pytest.raises(UncertainPublish):
            await driver._shared_pin_upload_with_capacity_recovery(*args)
    uploader.assert_awaited_once()
    driver._recover_draft_capacity.assert_not_awaited()
    driver._verify_recent_public_pin.assert_not_awaited()
    page.context.request.get.assert_awaited_once()

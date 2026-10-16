"""Draft-full repair must prove recovery and preserve jobs when cleanup fails."""

from __future__ import annotations

import ast
import asyncio
import json
import re
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture(autouse=True)
def _isolated_manual_recovery_state(monkeypatch, tmp_path):
    import pinterest_automation.account_recovery as recovery_module

    monkeypatch.setattr(recovery_module, "RECOVERY_STATE_FILE", tmp_path / "account_recovery.json")


@pytest.fixture
def capacity_core(tmp_path):
    # Importing the uploader CLI initializes live circuit/log singletons. Load
    # only the helpers under test, and keep every filesystem operation in tmp.
    path = Path(__file__).resolve().parents[2] / "backend/scripts/pinterest_batch_core.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {
        "BrowserSessionLost",
        "PinCreationError",
        "PinterestDraftCapacityError",
        "PinterestPublishUnavailableError",
        "PinterestPublishUncertainError",
        "ensure_creator_draft_capacity_available",
        "turbo_create_pin",
    }
    selected = [node for node in tree.body if getattr(node, "name", "") in names]
    (tmp_path / "data").mkdir()
    namespace = {
        "re": re,
        "json": json,
        "asyncio": SimpleNamespace(sleep=AsyncMock()),
        "project_root": tmp_path,
        "shutil": shutil,
        "os": SimpleNamespace(getpid=lambda: 123),
        "random": SimpleNamespace(randint=lambda *_args: 456),
        "logger": Mock(),
        "is_browser_session_lost": lambda error: "browser has been closed" in str(error),
        "_safe_worker_id": lambda worker_id: worker_id,
        "build_pin_description": lambda post: "A recipe",
        "wait_for_upload_ready": AsyncMock(return_value=True),
        "_fill_pin_title": AsyncMock(return_value=True),
        "_fill_pin_description": AsyncMock(return_value=True),
        "fill_destination_link": AsyncMock(return_value=True),
        "select_board": AsyncMock(return_value=True),
        "link_guard_ok": AsyncMock(return_value=True),
        "_ensure_immediate_publish": AsyncMock(return_value=True),
        "_prepare_publish": AsyncMock(),
        "_PublishNetworkDiagnostics": Mock(
            return_value=SimpleNamespace(
                close=AsyncMock(), summary=Mock(return_value={}), click_started=False
            )
        ),
        "_click_publish_once": AsyncMock(),
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)  # noqa: S102
    return SimpleNamespace(**namespace)


class _CreatorPage:
    def __init__(self, text="", *, disabled=False):
        self.text = text
        self.disabled = disabled
        self.url = "https://www.pinterest.com/pin-creation-tool/"
        self.goto = AsyncMock()
        self.upload = SimpleNamespace(set_input_files=AsyncMock())
        self.wait_for_selector = AsyncMock(return_value=self.upload)
        self.evaluate = AsyncMock()
        self.keyboard = SimpleNamespace(press=AsyncMock())

    def locator(self, selector):
        if selector == "body":
            return SimpleNamespace(inner_text=AsyncMock(side_effect=lambda **_kwargs: self.text))
        present = self.disabled if "aria-disabled" in selector else False
        element = SimpleNamespace(
            count=AsyncMock(return_value=int(present)), is_visible=AsyncMock(return_value=present)
        )
        element.first = element
        return element


@pytest.fixture
def readiness_core(capacity_core):
    path = Path(__file__).resolve().parents[2] / "backend/scripts/pinterest_batch_core.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "wait_for_upload_ready"
    ]
    namespace = capacity_core.ensure_creator_draft_capacity_available.__globals__
    namespace.update({"time": time, "json": json})
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)  # noqa: S102
    return SimpleNamespace(**namespace)


@pytest.mark.asyncio
async def test_delayed_capacity_warning_interrupts_upload_readiness_poll_promptly(readiness_core):
    page = _CreatorPage()
    page.query_selector = AsyncMock(return_value=None)
    page.get_by_text = Mock(
        return_value=SimpleNamespace(first=SimpleNamespace(is_visible=AsyncMock(return_value=False)))
    )
    page.screenshot = AsyncMock()
    elapsed = 0.0

    async def poll_sleep(seconds):
        nonlocal elapsed
        elapsed += seconds
        page.text = "You have reached the limit of 50 drafts"

    namespace = readiness_core.wait_for_upload_ready.__globals__
    namespace["time"] = SimpleNamespace(time=lambda: elapsed)
    sleep = AsyncMock(side_effect=poll_sleep)
    namespace["asyncio"] = SimpleNamespace(sleep=sleep)
    with pytest.raises(readiness_core.PinterestDraftCapacityError):
        await readiness_core.wait_for_upload_ready(page, "worker-r1", timeout_seconds=120)
    assert elapsed == 2.0
    sleep.assert_awaited_once_with(2)
    page.screenshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_ordinary_upload_progress_still_returns_ready(readiness_core):
    page = _CreatorPage()
    title = object()
    title_ready = False
    page.query_selector = AsyncMock(side_effect=lambda _selector: title if title_ready else None)
    page.get_by_text = Mock(
        return_value=SimpleNamespace(first=SimpleNamespace(is_visible=AsyncMock(return_value=False)))
    )
    elapsed = 0.0

    async def poll_sleep(seconds):
        nonlocal elapsed, title_ready
        elapsed += seconds
        title_ready = True

    namespace = readiness_core.wait_for_upload_ready.__globals__
    namespace["time"] = SimpleNamespace(time=lambda: elapsed)
    sleep = AsyncMock(side_effect=poll_sleep)
    namespace["asyncio"] = SimpleNamespace(sleep=sleep)
    assert await readiness_core.wait_for_upload_ready(page, "worker-r1", timeout_seconds=120) is True
    assert elapsed == 2.0
    sleep.assert_awaited_once_with(2)


@pytest.mark.asyncio
async def test_lost_browser_during_upload_readiness_is_not_swallowed(readiness_core):
    page = _CreatorPage()
    page.query_selector = AsyncMock(side_effect=RuntimeError("browser has been closed"))
    with pytest.raises(readiness_core.BrowserSessionLost):
        await readiness_core.wait_for_upload_ready(page, "worker-r1", timeout_seconds=120)
    readiness_core.asyncio.sleep.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "warning",
    [
        "You have reached the limit of 50 drafts",
        "You've reached your draft limit. Delete a draft to continue.",
        "Has alcanzado el límite de 50 borradores",
        "You have reached the limit of 50 Pin drafts",
    ],
)
async def test_visible_capacity_warning_is_specific_error(capacity_core, warning):
    with pytest.raises(capacity_core.PinterestDraftCapacityError, match="draft capacity reached") as exc:
        await capacity_core.ensure_creator_draft_capacity_available(_CreatorPage(warning), "worker-r1")
    assert exc.value.error_code == "pinterest_draft_capacity"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "disabled"),
    [
        ("Create Pin", True),
        ("Pin drafts (50)", False),
        ("You can save up to 50 drafts", False),
        ("Pin drafts (49)", True),
        ("You have reached the daily publish limit", True),
    ],
)
async def test_other_disabled_or_informational_states_are_not_draft_capacity(capacity_core, text, disabled):
    await capacity_core.ensure_creator_draft_capacity_available(
        _CreatorPage(text, disabled=disabled), "worker-r1"
    )


@pytest.mark.asyncio
async def test_full_count_and_disabled_creator_identify_draft_capacity(capacity_core):
    with pytest.raises(capacity_core.PinterestDraftCapacityError):
        await capacity_core.ensure_creator_draft_capacity_available(
            _CreatorPage("Pin drafts (50)", disabled=True), "worker-r1"
        )


@pytest.mark.asyncio
async def test_lost_session_is_not_swallowed_by_capacity_detection(capacity_core):
    page = SimpleNamespace(
        locator=lambda _selector: SimpleNamespace(
            inner_text=AsyncMock(side_effect=RuntimeError("browser has been closed"))
        )
    )
    with pytest.raises(capacity_core.BrowserSessionLost):
        await capacity_core.ensure_creator_draft_capacity_available(page, "worker-r1")


@pytest.mark.asyncio
async def test_known_capacity_defers_before_even_hanging_recovery_is_awaited(
    capacity_core, monkeypatch, tmp_path
):
    page = _CreatorPage("You have reached the limit of 50 drafts", disabled=True)

    async def hang_forever(*_args, **_kwargs):
        await asyncio.Event().wait()

    recovery = AsyncMock(side_effect=hang_forever)
    monkeypatch.setitem(
        sys.modules,
        "scripts.ops.clear_pinterest_drafts",
        SimpleNamespace(clear_drafts_for_page=recovery),
    )
    image = tmp_path / "recipe.jpg"
    image.write_bytes(b"test image")
    with pytest.raises(capacity_core.PinterestDraftCapacityError):
        await asyncio.wait_for(
            capacity_core.turbo_create_pin(
                page, {"title": "Recipe", "slug": "recipe"}, image, "Chocolate", "worker-r1"
            ),
            timeout=1.0,
        )
    recovery.assert_not_awaited()
    page.wait_for_selector.assert_not_awaited()
    page.upload.set_input_files.assert_not_awaited()
    capacity_core._fill_pin_title.assert_not_awaited()
    capacity_core.select_board.assert_not_awaited()
    page.keyboard.press.assert_not_awaited()
    assert image.exists()
    assert list((tmp_path / "data").iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["Pin drafts (49)", "You can save up to 50 drafts"])
async def test_ordinary_editor_or_informational_limit_proceeds_without_draft_purge(
    capacity_core, monkeypatch, tmp_path, text
):
    page = _CreatorPage(text, disabled=True)
    recovery = AsyncMock(side_effect=AssertionError("ordinary editor state must never purge drafts"))
    monkeypatch.setitem(
        sys.modules,
        "scripts.ops.clear_pinterest_drafts",
        SimpleNamespace(clear_drafts_for_page=recovery),
    )
    # End this mock flow at board selection after proving upload/editor access.
    capacity_core.select_board.return_value = False
    image = tmp_path / "recipe.jpg"
    image.write_bytes(b"test image")
    with pytest.raises(capacity_core.PinCreationError, match="board selection failed"):
        await capacity_core.turbo_create_pin(
            page, {"title": "Recipe", "slug": "recipe"}, image, "Chocolate", "worker-r1"
        )
    page.upload.set_input_files.assert_awaited_once()
    capacity_core.wait_for_upload_ready.assert_awaited_once()
    capacity_core._fill_pin_title.assert_awaited_once()
    capacity_core._fill_pin_description.assert_awaited_once()
    recovery.assert_not_awaited()


@pytest.mark.asyncio
async def test_capacity_appearing_after_upload_prevents_field_filling(capacity_core, tmp_path):
    page = _CreatorPage()

    async def upload_ready(*_args):
        page.text = "You have reached the limit of 50 drafts"
        return True

    capacity_core.wait_for_upload_ready.side_effect = upload_ready
    image = tmp_path / "recipe.jpg"
    image.write_bytes(b"test image")
    with pytest.raises(capacity_core.PinterestDraftCapacityError):
        await capacity_core.turbo_create_pin(
            page, {"title": "Recipe", "slug": "recipe"}, image, "Chocolate", "worker-r1"
        )
    page.upload.set_input_files.assert_awaited_once()
    capacity_core._fill_pin_title.assert_not_awaited()
    capacity_core.select_board.assert_not_awaited()
    page.keyboard.press.assert_not_awaited()


@pytest.mark.asyncio
async def test_capacity_appearing_after_board_selection_prevents_publish(capacity_core, tmp_path):
    page = _CreatorPage()

    async def board_selected(*_args):
        page.text = "You have reached the limit of 50 drafts"
        return True

    capacity_core.select_board.side_effect = board_selected
    image = tmp_path / "recipe.jpg"
    image.write_bytes(b"test image")
    with pytest.raises(capacity_core.PinterestDraftCapacityError):
        await capacity_core.turbo_create_pin(
            page, {"title": "Recipe", "slug": "recipe"}, image, "Chocolate", "worker-r1"
        )
    capacity_core.select_board.assert_awaited_once()
    page.evaluate.assert_not_awaited()
    page.keyboard.press.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked_stage", ["title", "schedule", "autosave"])
async def test_unverified_editor_preparation_defers_before_publish_or_diagnostics(
    capacity_core, tmp_path, blocked_stage
):
    page = _CreatorPage()
    if blocked_stage == "title":
        capacity_core._fill_pin_title.return_value = False
    elif blocked_stage == "schedule":
        capacity_core._ensure_immediate_publish.return_value = False
    else:
        capacity_core._prepare_publish.side_effect = capacity_core.PinterestPublishUnavailableError(
            "Autosave never settled"
        )
    image = tmp_path / "recipe.jpg"
    image.write_bytes(b"test image")

    with pytest.raises(capacity_core.PinterestPublishUnavailableError) as caught:
        await capacity_core.turbo_create_pin(
            page, {"title": "Recipe", "slug": "recipe"}, image, "Chocolate", "worker-r1"
        )

    assert caught.value.error_code == "pinterest_publish_unavailable"
    assert getattr(caught.value, "uncertain", False) is False
    capacity_core._click_publish_once.assert_not_awaited()
    capacity_core._PublishNetworkDiagnostics.assert_not_called()
    assert image.exists() and list((tmp_path / "data").iterdir()) == []


@pytest.fixture
def driver_harness(capacity_core, monkeypatch, tmp_path):
    import pinterest_automation.pinterest_driver as driver_module

    shared_upload = AsyncMock()
    monkeypatch.setitem(
        sys.modules,
        "backend.scripts.pinterest_batch_core",
        SimpleNamespace(
            PinCreationError=capacity_core.PinCreationError,
            PinterestDraftCapacityError=capacity_core.PinterestDraftCapacityError,
            BrowserSessionLost=capacity_core.BrowserSessionLost,
            ensure_creator_draft_capacity_available=capacity_core.ensure_creator_draft_capacity_available,
            create_pin_from_fields=shared_upload,
        ),
    )
    cleanup = AsyncMock(return_value={"ok": False, "creator_ready": False, "error": "delete unavailable"})
    monkeypatch.setitem(
        sys.modules,
        "scripts.ops.clear_pinterest_drafts",
        SimpleNamespace(clear_drafts_for_page_verified=cleanup),
    )
    limiter = Mock(can_execute=Mock(return_value=True))
    monkeypatch.setattr(driver_module, "get_rate_limiter", lambda **_kwargs: limiter)
    monkeypatch.setattr(driver_module, "resolve_account_board_name", lambda board, handle: board)
    driver = object.__new__(driver_module.PinterestDriver)
    page = _CreatorPage()
    page.remove_listener = Mock()
    driver.account_handle = "blocked"
    driver.config = SimpleNamespace(default_board="Chocolate", accounts={})
    driver.circuit = Mock(can_execute=Mock(return_value=True))
    driver._acquire_session = AsyncMock(return_value=SimpleNamespace(page=page))
    driver._response_handler = Mock()

    def interception_setup(_page):
        driver._pin_create_event = asyncio.Event()
        driver._pin_create_data = {}

    driver._setup_pin_interception = Mock(side_effect=interception_setup)
    driver._pin_create_event = asyncio.Event()
    driver._pin_create_data = {}
    driver.info = Mock()
    driver.warning = Mock()
    driver._verify_recent_public_pin = AsyncMock(return_value=None)
    image = tmp_path / "recipe.jpg"
    image.write_bytes(b"test image")
    return SimpleNamespace(
        driver=driver,
        page=page,
        image=image,
        upload=shared_upload,
        cleanup=cleanup,
        limiter=limiter,
        core=capacity_core,
    )


@pytest.mark.asyncio
async def test_driver_cleanup_failure_returns_capacity_code_without_legacy_retry_or_circuit_failure(
    driver_harness,
):
    harness = driver_harness
    harness.upload.side_effect = harness.core.PinterestDraftCapacityError("draft capacity")
    result = await harness.driver.create_pin(
        str(harness.image), "Recipe", "Recipe description", board_name="Chocolate"
    )
    assert result == {
        "success": False,
        "error": "draft capacity",
        "error_code": "pinterest_draft_capacity",
        "draft_cleanup": {"ok": False, "creator_ready": False, "error": "delete unavailable"},
    }
    harness.cleanup.assert_awaited_once_with(harness.page, account_name="blocked", timeout_seconds=90)
    harness.upload.assert_awaited_once()
    harness.page.goto.assert_not_awaited()
    harness.driver.circuit.record_failure.assert_not_called()
    harness.limiter.record_failure.assert_not_called()
    harness.limiter.record_execution.assert_not_called()
    harness.driver.circuit.can_execute.assert_called_once_with("pin_upload:blocked")
    harness.limiter.can_execute.assert_called_once_with("pin_upload:direct:blocked")
    assert harness.image.exists()


def _verified_cleanup_report(**overrides):
    return {
        "ok": True,
        "deleted": 50,
        "initial_count": 50,
        "remaining_count": 0,
        "creator_ready": True,
        "error": None,
        **overrides,
    }


@pytest.mark.asyncio
async def test_driver_repairs_draft_capacity_then_publishes_identical_payload_in_same_session(driver_harness):
    harness = driver_harness
    pin_id = "1148488342519617703"
    harness.upload.side_effect = [harness.core.PinterestDraftCapacityError("draft full"), pin_id]
    report = _verified_cleanup_report()
    harness.cleanup.return_value = report
    result = await harness.driver.create_pin(
        str(harness.image),
        "Recipe",
        "Recipe description",
        link="https://recetagenial.com/recipe",
        board_name="Chocolate",
        domain_handle="recetagenial",
    )
    assert result == {
        "success": True,
        "pin_id": pin_id,
        "pin_url": f"https://www.pinterest.com/pin/{pin_id}/",
        "method": "shared-core",
        "draft_cleanup": report,
    }
    assert harness.upload.await_count == 2
    assert harness.upload.await_args_list[0] == harness.upload.await_args_list[1]
    assert harness.upload.await_args_list[0].args == (
        harness.page,
        harness.image,
        "Recipe",
        "https://recetagenial.com/recipe",
        "Recipe description",
        "Chocolate",
        "driver-blocked",
    )
    harness.driver._acquire_session.assert_awaited_once_with("blocked")
    harness.page.remove_listener.assert_called_once_with("response", harness.driver._response_handler)
    assert harness.driver._setup_pin_interception.call_count == 2
    harness.driver.circuit.record_success.assert_called_once_with("pin_upload:blocked")
    harness.limiter.record_execution.assert_called_once_with("pin_upload:recetagenial:blocked")
    harness.driver.circuit.record_failure.assert_not_called()
    harness.page.goto.assert_not_awaited()
    assert harness.image.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "report",
    [
        _verified_cleanup_report(ok=False),
        _verified_cleanup_report(creator_ready=False),
        _verified_cleanup_report(remaining_count=1),
        _verified_cleanup_report(remaining_count=None),
        _verified_cleanup_report(deleted=-1),
        _verified_cleanup_report(deleted=True),
        None,
    ],
)
async def test_driver_requires_verified_empty_creator_before_retrying(driver_harness, report):
    harness = driver_harness
    harness.upload.side_effect = harness.core.PinterestDraftCapacityError("draft full")
    harness.cleanup.return_value = report
    result = await harness.driver.create_pin(str(harness.image), "Recipe", "Recipe description")
    assert result["success"] is False
    assert result["error_code"] == "pinterest_draft_capacity"
    assert result["draft_cleanup"]["ok"] is False
    harness.upload.assert_awaited_once()
    harness.driver.circuit.record_failure.assert_not_called()
    harness.limiter.record_failure.assert_not_called()
    harness.page.goto.assert_not_awaited()
    assert harness.image.exists()


@pytest.mark.asyncio
async def test_driver_caps_capacity_repair_to_one_retry_and_preserves_failed_job(driver_harness):
    harness = driver_harness
    harness.upload.side_effect = harness.core.PinterestDraftCapacityError("still full")
    harness.cleanup.return_value = _verified_cleanup_report()
    result = await harness.driver.create_pin(str(harness.image), "Recipe", "Recipe description")
    assert result["success"] is False
    assert result["error_code"] == "pinterest_draft_capacity"
    assert harness.upload.await_count == 2
    harness.cleanup.assert_awaited_once()
    harness.page.goto.assert_not_awaited()
    harness.driver.circuit.record_failure.assert_not_called()
    assert harness.image.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("proof", [None, "123", "https://other.invalid/pin/1148488342519617703/"])
async def test_driver_never_falls_back_after_repaired_upload_without_valid_pin_id(driver_harness, proof):
    harness = driver_harness
    harness.upload.side_effect = [harness.core.PinterestDraftCapacityError("draft full"), proof]
    harness.cleanup.return_value = _verified_cleanup_report()
    result = await harness.driver.create_pin(str(harness.image), "Recipe", "Recipe description")
    assert result["success"] is False
    assert result["uncertain"] is True
    assert result["draft_cleanup"]["ok"] is True
    assert harness.upload.await_count == 2
    harness.page.goto.assert_not_awaited()
    harness.limiter.record_execution.assert_not_called()
    harness.driver.circuit.record_success.assert_not_called()
    assert harness.image.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("public_verified", [True, False])
async def test_driver_requires_public_proof_before_candidate_overrides_capacity_error(
    driver_harness, public_verified
):
    harness = driver_harness
    pin_id = "1148488342519617703"

    async def upload_with_boundary_response(*_args):
        harness.driver._pin_create_data["pin_id"] = pin_id
        raise harness.core.PinterestDraftCapacityError("late draft warning")

    harness.upload.side_effect = upload_with_boundary_response
    harness.driver._verify_intercepted_public_pin = AsyncMock(
        return_value=pin_id if public_verified else None
    )
    result = await harness.driver.create_pin(
        str(harness.image), "Recipe", "Recipe description", link="https://recetagenial.com/recipe"
    )
    assert result["success"] is public_verified
    if public_verified:
        assert result["pin_id"] == pin_id
        harness.cleanup.assert_not_awaited()
    else:
        assert result["error_code"] == "pinterest_draft_capacity"
        harness.cleanup.assert_awaited_once()
        harness.limiter.record_execution.assert_not_called()
        harness.driver.circuit.record_success.assert_not_called()
        assert harness.image.exists()
    harness.driver._verify_intercepted_public_pin.assert_awaited_once_with(
        harness.page,
        title="Recipe",
        link="https://recetagenial.com/recipe",
        account_handle="blocked",
        description="Recipe description",
    )
    harness.driver._verify_recent_public_pin.assert_not_awaited()
    harness.upload.assert_awaited_once()


@pytest.mark.asyncio
async def test_driver_ignores_cleanup_pinresource_response_when_retrying_original_upload(driver_harness):
    harness = driver_harness
    expected_id = "1148488342519617703"
    deleted_draft_id = "1148488342519609525"
    harness.upload.side_effect = [harness.core.PinterestDraftCapacityError("draft full"), expected_id]

    async def cleanup_with_draft_resource(*_args, **_kwargs):
        # A stale event during deletion must be cleared before posting the pin.
        harness.driver._pin_create_data["pin_id"] = deleted_draft_id
        harness.driver._pin_create_event.set()
        return _verified_cleanup_report()

    harness.cleanup.side_effect = cleanup_with_draft_resource
    result = await harness.driver.create_pin(str(harness.image), "Recipe", "Recipe description")
    assert result["success"] is True
    assert result["pin_id"] == expected_id
    assert harness.upload.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("uploader_raises", [False, True])
async def test_unverified_candidate_never_triggers_native_republish(driver_harness, uploader_raises):
    harness = driver_harness

    async def upload_with_candidate(*_args):
        harness.driver._pin_create_data["pin_id"] = "1148488342519617703"
        harness.driver._pin_create_event.set()
        if uploader_raises:
            raise harness.core.PinCreationError("publish confirmation failed")
        return None

    harness.upload.side_effect = upload_with_candidate
    result = await harness.driver.create_pin(
        str(harness.image), "Recipe", "Recipe description", link="https://recetagenial.com/recipe"
    )
    assert result["success"] is False
    assert result["uncertain"] is True
    harness.page.goto.assert_not_awaited()
    harness.cleanup.assert_not_awaited()
    harness.upload.assert_awaited_once()
    harness.limiter.record_execution.assert_not_called()
    assert harness.image.exists()


@pytest.mark.asyncio
async def test_repaired_creator_failure_preserves_uncertainty_without_native_republish(driver_harness):
    harness = driver_harness
    harness.upload.side_effect = [
        harness.core.PinterestDraftCapacityError("draft full"),
        harness.core.PinCreationError("publish confirmation failed"),
    ]
    harness.cleanup.return_value = _verified_cleanup_report()
    result = await harness.driver.create_pin(str(harness.image), "Recipe", "Recipe description")
    assert result["success"] is False
    assert result["uncertain"] is True
    assert result["draft_cleanup"]["ok"] is True
    assert harness.upload.await_count == 2
    harness.page.goto.assert_not_awaited()
    harness.limiter.record_execution.assert_not_called()
    assert harness.image.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["pinterest_publish_unavailable", "pinterest_publish_uncertain"])
async def test_publish_action_failure_preserves_typed_metadata_without_native_fallback(driver_harness, code):
    harness = driver_harness
    error = harness.core.PinCreationError("publish could not be verified")
    error.error_code = code
    error.uncertain = code == "pinterest_publish_uncertain"
    error.publish_diagnostics = {
        "click_started": error.uncertain,
        "mutating_requests": int(error.uncertain),
        "rejected_responses": 0,
        "requests": [],
    }
    harness.upload.side_effect = error

    result = await harness.driver.create_pin(str(harness.image), "Recipe", "Description")

    assert result["success"] is False
    assert result["error_code"] == code
    assert result["uncertain"] is error.uncertain
    assert result["publish_diagnostics"] == error.publish_diagnostics
    harness.upload.assert_awaited_once()
    harness.page.goto.assert_not_awaited()
    harness.cleanup.assert_not_awaited()
    harness.driver._verify_recent_public_pin.assert_not_awaited()
    harness.limiter.record_execution.assert_not_called()
    harness.limiter.record_failure.assert_not_called()
    harness.driver.circuit.record_success.assert_not_called()
    harness.driver.circuit.record_failure.assert_not_called()
    assert harness.image.exists()


@pytest.mark.asyncio
async def test_cleanup_timeout_is_capacity_deferral_without_consuming_upload_failure(driver_harness):
    harness = driver_harness
    harness.upload.side_effect = harness.core.PinterestDraftCapacityError("draft full")
    harness.cleanup.side_effect = TimeoutError("draft delete confirmation timed out")
    result = await harness.driver.create_pin(str(harness.image), "Recipe", "Recipe description")
    assert result["error_code"] == "pinterest_draft_capacity"
    assert result["draft_cleanup"]["ok"] is False
    harness.upload.assert_awaited_once()
    harness.driver.circuit.record_failure.assert_not_called()
    harness.limiter.record_failure.assert_not_called()
    assert harness.image.exists()


@pytest.mark.asyncio
async def test_driver_cancellation_drains_cleanup_and_never_retries_a_closed_session(driver_harness):
    harness = driver_harness
    harness.upload.side_effect = harness.core.PinterestDraftCapacityError("draft full")
    started = asyncio.Event()
    finished = asyncio.Event()

    async def pending_cleanup(*_args, **_kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()

    harness.cleanup.side_effect = pending_cleanup
    task = asyncio.create_task(harness.driver.create_pin(str(harness.image), "Recipe", "Recipe description"))
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()
    harness.upload.assert_awaited_once()
    assert harness.image.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["Pin drafts (49)", "You can save up to 50 drafts", "Loading..."])
async def test_native_recovery_does_not_delete_drafts_for_loading_or_information(driver_harness, text):
    harness = driver_harness
    harness.page.text = text
    harness.page.disabled = True
    assert await harness.driver._clear_draft_limit_if_needed(harness.page) == 0
    harness.cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_capacity_deferral_preserves_longer_account_and_job_deadlines(monkeypatch):
    import pinterest_automation.supervisor as supervisor_module

    monkeypatch.setattr(supervisor_module, "time", SimpleNamespace(time=lambda: 1000.0))
    supervisor = object.__new__(supervisor_module.AutonomousSupervisor)
    supervisor.queue = SimpleNamespace(release_async=AsyncMock(), retry_or_fail_async=AsyncMock())
    supervisor._account_cooldowns = {"blocked": 3000.0, "healthy": 4000.0}
    job = SimpleNamespace(id="blocked-pin", next_retry_at=5000.0)
    await supervisor._defer_draft_capacity_job(job, "blocked", "draft full")
    supervisor.queue.release_async.assert_awaited_once_with("blocked-pin", delay_seconds=4000.0)
    supervisor.queue.retry_or_fail_async.assert_not_awaited()
    assert supervisor._account_cooldowns == {"blocked": 5000.0, "healthy": 4000.0}


@pytest.mark.asyncio
async def test_worker_capacity_deferral_preserves_retries_images_and_other_account_progress(
    monkeypatch, tmp_path
):
    import pinterest_automation.job_queue as queue_module
    import pinterest_automation.supervisor as supervisor_module
    from pinterest_automation.job_queue import Job, JobQueue

    for name in ("QUEUE_FILE", "DLQ_FILE", "COMPLETED_FILE"):
        monkeypatch.setattr(queue_module, name, tmp_path / f"{name}.absent.json")
    configured = SimpleNamespace(
        accounts={"blocked": SimpleNamespace(), "healthy": SimpleNamespace()},
        default_board="Chocolate",
        cross_save_enabled=False,
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

    class Driver:
        ensure_logged_in = AsyncMock(return_value=True)
        close = AsyncMock()

        async def create_pin(self, **kwargs):
            if kwargs["account_handle"] == "blocked":
                return {
                    "success": False,
                    "error": "Pinterest creator draft capacity reached",
                    "error_code": "pinterest_draft_capacity",
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
    assert blocked.next_retry_at >= started + 900
    assert blocked.error_log == []
    assert Path(blocked.payload["image_path"]).exists()
    assert queue.get_stats()["dlq_size"] == 0
    assert queue.get_job_outcome("healthy")["state"] == "completed"
    assert supervisor._account_cooldowns["blocked"] >= started + 900
    assert "healthy" not in supervisor._account_cooldowns
    limiter.record_failure.assert_not_called()


@pytest.mark.asyncio
async def test_supervisor_completes_original_job_after_account_locked_verified_draft_repair(
    driver_harness, monkeypatch, tmp_path
):
    import pinterest_automation.job_queue as queue_module
    import pinterest_automation.supervisor as supervisor_module
    from pinterest_automation.job_queue import Job, JobQueue

    harness = driver_harness
    for name in ("QUEUE_FILE", "DLQ_FILE", "COMPLETED_FILE"):
        monkeypatch.setattr(queue_module, name, tmp_path / f"{name}.absent.json")
    configured = SimpleNamespace(
        accounts={"blocked": SimpleNamespace()},
        default_board="Chocolate",
        cross_save_enabled=False,
    )
    monkeypatch.setattr(queue_module, "get_config", lambda: configured)
    monkeypatch.setattr(supervisor_module, "get_config", lambda: configured)
    monkeypatch.setenv("PINTEREST_DEFAULT_ACCOUNT_HANDLE", "blocked")
    queue = JobQueue(db_file=tmp_path / "repair-jobs.db")
    queue.enqueue(
        Job(
            id="same-original-job",
            attempt=2,
            max_attempts=3,
            payload={
                "account_handle": "blocked",
                "domain_handle": "test_domain",
                "image_path": str(harness.image),
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
    harness.driver.ensure_logged_in = AsyncMock(return_value=True)
    harness.driver.close = AsyncMock()
    monkeypatch.setattr(supervisor_module, "PinterestDriver", lambda: harness.driver)

    async def cleanup_under_account_lock(*_args, **_kwargs):
        assert supervisor._account_locks["blocked"].locked()
        current = queue.get_job_outcome("same-original-job")
        assert current["state"] == "processing"
        return _verified_cleanup_report()

    calls = 0

    async def original_job_upload(*_args):
        nonlocal calls
        calls += 1
        assert supervisor._account_locks["blocked"].locked()
        if calls == 1:
            raise harness.core.PinterestDraftCapacityError("draft full")
        supervisor._shutdown_event.set()
        return "1148488342519617703"

    harness.cleanup.side_effect = cleanup_under_account_lock
    harness.upload.side_effect = original_job_upload
    worker_asyncio = SimpleNamespace(
        **{name: getattr(asyncio, name) for name in dir(asyncio) if not name.startswith("__")}
    )
    worker_asyncio.sleep = AsyncMock()
    monkeypatch.setattr(supervisor_module, "asyncio", worker_asyncio)
    await asyncio.wait_for(supervisor._queue_worker(1), timeout=5)
    outcome = queue.get_job_outcome("same-original-job")
    assert outcome["state"] == "completed"
    assert outcome["result"]["pin_id"] == "1148488342519617703"
    assert supervisor.is_verified_upload(outcome["result"]) is True
    with queue._conn() as conn:
        completed = conn.execute("SELECT job_json FROM completed_log").fetchall()
        assert len(completed) == 1
        persisted = json.loads(completed[0]["job_json"])
        assert persisted["id"] == "same-original-job"
        # The one successful lease increments 2 to 3. Draft repair never
        # releases/re-enqueues the job or consumes an additional attempt.
        assert persisted["attempt"] == 3
        assert persisted["error_log"] == []
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    assert queue.get_stats()["dlq_size"] == 0
    assert calls == 2
    harness.cleanup.assert_awaited_once()
    assert harness.upload.await_args_list[0] == harness.upload.await_args_list[1]
    limiter.record_failure.assert_not_called()
    harness.limiter.record_execution.assert_called_once_with("pin_upload:test_domain:blocked")
    assert supervisor._account_locks["blocked"].locked() is False


@pytest.mark.asyncio
async def test_other_account_publishes_while_blocked_account_repairs_drafts(
    driver_harness, monkeypatch, tmp_path
):
    import pinterest_automation.job_queue as queue_module
    import pinterest_automation.supervisor as supervisor_module
    from pinterest_automation.job_queue import Job, JobQueue

    harness = driver_harness
    for name in ("QUEUE_FILE", "DLQ_FILE", "COMPLETED_FILE"):
        monkeypatch.setattr(queue_module, name, tmp_path / f"{name}.absent.json")
    configured = SimpleNamespace(
        accounts={"blocked": SimpleNamespace(), "healthy": SimpleNamespace()},
        default_board="Chocolate",
        cross_save_enabled=False,
    )
    monkeypatch.setattr(queue_module, "get_config", lambda: configured)
    monkeypatch.setattr(supervisor_module, "get_config", lambda: configured)
    queue = JobQueue(db_file=tmp_path / "parallel-repair-jobs.db")
    for account in ("blocked", "healthy"):
        image = harness.image if account == "blocked" else tmp_path / "healthy.jpg"
        image.write_bytes(b"test image")
        queue.enqueue(
            Job(
                id=account,
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
    limiter = SimpleNamespace(can_execute=Mock(return_value=True), wait_async=AsyncMock())
    monkeypatch.setattr(supervisor_module, "get_rate_limiter", lambda **_kwargs: limiter)
    supervisor = object.__new__(supervisor_module.AutonomousSupervisor)
    supervisor.config = SimpleNamespace(worker_count=2, watch_interval_seconds=0.001)
    supervisor.queue = queue
    supervisor.health = SimpleNamespace(get_snapshot=lambda: SimpleNamespace(checks={}))
    supervisor._shutdown_event = asyncio.Event()
    supervisor._session_generation = 0
    supervisor._account_locks = {}
    supervisor._lease = SimpleNamespace(started_at=time.time())
    supervisor._log_success = Mock()
    supervisor._enqueue_cross_save = AsyncMock()
    cleanup_started = asyncio.Event()
    healthy_published = asyncio.Event()
    completed = set()
    harness.driver.ensure_logged_in = AsyncMock(return_value=True)
    harness.driver.close = AsyncMock()

    async def cleanup_while_other_account_publishes(*_args, **_kwargs):
        assert supervisor._account_locks["blocked"].locked()
        cleanup_started.set()
        await asyncio.wait_for(healthy_published.wait(), timeout=2)
        return _verified_cleanup_report()

    calls = 0

    async def blocked_upload(*_args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise harness.core.PinterestDraftCapacityError("draft full")
        return "1148488342519617703"

    class AccountDriver:
        ensure_logged_in = AsyncMock(return_value=True)
        close = AsyncMock()

        async def create_pin(self, **kwargs):
            account = kwargs["account_handle"]
            if account == "blocked":
                result = await harness.driver.create_pin(**kwargs)
            else:
                await asyncio.wait_for(cleanup_started.wait(), timeout=2)
                assert supervisor._account_locks["blocked"].locked()
                assert supervisor._account_locks["healthy"].locked()
                healthy_published.set()
                result = {"success": True, "pin_id": "1082904672940181452"}
            completed.add(account)
            if completed == {"blocked", "healthy"}:
                supervisor._shutdown_event.set()
            return result

    harness.cleanup.side_effect = cleanup_while_other_account_publishes
    harness.upload.side_effect = blocked_upload
    monkeypatch.setattr(supervisor_module, "PinterestDriver", AccountDriver)
    worker_asyncio = SimpleNamespace(
        **{name: getattr(asyncio, name) for name in dir(asyncio) if not name.startswith("__")}
    )

    # Keep workers yielding while they wait for the other account, without the
    # production two-second post-upload pause.
    async def fast_sleep(seconds):
        await asyncio.sleep(0.001 if seconds else 0)

    worker_asyncio.sleep = fast_sleep
    monkeypatch.setattr(supervisor_module, "asyncio", worker_asyncio)
    await asyncio.wait_for(
        asyncio.gather(supervisor._queue_worker(1), supervisor._queue_worker(2)), timeout=5
    )
    assert queue.get_job_outcome("blocked")["state"] == "completed"
    assert queue.get_job_outcome("healthy")["state"] == "completed"
    assert queue.get_stats()["dlq_size"] == 0
    harness.cleanup.assert_awaited_once()
    assert calls == 2

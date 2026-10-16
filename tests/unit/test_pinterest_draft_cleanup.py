"""Exercise cleanup against an isolated, rerendering creator DOM.

No Pinterest connection, persistent profile, queue, or runtime state is used.
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import urlencode

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright


@pytest.fixture
def cleanup():
    path = Path(__file__).resolve().parents[2] / "scripts/ops/clear_pinterest_drafts.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    helpers = []
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name not in {"aggressive_clear", "clear_all_accounts_drafts", "main"}:
                helpers.append(node)
        elif isinstance(node, ast.Assign):
            if all(isinstance(target, ast.Name) and target.id.isupper() for target in node.targets):
                helpers.append(node)
    namespace = {"asyncio": asyncio, "re": re, "logger": Mock()}
    exec(compile(ast.Module(body=helpers, type_ignores=[]), str(path), "exec"), namespace)  # noqa: S102
    return SimpleNamespace(**namespace)


@pytest_asyncio.fixture
async def creator_page():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        # State remains in the document across helper goto calls, simulating
        # server-persisted deletes without any network request.
        async def local_goto(*_args, **_kwargs):
            return None

        page.goto = local_goto
        try:
            yield page
        finally:
            await context.close()
            await browser.close()


async def set_creator(page, **options):
    defaults = {
        "count": 50,
        "batch": 50,
        "stuck": False,
        "warning": False,
        "spanish": False,
        "individual": False,
        "empty_disabled": False,
        "dialog_draft": True,
    }
    defaults.update(options)
    await page.set_content(
        """<html><body>
        <button id="unrelated-delete" onclick="window.wrongDeletes++">Delete</button>
        <div id="sidebar"></div><div id="dialogs"></div>
        <input id="upload" type="file" hidden>
        <script>
        window.opts = OPTIONS;
        window.remaining = opts.count;
        window.checked = false;
        window.closeClicks = 0;
        window.wrongDeletes = 0;
        window.confirmations = 0;
        window.selectionClicks = 0;
        function closeSidebar() { closeClicks++; sidebar.innerHTML = ''; }
        function openDelete() {
          const title = opts.dialog_draft ? (opts.spanish ? 'Eliminar borradores?' : 'Delete these drafts?') : 'Delete board?';
          const action = opts.spanish ? 'Eliminar' : 'Delete';
          dialogs.innerHTML = '<div role="dialog"><h2>'+title+'</h2><button onclick="confirmDelete()">'+action+'</button><button>Cancel</button></div>';
        }
        function confirmDelete() {
          confirmations++;
          if (!opts.stuck) remaining -= Math.min(remaining, opts.individual ? 1 : opts.batch);
          checked = false;
          dialogs.innerHTML = '';
          render();
        }
        function menu() {
          dialogs.innerHTML = '<div role="menu"><button onclick="openDelete()">'+(opts.spanish ? 'Eliminar' : 'Delete')+'</button></div>';
        }
        function render() {
          const name = opts.spanish ? 'Borradores de pines' : 'Pin drafts';
          let controls = '';
          if (remaining > 0) {
            if (opts.individual) controls = '<button aria-label="Pin draft actions" onclick="menu()">...</button>';
            else controls = '<input type="checkbox" id="storyboard-drafts-sidebar-bulk-select-checkbox" '+(checked?'checked':'')+' onchange="window.checked=this.checked;selectionClicks++;render()"><label for="storyboard-drafts-sidebar-bulk-select-checkbox">Select all</label>';
            if (checked) controls += '<button onclick="openDelete()">'+(opts.spanish?'Eliminar':'Delete')+'</button>';
          }
          sidebar.innerHTML = '<button data-test-id="collapse-drafts-sidebar-button" aria-label="Close drafts sidebar" onclick="closeSidebar()">x</button><h2>'+name+' ('+remaining+')</h2><button '+(remaining>=50||opts.empty_disabled?'disabled':'')+'>Create new</button>'+controls;
          upload.disabled = remaining >= 50 || opts.empty_disabled;
          if (opts.warning && remaining > 0) sidebar.innerHTML += '<p>You have reached the limit of 50 drafts</p>';
        }
        render();
        </script></body></html>""".replace("OPTIONS", json.dumps(defaults))
    )
    # Individual fallback must expose an explicit draft drawer scope.
    if defaults["individual"]:
        await page.locator("#sidebar").evaluate("el => el.setAttribute('data-test-id', 'drafts-sidebar')")


@pytest.mark.asyncio
async def test_full_open_drawer_deletes_50_and_verifies_empty(cleanup, creator_page):
    await set_creator(creator_page, warning=True)
    result = await cleanup.clear_drafts_for_page_verified(creator_page, "account", timeout_seconds=15)
    assert result == {
        "ok": True,
        "success": True,
        "deleted": 50,
        "initial_count": 50,
        "remaining_count": 0,
        "remaining": 0,
        "creator_ready": True,
        "error": None,
    }
    assert await creator_page.evaluate("closeClicks") == 0
    assert await creator_page.evaluate("wrongDeletes") == 0
    assert await creator_page.evaluate("confirmations") == 1


@pytest.mark.asyncio
async def test_partial_bulk_deletions_reacquire_rerendered_drawer(cleanup, creator_page):
    await set_creator(creator_page, count=50, batch=20)
    result = await cleanup.clear_drafts_for_page_verified(creator_page, timeout_seconds=45)
    assert result["ok"] and result["deleted"] == 50, json.dumps(
        {
            "result": result,
            "dom": await creator_page.evaluate(
                "({remaining, confirmations, selectionClicks, closeClicks, checked, body: document.body.innerText})"
            ),
        }
    )
    assert await creator_page.evaluate("confirmations") == 3
    assert await creator_page.evaluate("selectionClicks") == 3


@pytest.mark.asyncio
async def test_spanish_draft_count_and_confirmation(cleanup, creator_page):
    await set_creator(creator_page, count=3, spanish=True)
    result = await cleanup.clear_drafts_for_page_verified(creator_page, timeout_seconds=15)
    assert result["ok"] and result["deleted"] == 3


@pytest.mark.asyncio
async def test_selected_bulk_checkbox_is_not_toggled_off(cleanup, creator_page):
    await set_creator(creator_page, count=3)
    await creator_page.evaluate("checked=true;render()")
    result = await cleanup.clear_drafts_for_page_verified(creator_page, timeout_seconds=15)
    assert result["ok"] and result["deleted"] == 3
    assert await creator_page.evaluate("selectionClicks") == 0


@pytest.mark.asyncio
async def test_no_progress_is_failure_not_count_of_confirmation_clicks(cleanup, creator_page):
    await set_creator(creator_page, count=50, stuck=True)
    result = await cleanup.clear_drafts_for_page_verified(creator_page, timeout_seconds=20)
    assert not result["ok"]
    assert result["deleted"] == 0 and result["remaining_count"] == 50
    assert result["error"]


@pytest.mark.asyncio
async def test_board_dialog_is_never_confirmed(cleanup, creator_page):
    await set_creator(creator_page, count=2, dialog_draft=False)
    result = await cleanup.clear_drafts_for_page_verified(creator_page, timeout_seconds=1)
    assert not result["ok"] and result["deleted"] == 0
    assert await creator_page.evaluate("confirmations") == 0
    assert await creator_page.evaluate("wrongDeletes") == 0


@pytest.mark.asyncio
async def test_missing_controls_and_count_never_mean_empty(cleanup, creator_page):
    await creator_page.set_content(
        '<aside data-test-id="drafts-sidebar"><h2>Pin drafts</h2>'
        '<button disabled>Create new</button></aside><p>Create Pin</p><input type="file">'
    )
    result = await cleanup.clear_drafts_for_page_verified(creator_page, timeout_seconds=0.7)
    assert not result["ok"] and result["remaining_count"] is None
    assert result["deleted"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("draft_title", ["No drafts yet - receta", "No hay borradores - receta"])
async def test_unrelated_empty_phrase_does_not_prove_zero_drafts(cleanup, draft_title):
    body = SimpleNamespace(inner_text=AsyncMock(return_value=f"Pin drafts\n{draft_title}\nUpload media"))
    upload = SimpleNamespace(is_enabled=AsyncMock(return_value=True))
    inputs = SimpleNamespace(count=AsyncMock(return_value=1), nth=Mock(return_value=upload))
    page = SimpleNamespace(locator=lambda selector: body if selector == "body" else inputs)

    state = await cleanup._read_draft_state(page)

    assert state["count"] is None and state["creator_ready"]


@pytest.mark.asyncio
async def test_missing_controls_with_full_count_is_explicit_failure(cleanup, creator_page):
    await creator_page.set_content("<p>Pin drafts (50)</p><p>You have reached the limit of 50 drafts</p>")
    result = await cleanup.clear_drafts_for_page_verified(creator_page, timeout_seconds=5)
    assert not result["ok"] and result["remaining_count"] == 50
    assert "no verified progress" in result["error"]


@pytest.mark.asyncio
async def test_zero_count_still_requires_creator_usable(cleanup, creator_page):
    await set_creator(creator_page, count=0, empty_disabled=True)
    result = await cleanup.clear_drafts_for_page_verified(creator_page, timeout_seconds=5)
    assert not result["ok"] and not result["creator_ready"]


@pytest.mark.asyncio
async def test_empty_creator_returns_zero_without_delete(cleanup, creator_page):
    await set_creator(creator_page, count=0)
    assert await cleanup.clear_drafts_for_page(creator_page) == 0
    assert await creator_page.evaluate("confirmations") == 0


@pytest.mark.asyncio
async def test_transient_state_read_after_delete_does_not_abort_cleanup(cleanup, creator_page):
    await set_creator(creator_page, count=3)
    namespace = cleanup.clear_drafts_for_page_verified.__globals__
    read_state = namespace["_read_draft_state"]
    failed_once = False

    async def transient_read(page):
        nonlocal failed_once
        if not failed_once and await page.evaluate("confirmations"):
            failed_once = True
            raise TimeoutError("Locator.inner_text timed out during creator navigation")
        return await read_state(page)

    namespace["_read_draft_state"] = transient_read
    result = await cleanup.clear_drafts_for_page_verified(creator_page, timeout_seconds=15)

    assert failed_once
    assert result["ok"] and result["deleted"] == 3 and result["remaining_count"] == 0
    assert await creator_page.evaluate("confirmations") == 1


@pytest.mark.asyncio
async def test_transient_navigation_timeout_retries_within_cleanup_deadline(cleanup, creator_page):
    await set_creator(creator_page, count=0)
    navigations = 0

    async def transient_navigation(*_args, **_kwargs):
        nonlocal navigations
        navigations += 1
        if navigations == 1:
            raise TimeoutError("Page.goto timed out during creator navigation")

    creator_page.goto = transient_navigation
    result = await cleanup.clear_drafts_for_page_verified(creator_page, timeout_seconds=5)

    assert result["ok"] and navigations == 3


@pytest.mark.asyncio
async def test_repeated_render_timeouts_remain_bounded_failure(cleanup):
    namespace = cleanup.clear_drafts_for_page_verified.__globals__
    read_state = AsyncMock(side_effect=TimeoutError("Locator.inner_text timed out"))
    namespace["_read_draft_state"] = read_state
    page = SimpleNamespace(
        goto=AsyncMock(return_value=None), url="https://www.pinterest.com/pin-creation-tool/"
    )

    result = await cleanup.clear_drafts_for_page_verified(page, timeout_seconds=5)

    assert not result["ok"] and result["remaining_count"] is None and result["deleted"] == 0
    assert page.goto.await_count == 2  # Initial navigation and one recovery refresh.
    assert read_state.await_count == 7  # Two sets of three reads plus final diagnostic read.


@pytest.mark.asyncio
@pytest.mark.parametrize("render_phase", ["initial", "after_delete", "persisted_zero"])
async def test_exhausted_render_reads_refresh_once_and_still_verify_persisted_zero(cleanup, render_phase):
    namespace = cleanup.clear_drafts_for_page_verified.__globals__
    full = {"count": 3, "blocked": False, "creator_ready": False}
    empty = {"count": 0, "blocked": False, "creator_ready": True}
    reads = [full, empty, empty, empty]
    offset = {"initial": 0, "after_delete": 1, "persisted_zero": 3}[render_phase]
    reads[offset:offset] = [TimeoutError("Locator.inner_text timed out")] * 3
    namespace["_read_draft_state"] = AsyncMock(side_effect=reads)
    namespace["_draft_drawer"] = AsyncMock(return_value=object())
    delete_batch = AsyncMock(return_value=True)
    namespace["_delete_draft_batch"] = delete_batch
    page = SimpleNamespace(goto=AsyncMock(), url="https://www.pinterest.com/pin-creation-tool/")

    result = await cleanup._clear_drafts_for_page_verified(page, timeout_seconds=5)

    assert result["ok"] and result["deleted"] == 3 and result["remaining_count"] == 0
    assert page.goto.await_count == 3  # Initial, one recovery, and independent persisted proof.
    assert namespace["_read_draft_state"].await_count == 7
    delete_batch.assert_awaited_once()


@pytest.mark.asyncio
async def test_nontransient_state_error_never_refreshes_creator(cleanup):
    namespace = cleanup.clear_drafts_for_page_verified.__globals__
    namespace["_read_draft_state"] = AsyncMock(side_effect=ValueError("malformed draft state"))
    page = SimpleNamespace(goto=AsyncMock(), url="https://www.pinterest.com/pin-creation-tool/")

    result = await cleanup._clear_drafts_for_page_verified(page, timeout_seconds=5)

    assert not result["ok"] and result["error"] == "malformed draft state"
    page.goto.assert_awaited_once()


@pytest.mark.asyncio
async def test_render_recovery_refresh_keeps_original_cleanup_deadline(cleanup):
    namespace = cleanup.clear_drafts_for_page_verified.__globals__
    empty = {"count": 0, "blocked": False, "creator_ready": True}
    namespace["_read_draft_state"] = AsyncMock(
        side_effect=[TimeoutError("Locator.inner_text timed out")] * 3 + [empty]
    )
    recovery_started = asyncio.Event()
    recovery_cancelled = asyncio.Event()
    navigations = 0

    async def goto(*_args, **_kwargs):
        nonlocal navigations
        navigations += 1
        if navigations == 2:
            recovery_started.set()
            try:
                await asyncio.sleep(60)
            finally:
                recovery_cancelled.set()

    page = SimpleNamespace(goto=goto, url="https://www.pinterest.com/pin-creation-tool/")
    result = await asyncio.wait_for(
        cleanup._clear_drafts_for_page_verified(page, timeout_seconds=0.6), timeout=2
    )

    assert recovery_started.is_set() and recovery_cancelled.is_set()
    assert navigations == 2 and not result["ok"] and result["error"] == "TimeoutError"
    assert result["deleted"] == 0  # A diagnostic read of zero cannot turn failure into success.


@pytest.mark.asyncio
async def test_cancellation_during_state_read_never_refreshes_creator(cleanup):
    namespace = cleanup.clear_drafts_for_page_verified.__globals__
    namespace["_read_draft_state"] = AsyncMock(side_effect=asyncio.CancelledError)
    page = SimpleNamespace(goto=AsyncMock(), url="https://www.pinterest.com/pin-creation-tool/")

    with pytest.raises(asyncio.CancelledError):
        await cleanup._clear_drafts_for_page_verified(page, timeout_seconds=5)

    page.goto.assert_awaited_once()


@pytest.mark.asyncio
async def test_render_retry_does_not_hide_nontransient_errors(cleanup):
    operation = AsyncMock(side_effect=ValueError("malformed state"))
    with pytest.raises(ValueError, match="malformed state"):
        await cleanup._retry_page_operation(operation)
    operation.assert_awaited_once()


@pytest.mark.asyncio
async def test_compatibility_wrapper_raises_on_unverified_cleanup(cleanup):
    namespace = cleanup.clear_drafts_for_page.__globals__
    report = {"ok": False, "deleted": 0, "error": "drafts still full"}
    namespace["clear_drafts_for_page_verified"] = AsyncMock(return_value=report)
    with pytest.raises(cleanup.DraftCleanupError, match="still full") as exc:
        await cleanup.clear_drafts_for_page(object())
    assert exc.value.result is report


@pytest.mark.asyncio
async def test_cancellation_propagates_without_returning_success(cleanup):
    page = SimpleNamespace(goto=AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await cleanup.clear_drafts_for_page_verified(page)


@pytest.mark.asyncio
async def test_success_requires_persisted_zero_count_after_reload(cleanup, creator_page):
    await set_creator(creator_page, count=3)
    navigations = 0

    async def revert_deletion_on_reload(*_args, **_kwargs):
        nonlocal navigations
        navigations += 1
        if navigations > 1:
            await creator_page.evaluate("remaining=3;opts.stuck=true;render()")

    creator_page.goto = revert_deletion_on_reload
    result = await cleanup.clear_drafts_for_page_verified(creator_page, timeout_seconds=2)
    assert not result["ok"] and result["remaining_count"] == 3
    assert result["deleted"] == 0


@pytest.mark.asyncio
async def test_individual_menu_reacquired_after_each_delete(cleanup, creator_page):
    await set_creator(creator_page, count=3, individual=True)
    # Preserve sidebar identity when the synthetic app rerenders its contents.
    result = await cleanup.clear_drafts_for_page_verified(creator_page, timeout_seconds=15)
    assert result["ok"] and result["deleted"] == 3
    assert await creator_page.evaluate("confirmations") == 3


@pytest.mark.asyncio
async def test_selection_timeout_does_not_toggle_completed_selection_again(cleanup):
    namespace = cleanup._delete_draft_batch.__globals__
    bulk = SimpleNamespace(
        evaluate=AsyncMock(side_effect=[False, True, True]),
        click=AsyncMock(side_effect=TimeoutError("navigation wait after selection")),
    )
    delete = SimpleNamespace(click=AsyncMock())
    namespace["_visible_first"] = AsyncMock(side_effect=[bulk, bulk, delete])
    namespace["_draft_drawer"] = AsyncMock(return_value=object())
    namespace["_confirm_draft_delete"] = AsyncMock(return_value=True)
    assert await cleanup._delete_draft_batch(object(), object()) is True
    bulk.click.assert_awaited_once()
    delete.click.assert_awaited_once()


@pytest.mark.asyncio
async def test_selection_timeout_without_selected_state_is_failure(cleanup):
    namespace = cleanup._delete_draft_batch.__globals__
    bulk = SimpleNamespace(
        evaluate=AsyncMock(return_value=False),
        click=AsyncMock(side_effect=TimeoutError("selection failed")),
    )
    namespace["_visible_first"] = AsyncMock(return_value=bulk)
    with pytest.raises(TimeoutError, match="selection failed"):
        await cleanup._delete_draft_batch(object(), object())
    bulk.click.assert_awaited_once()


@pytest.mark.asyncio
async def test_zero_and_creator_readiness_can_render_after_reload(cleanup, creator_page):
    await set_creator(creator_page, count=3)
    navigations = 0

    async def delayed_reload(*_args, **_kwargs):
        nonlocal navigations
        navigations += 1
        if navigations > 1:
            await creator_page.evaluate(
                "sidebar.innerHTML='Loading';upload.disabled=true;setTimeout(render, 700)"
            )

    creator_page.goto = delayed_reload
    result = await cleanup.clear_drafts_for_page_verified(creator_page, timeout_seconds=10)
    assert result["ok"] and result["creator_ready"]
    assert result["deleted"] == 3 and result["remaining_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("final_count", [None, 3])
async def test_deadline_during_reload_reports_latest_state_not_optimistic_zero(cleanup, final_count):
    namespace = cleanup.clear_drafts_for_page_verified.__globals__
    navigations = 0

    async def delayed_reload(*_args, **_kwargs):
        nonlocal navigations
        navigations += 1
        if navigations > 1:
            await asyncio.sleep(60)

    page = SimpleNamespace(goto=delayed_reload, url="https://www.pinterest.com/pin-creation-tool/")
    empty = {"count": 0, "blocked": False, "creator_ready": True}
    namespace["_read_draft_state"] = AsyncMock(
        side_effect=[
            {"count": 3, "blocked": False, "creator_ready": False},
            empty,
            empty,
            {"count": final_count, "blocked": bool(final_count), "creator_ready": False},
        ]
    )
    namespace["_draft_drawer"] = AsyncMock(return_value=object())
    namespace["_delete_draft_batch"] = AsyncMock(return_value=True)

    result = await cleanup.clear_drafts_for_page_verified(page, timeout_seconds=0.6)

    assert navigations == 2
    assert not result["ok"] and not result["creator_ready"]
    assert result["initial_count"] == 3 and result["remaining_count"] == final_count
    assert result["deleted"] == 0
    assert result["error"] == "TimeoutError"


def draft_feed(owner="123", *, request_bookmarks=None):
    route = f"/v3/users/{owner}/storypins/drafts/"
    options = {"url": route}
    if request_bookmarks is not None:
        options["bookmarks"] = request_bookmarks
    request = SimpleNamespace(
        url="https://es.pinterest.com/resource/ApiResource/get/?"
        + urlencode({"data": json.dumps({"options": options})})
    )
    payload = {
        "resource": {"name": "ApiResource", "options": {"url": route, "bookmarks": ["-end-"]}},
        "resource_response": {
            "status": "success",
            "code": 0,
            "http_status": 200,
            "endpoint_name": "v3_user_story_pin_drafts_feed",
            "data": [],
        },
        "client_context": {"is_authenticated": True, "user": {"id": owner}},
    }
    response = SimpleNamespace(request=request, status=200, json=AsyncMock(return_value=payload))
    return request, response, payload


@pytest.mark.asyncio
async def test_owned_complete_first_draft_feed_proves_zero_without_ui_counter(cleanup):
    page = SimpleNamespace(evaluate=AsyncMock(return_value="123"))
    evidence = cleanup._DraftFeedEvidence(page)
    await evidence.begin_navigation()
    request, response, _payload = draft_feed()
    evidence._request(request)
    evidence._response(response)
    await asyncio.gather(*evidence.pending)

    state = evidence.apply_count({"count": None, "blocked": False, "creator_ready": True})
    assert state["count"] == 0 and state["creator_ready"]
    await evidence.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "later_page",
        "nonterminal",
        "other_owner",
        "context_owner_mismatch",
        "wrong_endpoint",
        "failed_resource",
        "failed_http",
        "nonempty",
        "stale_navigation",
        "unowned",
    ],
)
async def test_untrusted_or_incomplete_feed_never_means_empty(cleanup, case):
    owner = None if case == "unowned" else "123"
    page = SimpleNamespace(evaluate=AsyncMock(return_value=owner))
    evidence = cleanup._DraftFeedEvidence(page)
    await evidence.begin_navigation()
    request, response, payload = draft_feed(
        "456" if case == "other_owner" else "123",
        request_bookmarks=["next-page"] if case == "later_page" else None,
    )
    if case == "nonterminal":
        payload["resource"]["options"]["bookmarks"] = ["next-page"]
    elif case == "context_owner_mismatch":
        payload["client_context"]["user"]["id"] = "456"
    elif case == "wrong_endpoint":
        payload["resource_response"]["endpoint_name"] = "v3_notifications"
    elif case == "failed_resource":
        payload["resource_response"]["status"] = "failure"
    elif case == "failed_http":
        response.status = 503
    elif case == "nonempty":
        payload["resource_response"]["data"] = [{"id": "pin-draft"}]
    elif case == "unowned":
        payload["client_context"] = {"is_authenticated": True}
    evidence._request(request)
    metadata = evidence.requests.get(id(request))
    if case == "stale_navigation":
        await evidence.begin_navigation()
        assert metadata is not None
        await evidence._consume_response(response, metadata[1])
    else:
        evidence._response(response)
        await asyncio.gather(*evidence.pending)

    assert evidence.apply_count({"count": None})["count"] is None
    await evidence.close()


@pytest.mark.asyncio
async def test_navigation_invalidates_previous_empty_feed_and_positive_ui_wins(cleanup):
    evidence = cleanup._DraftFeedEvidence(SimpleNamespace(evaluate=AsyncMock(return_value="123")))
    await evidence.begin_navigation()
    request, response, _payload = draft_feed()
    evidence._request(request)
    evidence._response(response)
    await asyncio.gather(*evidence.pending)
    assert evidence.apply_count({"count": None})["count"] == 0
    assert evidence.apply_count({"count": 2})["count"] == 2
    assert evidence.apply_count({"count": None})["count"] is None
    evidence.empty_owner = "123"
    await evidence.begin_navigation()
    assert evidence.apply_count({"count": None})["count"] is None
    await evidence.close()


@pytest.mark.asyncio
async def test_feed_trace_reports_failed_contract_without_account_or_payload_values(cleanup):
    evidence = cleanup._DraftFeedEvidence(SimpleNamespace(evaluate=AsyncMock(return_value="123")))
    await evidence.begin_navigation()
    request, response, payload = draft_feed()
    payload["resource"]["options"]["bookmarks"] = ["private-next-bookmark"]
    evidence._request(request)
    evidence._response(response)
    await asyncio.gather(*evidence.pending)
    summary = evidence.summary()
    assert summary["initial_requests_captured"] == 1 and summary["draft_responses_seen"] == 1
    assert summary["owner_resolved"] is True
    assert summary["last_feed_checks"]["terminal_bookmark"] is False
    assert summary["last_feed_checks"]["data_empty"] is True
    encoded = json.dumps(summary)
    assert "123" not in encoded and "private-next-bookmark" not in encoded
    assert evidence.apply_count({"count": None})["count"] is None
    await evidence.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("fresh_reload", [True, False])
async def test_network_empty_still_requires_fresh_reload_proof_and_detaches(cleanup, fresh_reload):
    namespace = cleanup.clear_drafts_for_page_verified.__globals__
    callbacks = {}
    navigations = 0

    def on(event, callback):
        callbacks[event] = callback

    async def goto(*_args, **_kwargs):
        nonlocal navigations
        navigations += 1
        if navigations == 1 or fresh_reload:
            request, response, _payload = draft_feed()
            callbacks["request"](request)
            callbacks["response"](response)
            await asyncio.sleep(0)

    page = SimpleNamespace(
        evaluate=AsyncMock(return_value="123"),
        on=on,
        remove_listener=Mock(),
        goto=goto,
        url="https://es.pinterest.com/pin-creation-tool/",
    )
    namespace["_read_draft_state"] = AsyncMock(
        return_value={"count": None, "blocked": False, "creator_ready": True}
    )
    namespace["_draft_drawer"] = AsyncMock(return_value=None)

    result = await cleanup.clear_drafts_for_page_verified(page, timeout_seconds=0.8)

    assert result["ok"] is fresh_reload
    assert result["creator_ready"]
    assert result["remaining_count"] == (0 if fresh_reload else None)
    assert navigations >= 2
    assert page.remove_listener.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("advance_during_body", [False, True])
async def test_stale_draft_response_cannot_establish_owner(cleanup, advance_during_body):
    evidence = cleanup._DraftFeedEvidence(SimpleNamespace(evaluate=AsyncMock(return_value=None)))
    await evidence.begin_navigation()
    request, response, payload = draft_feed()
    evidence._request(request)
    metadata = evidence.requests[id(request)][1]

    async def json_after_navigation():
        await evidence.begin_navigation()
        return payload

    if advance_during_body:
        response.json.side_effect = json_after_navigation
    else:
        await evidence.begin_navigation()
    await evidence._consume_response(response, metadata)

    assert evidence.owner_id is None and evidence.empty_owner is None
    await evidence.close()


@pytest.mark.asyncio
async def test_draft_response_requires_captured_request_object_identity(cleanup):
    evidence = cleanup._DraftFeedEvidence(SimpleNamespace(evaluate=AsyncMock(return_value="123")))
    await evidence.begin_navigation()
    original, _response, _payload = draft_feed()
    other, response, _payload = draft_feed()
    evidence._request(original)
    # Simulate a colliding lookup; retaining the actual request object must
    # reject this response even if its numeric object key was reused.
    evidence.requests[id(other)] = evidence.requests[id(original)]
    evidence._response(response)

    assert not evidence.pending and evidence.empty_owner is None
    response.json.assert_not_awaited()
    await evidence.close()


@pytest.mark.asyncio
async def test_draft_listener_shutdown_is_bounded_if_body_suppresses_cancellation(cleanup):
    evidence = cleanup._DraftFeedEvidence(SimpleNamespace(evaluate=AsyncMock(return_value=None)))
    await evidence.begin_navigation()
    request, response, payload = draft_feed()
    started = asyncio.Event()
    release = asyncio.Event()

    async def cancellation_resistant_body():
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        return payload

    response.json.side_effect = cancellation_resistant_body
    evidence._request(request)
    evidence._response(response)
    pending = tuple(evidence.pending)
    await started.wait()
    try:
        await asyncio.wait_for(evidence.close(), timeout=1.5)
        assert evidence.closed and evidence.owner_id is None and evidence.empty_owner is None
    finally:
        release.set()
        await asyncio.gather(*pending, return_exceptions=True)
    assert evidence.owner_id is None and evidence.empty_owner is None


def ssr_creator_page():
    page = SimpleNamespace(
        marker=1.0,
        url="https://es.pinterest.com/pin-creation-tool/",
        snapshot_owner="123",
        on=Mock(),
        remove_listener=Mock(),
        navigations=0,
    )
    _request, _response, payload = draft_feed()
    payload["request_cursor_present"] = False
    page.payload = payload

    async def evaluate(script):
        if script == "() => performance.timeOrigin":
            return page.marker
        if "document_token:" in script:
            return {
                "document_token": page.marker,
                "url": page.url,
                "owner_id": page.snapshot_owner,
                "feeds": [page.payload],
            }
        if "embedded_draft_feeds" in script:
            return {"available": True}
        return "123"

    async def goto(*_args, **_kwargs):
        page.marker += 1
        page.navigations += 1
        return SimpleNamespace(url=page.url, status=200)

    page.evaluate = AsyncMock(side_effect=evaluate)
    page.goto = AsyncMock(side_effect=goto)
    return page


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "nonempty",
        "wrong_owner",
        "wrong_route",
        "nonterminal",
        "paginated_tail",
        "failed_result",
        "failed_http",
        "malformed",
        "stale_document",
        "not_fresh",
        "wrong_page",
    ],
)
async def test_ssr_empty_proof_requires_fresh_owned_complete_creator_document(cleanup, case):
    page = ssr_creator_page()
    evidence = cleanup._DraftFeedEvidence(page)
    await evidence.begin_navigation()
    if case != "not_fresh":
        page.marker += 1
    if case == "wrong_page":
        page.url = "https://es.pinterest.com/other/"
    await evidence.bind_document(SimpleNamespace(status=200, url=page.url))
    if case == "nonempty":
        page.payload["resource_response"]["data"] = [{"id": "draft"}]
    elif case == "wrong_owner":
        page.snapshot_owner = "456"
    elif case == "wrong_route":
        page.payload["resource"]["options"]["url"] = "/v3/users/456/storypins/drafts/"
    elif case == "nonterminal":
        page.payload["resource"]["options"]["bookmarks"] = ["later"]
    elif case == "paginated_tail":
        page.payload["request_cursor_present"] = True
    elif case == "failed_result":
        page.payload["resource_response"]["status"] = "failure"
    elif case == "failed_http":
        page.payload["resource_response"]["http_status"] = 503
    elif case == "malformed":
        page.payload = {"request_cursor_present": False}
    elif case == "stale_document":
        page.marker += 1

    await evidence.read_bootstrap()

    assert (evidence.apply_count({"count": None})["count"] == 0) is (case == "valid")
    await evidence.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("reload_empty", [True, False])
async def test_ssr_empty_still_requires_independent_fresh_reload_proof(cleanup, reload_empty):
    page = ssr_creator_page()
    namespace = cleanup.clear_drafts_for_page_verified.__globals__
    namespace["_read_draft_state"] = AsyncMock(
        return_value={"count": None, "blocked": False, "creator_ready": True}
    )
    namespace["_draft_drawer"] = AsyncMock(return_value=None)
    original_goto = page.goto

    async def reload(*args, **kwargs):
        response = await original_goto(*args, **kwargs)
        if page.navigations > 1 and not reload_empty:
            page.payload["resource_response"]["data"] = [{"id": "still-a-draft"}]
        return response

    page.goto = reload
    result = await cleanup.clear_drafts_for_page_verified(page, timeout_seconds=0.8)

    assert result["ok"] is reload_empty
    assert result["remaining_count"] == (0 if reload_empty else None)
    assert page.navigations >= 2
    if not reload_empty:
        assert result["draft_feed_evidence"]["fresh_document_bound"] is True
        assert result["draft_feed_evidence"]["last_feed_checks"]["data_empty"] is False

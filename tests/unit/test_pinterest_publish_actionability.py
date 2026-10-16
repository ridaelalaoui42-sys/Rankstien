"""Exact actionable publication and sanitized diagnostics without live runtime."""

import ast
import asyncio
import json
import re
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest


@pytest.fixture
def publish_core():
    path = Path(__file__).resolve().parents[2] / "backend/scripts/pinterest_batch_core.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {
        "PinCreationError",
        "PinterestPublishUnavailableError",
        "PinterestPublishUncertainError",
        "_publish_diagnostic_text",
        "_publish_diagnostic_route",
        "_publish_diagnostic_flags",
        "_PublishNetworkDiagnostics",
        "_wait_for_actionable_publish",
        "_click_publish_once",
        "_fill_pin_description",
        "dismiss_publish_success_overlays",
        "_extract_published_before_dismiss",
    }
    namespace = {
        "asyncio": asyncio,
        "json": json,
        "re": re,
        "time": time,
        "urlsplit": urlsplit,
        "parse_qs": parse_qs,
        "logger": Mock(),
    }
    selected = [node for node in tree.body if getattr(node, "name", "") in names]
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)  # noqa: S102
    return SimpleNamespace(**namespace)


class Buttons:
    def __init__(self, buttons):
        self.buttons = buttons

    async def count(self):
        return len(self.buttons)

    def nth(self, index):
        return self.buttons[index]


def button(label="Publish", *, enabled=True):
    return SimpleNamespace(
        inner_text=AsyncMock(return_value=label),
        is_visible=AsyncMock(return_value=True),
        is_enabled=AsyncMock(return_value=enabled),
        click=AsyncMock(),
    )


def creator_page(buttons, nav_buttons=None):
    return SimpleNamespace(
        get_by_role=Mock(return_value=Buttons(buttons)),
        locator=Mock(return_value=Buttons(nav_buttons or [])),
        on=Mock(),
        remove_listener=Mock(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("label", ["Publish", "Publicar", "Publish now", "Publicar ahora"])
async def test_disabled_publish_waits_for_enabled_and_clicks_once_without_force(publish_core, label):
    control = button(label)
    control.is_enabled.side_effect = [False, False, True]
    page = creator_page([control])
    diagnostics = publish_core._PublishNetworkDiagnostics(page)
    await publish_core._click_publish_once(page, "worker", diagnostics, timeout_seconds=2)
    control.click.assert_awaited_once()
    assert set(control.click.await_args.kwargs) == {"timeout"}
    assert diagnostics.click_started and diagnostics.click_completed
    await diagnostics.close()


@pytest.mark.asyncio
async def test_exact_label_rejects_publish_later_and_nonpublish_known_nav(publish_core):
    later = button("Publish at a later date")
    done = button("Save")
    publish = button("Publish")
    page = creator_page([later, publish], [done])
    diagnostics = publish_core._PublishNetworkDiagnostics(page)
    await publish_core._click_publish_once(page, "worker", diagnostics)
    later.click.assert_not_awaited()
    done.click.assert_not_awaited()
    publish.click.assert_awaited_once()
    matcher = page.get_by_role.call_args.kwargs["name"]
    assert matcher.fullmatch("Publish") and not matcher.fullmatch("Publish at a later date")
    await diagnostics.close()


@pytest.mark.asyncio
async def test_persistently_disabled_publish_fails_before_any_click(publish_core):
    control = button(enabled=False)
    page = creator_page([control])
    diagnostics = publish_core._PublishNetworkDiagnostics(page)
    with pytest.raises(publish_core.PinterestPublishUnavailableError) as caught:
        await publish_core._click_publish_once(page, "worker", diagnostics, timeout_seconds=0.03)
    assert caught.value.error_code == "pinterest_publish_unavailable"
    control.click.assert_not_awaited()
    assert not diagnostics.click_started
    page.on.assert_not_called()


@pytest.mark.asyncio
async def test_actionability_rpc_hang_is_bounded_before_click(publish_core):
    control = button()

    async def blocked_enabled():
        await asyncio.sleep(60)

    control.is_enabled.side_effect = blocked_enabled
    page = creator_page([control])
    diagnostics = publish_core._PublishNetworkDiagnostics(page)
    with pytest.raises(publish_core.PinterestPublishUnavailableError):
        await publish_core._click_publish_once(page, "worker", diagnostics, timeout_seconds=0.03)
    control.click.assert_not_awaited()


@pytest.mark.asyncio
async def test_preclick_locator_failure_stays_unavailable_without_any_action(publish_core):
    control = button()
    control.inner_text.side_effect = RuntimeError("frame detached")
    diagnostics = publish_core._PublishNetworkDiagnostics(creator_page([control]))
    with pytest.raises(publish_core.PinterestPublishUnavailableError):
        await publish_core._click_publish_once(diagnostics.page, "worker", diagnostics)
    control.click.assert_not_awaited()
    assert not diagnostics.click_started


@pytest.mark.asyncio
async def test_click_timeout_is_uncertain_without_second_control_or_keyboard_retry(publish_core):
    first = button()
    first.click.side_effect = TimeoutError("timed out after dispatch")
    second = button()
    page = creator_page([first, second])
    diagnostics = publish_core._PublishNetworkDiagnostics(page)
    with pytest.raises(publish_core.PinterestPublishUncertainError) as caught:
        await publish_core._click_publish_once(page, "worker", diagnostics)
    assert caught.value.uncertain is True
    assert caught.value.error_code == "pinterest_publish_uncertain"
    first.click.assert_awaited_once()
    second.click.assert_not_awaited()
    assert diagnostics.click_started and not diagnostics.click_completed
    await diagnostics.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("rich_text", [True, False])
async def test_description_uses_normal_fill_and_verifies_rich_text_or_textarea(publish_core, rich_text):
    description = "Una receta cremosa y fácil.\nCon ingredientes frescos."
    field = SimpleNamespace(
        is_visible=AsyncMock(return_value=True),
        is_enabled=AsyncMock(return_value=True),
        fill=AsyncMock(),
        input_value=AsyncMock(side_effect=RuntimeError("not a textarea"))
        if rich_text
        else AsyncMock(return_value=description),
        inner_text=AsyncMock(return_value=description),
    )

    def locate(selector):
        matches = ("contenteditable" in selector) if rich_text else ("textarea" in selector)
        return Buttons([field] if matches else [])

    page = SimpleNamespace(locator=Mock(side_effect=locate))
    assert await publish_core._fill_pin_description(page, description)
    field.fill.assert_awaited_once()
    assert field.fill.await_args.args == (description,)
    assert set(field.fill.await_args.kwargs) == {"timeout"}
    assert field.inner_text.await_count == int(rich_text)


@pytest.mark.asyncio
async def test_description_readback_failure_never_claims_filled(publish_core):
    field = SimpleNamespace(
        is_visible=AsyncMock(return_value=True),
        is_enabled=AsyncMock(return_value=True),
        fill=AsyncMock(),
        input_value=AsyncMock(side_effect=RuntimeError("rich editor")),
        inner_text=AsyncMock(return_value=""),
    )
    page = SimpleNamespace(locator=Mock(return_value=Buttons([field])))
    assert not await publish_core._fill_pin_description(page, "Expected description")
    field.fill.assert_awaited_once()


def request(url="https://es.pinterest.com/resource/PinResource/create/?secret=do-not-log", **kwargs):
    return SimpleNamespace(url=url, method="POST", post_data=None, **kwargs)


@pytest.mark.asyncio
async def test_network_diagnostic_distinguishes_absent_mutation_and_rejected_response(publish_core):
    diagnostics = publish_core._PublishNetworkDiagnostics(creator_page([]))
    assert diagnostics.summary()["mutating_requests"] == 0
    req = request()
    diagnostics._request(req)
    response = SimpleNamespace(
        request=req,
        status=400,
        json=AsyncMock(
            return_value={
                "resource_response": {
                    "status": "failure",
                    "code": 147,
                    "error": {
                        "message": "Rejected for someone@example.test at https://pinterest.com/a?token=secret"
                    },
                    "data": {"password": "do-not-log", "cookie": "do-not-log"},
                }
            }
        ),
    )
    diagnostics._response(response)
    await asyncio.gather(*diagnostics.pending)
    summary = diagnostics.summary()
    assert summary["mutating_requests"] == 1 and summary["rejected_responses"] == 1
    assert summary["requests"][0]["error_code"] == "147"
    encoded = json.dumps(summary)
    assert "do-not-log" not in encoded and "someone@" not in encoded and "token=secret" not in encoded
    assert "[email]" in encoded and "[url]" in encoded
    await diagnostics.close()


def test_diagnostic_error_fields_reject_nested_payloads_and_redact_named_secrets(publish_core):
    assert publish_core._publish_diagnostic_text({"password": "never-log"}) == "[non-scalar]"
    result = publish_core._publish_diagnostic_text("password=never-log cookie=private token='private-value'")
    assert "never-log" not in result and "private" not in result
    assert result.count("[redacted]") == 3


@pytest.mark.asyncio
async def test_graphql_publish_diagnostic_and_http200_error(publish_core):
    diagnostics = publish_core._PublishNetworkDiagnostics(creator_page([]))
    req = request("https://www.pinterest.com/graphql")
    req.post_data = json.dumps(
        {"operationName": "PublishPinMutation", "variables": {"password": "not-retained"}}
    )
    diagnostics._request(req)
    diagnostics._response(
        SimpleNamespace(
            request=req, status=200, json=AsyncMock(return_value={"errors": [{"message": "Publish failed"}]})
        )
    )
    await asyncio.gather(*diagnostics.pending)
    summary = diagnostics.summary()
    assert summary["mutating_requests"] == 1 and summary["rejected_responses"] == 1
    assert summary["requests"][0]["operation"] == "PublishPinMutation"
    assert "not-retained" not in json.dumps(summary)
    await diagnostics.close()


def test_unparsed_graphql_is_unknown_rather_than_proof_of_no_request(publish_core):
    diagnostics = publish_core._PublishNetworkDiagnostics(creator_page([]))
    req = request("https://www.pinterest.com/graphql")
    req.post_data = "unparsed-private-request-body"
    diagnostics._request(req)
    summary = diagnostics.summary()
    assert summary["mutating_requests"] == 0 and summary["unknown_graphql_requests"] == 1
    assert "unparsed-private-request-body" not in json.dumps(summary)


@pytest.mark.parametrize("encoding", ["json", "form", "query"])
def test_api_resource_wrapper_records_only_underlying_pin_mutation_route(publish_core, encoding):
    diagnostics = publish_core._PublishNetworkDiagnostics(creator_page([]))
    body = json.dumps(
        {
            "options": {
                "url": "/v3/users/123/storypins/456/publish/",
                "method": "POST",
                "password": "never-log",
            }
        }
    )
    req = request("https://www.pinterest.com/resource/ApiResource/create/")
    if encoding == "query":
        req.url += "?" + urlencode({"data": body})
    else:
        req.post_data = body if encoding == "json" else urlencode({"data": body})
    diagnostics._request(req)
    summary = diagnostics.summary()
    assert summary["mutating_requests"] == 1
    assert summary["requests"][0]["route"] == "/v3/users/[id]/storypins/[id]/publish/"
    assert summary["requests"][0]["api_method"] == "POST"
    assert "never-log" not in json.dumps(summary)


def test_unparsed_api_wrapper_is_unknown_rather_than_absent_mutation(publish_core):
    diagnostics = publish_core._PublishNetworkDiagnostics(creator_page([]))
    req = request("https://www.pinterest.com/resource/ApiResource/create/")
    req.post_data = "private-malformed-body"
    diagnostics._request(req)
    summary = diagnostics.summary()
    assert summary["mutating_requests"] == 0 and summary["unknown_api_requests"] == 1
    assert "private-malformed-body" not in json.dumps(summary)


@pytest.mark.parametrize("encoding", ["json", "form", "query"])
def test_unknown_api_route_retains_named_endpoint_and_safe_flags_without_identifiers(publish_core, encoding):
    diagnostics = publish_core._PublishNetworkDiagnostics(creator_page([]))
    payload = {
        "options": {
            "url": "/v3/pin_creation_service/1234567890123456789/123e4567-e89b-12d3-a456-426614174000/publish/"
            "AbCdEf0123456789AbCdEf0123456789AbCdEf0123456789/?access_token=private-query",
            "data": {"publish": True, "is_draft": False, "status": "published", "password": "private-body"},
            "other": {"cookie": "private-cookie"},
        }
    }
    body = json.dumps(payload)
    req = request("https://www.pinterest.com/resource/ApiResource/update/")
    if encoding == "query":
        req.url += "?" + urlencode({"data": body})
    else:
        req.post_data = body if encoding == "json" else urlencode({"data": body})
    diagnostics._request(req)
    summary = diagnostics.summary()
    event = summary["requests"][0]
    assert event["route"] == "/v3/pin_creation_service/[id]/[id]/publish/[token]/"
    assert event["option_keys"] == ["url", "data", "other"]
    assert event["flags"] == {"publish": True, "is_draft": False, "status": "published"}
    assert summary["unknown_api_requests"] == 1
    encoded = json.dumps(summary)
    for private_value in (
        "1234567890123456789",
        "123e4567",
        "AbCdEf0123456789",
        "private-query",
        "private-body",
        "private-cookie",
    ):
        assert private_value not in encoded


def test_api_diagnostic_flags_reject_untrusted_strings_and_nonboolean_values(publish_core):
    options = {"publish": "private-text", "is_draft": 1, "status": "an arbitrary private message"}
    assert publish_core._publish_diagnostic_flags(options) == {}
    assert publish_core._publish_diagnostic_route("https://evil.test/private") == "[external-route]"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "success_text", ["Your Pin has been published!", "Tu Pin se ha publicado", "Guardado"]
)
async def test_visible_success_notice_prevents_all_overlay_dismissal_even_after_hidden_match(
    publish_core, success_text
):
    hidden = SimpleNamespace(is_visible=AsyncMock(return_value=False))
    visible = SimpleNamespace(is_visible=AsyncMock(return_value=True), text=success_text)
    page = SimpleNamespace(
        get_by_text=Mock(return_value=Buttons([hidden, visible])),
        locator=Mock(side_effect=AssertionError("must preserve success overlay")),
    )
    await publish_core.dismiss_publish_success_overlays(page)
    page.locator.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("known_extension", [True, False])
async def test_only_known_extension_dialog_can_be_dismissed_with_normal_scoped_click(
    publish_core, known_extension
):
    close = button("Not now")
    dialog = SimpleNamespace(
        is_visible=AsyncMock(return_value=True),
        inner_text=AsyncMock(
            return_value="Install the Pinterest browser extension"
            if known_extension
            else "Keep your draft changes?"
        ),
        get_by_role=Mock(return_value=Buttons([close])),
    )
    page = SimpleNamespace(
        get_by_text=Mock(return_value=Buttons([])),
        locator=Mock(return_value=Buttons([dialog])),
        keyboard=SimpleNamespace(press=AsyncMock()),
        evaluate=AsyncMock(),
    )
    await publish_core.dismiss_publish_success_overlays(page)
    assert close.click.await_count == int(known_extension)
    if known_extension:
        assert close.click.await_args.kwargs == {"timeout": 2000}
    page.keyboard.press.assert_not_awaited()
    page.evaluate.assert_not_awaited()
    page.locator.assert_called_once_with('[role="dialog"], [aria-modal="true"]')


@pytest.mark.asyncio
async def test_success_dialog_is_preserved_even_when_global_notice_lookup_misses_it(publish_core):
    close = button("Close")
    dialog = SimpleNamespace(
        is_visible=AsyncMock(return_value=True),
        inner_text=AsyncMock(
            return_value="Your Pin has been published! Install the Pinterest browser extension"
        ),
        get_by_role=Mock(return_value=Buttons([close])),
    )
    page = SimpleNamespace(
        get_by_text=Mock(return_value=Buttons([])), locator=Mock(return_value=Buttons([dialog]))
    )
    await publish_core.dismiss_publish_success_overlays(page)
    close.click.assert_not_awaited()
    dialog.get_by_role.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("pin_id", [None, "1082904672940181452"])
async def test_pin_proof_extraction_always_precedes_any_dismissal(publish_core, pin_id):
    namespace = publish_core._extract_published_before_dismiss.__globals__
    order = []

    async def extract(*_args):
        order.append("extract")
        return pin_id

    async def dismiss(*_args):
        order.append("dismiss")

    namespace["extract_published_pin_id"] = extract
    namespace["dismiss_publish_success_overlays"] = dismiss
    result = await publish_core._extract_published_before_dismiss(object(), "worker", dismiss=True)
    assert result == pin_id
    assert order == (["extract"] if pin_id else ["extract", "dismiss"])


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/resource/PinResource/create/",
        "https://pinterest.com.evil.test/graphql",
        "https://www.pinterest.com/login/",
        "https://www.pinterest.com/resource/PinResource/get/",
    ],
)
def test_diagnostics_ignore_foreign_auth_and_read_requests(publish_core, url):
    diagnostics = publish_core._PublishNetworkDiagnostics(creator_page([]))
    diagnostics._request(request(url))
    assert diagnostics.summary()["requests"] == []


@pytest.mark.asyncio
async def test_network_capture_is_bounded_and_preserves_request_identity(publish_core):
    diagnostics = publish_core._PublishNetworkDiagnostics(creator_page([]))
    requests = [request() for _ in range(30)]
    for req in requests:
        diagnostics._request(req)
    assert len(diagnostics.events) == 20
    assert diagnostics.summary()["capture_limit_reached"] is True
    req = requests[0]
    captured = diagnostics.requests[id(req)]
    assert captured[0] is req
    req.failure = "net::ERR_CONNECTION_RESET at https://pinterest.com/?secret=private"
    diagnostics._request_failed(req)
    assert diagnostics.summary()["request_failures"] == 1
    assert diagnostics.events[0]["request_failure"] == "net::ERR_CONNECTION_RESET"
    await diagnostics.close()


@pytest.mark.asyncio
async def test_diagnostic_close_is_bounded_and_late_body_cannot_change_evidence(publish_core):
    diagnostics = publish_core._PublishNetworkDiagnostics(creator_page([]))
    req = request()
    diagnostics._request(req)
    entered = asyncio.Event()
    finish = asyncio.Event()

    async def resistant_body():
        entered.set()
        try:
            await finish.wait()
        except asyncio.CancelledError:
            await finish.wait()
        return {"resource_response": {"status": "failure", "code": 999}}

    diagnostics._response(
        SimpleNamespace(request=req, status=200, json=AsyncMock(side_effect=resistant_body))
    )
    await entered.wait()
    tasks = tuple(diagnostics.pending)
    try:
        await asyncio.wait_for(diagnostics.close(), timeout=2)
        before = diagnostics.summary()
        finish.set()
        await asyncio.gather(*tasks)
        assert diagnostics.summary() == before
    finally:
        finish.set()
        await asyncio.gather(*tasks, return_exceptions=True)

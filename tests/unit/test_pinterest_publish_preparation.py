"""Exercise editor preparation in isolated Chromium documents, without runtime imports."""

from __future__ import annotations

import ast
import asyncio
import re
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright


@pytest.fixture
def preparation():
    path = Path(__file__).resolve().parents[2] / "backend/scripts/pinterest_batch_core.py"
    names = {
        "PinCreationError",
        "PinterestPublishUnavailableError",
        "PinterestPublishUncertainError",
        "_fill_pin_title",
        "_ensure_immediate_publish",
        "_prepare_publish",
        "_wait_for_actionable_publish",
        "_click_publish_once",
    }
    tree = ast.parse(path.read_text(encoding="utf-8"))
    selected = [node for node in tree.body if getattr(node, "name", "") in names]
    namespace = {"asyncio": asyncio, "re": re, "time": time, "logger": Mock()}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)  # noqa: S102
    return SimpleNamespace(**namespace)


@pytest_asyncio.fixture
async def editor():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        await context.route("**/*", lambda route: route.abort())
        page = await context.new_page()
        try:
            yield page
        finally:
            await context.close()
            await browser.close()


def diagnostics():
    return SimpleNamespace(attach=Mock(), click_started=False, click_completed=False)


@pytest.mark.asyncio
async def test_link_blur_save_can_swallow_click_then_preparation_allows_one_publish(preparation, editor):
    await editor.set_content(
        """<input id="link" placeholder="Add a link">
        <p id="state">Changes stored!</p>
        <button id="publish" onclick="window.publishes++">Publish</button>
        <script>
        window.publishes = 0;
        window.blurs = 0;
        link.onblur = () => {
            window.blurs++;
            publish.disabled = true;
            state.textContent = 'Saving...';
            setTimeout(() => {
                state.textContent = 'Changes stored!';
                publish.disabled = false;
            }, 200);
        };
        </script>"""
    )
    await editor.locator("#link").fill("https://example.test/recipe")
    # Chromium can finish a normal click while the focused field's blur
    # disables the target between pointerdown and click dispatch.
    await editor.get_by_role("button", name="Publish", exact=True).click()
    assert await editor.evaluate("window.publishes") == 0
    await editor.wait_for_function("!publish.disabled")
    await editor.locator("#link").focus()

    await preparation._prepare_publish(editor, "isolated-worker", timeout_seconds=15)
    assert await editor.evaluate("document.activeElement.id") != "link"
    assert await editor.evaluate("window.blurs") == 2
    assert await editor.locator("#state").inner_text() == "Changes stored!"
    assert await editor.evaluate("window.publishes") == 0

    evidence = diagnostics()
    await preparation._click_publish_once(editor, "isolated-worker", evidence, timeout_seconds=5)
    assert await editor.evaluate("window.publishes") == 1
    assert evidence.click_started and evidence.click_completed
    evidence.attach.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "marker",
    [
        "Changes stored!",
        "All changes saved",
        "Changes saved",
        "Cambios guardados!",
        "Todos los cambios guardados",
    ],
)
async def test_exact_saved_markers_allow_preparation_without_click(preparation, editor, marker):
    await editor.set_content(
        f'<p role="status">{marker}</p><button onclick="window.publishes++">Publicar</button>'
        "<script>window.publishes = 0</script>"
    )
    started = time.monotonic()
    await preparation._prepare_publish(editor, "worker", timeout_seconds=10)
    assert time.monotonic() - started >= 0.35
    assert await editor.evaluate("window.publishes") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "markup",
    [
        "<p>Saving...</p>",
        "<p>Guardando...</p><p>Cambios guardados!</p>",
        "<p>No autosave status available</p>",
        "<p hidden>Changes stored!</p>",
        "<p>All changes saved except the destination link</p>",
    ],
)
async def test_unsettled_or_unproven_save_fails_before_publish(preparation, editor, markup):
    await editor.set_content(
        markup
        + '<button onclick="window.publishes++">Publish</button>'
        + "<script>window.publishes = 0</script>"
    )
    started = time.monotonic()
    with pytest.raises(preparation.PinterestPublishUnavailableError) as caught:
        await preparation._prepare_publish(editor, "worker", timeout_seconds=0.15)
    assert caught.value.error_code == "pinterest_publish_unavailable"
    assert time.monotonic() - started < 1.5
    assert await editor.evaluate("window.publishes") == 0


@pytest.mark.asyncio
async def test_save_marker_must_remain_stable_after_resumed_saving(preparation, editor):
    await editor.set_content(
        """<input id="link"><p id="state">Changes stored!</p>
        <button onclick="window.publishes++">Publish</button>
        <script>
        window.publishes = 0;
        window.saveFinished = false;
        link.onblur = () => {
            setTimeout(() => { state.textContent = 'Saving...'; }, 100);
            setTimeout(() => {
                state.textContent = 'Changes stored!';
                window.saveFinished = true;
            }, 280);
        };
        </script>"""
    )
    await editor.locator("#link").focus()
    started = time.monotonic()
    await preparation._prepare_publish(editor, "worker", timeout_seconds=10)
    assert await editor.evaluate("window.saveFinished")
    assert time.monotonic() - started >= 0.6
    assert await editor.evaluate("window.publishes") == 0


@pytest.mark.asyncio
async def test_preparation_browser_rpc_hang_obeys_original_deadline(preparation):
    async def hang(*_args, **_kwargs):
        await asyncio.sleep(60)

    page = SimpleNamespace(keyboard=SimpleNamespace(press=AsyncMock(side_effect=hang)))
    started = time.monotonic()
    with pytest.raises(preparation.PinterestPublishUnavailableError):
        await preparation._prepare_publish(page, "worker", timeout_seconds=0.03)
    assert time.monotonic() - started < 1
    page.keyboard.press.assert_awaited_once_with("Tab")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "markup",
    [
        '<textarea id="storyboard-selector-title"></textarea>',
        '<div data-test-id="pin-draft-title"><input></div>',
        '<div data-test-id="pin-draft-title"><div contenteditable="true"></div></div>',
        '<input placeholder="Add a title">',
        '<textarea placeholder="Añade un título"></textarea>',
    ],
)
async def test_title_normal_fill_dispatches_input_and_commits_retained_value(preparation, editor, markup):
    title = "Galletas de mantequilla fáciles"
    await editor.set_content(
        markup
        + '<button id="after">Next field</button>'
        + """<script>
        window.inputs = 0;
        window.blurs = 0;
        const title = document.querySelector('input, textarea, [contenteditable]');
        title.addEventListener('input', () => { window.inputs++; });
        title.addEventListener('blur', () => { window.blurs++; });
        </script>"""
    )
    assert await preparation._fill_pin_title(editor, title, timeout_seconds=10)
    field = editor.locator("input, textarea, [contenteditable]")
    observed = (
        await field.inner_text()
        if await field.get_attribute("contenteditable")
        else await field.input_value()
    )
    assert observed == title
    assert await editor.evaluate("window.inputs") >= 1
    assert await editor.evaluate("window.blurs") == 1
    assert await editor.evaluate("document.activeElement.id") == "after"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "markup",
    [
        '<input placeholder="Search"><button>Next</button>',
        '<textarea id="storyboard-selector-title" disabled></textarea>',
        '<textarea id="storyboard-selector-title" hidden></textarea>',
        '<textarea id="storyboard-selector-title" onblur="this.value=\'\'"></textarea><button>Next</button>',
    ],
)
async def test_missing_disabled_hidden_or_unretained_title_is_failure(preparation, editor, markup):
    await editor.set_content(markup)
    assert not await preparation._fill_pin_title(editor, "Expected title", timeout_seconds=0.15)


@pytest.mark.asyncio
async def test_title_reverted_on_blur_fails_retained_readback_before_deadline(preparation, editor):
    await editor.set_content(
        '<textarea id="storyboard-selector-title" onblur="this.value=\'\';window.blurs++"></textarea>'
        "<button>Next field</button><script>window.blurs=0</script>"
    )

    assert not await preparation._fill_pin_title(editor, "Expected title", timeout_seconds=10)
    assert await editor.evaluate("window.blurs") == 1
    assert await editor.locator("#storyboard-selector-title").input_value() == ""


@pytest.mark.asyncio
async def test_native_schedule_checked_state_takes_precedence_over_stale_aria(preparation, editor):
    await editor.set_content(
        '<div data-test-id="pin-draft-switch-group">'
        '<input type="checkbox" id="schedule" aria-checked="false" checked>'
        "Publish at a later date</div>"
    )

    assert await preparation._ensure_immediate_publish(editor, timeout_seconds=5)
    assert not await editor.locator("#schedule").is_checked()


@pytest.mark.asyncio
async def test_schedule_targets_exact_group_and_leaves_upload_and_unrelated_controls(preparation, editor):
    await editor.set_content(
        """<main id="outer">
        <div>Publish at a later date</div>
        <input type="file" id="upload" hidden>
        <label><input type="checkbox" id="unrelated" checked>Other preference</label>
        <div data-test-id="pin-draft-switch-group">
            <label><input type="checkbox" id="schedule" checked>Publish at a later date</label>
        </div>
        <button>Publish</button>
        </main>
        <script>
        window.scheduleChanges = 0;
        window.wrongChanges = 0;
        schedule.onchange = () => { window.scheduleChanges++; };
        unrelated.onchange = () => { window.wrongChanges++; };
        upload.onchange = () => { window.wrongChanges++; };
        </script>"""
    )
    assert await preparation._ensure_immediate_publish(editor, timeout_seconds=5)
    assert not await editor.locator("#schedule").is_checked()
    assert await editor.locator("#unrelated").is_checked()
    assert await editor.evaluate("window.scheduleChanges") == 1
    assert await editor.evaluate("window.wrongChanges") == 0
    assert await editor.locator("#upload").input_value() == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("label", ["Publicar más tarde", "Publicar en una fecha posterior"])
async def test_exact_accessible_schedule_switch_is_disabled_once(preparation, editor, label):
    await editor.set_content(
        f'<button id="schedule" role="switch" aria-label="{label}" aria-checked="true" '
        "onclick=\"window.toggles++; this.setAttribute('aria-checked', 'false')\"></button>"
        "<script>window.toggles = 0</script>"
    )
    assert await preparation._ensure_immediate_publish(editor, timeout_seconds=5)
    assert await editor.locator("#schedule").get_attribute("aria-checked") == "false"
    assert await editor.evaluate("window.toggles") == 1


@pytest.mark.asyncio
async def test_absent_schedule_is_success_and_unrelated_checkbox_is_untouched(preparation, editor):
    await editor.set_content(
        '<label><input type="checkbox" id="unrelated" checked>Keep my setting</label>'
        '<p>Learn about Publish at a later date in Help</p><input type="file" hidden>'
    )
    assert await preparation._ensure_immediate_publish(editor, timeout_seconds=2)
    assert await editor.locator("#unrelated").is_checked()


@pytest.mark.asyncio
async def test_schedule_that_remains_checked_is_failure(preparation, editor):
    await editor.set_content(
        '<div data-test-id="pin-draft-switch-group">'
        '<input type="checkbox" id="schedule" checked onchange="this.checked=true">'
        "Publish at a later date</div>"
    )
    assert not await preparation._ensure_immediate_publish(editor, timeout_seconds=0.2)
    assert await editor.locator("#schedule").is_checked()

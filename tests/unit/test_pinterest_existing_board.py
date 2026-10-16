from __future__ import annotations

import ast
import re
import time
import unicodedata
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright


@pytest.fixture
def board_core():
    # Load only the uploader functions: importing the full CLI initializes
    # production log/circuit singletons, which these DOM tests must never use.
    path = Path(__file__).resolve().parents[2] / "backend/scripts/pinterest_batch_core.py"
    source = ast.parse(path.read_text(encoding="utf-8"))
    functions = [
        node
        for node in source.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and (
            node.name in {"select_board", "normalize_seo", "_submit_board_creation"}
            or node.name.startswith("_board_")
        )
    ]
    namespace = {
        "asyncio": SimpleNamespace(sleep=AsyncMock()),
        "re": re,
        "time": time,
        "unicodedata": unicodedata,
        "logger": Mock(),
        "circuit": Mock(can_execute=Mock(return_value=True)),
        "resolve_account_board_name": lambda board, account: board,
        "is_browser_session_lost": lambda error: False,
        "BrowserSessionLost": type("BrowserSessionLost", (Exception,), {}),
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)  # noqa: S102
    return SimpleNamespace(**namespace)


@pytest_asyncio.fixture
async def board_page(monkeypatch):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        await context.route("**/*", lambda route: route.abort())
        page = await context.new_page()
        monkeypatch.setattr(page, "screenshot", AsyncMock())
        try:
            yield page
        finally:
            await context.close()
            await browser.close()


def _picker_html(*, update_selection=True, duplicate_recovery=False, board="Chocolate"):
    # Pinterest rows contain counts/visibility metadata and do not always carry
    # role=listitem. A successful selection replaces the dropdown DOM node.
    selected_text = "Board<br>Chocolate" if update_selection else "Board<br>Aperitivos"
    return f"""
        <button data-test-id="board-dropdown-select-button"
                onclick="document.querySelector('#picker').hidden=false">Board<br>Aperitivos</button>
        <div id="picker" data-test-id="board-picker-flyout" hidden>
          <input placeholder="Search">
          <div id="existing" data-test-id="boardWithoutSection"
               {"hidden" if duplicate_recovery else ""} onclick="chooseBoard()">
            <button><span>{board}</span><br><span>29 Pins</span><br><span>Secret</span></button>
          </div>
          <button data-test-id="create-board-button" onclick="openCreate()">Create board</button>
        </div>
        <div id="creation" role="dialog" hidden>
          <label for="boardEditName">Name</label><input id="boardEditName">
          <p>Try a different name. You already have a board with this name!</p>
          <button onclick="cancelCreate()">Cancel</button><button disabled>Create</button>
        </div>
        <script>
          window.creationAttempts=0;
          function chooseBoard() {{
            document.querySelector('#picker').hidden=true;
            const old=document.querySelector('[data-test-id="board-dropdown-select-button"]');
            const fresh=old.cloneNode(true);
            fresh.innerHTML='{selected_text}';
            old.replaceWith(fresh);
          }}
          function openCreate() {{
            window.creationAttempts++;
            document.querySelector('#picker').hidden=true;
            document.querySelector('#creation').hidden=false;
          }}
          function cancelCreate() {{
            document.querySelector('#creation').hidden=true;
            document.querySelector('#existing').hidden=false;
          }}
        </script>
    """


@pytest.mark.unit
@pytest.mark.asyncio
async def test_existing_board_with_metadata_uses_fresh_selected_field(board_core, board_page):
    await board_page.set_content(_picker_html())

    assert await board_core.select_board(board_page, "Chocolate", "driver-rida") is True
    assert await board_page.evaluate("window.creationAttempts") == 0
    board_core.circuit.record_success.assert_called_once_with("board_selection:driver-rida")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_existing_board_click_without_verified_selection_never_creates(board_core, board_page):
    await board_page.set_content(_picker_html(update_selection=False))

    assert await board_core.select_board(board_page, "Chocolate", "driver-rida") is False
    assert await board_page.evaluate("window.creationAttempts") == 0
    board_core.circuit.record_success.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_duplicate_name_modal_recovers_existing_board_without_resubmission(board_core, board_page):
    await board_page.set_content(_picker_html(duplicate_recovery=True))

    assert await board_core.select_board(board_page, "Chocolate", "driver-rida") is True
    assert await board_page.evaluate("window.creationAttempts") == 1
    assert not await board_page.locator("#creation").is_visible()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_similar_board_name_does_not_verify_requested_board(board_core, board_page):
    await board_page.set_content(_picker_html(board="Chocolate blanco"))

    assert await board_core.select_board(board_page, "Chocolate", "driver-rida") is False
    board_core.circuit.record_success.assert_not_called()

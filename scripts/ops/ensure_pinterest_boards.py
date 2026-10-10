"""
RankStein Ops — Automatic Pinterest Board Provisioning
Ensures all required live boards exist for all configured Pinterest accounts.
Creates missing boards automatically so new accounts never fail board selection.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from backend.scripts.pinterest_batch_core import (
    cleanup_session_artifacts,
    ensure_logged_in,
    load_accounts,
    pinterest_session_valid,
)
from pinterest_automation.config import LIVE_BOARD_NAMES
from scripts.ops.clear_pinterest_drafts import clear_drafts_for_page

logger = logging.getLogger("rankstein.ensure_boards")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


async def ensure_boards_for_account(
    account,
    boards_to_ensure: list[str] | None = None,
) -> dict:
    """Ensure all required live boards exist for a single Pinterest account."""
    account_name = getattr(account, "name", str(account))
    session_dir = getattr(account, "session_dir", None) or (project_root / "data" / "sessions" / account_name)
    browser_type = getattr(account, "browser", "chromium")
    email = getattr(account, "email", "")
    password = getattr(account, "password", "")
    boards = boards_to_ensure or sorted(LIVE_BOARD_NAMES)

    logger.info(f"--- ENSURING BOARDS FOR ACCOUNT: {account_name} ({browser_type}) ---")
    cleanup_session_artifacts(Path(session_dir), browser_type)

    created_boards = []
    existing_boards = []
    proof_screenshots = []
    screenshots_dir = project_root / "data" / "reports" / "screenshots" / "board_provisioning"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    # Use a dummy or existing test image so board selector is enabled
    test_img = project_root / "data" / "debug_dd_creation.png"
    if not test_img.exists():
        # Fallback search for any existing image
        images = list((project_root / "data").glob("**/*.png"))
        test_img = next((img for img in images if img.is_file()), test_img)

    try:
        async with async_playwright() as p:
            browser_launcher = p.chromium if browser_type == "chromium" else p.firefox
            context = await browser_launcher.launch_persistent_context(
                user_data_dir=str(session_dir),
                headless=True,
                viewport={"width": 1280, "height": 800},
                args=["--no-sandbox", "--disable-dev-shm-usage"] if browser_type == "chromium" else [],
            )
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                # 1. Login Preflight
                is_valid = await pinterest_session_valid(page)
                if not is_valid and email and password:
                    logger.info(f"[{account_name}] Session invalid or unauthenticated; logging in first...")
                    logged_in = await ensure_logged_in(page, email, password)
                    if not logged_in:
                        logger.warning(f"[{account_name}] Authentication failed before board provisioning.")
                        fail_path = screenshots_dir / f"{account_name}_auth_fail_{timestamp}.png"
                        await page.screenshot(path=str(fail_path))
                        proof_screenshots.append(str(fail_path))
                        return {
                            "account": account_name,
                            "ok": False,
                            "error": "Authentication failed",
                            "created_boards": [],
                            "existing_boards": [],
                            "proof_screenshots": proof_screenshots,
                        }

                # 2. Open Pin Creation Tool
                await page.goto("https://www.pinterest.com/pin-creation-tool/", wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(4)

                # Clear preexisting drafts first
                await clear_drafts_for_page(page, account_name=account_name)

                # Upload image to unlock board selector
                if test_img.exists():
                    file_input = await page.wait_for_selector('input[type="file"]', timeout=30000)
                    await file_input.set_input_files(str(test_img.resolve()))
                    await asyncio.sleep(4)

                # 3. Provision Each Required Board
                for board_name in boards:
                    target_norm = board_name.strip().lower()
                    try:
                        # Open dropdown
                        board_btn = page.locator(
                            '[data-test-id="board-dropdown-select-button"], [aria-label*="Choose a board" i]'
                        ).first
                        await board_btn.scroll_into_view_if_needed()
                        await board_btn.click(force=True)
                        await asyncio.sleep(1.5)

                        flyout = page.locator('[data-test-id="board-picker-flyout"]').first
                        if await flyout.count() > 0:
                            search_input = flyout.locator('input').first
                            if await search_input.count() > 0:
                                await search_input.fill(board_name)
                                await asyncio.sleep(1.5)

                            # Check if board already exists
                            rows = flyout.locator('[data-test-id="boardWithoutSection"], [role="option"]')
                            already_exists = False
                            for i in range(await rows.count()):
                                r_text = (await rows.nth(i).inner_text()).strip().lower()
                                if r_text == target_norm:
                                    already_exists = True
                                    existing_boards.append(board_name)
                                    logger.info(f"[{account_name}] Board '{board_name}' already exists.")
                                    await page.keyboard.press("Escape")
                                    await asyncio.sleep(1)
                                    break

                            if already_exists:
                                continue

                            # Click Create board
                            create_btn = flyout.locator('[data-test-id="create-board-button"]').first
                            if await create_btn.count() > 0 and await create_btn.is_visible():
                                logger.info(f"[{account_name}] Creating missing board '{board_name}'...")
                                await create_btn.click(force=True)
                                await asyncio.sleep(1.5)

                                dialog = page.locator(
                                    '[role="dialog"]:has(#boardEditName), [role="dialog"][aria-label*="Board" i]'
                                ).first
                                if await dialog.count() > 0:
                                    name_input = dialog.locator('#boardEditName, input[name="name"]').first
                                    if await name_input.count() > 0:
                                        await name_input.fill(board_name)
                                        await asyncio.sleep(0.5)

                                    submit_btn = dialog.locator(
                                        '[data-test-id="board-form-submit-button"], button:has-text("Create"), button:has-text("Crear")'
                                    ).first
                                    if await submit_btn.count() > 0:
                                        await submit_btn.click(force=True)
                                        await asyncio.sleep(3)
                                        created_boards.append(board_name)
                                        logger.info(f"[{account_name}] Successfully created board: '{board_name}'")
                    except Exception as b_err:
                        logger.warning(f"[{account_name}] Board check/create error for '{board_name}': {b_err}")
                        try:
                            await page.keyboard.press("Escape")
                        except Exception:
                            pass

                # 4. Clean up the draft generated by uploading test image
                await clear_drafts_for_page(page, account_name=account_name)

                # 5. Capture Final Visual Proof
                proof_path = screenshots_dir / f"{account_name}_boards_verified_{timestamp}.png"
                await page.screenshot(path=str(proof_path))
                proof_screenshots.append(str(proof_path))
                logger.info(f"[{account_name}] Captured boards verification proof: {proof_path.name}")

            finally:
                await context.close()

    except Exception as exc:
        logger.error(f"[{account_name}] Failed to provision boards: {exc}")
        return {
            "account": account_name,
            "ok": False,
            "error": str(exc),
            "created_boards": created_boards,
            "existing_boards": existing_boards,
            "proof_screenshots": proof_screenshots,
        }

    return {
        "account": account_name,
        "ok": True,
        "created_boards": created_boards,
        "existing_boards": existing_boards,
        "proof_screenshots": proof_screenshots,
    }


async def main():
    load_dotenv()
    target_handles = set(sys.argv[1:]) if len(sys.argv) > 1 else set()
    accounts = load_accounts()
    if target_handles:
        accounts = [a for a in accounts if a.name in target_handles]

    logger.info(f"Provisioning boards for {len(accounts)} accounts: {[a.name for a in accounts]}")
    for acc in accounts:
        res = await ensure_boards_for_account(acc)
        logger.info(f"Result for {acc.name}: {res}")


if __name__ == "__main__":
    asyncio.run(main())

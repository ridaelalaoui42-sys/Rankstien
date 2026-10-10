import asyncio
import logging
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from backend.scripts.pinterest_batch_core import cleanup_session_artifacts, load_accounts

logger = logging.getLogger("rankstein.clear_drafts")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


async def clear_drafts_for_page(page, account_name: str = "account") -> int:
    """Clear drafts in the current creator page.

    Returns the number of drafts purged (or 0 if already 0).
    """
    total_deleted = 0
    for loop in range(1, 4):
        logger.info(f"[{account_name}] Purge check loop {loop}/3...")
        try:
            await page.goto(
                "https://www.pinterest.com/pin-creation-tool/",
                wait_until="domcontentloaded",
                timeout=45000,
            )
            # Give UI time to render draft drawer / counter
            await asyncio.sleep(4)

            # Check if redirected to login
            if "login" in page.url:
                logger.warning(f"[{account_name}] Redirected to login page; session may require re-auth.")
                break

            # 1. Expand / open drafts drawer if collapsed
            drawer_toggles = [
                '[data-test-id="side-navigation-toggle"]',
                '[data-test-id="drafts-drawer-toggle"]',
                '[data-test-id="open-drafts-button"]',
                'button[aria-label*="draft" i]',
                'button[aria-label*="borrador" i]',
                'button:has-text("Drafts")',
                'button:has-text("Borradores")',
            ]
            for toggle_sel in drawer_toggles:
                try:
                    toggle_btn = page.locator(toggle_sel).first
                    if await toggle_btn.count() > 0 and await toggle_btn.is_visible(timeout=500):
                        await toggle_btn.click(force=True)
                        await asyncio.sleep(1)
                        break
                except Exception:
                    continue

            # Check draft count
            content = await page.content()
            count_match = re.search(r"(?:Pin drafts|Borradores de pines|Drafts|Borradores)\s*\((\d+)\)", content, re.I)
            if count_match:
                draft_count = int(count_match.group(1))
                logger.info(f"[{account_name}] Detected {draft_count} draft(s).")
                if draft_count == 0:
                    logger.info(f"[{account_name}] No drafts remaining.")
                    break
            elif "Pin drafts (0)" in content or "Borradores de pines (0)" in content:
                logger.info(f"[{account_name}] Zero drafts found. Purge complete.")
                break

            # 2. Bulk Select Checkbox
            bulk_selectors = [
                '[data-test-id="bulk-select-drafts-checkbox"]',
                'input[type="checkbox"][aria-label*="Select all" i]',
                'input[type="checkbox"][aria-label*="Seleccionar todo" i]',
                'div[role="checkbox"][aria-label*="Select all" i]',
                'button:has-text("Select all")',
                'button:has-text("Seleccionar todo")',
            ]
            bulk_clicked = False
            for b_sel in bulk_selectors:
                try:
                    bulk = page.locator(b_sel).first
                    if await bulk.count() > 0 and await bulk.is_visible(timeout=1000):
                        await bulk.click(force=True)
                        bulk_clicked = True
                        logger.info(f"[{account_name}] Clicked Bulk Select ({b_sel})")
                        await asyncio.sleep(2)
                        break
                except Exception:
                    continue

            # 3. If bulk select clicked, click Bulk Delete
            if bulk_clicked:
                delete_selectors = [
                    '[data-test-id="bulk-delete-drafts-button"]',
                    '[data-test-id="delete-drafts-button"]',
                    'button:has-text("Delete")',
                    'button:has-text("Eliminar")',
                    '[aria-label*="Delete" i]',
                    '[aria-label*="Eliminar" i]',
                ]
                delete_clicked = False
                for d_sel in delete_selectors:
                    try:
                        del_btn = page.locator(d_sel).first
                        if await del_btn.count() > 0 and await del_btn.is_visible(timeout=1500):
                            await del_btn.click(force=True)
                            delete_clicked = True
                            logger.info(f"[{account_name}] Clicked Delete button ({d_sel})")
                            await asyncio.sleep(2)
                            break
                    except Exception:
                        continue

                if delete_clicked:
                    # 4. Confirm in dialog
                    confirm_selectors = [
                        'div[role="dialog"] button:has-text("Delete")',
                        'div[role="dialog"] button:has-text("Eliminar")',
                        '[data-test-id="confirm-delete-button"]',
                        'button:has-text("Delete")',
                        'button:has-text("Eliminar")',
                    ]
                    confirmed = False
                    for c_sel in confirm_selectors:
                        try:
                            conf_btn = page.locator(c_sel).first
                            if await conf_btn.count() > 0 and await conf_btn.is_visible(timeout=2000):
                                await conf_btn.click(force=True)
                                confirmed = True
                                total_deleted += 1
                                logger.info(f"[{account_name}] Confirmed delete via {c_sel}")
                                await asyncio.sleep(4)
                                break
                        except Exception:
                            continue
                    if not confirmed:
                        await page.keyboard.press("Enter")
                        await asyncio.sleep(3)

            # Fallback: Individual draft actions delete if bulk select wasn't available
            if not bulk_clicked:
                action_buttons = page.locator(
                    'button[aria-label*="draft actions" i], [data-test-id="draft-actions-button"], [data-test-id="pin-draft-actions-button"]'
                )
                action_count = await action_buttons.count()
                if action_count > 0:
                    logger.info(f"[{account_name}] Bulk select unavailable; deleting {min(action_count, 10)} individual drafts...")
                    for idx in range(min(action_count, 10)):
                        try:
                            btn = action_buttons.first
                            if await btn.count() > 0:
                                await btn.click(force=True)
                                await asyncio.sleep(0.5)
                                del_action = page.locator(
                                    '[data-test-id="delete-draft-action"], button:has-text("Delete"), button:has-text("Eliminar")'
                                ).first
                                if await del_action.count() > 0:
                                    await del_action.click(force=True)
                                    await asyncio.sleep(0.5)
                                    conf = page.locator('div[role="dialog"] button:has-text("Delete"), button:has-text("Delete")').first
                                    if await conf.count() > 0:
                                        await conf.click(force=True)
                                        total_deleted += 1
                                        await asyncio.sleep(1)
                        except Exception as e:
                            logger.warning(f"[{account_name}] Individual draft deletion error: {e}")
                            break
                else:
                    logger.info(f"[{account_name}] No draft actions or bulk checkbox detected; page may have 0 drafts.")
                    break

        except Exception as e:
            logger.warning(f"[{account_name}] Purge loop {loop} error: {e}")

    return total_deleted


async def aggressive_clear(account) -> dict:
    account_name = getattr(account, "name", str(account))
    session_dir = getattr(account, "session_dir", None) or (project_root / "data" / "sessions" / account_name)
    browser_type = getattr(account, "browser", "chromium")
    email = getattr(account, "email", "")
    password = getattr(account, "password", "")

    logger.info(f"--- DRAFT PURGE START: {account_name} ({browser_type}) ---")
    cleanup_session_artifacts(Path(session_dir), browser_type)

    deleted = 0
    proof_screenshots = []
    screenshots_dir = project_root / "data" / "reports" / "screenshots" / "draft_clearing"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")

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
                # 1. Ensure account is logged in BEFORE clearing drafts
                from backend.scripts.pinterest_batch_core import pinterest_session_valid, ensure_logged_in
                is_valid = await pinterest_session_valid(page)
                if not is_valid and email and password:
                    logger.info(f"[{account_name}] Session invalid or unauthenticated, logging in first...")
                    logged_in = await ensure_logged_in(page, email, password)
                    if not logged_in:
                        logger.warning(f"[{account_name}] Authentication failed before draft clear; capturing proof.")
                        fail_path = screenshots_dir / f"{account_name}_auth_fail_{timestamp}.png"
                        await page.screenshot(path=str(fail_path))
                        proof_screenshots.append(str(fail_path))
                        return {
                            "account": account_name,
                            "ok": False,
                            "error": "Authentication failed before draft clear",
                            "deleted": 0,
                            "proof_screenshots": proof_screenshots,
                        }
                elif not is_valid:
                    logger.warning(f"[{account_name}] Session invalid and no email/password credentials available.")

                # 2. Capture Initial Creator State Screenshot
                await page.goto("https://www.pinterest.com/pin-creation-tool/", wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(3)
                before_path = screenshots_dir / f"{account_name}_before_{timestamp}.png"
                await page.screenshot(path=str(before_path))
                proof_screenshots.append(str(before_path))
                logger.info(f"[{account_name}] Captured initial visual proof: {before_path.name}")

                # 3. Clear Drafts
                deleted = await clear_drafts_for_page(page, account_name)

                # 4. Capture Final Verified State Screenshot
                await asyncio.sleep(2)
                after_path = screenshots_dir / f"{account_name}_after_{timestamp}.png"
                await page.screenshot(path=str(after_path))
                proof_screenshots.append(str(after_path))
                logger.info(f"[{account_name}] Captured final visual proof: {after_path.name}")

            finally:
                await context.close()
    except Exception as exc:
        logger.error(f"[{account_name}] Purge session failed: {exc}")
        return {
            "account": account_name,
            "ok": False,
            "error": str(exc),
            "deleted": deleted,
            "proof_screenshots": proof_screenshots,
        }

    logger.info(f"--- DRAFT PURGE COMPLETE: {account_name} (deleted={deleted}, proofs={len(proof_screenshots)}) ---")
    return {
        "account": account_name,
        "ok": True,
        "deleted": deleted,
        "proof_screenshots": proof_screenshots,
    }


async def clear_all_accounts_drafts() -> list[dict]:
    """Purge drafts for all configured Pinterest accounts."""
    load_dotenv()
    accounts = load_accounts()
    if not accounts:
        logger.warning("No configured Pinterest accounts found to clear drafts.")
        return []

    results = []
    for acc in accounts:
        res = await aggressive_clear(acc)
        results.append(res)
    return results


async def main():
    results = await clear_all_accounts_drafts()
    logger.info(f"Finished clearing drafts for {len(results)} accounts: {results}")


if __name__ == "__main__":
    asyncio.run(main())

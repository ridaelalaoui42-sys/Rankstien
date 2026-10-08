import argparse
import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "scripts"))

from backend.scripts.pinterest_batch_core import (
    close_turbo_browser,
    create_turbo_browser,
    ensure_account_logged_in,
    load_accounts,
)


def now_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


async def click_first_visible(page, locators, timeout=1200) -> bool:
    for locator in locators:
        try:
            count = await locator.count()
        except Exception:
            continue
        for index in range(count):
            item = locator.nth(index)
            try:
                if await item.is_visible(timeout=timeout):
                    await item.click(force=True, timeout=3000)
                    await asyncio.sleep(1.5)
                    return True
            except Exception:
                continue
    return False


async def draft_count(page) -> int | None:
    try:
        text = await page.locator("body").inner_text(timeout=2000)
    except Exception:
        return None
    match = re.search(r"Pin drafts\s*\((\d+)\)", text, re.I)
    if match:
        return int(match.group(1))
    if "Pin drafts" not in text and re.search(r"Create Pin|Create new", text, re.I):
        return 0
    if re.search(r"No drafts|Create new", text, re.I):
        return 0
    return None


async def select_all_drafts(page) -> bool:
    async def delete_button_present() -> bool:
        try:
            button = page.locator('[data-test-id="bulk-delete-drafts-button"]').first
            return bool(await button.count() and await button.is_visible(timeout=800))
        except Exception:
            return False

    selectors = [
        "#storyboard-drafts-sidebar-bulk-select-checkbox",
        '[data-test-id="bulk-select-drafts-checkbox"] input[type="checkbox"]',
        'label[for="storyboard-drafts-sidebar-bulk-select-checkbox"]',
    ]
    for selector in selectors:
        try:
            checkbox = page.locator(selector).last
            if await checkbox.count() and await checkbox.is_visible(timeout=1200):
                if selector.endswith('input[type="checkbox"]') or selector.startswith("#"):
                    checked = await checkbox.is_checked()
                    if checked and await delete_button_present():
                        return True
                await checkbox.click(force=True, timeout=3000)
                await asyncio.sleep(1.5)
                if await delete_button_present():
                    return True
        except Exception:
            continue

    locators = [
        page.locator('[data-test-id="bulk-select-drafts-checkbox"] input'),
        page.locator('[data-test-id="bulk-select-drafts-checkbox"]'),
        page.locator("label").filter(has_text=re.compile(r"^Select all$|^Seleccionar todo$", re.I)),
        page.get_by_role("checkbox", name=re.compile(r"Select all|Seleccionar todo", re.I)),
    ]
    for locator in locators:
        if await click_first_visible(page, [locator]):
            await asyncio.sleep(1)
            if await delete_button_present():
                return True

    # Pinterest currently renders the bulk selector as a sticky bottom-left checkbox.
    try:
        await page.mouse.click(30, 865)
        await asyncio.sleep(1.5)
        if await delete_button_present():
            return True
    except Exception:
        pass
    return False


async def click_delete(page) -> bool:
    locators = [
        page.locator('[data-test-id="bulk-delete-drafts-button"]'),
        page.get_by_role("button", name=re.compile(r"Delete|Eliminar|Remove", re.I)),
        page.locator('button[aria-label*="Delete" i]'),
        page.locator('button[aria-label*="Eliminar" i]'),
        page.locator('[data-test-id*="delete" i]'),
    ]
    if await click_first_visible(page, locators):
        return True

    # Last resort: identify a visible trash/delete icon button by accessible text or SVG label.
    try:
        clicked = await page.evaluate(
            """() => {
                const visible = (el) => {
                    const r = el.getBoundingClientRect();
                    const s = window.getComputedStyle(el);
                    return !!(r.width && r.height) && s.display !== 'none' && s.visibility !== 'hidden';
                };
                const buttons = Array.from(document.querySelectorAll('button, [role="button"]'));
                const target = buttons.find((button) => {
                    if (!visible(button)) return false;
                    const text = [
                        button.innerText || '',
                        button.textContent || '',
                        button.getAttribute('aria-label') || '',
                        ...Array.from(button.querySelectorAll('svg, path, title')).map((el) => el.getAttribute('aria-label') || el.textContent || '')
                    ].join(' ');
                    return /delete|eliminar|trash|remove/i.test(text);
                });
                if (!target) return false;
                target.click();
                return true;
            }"""
        )
        if clicked:
            await asyncio.sleep(1.5)
            return True
    except Exception:
        pass
    return False


async def confirm_delete(page) -> bool:
    return await click_first_visible(
        page,
        [
            page.locator('[role="dialog"] button').filter(
                has_text=re.compile(r"^Delete$|^Eliminar$|^Remove$", re.I)
            ),
            page.get_by_role("button", name=re.compile(r"^Delete$|^Eliminar$|^Remove$", re.I)),
            page.locator('[data-test-id*="confirm" i] button').filter(
                has_text=re.compile(r"Delete|Eliminar|Remove", re.I)
            ),
            page.locator('button[type="submit"]').filter(
                has_text=re.compile(r"Delete|Eliminar|Remove", re.I)
            ),
        ],
        timeout=1800,
    )


async def delete_single_visible_draft(page) -> bool:
    actions = [
        page.locator('button[aria-label="Pin draft actions"]'),
        page.locator('[data-test-id="pin-draft-actions"] button'),
    ]
    if not await click_first_visible(page, actions):
        return False
    if not await click_first_visible(
        page,
        [
            page.locator('[data-test-id="delete-draft-action"]'),
            page.locator('[role="menu"] [role="menuitem"]').filter(
                has_text=re.compile(r"^Delete$|^Eliminar$|^Remove$", re.I)
            ),
            page.get_by_role("menuitem", name=re.compile(r"^Delete$|^Eliminar$|^Remove$", re.I)),
        ],
        timeout=1800,
    ):
        return False
    return await confirm_delete(page)


async def clear_account(account, run_id: str) -> dict:
    result = {
        "account": account.name,
        "session": account.session_dir.name,
        "browser": account.browser,
        "started_at": datetime.now(UTC).isoformat(),
    }
    pw = context = page = None
    try:
        pw, context, page = await create_turbo_browser(account, f"draft-clear-{account.name}", headless=True)
        if not await ensure_account_logged_in(page, account):
            raise RuntimeError("Pinterest session is not logged in")
        await page.goto("https://www.pinterest.com/pin-creation-tool/", wait_until="commit", timeout=90000)
        await asyncio.sleep(8)
        before = await draft_count(page)
        result["drafts_before"] = before
        if not before:
            result["success"] = True
            result["deleted"] = 0
            return result

        if await select_all_drafts(page):
            if not await click_delete(page):
                raise RuntimeError("Draft delete button not found after selecting drafts")
            if not await confirm_delete(page):
                raise RuntimeError("Draft delete confirmation button not found")
            result["delete_mode"] = "bulk"
        elif before == 1 and await delete_single_visible_draft(page):
            result["delete_mode"] = "single"
        else:
            raise RuntimeError("Select all drafts checkbox not found")

        after = None
        for _ in range(20):
            await asyncio.sleep(2)
            after = await draft_count(page)
            if after is not None and after < before:
                break
        try:
            await page.reload(wait_until="domcontentloaded", timeout=60000)
        except Exception:
            await page.goto(
                "https://www.pinterest.com/pin-creation-tool/", wait_until="commit", timeout=60000
            )
        await asyncio.sleep(5)
        after = await draft_count(page)
        result["drafts_after"] = after
        result["deleted"] = None if after is None else max(0, (before or 0) - after)
        result["success"] = after == 0 or (after is not None and after < before)
        return result
    except Exception as exc:
        result["success"] = False
        result["error"] = str(exc)
        if page:
            screenshot = PROJECT_ROOT / "data" / f"draft_clear_failed_{account.name}_{run_id}.png"
            try:
                await page.screenshot(path=str(screenshot), full_page=True)
                result["screenshot"] = str(screenshot)
            except Exception:
                pass
        return result
    finally:
        try:
            await close_turbo_browser(pw, context)
        finally:
            result["finished_at"] = datetime.now(UTC).isoformat()


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", action="append", help="Account handle to clear. Can be repeated.")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env", override=True)
    accounts = load_accounts()
    if args.account:
        wanted = set(args.account)
        accounts = [account for account in accounts if account.name in wanted]
    if not accounts:
        raise RuntimeError("No matching Pinterest accounts configured")

    run_id = now_id()
    report = {
        "run_id": run_id,
        "started_at": datetime.now(UTC).isoformat(),
        "accounts": [],
    }
    for account in accounts:
        report["accounts"].append(await clear_account(account, run_id))
    report["finished_at"] = datetime.now(UTC).isoformat()

    report_path = PROJECT_ROOT / "data" / "reports" / f"pinterest_draft_clear_{run_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        json.dumps({"report": str(report_path), "accounts": report["accounts"]}, indent=2, ensure_ascii=False)
    )
    return 0 if all(item.get("success") for item in report["accounts"]) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

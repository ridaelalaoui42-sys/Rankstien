import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from backend.scripts.pinterest_batch_core import cleanup_session_artifacts, load_accounts


async def aggressive_clear(account):
    print(f"--- AGGRESSIVE PURGE for: {account.name} ---")
    cleanup_session_artifacts(account.session_dir, account.browser)

    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=str(account.session_dir), headless=True, viewport={"width": 1280, "height": 800}
        )
        page = browser.pages[0] if browser.pages else await browser.new_page()

        for loop in range(1, 6):
            print(f"Purge Loop {loop}/5...")
            try:
                await page.goto(
                    "https://www.pinterest.com/pin-creation-tool/",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                await asyncio.sleep(15)

                # Check current count
                content = await page.content()
                if "Pin drafts (0)" in content:
                    print("No drafts left! Purge complete.")
                    break

                # 1. Bulk Select
                print("Clicking Bulk Select...")
                bulk = page.locator('[data-test-id="bulk-select-drafts-checkbox"]').first
                if await bulk.count() > 0:
                    await bulk.click(force=True)
                    await asyncio.sleep(3)

                    # 2. Delete
                    print("Clicking Delete...")
                    # Try by testid and by text
                    delete_btn = page.locator('[data-test-id="bulk-delete-drafts-button"]').first
                    if await delete_btn.count() == 0:
                        delete_btn = page.locator(
                            'button:has-text("Delete"), button:has-text("Eliminar")'
                        ).first

                    if await delete_btn.count() > 0:
                        await delete_btn.click(force=True)
                        await asyncio.sleep(3)

                        # 3. Confirm Modal
                        print("Confirming...")
                        conf_btn = page.locator(
                            'div[role="dialog"] button:has-text("Delete"), div[role="dialog"] button:has-text("Eliminar")'
                        ).first
                        if await conf_btn.count() > 0:
                            await conf_btn.click(force=True)
                            print("Sent CONFIRM.")
                            await asyncio.sleep(8)  # Wait for backend sync
                        else:
                            # Try keyboard fallback
                            await page.keyboard.press("Enter")
                    else:
                        print("Delete button not revealed.")
                else:
                    print("Bulk select not found.")
            except Exception as e:
                print(f"Loop error: {e}")

            await page.screenshot(path=f"data/purge_loop_{loop}_{account.name}.png")

        await browser.close()


async def main():
    load_dotenv()
    accounts = load_accounts()
    for acc in accounts:
        await aggressive_clear(acc)


if __name__ == "__main__":
    asyncio.run(main())

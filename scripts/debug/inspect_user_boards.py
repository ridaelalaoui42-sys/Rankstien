import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

async def inspect():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir="data/sessions/DD",
            headless=True,
            viewport={"width": 1280, "height": 800},
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.goto("https://www.pinterest.com/", wait_until="domcontentloaded")
            await asyncio.sleep(3)
            links = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('header a')).map(a => a.href);
            }""")
            print("Header links:", links)
            
            # Go directly to pin creation tool
            await page.goto("https://www.pinterest.com/pin-creation-tool/", wait_until="domcontentloaded")
            await asyncio.sleep(4)
            
            # Look at the board container
            board_field = page.locator('[data-test-id="board-dropdown-select-button"], div:has-text("Choose a board")').first
            print("Board field text:", await board_field.inner_text() if await board_field.count() else "Not found")
            
            # Click the board field
            await board_field.click()
            await asyncio.sleep(2)
            
            # Take screenshot of what pops up when board field is clicked
            popup_path = Path("data/reports/screenshots/medridaelalaoui6_board_popup.png")
            await page.screenshot(path=str(popup_path))
            print(f"Popup screenshot saved: {popup_path}")
            
            # Extract all elements inside any dialog / popover
            popover_items = await page.evaluate("""() => {
                const dialogs = document.querySelectorAll('[role="dialog"], [role="listbox"], [data-test-id="board-dropdown"], div[style*="z-index"]');
                return Array.from(dialogs).map(d => ({
                    role: d.getAttribute('role'),
                    text: (d.innerText || '').slice(0, 500)
                }));
            }""")
            print("Popover items:", json.dumps(popover_items, indent=2))
        finally:
            await context.close()

if __name__ == "__main__":
    asyncio.run(inspect())

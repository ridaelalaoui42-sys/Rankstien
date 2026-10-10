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
            # 1. Inspect on profile page
            await page.goto("https://www.pinterest.com/me/_saved/", wait_until="domcontentloaded")
            await asyncio.sleep(4)
            btns = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('button, [role="button"], a[href*="create"], [data-test-id]')).map(b => ({
                    tag: b.tagName,
                    text: (b.innerText || '').trim().slice(0, 50),
                    aria: b.getAttribute('aria-label') || '',
                    testid: b.getAttribute('data-test-id') || '',
                    href: b.getAttribute('href') || ''
                })).filter(x => x.text || x.aria || x.testid || x.href);
            }""")
            print("Buttons on /me/_saved/:", json.dumps(btns[:30], indent=2))
            
            # 2. Inspect inside pin creation tool when clicking board dropdown
            await page.goto("https://www.pinterest.com/pin-creation-tool/", wait_until="domcontentloaded")
            await asyncio.sleep(4)
            
            # Click board selector
            board_btn = page.locator(
                '[data-test-id="board-dropdown-select-button"], [aria-label*="Choose a board" i], button:has-text("Choose a board")'
            ).first
            
            if await board_btn.count() > 0:
                print("Clicking board_btn...")
                await board_btn.click()
                await asyncio.sleep(2)
                
                # Check for search input in dropdown
                search = page.locator('input[placeholder*="Search" i], input[placeholder*="Buscar" i], input[aria-label*="Search" i]').first
                if await search.count() > 0:
                    print("Found search input! Typing 'Aperitivos'...")
                    await search.fill("Aperitivos")
                    await asyncio.sleep(2)
                
                # Take screenshot of board dropdown state
                drop_ss = Path("data/reports/screenshots/medridaelalaoui6_board_search.png")
                await page.screenshot(path=str(drop_ss))
                print(f"Board search screenshot: {drop_ss}")
                
                # Find all buttons / elements inside dropdown/dialog
                dropdown_elements = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('[role="dialog"], [role="listbox"], [data-test-id*="board"], [data-test-id*="create"]')).map(el => ({
                        tag: el.tagName,
                        testid: el.getAttribute('data-test-id') || '',
                        aria: el.getAttribute('aria-label') || '',
                        text: (el.innerText || '').slice(0, 100)
                    }));
                }""")
                print("Dropdown elements:", json.dumps(dropdown_elements, indent=2))
            else:
                print("board_btn not found")
        finally:
            await context.close()

if __name__ == "__main__":
    asyncio.run(inspect())

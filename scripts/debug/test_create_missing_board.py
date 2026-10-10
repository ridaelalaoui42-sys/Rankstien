import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

async def test_create_missing_board():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir="data/sessions/DD",
            headless=True,
            viewport={"width": 1280, "height": 800},
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            test_img = Path("data/debug_dd_creation.png")
            await page.goto("https://www.pinterest.com/pin-creation-tool/", wait_until="domcontentloaded")
            await asyncio.sleep(4)
            
            file_input = await page.wait_for_selector('input[type="file"]', timeout=30000)
            await file_input.set_input_files(str(test_img.resolve()))
            await asyncio.sleep(4)
            
            # Click board dropdown
            board_btn = page.locator('[data-test-id="board-dropdown-select-button"]').first
            await board_btn.click(force=True)
            await asyncio.sleep(2)
            
            # Type missing board "Arroces"
            search = page.locator('input[placeholder*="Search" i], input[placeholder*="Buscar" i], input[aria-label*="Search" i]').first
            if await search.count() > 0:
                print("Typing 'Arroces' in search...")
                await search.fill("Arroces")
                await asyncio.sleep(2)
            
            # Look for create board button specifically
            create_btn = page.locator('[data-test-id="create-board-button"]').first
            print("create-board-button count:", await create_btn.count())
            if await create_btn.count() > 0:
                print("create_btn text:", await create_btn.inner_text())
                await create_btn.scroll_into_view_if_needed()
                await create_btn.click(force=True)
                await asyncio.sleep(2)
            
            # Screenshot after clicking create-board-button
            after_click = Path("data/reports/screenshots/after_create_board_click.png")
            await page.screenshot(path=str(after_click))
            print(f"Screenshot saved: {after_click}")
            
            # Dump all visible inputs and buttons on page
            inputs_and_btns = await page.evaluate("""() => {
                const els = document.querySelectorAll('input, button, [role="button"], [role="dialog"]');
                return Array.from(els).filter(e => {
                    const r = e.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                }).map(e => ({
                    tag: e.tagName,
                    role: e.getAttribute('role'),
                    id: e.id,
                    placeholder: e.placeholder,
                    testid: e.getAttribute('data-test-id'),
                    aria: e.getAttribute('aria-label'),
                    text: (e.innerText || e.value || '').trim().slice(0, 50)
                }));
            }""")
            print("Visible interactive elements:", json.dumps(inputs_and_btns, indent=2))
            
        finally:
            await context.close()

if __name__ == "__main__":
    asyncio.run(test_create_missing_board())

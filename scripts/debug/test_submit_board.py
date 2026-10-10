import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

async def test_submit():
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
            
            board_btn = page.locator('[data-test-id="board-dropdown-select-button"]').first
            await board_btn.click(force=True)
            await asyncio.sleep(2)
            
            search = page.locator('input[placeholder*="Search" i], input[placeholder*="Buscar" i], input[aria-label*="Search" i]').first
            if await search.count() > 0:
                await search.fill("Arroces")
                await asyncio.sleep(2)
            
            create_btn = page.locator('[data-test-id="create-board-button"]').first
            if await create_btn.count() > 0:
                await create_btn.scroll_into_view_if_needed()
                await create_btn.click(force=True)
                await asyncio.sleep(2)
                
            # Click submit in modal
            submit_btn = page.locator('[data-test-id="board-form-submit-button"], button:has-text("Create"), button:has-text("Crear")').first
            if await submit_btn.count() > 0:
                print("Clicking submit button in Create Board modal...")
                await submit_btn.click(force=True)
                await asyncio.sleep(3)
                
            # Check what board is now selected
            board_btn = page.locator('[data-test-id="board-dropdown-select-button"]').first
            print("Selected board text:", (await board_btn.inner_text()).strip())
            
            after_created_ss = Path("data/reports/screenshots/after_board_created.png")
            await page.screenshot(path=str(after_created_ss))
            print(f"Screenshot saved: {after_created_ss}")
        finally:
            await context.close()

if __name__ == "__main__":
    asyncio.run(test_submit())

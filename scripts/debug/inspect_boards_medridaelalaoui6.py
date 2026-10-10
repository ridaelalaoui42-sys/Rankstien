import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

async def inspect_boards():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir="data/sessions/DD",
            headless=True,
            viewport={"width": 1280, "height": 800},
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.goto("https://www.pinterest.com/pin-creation-tool/", wait_until="domcontentloaded")
            await asyncio.sleep(4)
            
            dropdown = page.locator(
                '[data-test-id="board-dropdown-select-button"], [aria-label*="Choose a board" i], [aria-label*="Selecciona un tablero" i], button:has-text("Choose a board"), button:has-text("Selecciona un tablero")'
            ).first
            if await dropdown.count() > 0:
                print("Found dropdown button, text:", (await dropdown.inner_text()).strip())
                await dropdown.click(force=True)
                await asyncio.sleep(2)
                
                # Check for board rows
                rows = page.locator('[data-test-id="boardWithoutSection"], [role="option"], [role="listitem"]')
                count = await rows.count()
                print(f"Found {count} board rows/options")
                for i in range(count):
                    t = await rows.nth(i).inner_text()
                    print(f"  Board {i}: {t.strip()[:60]}")
                    
                # Look for Create Board button
                create_btns = page.locator(
                    '[data-test-id="create-board-button"], button:has-text("Create board"), button:has-text("Crear tablero")'
                )
                c_count = await create_btns.count()
                print(f"Found {c_count} create board buttons")
                for i in range(c_count):
                    print(f"  Create btn {i}: {(await create_btns.nth(i).inner_text()).strip()}")

                screenshot_path = Path("data/reports/screenshots/medridaelalaoui6_boards_dropdown.png")
                screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(screenshot_path))
                print(f"Screenshot saved to {screenshot_path}")
            else:
                print("Dropdown button NOT found")
                screenshot_path = Path("data/reports/screenshots/medridaelalaoui6_no_dropdown.png")
                await page.screenshot(path=str(screenshot_path))
                print(f"Screenshot saved to {screenshot_path}")
        finally:
            await context.close()

if __name__ == "__main__":
    asyncio.run(inspect_boards())

import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

async def test_upload_and_board():
    # Find an existing image in data/
    images = list(Path("data").glob("**/*.png")) + list(Path("data").glob("**/*.jpg"))
    test_img = next((img for img in images if img.is_file() and "screenshot" not in str(img)), None)
    if not test_img:
        # Create a small blank image for test
        from PIL import Image
        test_img = Path("data/reports/test_pin.png")
        Image.new("RGB", (800, 1200), color=(200, 100, 100)).save(test_img)
    
    print(f"Using test image: {test_img}")

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
            
            # Upload image
            file_input = await page.wait_for_selector('input[type="file"]', timeout=30000)
            await file_input.set_input_files(str(test_img.resolve()))
            print("Set input file, waiting 5s...")
            await asyncio.sleep(5)
            
            # Check board dropdown
            dropdown_selectors = [
                '[data-test-id="board-dropdown-select-button"]',
                '[aria-label*="Choose a board" i]',
                'button:has-text("Choose a board")',
                'div[role="button"]:has-text("Choose a board")',
            ]
            board_btn = None
            for sel in dropdown_selectors:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    board_btn = loc
                    print(f"Found visible board_btn with selector: {sel}")
                    break
                    
            if not board_btn:
                print("Board button not visible yet, taking screenshot...")
                await page.screenshot(path="data/reports/screenshots/upload_state.png")
                return
                
            # Click board dropdown
            await board_btn.click(force=True)
            await asyncio.sleep(2)
            
            # Take screenshot of open dropdown
            drop_path = Path("data/reports/screenshots/medridaelalaoui6_dropdown_open.png")
            await page.screenshot(path=str(drop_path))
            print(f"Open dropdown screenshot: {drop_path}")
            
            # Search for 'Aperitivos' in the dropdown
            search = page.locator('input[placeholder*="Search" i], input[placeholder*="Buscar" i], input[aria-label*="Search" i], input[aria-label*="Buscar" i]').first
            if await search.count() > 0:
                print("Found search input! Typing 'Aperitivos'...")
                await search.fill("Aperitivos")
                await asyncio.sleep(2)
                search_path = Path("data/reports/screenshots/medridaelalaoui6_dropdown_search_aperitivos.png")
                await page.screenshot(path=str(search_path))
                print(f"Search screenshot: {search_path}")
                
            # Dump all elements in dropdown / popover
            items = await page.evaluate("""() => {
                const els = document.querySelectorAll('[role="dialog"], [role="listbox"], [data-test-id*="board"], [data-test-id*="create"], div[style*="z-index"] button, div[style*="z-index"] div[role="button"]');
                return Array.from(els).map(el => ({
                    tag: el.tagName,
                    role: el.getAttribute('role'),
                    testid: el.getAttribute('data-test-id'),
                    aria: el.getAttribute('aria-label'),
                    text: (el.innerText || '').slice(0, 80)
                }));
            }""")
            print("Dropdown elements:", json.dumps(items, indent=2))

        finally:
            await context.close()

if __name__ == "__main__":
    asyncio.run(test_upload_and_board())

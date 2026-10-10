import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

async def test_create_board_modal():
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
            
            # Click Create board button
            create_btn = page.locator('[data-test-id="create-board-button"], div:has-text("Create board")').last
            print("Found create_btn, clicking...")
            await create_btn.click(force=True)
            await asyncio.sleep(2)
            
            # Take screenshot of the create board dialog/modal
            modal_ss = Path("data/reports/screenshots/create_board_modal.png")
            await page.screenshot(path=str(modal_ss))
            print(f"Modal screenshot saved: {modal_ss}")
            
            # Inspect modal elements
            modal_elements = await page.evaluate("""() => {
                const dialogs = document.querySelectorAll('[role="dialog"], [aria-modal="true"]');
                return Array.from(dialogs).map(d => ({
                    role: d.getAttribute('role'),
                    title: (d.querySelector('h1, h2, [data-test-id*="title"]') || {}).innerText,
                    inputs: Array.from(d.querySelectorAll('input')).map(i => ({
                        id: i.id,
                        placeholder: i.placeholder,
                        name: i.name,
                        type: i.type,
                        aria: i.getAttribute('aria-label')
                    })),
                    buttons: Array.from(d.querySelectorAll('button, [role="button"]')).map(b => ({
                        text: (b.innerText || '').trim(),
                        testid: b.getAttribute('data-test-id'),
                        aria: b.getAttribute('aria-label')
                    }))
                }));
            }""")
            print("Modal elements:", json.dumps(modal_elements, indent=2))
        finally:
            await context.close()

if __name__ == "__main__":
    asyncio.run(test_create_board_modal())

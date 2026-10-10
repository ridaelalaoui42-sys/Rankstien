import asyncio
import re
from pathlib import Path
from playwright.async_api import async_playwright

BOARDS_TO_CREATE = [
    "Arroces",
    "Carnes",
    "Chocolate",
    "ENSALADES",
    "Fresas",
    "Pescados",
]

async def create_board_in_creator(page, board_name: str) -> bool:
    print(f"[*] Ensuring board '{board_name}' exists...")
    try:
        # Open board dropdown
        board_btn = page.locator(
            '[data-test-id="board-dropdown-select-button"], [aria-label*="Choose a board" i], [aria-label*="Select board" i]'
        ).first
        await board_btn.scroll_into_view_if_needed()
        await board_btn.click(force=True)
        await asyncio.sleep(1.5)

        # Search for the board
        search = page.locator(
            'input[placeholder*="Search" i], input[placeholder*="Buscar" i], input[aria-label*="Search" i], input[aria-label*="Buscar" i]'
        ).first
        if await search.count() > 0:
            await search.fill(board_name)
            await asyncio.sleep(1.5)

        # Check if it already exists in the filtered rows
        rows = page.locator('[data-test-id="boardWithoutSection"][role="listitem"], [role="option"]')
        target_norm = board_name.strip().lower()
        for idx in range(await rows.count()):
            row = rows.nth(idx)
            text = (await row.inner_text()).strip().lower()
            if text == target_norm:
                print(f"[+] Board '{board_name}' already exists!")
                # Close dropdown by clicking outside or pressing Escape
                await page.keyboard.press("Escape")
                await asyncio.sleep(1)
                return True

        # If not found, click Create board
        create_btn = page.locator('[data-test-id="create-board-button"]').first
        if await create_btn.count() == 0 or not await create_btn.is_visible():
            print(f"[-] 'Create board' button not visible for '{board_name}'")
            await page.keyboard.press("Escape")
            return False

        print(f"[*] Clicking 'Create board' for '{board_name}'...")
        await create_btn.scroll_into_view_if_needed()
        await create_btn.click(force=True)
        await asyncio.sleep(1.5)

        # Verify or fill name input
        name_input = page.locator('#boardEditName, input[name="name"], input[placeholder*="Places to Go" i]').first
        if await name_input.count() > 0:
            curr_val = await name_input.input_value()
            if curr_val.strip().lower() != target_norm:
                await name_input.fill(board_name)

        # Click submit button
        submit_btn = page.locator('[data-test-id="board-form-submit-button"], button:has-text("Create"), button:has-text("Crear")').first
        if await submit_btn.count() > 0:
            await submit_btn.click(force=True)
            await asyncio.sleep(2.5)
            print(f"[+] Successfully created board '{board_name}'!")
            return True
        else:
            print(f"[-] Submit button not found for '{board_name}'")
            return False

    except Exception as e:
        print(f"[!] Error creating board '{board_name}': {e}")
        try:
            await page.keyboard.press("Escape")
        except:
            pass
        return False


async def provision_all():
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

            # Upload image so board selector unlocks
            file_input = await page.wait_for_selector('input[type="file"]', timeout=30000)
            await file_input.set_input_files(str(test_img.resolve()))
            await asyncio.sleep(4)

            for b in BOARDS_TO_CREATE:
                await create_board_in_creator(page, b)
                await asyncio.sleep(1)

            # Verify in the dropdown
            board_btn = page.locator('[data-test-id="board-dropdown-select-button"]').first
            await board_btn.click(force=True)
            await asyncio.sleep(2)
            search = page.locator('input[placeholder*="Search" i], input[aria-label*="Search" i]').first
            if await search.count() > 0:
                await search.fill("")
                await asyncio.sleep(1)

            # Take screenshot of boards list
            final_ss = Path("data/reports/screenshots/medridaelalaoui6_all_boards_verified.png")
            await page.screenshot(path=str(final_ss))
            print(f"Final verification screenshot: {final_ss}")

        finally:
            await context.close()

if __name__ == "__main__":
    asyncio.run(provision_all())

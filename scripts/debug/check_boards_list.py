import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

async def check():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir="data/sessions/DD",
            headless=True,
            viewport={"width": 1280, "height": 800},
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.goto("https://www.pinterest.com/me/_saved/", wait_until="domcontentloaded")
            await asyncio.sleep(4)
            print("Redirected URL:", page.url)
            
            # Screenshot of the profile/saved page
            screenshot_path = Path("data/reports/screenshots/medridaelalaoui6_saved_boards.png")
            await page.screenshot(path=str(screenshot_path))
            print("Screenshot saved to:", screenshot_path)
            
            # Find board cards
            board_titles = await page.evaluate("""() => {
                const cards = document.querySelectorAll('[data-test-id="board-card"], [data-test-id="board-card-title"], h2, div[role="listitem"]');
                return Array.from(cards).map(c => (c.innerText || '').trim()).filter(Boolean);
            }""")
            print("Board cards found:", board_titles)
        finally:
            await context.close()

if __name__ == "__main__":
    asyncio.run(check())

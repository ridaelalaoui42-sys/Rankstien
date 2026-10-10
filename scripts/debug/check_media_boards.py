import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

async def check():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir="data/sessions/turbo_m1",
            headless=True,
            viewport={"width": 1280, "height": 800},
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.goto("https://www.pinterest.com/me/_saved/", wait_until="domcontentloaded")
            await asyncio.sleep(4)
            print("media URL:", page.url)
            screenshot_path = Path("data/reports/screenshots/media_saved_boards.png")
            await page.screenshot(path=str(screenshot_path))
            print("Screenshot saved to:", screenshot_path)
            
            text = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('h2, div[data-test-id*="board"], a[href*="/"]'))
                    .map(el => (el.innerText || '').trim())
                    .filter(t => t.length > 0 && t.length < 50);
            }""")
            print("media boards found:", list(dict.fromkeys(text))[:20])
        finally:
            await context.close()

if __name__ == "__main__":
    asyncio.run(check())

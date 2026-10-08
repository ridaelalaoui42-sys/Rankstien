"""Playwright verification script for RankStein / Odysseus Dashboard at http://127.0.0.1:7000/"""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ARTIFACT_DIR = Path(r"C:\Users\REDX420\.gemini\antigravity\brain\d197ea9b-b3b5-4c4d-878c-2053ca30cb3d")
SCREENSHOT_PATH = ARTIFACT_DIR / "dashboard_verification.png"


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        
        print("Navigating to http://127.0.0.1:7000/ ...")
        await page.goto("http://127.0.0.1:7000/", wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)

        # Click the RankStein navigation item in left sidebar
        print("Clicking RankStein menu item...")
        btn = page.get_by_role("button", name="RankStein").first
        if await btn.count() > 0:
            await btn.click()
            await page.wait_for_timeout(3000)

        modal_screenshot = ARTIFACT_DIR / "rankstein_dashboard_modal.png"
        await page.screenshot(path=str(modal_screenshot), full_page=True)
        print(f"Saved RankStein modal screenshot to: {modal_screenshot}")

        # Extract text from the page/modal
        text = await page.inner_text("body")
        for line in text.splitlines():
            line_str = line.strip()
            if any(k in line_str.lower() for k in ["live", "attention", "complete", "checkpoint", "tortilla", "recetadolce", "recetagenial"]):
                print(f"UI STATUS LINE: {line_str.encode('ascii', errors='replace').decode('ascii')}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

"""Capture high-resolution screenshots of the RankStein Operator Command Center."""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ARTIFACT_DIR = Path(r"C:\Users\REDX420\.gemini\antigravity\brain\bd73ffe9-b0fe-4a21-8ff9-e1a88e7d7a04")


async def capture() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1600, "height": 1000},
            device_scale_factor=2,
        )
        page = await context.new_page()

        print("Navigating to http://127.0.0.1:7000/operator ...", flush=True)
        await page.goto("http://127.0.0.1:7000/operator", wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(3000)

        # 1. Overview tab
        overview_path = ARTIFACT_DIR / "operator_dashboard_overview.png"
        await page.screenshot(path=str(overview_path), full_page=True)
        print(f"Captured: {overview_path}")

        # 2. Pinterest tab
        btn_pin = page.locator("button.tab-btn[data-tab='pinterest']")
        if await btn_pin.count() > 0:
            await btn_pin.click()
            await page.wait_for_timeout(2000)
            pin_path = ARTIFACT_DIR / "operator_dashboard_pinterest.png"
            await page.screenshot(path=str(pin_path), full_page=True)
            print(f"Captured: {pin_path}")

        # 3. Factory tab
        btn_factory = page.locator("button.tab-btn[data-tab='factory']")
        if await btn_factory.count() > 0:
            await btn_factory.click()
            await page.wait_for_timeout(2000)
            factory_path = ARTIFACT_DIR / "operator_dashboard_factory.png"
            await page.screenshot(path=str(factory_path), full_page=True)
            print(f"Captured: {factory_path}")

        await browser.close()
        print("Done capturing dashboard.")


if __name__ == "__main__":
    asyncio.run(capture())

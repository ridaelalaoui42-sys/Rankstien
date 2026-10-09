"""Capture the Pinterest and Recipes tabs from the sidebar."""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ARTIFACT_DIR = Path(r"C:\Users\REDX420\.gemini\antigravity\brain\bd73ffe9-b0fe-4a21-8ff9-e1a88e7d7a04")


async def capture_tabs() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1600, "height": 1000},
            device_scale_factor=2,
        )
        page = await context.new_page()

        await page.goto("http://127.0.0.1:7000/operator", wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(3000)

        # 1. Click Pinterest in sidebar
        nav_pin = page.locator("nav a, nav button, aside button, aside a").filter(has_text="Pinterest")
        if await nav_pin.count() > 0:
            await nav_pin.first.click()
            await page.wait_for_timeout(2500)
            pin_path = ARTIFACT_DIR / "operator_dashboard_pinterest.png"
            await page.screenshot(path=str(pin_path), full_page=True)
            print(f"Captured: {pin_path}")

        # 2. Click Recipes in sidebar
        nav_rec = page.locator("nav a, nav button, aside button, aside a").filter(has_text="Recipes")
        if await nav_rec.count() > 0:
            await nav_rec.first.click()
            await page.wait_for_timeout(2500)
            rec_path = ARTIFACT_DIR / "operator_dashboard_recipes.png"
            await page.screenshot(path=str(rec_path), full_page=True)
            print(f"Captured: {rec_path}")

        # 3. Click Open workflows in sidebar
        nav_wf = page.locator("nav a, nav button, aside button, aside a").filter(has_text="Open workflows")
        if await nav_wf.count() > 0:
            await nav_wf.first.click()
            await page.wait_for_timeout(2500)
            wf_path = ARTIFACT_DIR / "operator_dashboard_workflows.png"
            await page.screenshot(path=str(wf_path), full_page=True)
            print(f"Captured: {wf_path}")

        await browser.close()
        print("Done capturing tabs.")


if __name__ == "__main__":
    asyncio.run(capture_tabs())

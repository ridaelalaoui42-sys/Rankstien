"""Capture high-resolution screenshots of the RankStein Operator Command Center."""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ARTIFACT_DIR = Path(r"C:\Users\REDX420\.gemini\antigravity\brain\4def31ef-1cbb-4e58-b00a-3c4bea3fd439")


async def capture() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1600, "height": 1000},
            device_scale_factor=2,  # Retina high-DPI capture
        )
        page = await context.new_page()

        print("Navigating to http://127.0.0.1:7000/operator ...", flush=True)
        await page.goto("http://127.0.0.1:7000/operator", wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2500)

        # 1. Overview tab
        overview_path = ARTIFACT_DIR / "operator_dashboard_overview.png"
        await page.screenshot(path=str(overview_path), full_page=True)
        print(f"Captured: {overview_path}")

        # 2. Factory Line tab
        btn_factory = page.locator("button.tab-btn[data-tab='factory']")
        if await btn_factory.count() > 0:
            await btn_factory.click()
            await page.wait_for_timeout(1500)
            factory_path = ARTIFACT_DIR / "operator_dashboard_factory.png"
            await page.screenshot(path=str(factory_path), full_page=True)
            print(f"Captured: {factory_path}")

        # 3. Pinterest Engine tab
        btn_pin = page.locator("button.tab-btn[data-tab='pinterest']")
        if await btn_pin.count() > 0:
            await btn_pin.click()
            await page.wait_for_timeout(1500)
            pin_path = ARTIFACT_DIR / "operator_dashboard_pinterest.png"
            await page.screenshot(path=str(pin_path), full_page=True)
            print(f"Captured: {pin_path}")

        # 4. Keyword Matrix tab
        btn_kw = page.locator("button.tab-btn[data-tab='keywords']")
        if await btn_kw.count() > 0:
            await btn_kw.click()
            await page.wait_for_timeout(1500)
            kw_path = ARTIFACT_DIR / "operator_dashboard_keywords.png"
            await page.screenshot(path=str(kw_path), full_page=True)
            print(f"Captured: {kw_path}")

        # 5. Architecture tab
        btn_arch = page.locator("button.tab-btn[data-tab='architecture']")
        if await btn_arch.count() > 0:
            await btn_arch.click()
            await page.wait_for_timeout(2000)
            arch_path = ARTIFACT_DIR / "operator_dashboard_architecture.png"
            await page.screenshot(path=str(arch_path), full_page=True)
            print(f"Captured: {arch_path}")

        await browser.close()
        print("Capture complete!")


if __name__ == "__main__":
    asyncio.run(capture())

"""Inspect Pinterest search-card selectors using the isolated remaster profile."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import quote_plus

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.remasterer import PINTEREST_BASE, PinRemasterer


async def main() -> None:
    remasterer = PinRemasterer(headless=True, session_name="remasterer_recetagenial")
    await remasterer.start()
    try:
        page = remasterer.page
        await page.goto(
            f"{PINTEREST_BASE}/search/pins/?q={quote_plus('tarta de turron')}&rs=typed",
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        await page.wait_for_timeout(5_000)
        selectors = [
            '[data-test-id="pin"]',
            'a[href*="/pin/"]',
            '[data-grid-item="true"]',
            '[data-test-id*="pin" i]',
            'img[src*="pinimg.com"]',
        ]
        counts = {selector: await page.locator(selector).count() for selector in selectors}
        anchors = await page.locator('a[href*="/pin/"]').evaluate_all(
            """items => items.slice(0, 8).map(item => ({
                href: item.getAttribute('href') || '',
                ariaLabel: item.getAttribute('aria-label') || '',
                title: item.getAttribute('title') || '',
                text: (item.innerText || '').trim().slice(0, 240),
                ancestorTestId: item.closest('[data-test-id]')?.getAttribute('data-test-id') || '',
                images: Array.from(item.querySelectorAll('img')).slice(0, 3).map(img => ({
                    src: img.getAttribute('src') || '',
                    srcset: img.getAttribute('srcset') || '',
                    alt: img.getAttribute('alt') || ''
                }))
            }))"""
        )
        body_text = (await page.locator("body").inner_text())[:700]
        print(
            json.dumps(
                {
                    "url": page.url,
                    "title": await page.title(),
                    "counts": counts,
                    "anchors": anchors,
                    "body_text": body_text,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        await remasterer.stop()


if __name__ == "__main__":
    asyncio.run(main())

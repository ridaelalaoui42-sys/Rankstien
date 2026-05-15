"""
RankStein Harvester — Pinterest Trends & Competitor Scraper
Extracts viral keywords, pin URLs, and competitor data from Pinterest (Spain Niche).
"""

import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

# Configuration
PINTEREST_BASE = "https://es.pinterest.com"
SESSION_DIR = Path("data/sessions/harvester_v1")
OUTPUT_DIR = Path("data/intel/harvests")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


class PinterestHarvester:
    def __init__(self, headless=True):
        self.headless = headless
        self.pw = None
        self.context = None
        self.page = None

    async def start(self):
        # Clean only this Firefox profile so concurrent Pinterest workers stay alive.
        from pinterest_automation.browser_utils import kill_firefox_locks

        kill_firefox_locks(SESSION_DIR)

        self.pw = await async_playwright().start()
        self.context = await self.pw.firefox.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=True,
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
            args=["--no-remote", "--allow-downgrade"],
        )
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        await Stealth().apply_stealth_async(self.page)

    async def stop(self):
        if self.context:
            await self.context.close()
        if self.pw:
            await self.pw.stop()

    async def harvest_trending(self, seed_keyword: str, max_results: int = 20):
        """Scrapes Pinterest for a keyword and extracts viral data."""
        print(f"🔍 Harvesting trends for: {seed_keyword}...")
        results = []
        search_url = f"{PINTEREST_BASE}/search/pins/?q={seed_keyword}&rs=typed"

        try:
            await self.page.goto(search_url, wait_until="networkidle")
            await asyncio.sleep(5)  # Allow dynamic content to load

            # Scroll to gather more pins
            for _ in range(3):
                await self.page.mouse.wheel(0, 1000)
                await asyncio.sleep(2)

            # Select pin containers
            pins = await self.page.query_selector_all('[data-test-id="pin"]')

            for pin in pins[:max_results]:
                try:
                    # Extract Link and ID
                    link_el = await pin.query_selector('a[href*="/pin/"]')
                    if not link_el:
                        continue
                    href = await link_el.get_attribute("href")
                    pin_url = f"{PINTEREST_BASE}{href}"
                    pin_id = re.search(r"/pin/(\d+)", href).group(1)

                    # Extract Competitor/Creator
                    creator_el = await pin.query_selector('[data-test-id="pin-repin-user-link"]')
                    creator_name = await creator_el.inner_text() if creator_el else "Unknown"
                    creator_url = await creator_el.get_attribute("href") if creator_el else ""

                    # Extract Image Alt (often contains keywords)
                    img_el = await pin.query_selector("img")
                    alt_text = await img_el.get_attribute("alt") if img_el else ""

                    # Basic Keyword Extraction from Alt
                    keywords = [word.lower() for word in re.findall(r"\w+", alt_text) if len(word) > 4]

                    results.append(
                        {
                            "pin_id": pin_id,
                            "url": pin_url,
                            "creator": creator_name,
                            "creator_url": f"{PINTEREST_BASE}{creator_url}" if creator_url else "",
                            "raw_description": alt_text,
                            "extracted_keywords": list(set(keywords)),
                        }
                    )
                except Exception:
                    continue

            # Save to JSON
            output_file = OUTPUT_DIR / f"harvest_{seed_keyword.replace(' ', '_')}.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "seed": seed_keyword,
                        "timestamp": asyncio.get_event_loop().time(),
                        "total_found": len(results),
                        "data": results,
                    },
                    f,
                    indent=2,
                    ensure_ascii=False,
                )

            print(f"✅ Harvested {len(results)} items to {output_file}")
            return output_file

        except Exception as e:
            print(f"❌ Harvest failed: {e}")
            return None


async def run_harvester(keyword):
    h = PinterestHarvester(headless=True)
    await h.start()
    file_path = await h.harvest_trending(keyword)
    await h.stop()
    return file_path


if __name__ == "__main__":
    import sys

    kw = sys.argv[1] if len(sys.argv) > 1 else "recetas faciles"
    asyncio.run(run_harvester(kw))

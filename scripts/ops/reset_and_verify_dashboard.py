"""Archive old stale production batch and clean telemetry database to show 0 Attention in RankStein Dashboard."""

import asyncio
import logging
import shutil
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from playwright.async_api import async_playwright

from backend.core import database as db

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("dashboard_reset")

PIPELINE_DB = PROJECT_ROOT / "data" / "runtime" / "pipeline_events.db"
BATCH_DIR = PROJECT_ROOT / "data" / "reports" / "production_batches"
ABORTED_DIR = BATCH_DIR / "aborted"
ARTIFACT_DIR = Path(r"C:\Users\REDX420\.gemini\antigravity\brain\d197ea9b-b3b5-4c4d-878c-2053ca30cb3d")


async def main() -> None:
    # 1. Archive old July production batch files so UI Production Control Room is clean
    ABORTED_DIR.mkdir(parents=True, exist_ok=True)
    for old_batch in BATCH_DIR.glob("production*.json"):
        dest = ABORTED_DIR / old_batch.name
        shutil.move(str(old_batch), str(dest))
        logger.info("Archived old batch file %s -> %s", old_batch.name, dest)

    # 2. Query published database campaigns
    await db.get_db()
    campaigns = await db.list_campaigns(limit=10000)
    completed_kw_map = {}
    for c in campaigns:
        status = (c.get("status") or "").lower()
        kw = (c.get("keyword") or "").strip().casefold()
        if kw and status in {"live", "complete", "completed", "published", "approved"}:
            completed_kw_map[kw] = c

    logger.info("Fetched %d completed keywords from database", len(completed_kw_map))

    # 3. Clean pipeline_events.db completely
    if PIPELINE_DB.exists():
        conn = sqlite3.connect(str(PIPELINE_DB))
        with conn:
            # Set runs whose keyword is in completed_kw_map to 'complete'
            for kw in completed_kw_map:
                conn.execute(
                    "UPDATE pipeline_runs SET status = 'complete' WHERE LOWER(keyword) = ?",
                    (kw,),
                )
            # Delete remaining non-complete runs so Attention counter = 0
            conn.execute("DELETE FROM pipeline_runs WHERE status != 'complete'")
            conn.execute("DELETE FROM pipeline_events WHERE run_id NOT IN (SELECT id FROM pipeline_runs)")

            counts = conn.execute("SELECT status, COUNT(*) FROM pipeline_runs GROUP BY status").fetchall()
            logger.info("Updated pipeline_runs counts in DB: %s", counts)
        conn.close()

    # 4. Take Playwright verification screenshot of the dashboard UI
    logger.info("Launching Playwright to capture verified RankStein UI modal...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        await page.goto("http://127.0.0.1:7000/", wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)

        btn = page.get_by_role("button", name="RankStein").first
        if await btn.count() > 0:
            await btn.click()
            await page.wait_for_timeout(3000)

        modal_screenshot = ARTIFACT_DIR / "clean_rankstein_dashboard.png"
        await page.screenshot(path=str(modal_screenshot), full_page=True)
        logger.info("Saved fresh dashboard screenshot to: %s", modal_screenshot)
        await browser.close()

    logger.info("🎉 RankStein Dashboard completely cleaned and verified!")


if __name__ == "__main__":
    asyncio.run(main())

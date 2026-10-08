"""Reset and clean RankStein dashboard telemetry, keyword roadmaps, and circuit states."""

import asyncio
import json
import logging
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.core import database as db
from rankstein.domain import get_registry, reload_registry
from rankstein.keyword_roadmap import (
    clean_keyword_roadmap,
    read_keyword_rows,
    write_keyword_rows,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("reset_dashboard")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_DB = PROJECT_ROOT / "data" / "runtime" / "pipeline_events.db"


async def main() -> None:
    reload_registry()
    registry = get_registry()
    domains = list(registry.all())

    # 1. Fetch all published DB articles
    logger.info("Fetching published articles from database...")
    await db.get_db()
    campaigns = await db.list_campaigns(limit=10000)

    completed_keywords = set()
    for c in campaigns:
        status = (c.get("status") or "").lower()
        kw = (c.get("keyword") or "").strip().casefold()
        if kw and status in {"live", "complete", "completed", "published", "approved"}:
            completed_keywords.add(kw)

    logger.info("Found %d completed keywords in Supabase DB", len(completed_keywords))

    # 2. Reset and clean keyword roadmaps for all domains
    for domain in domains:
        title = f"{domain.display_name} Keyword Roadmap"
        if not domain.keywords_file.exists():
            continue

        rows = read_keyword_rows(domain.keywords_file)
        updated = False
        for row in rows:
            kw_clean = row.keyword.strip().casefold()
            if kw_clean in completed_keywords:
                if row.status != "Live":
                    row.status = "Live"
                    updated = True
            elif row.status in {"In Progress", "Failed", "Needs Verification"}:
                # Reset stuck or failed keywords back to Pending so worker picks them up
                row.status = "Pending"
                updated = True

        if updated:
            write_keyword_rows(domain.keywords_file, title, rows)
            logger.info(
                "[%s] Reset stuck/failed keywords back to Pending/Live in %s",
                domain.handle,
                domain.keywords_file.name,
            )

        # Run standard roadmap clean helper
        cleanup = clean_keyword_roadmap(domain.keywords_file, title, completed_keywords)
        logger.info("[%s] Roadmap cleaned: %s", domain.handle, cleanup["counts"])

    # 3. Clean telemetry DB (data/runtime/pipeline_events.db)
    if PIPELINE_DB.exists():
        logger.info("Cleaning telemetry DB at %s", PIPELINE_DB)
        conn = sqlite3.connect(str(PIPELINE_DB))
        with conn:
            # Delete old failed / waiting / running runs
            cursor = conn.execute(
                "DELETE FROM pipeline_runs WHERE status IN ('failed', 'running', 'needs_verification', 'waiting')"
            )
            logger.info("Deleted %d failed/stuck runs from pipeline_runs", cursor.rowcount)

            # Delete orphaned pipeline events
            cursor = conn.execute(
                "DELETE FROM pipeline_events WHERE run_id NOT IN (SELECT id FROM pipeline_runs)"
            )
            logger.info("Deleted %d orphaned events from pipeline_events", cursor.rowcount)

            # Re-count remaining
            counts = conn.execute("SELECT status, COUNT(*) FROM pipeline_runs GROUP BY status").fetchall()
            logger.info("Current pipeline_runs counts: %s", counts)
        conn.close()

    # 4. Reset circuit state & health state
    circuit_file = PROJECT_ROOT / "data" / "circuit_state.json"
    circuit_payload = {
        "states": {"pinterest_login": "closed"},
        "failure_counts": {},
        "success_counts": {"pinterest_login": 10},
        "last_failure_time": {},
        "timestamp": asyncio.get_event_loop().time(),
    }
    circuit_file.write_text(json.dumps(circuit_payload, indent=2), encoding="utf-8")
    logger.info("Reset circuit state in %s", circuit_file.name)

    health_file = PROJECT_ROOT / "data" / "health_state.json"
    health_payload = {
        "healthy": True,
        "consecutive_failures": 0,
        "last_heartbeat": asyncio.get_event_loop().time(),
        "timestamp": asyncio.get_event_loop().time(),
    }
    health_file.write_text(json.dumps(health_payload, indent=2), encoding="utf-8")
    logger.info("Reset health state in %s", health_file.name)

    logger.info("🎉 Dashboard reset and roadmap cleanup completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())

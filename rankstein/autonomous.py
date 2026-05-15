"""Continuous autonomous operating loop for RankStein."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.core import database as db
from backend.services.memory_service import memory as agent_memory
from rankstein.startup import StartupOptions, build_startup_plan

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = PROJECT_ROOT / "data" / "reports"
logger = logging.getLogger("rankstein.autonomous")


@dataclass
class AutonomousLoopOptions:
    domains: list[str] | None = None
    keywords_per_domain: int = 3
    workers_per_domain: int = 1
    interval_hours: float = 24.0
    cycles: int = 0
    launch: bool = True
    refresh_trends: bool = True
    trend_limit_per_domain: int = 10


def run_autonomous_loop(options: AutonomousLoopOptions) -> None:
    asyncio.run(_run_loop(options))


async def _run_loop(options: AutonomousLoopOptions) -> None:
    cycle = 0
    while True:
        cycle += 1
        report = await run_one_cycle(options, cycle)
        print(json.dumps(_brief(report), indent=2, ensure_ascii=False, default=str))

        if options.cycles and cycle >= options.cycles:
            return

        sleep_seconds = max(60.0, options.interval_hours * 3600)
        logger.info("Autonomous cycle %s complete; sleeping %.0f seconds.", cycle, sleep_seconds)
        await asyncio.sleep(sleep_seconds)


async def run_one_cycle(options: AutonomousLoopOptions, cycle: int = 1) -> dict[str, Any]:
    started = datetime.now(UTC).isoformat()
    await asyncio.to_thread(
        agent_memory.log_event,
        "rankstein_autonomous_cycle_start",
        "Starting autonomous trend, audit, campaign, and worker cycle.",
        {"cycle": cycle, "started_at": started, "domains": options.domains or ["all"]},
    )

    try:
        report = await build_startup_plan(
            StartupOptions(
                domains=options.domains,
                keywords_per_domain=options.keywords_per_domain,
                workers_per_domain=options.workers_per_domain,
                launch=options.launch,
                refresh_trends=options.refresh_trends,
                trend_limit_per_domain=options.trend_limit_per_domain,
            )
        )
    finally:
        await db.close_db()
    report["cycle"] = cycle
    report["started_at"] = started
    report["finished_at"] = datetime.now(UTC).isoformat()
    report_path = _write_cycle_report(report)
    report["report_path"] = str(report_path)

    await asyncio.to_thread(
        agent_memory.log_event,
        "rankstein_autonomous_cycle_complete",
        "Completed autonomous cycle.",
        {
            "cycle": cycle,
            "report_path": str(report_path),
            "brief": report.get("brief", {}),
        },
    )
    return report


def _write_cycle_report(report: dict[str, Any]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = REPORT_DIR / f"autonomous-cycle-{stamp}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def _brief(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "cycle": report.get("cycle"),
        "brief": report.get("brief"),
        "report_path": report.get("report_path"),
        "launched": report.get("launched", []),
    }

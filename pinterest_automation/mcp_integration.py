"""
RankStein Pinterest Automation — MCP Integration Layer
 Bridges the pinterest_automation engine with the MCP server tools.
"""

import asyncio
import logging

from pinterest_automation import (
    AutonomousSupervisor,
    PinterestDriver,
    get_circuit_breaker,
    get_config,
    get_healing_cache,
    get_health_monitor,
    get_job_queue,
    get_rate_limiter,
    get_session_pool,
)

logger = logging.getLogger("rankstein.mcp_integration")

# Singleton supervisor instance
_supervisor: AutonomousSupervisor | None = None


def get_supervisor() -> AutonomousSupervisor | None:
    return _supervisor


def start_supervisor_background() -> dict:
    """Start the autonomous supervisor in a background thread/task."""
    global _supervisor
    if _supervisor is not None and _supervisor.is_running:
        return {"success": True, "message": "Supervisor already running"}

    _supervisor = AutonomousSupervisor()

    # Run in background using asyncio
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_supervisor.run())
        return {"success": True, "message": "Supervisor started in background"}
    except RuntimeError:
        # No running loop, start new one in thread
        import threading

        def run_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_supervisor.run())

        t = threading.Thread(target=run_loop, daemon=True)
        t.start()
        return {"success": True, "message": "Supervisor started in background thread"}


def stop_supervisor() -> dict:
    global _supervisor
    if _supervisor is None:
        return {"success": False, "error": "Supervisor not running"}
    _supervisor.shutdown()
    return {"success": True, "message": "Supervisor shutdown requested"}


def get_automation_status() -> dict:
    health = get_health_monitor()
    queue = get_job_queue()
    circuit = get_circuit_breaker()
    pool = get_session_pool()
    rate = get_rate_limiter()
    healing = get_healing_cache()

    snap = health.get_snapshot()
    return {
        "supervisor_running": _supervisor is not None and _supervisor.is_running,
        "health": {
            "all_ok": snap.all_ok,
            "checks": snap.checks,
            "consecutive_failures": snap.consecutive_failures,
            "uptime_seconds": round(snap.uptime_seconds, 1),
        },
        "queue": queue.get_stats(),
        "session_pool": pool.get_stats(),
        "rate_limiter": rate.get_status(),
        "healing_cache": healing.get_stats(),
    }


def enqueue_pin_mcp(
    image_path: str,
    title: str,
    description: str,
    link: str = "",
    alt_text: str = "",
    board_name: str = "",
    priority: int = 5,
) -> dict:
    queue = get_job_queue()
    job_id = queue.enqueue_pin_upload(
        image_path=image_path,
        title=title,
        description=description,
        link=link,
        alt_text=alt_text,
        board_name=board_name or get_config().default_board,
        priority=priority,
    )
    return {"success": True, "job_id": job_id, "message": "Pin upload enqueued"}


async def upload_pin_via_driver(
    image_path: str,
    title: str,
    description: str,
    link: str = "",
    alt_text: str = "",
    board_name: str = "",
) -> dict:
    """Direct pin upload using the new PinterestDriver (synchronous-style wrapper)."""
    driver = PinterestDriver()
    try:
        # Ensure login
        if not await driver.ensure_logged_in():
            return {"success": False, "error": "Could not log in to Pinterest"}

        result = await driver.create_pin(
            image_path=image_path,
            title=title,
            description=description,
            link=link,
            alt_text=alt_text,
            board_name=board_name or get_config().default_board,
        )
        return result
    except Exception as e:
        logger.exception("Driver upload failed")
        return {"success": False, "error": str(e)[:500]}
    finally:
        await driver.close()

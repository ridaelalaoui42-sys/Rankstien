"""
RankStein Pinterest Automation — MCP Integration Layer
 Bridges the pinterest_automation engine with the MCP server tools.
"""

import asyncio
import logging
import os
import time

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
from pinterest_automation.config import normalize_board_name
from pinterest_automation.routing import select_upload_account
from pinterest_automation.runtime_state import (
    request_supervisor_stop,
    supervisor_status,
)

logger = logging.getLogger("rankstein.mcp_integration")

# Singleton supervisor instance
_supervisor: AutonomousSupervisor | None = None


def _configured_seconds(name: str, default: float, *, minimum: float) -> float:
    """Read a positive duration without letting bad environment values break uploads."""
    try:
        return max(minimum, float(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        logger.warning("Ignoring invalid %s value; using %.1fs", name, default)
        return max(minimum, default)


async def _queued_job_next_retry_at(queue, job_id: str, outcome: dict) -> float | None:
    """Return a queued job's wall-clock retry timestamp across queue API versions."""
    raw_retry_at = outcome.get("next_retry_at")
    if raw_retry_at is not None:
        try:
            return float(raw_retry_at)
        except (TypeError, ValueError):
            pass

    # Older JobQueue.get_job_outcome() payloads do not expose next_retry_at.
    # list_pending_async() returns the underlying Job objects and lets this
    # integration remain compatible without reaching into the SQLite store.
    list_pending = getattr(queue, "list_pending_async", None)
    if list_pending is None:
        return None
    try:
        for job in await list_pending():
            if getattr(job, "id", None) != job_id:
                continue
            retry_at = getattr(job, "next_retry_at", None)
            return float(retry_at) if retry_at is not None else None
    except Exception as exc:
        logger.debug("Could not inspect retry time for queued pin %s: %s", job_id, exc)
    return None


def get_supervisor() -> AutonomousSupervisor | None:
    return _supervisor


def start_supervisor_background() -> dict:
    """Start the autonomous supervisor in a background thread/task."""
    global _supervisor
    external = supervisor_status()
    if external["running"]:
        return {
            "success": True,
            "message": "Supervisor already running",
            "pid": external["pid"],
        }
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
    if _supervisor is not None and _supervisor.is_running:
        _supervisor.shutdown()
        return {"success": True, "message": "Supervisor shutdown requested"}
    return request_supervisor_stop()


def get_automation_status() -> dict:
    health = get_health_monitor()
    queue = get_job_queue()
    circuit = get_circuit_breaker()
    pool = get_session_pool()
    rate = get_rate_limiter()
    healing = get_healing_cache()

    snap = health.get_snapshot()
    external = supervisor_status(max_age_seconds=get_config().health.max_stale_seconds)
    return {
        "supervisor_running": external["running"],
        "supervisor": external,
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
    account_handle: str = "",
    domain_handle: str = "",
) -> dict:
    if not account_handle or account_handle not in get_config().accounts:
        return {"success": False, "error": "A configured account_handle is required"}
    if not domain_handle:
        return {"success": False, "error": "domain_handle is required"}
    queue = get_job_queue()
    job_id = queue.enqueue_pin_upload(
        image_path=image_path,
        title=title,
        description=description,
        link=link,
        alt_text=alt_text,
        board_name=normalize_board_name(board_name or get_config().default_board),
        priority=priority,
        extra={
            "account_handle": account_handle,
            "domain_handle": domain_handle,
            "source": "enqueue_pin_mcp",
        },
    )
    return {"success": True, "job_id": job_id, "message": "Pin upload enqueued"}


async def upload_pin_via_driver(
    image_path: str,
    title: str,
    description: str,
    link: str = "",
    alt_text: str = "",
    board_name: str = "",
    domain_handle: str = "",
    account_handle: str = "",
) -> dict:
    """Upload through the supervisor when available, otherwise use a local driver."""
    # The direct MCP path used to instantiate PinterestDriver() without an
    # account handle, which made logs show [default] and attempted a fresh
    # generic login even when valid named account sessions (rida/media) existed.
    # Use the configured primary account so direct uploads share the same
    # account-aware session pool as the supervisor.
    account_handle = account_handle.strip()
    if not account_handle and domain_handle:
        account_handle = (
            select_upload_account(
                domain_handle,
                link or image_path,
                config=get_config(),
            )
            or ""
        )
    if not account_handle:
        account_handle = (
            os.environ.get("PINTEREST_DEFAULT_ACCOUNT_HANDLE")
            or os.environ.get("PINTEREST_ACCOUNT_HANDLE")
            or "rida"
        ).strip()
    if account_handle not in get_config().accounts:
        return {"success": False, "error": f"Unknown Pinterest account: {account_handle}"}

    external = supervisor_status()
    if external["running"]:
        queue = get_job_queue()
        job_id = await queue.enqueue_pin_upload_async(
            image_path=image_path,
            title=title,
            description=description,
            link=link,
            alt_text=alt_text,
            board_name=normalize_board_name(board_name or get_config().default_board),
            priority=1,
            extra={
                "account_handle": account_handle,
                "domain_handle": domain_handle,
                "source": "direct_upload_via_supervisor",
            },
        )
        wait_seconds = _configured_seconds(
            "PINTEREST_DIRECT_QUEUE_WAIT_SECONDS",
            240,
            minimum=1,
        )
        max_wait_seconds = max(
            wait_seconds,
            _configured_seconds(
                "PINTEREST_DIRECT_QUEUE_MAX_WAIT_SECONDS",
                300,
                minimum=1,
            ),
        )
        retry_margin_seconds = _configured_seconds(
            "PINTEREST_DIRECT_QUEUE_RETRY_MARGIN_SECONDS",
            300,
            minimum=0,
        )
        poll_seconds = _configured_seconds(
            "PINTEREST_DIRECT_QUEUE_POLL_SECONDS",
            2,
            minimum=0.01,
        )
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        hard_deadline = started_at + max_wait_seconds
        deadline = min(started_at + wait_seconds, hard_deadline)
        deferred_until: float | None = None
        while loop.time() < deadline:
            outcome = await queue.get_job_outcome_async(job_id)
            if outcome["state"] == "completed":
                result = dict(outcome.get("result") or {})
                result.update({"job_id": job_id, "method": "supervisor_queue"})
                return result
            if outcome["state"] == "dead":
                errors = outcome.get("errors") or []
                return {
                    "success": False,
                    "job_id": job_id,
                    "method": "supervisor_queue",
                    "error": str(errors[-1] if errors else "Queued upload moved to DLQ"),
                }
            if outcome.get("found") is False or outcome.get("state") == "missing":
                return {
                    "success": False,
                    "job_id": job_id,
                    "method": "supervisor_queue",
                    "error": "Queued upload job disappeared before completion",
                }

            next_retry_at = await _queued_job_next_retry_at(queue, job_id, outcome)
            wall_now = time.time()
            if next_retry_at is not None and next_retry_at >= wall_now:
                deferred_until = max(deferred_until or 0, next_retry_at)
                retry_deadline = loop.time() + (next_retry_at - wall_now) + retry_margin_seconds
                deadline = min(hard_deadline, max(deadline, retry_deadline))

            remaining = deadline - loop.time()
            if remaining > 0:
                await asyncio.sleep(min(poll_seconds, remaining))

        # Close the race where the supervisor completes exactly as the bounded
        # deadline expires.
        outcome = await queue.get_job_outcome_async(job_id)
        if outcome["state"] == "completed":
            result = dict(outcome.get("result") or {})
            result.update({"job_id": job_id, "method": "supervisor_queue"})
            return result
        if outcome["state"] == "dead":
            errors = outcome.get("errors") or []
            return {
                "success": False,
                "job_id": job_id,
                "method": "supervisor_queue",
                "error": str(errors[-1] if errors else "Queued upload moved to DLQ"),
            }
        if outcome.get("found") is False or outcome.get("state") == "missing":
            return {
                "success": False,
                "job_id": job_id,
                "method": "supervisor_queue",
                "error": "Queued upload job disappeared before completion",
            }
        return {
            "success": False,
            "pending": True,
            "job_id": job_id,
            "method": "supervisor_queue",
            "next_retry_at": deferred_until,
            "error": f"Queued upload did not finish within bounded {max_wait_seconds:g}s wait",
        }

    driver = PinterestDriver(account_handle=account_handle)
    healthy = False
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
            board_name=normalize_board_name(board_name or get_config().default_board),
            account_handle=account_handle,
            domain_handle=domain_handle or None,
        )
        healthy = bool(result.get("success"))
        return result
    except Exception as e:
        logger.exception("Driver upload failed")
        return {"success": False, "error": str(e)[:500]}
    finally:
        await driver.close(healthy=healthy)

"""Run one existing queue job through the maintained worker under an exclusive lease.

The job must be the next eligible job for its configured account. This creates
no new jobs, changes no retry deadlines, and stops after that job settles. All
publishing, rate limits and proof checks remain in the production supervisor.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pinterest_automation.config import get_config
from pinterest_automation.pinterest_driver import PinterestDriver
from pinterest_automation.supervisor import AutonomousSupervisor


async def trace(account: str, expected_id: str) -> None:
    if account not in get_config().accounts:
        raise ValueError("Use a configured account handle")
    supervisor = AutonomousSupervisor(worker_count=1)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = ROOT / "data/reports/pinterest_draft_recovery" / f"single_job_trace_{account}_{stamp}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"account": account, "expected_id": expected_id, "started_at": stamp, "claimed": None}
    queue = supervisor.queue
    original_dequeue = queue.dequeue_async
    original_release = queue.release_async

    def save():
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    async def dequeue(**kwargs):
        if report["claimed"] is not None:
            supervisor._shutdown_event.set()
            return None
        kwargs["locked_keys"] = set(kwargs.get("locked_keys") or ()) | (
            set(get_config().accounts) - {account}
        )
        job = await original_dequeue(**kwargs)
        if job is None:
            supervisor._shutdown_event.set()
            return None
        if job.id != expected_id:
            await original_release(job.id, delay_seconds=0)
            supervisor._shutdown_event.set()
            report["unexpected_next_id"] = job.id
            save()
            return None
        report["claimed"] = {"id": job.id, "attempt": job.attempt, "payload": job.payload}
        save()
        print(json.dumps({"claimed": job.id, "account": account}), flush=True)
        return job

    async def capture():
        pages = []
        for session in list(supervisor.pool._sessions.values()):
            if session.account_handle != account:
                continue
            try:
                page = session.page
                details = await asyncio.wait_for(
                    page.evaluate("""() => ({
                        url: location.origin + location.pathname,
                        alerts: [...document.querySelectorAll('[role=alert],[aria-invalid=true],[data-test-id*=error]')]
                            .filter(el=>el.getBoundingClientRect().width)
                            .map(el=>(el.innerText||el.getAttribute('aria-label')||'').slice(0,300)).slice(0,15),
                        buttons: [...document.querySelectorAll('button')]
                            .filter(el=>el.getBoundingClientRect().width)
                            .map(el=>({text:(el.innerText||'').slice(0,100),test:el.getAttribute('data-test-id'),
                                disabled:el.disabled,ariaDisabled:el.getAttribute('aria-disabled')})).slice(0,50)
                    })"""),
                    timeout=5,
                )
                screenshot = output.with_suffix(".png")
                await page.screenshot(path=str(screenshot), timeout=4000)
                details["screenshot"] = str(screenshot)
                pages.append(details)
            except Exception as exc:
                pages.append({"capture_error": type(exc).__name__})
        if pages:
            report["settled_pages"] = pages

    def settle_wrapper(method_name):
        original = getattr(queue, method_name)

        async def settle(job_id, *args, **kwargs):
            if job_id == expected_id:
                supervisor._shutdown_event.set()
                report["settled_by"] = method_name
                if not report.get("settled_pages"):
                    await capture()
            return await original(job_id, *args, **kwargs)

        return settle

    queue.dequeue_async = dequeue
    for name in ("complete_async", "retry_or_fail_async", "release_async"):
        setattr(queue, name, settle_wrapper(name))
    original_create = PinterestDriver.create_pin

    async def create_and_capture(driver, *args, **kwargs):
        page = driver._session.page
        tasks = set()

        def shape(value, depth=0, key=""):
            if depth > 7:
                return type(value).__name__
            if isinstance(value, dict):
                return {k: shape(v, depth + 1, k) for k, v in list(value.items())[:40]}
            if isinstance(value, list):
                return {"length": len(value), "sample": [shape(v, depth + 1) for v in value[:2]]}
            if isinstance(value, bool) or value is None:
                return value
            if key in {"id", "pin_id", "story_pin_id"} and re.fullmatch(r"\d{15,22}", str(value)):
                return str(value)
            if key in {"status", "type", "endpoint_name"} and re.fullmatch(r"[A-Za-z_ -]{1,80}", str(value)):
                return str(value)
            return {"kind": type(value).__name__}

        async def inspect_response(response):
            if urlsplit(response.url).path != "/resource/ApiResource/create/":
                return
            try:
                body = await response.json()
                resource = body.get("resource") or {}
                route = urlsplit(str((resource.get("options") or {}).get("url") or "")).path
                if route != "/v3/storypins/":
                    return
                records = report.setdefault("story_publish_response_shapes", [])
                if len(records) < 3:
                    records.append(
                        {
                            "route": route,
                            "http_status": response.status,
                            "response": shape(body.get("resource_response")),
                        }
                    )
                    save()
            except Exception:
                pass

        def schedule(response):
            task = asyncio.create_task(inspect_response(response))
            tasks.add(task)
            task.add_done_callback(tasks.discard)

        page.on("response", schedule)
        try:
            result = await original_create(driver, *args, **kwargs)
            report["driver_result"] = result
            await capture()
            save()
            return result
        finally:
            page.remove_listener("response", schedule)
            if tasks:
                _, pending = await asyncio.wait(tuple(tasks), timeout=5)
                for task in pending:
                    task.cancel()

    PinterestDriver.create_pin = create_and_capture
    try:
        await supervisor.run(startup_draft_maintenance=False)
    finally:
        PinterestDriver.create_pin = original_create
        report["outcome"] = await queue.get_job_outcome_async(expected_id)
        report["finished_at"] = datetime.now(UTC).isoformat()
        save()
        print(json.dumps({"report": str(output), "settled_by": report.get("settled_by")}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", required=True)
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    asyncio.run(trace(args.account, args.job_id))

"""Inspect the configured creator UI only when its supervisor is stopped."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pinterest_automation.config import get_config
from pinterest_automation.pinterest_driver import PinterestDriver
from pinterest_automation.runtime_state import SupervisorLease, supervisor_status
from pinterest_automation.session_pool import get_session_pool


async def inspect(
    account: str,
    select_all: bool = False,
    delete_dialog: bool = False,
    inspect_auth: bool = False,
    clear_drafts: bool = False,
) -> None:
    status = supervisor_status()
    if status.get("running"):
        raise RuntimeError("Stop and drain the existing supervisor before inspecting its profiles")
    if account not in get_config().accounts:
        raise ValueError("Account must be configured")
    lease = SupervisorLease(worker_count=0)
    lease.acquire()

    async def heartbeat():
        while True:
            lease.heartbeat()
            await asyncio.sleep(5)

    heartbeat_task = asyncio.create_task(heartbeat())
    pool = get_session_pool()
    driver = PinterestDriver()
    try:
        authenticated = None
        if inspect_auth:
            await driver._acquire_session(account)
        else:
            authenticated = await driver.ensure_logged_in(account)
        page = driver._session.page
        resource_responses = []
        capture_tasks = set()
        failed_requests = []
        page.on(
            "requestfailed",
            lambda request: failed_requests.append(
                {"path": urlparse(request.url).path, "failure": request.failure}
            ),
        )

        def shape(value, depth=0, key=""):
            if depth > 5:
                return type(value).__name__
            if isinstance(value, dict):
                return {k: shape(v, depth + 1, k) for k, v in list(value.items())[:30]}
            if isinstance(value, list):
                return {"length": len(value), "sample": [shape(v, depth + 1) for v in value[:2]]}
            if isinstance(value, (int, float, bool)) or value is None:
                return value
            if key in {"status", "is_draft", "type", "id"}:
                return str(value)[:80]
            if key in {"bookmarks", "bookmark", "next_cursor", "next"}:
                return {"is_end": value in ("-end-", "end", ""), "length": len(str(value))}
            return {"kind": type(value).__name__, "length": len(str(value))}

        async def capture_resource(response):
            path = urlparse(response.url).path
            if "/resource/" not in path:
                return
            try:
                payload = await response.json()
                resource = payload.get("resource") or {}
                resource_response = payload.get("resource_response") or {}
                options = resource.get("options") or {}
                resource_responses.append(
                    {
                        "path": path,
                        "status": response.status,
                        "resource_name": resource.get("name"),
                        "route": urlparse(str(options.get("url") or "")).path,
                        "endpoint_name": resource_response.get("endpoint_name"),
                        "terminal_bookmarks": options.get("bookmarks") == ["-end-"],
                        "response": shape(resource_response),
                        "pagination": {
                            k: shape(v, key=k) for k, v in options.items() if "bookmark" in k or "cursor" in k
                        },
                    }
                )
            except Exception:
                resource_responses.append({"path": path, "status": response.status})

        def schedule_capture(response):
            task = asyncio.create_task(capture_resource(response))
            capture_tasks.add(task)
            task.add_done_callback(capture_tasks.discard)

        page.on("response", schedule_capture)
        if authenticated is not False:
            await page.goto(
                "https://www.pinterest.com/pin-creation-tool/", wait_until="domcontentloaded", timeout=45000
            )
        await page.wait_for_timeout(5000)
        render_error = None
        if authenticated is True:
            try:
                await page.wait_for_function(
                    "!!document.querySelector('input[type=file]') && /Pin drafts|Borradores/.test(document.body.innerText)",
                    timeout=60000,
                )
            except Exception as exc:
                render_error = str(exc)
        cleanup = None
        if clear_drafts:
            if authenticated is not True:
                raise RuntimeError("Verified authentication is required before draft cleanup")
            from scripts.ops.clear_pinterest_drafts import clear_drafts_for_page_verified

            cleanup = await clear_drafts_for_page_verified(page, account_name=account, timeout_seconds=90)
            print(json.dumps({"account": account, "draft_cleanup": cleanup}), flush=True)
        if (
            select_all
            and not await page.locator("#storyboard-drafts-sidebar-bulk-select-checkbox").is_checked()
        ):
            try:
                await page.locator('label[for="storyboard-drafts-sidebar-bulk-select-checkbox"]').click(
                    timeout=20000
                )
            except Exception:
                if not await page.locator("#storyboard-drafts-sidebar-bulk-select-checkbox").is_checked():
                    raise
            await page.wait_for_timeout(1000)
        if delete_dialog:
            await page.locator('[data-test-id="bulk-delete-drafts-button"]').click(
                timeout=20000, no_wait_after=True
            )
            await page.wait_for_timeout(1000)
        if capture_tasks:
            await asyncio.wait(tuple(capture_tasks), timeout=15)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        report_dir = ROOT / "data/reports/pinterest_draft_recovery"
        report_dir.mkdir(parents=True, exist_ok=True)
        screenshot = report_dir / f"{account}_{stamp}.png"
        await page.screenshot(path=str(screenshot), full_page=True)
        details = await page.evaluate("""() => ({
          url: location.origin + location.pathname,
          body: document.body.innerText.slice(0, 12000),
          draftDOM: [...document.querySelectorAll('h1,h2,h3,[data-test-id]')]
            .filter(el => /draft|borrador/i.test(el.getAttribute('data-test-id') || '') ||
               (/^(Pin drafts|Borradores)/i.test(el.innerText || '') && /^H[123]$/.test(el.tagName)))
            .map(el=>({test:el.getAttribute('data-test-id'),html:el.outerHTML.slice(0,18000)})).slice(0,30),
          fileInputs: [...document.querySelectorAll('input[type="file"]')]
            .map(el=>({disabled:el.disabled, test:el.getAttribute('data-test-id'),id:el.id})),
          bootstrap: [...document.querySelectorAll('script[type="application/json"]')]
            .map(el=>{try {const data=JSON.parse(el.textContent); return {id:el.id,keys:Object.keys(data).slice(0,12),
              ownerIds:[data.context?.user?.id, data.context?.user_id,
                data.initialReduxState?.session?.user?.id, data.initialReduxState?.session?.userId,
                data.initialReduxState?.session?.user_id].filter(v=>v!=null),
              draftResource:/\\/storypins\\/drafts\\/$/.test(data.resource?.options?.url || '') ? {
                route:data.resource.options.url, endpoint:data.resource_response?.endpoint_name,
                status:data.resource_response?.status, http_status:data.resource_response?.http_status,
                code:data.resource_response?.code, dataLength:Array.isArray(data.resource_response?.data) ? data.resource_response.data.length : null,
                terminalBookmarks:JSON.stringify(data.resource.options.bookmarks)==='["-end-"]'
              } : null,
              resources: Object.entries(data.resourceResponses || data.resources || {}).map(([key,value])=>({key,
                name:value?.resource?.name,route:value?.resource?.options?.url,
                dataKeys:Object.keys(value?.resource_response?.data || {})}))};} catch {return {id:el.id}}}),
          controls: [...document.querySelectorAll('button,[role="button"],input,[role="checkbox"],label')]
            .filter(el=>el.getBoundingClientRect().width && el.getBoundingClientRect().height)
            .map(el=>({tag:el.tagName,role:el.getAttribute('role'),test:el.getAttribute('data-test-id'),id:el.id,
              aria:el.getAttribute('aria-label'),text:(el.innerText || '').slice(0,150),type:el.getAttribute('type'),
              disabled:el.disabled || el.getAttribute('aria-disabled')==='true',
              outer:el.tagName==='INPUT' ? null : el.outerHTML.slice(0,1100)}))
        })""")
        output = report_dir / f"{account}_{stamp}.json"
        output.write_text(
            json.dumps(
                {
                    "account": account,
                    "authenticated": authenticated,
                    "draft_cleanup": cleanup,
                    "resource_responses": resource_responses,
                    "failed_requests": failed_requests,
                    "render_error": render_error,
                    "screenshot": str(screenshot),
                    **details,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        controls = []
        for control in details["controls"]:
            identity = " ".join(str(control.get(k) or "") for k in ["id", "test", "aria", "text"])
            if re.search(r"bulk|select all|delete|discard|selected|sidebar", identity, re.I):
                controls.append(control)
        print(
            json.dumps(
                {
                    "report": str(output),
                    "screenshot": str(screenshot),
                    "body_tail": details["body"][-1600:],
                    "controls": controls,
                },
                ensure_ascii=True,
            )
        )
    finally:
        await driver.close()
        await pool.close_all()
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)
        lease.release()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", required=True)
    parser.add_argument("--select-all", action="store_true")
    parser.add_argument("--delete-dialog", action="store_true")
    parser.add_argument("--inspect-auth", action="store_true")
    parser.add_argument("--clear-drafts", action="store_true")
    args = parser.parse_args()
    asyncio.run(
        inspect(
            args.account,
            args.select_all or args.delete_dialog,
            args.delete_dialog,
            args.inspect_auth,
            args.clear_drafts,
        )
    )

import asyncio
import logging
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from backend.scripts.pinterest_batch_core import cleanup_session_artifacts, load_accounts

logger = logging.getLogger("rankstein.clear_drafts")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


CREATOR_URL = "https://www.pinterest.com/pin-creation-tool/"
_DRAFT_COUNT = re.compile(
    r"(?:Pin\s+drafts|Borradores\s+de\s+pines|Drafts|Borradores)\s*\(\s*(\d+)\s*\)", re.I
)
_CAPACITY_WARNING = re.compile(
    r"(?:reached.{0,40}(?:limit|maximum).{0,30}draft|"
    r"reached.{0,20}draft.{0,20}limit|alcanzado.{0,40}l[ií]mite.{0,30}borrador)",
    re.I,
)
_DELETE_LABEL = re.compile(
    r"^(?:Delete(?: (?:all )?(?:Pin )?drafts?| Pins)?|Discard(?: drafts?)?|Eliminar(?: borradores?)?|Descartar(?: borradores?)?)$",
    re.I,
)
_DRAWER_SELECTORS = (
    '[data-test-id="storyboard-drafts-sidebar"]',
    '[data-test-id="drafts-sidebar"]',
    '[data-test-id="drafts-drawer"]',
    'aside:has-text("Pin drafts")',
    'aside:has-text("Borradores")',
)
_BULK_SELECTORS = (
    'label[for="storyboard-drafts-sidebar-bulk-select-checkbox"]',
    "#storyboard-drafts-sidebar-bulk-select-checkbox",
    '[data-test-id="bulk-select-drafts-checkbox"]',
    'input[type="checkbox"][aria-label="Select all" i]',
    'input[type="checkbox"][aria-label="Seleccionar todo" i]',
    '[role="checkbox"][aria-label="Select all" i]',
)


class DraftCleanupError(RuntimeError):
    """Cleanup could not verify that the account's draft queue is empty."""

    def __init__(self, result):
        self.result = result
        super().__init__(result.get("error") or "Pinterest draft cleanup was not verified")


class _DraftFeedEvidence:
    """Accept only a fresh, owned, complete creator drafts feed as zero proof."""

    def __init__(self, page):
        self.page = page
        self.generation = 0
        self.owner_id = None
        self.empty_owner = None
        self.requests = {}
        self.pending = set()
        self.attached = False
        self.closed = False
        self.trace = {
            "navigations": 0,
            "draft_requests_seen": 0,
            "initial_requests_captured": 0,
            "paginated_requests_rejected": 0,
            "draft_responses_seen": 0,
            "stale_responses_rejected": 0,
            "response_read_failures": 0,
        }
        self.last_feed_checks = None
        self.previous_document = None
        self.current_document = None
        self.current_document_url = None
        self.trace["ssr_empty_feeds_accepted"] = 0

    def attach(self):
        if hasattr(self.page, "on"):
            self.page.on("request", self._request)
            self.page.on("response", self._response)
            self.attached = True

    async def close(self):
        self.closed = True
        self.generation += 1
        self.empty_owner = None
        self.requests.clear()
        if self.attached:
            self.page.remove_listener("request", self._request)
            self.page.remove_listener("response", self._response)
        pending = tuple(self.pending)
        for task in pending:
            task.cancel()
        if pending:
            _done, unfinished = await asyncio.wait(pending, timeout=1.0)
            if unfinished:
                logger.warning("Discarded draft feed reads that did not stop within the cleanup deadline")

    async def resolve_owner(self):
        if self.owner_id is not None or not hasattr(self.page, "evaluate"):
            return
        try:
            owner = await self.page.evaluate(
                """() => {
                  for (const id of ['__PWS_DATA__', '__PWS_INITIAL_PROPS__']) {
                    const el = document.getElementById(id);
                    if (!el) continue;
                    let data; try { data = JSON.parse(el.textContent); } catch { continue; }
                    const session = data.initialReduxState?.session;
                    const candidates = [data.context?.user?.id, data.context?.user_id,
                      session?.user?.id, session?.userId, session?.user_id];
                    for (const value of candidates) {
                      if (value != null && /^\\d+$/.test(String(value))) return String(value);
                    }
                  }
                  return null;
                }"""
            )
            if isinstance(owner, str) and owner.isdigit():
                self.owner_id = owner
        except Exception:
            # Bootstrap ownership may still be rendering; no owner means no
            # network-only count proof, never an assumption about the account.
            pass

    async def begin_navigation(self):
        self.generation += 1
        self.trace["navigations"] += 1
        self.empty_owner = None
        self.requests.clear()
        self.current_document = None
        self.current_document_url = None
        try:
            self.previous_document = await self.page.evaluate("() => performance.timeOrigin")
        except Exception:
            self.previous_document = None
        await self.resolve_owner()

    async def bind_document(self, response):
        """Bind SSR proof to a completed fresh creator document, never an SPA tail."""
        from urllib.parse import urlsplit

        generation = self.generation
        try:
            url = urlsplit(response.url)
            marker = await self.page.evaluate("() => performance.timeOrigin")
            if (
                response.status == 200
                and generation == self.generation
                and url.scheme == "https"
                and (url.hostname == "pinterest.com" or (url.hostname or "").endswith(".pinterest.com"))
                and url.path.rstrip("/") == "/pin-creation-tool"
                and not url.query
                and type(marker) in (int, float)
                and type(self.previous_document) in (int, float)
                and marker != self.previous_document
            ):
                self.current_document = marker
                self.current_document_url = response.url
        except Exception:
            return

    async def read_bootstrap(self):
        if self.closed or self.current_document is None:
            return
        generation = self.generation
        try:
            snapshot = await self.page.evaluate(
                """() => {
                  let owner=null; const feeds=[];
                  for (const el of document.querySelectorAll('script[type="application/json"]')) {
                    let data; try {data=JSON.parse(el.textContent)} catch {continue}
                    if (['__PWS_DATA__','__PWS_INITIAL_PROPS__'].includes(el.id)) {
                      const session=data.initialReduxState?.session;
                      for (const id of [data.context?.user?.id,data.context?.user_id,
                        session?.user?.id,session?.userId,session?.user_id]) {
                        if (id!=null && /^\\d+$/.test(String(id))) {owner=String(id);break}
                      }
                    }
                    const r=data.resource, response=data.resource_response;
                    if (response?.endpoint_name!=='v3_user_story_pin_drafts_feed' || feeds.length>=5) continue;
                    const options=r?.options || {};
                    const cursor=Object.entries(options).some(([key,value])=> {
                      if (key==='bookmarks' || !/bookmark|cursor|^offset$|^page$/i.test(key)) return false;
                      if (value==null || value==='' || (Array.isArray(value)&&value.length===0)) return false;
                      if (/^offset$/i.test(key)) return value!==0;
                      if (/^page$/i.test(key)) return value!==1;
                      return true;
                    });
                    feeds.push({request_cursor_present:cursor,
                      resource:{name:r?.name,options:{url:options.url,bookmarks:options.bookmarks}},
                      resource_response:{status:response.status,code:response.code,http_status:response.http_status,
                        endpoint_name:response.endpoint_name,
                        data:Array.isArray(response.data)&&response.data.length===0?[]:null}});
                  }
                  return {document_token:performance.timeOrigin,url:location.href,owner_id:owner,feeds};
                }"""
            )
            if (
                self.closed
                or generation != self.generation
                or not isinstance(snapshot, dict)
                or snapshot.get("document_token") != self.current_document
                or snapshot.get("url") != self.current_document_url
            ):
                return
            owner = snapshot.get("owner_id")
            if not isinstance(owner, str) or not owner.isdigit() or self.owner_id not in (None, owner):
                return
            for payload in snapshot.get("feeds", [])[:5]:
                if not isinstance(payload, dict) or payload.get("request_cursor_present") is not False:
                    continue
                route = (payload.get("resource") or {}).get("options", {}).get("url")
                if route != f"/v3/users/{owner}/storypins/drafts/":
                    continue
                payload = {**payload, "client_context": {"is_authenticated": True, "user": {"id": owner}}}

                class BootstrapResponse:
                    status = 200

                    def __init__(self, data):
                        self.data = data

                    async def json(self):
                        return self.data

                await self._consume_response(BootstrapResponse(payload), (generation, owner, route))
                if self.empty_owner == owner:
                    self.trace["ssr_empty_feeds_accepted"] += 1
        except Exception:
            return

    def _request(self, request):
        import json
        from urllib.parse import parse_qs, urlsplit

        if self.closed:
            return
        try:
            url = urlsplit(request.url)
            if not (
                url.scheme == "https"
                and (url.hostname == "pinterest.com" or (url.hostname or "").endswith(".pinterest.com"))
                and url.path == "/resource/ApiResource/get/"
            ):
                return
            options = json.loads(parse_qs(url.query)["data"][0])["options"]
            route = options.get("url", "")
            match = re.fullmatch(r"/v3/users/(\d+)/storypins/drafts/", route)
            if match:
                self.trace["draft_requests_seen"] += 1
            # An empty later page is never proof that the entire collection
            # is empty. Capture only the initial, unbookmarked feed request.
            if not match:
                return
            if options.get("bookmarks") not in (None, []):
                self.trace["paginated_requests_rejected"] += 1
                return
            self.requests[id(request)] = (request, (self.generation, match.group(1), route))
            self.trace["initial_requests_captured"] += 1
        except (AttributeError, KeyError, TypeError, ValueError):
            return

    def _response(self, response):
        if self.closed:
            return
        request = getattr(response, "request", None)
        captured = self.requests.pop(id(request), None)
        if captured is None or captured[0] is not request:
            return
        task = asyncio.create_task(self._consume_response(response, captured[1]))
        self.trace["draft_responses_seen"] += 1
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)

    async def _consume_response(self, response, metadata):
        generation, owner_id, route = metadata
        if self.closed or generation != self.generation:
            self.trace["stale_responses_rejected"] += 1
            return
        try:
            async with asyncio.timeout(10):
                if response.status != 200:
                    self.last_feed_checks = {"http_200": False}
                    return
                payload = await response.json()
            if self.closed or generation != self.generation:
                self.trace["stale_responses_rejected"] += 1
                return
            result = payload.get("resource_response", {})
            resource = payload.get("resource", {})
            options = resource.get("options", {})
            context = payload.get("client_context", {})
            context_owner = (context.get("user") or {}).get("id") or context.get("user_id")
            if context_owner is not None:
                context_owner = str(context_owner)
                if not context_owner.isdigit() or context_owner != owner_id:
                    self.last_feed_checks = {"context_owner_matches": False}
                    return
                if self.owner_id is None and context.get("is_authenticated") is True:
                    self.owner_id = context_owner
            checks = {
                "current_navigation": generation == self.generation,
                "owner_compatible": self.owner_id in (None, owner_id),
                "resource_is_api": resource.get("name") == "ApiResource",
                "route_matches_request": options.get("url") == route,
                "terminal_bookmark": options.get("bookmarks") == ["-end-"],
                "resource_success": result.get("status") == "success",
                "code_zero": result.get("code") == 0,
                "http_200": result.get("http_status") == 200,
                "draft_feed_endpoint": result.get("endpoint_name") == "v3_user_story_pin_drafts_feed",
                "data_empty": result.get("data") == [],
            }
            self.last_feed_checks = checks
            if all(checks.values()):
                self.empty_owner = owner_id
                if self.owner_id is None:
                    logger.info(
                        "Draft feed is empty, but creator ownership must be established before using count proof"
                    )
        except Exception:
            self.trace["response_read_failures"] += 1
            # The UI count remains authoritative when response bodies are
            # unavailable or the feed schema is unfamiliar.
            return

    def summary(self):
        return {
            **self.trace,
            "owner_resolved": self.owner_id is not None,
            "fresh_document_bound": self.current_document is not None,
            "empty_feed_seen": self.empty_owner is not None,
            "empty_feed_owner_matches": self.owner_id is not None and self.empty_owner == self.owner_id,
            "last_feed_checks": self.last_feed_checks,
        }

    async def bootstrap_probe(self):
        """Return contract shapes only; never bootstrap values or account IDs."""
        try:
            async with asyncio.timeout(1.0):
                return await self.page.evaluate(
                    """() => {
                      const result = {available:true, context_keys:[], session_keys:[], embedded_draft_feeds:[]};
                      for (const el of document.querySelectorAll('script[type="application/json"]')) {
                        if (!el.textContent || el.textContent.length > 5000000) continue;
                        let data; try {data=JSON.parse(el.textContent)} catch {continue}
                        if (el.id==='__PWS_DATA__') result.context_keys=Object.keys(data.context || {}).slice(0,25);
                        if (el.id==='__PWS_INITIAL_PROPS__') result.session_keys=Object.keys(data.initialReduxState?.session || {}).slice(0,25);
                        const response=data.resource_response, resource=data.resource;
                        if (response?.endpoint_name!=='v3_user_story_pin_drafts_feed') continue;
                        result.embedded_draft_feeds.push({
                          resource_is_api:resource?.name==='ApiResource',
                          route_is_draft_feed:/^\\/v3\\/users\\/\\d+\\/storypins\\/drafts\\/$/.test(resource?.options?.url || ''),
                          terminal_bookmark:JSON.stringify(resource?.options?.bookmarks)==='["-end-"]',
                          resource_success:response.status==='success',code_zero:response.code===0,
                          http_200:response.http_status===200,data_is_array:Array.isArray(response.data),
                          data_count:Array.isArray(response.data)?response.data.length:null
                        });
                        if (result.embedded_draft_feeds.length>=5) break;
                      }
                      return result;
                    }"""
                )
        except Exception:
            return {"available": False}

    def apply_count(self, state):
        if state["count"] not in (None, 0):
            self.empty_owner = None
        elif state["count"] is None and self.owner_id is not None and self.empty_owner == self.owner_id:
            state = {**state, "count": 0}
        return state


async def _visible_first(scope, selectors):
    """Return a fresh locator; Pinterest replaces the drawer after each action."""
    for selector in selectors:
        locator = scope.locator(selector)
        for index in range(min(await locator.count(), 20)):
            candidate = locator.nth(index)
            if await candidate.is_visible() and await candidate.is_enabled():
                return candidate
    return None


async def _read_draft_state(page):
    text = await page.locator("body").inner_text(timeout=3000)
    match = _DRAFT_COUNT.search(text)
    count = int(match.group(1)) if match else None
    blocked = bool(_CAPACITY_WARNING.search(text))
    ready = False
    if not blocked:
        inputs = page.locator(
            'input[type="file"], #storyboard-selector-title, [data-test-id="pin-draft-title"] textarea'
        )
        for index in range(min(await inputs.count(), 5)):
            if await inputs.nth(index).is_enabled():
                ready = True
                break
        if not ready:
            create = page.get_by_role("button", name=re.compile(r"^(?:Create new|Crear nuevo)$", re.I))
            for index in range(min(await create.count(), 5)):
                if await create.nth(index).is_visible() and await create.nth(index).is_enabled():
                    ready = True
                    break
    return {"count": count, "blocked": blocked, "creator_ready": ready}


def _transient_page_error(error):
    """Only retry navigation/render failures; programming errors stay visible."""
    return (
        isinstance(error, TimeoutError)
        or type(error).__name__ == "TimeoutError"
        or bool(
            re.search(
                r"execution context was destroyed|cannot find context|"
                r"frame was detached|interrupted by another navigation|"
                r"navigation .{0,80}(?:failed|interrupted)",
                str(error),
                re.I,
            )
        )
    )


async def _retry_page_operation(operation):
    """Allow a transient creator rerender without resetting the cleanup deadline."""
    for attempt in range(3):
        try:
            return await operation()
        except Exception as error:
            if attempt == 2 or not _transient_page_error(error):
                raise
            await asyncio.sleep(0.25)


async def _read_draft_state_resilient(page, evidence=None):
    state = await _retry_page_operation(lambda: _read_draft_state(page))
    if evidence is not None:
        await evidence.resolve_owner()
        if state["count"] is None:
            await evidence.read_bootstrap()
        state = evidence.apply_count(state)
    return state


async def _navigate_creator(page, evidence=None):
    async def navigate():
        if evidence is not None:
            await evidence.begin_navigation()
        response = await page.goto(CREATOR_URL, wait_until="domcontentloaded", timeout=20000)
        if evidence is not None:
            await evidence.bind_document(response)
        return response

    return await _retry_page_operation(navigate)


async def _draft_drawer(page):
    drawer = await _visible_first(page, _DRAWER_SELECTORS)
    if drawer is not None:
        return drawer
    # Current creator pages can render the sidebar open without a test ID.
    # Detect its known checkbox before looking for an expand control.
    checkbox = await _visible_first(page, _BULK_SELECTORS)
    if checkbox is not None:
        drawer = checkbox.locator("xpath=ancestor::*[.//button][1]")
        if await drawer.count():
            return drawer
    toggle = await _visible_first(
        page,
        (
            '[data-test-id="expand-drafts-sidebar-button"]',
            '[data-test-id="drafts-drawer-toggle"]',
            '[data-test-id="open-drafts-button"]',
            'button[aria-label="Drafts" i]',
            'button[aria-label="Borradores" i]',
            'button[aria-label="Open drafts sidebar" i]',
            'button[aria-label="Open drafts" i]',
        ),
    )
    if toggle is not None:
        await toggle.click(timeout=2500)
        await asyncio.sleep(0.2)
        drawer = await _visible_first(page, _DRAWER_SELECTORS)
    # A known draft checkbox itself is sufficient to establish drawer scope.
    # Never use the whole creator page as the scope for an ordinary Delete.
    if drawer is None:
        checkbox = await _visible_first(page, _BULK_SELECTORS)
        if checkbox is not None:
            drawer = checkbox.locator("xpath=ancestor::*[.//button][1]")
            if not await drawer.count():
                drawer = None
    return drawer


async def _exact_delete(scope):
    buttons = scope.get_by_role("button", name=_DELETE_LABEL)
    for index in range(min(await buttons.count(), 15)):
        button = buttons.nth(index)
        if await button.is_visible() and await button.is_enabled():
            return button
    return None


async def _confirm_draft_delete(page):
    for _poll in range(30):
        dialogs = page.locator('[role="dialog"], [role="alertdialog"]')
        for index in range(min(await dialogs.count(), 5)):
            dialog = dialogs.nth(index)
            if not await dialog.is_visible():
                continue
            text = await dialog.inner_text(timeout=2000)
            if not re.search(r"draft|borrador", text, re.I):
                return False
            button = await _exact_delete(dialog)
            if button is not None:
                await button.click(timeout=5000, no_wait_after=True)
                return True
        await asyncio.sleep(0.1)
    return False


async def _bulk_is_checked(bulk):
    return await bulk.evaluate(
        "el => el.checked === true || el.getAttribute('aria-checked') === 'true' || "
        "(el.control && el.control.checked === true)"
    )


async def _delete_draft_batch(page, drawer):
    bulk = await _visible_first(drawer, _BULK_SELECTORS)
    if bulk is not None:
        # A checked bulk checkbox must not be toggled off after a rerender.
        if not await _bulk_is_checked(bulk):
            try:
                await bulk.click(timeout=5000, no_wait_after=True)
            except Exception:
                # Click may have changed selection before Playwright timed out
                # on unrelated app navigation. Inspect before toggling again.
                bulk = await _visible_first(page, _BULK_SELECTORS)
                if bulk is None or not await _bulk_is_checked(bulk):
                    raise
        if not await _bulk_is_checked(bulk):
            return False
        await asyncio.sleep(0.2)
        drawer = await _draft_drawer(page)
        if drawer is None:
            return False
        button = await _visible_first(
            drawer,
            ('[data-test-id="bulk-delete-drafts-button"]', '[data-test-id="delete-drafts-button"]'),
        )
        button = button or await _exact_delete(drawer)
        if button is not None:
            await button.click(timeout=5000, no_wait_after=True)
            await asyncio.sleep(0.2)
            await _confirm_draft_delete(page)
            return True

    actions = await _visible_first(
        drawer,
        (
            'button[aria-label*="draft actions" i]',
            '[data-test-id="draft-actions-button"]',
            '[data-test-id="pin-draft-actions-button"]',
        ),
    )
    if actions is None:
        return False
    await actions.click(timeout=5000, no_wait_after=True)
    await asyncio.sleep(0.2)
    # Menu portals are scoped independently from the drawer, and the action
    # has to say draft explicitly before it can be clicked outside the drawer.
    action = await _visible_first(page, ('[data-test-id="delete-draft-action"]',))
    if action is None:
        menus = page.locator('[role="menu"]')
        for index in range(min(await menus.count(), 5)):
            menu = menus.nth(index)
            if await menu.is_visible():
                action = await _exact_delete(menu)
                if action is not None:
                    break
    if action is None:
        return False
    await action.click(timeout=5000, no_wait_after=True)
    await asyncio.sleep(0.2)
    await _confirm_draft_delete(page)
    return True


async def _clear_drafts_for_page_verified(
    page, account_name: str = "account", *, timeout_seconds=90.0, evidence=None
):
    """Empty creator drafts and return actual observed count/readiness proof.

    Runs inside the caller's existing account session. A missing selector,
    clicked dialog, or expired deadline is never proof of deletion.
    """
    initial_count = None
    remaining_count = None
    deleted = 0
    creator_ready = False
    error = None
    render_refresh_used = False

    async def read_state():
        nonlocal render_refresh_used
        try:
            return await _read_draft_state_resilient(page, evidence)
        except Exception as exc:
            if render_refresh_used or not _transient_page_error(exc):
                raise
            # Repeating a body read cannot recover a creator stuck between
            # documents. Refresh this same leased page once, within the outer
            # deadline, and invalidate any proof from the previous document.
            render_refresh_used = True
            logger.warning(
                "[%s] Creator state stayed unreadable; refreshing once within the cleanup deadline",
                account_name,
            )
            await _navigate_creator(page, evidence)
            return await _read_draft_state_resilient(page, evidence)

    try:
        async with asyncio.timeout(timeout_seconds):
            await _navigate_creator(page, evidence)
            stalled = 0
            unknown = 0
            for _attempt in range(64):
                if "login" in page.url:
                    raise RuntimeError("Pinterest redirected to login during draft cleanup")
                state = await read_state()
                remaining_count = state["count"]
                creator_ready = state["creator_ready"]
                if initial_count is None and remaining_count is not None:
                    initial_count = remaining_count
                if initial_count is not None and remaining_count is not None:
                    deleted = max(0, initial_count - remaining_count)
                if remaining_count == 0 and not state["blocked"] and creator_ready:
                    # Reload once to prove deletions persisted and the warning
                    # disappeared, rather than trusting an optimistic drawer.
                    await _navigate_creator(page, evidence)
                    verified = await read_state()
                    for _render_poll in range(40):
                        remaining_count = verified["count"]
                        creator_ready = verified["creator_ready"]
                        deleted = (
                            max(0, initial_count - remaining_count) if remaining_count is not None else 0
                        )
                        if verified["count"] not in (None, 0):
                            break
                        if verified["count"] == 0 and not verified["blocked"] and verified["creator_ready"]:
                            break
                        await asyncio.sleep(0.25)
                        verified = await read_state()
                    if verified["count"] is not None:
                        remaining_count = verified["count"]
                        deleted = max(0, initial_count - remaining_count)
                    if verified["count"] == 0 and not verified["blocked"] and verified["creator_ready"]:
                        remaining_count = 0
                        creator_ready = verified["creator_ready"]
                        logger.info(
                            "[%s] Draft cleanup verified: %s removed, 0 remain", account_name, deleted
                        )
                        return {
                            "ok": True,
                            "success": True,
                            "deleted": deleted,
                            "initial_count": initial_count,
                            "remaining_count": 0,
                            "remaining": 0,
                            "creator_ready": creator_ready,
                            "error": None,
                        }
                if remaining_count == 0:
                    unknown += 1
                    if unknown > 40:
                        raise RuntimeError("Drafts are empty but creator readiness could not be verified")
                    await asyncio.sleep(0.25)
                    continue
                if remaining_count is None:
                    unknown += 1
                    if unknown > 40:
                        raise RuntimeError(
                            "Draft count could not be verified; missing controls are not an empty queue"
                        )
                    await _draft_drawer(page)
                    await asyncio.sleep(0.25)
                    continue
                drawer = await _draft_drawer(page)
                try:
                    progressed = drawer is not None and await _delete_draft_batch(page, drawer)
                except Exception as exc:
                    logger.warning("[%s] Draft action will be reinspected: %s", account_name, exc)
                    progressed = False
                if progressed:
                    for _poll in range(16):
                        await asyncio.sleep(0.25)
                        after = await read_state()
                        if after["count"] is not None and after["count"] < remaining_count:
                            remaining_count = after["count"]
                            deleted = max(0, initial_count - remaining_count)
                            stalled = 0
                            break
                    else:
                        stalled += 1
                else:
                    stalled += 1
                if stalled >= 3:
                    raise RuntimeError(
                        f"Draft cleanup made no verified progress; {remaining_count} draft(s) remain"
                    )
                if stalled:
                    await _navigate_creator(page, evidence)
                    await asyncio.sleep(0.25)
            raise RuntimeError("Draft cleanup exceeded bounded action attempts")
    except Exception as exc:
        error = str(exc) or type(exc).__name__
        logger.warning("[%s] Draft cleanup unverified: %s", account_name, error)
        # A deadline can expire between a reload and its first render poll.
        # Capture current state briefly so the failure report never presents
        # an optimistic pre-reload zero as persisted deletion proof.
        try:
            async with asyncio.timeout(1.0):
                final_state = await _read_draft_state(page)
                remaining_count = final_state["count"]
                creator_ready = final_state["creator_ready"]
                deleted = (
                    max(0, initial_count - remaining_count)
                    if initial_count is not None and remaining_count is not None
                    else 0
                )
        except Exception:
            remaining_count = None
            creator_ready = False
            deleted = 0
    return {
        "ok": False,
        "success": False,
        "deleted": deleted,
        "initial_count": initial_count,
        "remaining_count": remaining_count,
        "remaining": remaining_count,
        "creator_ready": creator_ready,
        "error": error,
    }


async def clear_drafts_for_page_verified(page, account_name: str = "account", *, timeout_seconds=90.0):
    evidence = _DraftFeedEvidence(page)
    evidence.attach()
    try:
        result = await _clear_drafts_for_page_verified(
            page, account_name, timeout_seconds=timeout_seconds, evidence=evidence
        )
        if not result.get("ok"):
            result["draft_feed_evidence"] = evidence.summary()
            result["draft_feed_evidence"]["bootstrap_probe"] = await evidence.bootstrap_probe()
        return result
    finally:
        await evidence.close()


async def clear_drafts_for_page(page, account_name: str = "account") -> int:
    """Compatibility wrapper; return a count only after verified empty drafts."""
    result = await clear_drafts_for_page_verified(page, account_name)
    if not result["ok"]:
        raise DraftCleanupError(result)
    return result["deleted"]


async def aggressive_clear(account) -> dict:
    account_name = getattr(account, "name", str(account))
    session_leaf = getattr(account, "session_name", None) or account_name
    session_dir = getattr(account, "session_dir", None) or (project_root / "data" / "sessions" / session_leaf)
    browser_type = getattr(account, "browser", "chromium")
    email = getattr(account, "email", "")
    password = getattr(account, "password", "")

    logger.info(f"--- DRAFT PURGE START: {account_name} ({browser_type}) ---")
    cleanup_session_artifacts(Path(session_dir), browser_type)

    deleted = 0
    cleanup_result = None
    proof_screenshots = []
    screenshots_dir = project_root / "data" / "reports" / "screenshots" / "draft_clearing"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    try:
        async with async_playwright() as p:
            browser_launcher = p.chromium if browser_type == "chromium" else p.firefox
            context = await browser_launcher.launch_persistent_context(
                user_data_dir=str(session_dir),
                headless=True,
                viewport={"width": 1280, "height": 800},
                args=["--no-sandbox", "--disable-dev-shm-usage"] if browser_type == "chromium" else [],
            )
            page = context.pages[0] if context.pages else await context.new_page()
            try:
                # 1. Ensure account is logged in BEFORE clearing drafts
                from backend.scripts.pinterest_batch_core import ensure_logged_in, pinterest_session_valid

                is_valid = await pinterest_session_valid(page)
                if not is_valid and email and password:
                    logger.info(f"[{account_name}] Session invalid or unauthenticated, logging in first...")
                    logged_in = await ensure_logged_in(page, email, password)
                    if not logged_in:
                        logger.warning(
                            f"[{account_name}] Authentication failed before draft clear; capturing proof."
                        )
                        fail_path = screenshots_dir / f"{account_name}_auth_fail_{timestamp}.png"
                        await page.screenshot(path=str(fail_path))
                        proof_screenshots.append(str(fail_path))
                        return {
                            "account": account_name,
                            "ok": False,
                            "error": "Authentication failed before draft clear",
                            "deleted": 0,
                            "proof_screenshots": proof_screenshots,
                        }
                elif not is_valid:
                    logger.warning(
                        f"[{account_name}] Session invalid and no email/password credentials available."
                    )

                # 2. Capture Initial Creator State Screenshot
                await page.goto(
                    "https://www.pinterest.com/pin-creation-tool/",
                    wait_until="domcontentloaded",
                    timeout=45000,
                )
                await asyncio.sleep(3)
                before_path = screenshots_dir / f"{account_name}_before_{timestamp}.png"
                await page.screenshot(path=str(before_path))
                proof_screenshots.append(str(before_path))
                logger.info(f"[{account_name}] Captured initial visual proof: {before_path.name}")

                # 3. Clear Drafts
                cleanup_result = await clear_drafts_for_page_verified(page, account_name)
                deleted = cleanup_result["deleted"]

                # 4. Capture Final Verified State Screenshot
                await asyncio.sleep(2)
                after_path = screenshots_dir / f"{account_name}_after_{timestamp}.png"
                await page.screenshot(path=str(after_path))
                proof_screenshots.append(str(after_path))
                logger.info(f"[{account_name}] Captured final visual proof: {after_path.name}")

            finally:
                await context.close()
    except Exception as exc:
        logger.error(f"[{account_name}] Purge session failed: {exc}")
        return {
            "account": account_name,
            "ok": False,
            "error": str(exc),
            "deleted": deleted,
            "proof_screenshots": proof_screenshots,
        }

    logger.info(
        f"--- DRAFT PURGE COMPLETE: {account_name} (deleted={deleted}, proofs={len(proof_screenshots)}) ---"
    )
    return {
        "account": account_name,
        "ok": bool(cleanup_result and cleanup_result["ok"]),
        "deleted": deleted,
        "proof_screenshots": proof_screenshots,
        "cleanup": cleanup_result,
        "error": cleanup_result["error"] if cleanup_result else "Draft cleanup did not run",
    }


async def clear_all_accounts_drafts() -> list[dict]:
    """Purge drafts for all configured Pinterest accounts."""
    load_dotenv()
    accounts = load_accounts()
    if not accounts:
        logger.warning("No configured Pinterest accounts found to clear drafts.")
        return []

    results = []
    for acc in accounts:
        res = await aggressive_clear(acc)
        results.append(res)
    return results


async def main():
    results = await clear_all_accounts_drafts()
    logger.info(f"Finished clearing drafts for {len(results)} accounts: {results}")


if __name__ == "__main__":
    asyncio.run(main())

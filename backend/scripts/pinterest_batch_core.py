import argparse
import asyncio
import json
import logging
import os
import random
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import piexif

project_root = Path(__file__).resolve().parent.parent.parent
try:
    from dotenv import load_dotenv

    load_dotenv(project_root / ".env")
except Exception:
    pass

sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "backend" / "scripts"))

import batch_upload_remastered
from batch_upload_remastered import (
    build_pin_description,
    ensure_logged_in,
    get_board_for_slug,
    get_supabase,
    update_pin_id,
)

batch_upload_remastered.PINTEREST_BASE = "https://www.pinterest.com"

from pinterest_automation.circuit_breaker import get_circuit_breaker
from pinterest_automation.config import resolve_account_board_name

circuit = get_circuit_breaker()


MEDIA_DIR = project_root / "data" / "media" / "remaster_final"
UPLOADED_TRACKER = project_root / "data" / "media" / "uploaded_remasters.txt"
LOG_DIR = project_root / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    handlers=[
        RotatingFileHandler(
            str(LOG_DIR / "turbo_upload_v3.log"),
            maxBytes=5 * 1024 * 1024,
            backupCount=2,
            encoding="utf-8",
        ),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("Turbo")
logger.setLevel(logging.INFO)
logger.handlers.clear()
formatter = logging.Formatter("%(asctime)s | %(name)s | %(levelname)s | %(message)s")
fh = RotatingFileHandler(
    str(LOG_DIR / "turbo_upload_v3.log"),
    maxBytes=5 * 1024 * 1024,
    backupCount=2,
    encoding="utf-8",
)
fh.setFormatter(formatter)
sh = logging.StreamHandler()
sh.setFormatter(formatter)
logger.addHandler(fh)
logger.addHandler(sh)
logger.propagate = False


def _int_env(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


BROWSER_DEAD_MARKERS = (
    "target page, context or browser has been closed",
    "connection closed",
    "browser has been closed",
    "juggler pipe",
    "ns_error_net_http3_protocol_error",
)
MAX_ITEM_ATTEMPTS = max(1, _int_env("PINTEREST_MAX_ITEM_ATTEMPTS", 3))
MAX_BROWSER_LAUNCH_ATTEMPTS = max(1, _int_env("PINTEREST_BROWSER_LAUNCH_ATTEMPTS", 3))
DEFAULT_SESSION_POOL = (
    "turbo_v4",
    "turbo_v5",
    "turbo_v6",
    "remasterer_v1",
    "harvester_v1",
    "pinterest_rida_v7",
)
DEFAULT_BROWSER_MAP = {
    "turbo_v4": "chromium",
    "turbo_v5": "chromium",
    "turbo_v6": "chromium",
    "rida_v2_1": "chromium",
    "rida_v2_2": "chromium",
    "rida_v2_3": "chromium",
    "remasterer_v1": "firefox",
    "harvester_v1": "firefox",
    "pinterest_rida_v7": "chromium",
}
SESSION_LOCK_FILES = ("parent.lock", ".parentlock", "lock")
SESSION_STALE_GLOBS = ("*.pid", "*.tmp", "lock.*", "*-wal", "*-shm")
SESSION_CLONE_IGNORE = (
    "parent.lock",
    ".parentlock",
    "lock",
    "*.pid",
    "*.tmp",
    "lock.*",
    "*-wal",
    "*-shm",
    "cache2",
    "startupCache",
    "thumbnails",
    "crashes",
    "minidumps",
)


@dataclass(frozen=True)
class PinterestAccount:
    name: str
    session_dir: Path
    email: str = ""
    password: str = ""
    browser: str = "firefox"


class BrowserSessionLost(RuntimeError):
    """Raised when Playwright's Firefox context is no longer usable."""


class PinCreationError(RuntimeError):
    """Raised when the pin automation flow fails cleanly."""

    """Raised when Playwright's Firefox context is no longer usable."""


class PinterestDraftCapacityError(PinCreationError):
    """The account's creator remains blocked by Pinterest's draft capacity."""

    error_code = "pinterest_draft_capacity"


class PinterestPublishUnavailableError(PinCreationError):
    """The creator never exposed an actionable publish control."""

    error_code = "pinterest_publish_unavailable"


class PinterestPublishUncertainError(PinCreationError):
    """A publish action may have occurred, but publication remains unverified."""

    error_code = "pinterest_publish_uncertain"
    uncertain = True


def _publish_diagnostic_text(value):
    if not isinstance(value, (str, int, float, bool)):
        return "[non-scalar]"
    text = str(value or "")[:400]
    text = re.sub(r"https?://\S+", "[url]", text, flags=re.I)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email]", text)
    text = re.sub(r"\b[A-Za-z0-9_=-]{40,}\b", "[token]", text)
    text = re.sub(
        r"\b(password|passwd|token|authorization|cookie|secret)\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|\S+)",
        r"\1=[redacted]",
        text,
        flags=re.I,
    )
    return " ".join(text.split())[:160]


def _publish_diagnostic_route(value):
    """Keep endpoint names while dropping query strings and identifier values."""
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.netloc and not (
        parsed.hostname == "pinterest.com" or (parsed.hostname or "").endswith(".pinterest.com")
    ):
        return "[external-route]"
    parts = []
    for segment in parsed.path.split("/")[:24]:
        if not segment:
            parts.append(segment)
        elif segment.isdigit() or re.fullmatch(
            r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", segment
        ):
            parts.append("[id]")
        elif (
            re.fullmatch(r"[0-9a-fA-F]{32}", segment)
            or len(segment) > 80
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", segment)
            or (len(segment) >= 32 and not re.fullmatch(r"[a-z]+(?:[_-][a-z]+)+", segment))
        ):
            parts.append("[token]")
        else:
            parts.append(segment)
    return "/".join(parts)[:240]


def _publish_diagnostic_flags(options):
    """Expose only explicit publication state, never arbitrary option values."""
    flags = {}
    sources = [options]
    if isinstance(options.get("data"), dict):
        sources.append(options["data"])
    for source in sources:
        for key in ("publish", "is_draft"):
            if type(source.get(key)) is bool:
                flags[key] = source[key]
        status = source.get("status")
        if isinstance(status, str) and status.lower() in {
            "draft",
            "published",
            "publishing",
            "unpublished",
            "pending",
            "scheduled",
            "success",
            "failure",
            "failed",
            "error",
        }:
            flags["status"] = status.lower()
    return flags


class _PublishNetworkDiagnostics:
    """Keep bounded, sanitized mutation evidence for this single publish action."""

    def __init__(self, page):
        self.page = page
        self.events = []
        self.requests = {}
        self.pending = set()
        self.attached = False
        self.closed = False
        self.click_started = False
        self.click_completed = False

    def attach(self):
        if not self.attached:
            for event, callback in (
                ("request", self._request),
                ("response", self._response),
                ("requestfailed", self._request_failed),
            ):
                self.page.on(event, callback)
            self.attached = True

    def _request(self, request):
        if self.closed or len(self.events) >= 20:
            return
        try:
            parsed = urlsplit(request.url)
            method = request.method.upper()
            if (
                parsed.scheme != "https"
                or not (
                    parsed.hostname == "pinterest.com" or (parsed.hostname or "").endswith(".pinterest.com")
                )
                or method not in {"POST", "PUT", "PATCH", "DELETE"}
            ):
                return
            path = parsed.path
            operation = ""
            mutation = True
            extra = {}
            if "graphql" in path.lower():
                try:
                    body = json.loads(request.post_data or "{}")
                except (TypeError, ValueError):
                    body = {}
                if not isinstance(body, dict):
                    body = {}
                operation = str(body.get("operationName") or "")
                if not re.fullmatch(r"[A-Za-z0-9_]{1,100}", operation):
                    operation = "unknown"
                query = str(body.get("query") or "").lstrip()
                if query.startswith("query ") or query.startswith("query{"):
                    return
                if not query.startswith("mutation") and not re.search(
                    r"(?:create|publish|update|delete|save).*(?:pin|story)|(?:pin|story).*(?:create|publish|update|delete|save)",
                    operation,
                    re.I,
                ):
                    mutation = None
            elif re.fullmatch(
                r"/resource/ApiResource/(?:get|create|update|delete|save|publish)/?", path, re.I
            ):
                operation = "/".join(path.strip("/").split("/")[-2:])
                mutation = None
                query_data = parse_qs(parsed.query).get("data", [None])[0]
                raw = query_data or request.post_data or ""
                if isinstance(raw, str) and len(raw) <= 65536:
                    if not raw.lstrip().startswith("{"):
                        raw = parse_qs(raw).get("data", [""])[0]
                    try:
                        options = json.loads(raw).get("options", {})
                    except (AttributeError, TypeError, ValueError):
                        options = {}
                    if isinstance(options, dict):
                        route = options.get("url")
                        logical_method = str(options.get("method") or "").upper()
                        extra["option_keys"] = [
                            key
                            if isinstance(key, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", key)
                            else "[other]"
                            for key in list(options)[:25]
                        ]
                        safe_route = _publish_diagnostic_route(route)
                        if safe_route is not None:
                            extra["route"] = safe_route
                        flags = _publish_diagnostic_flags(options)
                        if flags:
                            extra["flags"] = flags
                        if (
                            isinstance(route, str)
                            and re.fullmatch(
                                r"/v3/(?:users/\d+/)?(?:pins|storypins|story_pins)(?:/[A-Za-z0-9_-]+)*/?",
                                urlsplit(route).path,
                                re.I,
                            )
                            and route.startswith("/v3/")
                        ):
                            if logical_method in {"POST", "PUT", "PATCH", "DELETE"}:
                                mutation = True
                                extra["api_method"] = logical_method
                            elif logical_method == "GET":
                                return
                            elif not path.lower().rstrip("/").endswith("/get"):
                                mutation = True
            elif re.fullmatch(
                r"/resource/[^/]*(?:Pin|Story|Board)[^/]*/(?:create|update|delete|save|publish)/?", path, re.I
            ):
                operation = "/".join(path.strip("/").split("/")[-2:])
            elif re.fullmatch(r"/v3/(?:pins|story_pins)(?:/\d+)?/?", path, re.I):
                operation = f"{method} pin"
            else:
                return
            # Do not retain pin IDs, query strings, headers, or request bodies.
            safe_path = re.sub(r"/\d+(?=/|$)", "/[id]", path)[:160]
            event = {
                "method": method,
                "path": safe_path,
                "operation": operation,
                "mutation": mutation,
                **extra,
            }
            self.events.append(event)
            self.requests[id(request)] = (request, event)
        except (AttributeError, TypeError, ValueError):
            return

    def _response(self, response):
        if self.closed:
            return
        request = response.request
        captured = self.requests.pop(id(request), None)
        if captured is None or captured[0] is not request:
            return
        event = captured[1]
        event["status"] = response.status
        task = asyncio.create_task(self._consume_response(response, event))
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)

    async def _consume_response(self, response, event):
        try:
            async with asyncio.timeout(3):
                body = await response.json()
            if self.closed or not isinstance(body, dict):
                return
            resource = body.get("resource_response", body)
            if not isinstance(resource, dict):
                return
            status = resource.get("status")
            if isinstance(status, str):
                event["resource_status"] = _publish_diagnostic_text(status)
            errors = body.get("errors")
            error = resource.get("error")
            if not error and isinstance(errors, list) and errors:
                error = errors[0]
            rejected = response.status >= 400 or bool(error) or status in {"failure", "failed", "error"}
            code = resource.get("code")
            if code not in (None, 0, 200, "0", "200"):
                rejected = True
            if rejected:
                event["rejected"] = True
                if isinstance(error, dict):
                    code = error.get("code") or code
                    message = error.get("message") or error.get("error_message")
                else:
                    message = error or resource.get("message") or resource.get("error_message")
                if code is not None:
                    event["error_code"] = _publish_diagnostic_text(code)
                if message:
                    event["error_message"] = _publish_diagnostic_text(message)
        except Exception:
            return

    def _request_failed(self, request):
        captured = self.requests.pop(id(request), None)
        if self.closed or captured is None or captured[0] is not request:
            return
        match = re.search(r"net::[A-Z0-9_]+", str(getattr(request, "failure", "")))
        captured[1]["request_failure"] = match.group(0) if match else "request_failed"

    async def close(self):
        if self.closed:
            return
        if self.attached:
            for event, callback in (
                ("request", self._request),
                ("response", self._response),
                ("requestfailed", self._request_failed),
            ):
                self.page.remove_listener(event, callback)
        try:
            if self.pending:
                await asyncio.wait(tuple(self.pending), timeout=0.5)
        finally:
            self.closed = True
            self.requests.clear()
            for task in tuple(self.pending):
                task.cancel()

    def summary(self):
        return {
            "click_started": self.click_started,
            "click_completed": self.click_completed,
            "mutating_requests": sum(event["mutation"] is True for event in self.events),
            "unknown_graphql_requests": sum(
                event["mutation"] is None and "graphql" in event["path"].lower() for event in self.events
            ),
            "unknown_api_requests": sum(
                event["mutation"] is None and event["operation"].startswith("ApiResource/")
                for event in self.events
            ),
            "rejected_responses": sum(
                event.get("rejected", False) or event.get("status", 0) >= 400 for event in self.events
            ),
            "request_failures": sum("request_failure" in event for event in self.events),
            "capture_limit_reached": len(self.events) >= 20,
            "requests": [dict(event) for event in self.events],
        }


async def _wait_for_actionable_publish(page, worker_id, diagnostics, timeout_seconds):
    """Wait for one exact, actionable Publish control; never force or repeat it."""
    labels = re.compile(r"^(?:Publish(?: now)?|Publicar(?: ahora)?)$", re.I)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        groups = (
            page.get_by_role("button", name=labels),
            page.locator('[data-test-id="storyboard-creation-nav-done"]'),
        )
        for group in groups:
            for index in range(min(await group.count(), 10)):
                button = group.nth(index)
                text = " ".join((await button.inner_text(timeout=1000)).split())
                if (
                    not labels.fullmatch(text)
                    or not await button.is_visible()
                    or not await button.is_enabled()
                ):
                    continue
                diagnostics.attach()
                diagnostics.click_started = True
                logger.info("[%s] Clicking actionable exact Publish control", worker_id)
                try:
                    await button.click(timeout=max(1, int((deadline - time.monotonic()) * 1000)))
                except Exception as exc:
                    raise PinterestPublishUncertainError(
                        f"{worker_id}: publish action did not finish; publication remains unverified"
                    ) from exc
                diagnostics.click_completed = True
                return
        await asyncio.sleep(min(0.2, max(0, deadline - time.monotonic())))
    raise PinterestPublishUnavailableError(
        f"{worker_id}: exact Publish control did not become visible and enabled before deadline"
    )


async def _click_publish_once(page, worker_id, diagnostics, timeout_seconds=30.0):
    """Bound actionability checks too, including an unresponsive browser RPC."""
    try:
        async with asyncio.timeout(timeout_seconds):
            await _wait_for_actionable_publish(page, worker_id, diagnostics, timeout_seconds)
    except TimeoutError as exc:
        if diagnostics.click_started:
            raise PinterestPublishUncertainError(
                f"{worker_id}: publish action deadline elapsed; publication remains unverified"
            ) from exc
        raise PinterestPublishUnavailableError(
            f"{worker_id}: exact Publish control did not become visible and enabled before deadline"
        ) from exc
    except PinCreationError:
        raise
    except Exception as exc:
        # A pre-action locator/browser failure cannot establish a click. Keep
        # it on the account-availability path rather than a second publisher.
        raise PinterestPublishUnavailableError(
            f"{worker_id}: publish control actionability could not be established"
        ) from exc


async def _fill_pin_title(page, title, timeout_seconds=15.0):
    """Require a retained title using normal editing and blur events."""
    expected = title[:100]
    if not expected.strip():
        return False
    selectors = (
        "#storyboard-selector-title",
        '[data-test-id="pin-draft-title"] textarea',
        '[data-test-id="pin-draft-title"] input',
        '[data-test-id="pin-draft-title"][contenteditable="true"]',
        '[data-test-id="pin-draft-title"] [contenteditable="true"]',
        'input[placeholder*="title" i]',
        'input[placeholder*="titulo" i]',
        'input[placeholder*="título" i]',
        'textarea[placeholder*="title" i]',
        'textarea[placeholder*="titulo" i]',
        'textarea[placeholder*="título" i]',
    )
    deadline = time.monotonic() + timeout_seconds
    try:
        async with asyncio.timeout(timeout_seconds):
            while time.monotonic() < deadline:
                for selector in selectors:
                    fields = page.locator(selector)
                    for index in range(min(await fields.count(), 5)):
                        field = fields.nth(index)
                        if not await field.is_visible() or not await field.is_enabled():
                            continue
                        try:
                            await field.fill(
                                expected, timeout=max(1, int((deadline - time.monotonic()) * 1000))
                            )
                            await field.press("Tab", timeout=1000)
                            await asyncio.sleep(0.2)
                            try:
                                observed = await field.input_value(timeout=1000)
                            except Exception:
                                observed = await field.inner_text(timeout=1000)
                            return " ".join(observed.split()) == " ".join(expected.split())
                        except Exception:
                            continue
                await asyncio.sleep(0.1)
    except Exception:
        pass
    return False


async def _ensure_immediate_publish(page, timeout_seconds=10.0):
    """Turn off only an identified scheduling control and verify its state."""
    labels = re.compile(
        r"^(?:Publish at a later date|Publish later|Publicar m[aá]s tarde|"
        r"Publicar en una fecha posterior)$",
        re.I,
    )
    try:
        async with asyncio.timeout(timeout_seconds):
            groups = (
                page.locator(
                    '[data-test-id="pin-draft-switch-group"] input[type="checkbox"], '
                    '[data-test-id="pin-draft-switch-group"][role="switch"], '
                    '[data-test-id="pin-draft-switch-group"] [role="switch"]'
                ),
                page.get_by_role("switch", name=labels),
                page.get_by_role("checkbox", name=labels),
            )
            found = False
            for controls in groups:
                found = found or await controls.count() > 0
                for index in range(min(await controls.count(), 5)):
                    control = controls.nth(index)
                    if not await control.is_visible() or not await control.is_enabled():
                        continue
                    native_checkbox = await control.get_attribute("type") == "checkbox"

                    async def checked(control=control, native_checkbox=native_checkbox):
                        if native_checkbox:
                            return await control.is_checked()
                        aria = await control.get_attribute("aria-checked")
                        if aria in ("true", "false"):
                            return aria == "true"
                        return await control.is_checked()

                    if not await checked():
                        return True
                    if native_checkbox:
                        await control.uncheck(timeout=max(1, int(timeout_seconds * 1000)))
                    else:
                        await control.click(timeout=max(1, int(timeout_seconds * 1000)))
                    return not await checked()
            return not found
    except Exception:
        return False


async def _prepare_publish(page, worker_id, timeout_seconds=30.0):
    """Commit the focused field and require stable autosave before Publish."""
    saving = re.compile(r"^(?:Saving(?: changes)?|Guardando(?: cambios)?)[.!\s…]*$", re.I)
    saved = re.compile(
        r"^¡?(?:Changes stored|All changes saved|Changes saved|Cambios guardados|"
        r"Todos los cambios (?:est[aá]n )?guardados)[.!\s]*$",
        re.I,
    )
    labels = re.compile(r"^(?:Publish(?: now)?|Publicar(?: ahora)?)$", re.I)
    deadline = time.monotonic() + timeout_seconds
    stable_since = None

    async def visible_text(pattern):
        matches = page.get_by_text(pattern)
        for index in range(min(await matches.count(), 20)):
            if await matches.nth(index).is_visible():
                return True
        return False

    try:
        async with asyncio.timeout(timeout_seconds):
            # A pointer click blurs its previous field during pointerdown. If
            # that blur starts autosave and disables Publish before pointerup,
            # Playwright can finish the click without firing its handler.
            # Tab commits that field before the sole publication action.
            await page.keyboard.press("Tab")
            while time.monotonic() < deadline:
                actionable = False
                for controls in (
                    page.get_by_role("button", name=labels),
                    page.locator('[data-test-id="storyboard-creation-nav-done"]'),
                ):
                    for index in range(min(await controls.count(), 10)):
                        control = controls.nth(index)
                        text = " ".join((await control.inner_text(timeout=1000)).split())
                        if (
                            labels.fullmatch(text)
                            and await control.is_visible()
                            and await control.is_enabled()
                        ):
                            actionable = True
                            break
                    if actionable:
                        break
                if actionable and not await visible_text(saving) and await visible_text(saved):
                    if stable_since is None:
                        stable_since = time.monotonic()
                    elif time.monotonic() - stable_since >= 0.4:
                        return
                else:
                    stable_since = None
                await asyncio.sleep(0.1)
    except Exception as exc:
        raise PinterestPublishUnavailableError(
            f"{worker_id}: creator autosave readiness could not be established before publish"
        ) from exc
    raise PinterestPublishUnavailableError(
        f"{worker_id}: creator did not show stable saved changes and enabled Publish before deadline"
    )


async def _fill_pin_description(page, description, timeout_seconds=15.0):
    """Fill the current rich-text or textarea editor with normal input events."""
    expected = description[:500]
    if not expected.strip():
        return True
    selectors = (
        '[data-test-id="pin-draft-description"] [contenteditable="true"]',
        '[data-test-id="pin-draft-description"][contenteditable="true"]',
        '.public-DraftEditor-content[contenteditable="true"]',
        '[data-test-id="pin-draft-description"] textarea',
        'textarea[placeholder*="description" i]',
        'textarea[placeholder*="descripcion" i]',
        'textarea[placeholder*="descripción" i]',
    )
    deadline = time.monotonic() + timeout_seconds
    try:
        async with asyncio.timeout(timeout_seconds):
            while time.monotonic() < deadline:
                for selector in selectors:
                    fields = page.locator(selector)
                    for index in range(min(await fields.count(), 5)):
                        field = fields.nth(index)
                        if not await field.is_visible() or not await field.is_enabled():
                            continue
                        await field.fill(expected, timeout=max(1, int((deadline - time.monotonic()) * 1000)))
                        try:
                            observed = await field.input_value(timeout=1000)
                        except Exception:
                            observed = await field.inner_text(timeout=1000)
                        if " ".join(observed.split()) == " ".join(expected.split()):
                            return True
                        # A normal fill that failed readback is never replaced
                        # with direct DOM mutation that bypasses editor state.
                        return False
                await asyncio.sleep(min(0.2, max(0, deadline - time.monotonic())))
    except Exception:
        return False
    return False


async def ensure_creator_draft_capacity_available(page, worker_id):
    """Stop before editor actions when a visible draft-capacity warning remains.

    An ordinary disabled field or an informational draft count alone does not
    establish this account-level blocker. This check never deletes drafts.
    """
    try:
        body_text = await page.locator("body").inner_text(timeout=1500)
    except Exception as exc:
        if is_browser_session_lost(exc):
            raise BrowserSessionLost(str(exc)) from exc
        return
    text = " ".join(body_text.lower().split())
    capacity_warning = any(
        re.search(pattern, text)
        for pattern in (
            r"(?:reached|hit)\s+(?:the\s+)?(?:limit|maximum)\s+(?:of\s+)?\d+\s+(?:pin\s+)?drafts",
            r"(?:reached|hit)\s+(?:your|the)\s+(?:pin\s+)?draft\s+limit",
            r"(?:alcanzado|alcanzaste|alcanzó|llegado)\s+(?:el|al)\s+l[ií]mite\s+(?:de\s+)?\d+\s+borradores",
        )
    )
    if not capacity_warning:
        draft_count = re.search(r"(?:pin drafts|drafts|borradores)\s*\((\d+)\)", text)
        if draft_count and int(draft_count.group(1)) >= 50:
            disabled = page.locator(
                '[data-test-id="creation-form"][aria-disabled="true"], [disabled][data-test-id*="upload"]'
            ).first
            try:
                capacity_warning = await disabled.count() > 0 and await disabled.is_visible(timeout=300)
            except Exception as exc:
                if is_browser_session_lost(exc):
                    raise BrowserSessionLost(str(exc)) from exc
    if capacity_warning:
        raise PinterestDraftCapacityError(
            f"{worker_id}: Pinterest creator draft capacity reached; account upload deferred"
        )


def _truthy(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_session_dir(value) -> Path:
    raw = str(value or "").strip() or "pinterest_rida_v7"
    path = Path(raw)
    if path.is_absolute():
        return path
    if len(path.parts) == 1:
        return project_root / "data" / "sessions" / raw
    return project_root / path


def _safe_worker_id(worker_id):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(worker_id))


def _env_or_value(entry, value_key, env_key, default=""):
    value = entry.get(value_key)
    if value:
        return str(value)
    env_name = entry.get(env_key)
    if env_name:
        return os.environ.get(str(env_name), default)
    return default


def _dedupe_accounts(accounts):
    deduped = []
    seen = set()
    for account in accounts:
        key = str(account.session_dir.resolve()).lower()
        if key in seen:
            logger.warning(f"Skipping duplicate Pinterest session: {account.session_dir}")
            continue
        seen.add(key)
        deduped.append(account)
    return deduped


def load_accounts():
    """Load account/session pool from env, with a backwards-compatible default."""
    default_email = os.environ.get("PINTEREST_EMAIL", "")
    default_password = os.environ.get("PINTEREST_PASSWORD", "")
    default_browser = os.environ.get("PINTEREST_BROWSER", "firefox").strip().lower()

    raw_json = os.environ.get("PINTEREST_ACCOUNTS", "").strip()
    if raw_json:
        try:
            # Robust strip for env vars that might have outer single quotes
            if (raw_json.startswith("'") and raw_json.endswith("'")) or (
                raw_json.startswith('"') and raw_json.endswith('"')
            ):
                raw_json = raw_json[1:-1].strip()

            # Handle potential escaping from some .env parsers/shells
            raw_json = raw_json.replace('\\"', '"')

            payload = json.loads(raw_json)
            accounts = []
            for idx, entry in enumerate(payload, 1):
                session_value = (
                    entry.get("session_dir") or entry.get("session") or entry.get("name") or f"account_{idx}"
                )
                name = str(entry.get("name") or Path(str(session_value)).name or f"account_{idx}")
                # Fallback path logic: explicit browser > mapping for name > mapping for session > default_browser
                session_name = Path(str(session_value)).name
                mapped_browser = DEFAULT_BROWSER_MAP.get(
                    name, DEFAULT_BROWSER_MAP.get(session_name, default_browser)
                )
                accounts.append(
                    PinterestAccount(
                        name=name,
                        session_dir=_resolve_session_dir(session_value),
                        email=_env_or_value(entry, "email", "email_env", default_email),
                        password=_env_or_value(entry, "password", "password_env", default_password),
                        browser=entry.get("browser", mapped_browser),
                    )
                )
            if accounts:
                return _dedupe_accounts(accounts)
        except Exception as exc:
            logger.error(f"Invalid PINTEREST_ACCOUNTS JSON: {exc}")

    # Fallback to data/pinterest_accounts.json if available
    try:
        from pinterest_automation.config import DATA_DIR

        accounts_file_path = os.environ.get("PINTEREST_ACCOUNTS_FILE")
        accounts_file = (
            Path(accounts_file_path) if accounts_file_path else (DATA_DIR / "pinterest_accounts.json")
        )
        if accounts_file.is_file():
            data = json.loads(accounts_file.read_text(encoding="utf-8"))
            acc_list = data.get("accounts")
            if isinstance(acc_list, dict):
                acc_list = list(acc_list.values())
            if isinstance(acc_list, list) and acc_list:
                accounts = []
                for idx, entry in enumerate(acc_list, 1):
                    if not isinstance(entry, dict):
                        continue
                    session_value = (
                        entry.get("session_dir")
                        or entry.get("session_name")
                        or entry.get("session")
                        or entry.get("handle")
                        or entry.get("name")
                        or f"account_{idx}"
                    )
                    name = str(
                        entry.get("handle")
                        or entry.get("name")
                        or Path(str(session_value)).name
                        or f"account_{idx}"
                    )
                    session_name = Path(str(session_value)).name
                    mapped_browser = DEFAULT_BROWSER_MAP.get(
                        name, DEFAULT_BROWSER_MAP.get(session_name, default_browser)
                    )
                    accounts.append(
                        PinterestAccount(
                            name=name,
                            session_dir=_resolve_session_dir(session_value),
                            email=_env_or_value(entry, "email", "email_env", default_email),
                            password=_env_or_value(entry, "password", "password_env", default_password),
                            browser=entry.get("browser", mapped_browser),
                        )
                    )
                if accounts:
                    return _dedupe_accounts(accounts)
    except Exception as exc:
        logger.warning(f"Failed loading accounts from file: {exc}")

    accounts = []
    for idx in range(1, 21):
        prefix = f"PINTEREST_ACCOUNT_{idx}_"
        if not any(
            os.environ.get(prefix + key)
            for key in ("SESSION", "SESSION_DIR", "NAME", "EMAIL", "PASSWORD", "BROWSER")
        ):
            continue
        session_value = (
            os.environ.get(prefix + "SESSION_DIR")
            or os.environ.get(prefix + "SESSION")
            or os.environ.get(prefix + "NAME")
            or f"account_{idx}"
        )
        session_name = Path(session_value).name
        mapped_browser = DEFAULT_BROWSER_MAP.get(session_name, default_browser)
        accounts.append(
            PinterestAccount(
                name=os.environ.get(prefix + "NAME") or session_name,
                session_dir=_resolve_session_dir(session_value),
                email=os.environ.get(prefix + "EMAIL", default_email),
                password=os.environ.get(prefix + "PASSWORD", default_password),
                browser=os.environ.get(prefix + "BROWSER", mapped_browser),
            )
        )
    if accounts:
        return _dedupe_accounts(accounts)

    configured_pool = os.environ.get("PINTEREST_SESSION_POOL", "")
    session_names = [part.strip() for part in configured_pool.split(",") if part.strip()] or list(
        DEFAULT_SESSION_POOL
    )
    return _dedupe_accounts(
        [
            PinterestAccount(
                name=Path(session_name).name,
                session_dir=_resolve_session_dir(session_name),
                email=default_email,
                password=default_password,
                browser=DEFAULT_BROWSER_MAP.get(Path(session_name).name, default_browser),
            )
            for session_name in session_names
        ]
    )


def _ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def browser_pids_for_session(session_dir: Path, browser_type: str = "firefox"):
    target = str(session_dir.resolve())
    proc_name = "chrome.exe" if browser_type == "chromium" else "firefox.exe"
    script = (
        f"Get-CimInstance Win32_Process -Filter \"Name='{proc_name}'\" | "
        "Where-Object { $_.CommandLine } | "
        'ForEach-Object { "$($_.ProcessId)`t$($_.CommandLine)" }'
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            timeout=8,
        )
        target_lower = target.lower()
        pids = []
        if browser_type == "chromium":
            quoted = f'--user-data-dir="{target_lower}"'
            bare = f"--user-data-dir={target_lower}"
        else:
            quoted = f'-profile "{target_lower}"'
            bare = f"-profile {target_lower}"

        for line in (result.stdout or "").splitlines():
            if "\t" not in line:
                continue
            pid_text, command = line.split("\t", 1)
            command_lower = command.lower()
            if (
                quoted in command_lower
                or bare in command_lower
                or (browser_type == "chromium" and target_lower in command_lower)
            ):
                pids.append(int(pid_text.strip()))
        return pids
    except Exception:
        return []


def kill_browser_for_session(session_dir: Path, browser_type: str = "firefox"):
    actions = []
    pids = browser_pids_for_session(session_dir, browser_type)
    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            actions.append(f"killed {browser_type} pid {pid}")
        except Exception as exc:
            actions.append(f"could not kill {browser_type} pid {pid}: {exc}")

    deadline = time.time() + 6.0
    while time.time() < deadline:
        if not browser_pids_for_session(session_dir, browser_type):
            break
        time.sleep(0.4)
    return actions


def firefox_pids_for_session(session_dir: Path):
    return browser_pids_for_session(session_dir, "firefox")


def kill_firefox_for_session(session_dir: Path):
    return kill_browser_for_session(session_dir, "firefox")


def cleanup_session_artifacts(session_dir: Path, browser_type: str = "firefox"):
    session_dir.mkdir(parents=True, exist_ok=True)
    if browser_pids_for_session(session_dir, browser_type):
        return [f"session still in use, skipped cleanup: {session_dir.name}"]

    actions = []
    for lock_name in SESSION_LOCK_FILES:
        lock_path = session_dir / lock_name
        if lock_path.exists():
            try:
                lock_path.unlink()
                actions.append(f"removed {lock_name}")
            except Exception as exc:
                actions.append(f"could not remove {lock_name}: {exc}")

    for pattern in SESSION_STALE_GLOBS:
        for stale in session_dir.rglob(pattern):
            if not stale.is_file():
                continue
            try:
                stale.unlink()
                actions.append(f"removed {stale.relative_to(session_dir)}")
            except Exception:
                pass
    return actions


def _session_has_profile_data(session_dir: Path):
    return session_dir.exists() and any(session_dir.iterdir())


def clone_session_if_needed(account: PinterestAccount, source_dir: Path, clone_missing=True):
    target = account.session_dir
    if _session_has_profile_data(target):
        return cleanup_session_artifacts(target, account.browser)

    target.mkdir(parents=True, exist_ok=True)
    if account.browser == "chromium":
        logger.info(f"{account.name}: starting fresh Chromium session (skipping Firefox cloning)")
        return cleanup_session_artifacts(target, "chromium")

    if not clone_missing or target.resolve() == source_dir.resolve() or not source_dir.exists():
        return cleanup_session_artifacts(target, account.browser)

    if browser_pids_for_session(source_dir, "firefox"):
        logger.warning(f"{account.name}: primary profile is in use; created empty session instead of cloning")
        return cleanup_session_artifacts(target, account.browser)

    try:
        shutil.copytree(
            source_dir,
            target,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(*SESSION_CLONE_IGNORE),
        )
        actions = [f"cloned {source_dir.name} -> {target.name}"]
        actions.extend(cleanup_session_artifacts(target, account.browser))
        return actions
    except Exception as exc:
        logger.warning(f"{account.name}: session clone failed ({exc}); using empty session")
        return cleanup_session_artifacts(target, account.browser)


def ensure_account_sessions(accounts, clone_missing=True):
    source_dir = _resolve_session_dir(os.environ.get("PINTEREST_PRIMARY_SESSION", "pinterest_rida_v7"))
    for account in accounts:
        actions = clone_session_if_needed(account, source_dir, clone_missing=clone_missing)
        if actions:
            logger.info(f"{account.name}: session prep - " + "; ".join(actions[:6]))


def filter_available_accounts(accounts):
    available = []
    for account in accounts:
        pids = browser_pids_for_session(account.session_dir, account.browser)
        if pids:
            logger.warning(
                f"Skipping active Pinterest session {account.name}; owned by {account.browser} pid(s) {pids}"
            )
            continue
        available.append(account)
    return available


def normalize_seo(text):
    if not text:
        return ""

    text = "".join(c for c in unicodedata.normalize("NFD", str(text)) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9\s]", "", text.lower()).strip()


def get_exif_title(image_path):
    try:
        exif_dict = piexif.load(str(image_path))
        if piexif.ImageIFD.XPTitle in exif_dict.get("0th", {}):
            title_tuple = exif_dict["0th"][piexif.ImageIFD.XPTitle]
            return bytes(title_tuple).decode("utf-16le").rstrip("\x00")
    except Exception:
        pass
    return ""


def is_browser_session_lost(error):
    message = str(error).lower()
    return any(marker in message for marker in BROWSER_DEAD_MARKERS)


def page_is_alive(page):
    if page is None:
        return False
    try:
        return not page.is_closed()
    except Exception as exc:
        if is_browser_session_lost(exc):
            raise BrowserSessionLost(str(exc)) from exc
        return False


async def close_turbo_browser(pw, context):
    if context:
        try:
            await context.close()
        except Exception:
            pass
    if pw:
        try:
            await pw.stop()
        except Exception:
            pass


async def pinterest_session_valid(page):
    try:
        await page.goto("https://www.pinterest.com/", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(4)
        profile = await page.query_selector(
            '[data-test-id="header-profile"], [data-test-id="header-avatar"], [data-test-id="user-avatar"]'
        )
        if profile:
            return True

        await page.goto(
            "https://www.pinterest.com/pin-creation-tool/", wait_until="domcontentloaded", timeout=60000
        )
        await asyncio.sleep(4)
        if "pin-creation-tool" not in page.url:
            return False
        return await page.query_selector('input[type="file"]') is not None
    except Exception as exc:
        if is_browser_session_lost(exc):
            raise BrowserSessionLost(str(exc)) from exc
        return False


async def ensure_account_logged_in(page, account: PinterestAccount):
    if await pinterest_session_valid(page):
        logger.info(f"{account.name}: session valid")
        return True
    if not account.email or not account.password:
        logger.error(f"{account.name}: logged out and no credentials configured")
        return False
    return await ensure_logged_in(page, account.email, account.password)


async def force_text_value(element, text):
    try:
        value = await element.evaluate(
            """(el, value) => {
                el.scrollIntoView({block: 'center', inline: 'center'});
                el.focus();
                const proto = Object.getPrototypeOf(el);
                const descriptor =
                    Object.getOwnPropertyDescriptor(proto, 'value') ||
                    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value') ||
                    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');
                if (descriptor && descriptor.set) {
                    descriptor.set.call(el, value);
                } else {
                    el.innerText = value;
                    el.textContent = value;
                }
                el.dispatchEvent(new InputEvent('input', {bubbles: true, data: value, inputType: 'insertText'}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                return el.value || el.innerText || el.textContent || '';
            }""",
            text,
        )
        await asyncio.sleep(0.5)
        return text[:20] in (value or "")
    except Exception:
        return False


async def fill_destination_link(page, url, worker_id):
    link_selectors = [
        "#WebsiteField",
        'input[id="pin-draft-link"]',
        'input[name="link"]',
        'input[placeholder*="link" i]',
        'input[placeholder*="enlace" i]',
        'textarea[placeholder*="link" i]',
        'textarea[placeholder*="enlace" i]',
        '[contenteditable="true"][aria-label*="link" i]',
        '[contenteditable="true"][aria-label*="enlace" i]',
    ]

    async def force_value(element):
        try:
            value = await element.evaluate(
                """(el, value) => {
                    el.scrollIntoView({block: 'center', inline: 'center'});
                    el.focus();
                    const proto = Object.getPrototypeOf(el);
                    const descriptor =
                        Object.getOwnPropertyDescriptor(proto, 'value') ||
                        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value') ||
                        Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');
                    if (descriptor && descriptor.set) {
                        descriptor.set.call(el, value);
                    } else {
                        el.value = value;
                        el.textContent = value;
                    }
                    el.dispatchEvent(new InputEvent('input', {bubbles: true, data: value, inputType: 'insertText'}));
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                    return el.value || el.innerText || el.textContent || '';
                }""",
                url,
            )
            await asyncio.sleep(0.5)
            return url in (value or "")
        except Exception as exc:
            if is_browser_session_lost(exc):
                raise BrowserSessionLost(str(exc)) from exc
            return False

    for selector in link_selectors:
        try:
            element = await page.wait_for_selector(selector, timeout=2500, state="attached")
            if not element:
                continue
            if await force_value(element):
                return True
            await element.scroll_into_view_if_needed()
            await element.click(force=True)
            try:
                await element.fill(url)
            except Exception as exc:
                if is_browser_session_lost(exc):
                    raise BrowserSessionLost(str(exc)) from exc
                await page.keyboard.down("Control")
                await page.keyboard.press("A")
                await page.keyboard.up("Control")
                await page.keyboard.type(url)
            value = ""
            try:
                value = await element.input_value()
            except Exception as exc:
                if is_browser_session_lost(exc):
                    raise BrowserSessionLost(str(exc)) from exc
                value = await element.evaluate("(el) => el.innerText || el.textContent || ''")
            if url in value:
                return True
            if await force_value(element):
                return True
        except Exception as exc:
            if is_browser_session_lost(exc):
                raise BrowserSessionLost(str(exc)) from exc
            continue

    for button_text in (
        "Add destination link",
        "Add a destination link",
        "Destination link",
        "Agregar enlace",
        "Añadir enlace",
    ):
        try:
            button = page.get_by_text(button_text, exact=False).first
            if await button.count():
                await button.click(force=True)
                await asyncio.sleep(1)
                for selector in link_selectors:
                    try:
                        element = await page.wait_for_selector(selector, timeout=2500, state="attached")
                        if element:
                            if await force_value(element):
                                return True
                            try:
                                await element.fill(url)
                                value = await element.input_value()
                            except Exception as exc:
                                if is_browser_session_lost(exc):
                                    raise BrowserSessionLost(str(exc)) from exc
                                value = ""
                            if url in value:
                                return True
                    except Exception as exc:
                        if is_browser_session_lost(exc):
                            raise BrowserSessionLost(str(exc)) from exc
                        continue
        except Exception as exc:
            if is_browser_session_lost(exc):
                raise BrowserSessionLost(str(exc)) from exc
            continue

    try:
        inputs = await page.evaluate(
            """() => Array.from(document.querySelectorAll('input, textarea, [contenteditable="true"]')).map((el) => {
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return {
                    tag: el.tagName,
                    type: el.getAttribute('type') || '',
                    id: el.id || '',
                    name: el.getAttribute('name') || '',
                    placeholder: el.getAttribute('placeholder') || '',
                    aria: el.getAttribute('aria-label') || '',
                    value: (el.value || el.innerText || el.textContent || '').slice(0, 120),
                    visible: !!(r.width && r.height) && style.visibility !== 'hidden' && style.display !== 'none',
                    box: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]
                };
            }).filter((x) => x.visible || /link|enlace|website|url|title|description|descripcion/i.test(JSON.stringify(x))).slice(0, 40)"""
        )
        logger.error(f"{worker_id}: link diagnostics: {json.dumps(inputs, ensure_ascii=False)}")
        await page.screenshot(
            path=str(project_root / "data" / f"link_not_filled_{_safe_worker_id(worker_id)}.png"),
            full_page=True,
        )
    except Exception as exc:
        if is_browser_session_lost(exc):
            raise BrowserSessionLost(str(exc)) from exc
        logger.error(f"{worker_id}: link diagnostics failed: {exc}")
    logger.error(f"{worker_id}: link field not filled; aborting publish")
    return False


async def link_guard_ok(page, url):
    selectors = [
        "#WebsiteField",
        'input[id="pin-draft-link"]',
        'input[name="link"]',
        'input[placeholder*="link" i]',
        'input[placeholder*="enlace" i]',
        'textarea[placeholder*="link" i]',
        'textarea[placeholder*="enlace" i]',
        '[contenteditable="true"][aria-label*="link" i]',
        '[contenteditable="true"][aria-label*="enlace" i]',
    ]
    for selector in selectors:
        try:
            element = await page.query_selector(selector)
            if not element:
                continue
            try:
                value = await element.input_value()
            except Exception as exc:
                if is_browser_session_lost(exc):
                    raise BrowserSessionLost(str(exc)) from exc
                value = await element.evaluate("(el) => el.innerText || el.textContent || ''")
            if url in value:
                return True
        except Exception as exc:
            if is_browser_session_lost(exc):
                raise BrowserSessionLost(str(exc)) from exc
            pass
    return False


async def wait_for_pinterest_save(page, timeout_seconds=45):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            saving = page.get_by_text(re.compile(r"Saving|Guardando", re.I)).first
            if not await saving.is_visible(timeout=800):
                return True
        except Exception:
            return True
        await asyncio.sleep(1)
    return False


async def is_disabled(element):
    try:
        return await element.evaluate(
            """(el) => {
                const ariaDisabled = el.getAttribute('aria-disabled') === 'true';
                const disabledAncestor = el.closest('[aria-disabled="true"], [disabled]');
                return !!el.disabled || ariaDisabled || !!disabledAncestor;
            }"""
        )
    except Exception:
        return False


async def wait_for_upload_ready(page, worker_id, timeout_seconds=120):
    """Wait until Pinterest has accepted the media and unlocked the editor."""
    deadline = time.time() + timeout_seconds
    last_state = {}

    title_selectors = [
        "#storyboard-selector-title",
        '[data-test-id="pin-draft-title"] textarea',
        'input[placeholder*="title" i]',
        'input[placeholder*="titulo" i]',
        'textarea[placeholder*="title" i]',
        'textarea[placeholder*="titulo" i]',
        'div[contenteditable="true"]',
    ]

    board_selectors = [
        '[data-test-id="board-dropdown-select-button"]',
        '[aria-label*="Select board" i]',
        '[aria-label*="Choose a board" i]',
        'button:has-text("Choose a board")',
        'button:has-text("Selecciona un tablero")',
    ]

    while time.time() < deadline:
        # Pinterest may reveal its account-capacity warning only after media
        # upload. Keep this outside the tolerant DOM-read block so the typed
        # deferral (or a lost browser session) reaches the caller immediately.
        await ensure_creator_draft_capacity_available(page, worker_id)
        try:
            title = None
            for sel in title_selectors:
                title = await page.query_selector(sel)
                if title:
                    break

            board = None
            for sel in board_selectors:
                board = await page.query_selector(sel)
                if board:
                    break

            upload_error = page.get_by_text(
                re.compile(r"reached the limit|límite|limite|failed|error", re.I)
            ).first
            error_visible = False
            try:
                error_visible = await upload_error.is_visible(timeout=500)
            except Exception:
                error_visible = False

            last_state = {
                "title_present": bool(title),
                "board_present": bool(board),
                "upload_error_visible": error_visible,
            }
            if title and not error_visible:
                return True

        except Exception as exc:
            if is_browser_session_lost(exc):
                raise BrowserSessionLost(str(exc)) from exc
            last_state = {"error": str(exc)}
        await asyncio.sleep(2)

    logger.error(f"{worker_id}: upload editor did not unlock: {json.dumps(last_state, ensure_ascii=False)}")
    try:
        await page.screenshot(
            path=str(project_root / "data" / f"upload_not_ready_{_safe_worker_id(worker_id)}.png"),
            full_page=True,
        )
    except Exception:
        pass
    return False


async def _submit_board_creation(dialog, board_name):
    """Fill the visible modal's name field and require a completed form submission."""
    candidates = [
        dialog.get_by_label(re.compile(r"^(Name|Nombre)$", re.I)).first,
        dialog.get_by_role("textbox").first,
    ]
    candidates.extend(
        dialog.locator(selector).first
        for selector in (
            "#boardEditName",
            'input[name="name"]',
            'input[placeholder*="Name" i]',
            'input[placeholder*="Nombre" i]',
            'input[type="text"]',
        )
    )
    filled = False
    for candidate in candidates:
        if await candidate.count() and await candidate.is_visible() and await candidate.is_enabled():
            await candidate.fill(board_name, timeout=3000)
            if (await candidate.input_value()).strip() == board_name:
                filled = True
                break
    if not filled:
        return False
    submissions = [dialog.get_by_role("button", name=re.compile(r"^(Create|Crear)$", re.I)).first]
    submissions.extend(
        dialog.locator(selector).first
        for selector in ('[data-test-id="board-form-submit-button"]', 'button[type="submit"]')
    )
    for submit in submissions:
        if await submit.count() and await submit.is_visible() and await submit.is_enabled():
            await submit.click(timeout=3000)
            try:
                await dialog.wait_for(state="hidden", timeout=10000)
            except Exception:
                return False
            return True
    return False


async def _board_label_matches(locator, board_name):
    """Match the board label itself, excluding row counts and similar names."""
    exact = locator.get_by_text(board_name, exact=True)
    for index in range(await exact.count()):
        if await exact.nth(index).is_visible():
            return True
    target = normalize_seo(board_name)
    text = await locator.inner_text(timeout=2000)
    return any(normalize_seo(line) == target for line in text.splitlines())


async def _board_selection_matches(page, dropdown_selector, board_name):
    # Selecting a board can replace its dropdown node. Reacquire the live field
    # instead of trusting the ElementHandle used to open the old picker.
    fields = page.locator(dropdown_selector)
    for index in range(await fields.count()):
        field = fields.nth(index)
        if await field.is_visible() and await _board_label_matches(field, board_name):
            return True
    return False


async def _board_select_existing(page, dropdown_selector, board_name, worker_id):
    """Return selection proof and whether a concrete matching board was found."""
    rows = page.locator(
        '[data-test-id="boardWithoutSection"], '
        '[data-test-id="boardWithSection"], '
        '[data-test-id="board-picker-flyout"] [role="listitem"], [role="option"]'
    )
    found = False
    for index in range(await rows.count()):
        row = rows.nth(index)
        try:
            if not await row.is_visible() or not await _board_label_matches(row, board_name):
                continue
            found = True
            label = row.get_by_text(board_name, exact=True).first
            clickable = label if await label.count() and await label.is_visible() else row
            await clickable.click(timeout=3000)
            for _ in range(5):
                if await _board_selection_matches(page, dropdown_selector, board_name):
                    return True, True
                await asyncio.sleep(0.2)
            logger.warning(f"[{worker_id}] Existing board click did not select {board_name}")
        except Exception as exc:
            if is_browser_session_lost(exc):
                raise BrowserSessionLost(str(exc)) from exc
            logger.debug(f"[{worker_id}] Existing board candidate failed: {exc}")
    return False, found


async def _board_creation_duplicate(dialog):
    warning = dialog.get_by_text(
        re.compile(
            r"already have a board with this name|board.*already exists|"
            r"ya tienes un tablero.*nombre|ya existe.*tablero",
            re.I,
        )
    )
    return any([await warning.nth(index).is_visible() for index in range(await warning.count())])


async def _board_cancel_creation(dialog):
    cancel = dialog.get_by_role("button", name=re.compile(r"^(Cancel|Cancelar)$", re.I)).first
    if await cancel.count() and await cancel.is_visible() and await cancel.is_enabled():
        await cancel.click(timeout=3000)
        await dialog.wait_for(state="hidden", timeout=3000)
        return True
    return False


async def select_board(page, board_name, worker_id):
    """
    Select the configured live board, falling back only when Pinterest does not expose it.
    """
    if not circuit.can_execute(f"board_selection:{worker_id}"):
        logger.warning(f"{worker_id}: circuit for board selection is OPEN; skipping interaction")
        return False

    try:
        account_handle = str(worker_id).removeprefix("driver-")
        board_name = resolve_account_board_name(board_name, account_handle)
        logger.info(f"[{worker_id}] Selecting configured board: {board_name}")

        # 1. Open dropdown
        dropdown_selectors = [
            '[data-test-id="board-dropdown-select-button"]',
            '[data-test-id="board-selection-button"]',
            '[data-test-id="PinBetterSaveCanvas"] button',
            '[data-test-id="PinBetterSaveDropdown"]',
            '[data-test-id="save-to-board-button"]',
            'button[aria-label*="board" i]',
            'button[aria-label*="tablero" i]',
            'div[role="button"][aria-label*="board" i]',
            'div[role="button"][aria-label*="tablero" i]',
            'button:has-text("Save to")',
            'button:has-text("Guardar en")',
            '[aria-label*="Choose a board" i]',
            '[aria-label*="Select board" i]',
            'div[role="button"]:has-text("Choose a board")',
            'div[role="button"]:has-text("Selecciona un tablero")',
            'button:has-text("Choose a board")',
            'button:has-text("Selecciona un tablero")',
        ]

        board_btn = None
        dropdown_selector = None
        for sel in dropdown_selectors:
            try:
                loc = await page.query_selector(sel)
                if loc and await loc.is_visible():
                    board_btn = loc
                    dropdown_selector = sel
                    break
            except:
                continue

        if not board_btn:
            logger.warning(f"[{worker_id}] Board dropdown button not found or not visible")
            return False

        if await _board_selection_matches(page, dropdown_selector, board_name):
            circuit.record_success(f"board_selection:{worker_id}")
            return True

        logger.info(f"[{worker_id}] Clicking board dropdown...")
        await board_btn.click(force=True)
        await asyncio.sleep(2)

        # 2. Search first because Pinterest virtualizes long board lists.
        try:
            search = None
            search_selectors = [
                '[data-test-id="board-picker-flyout"] input:not([disabled])',
                '[role="dialog"] input:not([disabled]):not([id*="tag" i]):not([id*="interest" i])',
                '[role="listbox"] input:not([disabled])',
                'input[placeholder*="Search" i]:not([disabled]):not([id*="tag" i]):not([id*="interest" i])',
                'input[placeholder*="Buscar" i]:not([disabled]):not([id*="tag" i]):not([id*="interest" i])',
            ]
            for sel in search_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible() and await el.is_enabled():
                        search = el
                        break
                except Exception:
                    continue
            if search:
                await search.fill(board_name, timeout=3000)
                await asyncio.sleep(1.5)
        except Exception as exc:
            if is_browser_session_lost(exc):
                raise BrowserSessionLost(str(exc)) from exc
            logger.warning(f"[{worker_id}] Board search failed for {board_name}: {exc}")

        # 3. Board rows may include counts/visibility metadata and omit a role.
        selected, existing_found = await _board_select_existing(
            page, dropdown_selector, board_name, worker_id
        )
        if selected:
            logger.info(f"[{worker_id}] Selected and verified configured board: {board_name}")
            circuit.record_success(f"board_selection:{worker_id}")
            return True
        if existing_found:
            logger.warning(
                f"[{worker_id}] Existing board {board_name} could not be selected; skipping creation"
            )
            circuit.record_failure(f"board_selection:{worker_id}")
            return False

        # 4. Fallback: Automatically create the missing board if not found in account
        logger.info(
            f"[{worker_id}] Board '{board_name}' not found in account; attempting automatic board creation..."
        )
        create_selectors = [
            '[data-test-id="create-board-button"]',
            '[data-test-id*="create-board"]',
            '[data-test-id="board-picker-create-board-button"]',
            'button:has-text("Create board")',
            'button:has-text("Crear tablero")',
            'div[role="button"]:has-text("Create board")',
            'div[role="button"]:has-text("Crear tablero")',
            '[role="listitem"]:has-text("Create board")',
            '[role="listitem"]:has-text("Crear tablero")',
        ]

        create_btn = None
        for csel in create_selectors:
            loc = page.locator(csel).first
            if await loc.count() > 0:
                create_btn = loc
                break

        # If not found with active search query, clear the search box to reveal bottom create button
        if not create_btn and search:
            try:
                await search.fill("")
                await asyncio.sleep(1)
                # Scroll flyout container to bottom
                flyout_scroll = page.locator('[data-test-id="board-picker-flyout"], [role="listbox"]').first
                if await flyout_scroll.count() > 0:
                    await flyout_scroll.evaluate("el => el.scrollTop = el.scrollHeight")
                    await asyncio.sleep(0.5)
                for csel in create_selectors:
                    loc = page.locator(csel).first
                    if await loc.count() > 0:
                        create_btn = loc
                        break
            except Exception as e:
                logger.debug(f"[{worker_id}] Search clear/scroll fallback: {e}")

        if create_btn and await create_btn.count() > 0:
            try:
                await create_btn.scroll_into_view_if_needed()
            except Exception:
                pass
            await create_btn.click(force=True)
            await asyncio.sleep(2)

            dialog_selectors = [
                '[role="dialog"]:has(#boardEditName)',
                '[role="dialog"][aria-label*="Board" i]',
                '[role="dialog"][aria-label*="Tablero" i]',
                '[role="dialog"]',
            ]
            dialog = None
            for dsel in dialog_selectors:
                dloc = page.locator(dsel).first
                if await dloc.count() > 0 and await dloc.is_visible():
                    dialog = dloc
                    break

            created = bool(dialog) and await _submit_board_creation(dialog, board_name)
            if created:
                if await _board_selection_matches(page, dropdown_selector, board_name):
                    logger.info(
                        f"[{worker_id}] Successfully created and selected missing board: {board_name}"
                    )
                    circuit.record_success(f"board_selection:{worker_id}")
                    return True

                # If board created but not auto-selected, re-open dropdown and click it
                logger.info(f"[{worker_id}] Board created; re-verifying selection for '{board_name}'...")
                await page.locator(dropdown_selector).first.click(timeout=3000)
                await asyncio.sleep(1.5)
                selected, _ = await _board_select_existing(page, dropdown_selector, board_name, worker_id)
                if selected:
                    logger.info(f"[{worker_id}] Selected created board '{board_name}' on second pass.")
                    circuit.record_success(f"board_selection:{worker_id}")
                    return True
            elif dialog and await _board_creation_duplicate(dialog):
                logger.warning(f"[{worker_id}] Pinterest confirms {board_name} already exists; selecting it")
                if await _board_cancel_creation(dialog):
                    await page.locator(dropdown_selector).first.click(timeout=3000)
                    await asyncio.sleep(1)
                    selected, _ = await _board_select_existing(page, dropdown_selector, board_name, worker_id)
                    if selected:
                        circuit.record_success(f"board_selection:{worker_id}")
                        return True

        # Diagnostic capture
        try:
            diag_path = f"data/logs/board_selection_failed_{worker_id}_{int(time.time())}.png"
            await page.screenshot(path=diag_path)
            logger.info(f"[{worker_id}] Saved diagnostic screenshot: {diag_path}")
        except Exception:
            pass

        logger.warning(
            f"[{worker_id}] Board selection failed: configured board '{board_name}' could not be verified"
        )
        circuit.record_failure(f"board_selection:{worker_id}")
        return False

    except Exception as e:
        logger.error(f"[{worker_id}] Error in simplified select_board: {e}")
        circuit.record_failure(f"board_selection:{worker_id}")
        return False


async def log_publish_diagnostics(page, worker_id):
    try:
        buttons = await page.evaluate(
            """() => Array.from(document.querySelectorAll('button, [role="button"]')).map((el) => {
                const r = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return {
                    text: (el.innerText || el.textContent || '').trim().slice(0, 80),
                    aria: el.getAttribute('aria-label') || '',
                    testid: el.getAttribute('data-test-id') || '',
                    disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
                    visible: !!(r.width && r.height) && style.visibility !== 'hidden' && style.display !== 'none',
                    box: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]
                };
            }).filter((b) => b.visible || /publish|publicar|board|draft|done|save/i.test(JSON.stringify(b))).slice(0, 30)"""
        )
        logger.error(f"{worker_id}: publish diagnostics: {json.dumps(buttons, ensure_ascii=False)}")
        await page.screenshot(
            path=str(project_root / "data" / f"publish_not_found_{_safe_worker_id(worker_id)}.png"),
            full_page=True,
        )
    except Exception as exc:
        logger.error(f"{worker_id}: publish diagnostics failed: {exc}")


async def dismiss_publish_success_overlays(page):
    """Dismiss only a known extension prompt, preserving every success notice."""
    try:
        notices = page.get_by_text(re.compile(r"published|publicado|guardado", re.I))
        for index in range(min(await notices.count(), 20)):
            if await notices.nth(index).is_visible(timeout=300):
                return
        dialogs = page.locator('[role="dialog"], [aria-modal="true"]')
        for index in range(min(await dialogs.count(), 10)):
            dialog = dialogs.nth(index)
            if not await dialog.is_visible(timeout=300):
                continue
            text = await dialog.inner_text(timeout=1000)
            if re.search(r"published|publicado|guardado", text, re.I):
                return
            if not re.search(r"install the pinterest browser extension|instalar la extensi[oó]n", text, re.I):
                continue
            dismiss = dialog.get_by_role(
                "button",
                name=re.compile(
                    r"^(?:Close|Cerrar|Not now|Ahora no|Maybe later|Quiz[aá]s m[aá]s tarde)$", re.I
                ),
            )
            for button_index in range(min(await dismiss.count(), 10)):
                button = dismiss.nth(button_index)
                if await button.is_visible(timeout=300) and await button.is_enabled():
                    await button.click(timeout=2000)
                    return
    except Exception:
        # An unfamiliar overlay is never removed speculatively. In particular,
        # Escape, page-wide Close buttons, and hidden ancestor divs lose proof.
        return


async def _extract_published_before_dismiss(page, worker_id, *, dismiss=False):
    pin_id = await extract_published_pin_id(page, worker_id)
    if pin_id:
        return pin_id
    if dismiss:
        await dismiss_publish_success_overlays(page)
    return None


async def extract_published_pin_id(page, worker_id, click_view=True):
    """Return the published pin id from current URL, toast links, or the success View button."""
    try:
        match = re.search(r"/pin/(\d+)", page.url)
        if match:
            return match.group(1)

        links = await page.query_selector_all('a[href*="/pin/"]')
        for link in links:
            href = await link.get_attribute("href")
            match = re.search(r"/pin/(\d+)", href or "")
            if match:
                return match.group(1)

        success_msg = page.get_by_text(re.compile(r"published|publicado|guardado", re.I)).first
        success_visible = False
        try:
            success_visible = await success_msg.count() > 0 and await success_msg.is_visible(timeout=500)
        except Exception:
            success_visible = False

        if success_visible and click_view:
            for locator in (
                page.get_by_role("button", name=re.compile(r"^(View|Ver)$", re.I)).first,
                page.get_by_text(re.compile(r"^(View|Ver)$", re.I)).first,
            ):
                try:
                    if await locator.count() > 0 and await locator.is_visible(timeout=700):
                        logger.info(f"[{worker_id}] Published toast visible; opening View to capture pin id")
                        await locator.click(force=True)
                        await page.wait_for_load_state("domcontentloaded", timeout=10000)
                        await asyncio.sleep(2)
                        match = re.search(r"/pin/(\d+)", page.url)
                        if match:
                            return match.group(1)
                        links = await page.query_selector_all('a[href*="/pin/"]')
                        for link in links:
                            href = await link.get_attribute("href")
                            match = re.search(r"/pin/(\d+)", href or "")
                            if match:
                                return match.group(1)
                except Exception as exc:
                    if is_browser_session_lost(exc):
                        raise BrowserSessionLost(str(exc)) from exc
                    continue
    except Exception as exc:
        if is_browser_session_lost(exc):
            raise BrowserSessionLost(str(exc)) from exc
        logger.warning(f"{worker_id}: success pin id extraction failed: {exc}")
    return None


async def turbo_create_pin(
    page,
    post,
    image_path,
    board_name,
    worker_id,
    url_override=None,
    description_override=None,
):
    title = post["title"]
    url = url_override or f"https://recetadolce.com/{post['slug']}"
    desc = description_override if description_override is not None else build_pin_description(post)

    ext = image_path.suffix
    safe_id = _safe_worker_id(worker_id)
    temp_img = (
        project_root / "data" / f"upload_temp_{safe_id}_{os.getpid()}_{random.randint(1000, 9999)}{ext}"
    )
    shutil.copy2(str(image_path), str(temp_img))
    publish_diagnostics = None

    try:
        await page.goto(
            "https://www.pinterest.com/pin-creation-tool/", wait_until="domcontentloaded", timeout=90000
        )
        await asyncio.sleep(5)

        if "pin-creation-tool" not in page.url:
            await page.goto(
                "https://www.pinterest.com/pin-creation-tool/", wait_until="domcontentloaded", timeout=90000
            )
            await asyncio.sleep(5)

        # Defer confirmed account capacity immediately. Ordinary disabled or
        # loading UI should proceed to media readiness, never draft deletion.
        await ensure_creator_draft_capacity_available(page, worker_id)
        file_input = await page.wait_for_selector('input[type="file"]', timeout=45000)
        await file_input.set_input_files(str(temp_img))
        if not await wait_for_upload_ready(page, worker_id):
            await ensure_creator_draft_capacity_available(page, worker_id)
            raise PinCreationError(f"{worker_id}: upload editor did not unlock within timeout")

        await ensure_creator_draft_capacity_available(page, worker_id)
        if not await _fill_pin_title(page, title):
            raise PinterestPublishUnavailableError(
                f"{worker_id}: title editor did not accept and retain the required text"
            )

        if not await _fill_pin_description(page, desc):
            raise PinterestPublishUnavailableError(
                f"{worker_id}: description editor did not accept and retain the supplied text"
            )

        if not await fill_destination_link(page, url, worker_id):
            raise PinCreationError(f"{worker_id}: destination link field not filled for {url}")

        await asyncio.sleep(2)

        # --- Aggressive Board Selection ---
        await ensure_creator_draft_capacity_available(page, worker_id)
        if not await select_board(page, board_name, worker_id):
            raise PinCreationError(f"{worker_id}: configured board selection failed for {board_name}")

        await asyncio.sleep(3)  # Ensure board selection is registered

        if not await _ensure_immediate_publish(page):
            raise PinterestPublishUnavailableError(
                f"{worker_id}: immediate publication could not be verified from the scheduling control"
            )

        if not await link_guard_ok(page, url):
            if not await fill_destination_link(page, url, worker_id) or not await link_guard_ok(page, url):
                raise PinterestPublishUnavailableError(
                    f"{worker_id}: destination editor did not retain the required link"
                )

        # --- Aggressive Publish ---
        await ensure_creator_draft_capacity_available(page, worker_id)
        logger.info(f"[{worker_id}] Finalizing publish: strictly real publication...")

        # 1. Reveal UI
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1)
        await _prepare_publish(page, worker_id)

        # Normal Playwright actionability checks wait for autosave/rendering.
        # A forced click could silently target a disabled Publish button.
        publish_diagnostics = _PublishNetworkDiagnostics(page)
        await _click_publish_once(page, worker_id, publish_diagnostics)
        await asyncio.sleep(5)

        # 5. Extraction loop
        for loop_idx in range(75):
            await asyncio.sleep(1)
            pin_id = await _extract_published_before_dismiss(page, worker_id, dismiss=loop_idx % 5 == 0)
            if pin_id:
                return pin_id

            # B. Check for SPA success markers (The "Your Pin has been published!" toast)
            try:
                # Look for "Your Pin has been published!" or "View" button
                success_msg = page.get_by_text(re.compile(r"published|publicado", re.I)).first

                if await success_msg.count() > 0 and await success_msg.is_visible(timeout=500):
                    logger.info(f"[{worker_id}] SPA Success marker found: 'Published'")
                    pin_id = await extract_published_pin_id(page, worker_id)
                    if pin_id:
                        return pin_id
                    logger.info(f"[{worker_id}] Success message seen, but no Pin ID link yet...")
            except:
                pass

            # C. Check for generic view link
            view_pin = await page.query_selector('a[href*="/pin/"]')
            if view_pin:
                href = await view_pin.get_attribute("href")
                match = re.search(r"/pin/(\d+)", href or "")
                if match:
                    return match.group(1)

            # D. Check for success toast specifically
            try:
                toast = await page.query_selector('[role="alert"], .Toastify__toast-body')
                if toast:
                    text = (await toast.inner_text()).lower()
                    if "saved to" in text or "guardado" in text:
                        if "draft" in text or "borrador" in text:
                            logger.warning(
                                f"[{worker_id}] Pin remains a draft; preserving the single publish attempt"
                            )
                        else:
                            # It was saved to a board! Try to find the link.
                            view_link = await toast.query_selector('a[href*="/pin/"]')
                            if view_link:
                                href = await view_link.get_attribute("href")
                                match = re.search(r"/pin/(\d+)", href or "")
                                if match:
                                    return match.group(1)
            except:
                pass

        # If we reach here, check URL one last time
        pin_id = await extract_published_pin_id(page, worker_id)
        if pin_id:
            return pin_id

        # Save diagnostic screenshot and state on timeout
        try:
            shot_file = LOG_DIR / f"pin_timeout_{worker_id}_{int(time.time())}.png"
            await page.screenshot(path=str(shot_file))
            logger.warning(f"[{worker_id}] Timeout screenshot saved to {shot_file}. Page URL: {page.url}")
        except Exception as shot_err:
            logger.warning(f"[{worker_id}] Could not save timeout screenshot: {shot_err}")

        raise PinterestPublishUncertainError(
            f"{worker_id}: publish clicked but no Pin ID found within 75s timeout"
        )

    except BrowserSessionLost:
        raise
    except PinCreationError as exc:
        if publish_diagnostics is not None:
            await publish_diagnostics.close()
            exc.publish_diagnostics = publish_diagnostics.summary()
            logger.warning(
                "[%s] Publish network diagnostics: %s", worker_id, json.dumps(exc.publish_diagnostics)
            )
        raise
    except Exception as exc:
        logger.error(f"{worker_id}: create pin error: {exc}")
        if is_browser_session_lost(exc):
            raise BrowserSessionLost(str(exc)) from exc
        error_type = (
            PinterestPublishUncertainError
            if publish_diagnostics is not None and publish_diagnostics.click_started
            else PinCreationError
        )
        error = error_type(f"{worker_id}: unexpected error during pin creation: {exc}")
        if publish_diagnostics is not None:
            await publish_diagnostics.close()
            error.publish_diagnostics = publish_diagnostics.summary()
        raise error from exc
    finally:
        if publish_diagnostics is not None:
            await publish_diagnostics.close()
        try:
            if temp_img.exists():
                temp_img.unlink()
        except Exception:
            pass
    return None


async def create_pin_from_fields(
    page,
    image_path,
    title,
    link,
    description,
    board_name,
    worker_id="pinterest-upload",
):
    """Compatibility helper for legacy uploaders that already built metadata."""
    slug_source = link.rstrip("/").split("/")[-1] if link else title
    slug = re.sub(r"[^a-z0-9]+", "-", slug_source.lower()).strip("-") or "pin"
    post = {"title": title, "slug": slug, "excerpt": description}
    return await turbo_create_pin(
        page,
        post,
        Path(image_path),
        board_name,
        worker_id,
        url_override=link,
        description_override=description,
    )


class PinManager:
    def __init__(self, sb):
        self.sb = sb
        self.uploaded = set()
        if UPLOADED_TRACKER.exists():
            self.uploaded = set(
                line.strip() for line in UPLOADED_TRACKER.read_text(encoding="utf-8").splitlines()
            )
        self.lock = asyncio.Lock()

    def is_uploaded(self, filename):
        return filename in self.uploaded

    async def mark_completed(self, filename, post, pin_id):
        # Strict validation: Only consider completed and safe to delete if pin_id is verified
        clean_pin_id = str(pin_id or "").strip()
        if not clean_pin_id or not re.match(r"^\d{15,22}$", clean_pin_id):
            logger.warning(
                f"Refusing to delete image {filename}: pin_id '{pin_id}' is not verified as a valid Pinterest pin"
            )
            return

        async with self.lock:
            if filename in self.uploaded:
                return
            self.uploaded.add(filename)
            with open(UPLOADED_TRACKER, "a", encoding="utf-8") as tracker:
                tracker.write(filename + "\n")
            try:
                update_pin_id(self.sb, post["id"], clean_pin_id)
            except Exception as exc:
                logger.error(f"Supabase pin update failed for {filename}: {exc}")
            path = MEDIA_DIR / filename
            if path.exists():
                try:
                    path.unlink()
                    logger.info(f"Deleted verified uploaded image: {filename}")
                except Exception as exc:
                    logger.error(f"Delete failed for {filename}: {exc}")


async def create_turbo_browser(account: PinterestAccount, name, headless=True):
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth

    last_error = None
    for attempt in range(1, MAX_BROWSER_LAUNCH_ATTEMPTS + 1):
        actions = cleanup_session_artifacts(account.session_dir, account.browser)
        if actions:
            logger.info(f"{name}: profile cleanup - " + "; ".join(actions[:5]))

        pw = await async_playwright().start()
        try:
            if account.browser == "chromium":
                context = await pw.chromium.launch_persistent_context(
                    user_data_dir=str(account.session_dir),
                    headless=True,
                    viewport={"width": 1440, "height": 900},
                    args=["--allow-downgrade", "--no-sandbox", "--disable-setuid-sandbox"],
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                    timeout=120000,
                )
            else:
                context = await pw.firefox.launch_persistent_context(
                    user_data_dir=str(account.session_dir),
                    headless=True,
                    viewport={"width": 1440, "height": 900},
                    args=["--allow-downgrade"],
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
                    firefox_user_prefs={
                        "network.http.http3.enable": False,
                        "browser.cache.disk.enable": False,
                    },
                    timeout=120000,
                )
            page = context.pages[0] if context.pages else await context.new_page()
            await Stealth().apply_stealth_async(page)
            return pw, context, page
        except Exception as exc:
            last_error = exc
            logger.error(
                f"{name}: browser launch failed attempt {attempt}/{MAX_BROWSER_LAUNCH_ATTEMPTS}: {exc}"
            )
            try:
                await pw.stop()
            except Exception:
                pass
            for action in kill_browser_for_session(account.session_dir, account.browser):
                logger.warning(f"{name}: {action}")
            cleanup_session_artifacts(account.session_dir, account.browser)
            if attempt < MAX_BROWSER_LAUNCH_ATTEMPTS:
                await asyncio.sleep(2 * attempt)

    raise BrowserSessionLost(f"{name}: browser launch exhausted: {last_error}")


async def worker(name, account: PinterestAccount, queue, manager, headless=True):
    logger.info(f"Worker {name} using session {account.session_dir.name}")
    pw, context, page = None, None, None

    async def restart_browser(reason):
        nonlocal pw, context, page
        logger.warning(f"Worker {name} restarting browser: {reason}")
        had_browser = any([pw, context, page])
        await close_turbo_browser(pw, context)
        pw, context, page = None, None, None
        if had_browser:
            for action in kill_browser_for_session(account.session_dir, account.browser):
                logger.warning(f"Worker {name}: {action}")
        pw, context, page = await create_turbo_browser(account, name, headless=headless)
        if not await ensure_account_logged_in(page, account):
            raise BrowserSessionLost(f"Worker {name} could not verify Pinterest login")

    async def requeue_or_fail(item, filename, reason):
        item["attempts"] = item.get("attempts", 0) + 1
        if item["attempts"] < MAX_ITEM_ATTEMPTS:
            await queue.put(item)
            logger.warning(
                f"Worker {name} requeued {filename}: {reason} ({item['attempts']}/{MAX_ITEM_ATTEMPTS})"
            )
            return
        logger.error(f"Worker {name} failed {filename} after {item['attempts']} attempts: {reason}")

    try:
        while True:
            item = await queue.get()
            try:
                if item is None:
                    break

                img_path = item["file"]
                filename = img_path.name
                post = item["post"]

                if manager.is_uploaded(filename):
                    continue
                if not img_path.exists():
                    logger.warning(f"Worker {name} skipping missing file: {filename}")
                    continue

                if not page_is_alive(page):
                    try:
                        await restart_browser("no live page")
                    except Exception as exc:
                        await requeue_or_fail(item, filename, f"browser unavailable: {exc}")
                        await asyncio.sleep(min(120, 20 * max(1, item.get("attempts", 1))))
                        continue

                board = get_board_for_slug(post["slug"])
                logger.info(f"Worker {name} pinning: {filename}")
                try:
                    pin_id = await turbo_create_pin(page, post, img_path, board, name)
                    if pin_id:
                        logger.info(f"Worker {name} success: {pin_id}")
                        await manager.mark_completed(filename, post, pin_id)
                    else:
                        if not page_is_alive(page):
                            await close_turbo_browser(pw, context)
                            pw, context, page = None, None, None
                        await requeue_or_fail(item, filename, "pin flow returned no pin id")
                except Exception as exc:
                    if is_browser_session_lost(exc):
                        await close_turbo_browser(pw, context)
                        pw, context, page = None, None, None
                    await requeue_or_fail(item, filename, f"runtime error: {exc}")
            finally:
                queue.task_done()
                if item is not None:
                    await asyncio.sleep(random.uniform(1, 3))
    finally:
        await close_turbo_browser(pw, context)


def find_upload_files():
    files = {}
    for pattern in (
        "remastered_*.jpg",
        "remastered_*.jpeg",
        "remastered_*.png",
        "remaster_*.jpg",
        "remaster_*.jpeg",
        "remaster_*.png",
    ):
        for path in MEDIA_DIR.glob(pattern):
            files[str(path.resolve()).lower()] = path
    return list(files.values())


def build_upload_queue(posts, manager, limit=None):
    to_upload = []
    for image_path in find_upload_files():
        if manager.is_uploaded(image_path.name):
            continue

        exif_title = get_exif_title(image_path)
        file_norm = normalize_seo(image_path.name).replace(" ", "")
        exif_norm = normalize_seo(exif_title)
        matched_post = None
        best_score = 0

        for post in posts:
            title_norm = normalize_seo(post["title"])
            slug_orig = post["slug"].lower()
            slug_norm = normalize_seo(post["slug"]).replace(" ", "")
            score = 0

            # 1. Highest priority: slug exists as a whole word in the filename
            # (assuming filename is remastered_<slug>_<id>.jpg)
            if slug_orig in image_path.name.lower():
                score += 50

            # 2. Strong match: normalized slug in normalized filename
            if slug_norm and slug_norm in file_norm:
                score += 20

            # 3. EXIF match
            if exif_norm:
                common = set(title_norm.split()).intersection(set(exif_norm.split()))
                if len(common) > 2:
                    score += len(common) * 2

            if score > best_score:
                best_score = score
                matched_post = post

        if matched_post and best_score >= 10:
            clean_slug = matched_post["slug"]
            original_id = re.search(r"_(\d+)$", image_path.stem)
            image_id = original_id.group(1) if original_id else str(random.randint(1000, 9999))
            new_name = f"remastered_{clean_slug}_{image_id}{image_path.suffix}"
            new_path = image_path.parent / new_name
            while new_path.exists() and new_path.resolve() != image_path.resolve():
                image_id = str(random.randint(1000, 9999))
                new_name = f"remastered_{clean_slug}_{image_id}{image_path.suffix}"
                new_path = image_path.parent / new_name

            if image_path.name != new_name:
                try:
                    image_path.rename(new_path)
                    image_path = new_path
                    logger.info(f"SEO renamed: {new_name}")
                except Exception as exc:
                    logger.error(f"Rename failed for {image_path.name}: {exc}")

            to_upload.append({"file": image_path, "post": matched_post, "attempts": 0})
            if limit and len(to_upload) >= limit:
                break
    return to_upload


def parse_args():
    parser = argparse.ArgumentParser(description="Parallel Pinterest batch uploader")
    parser.add_argument("--run", action="store_true", help="Confirm a full unattended batch run")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of pins to queue")
    parser.add_argument("--workers", type=int, default=None, help="Maximum number of account sessions to use")

    parser.add_argument(
        "--no-clone", action="store_true", help="Do not clone missing turbo sessions from the primary profile"
    )
    args = parser.parse_args()
    # Enforce headless mode
    args.headful = False
    return args


async def main():
    args = parse_args()
    if args.limit is None and not args.run:
        logger.warning("No --limit or --run supplied; refusing unattended full batch")
        logger.warning("Use --run for the full queue, or --limit N for a controlled batch")
        return

    # Initialize Supabase and JobQueue
    from pinterest_automation.job_queue import get_job_queue

    queue = get_job_queue()
    sb = get_supabase()

    # Load posts
    response = (
        sb.table("posts")
        .select("id, title, slug, excerpt, pinterest_pin_id")
        .eq("status", "published")
        .execute()
    )
    posts = response.data
    manager = PinManager(sb)

    # Identify files to upload
    to_upload = build_upload_queue(posts, manager, limit=args.limit)

    if not to_upload:
        logger.info("No new pins to upload.")
        return

    logger.info(f"Enqueuing {len(to_upload)} pins for multi-account parallel processing...")

    # Define target accounts from PINTEREST_ACCOUNTS or defaults
    accounts = load_accounts()
    if not accounts:
        logger.error("No configured Pinterest accounts available; no jobs enqueued")
        return

    count = 0
    for i, item in enumerate(to_upload):
        img_path = item["file"]
        post = item["post"]
        board = get_board_for_slug(post["slug"])
        desc = build_pin_description(post)

        # Round-robin distribution across ALL available accounts
        target_account = accounts[i % len(accounts)]

        queue.enqueue_pin_upload(
            image_path=str(img_path.resolve()),
            title=post["title"],
            description=desc,
            link=f"https://recetadolce.com/{post['slug']}",
            board_name=board,
            extra={"account_handle": target_account.name},
        )
        count += 1

    logger.info(f"Successfully enqueued {count} jobs distributed across {len(accounts)} accounts.")
    logger.info("The Autonomous Supervisor will now process these in parallel.")

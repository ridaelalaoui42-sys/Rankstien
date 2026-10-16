"""
RankStein Pinterest Automation — Unified Pinterest Driver
High-level abstraction over Playwright with self-healing, retries, and health tracking.
"""

import asyncio
import contextlib
import json
import logging
import math
import os
import re
import time
import unicodedata
from collections.abc import Callable, Mapping
from datetime import UTC
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree

import httpx
from playwright.async_api import Page, Response
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .circuit_breaker import CircuitBreakerOpenError, get_circuit_breaker
from .config import DATA_DIR, get_config, resolve_account_board_name
from .mcp_bridge import publish_pin_agentic, publish_pin_direct_mcp
from .rate_limiter import get_rate_limiter
from .self_healing import fallback_heal, robust_fill
from .session_pool import SessionInfo, get_session_pool

logger = logging.getLogger("rankstein.driver")


def _pinterest_public_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme == "https"
            and (parsed.hostname == "pinterest.com" or (parsed.hostname or "").endswith(".pinterest.com"))
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        ):
            return parsed
    except ValueError:
        pass
    return None


def _public_pin_url_id(value):
    parsed = _pinterest_public_url(value)
    match = re.fullmatch(r"/pin/(\d{15,22})/?", parsed.path) if parsed else None
    return match.group(1) if match else None


def _story_pin_publication_request(request):
    """Identify only the observed story-pin create route inside ApiResource."""
    try:
        raw = request.post_data
        if not isinstance(raw, str):
            return False
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            encoded = parse_qs(raw).get("data", [])
            if len(encoded) != 1:
                return False
            payload = json.loads(encoded[0])
        if not isinstance(payload, dict) or not isinstance(payload.get("options"), dict):
            return False
        options = payload["options"]
        route = urlsplit(options.get("url", ""))
        if (
            route.scheme
            or route.netloc
            or route.query
            or route.fragment
            or route.path not in {"/v3/storypins", "/v3/storypins/"}
        ):
            return False
        for flags in (options, options.get("data")):
            if isinstance(flags, dict) and (
                flags.get("is_draft") is True
                or flags.get("draft") is True
                or flags.get("is_published") is False
                or str(flags.get("status", "")).casefold() in {"draft", "failed", "error"}
            ):
                return False
        return True
    except (AttributeError, TypeError, ValueError):
        return False


class _PublishedPinMetadata(HTMLParser):
    """Collect exact tags, including Pinterest's streamed public metadata."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_head = False
        self.head_seen = False
        self.body_seen = False
        self.values = {}
        self.ambiguous = False
        self.streamed = False

    def handle_starttag(self, tag, attrs):
        tag = tag.casefold()
        if tag == "head":
            if not self.head_seen and not self.body_seen:
                self.in_head = True
                self.head_seen = True
            else:
                self.ambiguous = True
            return
        if tag == "body":
            self.in_head = False
            self.body_seen = True
        attributes = {name.casefold(): value for name, value in attrs}
        key = ""
        value = None
        if tag == "meta":
            key = str(attributes.get("property") or attributes.get("name") or "").casefold()
            if key not in {"og:url", "og:title", "pinterestapp:source", "pinterestapp:pinner"}:
                return
            value = attributes.get("content")
        elif tag == "link" and "canonical" in str(attributes.get("rel") or "").casefold().split():
            key = "canonical"
            value = attributes.get("href")
        if key:
            self.streamed = self.streamed or not self.in_head
            if len(attributes) != len(attrs):
                self.ambiguous = True
            self.values.setdefault(key, set()).add(value)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag.casefold() == "head":
            self.in_head = False

    def exact(self, key):
        values = self.values.get(key, set())
        if self.ambiguous or len(values) != 1:
            return None
        return next(iter(values))


def _rss_candidate_receipt(body, candidate, title, description, started_at, observed_at):
    """Require an exact ID and fresh publication receipt from an owned feed."""
    checks = {
        "candidate_item_found": False,
        "link_matches": False,
        "guid_matches": False,
        "publication_time_matches": False,
        "title_or_description_matches": False,
    }
    try:
        root = ElementTree.fromstring(body)
    except (ElementTree.ParseError, TypeError, ValueError):
        return False, checks
    for item in root.findall("./channel/item"):
        link_matches = _public_pin_url_id(item.findtext("link")) == candidate
        guid_matches = _public_pin_url_id(item.findtext("guid")) == candidate
        if not link_matches and not guid_matches:
            continue
        publication_time_matches = False
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "")
            if published.utcoffset() is not None:
                publication_time_matches = started_at - 5 <= published.timestamp() <= observed_at + 5
        except (AttributeError, TypeError, ValueError, OverflowError):
            pass

        def normalize(value):
            return unicodedata.normalize("NFC", " ".join(value.split())).casefold()

        receipt_title = normalize(item.findtext("title") or "")
        expected = {normalize(title[:100])}
        if description and description.strip():
            expected.add(normalize(description))
        checks = {
            "candidate_item_found": True,
            "link_matches": link_matches,
            "guid_matches": guid_matches,
            "publication_time_matches": publication_time_matches,
            "title_or_description_matches": bool(receipt_title) and receipt_title in expected,
        }
        if all(checks.values()):
            return True, checks
    return False, checks


async def _anonymous_public_document(url: str, *, max_bytes: int = 3_000_000) -> str | None:
    """Read one public Pinterest document without the browser's account cookies."""
    if _pinterest_public_url(url) is None:
        return None
    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html,application/rss+xml"},
        cookies={},
        follow_redirects=False,
        timeout=httpx.Timeout(12),
    ) as client:
        async with client.stream("GET", url) as response:
            if response.status_code != 200 or str(response.url) != url:
                return None
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > max_bytes:
                    return None
            return content.decode(response.encoding or "utf-8", errors="replace")


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


PIN_CONFIRM_TIMEOUT_SECONDS = max(3, _int_env("PINTEREST_PIN_CONFIRM_TIMEOUT_SECONDS", 8))
PUBLISH_LLM_HEALING_ENABLED = _bool_env("PINTEREST_PUBLISH_LLM_HEALING", False)
MCP_FALLBACK_ENABLED = _bool_env("PINTEREST_ENABLE_MCP_FALLBACK", False)
DRAFT_CAPACITY_RECOVERY_TIMEOUT_SECONDS = 90


class PinterestNavigationUnavailableError(RuntimeError):
    """Pinterest could not be reached before authentication was checked."""

    def __init__(self, network_code: str, retry_after_seconds: float = 0):
        self.network_code = network_code
        try:
            retry_delay = float(retry_after_seconds)
        except (TypeError, ValueError, OverflowError):
            retry_delay = 0.0
        self.retry_after_seconds = retry_delay if math.isfinite(retry_delay) and retry_delay > 0 else 0.0
        super().__init__(f"Pinterest navigation unavailable ({network_code})")


def _parse_retry_after_seconds(value: object) -> float:
    """Honor a server's delay or HTTP date without retaining its raw header."""
    if not isinstance(value, str) or not value.strip():
        return 0.0
    value = value.strip()
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
        try:
            delay = float(value)
        except (ValueError, OverflowError):
            return 0.0
    else:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            delay = retry_at.timestamp() - time.time()
        except (TypeError, ValueError, OverflowError):
            return 0.0
    return delay if math.isfinite(delay) and delay > 0 else 0.0


class PinterestDriver:
    """
    Production-grade Pinterest automation driver.
    Handles login, pin creation, and session management with full self-healing.
    """

    def __init__(self, account_handle: str | None = None):
        self.config = get_config()
        self.pool = get_session_pool()
        self.rate_limiter = get_rate_limiter()
        self.circuit = get_circuit_breaker()
        self.account_handle = self._normalize_account_handle(account_handle)
        self._session: SessionInfo | None = None
        self._pin_create_data: dict = {}
        self._pin_create_event: asyncio.Event | None = None
        self._response_handler: Callable | None = None
        self._logger = logger

    def _normalize_account_handle(self, account_handle: str | None) -> str | None:
        if not account_handle:
            return account_handle
        handle = str(account_handle).strip()
        if handle in self.config.accounts:
            return handle
        if handle.startswith("r") and "rida" in self.config.accounts:
            return "rida"
        if handle.startswith("m") and "media" in self.config.accounts:
            return "media"
        return handle

    def _log(self, level, msg, *args, **kwargs):
        handle = self.account_handle
        if self._session and self._session.account_handle:
            handle = self._session.account_handle
        prefix = f"[{handle or 'default'}] "
        self._logger.log(level, prefix + msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self._log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self._log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self._log(logging.ERROR, msg, *args, **kwargs)

    def debug(self, msg, *args, **kwargs):
        self._log(logging.DEBUG, msg, *args, **kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def _acquire_session(self, account_handle: str | None = None) -> SessionInfo:
        handle = self._normalize_account_handle(account_handle or self.account_handle)
        if (
            self._session is None
            or self._session.closed
            or (handle and self._session.account_handle != handle)
        ):
            if self._session:
                await self.close()
            self._session = await self.pool.acquire(handle)
            if handle:
                self.account_handle = handle
        return self._session

    async def close(self, healthy: bool = True):
        if self._session:
            session = self._session
            self._session = None
            if healthy:
                await self.pool.release(session, healthy=True)
            else:
                await self.pool.release(session, healthy=False)
                await self.pool.retire(session)

    # ── Response interception ──────────────────────────────

    def _setup_pin_interception(self, page: Page):
        if self._response_handler is not None:
            with contextlib.suppress(Exception):
                page.remove_listener("response", self._response_handler)
        self._pin_create_data = {
            "pin_id": None,
            "pin_url": None,
            "generation_started_at": time.time(),
        }
        self._pin_candidate_verification = None
        self._pin_create_event = asyncio.Event()
        candidate_data = self._pin_create_data
        candidate_event = self._pin_create_event

        async def _on_response(response: Response):
            if self._pin_create_event is not candidate_event or response.request.method != "POST":
                return
            parsed = urlsplit(response.url)
            wrapper_create = parsed.path.lower().rstrip("/") == "/resource/apiresource/create"
            if (
                parsed.scheme != "https"
                or not (
                    parsed.hostname == "pinterest.com" or (parsed.hostname or "").endswith(".pinterest.com")
                )
                or (
                    parsed.path.lower().rstrip("/") not in {"/v3/pins", "/resource/pinresource/create"}
                    and not wrapper_create
                )
                or not 200 <= response.status < 300
                or (wrapper_create and not _story_pin_publication_request(response.request))
            ):
                return
            try:
                data = await response.json()
                if not isinstance(data, dict):
                    return
                resource = data.get("resource_response", data)
                if not isinstance(resource, dict) or (
                    (wrapper_create and resource.get("status") != "success")
                    or (wrapper_create and not isinstance(data.get("resource_response"), dict))
                    or (
                        resource.get("http_status") is not None
                        and (
                            type(resource["http_status"]) is not int
                            or not 200 <= resource["http_status"] < 300
                        )
                    )
                    or resource.get("status") not in (None, "success")
                    or resource.get("error")
                    or resource.get("errors")
                ):
                    return
                pin = resource.get("data", resource)
                if not isinstance(pin, dict) or (
                    pin.get("is_draft") is True
                    or pin.get("draft") is True
                    or pin.get("is_published") is False
                    or str(pin.get("status", "")).lower() in {"draft", "failed", "error"}
                ):
                    return
                pin_id = str(pin.get("id") or "")
                if re.fullmatch(r"\d{15,22}", pin_id) and self._pin_create_event is candidate_event:
                    # A successful create response is a candidate, not proof of
                    # publication. Draft creation and published creation can
                    # share API shapes; callers still need publication proof.
                    candidate_data["pin_id"] = pin_id
                    candidate_data["pin_url"] = f"https://www.pinterest.com/pin/{pin_id}/"
                    candidate_data["observed_at"] = time.time()
                    candidate_event.set()
                    self.info(f"Intercepted pin creation candidate: {pin_id}")
            except Exception:
                pass

        self._response_handler = _on_response
        page.on("response", _on_response)

    # ── Login ──────────────────────────────────────────────

    async def _has_auth_cookies(self, context) -> bool:
        """Check for Pinterest auth cookies without navigating."""
        try:
            cookies = await context.cookies()
            auth_cookie_names = {"_auth", "_pinterest_sess", "pinterest.auth", "_r", "csrftoken"}
            found = {
                c["name"] for c in cookies if c["name"] in auth_cookie_names or "auth" in c["name"].lower()
            }
            return len(found) >= 2
        except Exception:
            return False

    async def _is_login_page(self, page) -> bool:
        """Check if current page is the Pinterest login page."""
        url = page.url.lower()
        return "login" in url or "oauth" in url or "signin" in url

    async def _navigate_for_login(self, page, url: str, **kwargs):
        """Keep explicit transport failures separate from rejected authentication."""
        try:
            response = await page.goto(url, **kwargs)
        except (PlaywrightTimeoutError, TimeoutError):
            # A navigation timeout says nothing about the supplied credentials.
            # Do not count it against the account's authentication circuit.
            raise PinterestNavigationUnavailableError("NAVIGATION_TIMEOUT") from None
        except Exception as exc:
            match = re.search(r"\bnet::(ERR_[A-Z_]+)\b", str(exc))
            if match and match.group(1) in {
                "ERR_NAME_NOT_RESOLVED",
                "ERR_INTERNET_DISCONNECTED",
                "ERR_NETWORK_CHANGED",
                "ERR_CONNECTION_CLOSED",
                "ERR_CONNECTION_RESET",
                "ERR_CONNECTION_REFUSED",
                "ERR_CONNECTION_ABORTED",
                "ERR_CONNECTION_TIMED_OUT",
                "ERR_TIMED_OUT",
                "ERR_EMPTY_RESPONSE",
                "ERR_ADDRESS_UNREACHABLE",
                "ERR_PROXY_CONNECTION_FAILED",
                "ERR_TUNNEL_CONNECTION_FAILED",
                "ERR_DNS_TIMED_OUT",
            }:
                # The raw browser error may contain a URL or user information.
                raise PinterestNavigationUnavailableError(match.group(1)) from None
            raise
        status = getattr(response, "status", None)
        if type(status) is int and (status == 429 or 500 <= status <= 599):
            # goto returns a response for HTTP errors, so merely landing on a
            # creator URL must not treat an outage/throttle as a valid login.
            headers = getattr(response, "headers", {})
            retry_after = None
            if isinstance(headers, Mapping):
                retry_after = next(
                    (value for key, value in headers.items() if str(key).lower() == "retry-after"), None
                )
            raise PinterestNavigationUnavailableError(
                f"HTTP_{status}", retry_after_seconds=_parse_retry_after_seconds(retry_after)
            )
        return response

    async def ensure_logged_in(self, account_handle: str | None = None) -> bool:
        handle = account_handle or self.account_handle
        login_operation = f"pinterest_login:{handle or 'default'}"
        if not self.circuit.can_execute(login_operation):
            raise CircuitBreakerOpenError(f"Pinterest login circuit is OPEN for {handle or 'default'}")
        session = await self._acquire_session(handle)
        page = session.page

        try:
            # ── Phase 1: Lightweight check (no navigation) ──
            # If we're already on the pin creation page, we're good.
            current_url = page.url.lower()
            if "pin-creation-tool" in current_url or "pin-builder" in current_url:
                self.info(f"Already on creation tool — logged in as {handle or 'default'}")
                self.circuit.record_success(login_operation)
                return True

            # Check auth cookies — if present, session should be valid
            has_cookies = await self._has_auth_cookies(session.context)
            if has_cookies and not await self._is_login_page(page):
                # Have cookies and not on login page — navigate to pin-creation-tool
                self.info(f"Auth cookies present, navigating to creation tool for {handle or 'default'}...")
                await self._navigate_for_login(
                    page,
                    "https://www.pinterest.com/pin-creation-tool/",
                    timeout=self.config.browser.navigation_timeout_ms,
                    wait_until="domcontentloaded",
                )
                await asyncio.sleep(2)
                if "pin-creation-tool" in page.url or "pin-builder" in page.url:
                    self.info(f"Already logged in and ready as {handle or 'default'}")
                    self.circuit.record_success(login_operation)
                    return True
                if not await self._is_login_page(page):
                    # Weird landing page — try one more navigation
                    await self._navigate_for_login(
                        page, "https://www.pinterest.com/pin-creation-tool/", timeout=30000
                    )
                    await asyncio.sleep(2)
                    if "pin-creation-tool" in page.url or "pin-builder" in page.url:
                        return True

            # ── Phase 2: Full login flow ──
            self.info(
                f"Session invalid for creation tool, attempting Pinterest login for {handle or 'default'}..."
            )
            if not await self._is_login_page(page):
                await self._navigate_for_login(
                    page,
                    "https://www.pinterest.com/login/",
                    timeout=self.config.browser.navigation_timeout_ms,
                )
            await page.wait_for_timeout(2000)

            # Get credentials
            creds = self.config.credentials
            if handle and handle in self.config.accounts:
                creds = self.config.accounts[handle]

            email = creds.email
            password = creds.password

            # Dismiss overlays and wait for input visibility
            found_login = False
            for _ in range(12):
                email_loc = page.locator('input[type="email"], input#email, input[name="id"]').first
                password_loc = page.locator(
                    'input[type="password"], input#password, input[name="password"]'
                ).first

                if await email_loc.count() > 0 and await password_loc.count() > 0:
                    if await email_loc.is_visible() and await password_loc.is_visible():
                        found_login = True
                        break

                # Evaluate JS to hide Google One Tap overlays
                try:
                    await page.evaluate("""
                        () => {
                            const selectors = [
                                '#credential_picker_container',
                                '.L5Fo6c-PQbLGe',
                                '[title="Sign in with Google Dialog"]'
                            ];
                            selectors.forEach(sel => {
                                const el = document.querySelector(sel);
                                if (el) el.style.display = 'none';
                            });
                        }
                    """)
                except Exception:
                    pass

                # Try clicking Log in button overlay if visible
                try:
                    btn = page.locator(
                        'div[data-test-id="login-button"], button:has-text("Log in"), button:has-text("Iniciar sesión"), a:has-text("Log in"), a:has-text("Iniciar sesión")'
                    ).first
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click(timeout=1000)
                        await asyncio.sleep(1)
                        continue
                except Exception:
                    pass

                await asyncio.sleep(1)

            # Find and fill email. Pinterest periodically changes between
            # login, signup, localized, and embedded forms. Do not hard-fail on
            # a single selector; choose the first visible username-like input.
            self.info(f"Looking for email/password fields for {email}...")
            email_sel = await self._first_visible_selector(
                page,
                [
                    "input#email",
                    'input[name="id"]',
                    'input[type="email"]',
                    'input[autocomplete="username"]',
                    'input[autocomplete="email"]',
                    'input[placeholder*="email" i]',
                    'input[placeholder*="correo" i]',
                    'input[aria-label*="email" i]',
                    'input[aria-label*="correo" i]',
                ],
                timeout_ms=15000,
            )
            if not email_sel:
                await self._save_debug_artifact(page, "login_no_email")
                self.circuit.record_failure(login_operation)
                session.failure_count += 1
                return False
            self.info(f"Using email selector: {email_sel}")
            email_el = page.locator(email_sel).first
            is_readonly = await email_el.get_attribute("readonly") is not None
            if not is_readonly and await email_el.is_editable():
                await page.fill(email_sel, email)
            else:
                self.info("Email field is readonly/pre-filled; skipping email fill")
            await page.wait_for_timeout(1000)

            # Pinterest now uses a 2-step login:
            #   Step 1: email only + "Continue" button
            #   Step 2: password + "Log in" button
            # Check if password field is visible on the same page first.
            pwd_inline = await self._first_visible_selector(
                page,
                [
                    "input#password",
                    'input[name="password"]',
                    'input[type="password"]',
                    'input[autocomplete="current-password"]',
                ],
                timeout_ms=3000,
            )

            if pwd_inline:
                # Single-page login (both fields visible)
                self.info(f"Using password selector (inline): {pwd_inline}")
                await page.fill(pwd_inline, password)
                await page.wait_for_timeout(1000)
                self.info("Submitting login form...")
                try:
                    await page.click('button[type="submit"]')
                except Exception:
                    self.warning("Submit button click failed, using Enter key")
                    await page.keyboard.press("Enter")
                await page.wait_for_timeout(15000)
            else:
                # Two-step login: submit email first, then fill password
                self.info("Password field not visible — using 2-step login flow")
                self.info("Submitting email (Step 1)...")
                try:
                    await page.click('button[type="submit"]')
                except Exception:
                    await page.keyboard.press("Enter")
                await page.wait_for_timeout(5000)

                # Wait for password field to appear
                self.info("Waiting for password field (Step 2)...")
                pwd_sel = await self._first_visible_selector(
                    page,
                    [
                        "input#password",
                        'input[name="password"]',
                        'input[type="password"]',
                        'input[autocomplete="current-password"]',
                        'input[placeholder*="password" i]',
                        'input[placeholder*="contraseña" i]',
                        'input[aria-label*="password" i]',
                        'input[aria-label*="contraseña" i]',
                    ],
                    timeout_ms=15000,
                )
                if not pwd_sel:
                    await self._save_debug_artifact(page, "login_no_password")
                    self.circuit.record_failure(login_operation)
                    session.failure_count += 1
                    return False
                self.info(f"Using password selector: {pwd_sel}")
                await page.fill(pwd_sel, password)
                await page.wait_for_timeout(1000)
                self.info("Submitting password (Step 2)...")
                try:
                    await page.click('button[type="submit"]')
                except Exception:
                    await page.keyboard.press("Enter")
                await page.wait_for_timeout(15000)

            logged_in = "login" not in page.url and "pinterest.com" in page.url
            if logged_in:
                self.info("Login successful")
                self.circuit.record_success(login_operation)
                return True
            else:
                # Check if a 2FA / security challenge page appeared
                self.error(f"Login failed for account {handle or 'default'}")
                await self._save_debug_artifact(page, "login_fail")
                self.circuit.record_failure(login_operation, retryable=False)
                return False

        except PinterestNavigationUnavailableError:
            raise
        except Exception as e:
            self.error(f"Login error: {e}")
            self.circuit.record_failure(login_operation)
            session.failure_count += 1
            return False

    async def _recover_draft_capacity(self, page: Page, account_handle: str | None) -> dict:
        """Empty the blocked account's drafts and require verified creator recovery.

        The caller retains its existing account lock and session throughout. Draft
        deletion requests must not be mistaken for a newly published pin.
        """
        handler = getattr(self, "_response_handler", None)
        if handler is not None:
            with contextlib.suppress(Exception):
                page.remove_listener("response", handler)
        self._pin_create_data = {"pin_id": None, "pin_url": None}
        if self._pin_create_event is not None:
            self._pin_create_event.clear()
        try:
            from scripts.ops.clear_pinterest_drafts import clear_drafts_for_page_verified

            report = await asyncio.wait_for(
                clear_drafts_for_page_verified(
                    page,
                    account_name=account_handle or self.account_handle or "driver",
                    timeout_seconds=DRAFT_CAPACITY_RECOVERY_TIMEOUT_SECONDS,
                ),
                timeout=DRAFT_CAPACITY_RECOVERY_TIMEOUT_SECONDS + 5,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            from backend.scripts.pinterest_batch_core import BrowserSessionLost

            if isinstance(exc, BrowserSessionLost):
                raise
            self.warning(f"Draft capacity repair could not be verified: {exc}")
            return {"ok": False, "creator_ready": False, "error": str(exc)[:500]}
        verified = (
            isinstance(report, dict)
            and report.get("ok") is True
            and report.get("creator_ready") is True
            and type(report.get("remaining_count")) is int
            and report.get("remaining_count") == 0
            and type(report.get("deleted")) is int
            and report["deleted"] >= 0
        )
        if not verified:
            error = report.get("error") if isinstance(report, dict) else None
            self.warning(f"Draft capacity repair did not restore an empty creator: {error or report}")
            return {**(report if isinstance(report, dict) else {}), "ok": False}
        self.info(f"Draft capacity repaired: {report['deleted']} drafts deleted; creator ready.")
        return report

    async def _clear_draft_limit_if_needed(self, page: Page, max_delete: int = 50) -> int:
        """Repair a confirmed capacity warning; ordinary loading never deletes drafts.

        ``max_delete`` remains accepted for legacy callers. A full creator needs
        verified empty-draft recovery rather than an unverified partial purge.
        """
        from backend.scripts.pinterest_batch_core import (
            PinterestDraftCapacityError,
            ensure_creator_draft_capacity_available,
        )

        try:
            await ensure_creator_draft_capacity_available(page, f"driver-{self.account_handle or 'default'}")
        except PinterestDraftCapacityError as exc:
            report = await self._recover_draft_capacity(page, self.account_handle)
            if report.get("ok") is not True:
                exc.draft_cleanup = report
                raise
            self._setup_pin_interception(page)
            return report["deleted"]
        return 0

    async def _shared_pin_upload_attempt(
        self,
        upload_call,
        page: Page,
        local: Path,
        title: str,
        link: str,
        description: str,
        board_name: str,
        worker_id: str,
    ) -> str | None:
        """Wait for publication; an API candidate must never cancel the uploader."""
        shared_task = asyncio.create_task(
            upload_call(page, local, title, link, description, board_name, worker_id)
        )
        response_task = asyncio.create_task(self._pin_create_event.wait())
        try:
            await asyncio.wait({shared_task, response_task}, return_when=asyncio.FIRST_COMPLETED)
            pin_id = await shared_task
            return str(pin_id) if re.fullmatch(r"\d{15,22}", str(pin_id or "")) else None
        finally:
            # Neither child may outlive the account session on outer cancellation.
            for task in (shared_task, response_task):
                if not task.done():
                    task.cancel()
            for task in (shared_task, response_task):
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    async def _shared_pin_upload_with_capacity_recovery(
        self,
        upload_call,
        page: Page,
        local: Path,
        title: str,
        link: str,
        description: str,
        board_name: str,
        account_handle: str | None,
    ) -> tuple[str | None, dict | None]:
        """Recover capacity once on the same page, then retry the identical payload."""
        from backend.scripts.pinterest_batch_core import PinCreationError

        worker_id = f"driver-{account_handle or 'default'}"
        recovery = None
        for attempt in range(2):
            try:
                pin_id = await self._shared_pin_upload_attempt(
                    upload_call, page, local, title, link, description, board_name, worker_id
                )
                if not pin_id and recovery is not None:
                    exc = PinCreationError(f"{worker_id}: repaired creator returned no verified Pin ID")
                    exc.draft_cleanup = recovery
                    raise exc
                if not pin_id and self._pin_create_data.get("pin_id"):
                    exc = PinCreationError(f"{worker_id}: creation candidate has no verified publication")
                    exc.uncertain = True
                    raise exc
                return pin_id, recovery
            except PinCreationError as exc:
                # A candidate can accompany a failed/draft creation. Only an
                # exact public match can override the uploader's exception.
                verified = await self._verify_intercepted_public_pin(
                    page,
                    title=title,
                    link=link,
                    account_handle=account_handle,
                    description=description[:500],
                )
                if verified:
                    return verified, recovery
                if getattr(exc, "error_code", None) != "pinterest_draft_capacity":
                    if recovery is not None:
                        exc.draft_cleanup = recovery
                    if self._pin_create_data.get("pin_id"):
                        exc.uncertain = True
                    raise
                if attempt:
                    exc.draft_cleanup = recovery
                    raise
                self.warning("Creator draft capacity reached; repairing the account before retrying its pin.")
                recovery = await self._recover_draft_capacity(page, account_handle)
                if recovery.get("ok") is not True:
                    exc.draft_cleanup = recovery
                    raise
                # Cleanup may send PinResource POSTs for existing drafts. Only
                # fresh creation responses from the retry may establish proof.
                self._setup_pin_interception(page)
            except Exception as exc:
                if recovery is not None:
                    exc.draft_cleanup = recovery
                raise
        return None, recovery

    async def _first_visible_selector(
        self, page: Page, selectors: list[str], timeout_ms: int = 10000
    ) -> str | None:
        deadline = time.time() + max(1, timeout_ms / 1000)
        while time.time() < deadline:
            for selector in selectors:
                try:
                    locator = page.locator(selector).first
                    if await locator.count() > 0 and await locator.is_visible(timeout=300):
                        return selector
                except Exception:
                    continue
            await page.wait_for_timeout(500)
        return None

    async def _save_debug_artifact(self, page: Page, prefix: str) -> None:
        stamp = int(time.time())
        try:
            await page.screenshot(path=str(DATA_DIR / f"debug_{prefix}_{stamp}.png"), timeout=10000)
        except Exception:
            pass
        try:
            (DATA_DIR / f"debug_{prefix}_{stamp}.html").write_text(await page.content(), encoding="utf-8")
        except Exception:
            pass

    # ── Pin Creation ───────────────────────────────────────

    async def create_pin(
        self,
        image_path: str,
        title: str,
        description: str,
        link: str = "",
        alt_text: str = "",
        board_name: str = "",
        account_handle: str | None = None,
        domain_handle: str | None = None,
    ) -> dict:
        """
        Create a Pinterest pin with full self-healing and retry logic.
        Returns: {success, pin_id, pin_url, error}
        """
        operation = "pin_upload"
        handle = account_handle or self.account_handle
        circuit_operation = f"{operation}:{handle or 'default'}"
        rate_operation = f"{operation}:{domain_handle or 'direct'}:{handle or 'unknown'}"
        limiter = get_rate_limiter(domain_handle=domain_handle)
        board_name = resolve_account_board_name(
            board_name or self.config.default_board,
            handle,
        )
        if not self.circuit.can_execute(circuit_operation):
            raise CircuitBreakerOpenError(f"Circuit '{circuit_operation}' is OPEN")

        if not limiter.can_execute(rate_operation):
            return {"success": False, "error": "Rate limit exceeded"}

        session = await self._acquire_session(handle)
        page = session.page

        local = Path(image_path)
        if not local.exists():
            return {"success": False, "error": f"Image not found: {image_path}"}

        self._setup_pin_interception(page)

        from backend.scripts.pinterest_batch_core import (
            BrowserSessionLost,
            PinCreationError,
            ensure_creator_draft_capacity_available,
        )

        try:
            from backend.scripts.pinterest_batch_core import create_pin_from_fields

            self.info("Using shared Pinterest uploader core...")
            pin_id, recovery = await self._shared_pin_upload_with_capacity_recovery(
                create_pin_from_fields, page, local, title, link, description, board_name, handle
            )
            if pin_id:
                limiter.record_execution(rate_operation)
                self.circuit.record_success(circuit_operation)
                return {
                    "success": True,
                    "pin_id": pin_id,
                    "pin_url": f"https://www.pinterest.com/pin/{pin_id}/",
                    "method": "shared-core",
                    **self._candidate_verification_details(),
                    **({"draft_cleanup": recovery} if recovery is not None else {}),
                }
            self.warning("Shared Pinterest uploader returned no pin id; continuing with legacy fallback.")
        except BrowserSessionLost:
            raise
        except Exception as shared_exc:
            from backend.scripts.pinterest_batch_core import PinCreationError

            if isinstance(shared_exc, PinCreationError):
                msg = str(shared_exc)
                self.warning(f"Shared uploader aborted: {msg}.")
                if getattr(shared_exc, "error_code", None) in {
                    "pinterest_publish_unavailable",
                    "pinterest_publish_uncertain",
                }:
                    # A disabled editor never justifies a second publisher;
                    # an uncertain click must retain its exact failure state.
                    return {
                        "success": False,
                        "error": msg,
                        "error_code": shared_exc.error_code,
                        "uncertain": bool(getattr(shared_exc, "uncertain", False)),
                        "publish_diagnostics": getattr(shared_exc, "publish_diagnostics", None),
                        **self._candidate_verification_details(),
                        **(
                            {"draft_cleanup": shared_exc.draft_cleanup}
                            if getattr(shared_exc, "draft_cleanup", None) is not None
                            else {}
                        ),
                    }
                if getattr(shared_exc, "error_code", None) == "pinterest_draft_capacity":
                    return {
                        "success": False,
                        "error": msg,
                        "error_code": "pinterest_draft_capacity",
                        "draft_cleanup": getattr(shared_exc, "draft_cleanup", None),
                    }
                if getattr(shared_exc, "draft_cleanup", None) is not None:
                    return {
                        "success": False,
                        "error": msg,
                        "uncertain": True,
                        "draft_cleanup": shared_exc.draft_cleanup,
                    }
                if getattr(shared_exc, "uncertain", False):
                    return {"success": False, "error": msg, "uncertain": True}
                if "publish clicked but no Pin ID" in msg:
                    pin_id = await self._verify_recent_public_pin(
                        page,
                        title=title,
                        link=link,
                        account_handle=handle,
                    )
                    if pin_id:
                        limiter.record_execution(rate_operation)
                        self.circuit.record_success(circuit_operation)
                        return {
                            "success": True,
                            "pin_id": pin_id,
                            "pin_url": f"https://www.pinterest.com/pin/{pin_id}/",
                            "method": "public-profile-verification",
                        }
                    return {
                        "success": False,
                        "error": "Pin creation could not be verified; no pin_id or pin_url found",
                    }
                self.warning("Falling back to driver-native logic before any publish was confirmed.")
                if "board selection failed" in msg:
                    # Specific case where we might want to record failure but still try fallback
                    pass
            else:
                if getattr(shared_exc, "draft_cleanup", None) is not None:
                    return {
                        "success": False,
                        "error": str(shared_exc)[:500],
                        "uncertain": True,
                        "draft_cleanup": shared_exc.draft_cleanup,
                    }
                self.warning(f"Shared Pinterest uploader failed before legacy fallback: {shared_exc}")

        try:
            # Navigate to pin builder with shorter timeout and manual retries
            self.info("Navigating to pin creation tool...")
            success_nav = False
            for nav_attempt in range(3):
                try:
                    self.info(f"Navigation attempt {nav_attempt + 1} to pin-creation-tool...")
                    await page.goto(
                        "https://www.pinterest.com/pin-creation-tool/",
                        timeout=30000,
                        wait_until="domcontentloaded",
                    )
                    self.info(f"Page reached. URL: {page.url}")
                    success_nav = True
                    break
                except Exception as nav_e:
                    self.warning(f"Navigation attempt {nav_attempt + 1} failed: {nav_e}")
                    await asyncio.sleep(5)

            if not success_nav:
                return {"success": False, "error": "Could not reach pin creation tool after 3 attempts"}

            await asyncio.sleep(3)

            # Check login redirect
            if "login" in page.url:
                self.warning("Redirected to login, attempting relogin...")
                if not await self.ensure_logged_in(handle):
                    return {"success": False, "error": "Not logged in after relogin attempt"}
                await page.goto("https://www.pinterest.com/pin-creation-tool/", timeout=45000)
                await page.wait_for_load_state("domcontentloaded", timeout=10000)

            self.info("Starting upload sequence...")

            cleared_drafts = await self._clear_draft_limit_if_needed(page, max_delete=2)
            if cleared_drafts:
                self.info(f"Deleted {cleared_drafts} stale Pinterest draft(s); reloading creator.")
                await page.goto(
                    "https://www.pinterest.com/pin-creation-tool/",
                    timeout=45000,
                    wait_until="domcontentloaded",
                )
                await page.wait_for_timeout(3000)

            # Upload image
            self.info(f"Looking for file input for: {local.name}")

            # Hide drafts sidebar if it exists
            try:
                sidebar_btn = page.locator('[data-test-id="collapse-drafts-sidebar-button"]').first
                if await sidebar_btn.count() > 0 and await sidebar_btn.is_visible():
                    self.info("Collapsing drafts sidebar...")
                    await sidebar_btn.click()
                    await page.wait_for_timeout(500)
            except Exception as e:
                self.debug(f"Drafts sidebar collapse failed: {e}")

            if not local.exists():
                return {"success": False, "error": f"Image not found on disk: {local}"}

            file_input = page.locator('input[type="file"]')
            await file_input.set_input_files(str(local), timeout=15000)
            self.info("Image upload triggered via set_input_files")
            self.info("Waiting for image to process on page...")
            try:
                await page.locator(
                    "#storyboard-selector-title, "
                    "[data-test-id='pin-draft-title'] textarea, "
                    "input[placeholder*='title' i]"
                ).first.wait_for(state="visible", timeout=20000)
            except Exception:
                await page.wait_for_timeout(2500)

            await ensure_creator_draft_capacity_available(page, f"driver-{handle or 'default'}")

            # Scroll for visibility
            self.info("Scrolling page for form field visibility...")
            await page.evaluate("window.scrollTo(0, 300)")
            await page.wait_for_timeout(500)

            # Fill fields with self-healing
            self.info(f"Filling title: {title[:30]}...")
            title_filled = await robust_fill(page, "title", "the pin title input field", title[:100])
            self.info(f"Title filled status: {title_filled}")
            if not title_filled:
                return {"success": False, "error": "Title field was not filled"}
            await page.wait_for_timeout(500)

            self.info(f"Filling description ({len(description)} chars)...")
            desc_filled = await robust_fill(
                page, "description", "the pin description input field", description[:499], use_keyboard=True
            )
            self.info(f"Description filled status: {desc_filled}")
            if not desc_filled:
                return {"success": False, "error": "Description field was not filled"}
            await page.wait_for_timeout(500)

            # Alt text and Tags
            if alt_text:
                self.info("Filling alt text...")
                await self._fill_alt_text(page, alt_text)
                await page.wait_for_timeout(500)

            # Targeted Topics
            try:
                self.info("Filling tagged topics...")
                # Look for the "Tagged topics" button or input container
                tag_input = page.locator('[data-test-id="topic-search-input"]')
                if await tag_input.count() > 0:
                    await tag_input.fill("Food & Drink")
                    await page.keyboard.press("Enter")
                    self.info("Tagged topics filled")
                    await page.wait_for_timeout(500)
            except Exception as e:
                self.debug(f"Tagged topics filling skipped/failed: {e}")

            # Destination link
            if link:
                self.info(f"Filling link: {link}")
                link_filled = await robust_fill(page, "link", "the destination link input field", link)
                self.info(f"Link filled status: {link_filled}")
                if not link_filled:
                    return {"success": False, "error": "Destination link field was not filled"}
                await page.wait_for_timeout(750)

            # Board selection
            await ensure_creator_draft_capacity_available(page, f"driver-{handle or 'default'}")
            if board_name:
                self.info(f"Selecting board: {board_name}")
                board_selected = await self._select_board(page, board_name)
                if not board_selected:
                    return {"success": False, "error": f"Board selection failed: {board_name}"}
                await page.wait_for_timeout(750)

            # Scroll to publish
            self.info("Scrolling to the bottom to find publish button...")
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(500)

            # Publish
            await ensure_creator_draft_capacity_available(page, f"driver-{handle or 'default'}")
            self.info("Clicking Publish...")
            publish_ok = await self._click_publish(page)
            self.info(f"Publish click outcome: {publish_ok}")
            if not publish_ok:
                return {"success": False, "error": "Publish button not found or not clickable"}

            # Wait for API response
            self.info(
                f"Waiting up to {PIN_CONFIRM_TIMEOUT_SECONDS}s for pin creation confirmation from API..."
            )
            try:
                await asyncio.wait_for(self._pin_create_event.wait(), timeout=PIN_CONFIRM_TIMEOUT_SECONDS)
                self.info("API confirmation received!")
            except TimeoutError:
                self.info("API interception timeout, checking page URL/DOM for success markers...")

            pin_id = self._pin_create_data.get("pin_id")
            current_url = page.url

            # Fallback extraction
            if not pin_id:
                pin_id = await self._extract_pin_from_page(page)

            if not pin_id:
                pin_match = re.search(r"/pin/(\d+)", current_url)
                if pin_match:
                    pin_id = pin_match.group(1)

            if pin_id:
                pin_id = await self._verify_intercepted_public_pin(
                    page, title=title, link=link, account_handle=handle, candidate_id=pin_id
                )
            else:
                pin_id = await self._verify_recent_public_pin(
                    page,
                    title=title,
                    link=link,
                    account_handle=handle,
                )

            if pin_id:
                limiter.record_execution(rate_operation)
                self.circuit.record_success(circuit_operation)
                return {
                    "success": True,
                    "pin_id": pin_id,
                    "pin_url": f"https://www.pinterest.com/pin/{pin_id}/",
                }
            else:
                self.warning("Pin creation could not be verified; no pin id/url found")
                limiter.record_failure(rate_operation)
                self.circuit.record_failure(circuit_operation)
                session.failure_count += 1
                return {
                    "success": False,
                    "error": "Pin creation could not be verified; no pin_id or pin_url found",
                    "uncertain": True,
                }

        except Exception as e:
            if getattr(e, "error_code", None) == "pinterest_draft_capacity":
                return {
                    "success": False,
                    "error": str(e),
                    "error_code": "pinterest_draft_capacity",
                    "draft_cleanup": getattr(e, "draft_cleanup", None),
                }
            self.error(f"Manual Pin creation failed: {e}")
            if not MCP_FALLBACK_ENABLED:
                limiter.record_failure(rate_operation)
                self.circuit.record_failure(circuit_operation)
                session.failure_count += 1
                return {"success": False, "error": str(e)[:500]}

            self.info("Attempting DIRECT MCP fallback...")
            # Direct MCP fallback
            try:
                direct_res = await publish_pin_direct_mcp(
                    image_path=image_path,
                    title=title,
                    description=description,
                    link=link,
                    board_name=board_name,
                )
                if direct_res.get("success"):
                    limiter.record_execution(rate_operation)
                    self.circuit.record_success(circuit_operation)
                    return direct_res
                else:
                    self.warning(
                        f"Direct MCP fallback failed: {direct_res.get('error')}. Moving to AGENTIC fallback..."
                    )
            except Exception as direct_e:
                self.error(f"Direct MCP fallback crashed: {direct_e}")

            # Agentic fallback
            try:
                self.info("Attempting AGENTIC fallback via MCP...")
                agent_res = publish_pin_agentic(
                    image_path=image_path,
                    title=title,
                    description=description,
                    link=link,
                    board_name=board_name,
                )
                if agent_res.get("success"):
                    limiter.record_execution(rate_operation)
                    self.circuit.record_success(circuit_operation)
                    pin_url = agent_res["pin_url"]
                    pin_id = pin_url.split("/pin/")[-1].strip("/")
                    return {"success": True, "pin_id": pin_id, "pin_url": pin_url, "method": "agentic"}
                else:
                    self.error(f"Agentic fallback also failed: {agent_res.get('error')}")
            except Exception as agent_e:
                self.error(f"Agentic fallback crashed: {agent_e}")

            limiter.record_failure(rate_operation)
            self.circuit.record_failure(circuit_operation)
            session.failure_count += 1
            return {"success": False, "error": str(e)[:500]}

    # ── Pin Saving (Repin) ─────────────────────────────────

    async def save_pin(
        self,
        pin_url: str,
        board_name: str = "",
        account_handle: str | None = None,
        domain_handle: str | None = None,
    ) -> dict:
        """
        Save (repin) an existing pin to a board.
        Returns: {success, pin_id, error}
        """
        operation = "pin_save"
        handle = account_handle or self.account_handle
        circuit_operation = f"{operation}:{handle or 'default'}"
        rate_operation = f"{operation}:{domain_handle or 'direct'}:{handle or 'unknown'}"
        limiter = get_rate_limiter(domain_handle=domain_handle)
        board_name = resolve_account_board_name(
            board_name or self.config.default_board,
            handle,
        )
        if not self.circuit.can_execute(circuit_operation):
            raise CircuitBreakerOpenError(f"Circuit '{circuit_operation}' is OPEN")
        if not limiter.can_execute(rate_operation):
            return {"success": False, "error": "Rate limit exceeded"}

        session = await self._acquire_session(handle)
        page = session.page

        try:
            # Ensure logged in
            if not await self.ensure_logged_in(handle):
                return {"success": False, "error": "Login failed"}

            self.info(f"Navigating to pin URL for saving: {pin_url}")
            nav_ok = False
            for attempt in range(2):
                try:
                    await page.goto(
                        pin_url, timeout=60000 if attempt == 0 else 30000, wait_until="domcontentloaded"
                    )
                    nav_ok = True
                    break
                except PlaywrightTimeoutError as nav_exc:
                    self.warning(f"Pin page navigation timed out on attempt {attempt + 1}: {nav_exc}")
                    if "/pin/" in page.url:
                        nav_ok = True
                        break
                    await asyncio.sleep(3)
            if not nav_ok:
                return {"success": False, "error": f"Pin page navigation failed: {pin_url}"}
            await asyncio.sleep(3)

            # Check if already saved or if pin exists
            if await page.query_selector('button:has-text("Saved"), button:has-text("Guardado")'):
                self.info("Pin already saved to a board")
                return {"success": True, "already_saved": True}

            # Select board if provided
            if board_name:
                self.info(f"Selecting board for save: {board_name}")
                await self._select_board(page, board_name)
                await asyncio.sleep(2)

            # Click Save/Publish
            self.info("Clicking Save button...")
            save_ok = await self._click_publish(page)  # Reusing publish button logic
            if not save_ok:
                # Try generic "Save" button on the pin page
                for sel in [
                    'button[data-test-id="PinBetterSaveCanvas"]',
                    'button:has-text("Save")',
                    'button:has-text("Guardar")',
                ]:
                    try:
                        btn = page.locator(sel).first
                        if await btn.count() > 0 and await btn.is_visible():
                            await btn.click(force=True)
                            save_ok = True
                            break
                    except:
                        continue

            if save_ok:
                self.info("Pin saved successfully")
                limiter.record_execution(rate_operation)
                self.circuit.record_success(circuit_operation)
                # Extract pin ID from URL
                pin_id = None
                m = re.search(r"/pin/(\d+)", pin_url)
                if m:
                    pin_id = m.group(1)
                return {"success": True, "pin_id": pin_id, "pin_url": pin_url}
            else:
                return {"success": False, "error": "Save button not found"}

        except Exception as e:
            self.error(f"Save pin failed: {e}")
            limiter.record_failure(rate_operation)
            self.circuit.record_failure(circuit_operation)
            session.failure_count += 1
            return {"success": False, "error": str(e)}

    async def _fill_alt_text(self, page: Page, alt_text: str):
        # Try to open More options
        try:
            more_sel = await fallback_heal(page, "more_options")
            if more_sel:
                loc = page.locator(more_sel).last
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click(timeout=2000)
                    await asyncio.sleep(1)
        except Exception:
            pass

        locators = [
            'textarea[id*="alt" i]',
            'textarea[placeholder*="alt" i]',
            'textarea[aria-label*="alt" i]',
            'input[placeholder*="alt" i]',
        ]
        for sel in locators:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.fill(alt_text[:499])
                    self.info("Alt text filled")
                    return True
            except Exception:
                continue
        return False

    async def _select_board(self, page: Page, board_name: str) -> bool:
        from backend.scripts.pinterest_batch_core import select_board

        handle = self.account_handle or "default"
        return await select_board(page, board_name, f"driver-{handle}")

    async def _click_publish(self, page: Page) -> bool:
        """Find and click the publish button with extreme prejudice."""
        self.info("Aggressive publish: ensuring live post...")
        try:
            # 0. Debug screenshot before publish
            try:
                await page.screenshot(path=str(DATA_DIR / f"debug_publish_before_{int(time.time())}.png"))
            except:
                pass

            # 1. Dismiss potential blockers
            try:
                for blocker in ["Got it", "Done", "Entendido", "Listo", "Aceptar", "Close", "Cerrar"]:
                    btn = page.get_by_text(blocker).first
                    if await btn.count() > 0 and await btn.is_visible(timeout=300):
                        await btn.click(force=True)
                        self.info(f"Dismissed blocker: {blocker}")
                        await asyncio.sleep(0.5)
            except:
                pass

            # 2. Reveal UI — scroll all the way down + intermediate
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.5)

            # 3. Broad publish selectors — covers EN, ES, IT, FR, PT, DE
            publish_selectors = [
                # English
                'button:has-text("Publish")',
                'button:has-text("Publish now")',
                'button:has-text("Save")',
                # Spanish
                'button:has-text("Publicar")',
                'button:has-text("Publicar ahora")',
                'button:has-text("Subir")',
                'button:has-text("Guardar")',
                # Other common
                'button:has-text("Publier")',
                'button:has-text("Veröffentlichen")',
                'button:has-text("Pubblicare")',
                # Data attributes
                '[data-test-id="storyboard-creation-nav-done"]',
                '[data-test-id="publish-button"]',
                '[data-test-id="save-button"]',
                '[data-test-id="save"]',
                # Generic footer — any primary button at the bottom
                'div[data-test-id*="footer"] button[type="button"]',
                'div[data-test-id*="footer"] button:not([aria-label])',
                # Role-based
                '[role="button"][aria-label*="Publish" i]',
                '[role="button"][aria-label*="Publicar" i]',
                '[role="button"][aria-label*="Save" i]',
                '[role="button"][aria-label*="Guardar" i]',
            ]

            for sel in publish_selectors:
                try:
                    btn = page.locator(sel).first
                    if await btn.count() > 0 and await btn.is_visible(timeout=500):
                        text = (await btn.inner_text()).lower() if await btn.inner_text() else ""
                        self.info(f"Checking selector: {sel} — text={text!r}")
                        # Skip any button that looks like draft/help/footer navigation
                        _skip_words = [
                            "save draft",
                            "guardar borrador",
                            "save as draft",
                            "how to create pins",
                            "create pins",
                            "help",
                            "learn",
                            "support",
                            "feedback",
                            "contact",
                            "privacy",
                            "terms",
                            "cookie",
                            "log out",
                            "cerrar sesión",
                            "sign up",
                            "regístrate",
                        ]
                        if any(w in text for w in _skip_words):
                            self.info(f"Skipping non-publish button: {sel} ({text!r})")
                            continue
                        self.info(f"Clicking REAL publish button: {sel}")
                        await btn.click(force=True)
                        await asyncio.sleep(2)
                        if "/pin/" in page.url or await self._page_has_publish_success(page):
                            return True
                except:
                    continue

            # 4. JS targeted publish — only click buttons with publish-related text
            self.info("Trying JS targeted publish fallback...")
            js_result = await page.evaluate("""() => {
                const targets = [
                    'publish', 'publicar', 'save', 'guardar',
                    'subir', 'upload', 'compartir', 'share',
                    'publier', 'veröffentlichen', 'pubblicare',
                    'publicar ahora', 'publish now',
                ];
                // Words that disqualify a button from being the publish action
                const skipWords = [
                    'draft', 'borrador', 'help', 'learn', 'support',
                    'feedback', 'contact', 'privacy', 'terms', 'cookie',
                    'log out', 'sign up', 'create pins', 'how to',
                    'cerrar', 'regístrate',
                ];
                const btns = Array.from(document.querySelectorAll(
                    'button, [role="button"], button[type="submit"], input[type="submit"]'
                )).filter(el => {
                    const t = (el.innerText || el.textContent || el.value || '').toLowerCase().trim();
                    if (skipWords.some(w => t.includes(w))) return false;
                    return targets.some(target => t.includes(target));
                });
                if (btns.length > 0) {
                    btns[btns.length - 1].click();
                    return 'clicked_' + btns.length;
                }
                return 'no_button_found';
            }""")
            self.info(f"JS targeted publish result: {js_result}")

            await asyncio.sleep(5)

            # 5. Final check — only /pin/ URL or explicit success toast counts
            if "/pin/" in page.url or await self._page_has_publish_success(page):
                return True

            # Debug screenshot after failure
            try:
                await page.screenshot(path=str(DATA_DIR / f"debug_publish_fail_{int(time.time())}.png"))
            except:
                pass
            return False

        except Exception as e:
            self.error(f"Error in aggressive publish: {e}")
            return False

    async def _page_has_publish_success(self, page: Page) -> bool:
        try:
            success = page.get_by_text(
                re.compile(
                    r"your pin has been published|pin has been published"
                    r"|pin published|pin guardado|publicado con éxito"
                    r"|se ha publicado|pin saved",
                    re.I,
                )
            ).first
            if await success.count() > 0 and await success.is_visible(timeout=500):
                return True
            # Check for success modal with View/Ver button
            view_btn = page.get_by_text(re.compile(r"^(View|Ver|See it)$", re.I)).first
            if await view_btn.count() > 0 and await view_btn.is_visible(timeout=300):
                return True
            return False
        except Exception:
            return False

    async def _dismiss_publish_success_overlays(self, page: Page) -> None:
        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
        except Exception:
            pass
        try:
            await page.evaluate(
                """() => {
                    const needles = [
                        'install the pinterest browser extension',
                        'find it. love it. save it.',
                        'install now'
                    ];
                    for (const el of Array.from(document.querySelectorAll('[role="dialog"], [aria-modal="true"], div'))) {
                        const text = (el.innerText || el.textContent || '').toLowerCase();
                        if (needles.some((needle) => text.includes(needle))) {
                            el.style.display = 'none';
                            el.setAttribute('aria-hidden', 'true');
                        }
                    }
                }"""
            )
        except Exception:
            pass

    async def _extract_pin_from_page(self, page: Page) -> str | None:
        try:
            # 1. Check current URL (most reliable if page navigated)
            current_url = page.url
            pin_match = re.search(r"/pin/(\d+)", current_url)
            if pin_match:
                return pin_match.group(1)

            try:
                if await self._page_has_publish_success(page):
                    await self._dismiss_publish_success_overlays(page)
                    view_btn = page.get_by_role("button", name=re.compile(r"^(View|Ver)$", re.I)).first
                    if await view_btn.count() > 0 and await view_btn.is_visible(timeout=500):
                        await view_btn.click(force=True)
                        await page.wait_for_load_state("domcontentloaded", timeout=10000)
                        await asyncio.sleep(2)
                        pin_match = re.search(r"/pin/(\d+)", page.url)
                        if pin_match:
                            return pin_match.group(1)
            except Exception:
                pass

            # 2. Check window.__PINTEREST_DATA__ and links via JS
            extracted = await page.evaluate("""
                () => {
                    // Try to find in Pinterest's internal data object
                    if (window.__PINTEREST_DATA__) {
                        const data = window.__PINTEREST_DATA__;
                        if (data && data.resourceResponses) {
                            for (const resp of data.resourceResponses) {
                                if (resp.response && resp.response.data && resp.response.data.id) {
                                    return resp.response.data.id;
                                }
                            }
                        }
                    }

                    // Try to find any pin link on the page (usually in toast or success modal)
                    const links = Array.from(document.querySelectorAll('a[href*="/pin/"]'));
                    for (const link of links) {
                        const href = link.getAttribute('href');
                        const match = href.match(/\\/pin\\/(\\d+)/);
                        if (match) return match[1];
                    }

                    // Try to find in meta tags (if viewing the pin directly)
                    const ogUrl = document.querySelector('meta[property="og:url"]');
                    if (ogUrl) {
                        const match = ogUrl.getAttribute('content').match(/\\/pin\\/(\\d+)/);
                        if (match) return match[1];
                    }

                    return null;
                }
            """)
            if extracted:
                return str(extracted)

            # 3. Last resort: wait a bit and check URL again
            await asyncio.sleep(3)
            current_url = page.url
            pin_match = re.search(r"/pin/(\d+)", current_url)
            if pin_match:
                return pin_match.group(1)

        except Exception as e:
            logger.debug(f"Page extraction failed: {e}")
        return None

    def _public_username(self, account_handle: str | None) -> str:
        raw = os.environ.get("PINTEREST_PUBLIC_USERNAME_MAP", "").strip()
        if raw:
            try:
                mapping = json.loads(raw)
            except (TypeError, ValueError):
                mapping = {}
            if isinstance(mapping, dict):
                username = str(mapping.get(account_handle or "", "")).strip()
                if username:
                    return username

        creds = self.config.accounts.get(account_handle or "")
        if creds and creds.email:
            return creds.email.partition("@")[0].strip()
        return ""

    def _candidate_verification_details(self):
        diagnostic = getattr(self, "_pin_candidate_verification", None)
        if isinstance(diagnostic, dict) and diagnostic.get("candidate_present") is True:
            return {"candidate_verification": dict(diagnostic)}
        return {}

    async def _verify_intercepted_public_pin(
        self,
        page: Page,
        *,
        title: str,
        link: str,
        account_handle: str | None,
        candidate_id: object = None,
        description: str = "",
    ) -> str | None:
        """Require the candidate to be public with this title and destination."""
        creation_data = self._pin_create_data
        candidate = str(candidate_id or creation_data.get("pin_id") or "")
        valid_candidate = bool(re.fullmatch(r"\d{15,22}", candidate))
        diagnostic = {"candidate_present": valid_candidate, "reason": "checking"}
        if valid_candidate:
            diagnostic["candidate_id"] = candidate
        self._pin_candidate_verification = diagnostic

        def finish(reason, verified=False, **details):
            diagnostic.update(reason=reason, **details)
            if valid_candidate:
                self.info(f"Public candidate verification: {json.dumps(diagnostic, sort_keys=True)}")
            return candidate if verified else None

        username = self._public_username(account_handle)
        if not valid_candidate:
            return finish("candidate_missing")
        if not re.fullmatch(r"[A-Za-z0-9_]+", username):
            return finish("public_username_unavailable")
        if not title or not link:
            return finish("expected_metadata_missing")
        candidate_event = self._pin_create_event
        started_at, observed_at = (
            creation_data.get("generation_started_at"),
            creation_data.get("observed_at"),
        )

        def fresh_create_window():
            return (
                str(creation_data.get("pin_id")) == candidate
                and type(started_at) in (int, float)
                and type(observed_at) in (int, float)
                and math.isfinite(started_at)
                and math.isfinite(observed_at)
                and started_at <= observed_at <= time.time() + 5
                and time.time() - observed_at <= 600
            )

        try:
            async with asyncio.timeout(35):
                response = await page.context.request.get(
                    f"https://www.pinterest.com/pin/{candidate}/",
                    timeout=30000,
                    fail_on_status_code=False,
                )
                diagnostic["http_status"] = response.status if type(response.status) is int else None
                if response.status != 200:
                    return finish("public_http_status")
                if _public_pin_url_id(response.url) != candidate:
                    return finish("public_response_id_mismatch")
                metadata = _PublishedPinMetadata()
                metadata.feed(await response.text())
                metadata.close()
                anonymous_variant = False
                # The authenticated API context can receive Pinterest's CSR
                # shell with no public ownership tags. A separate, cookieless
                # read must independently satisfy the same publication gates.
                if (
                    not metadata.ambiguous
                    and metadata.exact("pinterestapp:source") is None
                    and metadata.exact("pinterestapp:pinner") is None
                ):
                    if not fresh_create_window():
                        return finish("fresh_create_window_unavailable")
                    diagnostic["anonymous_fallback_attempted"] = True
                    public_body = await _anonymous_public_document(
                        f"https://www.pinterest.com/pin/{candidate}/"
                    )
                    if public_body is None:
                        return finish("anonymous_public_document_unavailable")
                    metadata = _PublishedPinMetadata()
                    metadata.feed(public_body)
                    metadata.close()
                    anonymous_variant = True
                diagnostic["public_response_variant"] = "anonymous" if anonymous_variant else "session"
                if (
                    self._pin_create_event is not candidate_event
                    or self._pin_create_data is not creation_data
                ):
                    return finish("stale_interception")

                def normalize(value):
                    return unicodedata.normalize("NFC", " ".join(value.split())).casefold()

                public_title = metadata.exact("og:title")
                pinner = _pinterest_public_url(metadata.exact("pinterestapp:pinner"))
                pinner_name = re.fullmatch(r"/([^/]+)/?", pinner.path) if pinner else None
                checks = {
                    "og_id_matches": _public_pin_url_id(metadata.exact("og:url")) == candidate,
                    "canonical_id_matches": _public_pin_url_id(metadata.exact("canonical")) == candidate,
                    "title_matches": isinstance(public_title, str)
                    and normalize(public_title) == normalize(title[:100]),
                    "source_matches": metadata.exact("pinterestapp:source") == link,
                    "pinner_matches": pinner_name is not None
                    and pinner_name.group(1).casefold() == username.casefold(),
                }
                diagnostic.update(metadata_checks=checks, streamed_metadata=metadata.streamed)
                if all(checks.values()):
                    return finish("verified", verified=True, method="public-metadata")
                if not checks["source_matches"] or not checks["pinner_matches"]:
                    return finish("public_owner_or_source_mismatch")
                if not fresh_create_window():
                    return finish("fresh_create_window_unavailable")
                diagnostic["create_window"] = {
                    "started_at": started_at,
                    "observed_at": observed_at,
                }
                if anonymous_variant:
                    rss_body = await _anonymous_public_document(
                        f"https://www.pinterest.com/{username}/feed.rss", max_bytes=2_000_000
                    )
                    if rss_body is None:
                        return finish("owned_rss_unavailable")
                else:
                    feed = await page.context.request.get(
                        f"https://www.pinterest.com/{username}/feed.rss",
                        timeout=15000,
                        fail_on_status_code=False,
                    )
                    feed_url = _pinterest_public_url(feed.url)
                    if (
                        feed.status != 200
                        or feed_url is None
                        or feed_url.path.casefold() != f"/{username}/feed.rss".casefold()
                    ):
                        return finish("owned_rss_unavailable")
                    rss_body = await feed.text()
                if (
                    self._pin_create_event is not candidate_event
                    or self._pin_create_data is not creation_data
                ):
                    return finish("stale_interception")
                if len(rss_body) > 2_000_000:
                    return finish("rss_receipt_too_large")
                verified, receipt_checks = _rss_candidate_receipt(
                    rss_body, candidate, title, description, started_at, observed_at
                )
                return finish(
                    "verified" if verified else "rss_receipt_unverified",
                    verified=verified,
                    method="rss-create-receipt",
                    receipt_checks=receipt_checks,
                )
        except Exception as exc:
            # A failed or unavailable public fetch cannot become publication
            # proof or fall back to another pin with the same title/link.
            return finish("public_fetch_unavailable", error_type=type(exc).__name__[:64])

    async def _verify_recent_public_pin(
        self,
        page: Page,
        *,
        title: str,
        link: str,
        account_handle: str | None,
    ) -> str | None:
        """Verify an uncertain publish against the account's public recent pins."""
        username = self._public_username(account_handle)
        if not username or not title or not link:
            return None

        try:
            profile_response = await page.context.request.get(
                f"https://www.pinterest.com/{username}/",
                timeout=30000,
                fail_on_status_code=False,
            )
            if profile_response.status != 200:
                return None
            profile_html = (await profile_response.text()).replace("\\/", "/")
            title_pos = profile_html.casefold().find(title.casefold())
            if title_pos < 0:
                return None

            window = profile_html[max(0, title_pos - 5000) : title_pos + 5000]
            candidates = list(dict.fromkeys(re.findall(r"/pin/(?:[^/\"<]*--)?(\d{10,})", window, flags=re.I)))
            for pin_id in candidates[:5]:
                pin_response = await page.context.request.get(
                    f"https://www.pinterest.com/pin/{pin_id}/",
                    timeout=30000,
                    fail_on_status_code=False,
                )
                if pin_response.status != 200:
                    continue
                pin_html = (await pin_response.text()).replace("\\/", "/")
                if title.casefold() in pin_html.casefold() and link in pin_html:
                    self.info(f"Verified recent public pin after API timeout: {pin_id}")
                    return pin_id
        except Exception as exc:
            self.debug(f"Recent public pin verification failed: {exc}")
        return None

"""
RankStein Pinterest Automation — Unified Pinterest Driver
High-level abstraction over Playwright with self-healing, retries, and health tracking.
"""

import asyncio
import contextlib
import json
import logging
import os
import re
import time
from collections.abc import Callable
from pathlib import Path

from playwright.async_api import Page, Response
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .circuit_breaker import CircuitBreakerOpenError, get_circuit_breaker
from .config import DATA_DIR, get_config, resolve_account_board_name
from .mcp_bridge import publish_pin_agentic, publish_pin_direct_mcp
from .rate_limiter import get_rate_limiter
from .self_healing import fallback_heal, robust_fill
from .session_pool import SessionInfo, get_session_pool

logger = logging.getLogger("rankstein.driver")


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
        self._pin_create_data = {"pin_id": None, "pin_url": None}
        self._pin_create_event = asyncio.Event()

        async def _on_response(response: Response):
            if response.request.method != "POST":
                return
            url = response.url.lower()
            if not any(
                p in url
                for p in ["/v3/pins", "pinresource/create", "pin-builder", "/resource/pin", "graphql"]
            ):
                return
            if "graphql" in url:
                post_data = (response.request.post_data or "").lower()
                if not any(
                    marker in post_data
                    for marker in (
                        "pinresourcecreate",
                        "createpin",
                        "pin_create",
                        "pinbuilder",
                        "storyboard",
                        "story_pin",
                        "pin",
                        "creation",
                    )
                ):
                    return
            try:
                data = await response.json()

                # Recursive search for a Pin ID (18-19 digit string or integer)
                import re

                def find_pin_id(obj):
                    if isinstance(obj, dict):
                        if "id" in obj:
                            val = str(obj["id"])
                            if re.match(r"^\d{17,20}$", val):
                                return val
                        for k, v in obj.items():
                            res = find_pin_id(v)
                            if res:
                                return res
                    elif isinstance(obj, list):
                        for item in obj:
                            res = find_pin_id(item)
                            if res:
                                return res
                    return None

                pin_id = find_pin_id(data)
                if pin_id:
                    self._pin_create_data["pin_id"] = str(pin_id)
                    self._pin_create_data["pin_url"] = f"https://www.pinterest.com/pin/{pin_id}/"
                    self._pin_create_event.set()
                    self.info(f"Intercepted pin creation: {pin_id}")
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

    async def ensure_logged_in(self, account_handle: str | None = None) -> bool:
        if not self.circuit.can_execute("pinterest_login"):
            raise CircuitBreakerOpenError("Pinterest login circuit is OPEN")

        handle = account_handle or self.account_handle
        session = await self._acquire_session(handle)
        page = session.page

        try:
            # ── Phase 1: Lightweight check (no navigation) ──
            # If we're already on the pin creation page, we're good.
            current_url = page.url.lower()
            if "pin-creation-tool" in current_url or "pin-builder" in current_url:
                self.info(f"Already on creation tool — logged in as {handle or 'default'}")
                self.circuit.record_success("pinterest_login")
                return True

            # Check auth cookies — if present, session should be valid
            has_cookies = await self._has_auth_cookies(session.context)
            if has_cookies and not await self._is_login_page(page):
                # Have cookies and not on login page — navigate to pin-creation-tool
                self.info(f"Auth cookies present, navigating to creation tool for {handle or 'default'}...")
                await page.goto(
                    "https://www.pinterest.com/pin-creation-tool/",
                    timeout=self.config.browser.navigation_timeout_ms,
                    wait_until="domcontentloaded",
                )
                await asyncio.sleep(2)
                if "pin-creation-tool" in page.url or "pin-builder" in page.url:
                    self.info(f"Already logged in and ready as {handle or 'default'}")
                    self.circuit.record_success("pinterest_login")
                    return True
                if not await self._is_login_page(page):
                    # Weird landing page — try one more navigation
                    await page.goto("https://www.pinterest.com/pin-creation-tool/", timeout=30000)
                    await asyncio.sleep(2)
                    if "pin-creation-tool" in page.url or "pin-builder" in page.url:
                        return True

            # ── Phase 2: Full login flow ──
            self.info(
                f"Session invalid for creation tool, attempting Pinterest login for {handle or 'default'}..."
            )
            if not await self._is_login_page(page):
                await page.goto(
                    "https://www.pinterest.com/login/", timeout=self.config.browser.navigation_timeout_ms
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
                self.circuit.record_failure("pinterest_login")
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
                    self.circuit.record_failure("pinterest_login")
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
                self.circuit.record_success("pinterest_login")
                return True
            else:
                # Check if a 2FA / security challenge page appeared
                self.error(f"Login failed for {email}, current URL: {page.url}")
                await self._save_debug_artifact(page, "login_fail")
                self.circuit.record_failure("pinterest_login", retryable=False)
                return False

        except Exception as e:
            self.error(f"Login error: {e}")
            self.circuit.record_failure("pinterest_login")
            session.failure_count += 1
            return False

    async def _clear_draft_limit_if_needed(self, page: Page, max_delete: int = 50) -> int:
        """Purge drafts when Pinterest creator is blocked by drafts or reaches limit.

        Uses select-all bulk deletion first, falling back to individual draft cleanup.
        """
        try:
            from scripts.ops.clear_pinterest_drafts import clear_drafts_for_page

            deleted = await clear_drafts_for_page(page, account_name=self.account_handle or "driver")
            if deleted > 0:
                self.info(f"Successfully purged {deleted} draft(s) using bulk purge engine.")
                return deleted
        except Exception as purge_err:
            self.warning(
                f"Bulk draft purge engine encountered error: {purge_err}; attempting direct DOM purge."
            )

        try:
            body_text = await page.locator("body").inner_text(timeout=3000)
        except Exception:
            body_text = ""

        draft_count_match = re.search(r"(?:Pin drafts|Drafts|Borradores)\s*\((\d+)\)", body_text, re.I)
        draft_count = int(draft_count_match.group(1)) if draft_count_match else None
        at_draft_limit = (
            (draft_count is not None and draft_count > 0)
            or "50 drafts" in body_text
            or ("limit" in body_text.lower() and "draft" in body_text.lower())
        )
        if not at_draft_limit:
            return 0

        self.warning("Pinterest creator has pending drafts; purging drafts to unlock upload.")

        # Try bulk select first
        try:
            bulk = page.locator(
                '[data-test-id="bulk-select-drafts-checkbox"], input[type="checkbox"][aria-label*="Select all" i], button:has-text("Select all")'
            ).first
            if await bulk.count() > 0 and await bulk.is_visible(timeout=1000):
                await bulk.click(force=True)
                await page.wait_for_timeout(1000)
                delete_btn = page.locator(
                    '[data-test-id="bulk-delete-drafts-button"], button:has-text("Delete"), button:has-text("Eliminar")'
                ).first
                if await delete_btn.count() > 0 and await delete_btn.is_visible(timeout=1500):
                    await delete_btn.click(force=True)
                    await page.wait_for_timeout(1000)
                    confirm_btn = page.locator(
                        'div[role="dialog"] button:has-text("Delete"), div[role="dialog"] button:has-text("Eliminar")'
                    ).first
                    if await confirm_btn.count() > 0 and await confirm_btn.is_visible(timeout=2000):
                        await confirm_btn.click(force=True)
                        await page.wait_for_timeout(3000)
                        self.info("Bulk deleted all drafts via modal confirm.")
                        return 1
                    else:
                        await page.keyboard.press("Enter")
                        return 1
        except Exception as b_err:
            self.warning(f"Direct bulk select failed: {b_err}")

        # Fallback to single actions
        deleted = 0
        for _ in range(min(max_delete, 10)):
            try:
                actions = page.locator(
                    'button[aria-label*="Pin draft actions" i], [data-test-id="draft-actions-button"]'
                )
                if await actions.count() == 0:
                    break
                await actions.first.click(force=True)
                await page.wait_for_timeout(500)

                delete_action = page.locator(
                    '[data-test-id="delete-draft-action"], button:has-text("Delete")'
                ).first
                await delete_action.wait_for(state="visible", timeout=3000)
                await delete_action.click(force=True)
                await page.wait_for_timeout(500)

                confirm = page.locator('button:has-text("Delete"), button:has-text("Eliminar")').last
                await confirm.wait_for(state="visible", timeout=3000)
                await confirm.click(force=True)
                deleted += 1
                await page.wait_for_timeout(1500)
            except Exception as delete_err:
                self.warning(f"Pinterest draft cleanup stopped after {deleted} deletion(s): {delete_err}")
                break
        return deleted

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
        rate_operation = f"{operation}:{domain_handle or 'direct'}:{handle or 'unknown'}"
        limiter = get_rate_limiter(domain_handle=domain_handle)
        board_name = resolve_account_board_name(
            board_name or self.config.default_board,
            handle,
        )
        if not self.circuit.can_execute(operation):
            raise CircuitBreakerOpenError(f"Circuit '{operation}' is OPEN")

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
        )

        try:
            from backend.scripts.pinterest_batch_core import create_pin_from_fields

            self.info("Using shared Pinterest uploader core...")
            shared_task = asyncio.create_task(
                create_pin_from_fields(
                    page,
                    local,
                    title,
                    link,
                    description,
                    board_name,
                    f"driver-{handle or 'default'}",
                )
            )
            response_task = asyncio.create_task(self._pin_create_event.wait())
            try:
                done, _ = await asyncio.wait(
                    {shared_task, response_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if response_task in done and self._pin_create_data.get("pin_id"):
                    pin_id = self._pin_create_data["pin_id"]
                else:
                    pin_id = await shared_task
            finally:
                # The supervisor wraps create_pin in wait_for(). If that outer
                # timeout cancels us while both children are pending, neither
                # child may outlive the page/session that it is operating on.
                # Drain completed exceptions as well so cleanup never masks the
                # primary result, exception, or cancellation.
                for task in (shared_task, response_task):
                    if not task.done():
                        task.cancel()
                for task in (shared_task, response_task):
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task
            if pin_id:
                limiter.record_execution(rate_operation)
                self.circuit.record_success(operation)
                return {
                    "success": True,
                    "pin_id": pin_id,
                    "pin_url": f"https://www.pinterest.com/pin/{pin_id}/",
                    "method": "shared-core",
                }
            self.warning("Shared Pinterest uploader returned no pin id; continuing with legacy fallback.")
        except BrowserSessionLost:
            raise
        except Exception as shared_exc:
            from backend.scripts.pinterest_batch_core import PinCreationError

            if isinstance(shared_exc, PinCreationError):
                msg = str(shared_exc)
                self.warning(f"Shared uploader aborted: {msg}.")
                if "publish clicked but no Pin ID" in msg:
                    pin_id = await self._verify_recent_public_pin(
                        page,
                        title=title,
                        link=link,
                        account_handle=handle,
                    )
                    if pin_id:
                        limiter.record_execution(rate_operation)
                        self.circuit.record_success(operation)
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

            if not pin_id:
                pin_id = await self._verify_recent_public_pin(
                    page,
                    title=title,
                    link=link,
                    account_handle=handle,
                )

            if pin_id:
                limiter.record_execution(rate_operation)
                self.circuit.record_success(operation)
                return {
                    "success": True,
                    "pin_id": pin_id,
                    "pin_url": f"https://www.pinterest.com/pin/{pin_id}/",
                }
            else:
                self.warning("Pin creation could not be verified; no pin id/url found")
                limiter.record_failure(rate_operation)
                self.circuit.record_failure(operation)
                session.failure_count += 1
                return {
                    "success": False,
                    "error": "Pin creation could not be verified; no pin_id or pin_url found",
                    "uncertain": True,
                }

        except Exception as e:
            self.error(f"Manual Pin creation failed: {e}")
            if not MCP_FALLBACK_ENABLED:
                limiter.record_failure(rate_operation)
                self.circuit.record_failure(operation)
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
                    self.circuit.record_success(operation)
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
                    self.circuit.record_success(operation)
                    pin_url = agent_res["pin_url"]
                    pin_id = pin_url.split("/pin/")[-1].strip("/")
                    return {"success": True, "pin_id": pin_id, "pin_url": pin_url, "method": "agentic"}
                else:
                    self.error(f"Agentic fallback also failed: {agent_res.get('error')}")
            except Exception as agent_e:
                self.error(f"Agentic fallback crashed: {agent_e}")

            limiter.record_failure(rate_operation)
            self.circuit.record_failure(operation)
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
        rate_operation = f"{operation}:{domain_handle or 'direct'}:{handle or 'unknown'}"
        limiter = get_rate_limiter(domain_handle=domain_handle)
        board_name = resolve_account_board_name(
            board_name or self.config.default_board,
            handle,
        )
        if not self.circuit.can_execute(operation):
            raise CircuitBreakerOpenError(f"Circuit '{operation}' is OPEN")
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
                self.circuit.record_success(operation)
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
            self.circuit.record_failure(operation)
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

"""
RankStein Pinterest Automation — Unified Pinterest Driver
High-level abstraction over Playwright with self-healing, retries, and health tracking.
"""

import asyncio
import logging
import os
import re
import time
from collections.abc import Callable
from pathlib import Path

from playwright.async_api import Page, Response, TimeoutError as PlaywrightTimeoutError

from .circuit_breaker import CircuitBreakerOpenError, get_circuit_breaker
from .config import DATA_DIR, get_config
from .mcp_bridge import publish_pin_agentic, publish_pin_direct_mcp
from .rate_limiter import get_rate_limiter
from .self_healing import fallback_heal, gemini_heal_selector, robust_fill
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

    async def close(self):
        if self._session:
            await self.pool.release(self._session, healthy=True)
            self._session = None

    # ── Response interception ──────────────────────────────

    def _setup_pin_interception(self, page: Page):
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

    async def ensure_logged_in(self, account_handle: str | None = None) -> bool:
        if not self.circuit.can_execute("pinterest_login"):
            raise CircuitBreakerOpenError("Pinterest login circuit is OPEN")

        handle = account_handle or self.account_handle
        session = await self._acquire_session(handle)
        page = session.page

        try:
            # Check current state
            await page.goto("https://www.pinterest.com/", timeout=self.config.browser.navigation_timeout_ms)
            await page.wait_for_load_state("domcontentloaded", timeout=10000)

            if await page.query_selector('[data-test-id="header-avatar"], [data-test-id="header-profile"]'):
                self.info(f"Already logged in as {handle or 'default'}")
                self.circuit.record_success("pinterest_login")
                return True

            # Need to login
            self.info(f"Attempting Pinterest login for {handle or 'default'}...")
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

            # Find and fill email
            self.info(f"Looking for email/password fields for {email}...")
            email_sel = (
                'input[name="id"]' if await page.query_selector('input[name="id"]') else 'input[type="email"]'
            )
            self.info(f"Using email selector: {email_sel}")
            await page.fill(email_sel, email)
            await page.wait_for_timeout(1000)

            # Find and fill password
            pwd_sel = (
                'input[name="password"]'
                if await page.query_selector('input[name="password"]')
                else 'input[type="password"]'
            )
            self.info(f"Using password selector: {pwd_sel}")
            await page.fill(pwd_sel, password)
            await page.wait_for_timeout(1000)

            # Submit
            self.info("Submitting login form...")
            try:
                await page.click('button[type="submit"]')
            except Exception:
                self.warning("Submit button click failed, using Enter key")
                await page.keyboard.press("Enter")

            await page.wait_for_timeout(15000)

            logged_in = "login" not in page.url and "pinterest.com" in page.url
            if logged_in:
                self.info("Login successful")
                self.circuit.record_success("pinterest_login")
                return True
            else:
                self.error(f"Login failed for {email}, current URL: {page.url}")
                try:
                    await page.screenshot(path=str(DATA_DIR / f"debug_login_fail_{int(time.time())}.png"))
                    self.info("Saved failure screenshot to data/")
                except:
                    pass
                self.circuit.record_failure("pinterest_login", retryable=False)
                return False

        except Exception as e:
            self.error(f"Login error: {e}")
            self.circuit.record_failure("pinterest_login")
            session.failure_count += 1
            return False

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
    ) -> dict:
        """
        Create a Pinterest pin with full self-healing and retry logic.
        Returns: {success, pin_id, pin_url, error}
        """
        operation = "pin_upload"
        if not self.circuit.can_execute(operation):
            raise CircuitBreakerOpenError(f"Circuit '{operation}' is OPEN")

        if not self.rate_limiter.can_execute(operation):
            return {"success": False, "error": "Rate limit exceeded"}

        handle = account_handle or self.account_handle
        session = await self._acquire_session(handle)
        page = session.page

        local = Path(image_path)
        if not local.exists():
            return {"success": False, "error": f"Image not found: {image_path}"}

        try:
            from backend.scripts.pinterest_batch_core import create_pin_from_fields

            self.info("Using shared Pinterest uploader core...")
            pin_id = await create_pin_from_fields(
                page,
                local,
                title,
                link,
                description,
                board_name or self.config.default_board,
                f"driver-{handle or 'default'}",
            )
            if pin_id:
                self.rate_limiter.record_execution(operation)
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
                self.warning(f"Shared uploader aborted: {msg}")
                if "board selection failed" in msg:
                    self.circuit.record_failure(operation, retryable=False)
                return {"success": False, "error": msg}
            self.warning(f"Shared Pinterest uploader failed before legacy fallback: {shared_exc}")

        try:
            # Setup API interception
            self._setup_pin_interception(page)

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

            if pin_id:
                self.rate_limiter.record_execution(operation)
                self.circuit.record_success(operation)
                return {
                    "success": True,
                    "pin_id": pin_id,
                    "pin_url": f"https://www.pinterest.com/pin/{pin_id}/",
                }
            else:
                self.warning("Pin creation could not be verified; no pin id/url found")
                self.rate_limiter.record_failure(operation)
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
                self.rate_limiter.record_failure(operation)
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
                    self.rate_limiter.record_execution(operation)
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
                    self.rate_limiter.record_execution(operation)
                    self.circuit.record_success(operation)
                    pin_url = agent_res["pin_url"]
                    pin_id = pin_url.split("/pin/")[-1].strip("/")
                    return {"success": True, "pin_id": pin_id, "pin_url": pin_url, "method": "agentic"}
                else:
                    self.error(f"Agentic fallback also failed: {agent_res.get('error')}")
            except Exception as agent_e:
                self.error(f"Agentic fallback crashed: {agent_e}")

            self.rate_limiter.record_failure(operation)
            self.circuit.record_failure(operation)
            session.failure_count += 1
            return {"success": False, "error": str(e)[:500]}

    # ── Pin Saving (Repin) ─────────────────────────────────

    async def save_pin(
        self,
        pin_url: str,
        board_name: str = "",
        account_handle: str | None = None,
    ) -> dict:
        """
        Save (repin) an existing pin to a board.
        Returns: {success, pin_id, error}
        """
        operation = "pin_save"
        if not self.circuit.can_execute(operation):
            raise CircuitBreakerOpenError(f"Circuit '{operation}' is OPEN")

        handle = account_handle or self.account_handle
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
                    await page.goto(pin_url, timeout=60000 if attempt == 0 else 30000, wait_until="domcontentloaded")
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
                self.rate_limiter.record_execution(operation)
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
                    await loc.click()
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
        # Handle dict being passed (bug prevention)
        if isinstance(board_name, dict):
            self.warning(f"Board name passed as dict, attempting to resolve: {board_name}")
            board_name = board_name.get("_default", "Aperitivos")
            self.info(f"Resolved board name to: {board_name}")

        try:
            from backend.scripts.pinterest_batch_core import select_board

            if await select_board(page, board_name, f"driver-{self.account_handle or 'default'}"):
                return True
        except Exception as shared_exc:
            self.warning(f"Shared board selector failed before legacy fallback: {shared_exc}")

        try:

            async def click_board_option(target_board: str) -> bool:
                option_selectors = [
                    f'[data-test-id^="board-row-"]:has-text("{target_board}")',
                    f'[data-test-id="boardWithoutSection"]:has-text("{target_board}")',
                    f'[role="listitem"]:has-text("{target_board}")',
                    f'div[role="option"]:has-text("{target_board}")',
                    f'[data-test-id*="board"]:has-text("{target_board}")',
                ]
                for sel in option_selectors:
                    option = page.locator(sel).first
                    if await option.count() > 0 and await option.is_visible():
                        self.info(f"Clicking board option: {sel}")
                        await option.click(force=True)
                        await asyncio.sleep(1)
                        return True
                return False

            # Combined selector for the dropdown button
            selectors = [
                '[data-test-id="board-dropdown-select-button"]',
                '[aria-label*="Choose a board" i]',
                '[aria-label*="Select board" i]',
                'div[role="button"]:has-text("Choose a board")',
                'div[role="button"]:has-text("Selecciona un tablero")',
            ]
            board_btn = None
            for sel in selectors:
                loc = page.locator(sel).first
                if await loc.count() > 0 and await loc.is_visible():
                    board_btn = loc
                    break

            if board_btn:
                self.info(
                    f"Clicking board dropdown button: {await board_btn.get_attribute('aria-label') or 'no label'}"
                )
                await board_btn.click(force=True)
                await asyncio.sleep(2)

                if await click_board_option(board_name):
                    return True

                # Check if search input appeared
                search_selectors = [
                    'input[placeholder*="search" i]',
                    'input[placeholder*="buscar" i]',
                    'input[aria-label*="search" i]',
                ]

                search_input = None
                for sel in search_selectors:
                    loc = page.locator(sel).first
                    if await loc.count() > 0 and await loc.is_visible():
                        search_input = loc
                        break

                if search_input:
                    self.info(f"Typing board name '{board_name}' into search...")
                    await search_input.fill(board_name)
                    await asyncio.sleep(2)
                else:
                    self.warning("Search input not found, trying direct typing...")
                    await page.keyboard.type(board_name, delay=30)
                    await asyncio.sleep(2)

                # Select the best matching option
                # Look for board rows or options that contain the board name.
                # Pinterest currently renders rows as board-row-<name>, not a
                # fixed board-row test id, so use prefix selectors.
                if await click_board_option(board_name):
                    await asyncio.sleep(3)
                    return True

                board_sample = await page.evaluate(
                    """() => Array.from(document.querySelectorAll('[data-test-id^="board-row-"], [data-test-id="boardWithoutSection"], [role="listitem"], [role="option"]'))
                    .map((el) => (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' '))
                    .filter(Boolean)
                    .slice(0, 12)"""
                )
                self.warning(f"Board option not found for '{board_name}'. Visible boards: {board_sample}")
            else:
                self.warning("Board dropdown button not found.")
        except Exception as e:
            self.warning(f"Board selection failed: {e}")
        return False

    async def _click_publish(self, page: Page) -> bool:
        publish_sel = await fallback_heal(page, "publish")
        if publish_sel:
            try:
                btn = page.locator(publish_sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.wait_for(state="visible", timeout=10000)
                    await btn.click(force=True)
                    self.info("Publish clicked")
                    return True
            except Exception as e:
                self.warning(f"Publish click failed: {e}")

        # English-first generic selectors
        generics = [
            'button[data-test-id="board-dropdown-save-button"]',
            'button:has-text("Publish")',
            'button:has-text("Publicar")',
            'button:has-text("Save")',
        ]
        for sel in generics:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click(force=True)
                    self.info(f"Publish clicked via generic: {sel}")
                    return True
            except:
                continue

        # Fast fallback: Pinterest's creator accepts Ctrl+Enter even when the
        # visible publish button locator is obscured by drafts/sidebar UI.
        try:
            await page.keyboard.press("Control+Enter")
            self.info("Ctrl+Enter sent — waiting for page navigation or API confirmation...")
            # Wait up to 10s for the page to leave pin-creation-tool, OR for
            # the response interceptor to fire (set by _setup_pin_interception).
            confirmed = False
            pin_event = getattr(self, "_pin_create_event", None)
            for _ in range(20):
                await asyncio.sleep(0.5)
                if "pin-creation-tool" not in page.url:
                    confirmed = True
                    break
                if pin_event and pin_event.is_set():
                    confirmed = True
                    break
            if confirmed:
                self.info("Published via Ctrl+Enter (confirmed)")
                return True
            self.warning("Ctrl+Enter sent but no confirmation received within 10s")
        except Exception:
            pass

        if PUBLISH_LLM_HEALING_ENABLED:
            healed = await gemini_heal_selector(page, "the publish or save pin button")
            if healed:
                try:
                    btn = page.locator(healed).first
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click(force=True)
                        self.info("Publish clicked via self-healing")
                        return True
                except Exception:
                    pass

        return False

    async def _extract_pin_from_page(self, page: Page) -> str | None:
        try:
            # 1. Check current URL (most reliable if page navigated)
            current_url = page.url
            pin_match = re.search(r"/pin/(\d+)", current_url)
            if pin_match:
                return pin_match.group(1)

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

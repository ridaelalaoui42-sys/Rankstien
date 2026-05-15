"""
RankStein Pinterest Automation — Browser Session Pool
Manages multiple browser sessions with rotation, TTL, and automatic cleanup.
"""

import asyncio
import logging
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from playwright.async_api import BrowserContext, Page, async_playwright

from .browser_utils import (
    DEFAULT_BROWSER_MAP,
    kill_browser_locks,
    normalize_browser_type,
    user_agent_for_browser,
)
from .config import SESSION_DIR, get_config

logger = logging.getLogger("rankstein.session_pool")


@dataclass
class SessionInfo:
    context: BrowserContext
    page: Page
    playwright: any
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_used: datetime = field(default_factory=lambda: datetime.now(UTC))
    use_count: int = 0
    failure_count: int = 0
    session_id: str = ""
    account_handle: str | None = None
    browser_type: str = "firefox"
    closed: bool = False
    in_use: bool = False  # Track if worker is using this

    @property
    def age_minutes(self) -> float:
        return (datetime.now(UTC) - self.created_at).total_seconds() / 60

    @property
    def idle_minutes(self) -> float:
        return (datetime.now(UTC) - self.last_used).total_seconds() / 60


class SessionPool:
    """
    Managed pool of browser sessions for Pinterest automation.
    Supports session rotation, TTL expiry, and automatic cleanup.
    """

    def __init__(self):
        self.config = get_config()
        self._sessions: dict[str, SessionInfo] = {}
        self._session_counter = 0
        self._dict_lock = asyncio.Lock()
        self._granular_locks: dict[str, asyncio.Lock] = {}
        self._playwright = None

    def _get_lock(self, account_handle: str | None, board: str | None) -> asyncio.Lock:
        key = f"{account_handle or 'default'}_{board or 'default'}"
        if key not in self._granular_locks:
            self._granular_locks[key] = asyncio.Lock()
        return self._granular_locks[key]

    def _get_session_dir(self, session_id: str, account_handle: str | None = None) -> Path:
        session_name = self.config.browser.session_name
        if account_handle and account_handle in self.config.accounts:
            acc_session = self.config.accounts[account_handle].session_name
            if acc_session:
                session_name = acc_session
        return SESSION_DIR / f"{session_name}_{session_id}"

    async def _ensure_playwright(self):
        if self._playwright is None:
            self._playwright = await async_playwright().start()

    async def _close_session_detached(self, info: SessionInfo):
        info.closed = True
        try:
            await info.context.close()
            logger.info(f"Closed session {info.session_id}")
        except Exception as e:
            logger.warning(f"Error closing session {info.session_id}: {e}")

    async def acquire(self, account_handle: str | None = None, board: str | None = None) -> SessionInfo:
        """Get or create a healthy browser session for a specific account."""
        lock = self._get_lock(account_handle, board)
        async with lock:
            async with self._dict_lock:
                # Try to reuse an existing healthy session for this account
                for sid, info in list(self._sessions.items()):
                    if info.closed or info.in_use:
                        continue
                    if info.account_handle != account_handle:
                        continue
                    if info.failure_count >= 3:
                        logger.warning(f"Session {sid} has {info.failure_count} failures, retiring")
                        self._sessions.pop(sid, None)
                        asyncio.create_task(self._close_session_detached(info))
                        continue
                    if info.age_minutes > self.config.browser.session_ttl_minutes:
                        logger.info(f"Session {sid} TTL expired ({info.age_minutes:.0f}m), rotating")
                        self._sessions.pop(sid, None)
                        asyncio.create_task(self._close_session_detached(info))
                        continue

                    info.last_used = datetime.now(UTC)
                    info.use_count += 1
                    info.in_use = True
                    logger.info(
                        f"Acquired existing session {sid} for account {account_handle or 'default'} (uses={info.use_count})"
                    )
                    return info

                # Need to create new session
                await self._retire_idle_session_if_full()
            
            info = await self._create_session(account_handle)
            info.in_use = True
            return info

    async def _retire_idle_session_if_full(self) -> None:
        if len(self._sessions) < self.config.browser.max_sessions:
            return
        idle = sorted(
            (s for s in self._sessions.values() if not s.in_use),
            key=lambda s: (s.failure_count, s.last_used),
            reverse=True,
        )
        if idle:
            info = self._sessions.pop(idle[0].session_id, None)
            if info:
                asyncio.create_task(self._close_session_detached(info))

    async def _create_session(self, account_handle: str | None = None) -> SessionInfo:
        await self._ensure_playwright()

        async with self._dict_lock:
            self._session_counter += 1
            session_id = f"pool_{self._session_counter}"
        session_dir = self._get_session_dir(session_id, account_handle)

        # Determine browser type (chromium or firefox)
        browser_type = "firefox"
        session_name = self.config.browser.session_name
        if account_handle and account_handle in self.config.accounts:
            creds = self.config.accounts[account_handle]
            if creds.browser:
                browser_type = normalize_browser_type(creds.browser)
            elif creds.session_name:
                session_name = creds.session_name
                browser_type = normalize_browser_type(DEFAULT_BROWSER_MAP.get(session_name, "firefox"))
        else:
            browser_type = normalize_browser_type(DEFAULT_BROWSER_MAP.get(session_name, "firefox"))
        user_agent = user_agent_for_browser(browser_type, self.config.browser.user_agent)

        # Clone primary session if target directory is empty to preserve login state
        import shutil

        source_dir = SESSION_DIR / session_name
        is_empty = not any(session_dir.iterdir()) if session_dir.exists() else True
        if is_empty and source_dir.exists() and any(source_dir.iterdir()):
            logger.info(
                f"Cloning primary session {session_name} to {session_dir.name} to preserve login state"
            )
            try:
                shutil.copytree(
                    source_dir,
                    session_dir,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(
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
                    ),
                )
                logger.info(f"Successfully cloned primary session {session_name} to {session_dir.name}")
            except Exception as e:
                logger.warning(f"Failed to clone primary session {session_name} to {session_dir.name}: {e}")

        session_dir.mkdir(parents=True, exist_ok=True)

        # Clean locks and confirm ghost processes are gone before launching
        kill_browser_locks(session_dir, browser_type)
        await asyncio.sleep(2)
        await self._wait_for_ghost_processes_clear(session_dir, browser_type)

        logger.info(f"Creating new browser session: {session_id} ({browser_type})")

        try:
            if browser_type == "chromium":
                context = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=str(session_dir),
                    headless=True,
                    locale=self.config.browser.locale,
                    user_agent=user_agent,
                    viewport={
                        "width": self.config.browser.viewport_width,
                        "height": self.config.browser.viewport_height,
                    },
                    args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
                    timeout=self.config.browser.launch_timeout_ms,
                )
            else:
                context = await self._playwright.firefox.launch_persistent_context(
                    user_data_dir=str(session_dir),
                    headless=True,
                    locale=self.config.browser.locale,
                    user_agent=user_agent,
                    viewport={
                        "width": self.config.browser.viewport_width,
                        "height": self.config.browser.viewport_height,
                    },
                    args=["--no-remote", "--allow-downgrade"],
                    firefox_user_prefs={
                        "network.http.http3.enable": False,
                        "network.http.spdy.enabled.http2": True,
                        "browser.startup.page": 0,
                        "browser.cache.disk.enable": False,
                    },
                    timeout=self.config.browser.launch_timeout_ms,
                )

            page = context.pages[0] if context.pages else await context.new_page()

            info = SessionInfo(
                context=context,
                page=page,
                playwright=self._playwright,
                session_id=session_id,
                account_handle=account_handle,
                browser_type=browser_type,
            )
            async with self._dict_lock:
                self._sessions[session_id] = info
            return info

        except Exception as e:
            logger.error(f"Failed to create session {session_id} ({browser_type}): {e}")
            # Try one more time after aggressive cleanup
            kill_browser_locks(session_dir, browser_type)
            await asyncio.sleep(3)
            await self._wait_for_ghost_processes_clear(session_dir, browser_type)

            if browser_type == "chromium":
                context = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=str(session_dir),
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
                    timeout=self.config.browser.launch_timeout_ms,
                )
            else:
                context = await self._playwright.firefox.launch_persistent_context(
                    user_data_dir=str(session_dir),
                    headless=True,
                    args=["--no-remote", "--allow-downgrade"],
                    timeout=self.config.browser.launch_timeout_ms,
                )

            page = context.pages[0] if context.pages else await context.new_page()
            info = SessionInfo(
                context=context,
                page=page,
                playwright=self._playwright,
                session_id=session_id,
                account_handle=account_handle,
                browser_type=browser_type,
            )
            async with self._dict_lock:
                self._sessions[session_id] = info
            return info

    async def _wait_for_ghost_processes_clear(
        self, session_dir: Path, browser_type: str, timeout: float = 5.0
    ):
        """
        After kill_browser_locks(), poll for up to `timeout` seconds to confirm
        that no browser processes still hold a lock on `session_dir`.  If any
        survive the wait, issue a second force-kill before returning.

        Works without psutil by using 'tasklist' on Windows.
        """
        proc_names = (
            ["chrome.exe", "chromium.exe"]
            if browser_type == "chromium"
            else ["firefox.exe", "firefox"]
        )
        session_str = str(session_dir).lower()
        deadline = asyncio.get_event_loop().time() + timeout

        def _any_ghost_running() -> bool:
            try:
                # tasklist is always available on Windows; no extra packages needed
                result = subprocess.run(
                    ["tasklist", "/fo", "csv", "/nh"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                for line in result.stdout.splitlines():
                    for name in proc_names:
                        if name.lower() in line.lower():
                            return True
            except Exception:
                pass
            return False

        while asyncio.get_event_loop().time() < deadline:
            if not _any_ghost_running():
                return
            await asyncio.sleep(0.5)

        # Still alive — issue a second force-kill
        if _any_ghost_running():
            logger.warning(
                f"Ghost {browser_type} processes still running after {timeout}s; force-killing."
            )
            kill_browser_locks(session_dir, browser_type)
            await asyncio.sleep(1)

    async def release(self, session: SessionInfo, healthy: bool = True):
        """Return a session to the pool. If unhealthy, it will be retired."""
        async with self._dict_lock:
            session.in_use = False
            if not healthy:
                session.failure_count += 1
                logger.warning(
                    f"Session {session.session_id} marked unhealthy (failures={session.failure_count})"
                )
            else:
                session.failure_count = max(0, session.failure_count - 1)

    async def _close_session(self, session_id: str):
        async with self._dict_lock:
            info = self._sessions.pop(session_id, None)
        if info is None:
            return
        info.closed = True
        try:
            await info.context.close()
            logger.info(f"Closed session {session_id}")
        except Exception as e:
            logger.warning(f"Error closing session {session_id}: {e}")

    async def close_all(self):
        """Close all sessions and stop playwright."""
        async with self._dict_lock:
            sids = list(self._sessions.keys())
        for sid in sids:
            await self._close_session(sid)
        
        async with self._dict_lock:
            self._sessions.clear()
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception as e:
                    logger.warning(f"Error stopping playwright: {e}")
                self._playwright = None

    def get_stats(self) -> dict:
        return {
            "active_sessions": len(self._sessions),
            "max_sessions": self.config.browser.max_sessions,
            "sessions": [
                {
                    "id": s.session_id,
                    "account": s.account_handle or "default",
                    "browser": s.browser_type,
                    "age_min": round(s.age_minutes, 1),
                    "idle_min": round(s.idle_minutes, 1),
                    "uses": s.use_count,
                    "failures": s.failure_count,
                }
                for s in self._sessions.values()
            ],
        }


# Singleton
_session_pool: SessionPool | None = None


def get_session_pool() -> SessionPool:
    global _session_pool
    if _session_pool is None:
        _session_pool = SessionPool()
    return _session_pool

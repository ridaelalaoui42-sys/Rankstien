"""Shared Firefox / Chromium / Playwright cleanup helpers.

Why this module exists
----------------------
Two code paths used to maintain their own copy of the same Firefox/Chromium-lock
cleanup logic:

- ``rankstein_mcp_server.py`` — direct ``upload_pin_to_pinterest`` MCP tool
- ``pinterest_automation/session_pool.py`` — supervisor / driver path

When one copy was hardened (taskkill + tasklist polling, broader lock-file
patterns), the other was forgotten.

This module is the single source of truth. Both call sites import from here.
Public functions:

- ``browser_is_running(browser_type)`` — best-effort tasklist check
- ``browser_pids_for_session(session_dir, browser_type)`` — find specific PIDs
- ``kill_browser_locks(session_dir, browser_type)`` — full cleanup
- ``kill_firefox_locks(session_dir)`` — legacy compatibility wrapper
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger("rankstein.browser_utils")


DEFAULT_BROWSER_MAP: dict[str, str] = {
    # All 6 active upload workers → Chromium (stable concurrent persistent contexts on Windows)
    "turbo_v4": "chromium",
    "turbo_v5": "chromium",
    "turbo_v6": "chromium",
    "rida_v2_1": "chromium",
    "rida_v2_2": "chromium",
    "rida_v2_3": "chromium",  # switched from firefox — avoids concurrent session lock crashes
    # Legacy / single-use Firefox profiles (manual or harvester use only)
    "remasterer_v1": "firefox",
    "harvester_v1": "firefox",
    "pinterest_rida_v7": "chromium",
}

FIREFOX_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0"
CHROMIUM_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


def normalize_browser_type(browser_type: str | None, default: str = "chromium") -> str:
    """Return a Playwright browser family supported by the automation."""
    value = (browser_type or default or "firefox").strip().lower()
    if value in {"chrome", "chromium", "msedge", "edge"}:
        return "chromium"
    if value in {"firefox", "ff"}:
        return "firefox"
    logger.warning("Unknown browser type %r; falling back to %s", browser_type, default)
    return default if default in {"chromium", "firefox"} else "firefox"


def user_agent_for_browser(browser_type: str | None, configured: str | None = None) -> str:
    """Use a browser-appropriate UA unless the caller set a matching one."""
    browser = normalize_browser_type(browser_type)
    configured = (configured or "").strip()
    if configured:
        lowered = configured.lower()
        if browser == "chromium" and "chrome/" in lowered:
            return configured
        if browser == "firefox" and "firefox/" in lowered:
            return configured
    return CHROMIUM_USER_AGENT if browser == "chromium" else FIREFOX_USER_AGENT


# Profile locks + SQLite sidecar files that block re-open if browser
# was killed mid-write. Removing -shm / -wal sidecars while browser HOLDS
# them is corruption; we only remove them after confirming process is
# gone.
_LOCK_FILES: tuple[str, ...] = (
    "parent.lock",
    ".parentlock",
    "lock",
    "places.sqlite-shm",
    "places.sqlite-wal",
    "cookies.sqlite-shm",
    "cookies.sqlite-wal",
    "webappsstore.sqlite-shm",
    "webappsstore.sqlite-wal",
    "storage.sqlite-shm",
    "storage.sqlite-wal",
)

_STALE_GLOBS: tuple[str, ...] = ("*.pid", "*.tmp", "lock.*")


def browser_is_running(browser_type: str = "firefox") -> bool:
    """Best-effort check: is any browser process running on this machine?"""
    proc_names = (
        ("chrome.exe", "chrome-headless-shell.exe", "msedge.exe")
        if browser_type == "chromium"
        else ("firefox.exe",)
    )
    try:
        for proc_name in proc_names:
            out = subprocess.run(
                ["tasklist", "/NH", "/FI", f"IMAGENAME eq {proc_name}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc_name in (out.stdout or "").lower():
                return True
        return False
    except Exception:
        return False


def firefox_is_running() -> bool:
    """Best-effort check: is any firefox.exe running on this machine?"""
    return browser_is_running("firefox")


def browser_pids_for_session(session_dir: Path, browser_type: str = "firefox") -> list[int]:
    """Find process IDs running with a specific session dir."""
    target = str(session_dir.resolve())
    proc_names = (
        ("chrome.exe", "chrome-headless-shell.exe", "msedge.exe")
        if browser_type == "chromium"
        else ("firefox.exe",)
    )

    # We use PowerShell to inspect command lines on Windows
    process_filter = " -or ".join(f"$_.Name -eq '{name}'" for name in proc_names)
    script = (
        "Get-CimInstance Win32_Process | "
        f"Where-Object {{ ($_.CommandLine) -and ({process_filter}) }} | "
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
        return sorted(set(pids))
    except Exception:
        return []


def kill_browser_locks(session_dir: Path, browser_type: str = "firefox") -> list[str]:
    """Kill stale browser processes and remove profile lock files."""
    actions: list[str] = []

    # Try specific target killing first if we can locate PIDs
    pids = browser_pids_for_session(session_dir, browser_type)
    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            actions.append(f"Killed specific {browser_type} pid {pid}")
        except Exception as exc:
            actions.append(f"Could not kill {browser_type} pid {pid}: {exc}")

    # We do NOT run a general wildcard taskkill /F /IM here because it kills sibling parallel workers
    # and would also close the user's own open browser windows. Targeted PID killing is sufficient.

    deadline = time.time() + 6.0
    while time.time() < deadline:
        # Check if the specific session processes or general processes are clear
        if pids:
            if not browser_pids_for_session(session_dir, browser_type):
                break
        else:
            if not browser_is_running(browser_type):
                break
        time.sleep(0.4)
    else:
        actions.append(f"Warning: {browser_type} still visible after 6s; proceeding anyway")

    # Clean lock files
    for lock_name in _LOCK_FILES:
        lock_path = session_dir / lock_name
        if lock_path.exists():
            try:
                lock_path.unlink()
                actions.append(f"Removed lock file: {lock_name}")
            except Exception as e:
                actions.append(f"Could not remove {lock_name}: {e}")

    # Clean stale patterns
    for pat in _STALE_GLOBS:
        for stale in session_dir.glob(pat):
            try:
                stale.unlink()
                actions.append(f"Removed stale file: {stale.name}")
            except Exception:
                pass

    return actions


def kill_firefox_locks(session_dir: Path) -> list[str]:
    """Legacy compatibility wrapper for Firefox lock clearing."""
    return kill_browser_locks(session_dir, "firefox")

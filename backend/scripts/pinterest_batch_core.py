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
    human_type,
    update_pin_id,
)

batch_upload_remastered.PINTEREST_BASE = "https://www.pinterest.com"

from pinterest_automation.circuit_breaker import get_circuit_breaker
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
    "pinterest_rida_v7": "firefox",
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
    import unicodedata

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
    while time.time() < deadline:
        try:
            title = await page.query_selector("#storyboard-selector-title")
            board = await page.query_selector('[data-test-id="board-dropdown-select-button"]')
            upload_error = page.get_by_text(
                re.compile(r"reached the limit|límite|limite|failed|error", re.I)
            ).first
            error_visible = False
            try:
                error_visible = await upload_error.is_visible(timeout=500)
            except Exception:
                error_visible = False

            title_disabled = await is_disabled(title) if title else True
            board_disabled = await is_disabled(board) if board else True
            last_state = {
                "title_present": bool(title),
                "title_disabled": title_disabled,
                "board_present": bool(board),
                "board_disabled": board_disabled,
                "upload_error_visible": error_visible,
            }
            if title and board and not title_disabled and not board_disabled and not error_visible:
                return True
        except Exception as exc:
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


async def select_board(page, board_name, worker_id):
    if not circuit.can_execute(f"board_selection:{worker_id}"):
        logger.warning(f"{worker_id}: circuit for board selection is OPEN; skipping interaction")
        return False

    # Try multiple selectors for the board button
    selectors = [
        '[data-test-id="board-dropdown-select-button"]',
        '[aria-label*="Select board" i]',
        '[aria-label*="Choose a board" i]',
        'button:has-text("Choose a board")',
        'button:has-text("Selecciona un tablero")',
    ]

    board_button = None
    for sel in selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=3000, state="attached")
            if el and await el.is_visible():
                board_button = el
                break
        except:
            continue

    if not board_button:
        # Fallback to the first one anyway if nothing visible
        try:
            board_button = await page.wait_for_selector(
                '[data-test-id="board-dropdown-select-button"]', timeout=5000, state="attached"
            )
        except:
            logger.error(f"{worker_id}: board button not found")
            return False

    async def board_label():
        try:
            text = await board_button.evaluate("(el) => (el.innerText || el.textContent || '').trim()")
            return re.sub(r"\s+", " ", text or "")
        except Exception:
            return ""

    async def board_selected():
        label = await board_label()
        # English: 'Choose a board', 'Board', etc.
        if label and not re.search(r"Choose a board|Selecciona|Elige|Board|Select board", label, re.I):
            return label
        return ""

    async def open_dropdown():
        async def is_open():
            try:
                # English 'All boards', 'Found X boards', etc.
                if await page.get_by_text(
                    re.compile(r"All boards|Todos los tableros|Found \d+ boards", re.I)
                ).first.is_visible(timeout=700):
                    return True
            except Exception:
                return False
            return False

        for _ in range(3):
            if await is_open():
                return True
            try:
                await board_button.scroll_into_view_if_needed()
                await board_button.click(force=True, timeout=3000)
            except Exception:
                # Try clicking by coordinates as fallback
                try:
                    box = await board_button.bounding_box()
                    if box:
                        await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                except:
                    pass

            await asyncio.sleep(1.5)
            if await is_open():
                return True
        return False

    async def log_board_diagnostics(reason):
        try:
            button_box = await board_button.bounding_box()
            options = await page.evaluate(
                """(buttonRect) => {
                    const visible = (el) => {
                        const r = el.getBoundingClientRect();
                        const s = window.getComputedStyle(el);
                        return !!(r.width && r.height) && s.display !== 'none' && s.visibility !== 'hidden';
                    };
                    return Array.from(document.querySelectorAll('button, [role="button"], [role="option"], [role="menuitem"], div, span, input'))
                        .map((el) => {
                            const r = el.getBoundingClientRect();
                            const text = (el.innerText || el.textContent || el.value || '').trim().replace(/\\s+/g, ' ');
                            return {
                                tag: el.tagName,
                                role: el.getAttribute('role') || '',
                                testid: el.getAttribute('data-test-id') || '',
                                aria: el.getAttribute('aria-label') || '',
                                text: text.slice(0, 120),
                                box: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
                                near: buttonRect && r.x >= buttonRect.x - 120 && r.x <= buttonRect.x + buttonRect.width + 240 && r.y >= buttonRect.y - 40 && r.y <= buttonRect.y + 520
                            };
                        })
                        .filter((x) => x.text && (x.near || /Aperitivos|Arroces|Paella|All boards|Choose a board|Tag Products|Create board/i.test(x.text) || /board/i.test(x.testid)))
                        .slice(0, 40);
                }""",
                button_box,
            )
            logger.error(
                f"{worker_id}: board diagnostics ({reason}): {json.dumps(options, ensure_ascii=False)}"
            )
            await page.screenshot(
                path=str(project_root / "data" / f"board_selection_failed_{_safe_worker_id(worker_id)}.png"),
                full_page=True,
            )
        except Exception as exc:
            logger.error(f"{worker_id}: board diagnostics failed: {exc}")

    async def find_board_search_input():
        """Return an enabled board-search input, avoiding Pinterest tag/product search fields."""
        selectors = [
            'input[data-test-id="search-boards-field"]',
            '[data-test-id="search-boards-field"] input',
            'input[placeholder*="board" i]',
            'input[placeholder*="tablero" i]',
            'input[aria-label*="board" i]',
            'input[aria-label*="tablero" i]',
            'input[placeholder*="search" i]',
            'input[placeholder*="buscar" i]',
        ]
        for sel in selectors:
            try:
                matches = page.locator(sel)
                for index in range(await matches.count()):
                    element = await matches.nth(index).element_handle()
                    if not element:
                        continue
                    if await is_disabled(element):
                        continue
                    meta = await element.evaluate(
                        """(el) => [
                            el.id || '',
                            el.name || '',
                            el.placeholder || '',
                            el.getAttribute('aria-label') || '',
                            el.getAttribute('data-test-id') || '',
                            el.getAttribute('role') || ''
                        ].join(' ').toLowerCase()"""
                    )
                    if re.search(r"tag|interest|product|topic|etiqueta|producto|tema", meta):
                        continue
                    return element
            except Exception:
                continue
        return None

    async def create_board_from_picker():
        """Create the requested board from Pinterest's board picker when no match exists."""
        try:
            create_button = page.locator('[data-test-id="create-board-button"]').first
            if not await create_button.count():
                create_button = page.get_by_text(re.compile(r"^Create board$|^Crear tablero$", re.I)).first
            if not await create_button.count() or not await create_button.is_visible(timeout=1500):
                return False
            logger.info(f"{worker_id}: creating missing board {board_name}")
            await create_button.click(force=True, timeout=3000)
            await asyncio.sleep(2)

            name_selectors = [
                'input[name="name"]',
                'input[placeholder*="Name" i]',
                'input[placeholder*="Nombre" i]',
                'input[aria-label*="Name" i]',
                'input[aria-label*="Nombre" i]',
                'input[type="text"]',
            ]
            name_input = None
            for selector in name_selectors:
                locator = page.locator(selector)
                for index in range(await locator.count()):
                    candidate = locator.nth(index)
                    try:
                        if await candidate.is_visible(timeout=1000) and await candidate.is_enabled(timeout=1000):
                            name_input = candidate
                            break
                    except Exception:
                        continue
                if name_input:
                    break
            if not name_input:
                logger.error(f"{worker_id}: create-board name input not found")
                return False

            await name_input.fill(board_name)
            await asyncio.sleep(0.5)

            done_locators = [
                page.get_by_role("button", name=re.compile(r"^Create$|^Done$|^Crear$|^Listo$", re.I)),
                page.locator("button").filter(has_text=re.compile(r"^Create$|^Done$|^Crear$|^Listo$", re.I)),
                page.locator('[data-test-id*="create" i] button'),
            ]
            for locator in done_locators:
                for index in range(await locator.count()):
                    button = locator.nth(index)
                    try:
                        if await button.is_visible(timeout=1000) and await button.is_enabled(timeout=1000):
                            await button.click(force=True, timeout=3000)
                            await asyncio.sleep(3)
                            selected = await board_selected()
                            if selected and board_matches(selected, board_name):
                                logger.info(f"{worker_id}: created and selected board {selected}")
                                return True
                            # Some flows create the board but leave the picker open; select it by name.
                            row = await page.query_selector(
                                f'[data-test-id="boardWithoutSection"]:has-text("{board_name}"), [data-test-id="board-row"]:has-text("{board_name}"), [role="option"]:has-text("{board_name}")'
                            )
                            if row:
                                await row.click(force=True)
                                await asyncio.sleep(2)
                                selected = await board_selected()
                                if selected and board_matches(selected, board_name):
                                    logger.info(f"{worker_id}: created then selected board {selected}")
                                    return True
                    except Exception:
                        continue
        except Exception as exc:
            logger.debug(f"{worker_id}: create-board fallback failed: {exc}")
        return False

    def candidate_boards():
        candidates = [
            board_name,
            board_name.split(" y ")[0],
            board_name.split(" & ")[0],
            "Aperitivos",
            "Arroces",
            "Arroces & Paella",
            "Postres",
            "Ensaladas",
            "Carnes",
        ]
        deduped = []
        seen = set()
        for candidate in candidates:
            candidate = re.sub(r"\s+", " ", str(candidate or "").strip())
            if not candidate:
                continue
            key = candidate.casefold()
            if key not in seen:
                seen.add(key)
                deduped.append(candidate)
        return deduped

    def board_norm(value):
        value = str(value or "").casefold()
        value = "".join(
            c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c)
        )
        value = re.sub(r"[^a-z0-9]+", " ", value)
        return re.sub(r"\s+", " ", value).strip()

    def board_matches(selected, candidate):
        selected_norm = board_norm(selected)
        candidate_norm = board_norm(candidate)
        if not selected_norm or not candidate_norm:
            return False
        if candidate_norm in selected_norm or selected_norm in candidate_norm:
            return True
        selected_tokens = {token for token in selected_norm.split() if len(token) >= 4}
        candidate_tokens = {token for token in candidate_norm.split() if len(token) >= 4}
        return bool(selected_tokens & candidate_tokens)

    for click_attempt in range(3):
        opened = await open_dropdown()
        if not opened:
            logger.info(f"{worker_id}: board dropdown did not open on attempt {click_attempt + 1}")
            continue

        # Try search-based selection first
        try:
            search_input = await find_board_search_input()
            if search_input:
                logger.info(f"{worker_id}: using search to find board {board_name}")
                await search_input.fill(board_name)
                await asyncio.sleep(2)
                for candidate in candidate_boards():
                    first_row = await page.query_selector(
                        f'[data-test-id="boardWithoutSection"]:has-text("{candidate}"), [data-test-id="board-row"]:has-text("{candidate}"), [role="option"]:has-text("{candidate}")'
                    )
                    if not first_row:
                        continue
                    await first_row.click(force=True)
                    await asyncio.sleep(2)
                    selected = await board_selected()
                    if selected and board_matches(selected, candidate):
                        logger.info(f"{worker_id}: selected board {selected} via search")
                        return True
                    if selected:
                        logger.warning(
                            f"{worker_id}: rejected board mismatch via search: requested={candidate}, selected={selected}"
                        )
                if await create_board_from_picker():
                    return True
        except Exception as e:
            logger.debug(f"{worker_id}: search selection failed: {e}")

        button_box = await board_button.bounding_box()
        for candidate in candidate_boards():
            try:
                # Prioritize board rows with the candidate name
                selectors = [
                    f'[data-test-id="boardWithoutSection"]:has-text("{candidate}")',
                    f'[data-test-id="board-row"]:has-text("{candidate}")',
                    f'div[role="option"]:has-text("{candidate}")',
                    f'div[role="listitem"]:has-text("{candidate}")',
                ]

                for sel in selectors:
                    matches = page.locator(sel)
                    count = await matches.count()
                    if count > 0:
                        for index in range(count):
                            option = matches.nth(index)
                            try:
                                box = await option.bounding_box(timeout=1000)
                            except:
                                box = None

                            if not box or not button_box:
                                continue
                            # Ensure it's in the dropdown (below the button or near it)
                            if box["y"] < button_box["y"]:
                                continue

                            await option.click(force=True, timeout=3000)
                            await asyncio.sleep(2)
                            selected = await board_selected()
                            if selected and board_matches(selected, candidate):
                                logger.info(f"{worker_id}: selected board {selected} via {sel}")
                                return True
                            if selected:
                                logger.warning(
                                    f"{worker_id}: rejected board mismatch via {sel}: requested={candidate}, selected={selected}"
                                )

                # Fallback to pure text match if no specific selectors found
                matches = page.get_by_text(candidate, exact=True)
                count = await matches.count()
                for index in range(count - 1, -1, -1):
                    option = matches.nth(index)
                    try:
                        box = await option.bounding_box(timeout=1000)
                    except Exception:
                        box = None
                    if not box or not button_box:
                        pass
                    elif box["x"] < button_box["x"] - 80 or box["y"] < button_box["y"] + button_box["height"]:
                        continue
                    try:
                        await option.click(force=True, timeout=3000)
                    except Exception:
                        await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                    await asyncio.sleep(2)
                    selected = await board_selected()
                    if selected and board_matches(selected, candidate):
                        logger.info(f"{worker_id}: selected board {selected} via text match")
                        return True
                    if selected:
                        logger.warning(
                            f"{worker_id}: rejected board mismatch via text match: requested={candidate}, selected={selected}"
                        )
                if count:
                    logger.info(f"{worker_id}: tried board candidate {candidate} ({count} exact matches)")
            except Exception:
                continue

        if button_box:
            try:
                clicked = await page.evaluate(
                    """({buttonRect, candidates}) => {
                        const norm = (value) => (value || '')
                            .toLowerCase()
                            .normalize('NFD')
                            .replace(/[\\u0300-\\u036f]/g, '')
                            .replace(/[^a-z0-9]+/g, ' ')
                            .trim();
                        const wanted = candidates.map((candidate) => norm(candidate)).filter(Boolean);
                        const nodes = Array.from(document.querySelectorAll('div, span, button, [role="option"], [role="menuitem"]'));
                        const visible = (el) => {
                            const r = el.getBoundingClientRect();
                            const s = window.getComputedStyle(el);
                            return !!(r.width && r.height) && s.display !== 'none' && s.visibility !== 'hidden';
                        };
                        const matches = nodes
                            .filter((el) => visible(el))
                            .map((el) => ({el, text: (el.innerText || el.textContent || '').trim(), rect: el.getBoundingClientRect(), testid: el.getAttribute('data-test-id') || ''}))
                            .filter((x) =>
                                x.rect.x >= buttonRect.x - 80 &&
                                x.rect.y >= buttonRect.y + buttonRect.height &&
                                x.rect.y <= buttonRect.y + buttonRect.height + 420 &&
                                x.text &&
                                x.text.length <= 80 &&
                                // STRICTER FILTER: must look like a board option
                                (x.testid === 'board-row' || x.el.getAttribute('role') === 'option' || x.el.closest('[data-test-id="board-row"]')) &&
                                !/^All boards$/i.test(x.text) &&
                                !/^Create board$/i.test(x.text) &&
                                !/^Tag Products/i.test(x.text) &&
                                !/^Add products/i.test(x.text) &&
                                !/^Tagged topics/i.test(x.text) &&
                                !/^Choose a board/i.test(x.text) &&
                                wanted.some((candidate) => {
                                    const text = norm(x.text);
                                    return text.includes(candidate) || candidate.includes(text);
                                })
                            );
                        if (!matches.length) return '';
                        matches.sort((a, b) => a.rect.y - b.rect.y || a.rect.x - b.rect.x);
                        const target = matches[0].el.closest('button, [role="option"], [role="menuitem"]') || matches[0].el;
                        target.click();
                        return matches[0].text;
                    }""",
                    {"buttonRect": button_box, "candidates": candidate_boards()},
                )
                if clicked:
                    await asyncio.sleep(2)
                    selected = await board_selected()
                    if selected and any(board_matches(selected, candidate) for candidate in candidate_boards()):
                        logger.info(f"{worker_id}: selected board {selected}")
                        return True
                    if selected:
                        logger.warning(
                            f"{worker_id}: rejected board mismatch via coordinate fallback: clicked={clicked}, selected={selected}"
                        )
                    logger.info(f"{worker_id}: clicked board option {clicked}, but field did not update")
            except Exception:
                pass
    await log_board_diagnostics(f"failed for {board_name}")
    logger.error(f"{worker_id}: board selection failed for {board_name}")
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

    ext = image_path.suffix
    safe_id = _safe_worker_id(worker_id)
    temp_img = (
        project_root / "data" / f"upload_temp_{safe_id}_{os.getpid()}_{random.randint(1000, 9999)}{ext}"
    )
    shutil.copy2(str(image_path), str(temp_img))

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

        file_input = await page.wait_for_selector('input[type="file"]', timeout=45000)
        await file_input.set_input_files(str(temp_img))
        if not await wait_for_upload_ready(page, worker_id):
            raise PinCreationError(f"{worker_id}: upload editor did not unlock within timeout")

        title_selectors = [
            "#storyboard-selector-title",
            '[data-test-id="pin-draft-title"] textarea',
            'input[placeholder*="title" i]',
            'input[placeholder*="titulo" i]',
            'textarea[placeholder*="title" i]',
            'textarea[placeholder*="titulo" i]',
            'div[contenteditable="true"]',
        ]
        for selector in title_selectors:
            try:
                element = await page.wait_for_selector(selector, timeout=5000)
                if element:
                    if not await force_text_value(element, title[:100]):
                        await human_type(page, element, title[:100])
                    break
            except Exception:
                continue

        desc_selectors = [
            '[data-test-id="pin-draft-description"] textarea',
            'textarea[placeholder*="description" i]',
            'textarea[placeholder*="descripcion" i]',
        ]
        for selector in desc_selectors:
            try:
                element = await page.wait_for_selector(selector, timeout=3000)
                if element:
                    if not await force_text_value(element, desc[:500]):
                        await human_type(page, element, desc[:500])
                    break
            except Exception:
                continue

        if not await fill_destination_link(page, url, worker_id):
            raise PinCreationError(f"{worker_id}: destination link field not filled for {url}")

        if not await wait_for_pinterest_save(page):
            logger.error(f"{worker_id}: Pinterest did not finish saving after link fill")
            try:
                await page.screenshot(
                    path=str(project_root / "data" / f"save_stuck_{_safe_worker_id(worker_id)}.png"),
                    full_page=True,
                )
            except Exception:
                pass
            raise PinCreationError(
                f"{worker_id}: Pinterest did not finish saving after link fill"
            )

        if not await select_board(page, board_name, worker_id):
            circuit.record_failure(f"board_selection:{worker_id}")
            raise PinCreationError(f"{worker_id}: board selection failed for '{board_name}'")
        circuit.record_success(f"board_selection:{worker_id}")

        if not await wait_for_pinterest_save(page):
            logger.error(f"{worker_id}: Pinterest did not finish saving after board selection")
            try:
                await page.screenshot(
                    path=str(project_root / "data" / f"save_stuck_{_safe_worker_id(worker_id)}.png"),
                    full_page=True,
                )
            except Exception:
                pass
            raise PinCreationError(
                f"{worker_id}: Pinterest did not finish saving after board selection"
            )
        await asyncio.sleep(2)

        if not await link_guard_ok(page, url):
            raise PinCreationError(
                f"{worker_id}: link_guard_failed — destination link '{url}' was not committed "
                f"to the form before publish; aborting to prevent wrong-URL pin"
            )

        publish_button = None
        publish_locators = [
            page.get_by_role("button", name=re.compile(r"Publish|Publicar", re.I)),
            page.locator("button").filter(has_text=re.compile(r"Publish|Publicar", re.I)),
            page.locator('[data-test-id="board-dropdown-save-button"]'),
            page.locator('[data-test-id="storyboard-creation-nav-done"]'),
        ]
        for locator in publish_locators:
            try:
                count = await locator.count()
                for index in range(count):
                    candidate = locator.nth(index)
                    if await candidate.is_visible(timeout=1500) and await candidate.is_enabled(timeout=1500):
                        publish_button = candidate
                        break
                if publish_button:
                    break
            except Exception:
                continue

        if not publish_button:
            logger.error(f"{worker_id}: publish button not found")
            await log_publish_diagnostics(page, worker_id)
            raise PinCreationError(f"{worker_id}: publish button not found after all locators")

        await publish_button.click(force=True)
        for _ in range(50):
            await asyncio.sleep(1)
            match = re.search(r"/pin/(\d+)", page.url)
            if match:
                return match.group(1)
            view_pin = await page.query_selector('a[href*="/pin/"]')
            if view_pin:
                href = await view_pin.get_attribute("href")
                match = re.search(r"/pin/(\d+)", href or "")
                if match:
                    return match.group(1)
        
        # If we reach here, we sent the click but never saw a resulting Pin ID
        raise PinCreationError(f"{worker_id}: publish clicked but no Pin ID found within 50s timeout")

    except BrowserSessionLost:
        raise
    except PinCreationError:
        raise
    except Exception as exc:
        logger.error(f"{worker_id}: create pin error: {exc}")
        if is_browser_session_lost(exc):
            raise BrowserSessionLost(str(exc)) from exc
        raise PinCreationError(f"{worker_id}: unexpected error during pin creation: {exc}") from exc
    finally:
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
        async with self.lock:
            if filename in self.uploaded:
                return
            self.uploaded.add(filename)
            with open(UPLOADED_TRACKER, "a", encoding="utf-8") as tracker:
                tracker.write(filename + "\n")
            try:
                update_pin_id(self.sb, post["id"], pin_id)
            except Exception as exc:
                logger.error(f"Supabase pin update failed for {filename}: {exc}")
            path = MEDIA_DIR / filename
            if path.exists():
                try:
                    path.unlink()
                    logger.info(f"Deleted uploaded image: {filename}")
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
                    await asyncio.sleep(random.uniform(12, 26))
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

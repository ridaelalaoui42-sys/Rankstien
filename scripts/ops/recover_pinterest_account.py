"""Open one paused Pinterest profile for a human, then verify its exact owner.

Example (use independently verified public owner details):
    python scripts/ops/recover_pinterest_account.py --account HANDLE \
        --expected-owner-id NUMERIC_ID --expected-username PUBLIC_USERNAME

The human completes login and any verification in the visible Chrome window.
This command never enters credentials, solves challenges, publishes, or changes
rate limits. It closes Chrome before resetting this account's login circuit and
clearing its persisted manual pause. Other accounts can continue working.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from pinterest_automation.account_recovery import (
    AccountRecoveryStateError,
    clear_manual_auth_after_owner_verification,
    manual_recovery_lease,
)
from pinterest_automation.config import SESSION_DIR, get_config

_OWNER = re.compile(r"[0-9]{10,22}")
_USERNAME = re.compile(r"[A-Za-z0-9_]{1,64}")
_CREATOR = "https://www.pinterest.com/pin-creation-tool/"
_IDENTITY_SCRIPT = r"""() => {
  const owners = [];
  for (const id of ['__PWS_DATA__', '__PWS_INITIAL_PROPS__']) {
    const element = document.getElementById(id);
    if (!element) continue;
    let data; try { data = JSON.parse(element.textContent); } catch { continue; }
    const context = data.context || {};
    const redux = data.initialReduxState || {};
    const session = redux.session || {};
    if ([context.isAuthenticated, context.is_authenticated,
         session.isAuthenticated, session.is_authenticated].some(x => x === false)) continue;
    // An arbitrary public profile record cannot establish the signed-in owner.
    const ids = [context.user?.id, session.user?.id, session.userId, session.user_id]
      .filter(x => x != null && /^\d+$/.test(String(x))).map(String);
    for (const ownerId of new Set(ids)) {
      const users = [context.user, session.user, redux.users?.[ownerId]];
      for (const user of users) {
        if (user && String(user.id) === ownerId && typeof user.username === 'string') {
          owners.push({id: ownerId, username: user.username});
        }
      }
    }
  }
  const visibleChallenge = [...document.querySelectorAll(
    'iframe[src*="recaptcha"],iframe[src*="hcaptcha"],iframe[title*="challenge"]'
  )].some(el => { const r = el.getBoundingClientRect(); return r.width > 20 && r.height > 20; });
  return {owners, challenge_present: visibleChallenge};
}"""


def _identity_matches(snapshot: object, owner_id: str, username: str) -> bool:
    if not isinstance(snapshot, dict) or snapshot.get("challenge_present") is not False:
        return False
    owners = snapshot.get("owners")
    if not isinstance(owners, list) or not owners:
        return False
    identities = set()
    for owner in owners:
        if not isinstance(owner, dict) or not isinstance(owner.get("id"), str):
            return False
        name = owner.get("username")
        if not isinstance(name, str) or not _USERNAME.fullmatch(name):
            return False
        identities.add((owner["id"], name.casefold()))
    return identities == {(owner_id, username.casefold())}


def _profile_for_account(account: str, config) -> Path:
    credentials = config.accounts.get(account)
    if credentials is None:
        raise ValueError("A configured Pinterest account is required")
    leaf = credentials.session_name or config.browser.session_name
    if not leaf or Path(leaf).name != leaf or leaf in {".", ".."}:
        raise ValueError("Configured account profile is not a valid session name")
    root = os.environ.get("PINTEREST_SESSION_ROOT", "").strip()
    session_root = Path(root).expanduser() if root else SESSION_DIR
    profile = (session_root / leaf).resolve(strict=True)
    if not profile.is_dir() or profile.parent != session_root.resolve():
        raise ValueError("Configured account profile is unavailable")
    return profile


def _assert_profile_idle(profile: Path) -> None:
    """Fail closed on an active profile or an uninspectable browser process."""
    import psutil

    target = os.path.normcase(str(profile.resolve()))
    browser_names = {
        "chrome.exe",
        "chrome",
        "chromium",
        "chromium.exe",
        "chrome-headless-shell.exe",
        "msedge.exe",
        "msedge",
        "firefox.exe",
        "firefox",
    }
    try:
        for process in psutil.process_iter(["pid", "name", "cmdline"], ad_value=None):
            info = process.info
            name = info.get("name")
            if name is None:
                raise AccountRecoveryStateError("A process identity cannot be inspected safely")
            if name.casefold() not in browser_names:
                continue
            arguments = info.get("cmdline")
            if not arguments:
                raise AccountRecoveryStateError("A browser profile owner cannot be inspected safely")
            values = []
            for index, argument in enumerate(arguments):
                if argument.startswith("--user-data-dir="):
                    values.append(argument.split("=", 1)[1])
                elif argument in {"--user-data-dir", "-profile"} and index + 1 < len(arguments):
                    values.append(arguments[index + 1])
            for value in values:
                if os.path.normcase(str(Path(value.strip('"')).resolve())) == target:
                    raise AccountRecoveryStateError("Configured account profile is already open")
    except psutil.Error as exc:
        raise AccountRecoveryStateError("Browser process ownership could not be verified") from exc


def _launch_options(profile: Path, config) -> dict:
    options = {
        "user_data_dir": str(profile),
        "headless": False,
        "locale": config.browser.locale,
        "viewport": {"width": 1280, "height": 900},
        "timeout": config.browser.launch_timeout_ms,
    }
    executable = os.environ.get("PINTEREST_CHROMIUM_EXECUTABLE_PATH", "").strip()
    if executable:
        options["executable_path"] = str(Path(executable).expanduser())
    else:
        options["channel"] = os.environ.get("PINTEREST_CHROMIUM_CHANNEL", "chrome").strip() or "chrome"
    return options


async def _wait_for_owner(page, owner_id: str, username: str, deadline: float, interval: float) -> None:
    while time.monotonic() < deadline:
        if page.is_closed():
            raise AccountRecoveryStateError("Chrome closed before owner verification completed")
        url = urlsplit(page.url)
        if url.scheme == "https" and url.hostname in {"pinterest.com", "www.pinterest.com"}:
            try:
                async with asyncio.timeout(5):
                    snapshot = await page.evaluate(_IDENTITY_SCRIPT)
                if _identity_matches(snapshot, owner_id, username):
                    return
            except Exception:
                # Human navigation and transient document replacement are expected.
                pass
        await asyncio.sleep(min(interval, max(0, deadline - time.monotonic())))
    raise TimeoutError("Human login did not reach the expected authenticated owner before the deadline")


def _reset_login_circuit(account: str) -> None:
    from pinterest_automation.circuit_breaker import get_circuit_breaker

    breaker = get_circuit_breaker()
    operation = f"pinterest_login:{account}"
    try:
        before = json.loads(breaker._state_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        before = {}
    if not isinstance(before, dict) or any(
        not isinstance(before.get(section, {}), dict)
        for section in ("states", "failure_counts", "success_counts", "last_failure_time")
    ):
        raise AccountRecoveryStateError("Existing circuit state cannot be safely preserved")
    # A corrupt circuit file must never become an implicit reset of other accounts.
    breaker._load_state()
    breaker.reset(operation)
    # Circuit persistence errors are logged by its API; do not resume on one.
    state = json.loads(breaker._state_file.read_text(encoding="utf-8"))
    if state.get("states", {}).get(operation) != "closed":
        raise AccountRecoveryStateError("The exact account login circuit reset was not persisted")


async def recover_account(
    account: str, expected_owner_id: str, expected_username: str, *, timeout_seconds=900, poll_interval=2
) -> dict:
    if not isinstance(expected_owner_id, str) or not _OWNER.fullmatch(expected_owner_id):
        raise ValueError("Expected owner ID must be an independently verified numeric Pinterest owner ID")
    if not isinstance(expected_username, str) or not _USERNAME.fullmatch(expected_username):
        raise ValueError("Expected public username is required")
    if not 10 <= timeout_seconds <= 3600 or not 0.5 <= poll_interval <= 10:
        raise ValueError("Recovery timeout must be 10..3600 seconds and poll interval 0.5..10 seconds")
    config = get_config()
    profile = _profile_for_account(account, config)
    from playwright.async_api import async_playwright

    with manual_recovery_lease(account) as pause_id:
        _assert_profile_idle(profile)
        context = None
        async with async_playwright() as playwright:
            try:
                context = await playwright.chromium.launch_persistent_context(
                    **_launch_options(profile, config)
                )
                page = context.pages[0] if context.pages else await context.new_page()
                print(
                    f"Chrome is open for paused account {account}. Complete login and human verification "
                    f"yourself. Expected public account: {expected_username}. Keep this command running.",
                    flush=True,
                )
                await page.goto(_CREATOR, wait_until="domcontentloaded", timeout=45000)
                print(
                    json.dumps(
                        {
                            "event": "window_ready",
                            "account": account,
                            "expected_username": expected_username,
                            "manual_action_required": True,
                        }
                    ),
                    flush=True,
                )
                deadline = time.monotonic() + timeout_seconds
                await _wait_for_owner(page, expected_owner_id, expected_username, deadline, poll_interval)
                # Fresh authenticated creator navigation excludes stale bootstrap identity.
                await page.goto(_CREATOR, wait_until="domcontentloaded", timeout=45000)
                await _wait_for_owner(page, expected_owner_id, expected_username, deadline, poll_interval)
            finally:
                if context is not None:
                    async with asyncio.timeout(20):
                        await context.close()
        # Both Playwright and Chrome must be closed before the pause can be cleared.
        for attempt in range(10):
            try:
                _assert_profile_idle(profile)
                break
            except AccountRecoveryStateError:
                if attempt == 9:
                    raise
                await asyncio.sleep(1)
        _reset_login_circuit(account)
        clear_manual_auth_after_owner_verification(
            account, expected_owner_id, expected_owner_id, expected_pause_id=pause_id
        )
    return {
        "account": account,
        "verified_owner_id": expected_owner_id,
        "verified_username": expected_username,
        "browser_closed": True,
        "pause_cleared": True,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", required=True)
    parser.add_argument("--expected-owner-id", required=True)
    parser.add_argument("--expected-username", required=True)
    parser.add_argument("--timeout", type=float, default=900)
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(
            recover_account(
                args.account, args.expected_owner_id, args.expected_username, timeout_seconds=args.timeout
            )
        )
    except (Exception, KeyboardInterrupt) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "account": args.account,
                    "pause_cleared": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:200],
                }
            )
        )
        return 1
    print(json.dumps({"ok": True, **result}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

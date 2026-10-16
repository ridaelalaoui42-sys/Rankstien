"""Repair explicit existing Pin links through Edit Pin/Save; default is HTTP-only dry run.

Apply requires an exact plan SHA256, explicit Pin IDs, one configured account,
fresh canonical Recipe proof, and an exclusive worker-zero maintenance lease.
It never creates/deletes Pins, changes the queue, or invokes private write APIs.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
MAX_PINS = 30
EDIT_NAME = re.compile(r"^(edit pin|editar pin)$", re.I)
MORE_NAME = re.compile(
    r"^(more actions|more options|más acciones|mas acciones|más opciones|mas opciones)$", re.I
)
SAVE_NAME = re.compile(r"^(save|save changes|guardar|guardar cambios|done|listo)$", re.I)


def _https(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected an explicit HTTPS URL")
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ValueError("URLs must be explicit HTTPS addresses without credentials, query, or fragment")
    return value


def _pin_id(url: str) -> str:
    parts = urlsplit(_https(url))
    match = re.fullmatch(r"/pin/(\d{15,22})/?", parts.path)
    if not re.fullmatch(r"(?:(?:www|[a-z]{2,3})\.)?pinterest\.com", parts.hostname or "") or not match:
        raise ValueError("Expected the exact public numeric Pin URL")
    return match[1]


def _observed_url(url: str) -> str:
    return urlsplit(url)._replace(query="", fragment="").geturl()


def _username(url: str) -> str:
    parts = urlsplit(_https(url))
    if parts.hostname not in {"pinterest.com", "www.pinterest.com"} or not re.fullmatch(
        r"/[A-Za-z0-9_]+/?", parts.path
    ):
        raise ValueError("Expected an exact public Pinterest owner profile")
    return parts.path.strip("/").casefold()


def validate_plan(
    plan: dict, accounts: set[str], pin_ids: list[str] | None = None, account: str | None = None
) -> list[dict]:
    source = plan.get("entries")
    if not isinstance(source, list) or not source or len(source) > 100:
        raise ValueError("Plan must contain one to 100 explicit Pin entries")
    by_id = {}
    for entry in source:
        pin = str(entry.get("pin_id") or "")
        if not re.fullmatch(r"\d{15,22}", pin) or pin in by_id or _pin_id(entry.get("pin_url")) != pin:
            raise ValueError("Plan contains an invalid or duplicate Pin identity")
        by_id[pin] = entry
    selected = pin_ids or list(by_id)
    if (
        not selected
        or len(selected) > MAX_PINS
        or len(set(selected)) != len(selected)
        or set(selected) - by_id.keys()
    ):
        raise ValueError("Select one to 30 unique Pin IDs present in the exact plan")
    entries = []
    for pin in selected:
        entry = by_id[pin]
        if entry.get("account") not in accounts or (account is not None and entry["account"] != account):
            raise ValueError("Every selected Pin must belong to the requested configured account")
        old, target = _https(entry.get("current_destination")), _https(entry.get("proposed_destination"))
        owner = str(entry.get("expected_owner_id") or "")
        if (
            not owner.isdigit()
            or not owner
            or _username(entry.get("expected_pinner")) != str(entry.get("expected_username") or "").casefold()
        ):
            raise ValueError("Verified expected owner ID, username, and pinner URL are required")
        wrapped = entry.get("canonical_recipe_proof") or {}
        proof = wrapped.get("proof") or {}
        recipe = proof.get("recipe_schema") or {}
        if (
            entry.get("ready_for_owner_ui_destination_edit") is not True
            or wrapped.get("verified") is not True
            or proof.get("status") != 200
            or proof.get("canonical_url") != target
            or proof.get("domain_handle") != entry.get("proposed_domain")
            or recipe.get("@type") != "Recipe"
            or not str(recipe.get("name") or "").strip()
            or old == target
        ):
            raise ValueError(
                "An explicit changed destination with verified canonical Recipe proof is required"
            )
        entries.append({**entry, "pin_id": pin, "expected_owner_id": owner})
    return entries


class _PinMetadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.canonical = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("property") and attrs.get("content"):
            self.meta[attrs["property"]] = attrs["content"]
        if tag == "link" and attrs.get("rel") == "canonical" and attrs.get("href"):
            self.canonical.append(attrs["href"])


def fetch_public_pin(url: str) -> dict:
    expected = _pin_id(url)
    request = Request(
        url, headers={"User-Agent": "RankSteinPinDestinationRepair/1.0", "Cache-Control": "no-cache"}
    )
    with urlopen(request, timeout=20) as response:
        body = response.read(2_000_001)
        status, final_url = response.status, response.url
    if status != 200 or len(body) > 2_000_000 or _pin_id(final_url) != expected:
        raise ValueError("Public Pin response does not prove the same Pin identity")
    parsed = _PinMetadata()
    parsed.feed(body.decode("utf-8", "replace"))
    identities = [parsed.meta.get("og:url"), *parsed.canonical]
    if not identities or any(not identity or _pin_id(identity) != expected for identity in identities):
        raise ValueError("Public canonical/OG metadata does not prove the same Pin ID")
    return {
        "pin_id": expected,
        "pinner": parsed.meta.get("pinterestapp:pinner"),
        "source": parsed.meta.get("pinterestapp:source"),
    }


def check_public(entry: dict, state: dict, *, after_save: bool = False) -> str:
    if state.get("pin_id") != entry["pin_id"] or _username(state.get("pinner")) != _username(
        entry["expected_pinner"]
    ):
        raise ValueError("Public Pin ID or owner differs from the exact plan")
    if state.get("source") == entry["proposed_destination"]:
        return "already_correct" if not after_save else "verified_updated"
    if after_save or state.get("source") != entry["current_destination"]:
        raise ValueError("Public destination differs from the exact expected URL")
    return "ready"


def fetch_article(url: str) -> dict:
    from scripts.dev.plan_pinterest_destination_repair import _article_proof

    return _article_proof(url)[1]


async def preflight(entries: list[dict], *, pin_fetcher=None, article_fetcher=None) -> list[dict]:
    pin_fetcher, article_fetcher = pin_fetcher or fetch_public_pin, article_fetcher or fetch_article
    semaphore = asyncio.Semaphore(3)

    async def bounded(function, argument):
        async with semaphore:
            return await asyncio.to_thread(function, argument)

    targets = sorted({entry["proposed_destination"] for entry in entries})
    proofs = dict(
        zip(
            targets,
            await asyncio.gather(*(bounded(article_fetcher, url) for url in targets), return_exceptions=True),
            strict=True,
        )
    )

    async def inspect(entry):
        try:
            proof = proofs[entry["proposed_destination"]]
            if isinstance(proof, BaseException):
                raise ValueError("Fresh canonical Recipe proof is unavailable") from proof
            expected = entry["canonical_recipe_proof"]["proof"]
            if any(
                proof.get(key) != expected.get(key)
                for key in ("status", "canonical_url", "domain_handle", "recipe_schema")
            ):
                raise ValueError("Fresh canonical Recipe proof differs from the exact plan")
            public = await bounded(pin_fetcher, entry["pin_url"])
            return {
                "pin_id": entry["pin_id"],
                "account": entry["account"],
                "state": check_public(entry, public),
                "public": public,
            }
        except Exception as error:
            return {
                "pin_id": entry["pin_id"],
                "account": entry["account"],
                "state": "blocked",
                "error": str(error)[:240],
            }

    return await asyncio.gather(*(inspect(entry) for entry in entries))


async def _unique_visible(locator, *, wait=False):
    if wait:
        await locator.first.wait_for(state="visible", timeout=15000)
    visible = [
        locator.nth(index) for index in range(await locator.count()) if await locator.nth(index).is_visible()
    ]
    if len(visible) != 1:
        raise ValueError("Expected exactly one visible normal UI control")
    return visible[0]


async def _primary_pin_more_actions(page):
    locator = page.get_by_role("button", name=MORE_NAME)
    await locator.first.wait_for(state="visible", timeout=15000)
    count = await locator.count()
    if count > 100:
        raise ValueError("Pin page exposes too many action controls to identify the primary Pin safely")
    primary = []
    for index in range(count):
        control = locator.nth(index)
        if not await control.is_visible():
            continue
        # The captured owner Pin toolbar has no recommendation test ID;
        # recommendation cards share this label and more-actions-button ID.
        if await control.get_attribute("data-test-id") == "more-actions-button":
            continue
        primary.append(control)
    if len(primary) != 1 or not await primary[0].is_enabled():
        raise ValueError("Could not identify one enabled primary Pin action control outside recommendations")
    return primary[0]


async def read_authenticated_owner(page) -> dict:
    return await page.evaluate("""() => {
      const ids = new Set(), names = new Set();
      for (const key of ['__PWS_DATA__', '__PWS_INITIAL_PROPS__']) {
        let data; try {data=JSON.parse(document.getElementById(key)?.textContent || '{}');} catch {continue;}
        const session=data.initialReduxState?.session;
        for (const value of [data.context?.user?.id,data.context?.user_id,session?.user?.id,session?.userId,session?.user_id])
          if (value != null && /^\\d+$/.test(String(value))) ids.add(String(value));
        for (const value of [data.context?.user?.username,session?.user?.username])
          if (typeof value==='string') names.add(value.toLowerCase());
      }
      return {ids:[...ids],usernames:[...names]};
    }""")


def check_authenticated_owner(entry, owner):
    if set(owner.get("ids") or []) != {entry["expected_owner_id"]}:
        raise ValueError("Authenticated browser owner is unresolved or differs from the exact plan")
    if owner.get("usernames") and set(owner["usernames"]) != {entry["expected_username"].casefold()}:
        raise ValueError("Authenticated browser username differs from the expected pinner")


async def edit_same_pin(page, entry: dict, *, guard, progress, pin_fetcher=None) -> dict:
    """Only fill the existing destination field and click the normal Save control once."""
    pin_fetcher = pin_fetcher or fetch_public_pin
    guard()
    public = await asyncio.to_thread(pin_fetcher, entry["pin_url"])
    state = check_public(entry, public)
    if state == "already_correct":
        return {"pin_id": entry["pin_id"], "state": state, "save_clicked": False, "public": public}
    await page.goto(entry["pin_url"], wait_until="domcontentloaded", timeout=45000)
    if _pin_id(_observed_url(page.url)) != entry["pin_id"]:
        raise ValueError("Browser navigated away from the exact existing Pin")
    await page.wait_for_function(
        "!!document.getElementById('__PWS_DATA__') || !!document.getElementById('__PWS_INITIAL_PROPS__')",
        timeout=20000,
    )
    check_authenticated_owner(entry, await read_authenticated_owner(page))
    guard()
    direct = page.get_by_role("button", name=EDIT_NAME)
    try:
        edit = await _unique_visible(direct)
    except ValueError:
        more = await _primary_pin_more_actions(page)
        await more.click(timeout=15000)
        edit = await _unique_visible(page.get_by_role("menuitem", name=EDIT_NAME), wait=True)
    await edit.click(timeout=15000)
    dialog = await _unique_visible(page.get_by_role("dialog"), wait=True)
    fields = dialog.locator("input,textarea")
    await fields.first.wait_for(state="visible", timeout=15000)
    matches = []
    for index in range(await fields.count()):
        field = fields.nth(index)
        if (
            await field.is_visible()
            and await field.is_editable()
            and await field.input_value() == entry["current_destination"]
        ):
            identity = " ".join(
                [
                    str(await field.get_attribute(key) or "")
                    for key in ("type", "id", "name", "aria-label", "placeholder")
                ]
            )
            if re.search(r"url|link|website|destination|enlace|sitio", identity, re.I):
                matches.append(field)
    if len(matches) != 1:
        raise ValueError("Edit Pin does not expose exactly one field with the expected old destination")
    destination = matches[0]
    save = await _unique_visible(dialog.get_by_role("button", name=SAVE_NAME), wait=True)
    await destination.fill(entry["proposed_destination"], timeout=15000)
    if await destination.input_value() != entry["proposed_destination"]:
        raise ValueError("Destination field did not retain the proposed URL")
    if not await save.is_enabled():
        raise ValueError("Normal Save control is disabled after changing the destination")
    check_authenticated_owner(entry, await read_authenticated_owner(page))
    guard()
    result = {
        "pin_id": entry["pin_id"],
        "state": "save_intent_recorded",
        "save_clicked": False,
        "expected_source": entry["current_destination"],
        "proposed_source": entry["proposed_destination"],
    }
    progress(result)
    result["save_attempted"] = True
    try:
        await save.click(timeout=20000)
        result["save_clicked"] = True
    except Exception as error:
        result["save_click_error"] = type(error).__name__
    for attempt in range(5):
        try:
            public = await asyncio.to_thread(pin_fetcher, entry["pin_url"])
            if check_public(entry, public, after_save=True) == "verified_updated":
                return {**result, "state": "verified_updated", "public": public}
        except Exception:
            pass
        if attempt < 4:
            await asyncio.sleep(2)
    return {**result, "state": "uncertain_after_save"}


def _assert_account_available(account):
    from pinterest_automation.account_recovery import paused_accounts

    if account in paused_accounts():
        raise RuntimeError("Account is paused for human recovery; refusing profile access or Pin edits")


async def failure_diagnostics(page, entry, report_path=None):
    parts = urlsplit(getattr(page, "url", ""))
    result = {"observed_url": {"host": parts.hostname, "path": parts.path[:300]}}
    try:
        result["visible_controls"] = await asyncio.wait_for(
            page.evaluate("""() =>
          [...document.querySelectorAll('button,[role=button],[role=menuitem],[role=dialog]')]
            .filter(el=>el.getBoundingClientRect().width && el.getBoundingClientRect().height)
            .slice(0,40).map(el=>({tag:el.tagName,role:el.getAttribute('role'),
              label:(el.getAttribute('aria-label') || el.innerText || '').slice(0,120),
              test:el.getAttribute('data-test-id'),disabled:el.disabled===true}))
        """),
            timeout=5,
        )
    except Exception as error:
        result["control_capture_error"] = type(error).__name__
    if report_path:
        path = Path(report_path).with_name(f"{Path(report_path).stem}_{entry['pin_id']}_blocked.png")
        try:
            await asyncio.wait_for(page.screenshot(path=str(path), full_page=True), timeout=5)
            result["screenshot"] = str(path)
        except Exception as error:
            result["screenshot_error"] = type(error).__name__
    return result


async def apply_entries(entries, report, save, *, lease_factory=None, pool_factory=None):
    if not entries or len(entries) > MAX_PINS or len({entry["account"] for entry in entries}) != 1:
        raise ValueError("Apply one bounded configured-account batch at a time")
    account = entries[0]["account"]
    _assert_account_available(account)
    if lease_factory is None or pool_factory is None:
        from pinterest_automation.runtime_state import SupervisorLease
        from pinterest_automation.session_pool import SessionPool

        lease_factory, pool_factory = lease_factory or SupervisorLease, pool_factory or SessionPool
    lease = lease_factory(worker_count=0)
    lease.acquire()
    pool = None
    heartbeat_failure = None

    def guard():
        _assert_account_available(account)
        if heartbeat_failure is not None:
            raise RuntimeError(
                "Maintenance heartbeat failed; refusing further Pin edits"
            ) from heartbeat_failure
        lease.heartbeat()
        if not lease._owned:
            raise RuntimeError("Maintenance ownership was lost; refusing further Pin edits")
        if lease.stop_requested():
            raise RuntimeError("Maintenance stop requested; refusing further Pin edits")

    async def heartbeat():
        nonlocal heartbeat_failure
        while True:
            try:
                guard()
            except Exception as error:
                heartbeat_failure = error
                return
            await asyncio.sleep(5)

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        pool = pool_factory()
        guard()
        session = await pool.acquire(account)
        for entry in entries:
            guard()

            def progress(result):
                report["in_progress"] = result
                save()

            try:
                result = await edit_same_pin(session.page, entry, guard=guard, progress=progress)
            except Exception as error:
                result = {
                    "pin_id": entry["pin_id"],
                    "state": "blocked",
                    "error": str(error)[:240],
                    "diagnostics": await failure_diagnostics(session.page, entry, report.get("report_path")),
                }
            report["results"].append(result)
            report.pop("in_progress", None)
            save()
            if result["state"] not in {"already_correct", "verified_updated"}:
                break
    finally:
        try:
            if pool is not None:
                await pool.close_all()
        finally:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
            lease.release()


def validate_apply_request(entries, *, pin_ids, account, expected_sha256, actual_sha256):
    if (
        not pin_ids
        or not account
        or expected_sha256 != actual_sha256
        or len(set(pin_ids)) != len(pin_ids)
        or set(pin_ids) != {entry["pin_id"] for entry in entries}
        or {entry["account"] for entry in entries} != {account}
    ):
        raise ValueError("Apply requires explicit Pin IDs, one account, and the exact expected plan SHA256")


def report_exit_code(report, selected_count):
    if any(item["state"] == "blocked" for item in report["preflight"]):
        return 1
    if report["dry_run"]:
        return 0
    return int(
        len(report["results"]) != selected_count
        or any(item["state"] not in {"verified_updated", "already_correct"} for item in report["results"])
    )


async def run(args):
    sys.path.insert(0, str(ROOT))
    from pinterest_automation.account_recovery import paused_accounts
    from pinterest_automation.config import get_config
    from pinterest_automation.runtime_state import supervisor_admission_status

    raw = args.plan.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    entries = validate_plan(json.loads(raw), set(get_config().accounts), args.pin_id, args.account)
    if args.apply:
        validate_apply_request(
            entries,
            pin_ids=args.pin_id,
            account=args.account,
            expected_sha256=args.expected_plan_sha256,
            actual_sha256=digest,
        )
        _assert_account_available(args.account)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = (
        args.output
        or ROOT / "data/reports/pinterest_draft_recovery" / f"published_pin_link_repair_{stamp}.json"
    )
    report = {
        "generated_utc": datetime.now(UTC).isoformat(),
        "report_path": str(output),
        "plan_sha256": digest,
        "dry_run": not args.apply,
        "admission": supervisor_admission_status(),
        "paused_accounts": sorted(paused_accounts()),
        "preflight_mode": "http_only",
        "selected_pin_ids": [entry["pin_id"] for entry in entries],
        "results": [],
    }

    def save():
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    report["preflight"] = await preflight(entries)
    save()
    if args.apply:
        if any(result["state"] == "blocked" for result in report["preflight"]):
            raise ValueError("Fresh preflight is blocked; no browser opened")
        await apply_entries(entries, report, save)
    print(
        json.dumps(
            {
                "report": str(output),
                "plan_sha256": digest,
                "dry_run": not args.apply,
                "selected": len(entries),
                "preflight": {
                    state: sum(item["state"] == state for item in report["preflight"])
                    for state in {item["state"] for item in report["preflight"]}
                },
                "results": report["results"],
            }
        ),
        flush=True,
    )
    return report_exit_code(report, len(entries))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--pin-id", action="append", help="Exact existing Pin ID; repeat for a bounded batch")
    parser.add_argument("--account")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--output", type=Path)
    raise SystemExit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()

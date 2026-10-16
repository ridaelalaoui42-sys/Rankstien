from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pinterest_automation import account_recovery as recovery
from scripts.ops import recover_pinterest_account as cli

OWNER = "1090504634680315734"
OTHER = "1082904810308958128"


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    state_file = tmp_path / "runtime" / "pinterest_account_recovery.json"
    monkeypatch.setattr(recovery, "RECOVERY_STATE_FILE", state_file)
    monkeypatch.setattr(
        recovery.runtime_state, "SUPERVISOR_LOCK_FILE", tmp_path / "runtime" / "supervisor.lock"
    )
    config = SimpleNamespace(
        accounts={"one": SimpleNamespace(session_name="one"), "two": SimpleNamespace(session_name="two")},
        browser=SimpleNamespace(session_name="default", locale="es-ES", launch_timeout_ms=1000),
    )
    monkeypatch.setattr(recovery, "get_config", lambda: config)
    monkeypatch.setattr(cli, "get_config", lambda: config)
    sessions = tmp_path / "sessions"
    for handle in config.accounts:
        (sessions / handle).mkdir(parents=True)
    monkeypatch.setattr(cli, "SESSION_DIR", sessions)
    return state_file


def test_missing_state_does_not_create_runtime_files(isolated):
    assert recovery.paused_accounts() == set()
    assert not isolated.exists()


def test_pause_idempotent_and_clear_exact_account_only(isolated):
    first = recovery.require_manual_auth("one")
    assert recovery.require_manual_auth("one")["pause_id"] == first["pause_id"]
    recovery.require_manual_auth("two", "authentication_required")
    assert recovery.paused_accounts() == {"one", "two"}
    assert recovery.clear_manual_auth_after_owner_verification(
        "one", OWNER, OWNER, expected_pause_id=first["pause_id"]
    )
    assert recovery.paused_accounts() == {"two"}
    text = isolated.read_text()
    assert "password" not in text and "cookie" not in text and "sessions" not in text


@pytest.mark.parametrize("actual", [OTHER, "", True, 1090504634680315734, "not-an-owner"])
def test_wrong_or_invalid_owner_never_clears_pause(isolated, actual):
    recovery.require_manual_auth("one")
    before = isolated.read_bytes()
    with pytest.raises(ValueError):
        recovery.clear_manual_auth_after_owner_verification("one", actual, OWNER)
    assert isolated.read_bytes() == before


def test_unknown_accounts_and_arbitrary_reason_rejected_without_write(isolated):
    with pytest.raises(ValueError):
        recovery.require_manual_auth("unknown")
    with pytest.raises(ValueError):
        recovery.require_manual_auth("one", "raw-secret-or-profile-path")
    assert not isolated.exists()


@pytest.mark.parametrize(
    "contents",
    [
        "{broken",
        "[]",
        '{"version":true,"accounts":{}}',
        '{"version":1,"accounts":{"unknown":{}}}',
        '{"version":1,"accounts":{"one":{}}}',
    ],
)
def test_corrupt_state_pauses_every_configured_account_and_cannot_be_overwritten(isolated, contents):
    isolated.parent.mkdir(parents=True)
    isolated.write_text(contents)
    assert recovery.paused_accounts() == {"one", "two"}
    with pytest.raises(recovery.AccountRecoveryStateError):
        recovery.require_manual_auth("one")
    with pytest.raises(recovery.AccountRecoveryStateError):
        recovery.clear_manual_auth_after_owner_verification("one", OWNER, OWNER)
    assert isolated.read_text() == contents


def test_unreadable_state_fails_closed(isolated, monkeypatch):
    def unreadable():
        raise PermissionError("busy file")

    monkeypatch.setattr(recovery, "_load_state", unreadable)
    assert recovery.paused_accounts() == {"one", "two"}


def test_stale_verification_cannot_clear_new_pause(isolated):
    recovery.require_manual_auth("one")
    with pytest.raises(recovery.AccountRecoveryStateError):
        recovery.clear_manual_auth_after_owner_verification("one", OWNER, OWNER, expected_pause_id="0" * 32)
    assert recovery.paused_accounts() == {"one"}


def test_failed_atomic_pause_write_preserves_previous_state(isolated, monkeypatch):
    recovery.require_manual_auth("one")
    before = isolated.read_bytes()

    def denied(*args):
        raise PermissionError("atomic replacement denied")

    monkeypatch.setattr(recovery.runtime_state, "_atomic_write_json", denied)
    with pytest.raises(PermissionError):
        recovery.require_manual_auth("two")
    assert isolated.read_bytes() == before
    assert recovery.paused_accounts() == {"one"}


def test_only_exact_login_circuit_reset_preserves_other_account_and_rate_state(isolated, monkeypatch):
    from pinterest_automation import circuit_breaker

    isolated.parent.mkdir(parents=True)
    state_file = isolated.parent / "circuit.json"
    rate_file = isolated.parent / "rate_limiter.db"
    rate_file.write_bytes(b"untouched daily budget evidence")
    before = {
        "states": {"pinterest_login:one": "open", "pinterest_login:two": "open", "pin_upload:one": "open"},
        "failure_counts": {"pinterest_login:one": 7, "pinterest_login:two": 9, "pin_upload:one": 3},
        "success_counts": {"pinterest_login:one": 0, "pinterest_login:two": 2, "pin_upload:one": 0},
        "last_failure_time": {"pinterest_login:one": 10, "pinterest_login:two": 20},
    }
    state_file.write_text(json.dumps(before))
    monkeypatch.setattr(circuit_breaker, "CIRCUIT_STATE_FILE", state_file)
    monkeypatch.setattr(
        circuit_breaker,
        "get_config",
        lambda: SimpleNamespace(circuit_breaker=SimpleNamespace(save_interval_seconds=0)),
    )
    breaker = circuit_breaker.CircuitBreaker()
    monkeypatch.setattr(circuit_breaker, "get_circuit_breaker", lambda: breaker)
    cli._reset_login_circuit("one")
    after = json.loads(state_file.read_text())
    assert after["states"]["pinterest_login:one"] == "closed"
    assert after["failure_counts"]["pinterest_login:one"] == 0
    for section in ("states", "failure_counts", "success_counts", "last_failure_time"):
        for operation, value in before[section].items():
            if operation != "pinterest_login:one":
                assert after[section][operation] == value
    assert rate_file.read_bytes() == b"untouched daily budget evidence"


def test_corrupt_circuit_file_is_preserved_and_cannot_resume_account(isolated, monkeypatch):
    from pinterest_automation import circuit_breaker

    isolated.parent.mkdir(parents=True)
    state_file = isolated.parent / "circuit.json"
    state_file.write_text("{invalid")
    breaker = SimpleNamespace(_state_file=state_file)
    monkeypatch.setattr(circuit_breaker, "get_circuit_breaker", lambda: breaker)
    with pytest.raises(ValueError):
        cli._reset_login_circuit("one")
    assert state_file.read_text() == "{invalid"


def test_profile_guard_exclusive_per_account_and_released_on_error(isolated):
    recovery.require_manual_auth("one")
    with recovery.manual_recovery_lease("one"):
        with pytest.raises(recovery.AccountRecoveryStateError):
            with recovery.account_profile_guard("one"):
                pass
        with recovery.account_profile_guard("two"):
            pass
    with recovery.account_profile_guard("one"):
        pass


def test_manual_lease_requires_existing_pause(isolated):
    with pytest.raises(ValueError, match="Pause the account"):
        with recovery.manual_recovery_lease("one"):
            pass


@pytest.mark.parametrize(
    "snapshot,expected",
    [
        ({"challenge_present": False, "owners": [{"id": OWNER, "username": "RecetaGenial1"}]}, True),
        ({"challenge_present": True, "owners": [{"id": OWNER, "username": "recetagenial1"}]}, False),
        ({"challenge_present": False, "owners": [{"id": OTHER, "username": "recetagenial1"}]}, False),
        ({"challenge_present": False, "owners": [{"id": OWNER, "username": "different"}]}, False),
        (
            {
                "challenge_present": False,
                "owners": [
                    {"id": OWNER, "username": "recetagenial1"},
                    {"id": OTHER, "username": "different"},
                ],
            },
            False,
        ),
        ({"challenge_present": False, "owners": []}, False),
        ({"owners": [{"id": OWNER, "username": "recetagenial1"}]}, False),
    ],
)
def test_authenticated_identity_requires_exact_unambiguous_owner_and_username(snapshot, expected):
    assert cli._identity_matches(snapshot, OWNER, "recetagenial1") is expected


@pytest.mark.parametrize(
    "cmdline,blocked",
    [
        (["chrome.exe", "--user-data-dir={profile}"], True),
        (["chrome.exe", "--user-data-dir", "{profile}"], True),
        (["chrome.exe", "--user-data-dir={profile}-another"], False),
        (None, True),
    ],
)
def test_process_preflight_rejects_active_or_uninspectable_browser(isolated, monkeypatch, cmdline, blocked):
    import psutil

    profile = isolated.parent / "profile"
    args = [x.replace("{profile}", str(profile)) for x in cmdline] if cmdline else None
    monkeypatch.setattr(
        psutil,
        "process_iter",
        lambda *a, **kw: [SimpleNamespace(info={"pid": 7, "name": "chrome.exe", "cmdline": args})],
    )
    if blocked:
        with pytest.raises(recovery.AccountRecoveryStateError):
            cli._assert_profile_idle(profile)
    else:
        cli._assert_profile_idle(profile)


@pytest.fixture
def fake_browser(monkeypatch, isolated):
    import playwright.async_api

    events = []
    page = SimpleNamespace()

    async def goto(*args, **kwargs):
        events.append("navigate")

    page.goto = goto

    class Context:
        def __init__(self):
            self.pages = [page]
            self.fail_close = False

        async def close(self):
            events.append("close")
            if self.fail_close:
                raise RuntimeError("browser close failed")

    context = Context()

    class Playwright:
        async def __aenter__(self):
            return SimpleNamespace(chromium=self)

        async def __aexit__(self, *args):
            events.append("playwright_stop")

        async def launch_persistent_context(self, **options):
            assert options["headless"] is False
            assert Path(options["user_data_dir"]).name == "one"
            events.append("launch")
            return context

    monkeypatch.setattr(playwright.async_api, "async_playwright", Playwright)
    monkeypatch.setattr(cli, "_assert_profile_idle", lambda p: events.append("profile_idle"))

    async def verified(*args):
        assert recovery.paused_accounts() == {"one"}
        events.append("verified")

    monkeypatch.setattr(cli, "_wait_for_owner", verified)

    def reset(account):
        assert account == "one"
        assert "close" in events and "playwright_stop" in events
        assert recovery.paused_accounts() == {"one"}
        events.append("reset_exact_login")

    monkeypatch.setattr(cli, "_reset_login_circuit", reset)
    recovery.require_manual_auth("one")
    return events, context


@pytest.mark.asyncio
async def test_human_recovery_closes_browser_before_reset_and_clear(isolated, fake_browser):
    events, _ = fake_browser
    result = await cli.recover_account("one", OWNER, "recetagenial1")
    assert result["browser_closed"] and result["pause_cleared"]
    assert recovery.paused_accounts() == set()
    assert events == [
        "profile_idle",
        "launch",
        "navigate",
        "verified",
        "navigate",
        "verified",
        "close",
        "playwright_stop",
        "profile_idle",
        "reset_exact_login",
    ]


@pytest.mark.asyncio
async def test_unverified_human_session_closes_and_remains_paused(isolated, fake_browser, monkeypatch):
    events, _ = fake_browser

    async def timeout(*args):
        raise TimeoutError("human verification incomplete")

    monkeypatch.setattr(cli, "_wait_for_owner", timeout)
    with pytest.raises(TimeoutError):
        await cli.recover_account("one", OWNER, "recetagenial1")
    assert recovery.paused_accounts() == {"one"}
    assert "close" in events and "reset_exact_login" not in events


@pytest.mark.asyncio
async def test_close_failure_never_unpauses_or_resets(isolated, fake_browser):
    events, context = fake_browser
    context.fail_close = True
    with pytest.raises(RuntimeError, match="close failed"):
        await cli.recover_account("one", OWNER, "recetagenial1")
    assert recovery.paused_accounts() == {"one"}
    assert "reset_exact_login" not in events


@pytest.mark.asyncio
async def test_profile_conflict_refuses_launch(isolated, fake_browser, monkeypatch):
    events, _ = fake_browser

    def conflict(*args):
        raise recovery.AccountRecoveryStateError("profile in use")

    monkeypatch.setattr(cli, "_assert_profile_idle", conflict)
    with pytest.raises(recovery.AccountRecoveryStateError):
        await cli.recover_account("one", OWNER, "recetagenial1")
    assert "launch" not in events
    assert recovery.paused_accounts() == {"one"}

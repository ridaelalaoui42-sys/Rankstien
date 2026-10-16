"""Persistent-session launch configuration without browsers or production profiles."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import pinterest_automation.session_pool as session_module


@pytest.fixture
def isolated_pool(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    profile_root = tmp_path / "configured-sessions"
    config = SimpleNamespace(
        accounts={
            "account_a": SimpleNamespace(session_name="account-profile"),
            "account_b": SimpleNamespace(session_name=""),
        },
        browser=SimpleNamespace(
            session_name="default-profile",
            locale="es-ES",
            user_agent="test user agent",
            viewport_width=1440,
            viewport_height=900,
            launch_timeout_ms=120000,
            navigation_timeout_ms=60000,
            action_timeout_ms=30000,
            max_sessions=3,
            session_ttl_minutes=60,
        ),
    )
    monkeypatch.setattr(session_module, "get_config", lambda: config)
    monkeypatch.setattr(session_module, "SESSION_DIR", profile_root)
    monkeypatch.setattr(session_module, "kill_browser_locks", Mock())
    monkeypatch.setattr(session_module.asyncio, "sleep", AsyncMock())
    monkeypatch.delenv("PINTEREST_SESSION_ROOT", raising=False)
    monkeypatch.delenv("PINTEREST_CHROMIUM_EXECUTABLE_PATH", raising=False)
    monkeypatch.delenv("PINTEREST_CHROMIUM_CHANNEL", raising=False)

    context = SimpleNamespace(
        pages=[SimpleNamespace(is_closed=lambda: False)],
        add_init_script=AsyncMock(),
        set_default_navigation_timeout=Mock(),
        set_default_timeout=Mock(),
        close=AsyncMock(),
    )
    launch = AsyncMock(return_value=context)
    pool = session_module.SessionPool(pause_reader=lambda: set(), profile_guard_factory=nullcontext)
    pool._playwright = SimpleNamespace(
        chromium=SimpleNamespace(launch_persistent_context=launch),
        firefox=SimpleNamespace(launch_persistent_context=AsyncMock()),
        stop=AsyncMock(),
    )
    pool._wait_for_ghost_processes_clear = AsyncMock()
    return pool, launch, context, profile_root


@pytest.mark.unit
@pytest.mark.parametrize("session_root", [None, "", "   "])
def test_default_session_root_keeps_configured_account_profiles(
    isolated_pool, monkeypatch: pytest.MonkeyPatch, session_root: str | None
) -> None:
    pool, _, _, profile_root = isolated_pool
    if session_root is not None:
        monkeypatch.setenv("PINTEREST_SESSION_ROOT", session_root)

    assert pool._get_session_dir("account_a", "account_a") == profile_root / "account-profile"
    assert pool._get_session_dir("account_b", "account_b") == profile_root / "default-profile"
    assert pool._get_session_dir("default") == profile_root / "default-profile"
    assert not profile_root.exists()


@pytest.mark.unit
def test_explicit_session_root_retains_account_profile_name(
    isolated_pool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pool, _, _, _ = isolated_pool
    selected_root = tmp_path / "operator-selected-root"
    monkeypatch.setenv("PINTEREST_SESSION_ROOT", f"  {selected_root}  ")

    assert pool._get_session_dir("account_a", "account_a") == selected_root / "account-profile"
    assert not selected_root.exists()


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("channel", "expected_channel"),
    [(None, "chrome"), ("msedge", "msedge"), ("", None), ("   ", None)],
)
async def test_chromium_launch_honors_channel_without_fixed_executable(
    isolated_pool,
    monkeypatch: pytest.MonkeyPatch,
    channel: str | None,
    expected_channel: str | None,
) -> None:
    pool, launch, context, profile_root = isolated_pool
    if channel is not None:
        monkeypatch.setenv("PINTEREST_CHROMIUM_CHANNEL", channel)
    profile = profile_root / "account-profile"
    profile.mkdir(parents=True)
    existing_marker = profile / "existing-session-marker.txt"
    existing_marker.write_text("preserve", encoding="utf-8")

    session = await pool.acquire("account_a")

    options = launch.await_args.kwargs
    assert launch.await_count == 1
    assert session.context is context
    assert session.account_handle == "account_a"
    assert session.in_use is True
    assert pool._creating_sessions == 0
    assert options["user_data_dir"] == str(profile)
    assert options.get("channel") == expected_channel
    assert "executable_path" not in options
    assert ("user_agent" in options) is (expected_channel is None)
    assert options["headless"] is True
    assert existing_marker.read_text(encoding="utf-8") == "preserve"
    pool._playwright.firefox.launch_persistent_context.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("channel", [None, "msedge", ""])
async def test_explicit_executable_does_not_compete_with_channel(
    isolated_pool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, channel: str | None
) -> None:
    pool, launch, _, _ = isolated_pool
    executable = tmp_path / "selected-browser" / "chrome.exe"
    monkeypatch.setenv("PINTEREST_CHROMIUM_EXECUTABLE_PATH", f"  {executable}  ")
    if channel is not None:
        monkeypatch.setenv("PINTEREST_CHROMIUM_CHANNEL", channel)

    await pool.acquire("account_a")

    options = launch.await_args.kwargs
    assert options["executable_path"] == str(executable)
    assert "channel" not in options
    assert "user_agent" not in options
    assert options["ignore_default_args"] == ["--enable-automation"]


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("explicit_executable", [False, True])
async def test_retry_keeps_same_profile_and_browser_configuration(
    isolated_pool, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, explicit_executable: bool
) -> None:
    pool, launch, context, _ = isolated_pool
    selected_root = tmp_path / "selected-sessions"
    monkeypatch.setenv("PINTEREST_SESSION_ROOT", str(selected_root))
    if explicit_executable:
        monkeypatch.setenv("PINTEREST_CHROMIUM_EXECUTABLE_PATH", str(tmp_path / "chrome.exe"))
    launch.side_effect = [RuntimeError("transient launch failure"), context]

    session = await pool.acquire("account_a")

    assert launch.await_count == 2
    first_options, retry_options = [call.kwargs for call in launch.await_args_list]
    assert first_options == retry_options
    assert first_options["user_data_dir"] == str(selected_root / "account-profile")
    assert ("executable_path" in first_options) is explicit_executable
    assert ("channel" in first_options) is not explicit_executable
    assert session.context is context
    assert pool._creating_sessions == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failed_launch_releases_capacity_reservation(isolated_pool) -> None:
    pool, launch, _, _ = isolated_pool
    launch.side_effect = RuntimeError("browser unavailable")

    with pytest.raises(RuntimeError, match="browser unavailable"):
        await pool.acquire("account_a")

    assert launch.await_count == 2
    assert pool._creating_sessions == 0
    assert pool._sessions == {}

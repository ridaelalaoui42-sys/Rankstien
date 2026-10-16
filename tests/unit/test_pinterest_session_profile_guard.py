"""Lifetime profile ownership and manual-recovery admission use isolated contexts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from pinterest_automation import account_recovery, runtime_state, session_pool

pytestmark = pytest.mark.unit


@pytest.fixture
def isolated_pool(monkeypatch):
    config = SimpleNamespace(
        accounts={
            "rida": SimpleNamespace(session_name="rida-profile"),
            "media": SimpleNamespace(session_name="media-profile"),
        },
        browser=SimpleNamespace(session_name="rida-profile", max_sessions=3, session_ttl_minutes=60),
    )
    monkeypatch.setattr(session_pool, "get_config", lambda: config)
    paused, active, guards = set(), set(), []

    class Guard:
        def __init__(self, account):
            self.account, self.exits = account, 0

        def __enter__(self):
            if self.account in active:
                raise RuntimeError("profile already owned")
            active.add(self.account)

        def __exit__(self, *args):
            self.exits += 1
            active.remove(self.account)

    def factory(account):
        guard = Guard(account)
        guards.append(guard)
        return guard

    pool = session_pool.SessionPool(pause_reader=lambda: paused, profile_guard_factory=factory)

    async def launch(account):
        assert account in active
        page = SimpleNamespace(is_closed=lambda: False)
        info = session_pool.SessionInfo(
            context=SimpleNamespace(pages=[page], close=AsyncMock()),
            page=page,
            playwright=None,
            session_id=account,
            account_handle=account,
        )
        pool._sessions[account] = info
        return info

    pool._launch_session = AsyncMock(side_effect=launch)
    return pool, paused, active, guards, config


@pytest.mark.asyncio
@pytest.mark.parametrize("close_path", ["normal", "detached", "retire", "all"])
async def test_guard_is_held_until_every_close_path_finishes_once(isolated_pool, close_path):
    pool, _, active, guards, _ = isolated_pool
    info = await pool.acquire("rida")
    await pool.release(info)
    assert active == {"rida"}
    if close_path == "normal":
        await pool._close_session("rida")
    elif close_path == "detached":
        await pool._close_session_detached(info)
    elif close_path == "retire":
        await pool.retire(info)
    else:
        await pool.close_all()
    assert active == set()
    assert guards[0].exits == 1
    assert info.profile_guard is None
    await pool._close_session_detached(info)
    assert guards[0].exits == 1


@pytest.mark.asyncio
async def test_launch_failure_returns_guard_and_capacity(isolated_pool):
    pool, _, active, guards, _ = isolated_pool
    pool._launch_session.side_effect = RuntimeError("launch failed")
    with pytest.raises(RuntimeError, match="launch failed"):
        await pool.acquire("rida")
    assert not active
    assert guards[0].exits == 1
    assert pool._creating_sessions == 0


@pytest.mark.asyncio
async def test_cancelled_launch_returns_guard_and_capacity(isolated_pool):
    pool, _, active, guards, _ = isolated_pool
    entered = asyncio.Event()

    async def launch(account):
        entered.set()
        await asyncio.Event().wait()

    pool._launch_session.side_effect = launch
    task = asyncio.create_task(pool.acquire("rida"))
    await entered.wait()
    assert active == {"rida"}
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not active
    assert guards[0].exits == 1
    assert pool._creating_sessions == 0


@pytest.mark.asyncio
async def test_close_error_still_releases_the_profile_guard(isolated_pool):
    pool, _, active, guards, _ = isolated_pool
    info = await pool.acquire("rida")
    info.context.close.side_effect = RuntimeError("close failed")
    await pool._close_session("rida")
    assert not active
    assert guards[0].exits == 1


@pytest.mark.asyncio
async def test_pause_prevents_cached_reuse_and_release_closes_for_human(isolated_pool):
    pool, paused, active, guards, _ = isolated_pool
    info = await pool.acquire("rida")
    paused.add("rida")
    with pytest.raises(RuntimeError, match="paused"):
        await pool.acquire("rida")
    assert pool._launch_session.await_count == 1
    await pool.release(info)
    assert not active
    assert "rida" not in pool._sessions
    assert guards[0].exits == 1


@pytest.mark.asyncio
async def test_retirement_finishes_before_same_account_replacement(isolated_pool):
    pool, _, active, guards, _ = isolated_pool
    first = await pool.acquire("rida")
    await pool.release(first)
    first.failure_count = 3
    second = await pool.acquire("rida")
    assert second is not first
    assert active == {"rida"}
    assert guards[0].exits == 1
    assert guards[1].exits == 0
    await pool.close_all()


@pytest.mark.asyncio
async def test_unknown_or_ambiguous_default_account_cannot_touch_profile(isolated_pool):
    pool, _, _, guards, config = isolated_pool
    with pytest.raises(ValueError, match="configured"):
        await pool.acquire("unknown")
    info = await pool.acquire()
    assert info.account_handle == "rida"
    await pool.close_all()
    config.accounts["duplicate"] = SimpleNamespace(session_name="rida-profile")
    with pytest.raises(ValueError, match="exactly one"):
        await pool.acquire()
    assert len(guards) == 1


@pytest.mark.asyncio
async def test_pause_during_playwright_start_precedes_profile_cleanup(isolated_pool, monkeypatch):
    pool, paused, active, guards, _ = isolated_pool
    pool._launch_session = session_pool.SessionPool._launch_session.__get__(pool)

    async def start():
        paused.add("rida")

    pool._ensure_playwright = start
    cleanup = Mock()
    monkeypatch.setattr(session_pool, "kill_browser_locks", cleanup)
    with pytest.raises(RuntimeError, match="paused"):
        await pool.acquire("rida")
    cleanup.assert_not_called()
    assert not active
    assert guards[0].exits == 1


@pytest.mark.asyncio
async def test_real_shared_guard_blocks_before_launch_using_only_temporary_files(
    isolated_pool, tmp_path, monkeypatch
):
    pool, _, _, _, config = isolated_pool
    monkeypatch.setattr(account_recovery, "get_config", lambda: config)
    monkeypatch.setattr(account_recovery, "RECOVERY_STATE_FILE", tmp_path / "recovery.json")
    monkeypatch.setattr(runtime_state, "SUPERVISOR_LOCK_FILE", tmp_path / "runtime" / "supervisor.lock")
    pool._profile_guard_factory = account_recovery.account_profile_guard

    async def launch(account):
        page = SimpleNamespace(is_closed=lambda: False)
        return session_pool.SessionInfo(
            context=SimpleNamespace(pages=[page], close=AsyncMock()),
            page=page,
            playwright=None,
            session_id=account,
            account_handle=account,
        )

    pool._launch_session = AsyncMock(side_effect=launch)
    with account_recovery.account_profile_guard("rida"):
        with pytest.raises(account_recovery.AccountRecoveryStateError, match="owns this account"):
            await pool.acquire("rida")
        pool._launch_session.assert_not_awaited()
        media = await pool.acquire("media")
        await pool._close_session_detached(media)
    rida = await pool.acquire("rida")
    await pool._close_session_detached(rida)
    assert not account_recovery.RECOVERY_STATE_FILE.exists()

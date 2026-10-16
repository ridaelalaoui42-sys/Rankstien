"""Concurrency regressions on the real worker/SQLite/session-pool execution path."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts.dev.benchmark_pinterest_workers import run_scenario


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("workers", [1, 2, 3, 6, 10])
async def test_workers_overlap_independent_accounts_and_preserve_account_exclusion(
    tmp_path: Path, workers: int
) -> None:
    report = await run_scenario(
        tmp_path,
        workers=workers,
        jobs_per_account=3,
        io_seconds=0.01,
        require_first_wave=True,
    )

    assert report["completed_verified"] == report["jobs_enqueued"] == 9
    assert report["peak_global_concurrency"] == min(workers, 3)
    assert report["peak_account_concurrency"] == {
        "benchmark_a": 1,
        "benchmark_b": 1,
        "benchmark_c": 1,
    }
    assert report["completed_by_account"] == {
        "benchmark_a": 3,
        "benchmark_b": 3,
        "benchmark_c": 3,
    }
    assert report["peak_browser_sessions"] <= 3
    assert report["deferred_jobs"] == []
    assert report["dlq_size"] == 0
    assert report["active_sessions_after_shutdown"] == 0
    assert report["active_uploads_after_shutdown"] == 0
    assert report["fifo_by_account"] == {
        "benchmark_a": [0, 1, 2],
        "benchmark_b": [0, 1, 2],
        "benchmark_c": [0, 1, 2],
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_session_limit_refuses_third_busy_profile_and_reuses_idle_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pinterest_automation.session_pool as session_module
    from pinterest_automation.session_pool import SessionInfo, SessionPool

    config = SimpleNamespace(
        browser=SimpleNamespace(max_sessions=2, session_ttl_minutes=60),
        accounts={handle: object() for handle in ("benchmark_a", "benchmark_b", "benchmark_c")},
    )
    monkeypatch.setattr(session_module, "get_config", lambda: config)
    pool = SessionPool(pause_reader=lambda: set())

    async def create_session(account_handle: str | None = None) -> SessionInfo:
        info = SessionInfo(
            context=SimpleNamespace(pages=[object()], close=AsyncMock()),
            page=SimpleNamespace(is_closed=lambda: False),
            playwright=None,
            session_id=account_handle,
            account_handle=account_handle,
        )
        pool._sessions[account_handle] = info
        return info

    pool._create_session = create_session
    first = await pool.acquire("benchmark_a")
    await pool.acquire("benchmark_b")
    with pytest.raises(RuntimeError, match="session limit reached"):
        await pool.acquire("benchmark_c")
    assert len(pool._sessions) == 2

    await pool.release(first)
    acquired = await pool.acquire("benchmark_c")
    assert acquired.account_handle == "benchmark_c"
    assert acquired.in_use is True
    assert len(pool._sessions) == 2
    await pool.close_all()
    # Give the real detached idle-session close its scheduling turn.
    await asyncio.sleep(0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concurrent_browser_launches_respect_session_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    import pinterest_automation.session_pool as session_module
    from pinterest_automation.session_pool import SessionInfo, SessionPool

    config = SimpleNamespace(
        browser=SimpleNamespace(max_sessions=2, session_ttl_minutes=60),
        accounts={handle: object() for handle in ("benchmark_a", "benchmark_b", "benchmark_c")},
    )
    monkeypatch.setattr(session_module, "get_config", lambda: config)
    pool = SessionPool(pause_reader=lambda: set())
    launches = 0

    async def create_session(account_handle: str | None = None) -> SessionInfo:
        nonlocal launches
        launches += 1
        # All calls have an opportunity to pass the capacity check before any
        # browser launch completes: a reservation must cover this await.
        await asyncio.sleep(0.02)
        info = SessionInfo(
            context=SimpleNamespace(pages=[object()], close=AsyncMock()),
            page=SimpleNamespace(is_closed=lambda: False),
            playwright=None,
            session_id=account_handle,
            account_handle=account_handle,
        )
        pool._sessions[account_handle] = info
        return info

    pool._create_session = create_session
    outcomes = await asyncio.gather(
        pool.acquire("benchmark_a"),
        pool.acquire("benchmark_b"),
        pool.acquire("benchmark_c"),
        return_exceptions=True,
    )
    try:
        assert launches == 2
        assert len(pool._sessions) == 2
        assert sum(isinstance(outcome, SessionInfo) for outcome in outcomes) == 2
        assert sum(isinstance(outcome, RuntimeError) for outcome in outcomes) == 1
    finally:
        await pool.close_all()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_extra_workers_cannot_parallelize_one_account(tmp_path: Path) -> None:
    report = await run_scenario(
        tmp_path,
        workers=10,
        accounts=("benchmark_a",),
        jobs_per_account=6,
        io_seconds=0.01,
        require_first_wave=True,
    )

    assert report["completed_verified"] == 6
    assert report["peak_global_concurrency"] == 1
    assert report["peak_account_concurrency"] == {"benchmark_a": 1}
    assert report["peak_browser_sessions"] == 1
    assert report["session_creations"] == {"benchmark_a": 1}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rate_deferred_account_preserves_jobs_while_other_accounts_drain(tmp_path: Path) -> None:
    started = time.time()
    report = await run_scenario(
        tmp_path,
        workers=10,
        jobs_per_account=3,
        io_seconds=0.01,
        blocked_accounts=("benchmark_c",),
        require_first_wave=True,
    )

    assert report["completed_verified"] == 6
    assert report["completed_by_account"] == {"benchmark_a": 3, "benchmark_b": 3}
    assert report["peak_global_concurrency"] == 2
    assert len(report["deferred_jobs"]) == 3
    for job in report["deferred_jobs"]:
        assert job["account_handle"] == "benchmark_c"
        assert job["status"] == "pending"
        assert job["attempt"] == 0
        assert job["next_retry_at"] >= started + 300
        assert job["image_preserved"] is True
    assert report["dlq_size"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_grouped_backlog_dispatches_and_completes_every_account(tmp_path: Path) -> None:
    report = await run_scenario(
        tmp_path,
        workers=3,
        jobs_per_account=3,
        io_seconds=0.01,
        layout="grouped",
        require_first_wave=True,
    )

    assert report["completed_verified"] == 9
    assert report["completed_by_account"] == {
        "benchmark_a": 3,
        "benchmark_b": 3,
        "benchmark_c": 3,
    }
    assert all(peak == 1 for peak in report["peak_account_concurrency"].values())
    assert report["peak_global_concurrency"] == 3
    assert set(report["start_order"][:3]) == {"benchmark_a", "benchmark_b", "benchmark_c"}
    assert report["dlq_size"] == 0

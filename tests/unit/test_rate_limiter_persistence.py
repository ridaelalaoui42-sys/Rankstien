"""Budgets and shared health reporting survive hour changes and restarts."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pinterest_automation import rate_limiter as rate_module


@pytest.fixture
def frozen_time(monkeypatch: pytest.MonkeyPatch):
    class FrozenDateTime(datetime):
        current = datetime(2026, 10, 8, 8, 20, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)

    monkeypatch.setattr(rate_module, "datetime", FrozenDateTime)
    monkeypatch.setattr(rate_module.time, "time", lambda: FrozenDateTime.current.timestamp())
    return FrozenDateTime


def _seed_rows(path: Path, rows: list[tuple]) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(rate_module._RL_SCHEMA)
        conn.executemany("INSERT INTO rl_counters VALUES (?, ?, ?, ?, ?, ?, ?)", rows)


@pytest.mark.unit
def test_restart_recovers_previous_hours_daily_budget(tmp_path: Path, frozen_time) -> None:
    path = tmp_path / "rate.db"
    operation = "pin_upload:recetagenial:media"
    _seed_rows(
        path,
        [
            (operation, "2026-10-08", "2026-10-08T00", 17, 17, 0, 0),
            (operation, "2026-10-08", "2026-10-08T01", 25, 8, 0, 0),
        ],
    )
    limiter = rate_module.RateLimiter(db_file=path)
    limiter.config.daily_pin_limit = 25
    assert limiter.get_status()["daily_counts"][operation] == 25
    assert limiter.get_status()["hourly_counts"].get(operation, 0) == 0
    assert limiter.can_execute(operation) is False
    assert limiter.retry_after_seconds(operation) == 15 * 3600 + 40 * 60


@pytest.mark.unit
def test_restart_preserves_current_hour_latest_cooldown(tmp_path: Path, frozen_time) -> None:
    path = tmp_path / "rate.db"
    operation = "pin_upload:recetadolce:rida"
    future = frozen_time.current.timestamp() + 120
    _seed_rows(
        path,
        [
            (operation, "2026-10-08", "2026-10-08T07", 8, 4, 1, 0),
            (operation, "2026-10-08", "2026-10-08T08", 11, 3, 5, future),
        ],
    )
    limiter = rate_module.RateLimiter(db_file=path)
    status = limiter.get_status()
    assert status["daily_counts"][operation] == 11
    assert status["hourly_counts"][operation] == 3
    assert status["failure_streaks"][operation] == 5
    assert status["cooldowns"][operation] == 120
    assert limiter.can_execute(operation) is False


@pytest.mark.unit
def test_restart_preserves_active_previous_hour_cooldown(tmp_path: Path, frozen_time) -> None:
    path = tmp_path / "rate.db"
    operation = "pin_upload:recetadolce:rida"
    _seed_rows(
        path,
        [
            (operation, "2026-10-08", "2026-10-08T07", 8, 4, 5, frozen_time.current.timestamp() + 60),
        ],
    )
    limiter = rate_module.RateLimiter(db_file=path)
    assert limiter.get_status()["failure_streaks"][operation] == 5
    assert limiter.retry_after_seconds(operation) == 60
    assert limiter.can_execute(operation) is False


@pytest.mark.unit
def test_reporting_fresh_shared_counts_without_double_counting(tmp_path: Path, frozen_time) -> None:
    path = tmp_path / "rate.db"
    stale_observer = rate_module.RateLimiter(db_file=path)
    _seed_rows(
        path,
        [
            ("pin_upload:recetadolce:rida", "2026-10-08", "2026-10-08T00", 19, 19, 0, 0),
            ("pin_upload:recetadolce:rida", "2026-10-08", "2026-10-08T01", 35, 16, 0, 0),
            ("pin_upload:recetadolce:rida", "2026-10-08", "2026-10-08T02", 50, 15, 0, 0),
            ("pin_upload:recetagenial:media", "2026-10-08", "2026-10-08T01", 25, 8, 0, 0),
            ("pin_upload:recetagenial:media", "2026-10-07", "2026-10-07T23", 25, 8, 0, 0),
            ("pin_save:recetagenial:media", "2026-10-08", "2026-10-08T01", 4, 4, 0, 0),
        ],
    )
    assert stale_observer.get_persisted_daily_counts() == {
        "pin_upload:recetadolce:rida": 50,
        "pin_upload:recetagenial:media": 25,
        "pin_save:recetagenial:media": 4,
    }
    assert stale_observer.get_status()["daily_counts"] == {}


@pytest.mark.unit
def test_reporting_missing_database_does_not_create_or_fake_zero(tmp_path: Path, frozen_time) -> None:
    observer = object.__new__(rate_module.RateLimiter)
    observer._db_file = tmp_path / "missing.db"
    assert observer.get_persisted_daily_counts() is None
    assert observer._db_file.exists() is False


@pytest.mark.unit
def test_restart_ignores_yesterday(tmp_path: Path, frozen_time) -> None:
    path = tmp_path / "rate.db"
    operation = "pin_upload:recetagenial:media"
    _seed_rows(path, [(operation, "2026-10-07", "2026-10-07T23", 25, 20, 0, 0)])
    limiter = rate_module.RateLimiter(db_file=path)
    assert limiter.get_status()["daily_counts"] == {}
    assert limiter.get_persisted_daily_counts() == {}
    assert limiter.can_execute(operation) is True


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "counts,expected",
    [
        (None, "unknown"),
        ({"pin_upload:one:a": 50, "pin_upload:two:b": 25, "pin_save:two:b": 4}, "75"),
    ],
)
async def test_supervisor_health_reports_persisted_pins(counts, expected, caplog) -> None:
    from pinterest_automation.supervisor import AutonomousSupervisor

    supervisor = object.__new__(AutonomousSupervisor)
    supervisor._shutdown_event = asyncio.Event()
    supervisor.health = SimpleNamespace(get_snapshot=lambda: SimpleNamespace(all_ok=True))

    async def stats():
        supervisor._shutdown_event.set()
        return {"total": 10}

    supervisor.queue = SimpleNamespace(get_stats_async=stats, requeue_stale_processing_async=AsyncMock())
    supervisor.pool = SimpleNamespace(get_stats=lambda: {"active_sessions": 0})
    supervisor.rate_limiter = SimpleNamespace(get_persisted_daily_counts=lambda: counts)
    supervisor._last_stale_requeue = float("inf")
    supervisor.config = SimpleNamespace(watch_interval_seconds=1)
    with caplog.at_level(logging.INFO):
        await supervisor._health_reporter()
    assert f"daily_pins={expected}" in caplog.text
    supervisor.queue.requeue_stale_processing_async.assert_not_awaited()

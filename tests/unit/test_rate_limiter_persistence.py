"""Budgets and shared health reporting survive hour changes and restarts."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pinterest_automation import rate_limiter as rate_module

_PROOF_SCHEMA = """
CREATE TABLE completed_log (id TEXT PRIMARY KEY, job_json TEXT, completed_at REAL);
CREATE TABLE jobs (id TEXT PRIMARY KEY, type TEXT, payload_json TEXT,
                   status TEXT, result_json TEXT, completed_at REAL);
"""


@pytest.fixture(autouse=True)
def isolated_proof_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "jobs.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(_PROOF_SCHEMA)
    config = SimpleNamespace(
        rate_limit=rate_module.get_config().rate_limit,
        accounts={"rida": object(), "media": object(), "baker": object()},
    )
    monkeypatch.setattr(rate_module, "get_config", lambda: config)
    monkeypatch.setattr(
        "rankstein.domain.get_registry",
        lambda: SimpleNamespace(
            all=lambda: [
                SimpleNamespace(handle="recetadolce", domain="recetadolce.com"),
                SimpleNamespace(handle="recetagenial", domain="recetagenial.com"),
                SimpleNamespace(handle="third", domain="third.example"),
            ]
        ),
    )
    monkeypatch.setenv(
        "PINTEREST_DOMAIN_ACCOUNT_MAP",
        json.dumps({"recetadolce": ["rida"], "recetagenial": ["media"], "third": ["baker"]}),
    )
    return path


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


def _pin_job(
    job_id: str,
    pin_id: str,
    *,
    domain: str = "recetadolce",
    account: str = "rida",
    host: str = "recetadolce.com",
) -> dict:
    return {
        "id": job_id,
        "type": "pin_upload",
        "status": "completed",
        "payload": {
            "domain_handle": domain,
            "account_handle": account,
            "link": f"https://{host}/a-recipe",
        },
        "result": {
            "success": True,
            "pin_id": pin_id,
            "pin_url": f"https://www.pinterest.com/pin/{pin_id}/",
        },
    }


def _archive_pin(path: Path, job: dict, completed_at: float) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO completed_log VALUES (?, ?, ?)",
            (job["id"], json.dumps(job), completed_at),
        )


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
def test_lost_history_recovers_unique_pin_floor_without_live_writes(
    tmp_path: Path, isolated_proof_queue: Path, frozen_time
) -> None:
    path = tmp_path / "rate.db"
    operation = "pin_upload:recetadolce:rida"
    _seed_rows(path, [(operation, "2026-10-08", "2026-10-08T08", 1, 1, 0, 0)])
    for index in range(3):
        job = _pin_job(f"job-{index}", str(10000000000000000 + index))
        _archive_pin(isolated_proof_queue, job, frozen_time.current.timestamp())
    duplicate = _pin_job("same-pin-new-job", "10000000000000000")
    _archive_pin(isolated_proof_queue, duplicate, frozen_time.current.timestamp())
    with sqlite3.connect(isolated_proof_queue) as connection:
        connection.execute(
            "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?)",
            (
                "also-current",
                duplicate["type"],
                json.dumps(duplicate["payload"]),
                "completed",
                json.dumps(duplicate["result"]),
                frozen_time.current.timestamp(),
            ),
        )
    limiter = rate_module.RateLimiter(db_file=path)
    limiter.config.daily_pin_limit = 3
    assert limiter.get_persisted_daily_counts() == {operation: 3}
    assert limiter.get_status()["daily_counts"][operation] == 3
    assert limiter.can_execute(operation) is False
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT MAX(daily_count) FROM rl_counters").fetchone()[0] == 1


@pytest.mark.unit
def test_current_successful_jobs_count_and_snapshots_are_not_summed(
    tmp_path: Path, isolated_proof_queue: Path, frozen_time
) -> None:
    operation = "pin_upload:third:baker"
    path = tmp_path / "rate.db"
    _seed_rows(
        path,
        [
            (operation, "2026-10-08", "2026-10-08T07", 4, 4, 0, 0),
            (operation, "2026-10-08", "2026-10-08T08", 5, 1, 0, 0),
        ],
    )
    job = _pin_job("third-job", "10000000000000000", domain="third", account="baker", host="third.example")
    with sqlite3.connect(isolated_proof_queue) as connection:
        connection.execute(
            "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?)",
            (
                job["id"],
                "pin_upload",
                json.dumps(job["payload"]),
                "completed",
                json.dumps(job["result"]),
                frozen_time.current.timestamp(),
            ),
        )
    limiter = rate_module.RateLimiter(db_file=path)
    assert limiter.get_persisted_daily_counts() == {operation: 5}
    assert limiter._proof_daily_counts() == {operation: 1}


@pytest.mark.unit
@pytest.mark.parametrize(
    "change",
    [
        "wrong_domain",
        "unknown_account",
        "wrong_domain_account",
        "conflicting_identity",
        "wrong_destination",
        "wrong_pin_url",
        "wrong_pin_id",
        "unproven",
        "not_completed",
        "pin_save",
        "yesterday",
    ],
)
def test_unrelated_or_unproven_rows_never_recover_budget(
    tmp_path: Path, isolated_proof_queue: Path, frozen_time, change: str
) -> None:
    job = _pin_job("bad-job", "10000000000000000")
    completed = frozen_time.current.timestamp()
    if change == "wrong_domain":
        job["payload"]["domain_handle"] = "unconfigured"
    elif change == "unknown_account":
        job["payload"]["account_handle"] = "unconfigured"
    elif change == "wrong_domain_account":
        job["payload"]["account_handle"] = "media"
    elif change == "conflicting_identity":
        job["payload"]["extra"] = {"account_handle": "media"}
    elif change == "wrong_destination":
        job["payload"]["link"] = "https://unrelated.example/a-recipe"
    elif change == "wrong_pin_url":
        job["result"]["pin_url"] = "https://www.pinterest.com/pin/20000000000000000/"
    elif change == "wrong_pin_id":
        job["result"]["pin_id"] = "not-a-pin"
    elif change == "unproven":
        job["result"]["success"] = False
    elif change == "not_completed":
        job["status"] = "processing"
    elif change == "pin_save":
        job["type"] = "pin_save"
    elif change == "yesterday":
        completed -= 86400
    _archive_pin(isolated_proof_queue, job, completed)
    limiter = rate_module.RateLimiter(db_file=tmp_path / "rate.db")
    assert limiter.get_persisted_daily_counts() == {}


@pytest.mark.unit
def test_missing_proof_db_fails_closed_and_never_creates_it(tmp_path: Path, frozen_time) -> None:
    missing = tmp_path / "missing-proof.db"
    limiter = rate_module.RateLimiter(db_file=tmp_path / "rate.db", proof_db_file=missing)
    assert limiter.can_execute("pin_upload:recetadolce:rida") is False
    assert limiter.retry_after_seconds("pin_upload:recetadolce:rida") >= 60
    assert limiter.get_persisted_daily_counts() is None
    assert missing.exists() is False
    assert limiter.can_execute("pin_save:recetadolce:rida") is True


@pytest.mark.unit
def test_truncated_proof_scan_is_unknown_not_partial_zero(
    tmp_path: Path, isolated_proof_queue: Path, frozen_time, monkeypatch: pytest.MonkeyPatch
) -> None:
    _archive_pin(isolated_proof_queue, _pin_job("job", "10000000000000000"), frozen_time.current.timestamp())
    monkeypatch.setattr(rate_module, "_PROOF_MAX_ROWS", 0)
    limiter = rate_module.RateLimiter(db_file=tmp_path / "rate.db")
    assert limiter.get_persisted_daily_counts() is None
    assert limiter.can_execute("pin_upload:recetadolce:rida") is False


@pytest.mark.unit
def test_oversized_proof_row_is_unknown_not_an_unbounded_allocation(
    tmp_path: Path, isolated_proof_queue: Path, frozen_time, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _pin_job("large-job", "10000000000000000")
    job["payload"]["description"] = "x" * 2048
    _archive_pin(isolated_proof_queue, job, frozen_time.current.timestamp())
    monkeypatch.setattr(rate_module, "_PROOF_MAX_ROW_BYTES", 1024)
    limiter = rate_module.RateLimiter(db_file=tmp_path / "rate.db")
    assert limiter.get_persisted_daily_counts() is None
    assert limiter.can_execute("pin_upload:recetadolce:rida") is False


@pytest.mark.unit
@pytest.mark.parametrize(
    "operation", ["pin_upload", "pin_upload:unknown:rida", "pin_upload:recetadolce:media"]
)
def test_unscoped_unknown_or_wrong_domain_account_operation_fails_closed(
    tmp_path: Path, frozen_time, operation: str
) -> None:
    limiter = rate_module.RateLimiter(db_file=tmp_path / "rate.db")
    assert limiter.can_execute(operation) is False
    assert limiter.retry_after_seconds(operation) >= 60


@pytest.mark.unit
def test_utc_rollover_excludes_yesterdays_proof_floor(
    tmp_path: Path, isolated_proof_queue: Path, frozen_time
) -> None:
    operation = "pin_upload:recetadolce:rida"
    _archive_pin(
        isolated_proof_queue, _pin_job("old-pin", "10000000000000000"), frozen_time.current.timestamp()
    )
    limiter = rate_module.RateLimiter(db_file=tmp_path / "rate.db")
    limiter.config.daily_pin_limit = 1
    assert limiter.can_execute(operation) is False
    frozen_time.current = datetime(2026, 10, 9, 0, 0, 1, tzinfo=UTC)
    assert limiter.can_execute(operation) is True
    assert limiter.get_persisted_daily_counts() == {}


@pytest.mark.unit
def test_matching_day_number_in_a_new_month_does_not_keep_old_usage(tmp_path: Path, frozen_time) -> None:
    limiter = rate_module.RateLimiter(db_file=tmp_path / "rate.db")
    operation = "pin_upload:recetadolce:rida"
    limiter.record_execution(operation)
    limiter.config.daily_pin_limit = 1
    assert limiter.can_execute(operation) is False
    frozen_time.current = datetime(2026, 11, 8, 8, 20, tzinfo=UTC)
    assert limiter.can_execute(operation) is True


@pytest.mark.unit
def test_stale_instance_failure_never_lowers_another_writers_counter(tmp_path: Path, frozen_time) -> None:
    path = tmp_path / "rate.db"
    first = rate_module.RateLimiter(db_file=path)
    stale = rate_module.RateLimiter(db_file=path)
    operation = "pin_upload:recetadolce:rida"
    first.record_execution(operation)
    first.record_execution(operation)
    stale.record_failure(operation)
    assert stale.get_persisted_daily_counts()[operation] == 2
    assert stale.get_status()["daily_counts"][operation] == 2
    stale.record_execution(operation)
    assert first.get_persisted_daily_counts()[operation] == 3


@pytest.mark.unit
def test_stale_instance_rechecks_shared_exhausted_budget(tmp_path: Path, frozen_time) -> None:
    path = tmp_path / "rate.db"
    stale = rate_module.RateLimiter(db_file=path)
    writer = rate_module.RateLimiter(db_file=path)
    operation = "pin_upload:recetadolce:rida"
    stale.config.daily_pin_limit = 1
    writer.record_execution(operation)
    assert stale.can_execute(operation) is False


@pytest.mark.unit
def test_proof_path_override_precedence_does_not_escape_isolated_db(
    tmp_path: Path, isolated_proof_queue: Path, frozen_time, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "configured" / "rate.db"
    monkeypatch.setattr(rate_module, "_RL_DB_FILE", configured)
    monkeypatch.setattr(rate_module, "_CONFIGURED_RL_DB_FILE", configured)
    monkeypatch.setenv("PINTEREST_QUEUE_DB_FILE", str(isolated_proof_queue))
    default = rate_module.RateLimiter()
    assert default._proof_db_file == isolated_proof_queue
    explicit = rate_module.RateLimiter(db_file=tmp_path / "isolated" / "rate.db")
    assert explicit._proof_db_file == tmp_path / "isolated" / "jobs.db"
    assert explicit.get_persisted_daily_counts() is None
    override = rate_module.RateLimiter(db_file=explicit._db_file, proof_db_file=isolated_proof_queue)
    assert override.get_persisted_daily_counts() == {}


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

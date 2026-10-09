from __future__ import annotations

import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from rankstein import pipeline_events


def _run(tmp_path):
    database = tmp_path / "isolated-pipeline.db"
    run_id = pipeline_events.start_pipeline_run(
        domain_handle="recetadolce",
        keyword="pastel de zanahoria sin horno",
        db_path=database,
    )
    return database, run_id


@pytest.mark.unit
def test_bounded_progress_writer_uses_one_real_sqlite_lock_deadline(tmp_path):
    database, run_id = _run(tmp_path)
    with sqlite3.connect(database, isolation_level=None) as holder:
        holder.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        with pytest.raises((sqlite3.OperationalError, TimeoutError)):
            pipeline_events.record_pipeline_stage(
                run_id,
                "pinterest_siphon",
                "running",
                db_path=database,
                write_timeout_seconds=0.05,
            )
        elapsed = time.monotonic() - started
        holder.execute("ROLLBACK")
    # This is an actual SQLite busy wait, not a timed thread still writing.
    assert elapsed < 1.0
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM pipeline_events WHERE stage='pinterest_siphon'"
        ).fetchone() == (0,)


@pytest.mark.unit
def test_guard_after_acquired_lock_cannot_refresh_run_or_reset_completed_stage(monkeypatch, tmp_path):
    database, run_id = _run(tmp_path)
    attempted_lock = threading.Event()
    finished = threading.Event()
    original_execute = pipeline_events._execute

    def observed_execute(connection, sql, *args, **kwargs):
        if sql == "BEGIN IMMEDIATE":
            attempted_lock.set()
        return original_execute(connection, sql, *args, **kwargs)

    monkeypatch.setattr(pipeline_events, "_execute", observed_execute)
    with sqlite3.connect(database, isolation_level=None) as holder, ThreadPoolExecutor(max_workers=1) as pool:
        holder.execute("BEGIN IMMEDIATE")
        future = pool.submit(
            pipeline_events.record_pipeline_stage,
            run_id,
            "pinterest_siphon",
            "running",
            "stale collector progress",
            db_path=database,
            write_timeout_seconds=2.0,
            should_skip=finished.is_set,
        )
        assert attempted_lock.wait(1.0)
        # Completion owns the lock first; a progress writer waiting behind it
        # must check completion after obtaining that same lock.
        finished.set()
        holder.execute("UPDATE pipeline_runs SET updated_at=123 WHERE id=?", (run_id,))
        pipeline_events._insert_event(
            holder, run_id, "pinterest_siphon", "complete", "15 accepted", {"accepted": 15}, 123
        )
        holder.execute("COMMIT")
        future.result(timeout=3)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT updated_at FROM pipeline_runs WHERE id=?", (run_id,)
        ).fetchone() == (123.0,)
        assert connection.execute(
            "SELECT state,message FROM pipeline_events WHERE stage='pinterest_siphon' ORDER BY id"
        ).fetchall() == [("complete", "15 accepted")]


@pytest.mark.unit
def test_finished_guard_does_not_create_unknown_run(tmp_path):
    database = tmp_path / "unknown-pipeline.db"
    pipeline_events.record_pipeline_stage(
        "unknown-run",
        "pinterest_siphon",
        "running",
        domain_handle="recetagenial",
        keyword="ensalada",
        db_path=database,
        write_timeout_seconds=1.0,
        should_skip=lambda: True,
    )
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE name IN ('pipeline_runs','pipeline_events')"
        ).fetchone() == (0,)


@pytest.mark.unit
def test_progress_suppresses_terminal_stage_but_preserves_ordinary_retry_behavior(tmp_path):
    database, run_id = _run(tmp_path)
    pipeline_events.record_pipeline_stage(run_id, "pinterest_siphon", "warning", "partial", db_path=database)
    pipeline_events.record_pipeline_stage(
        run_id,
        "pinterest_siphon",
        "running",
        "late progress",
        db_path=database,
        write_timeout_seconds=1.0,
        should_skip=lambda: False,
        skip_terminal_stage=True,
    )
    # A real new attempt is still allowed to transition warning -> running.
    pipeline_events.record_pipeline_stage(
        run_id, "pinterest_siphon", "running", "new attempt", db_path=database
    )
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT state,message FROM pipeline_events WHERE stage='pinterest_siphon' ORDER BY id"
        ).fetchall()
    assert rows == [("warning", "partial"), ("running", "new attempt")]


@pytest.mark.unit
def test_bounded_progress_records_real_domain_and_sanitized_counters(tmp_path):
    database = tmp_path / "isolated.db"
    details = {"accepted": 3, "examined": 12, "target": 15, "remaining_sources": 12}
    pipeline_events.record_pipeline_stage(
        "domain-run",
        "pinterest_siphon",
        "running",
        "3/15 accepted · 12 examined · 12 remaining",
        details=details,
        domain_handle="recetagenial",
        keyword="ensalada",
        db_path=database,
        write_timeout_seconds=1.0,
        should_skip=lambda: False,
    )
    with sqlite3.connect(database) as connection:
        run = connection.execute("SELECT domain_handle,keyword FROM pipeline_runs").fetchone()
        row = connection.execute("SELECT stage,state,details_json FROM pipeline_events").fetchone()
    assert run == ("recetagenial", "ensalada")
    assert row[:2] == ("pinterest_siphon", "running")
    assert json.loads(row[2]) == details

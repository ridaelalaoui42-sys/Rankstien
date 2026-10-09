"""Durable, process-safe telemetry for the per-keyword production pipeline.

The article worker, remaster subprocess, and dashboard run in separate
processes. SQLite gives them one small shared event stream without coupling
production work to the dashboard or relying on fragile log parsing.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIPELINE_DB = Path(
    os.environ.get(
        "RANKSTEIN_PIPELINE_DB",
        str(PROJECT_ROOT / "data" / "runtime" / "pipeline_events.db"),
    )
)

PIPELINE_STAGES = (
    "keyword_search",
    "keyword_selected",
    "source_scrape",
    "source_extract",
    "article_write",
    "quality_check",
    "hero_image",
    "hero_upload",
    "article_publish",
    "primary_pin",
    "primary_pin_publish",
    "pinterest_siphon",
    "remaster",
    "queue",
    "distribution",
    "verification",
)

EVENT_STATES = {"pending", "running", "complete", "waiting", "warning", "failed"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id TEXT PRIMARY KEY,
    domain_handle TEXT NOT NULL,
    keyword TEXT NOT NULL,
    slug TEXT NOT NULL DEFAULT '',
    cluster TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'running',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_updated
    ON pipeline_runs(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_domain
    ON pipeline_runs(domain_handle, updated_at DESC);

CREATE TABLE IF NOT EXISTS pipeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES pipeline_runs(id),
    stage TEXT NOT NULL,
    state TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pipeline_events_run
    ON pipeline_events(run_id, id);
CREATE INDEX IF NOT EXISTS idx_pipeline_events_created
    ON pipeline_events(created_at DESC);
"""


def _execute(
    connection: sqlite3.Connection,
    sql: str,
    parameters: tuple = (),
    *,
    deadline: float | None = None,
) -> sqlite3.Cursor:
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("pipeline telemetry write deadline exceeded")
        # Reset before each statement: multiple lock waits share one budget.
        connection.execute(f"PRAGMA busy_timeout={max(0, int(remaining * 1000))}")
    result = connection.execute(sql, parameters)
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("pipeline telemetry write deadline exceeded")
    return result


def _connect(db_path: Path = PIPELINE_DB, *, deadline: float | None = None) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if deadline is None:
        connection = sqlite3.connect(str(db_path), timeout=15)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=15000")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(_SCHEMA)
        return connection
    connection = sqlite3.connect(str(db_path), timeout=max(0.0, deadline - time.monotonic()))
    connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 100)
    try:
        _execute(connection, "PRAGMA journal_mode=WAL", deadline=deadline)
        _execute(connection, "PRAGMA foreign_keys=ON", deadline=deadline)
    except BaseException:
        connection.close()
        raise
    return connection


def start_pipeline_run(
    *,
    domain_handle: str,
    keyword: str,
    slug: str = "",
    cluster: str = "",
    source: str = "",
    db_path: Path = PIPELINE_DB,
) -> str:
    """Create a run and record the two keyword intake checkpoints."""

    run_id = f"{domain_handle}-{uuid.uuid4().hex[:12]}"
    now = time.time()
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO pipeline_runs (
                id, domain_handle, keyword, slug, cluster, source,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'running', ?, ?)
            """,
            (run_id, domain_handle, keyword, slug, cluster, source, now, now),
        )
        _insert_event(
            connection,
            run_id,
            "keyword_search",
            "complete",
            f"Discovered through {source or 'the keyword roadmap'}",
            {"source": source or "keyword roadmap"},
            now,
        )
        _insert_event(
            connection,
            run_id,
            "keyword_selected",
            "complete",
            "Reserved for production",
            {"cluster": cluster},
            now,
        )
    return run_id


def record_pipeline_stage(
    run_id: str,
    stage: str,
    state: str,
    message: str = "",
    *,
    details: dict[str, Any] | None = None,
    domain_handle: str = "",
    keyword: str = "",
    slug: str = "",
    db_path: Path = PIPELINE_DB,
    write_timeout_seconds: float | None = None,
    should_skip: Callable[[], bool] | None = None,
    skip_terminal_stage: bool = False,
) -> None:
    """Append a stage transition, optionally with bounded stale-safe progress.

    Ordinary callers retain their existing wait/transaction behavior. Progress
    writers opt into a shared SQLite deadline and a completion/cancel guard,
    checked only after BEGIN IMMEDIATE owns the write lock. Their late-running
    events therefore cannot be appended after the completion they waited for.
    """

    if stage not in PIPELINE_STAGES:
        raise ValueError(f"Unknown pipeline stage: {stage}")
    if state not in EVENT_STATES:
        raise ValueError(f"Unknown pipeline event state: {state}")
    deadline = None
    if write_timeout_seconds is not None:
        timeout = float(write_timeout_seconds)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("write_timeout_seconds must be finite and positive")
        deadline = time.monotonic() + timeout
    if should_skip is not None and deadline is None:
        raise ValueError("a completion guard requires a bounded write timeout")
    now = time.time()
    connection = _connect(db_path) if deadline is None else _connect(db_path, deadline=deadline)
    try:
        with connection:
            if deadline is not None:
                _execute(connection, "BEGIN IMMEDIATE", deadline=deadline)
                if should_skip is not None and should_skip():
                    return
                # No schema/run/event writes occur before the completion guard.
                # executescript could repeat the full busy timeout per statement
                # and implicitly commit away our acquired write lock.
                for statement in _SCHEMA.split(";"):
                    if statement.strip():
                        _execute(connection, statement, deadline=deadline)
                if skip_terminal_stage:
                    latest = _execute(
                        connection,
                        "SELECT state FROM pipeline_events WHERE run_id=? AND stage=? ORDER BY id DESC LIMIT 1",
                        (run_id, stage),
                        deadline=deadline,
                    ).fetchone()
                    if latest is not None and latest[0] in {"complete", "warning", "failed"}:
                        return
                now = time.time()
            _write_pipeline_stage(
                connection,
                run_id,
                stage,
                state,
                message,
                details or {},
                domain_handle,
                keyword,
                slug,
                now,
                deadline=deadline,
            )
            if deadline is not None:
                _execute(connection, "COMMIT", deadline=deadline)
    finally:
        connection.close()


def _write_pipeline_stage(
    connection: sqlite3.Connection,
    run_id: str,
    stage: str,
    state: str,
    message: str,
    details: dict[str, Any],
    domain_handle: str,
    keyword: str,
    slug: str,
    now: float,
    *,
    deadline: float | None = None,
) -> None:
    row = _execute(
        connection,
        "SELECT id FROM pipeline_runs WHERE id = ?",
        (run_id,),
        deadline=deadline,
    ).fetchone()
    if row is None:
        if not domain_handle or not keyword:
            raise ValueError("domain_handle and keyword are required for an unknown run_id")
        _execute(
            connection,
            """
                INSERT INTO pipeline_runs (
                    id, domain_handle, keyword, slug, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'running', ?, ?)
                """,
            (run_id, domain_handle, keyword, slug, now, now),
            deadline=deadline,
        )
    if slug:
        _execute(
            connection,
            "UPDATE pipeline_runs SET updated_at = ?, slug = ? WHERE id = ?",
            (now, slug, run_id),
            deadline=deadline,
        )
    else:
        _execute(
            connection,
            "UPDATE pipeline_runs SET updated_at = ? WHERE id = ?",
            (now, run_id),
            deadline=deadline,
        )
    _insert_event(
        connection,
        run_id,
        stage,
        state,
        message,
        details,
        now,
        deadline=deadline,
    )


def set_pipeline_run_status(
    run_id: str,
    status: str,
    *,
    db_path: Path = PIPELINE_DB,
) -> None:
    """Set the high-level outcome without inventing another workflow stage."""

    now = time.time()
    with _connect(db_path) as connection:
        connection.execute(
            "UPDATE pipeline_runs SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, run_id),
        )


def _insert_event(
    connection: sqlite3.Connection,
    run_id: str,
    stage: str,
    state: str,
    message: str,
    details: dict[str, Any],
    created_at: float,
    *,
    deadline: float | None = None,
) -> None:
    _execute(
        connection,
        """
        INSERT INTO pipeline_events (
            run_id, stage, state, message, details_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            stage,
            state,
            message,
            json.dumps(details, ensure_ascii=False, default=str),
            created_at,
        ),
        deadline=deadline,
    )

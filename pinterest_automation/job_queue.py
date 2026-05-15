"""RankStein Pinterest Automation — Persistent Job Queue (SQLite-backed).

Replaces the previous JSON-file storage. The public API
(``Job``, ``JobStatus``, ``JobQueue``, ``get_job_queue``) is unchanged —
callers keep working without edits.

Why SQLite over JSON
--------------------
The previous backend wrote the entire queue to ``pending_jobs.json`` on every
mutation, guarded by a ``threading.Lock``. That breaks under multi-process
workers (the lock is per-process), is O(n) per write, and silently loses the
DLQ if a write is interrupted between rename and fsync.

SQLite gives us:

- **Atomic dequeue** in a single ``BEGIN IMMEDIATE`` transaction: two workers
  cannot lease the same job.
- **WAL journal mode** so reads (``get_stats``, ``list_pending``) don't block
  writes (``enqueue``, ``dequeue``).
- **Crash-safe writes** via SQLite's own durability guarantees.
- **One-shot migration** of any pre-existing ``pending_jobs.json`` /
  ``dead_letter.json`` / ``completed_jobs.json`` on first init. The legacy
  files are renamed to ``*.migrated`` rather than deleted, so you can verify
  the migration before reclaiming the disk.

The legacy module constants (``QUEUE_FILE``, ``DLQ_FILE``, ``COMPLETED_FILE``)
are still exported because external scripts in ``scripts/oneoff/`` may
reference them. New code should not.
"""

from __future__ import annotations

import json
import logging
import os
import random
import sqlite3
import aiosqlite

import uuid
import asyncio
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from threading import Lock

from .config import QUEUE_DIR, get_config

logger = logging.getLogger("rankstein.queue")

# ── Storage paths ─────────────────────────────────────────────────────────────
DB_FILE = QUEUE_DIR / "jobs.db"

# Legacy file paths — kept as module attrs for backwards compat. The migration
# step below imports their content into SQLite and renames them to .migrated.
QUEUE_FILE = QUEUE_DIR / "pending_jobs.json"
DLQ_FILE = QUEUE_DIR / "dead_letter.json"
COMPLETED_FILE = QUEUE_DIR / "completed_jobs.json"

_COMPLETED_LOG_KEEP = 500
_COMPLETED_TTL_SECONDS = 7 * 86400


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


_PROCESSING_LEASE_TIMEOUT_SECONDS = max(300, _int_env("PINTEREST_PROCESSING_LEASE_TIMEOUT_SECONDS", 20 * 60))
_RETRY_BASE_SECONDS = max(5, _int_env("PINTEREST_RETRY_BASE_SECONDS", 20))
_RETRY_MAX_SECONDS = max(_RETRY_BASE_SECONDS, _int_env("PINTEREST_RETRY_MAX_SECONDS", 5 * 60))


class JobStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    RETRY = "retry"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD = "dead"


@dataclass
class Job:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    type: str = "pin_upload"
    payload: dict = field(default_factory=dict)
    status: str = JobStatus.PENDING.value
    created_at: float = field(default_factory=lambda: datetime.now(UTC).timestamp())
    started_at: float | None = None
    completed_at: float | None = None
    attempt: int = 0
    max_attempts: int = 3
    next_retry_at: float | None = None
    error_log: list[str] = field(default_factory=list)
    result: dict | None = None
    priority: int = 5  # 1 = highest

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Job:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ── Schema ────────────────────────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT    PRIMARY KEY,
    type            TEXT    NOT NULL,
    payload_json    TEXT    NOT NULL,
    status          TEXT    NOT NULL,
    created_at      REAL    NOT NULL,
    started_at      REAL,
    completed_at    REAL,
    attempt         INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 3,
    next_retry_at   REAL,
    error_log_json  TEXT    NOT NULL DEFAULT '[]',
    result_json     TEXT,
    priority        INTEGER NOT NULL DEFAULT 5
);
CREATE INDEX IF NOT EXISTS idx_jobs_status_priority
    ON jobs (status, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_next_retry
    ON jobs (next_retry_at);

CREATE TABLE IF NOT EXISTS dlq (
    id          TEXT PRIMARY KEY,
    job_json    TEXT NOT NULL,
    moved_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS completed_log (
    id              TEXT PRIMARY KEY,
    job_json        TEXT NOT NULL,
    completed_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_completed_log_completed_at
    ON completed_log (completed_at);
"""


# ── Row ↔ Job conversion ──────────────────────────────────────────────────────
def _job_to_row(job: Job) -> tuple:
    return (
        job.id,
        job.type,
        json.dumps(job.payload, ensure_ascii=False),
        job.status,
        job.created_at,
        job.started_at,
        job.completed_at,
        job.attempt,
        job.max_attempts,
        job.next_retry_at,
        json.dumps(job.error_log, ensure_ascii=False),
        json.dumps(job.result, ensure_ascii=False) if job.result is not None else None,
        job.priority,
    )


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        type=row["type"],
        payload=json.loads(row["payload_json"]),
        status=row["status"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        attempt=row["attempt"],
        max_attempts=row["max_attempts"],
        next_retry_at=row["next_retry_at"],
        error_log=json.loads(row["error_log_json"]),
        result=json.loads(row["result_json"]) if row["result_json"] else None,
        priority=row["priority"],
    )


_INSERT_OR_REPLACE_JOB = """
INSERT OR REPLACE INTO jobs (
    id, type, payload_json, status, created_at, started_at, completed_at,
    attempt, max_attempts, next_retry_at, error_log_json, result_json, priority
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


# ── Queue ─────────────────────────────────────────────────────────────────────
class JobQueue:
    """Persistent SQLite-backed job queue.

    Public surface is identical to the previous JSON-backed implementation:
    ``enqueue``, ``enqueue_pin_upload``, ``dequeue``, ``complete``,
    ``retry_or_fail``, ``get_stats``, ``list_pending``, ``purge_completed``.
    """

    def __init__(self, db_file: Path | None = None) -> None:
        self.config = get_config()
        # threading.Lock kept for symmetry with the old API; SQLite itself is
        # the real concurrency boundary thanks to BEGIN IMMEDIATE transactions.
        self._lock = Lock()
        self._db_file = db_file or DB_FILE
        self._db_file.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._migrate_legacy_json()
        self.requeue_stale_processing()

    # ---------- DB plumbing ----------------------------------------------------
    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(
            self._db_file,
            isolation_level=None,  # explicit BEGIN/COMMIT
            check_same_thread=False,
            timeout=30.0,
        )
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @asynccontextmanager
    async def _aconn(self):
        async with aiosqlite.connect(self._db_file, timeout=30.0) as db:
            db.row_factory = aiosqlite.Row
            yield db

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.executescript(_SCHEMA)

    def _migrate_legacy_json(self) -> None:
        """One-shot import of legacy JSON files. Idempotent."""
        for src, importer in (
            (QUEUE_FILE, self._import_legacy_pending),
            (DLQ_FILE, self._import_legacy_dlq),
            (COMPLETED_FILE, self._import_legacy_completed),
        ):
            if not src.exists():
                continue
            try:
                imported = importer(src)
                migrated_path = src.with_suffix(src.suffix + ".migrated")
                src.rename(migrated_path)
                logger.info(
                    f"Migrated {imported} entries from {src.name} -> SQLite. "
                    f"Old file renamed to {migrated_path.name}."
                )
            except Exception:
                logger.exception(f"Failed to migrate {src}; leaving it in place.")

    def _import_legacy_pending(self, path: Path) -> int:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = [_job_to_row(Job.from_dict(j)) for j in data.get("jobs", [])]
        if not rows:
            return 0
        with self._conn() as conn:
            conn.executemany(_INSERT_OR_REPLACE_JOB, rows)
        return len(rows)

    def _import_legacy_dlq(self, path: Path) -> int:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return 0
        with self._conn() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO dlq (id, job_json, moved_at) VALUES (?, ?, ?)",
                [
                    (j["id"], json.dumps(j, ensure_ascii=False), j.get("completed_at") or 0.0)
                    for j in data
                    if isinstance(j, dict) and "id" in j
                ],
            )
        return len(data)

    def _import_legacy_completed(self, path: Path) -> int:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return 0
        with self._conn() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO completed_log (id, job_json, completed_at) VALUES (?, ?, ?)",
                [
                    (j["id"], json.dumps(j, ensure_ascii=False), j.get("completed_at") or 0.0)
                    for j in data
                    if isinstance(j, dict) and "id" in j
                ],
            )
        return len(data)

    # ---------- Public API ----------------------------------------------------
    def enqueue(self, job: Job) -> str:
        with self._lock, self._conn() as conn:
            conn.execute(_INSERT_OR_REPLACE_JOB, _job_to_row(job))
        logger.info(f"Enqueued job {job.id} (type={job.type}, priority={job.priority})")
        return job.id

    async def enqueue_async(self, job: Job) -> str:
        async with self._aconn() as db:
            await db.execute(_INSERT_OR_REPLACE_JOB, _job_to_row(job))
            await db.commit()
        logger.info(f"Enqueued job {job.id} (type={job.type}, priority={job.priority})")
        return job.id
    
    async def enqueue_pin_upload_async(
        self,
        image_path: str,
        title: str,
        description: str,
        link: str,
        alt_text: str = "",
        board_name: str = "",
        priority: int = 5,
        extra: dict | None = None,
    ) -> str:
        extra = extra or {}
        payload = {
            "image_path": image_path,
            "title": title,
            "description": description,
            "link": link,
            "alt_text": alt_text,
            "board_name": board_name or self.config.default_board,
            "extra": extra,
        }
        if extra.get("account_handle"):
            payload["account_handle"] = str(extra["account_handle"]).strip()
        job = Job(
            type="pin_upload",
            payload=payload,
            priority=priority,
            max_attempts=3,
        )
        return await self.enqueue_async(job)

    def enqueue_pin_upload(
        self,
        image_path: str,
        title: str,
        description: str,
        link: str,
        alt_text: str = "",
        board_name: str = "",
        priority: int = 5,
        extra: dict | None = None,
    ) -> str:
        extra = extra or {}
        payload = {
            "image_path": image_path,
            "title": title,
            "description": description,
            "link": link,
            "alt_text": alt_text,
            "board_name": board_name or self.config.default_board,
            "extra": extra,
        }
        if extra.get("account_handle"):
            payload["account_handle"] = str(extra["account_handle"]).strip()
        job = Job(
            type="pin_upload",
            payload=payload,
            priority=priority,
            max_attempts=3,
        )
        return self.enqueue(job)


    def dequeue(self) -> Job | None:
        """Atomically lease the next ready job. Returns None if nothing ready."""
        now = datetime.now(UTC).timestamp()
        with self._lock, self._conn() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE;")
                row = conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status IN (?, ?)
                      AND (next_retry_at IS NULL OR next_retry_at <= ?)
                    ORDER BY priority ASC, created_at ASC
                    LIMIT 1
                    """,
                    (JobStatus.PENDING.value, JobStatus.RETRY.value, now),
                ).fetchone()

                if row is None:
                    conn.execute("COMMIT;")
                    return None

                job = _row_to_job(row)
                job.status = JobStatus.PROCESSING.value
                job.started_at = now
                job.attempt += 1

                conn.execute(
                    """
                    UPDATE jobs
                       SET status = ?, started_at = ?, attempt = ?
                     WHERE id = ?
                    """,
                    (job.status, job.started_at, job.attempt, job.id),
                )
                conn.execute("COMMIT;")
            except sqlite3.Error:
                conn.execute("ROLLBACK;")
                raise

        logger.info(f"Dequeued job {job.id} (attempt={job.attempt})")
        return job

    async def dequeue_async(self) -> Job | None:
        """Atomically lease the next ready job. Returns None if nothing ready."""
        now = datetime.now(UTC).timestamp()
        async with self._aconn() as db:
            try:
                await db.execute("BEGIN IMMEDIATE;")
                cursor = await db.execute(
                    """
                    SELECT * FROM jobs
                    WHERE (status = ? OR (status = ? AND next_retry_at <= ?))
                    ORDER BY priority ASC, created_at ASC
                    LIMIT 1
                    """,
                    (JobStatus.PENDING.value, JobStatus.RETRY.value, now),
                )
                row = await cursor.fetchone()
                if not row:
                    await db.execute("COMMIT;")
                    return None

                job = _row_to_job(row)
                job.status = JobStatus.PROCESSING.value
                job.started_at = now
                job.attempt += 1

                await db.execute(
                    """
                    UPDATE jobs
                       SET status = ?, started_at = ?, attempt = ?
                     WHERE id = ?
                    """,
                    (job.status, job.started_at, job.attempt, job.id),
                )
                await db.commit()
                logger.info(f"Dequeued job {job.id} (attempt={job.attempt})")
                return job
            except Exception:
                await db.rollback()
                raise

    def requeue_stale_processing(self, max_age_seconds: int = _PROCESSING_LEASE_TIMEOUT_SECONDS) -> int:
        """Return abandoned processing jobs to retry so crashes do not strand work."""
        cutoff = datetime.now(UTC).timestamp() - max_age_seconds
        now = datetime.now(UTC).timestamp()
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM jobs
                WHERE status = ?
                  AND started_at IS NOT NULL
                  AND started_at <= ?
                """,
                (JobStatus.PROCESSING.value, cutoff),
            ).fetchall()
            if not rows:
                return 0

            try:
                conn.execute("BEGIN IMMEDIATE;")
                for row in rows:
                    job = _row_to_job(row)
                    job.status = JobStatus.RETRY.value
                    job.next_retry_at = now
                    job.error_log.append("Recovered abandoned processing lease")
                    conn.execute(
                        """
                        UPDATE jobs
                           SET status = ?, next_retry_at = ?, error_log_json = ?
                         WHERE id = ?
                        """,
                        (
                            job.status,
                            job.next_retry_at,
                            json.dumps(job.error_log, ensure_ascii=False),
                            job.id,
                        ),
                    )
                conn.execute("COMMIT;")
            except sqlite3.Error:
                conn.execute("ROLLBACK;")
                raise

        logger.warning("Requeued %s stale processing job(s)", len(rows))
        return len(rows)

    async def requeue_stale_processing_async(self, max_age_seconds: int = _PROCESSING_LEASE_TIMEOUT_SECONDS) -> int:
        return await asyncio.to_thread(self.requeue_stale_processing, max_age_seconds)

    def complete(self, job_id: str, result: dict) -> None:
        completed_at = datetime.now(UTC).timestamp()
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return
            job = _row_to_job(row)
            job.status = JobStatus.COMPLETED.value
            job.completed_at = completed_at
            job.result = result

            try:
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute(
                    "INSERT OR REPLACE INTO completed_log (id, job_json, completed_at) VALUES (?, ?, ?)",
                    (job.id, json.dumps(job.to_dict(), ensure_ascii=False), completed_at),
                )
                # Trim completed_log to most recent N rows (cheap, runs every complete)
                conn.execute(
                    """
                    DELETE FROM completed_log
                    WHERE id NOT IN (
                        SELECT id FROM completed_log
                        ORDER BY completed_at DESC
                        LIMIT ?
                    )
                    """,
                    (_COMPLETED_LOG_KEEP,),
                )
                conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
                conn.execute("COMMIT;")
            except sqlite3.Error:
                conn.execute("ROLLBACK;")
                raise
        logger.info(f"Job {job_id} completed")

    async def complete_async(self, job_id: str, result: dict) -> None:
        completed_at = datetime.now(UTC).timestamp()
        async with self._aconn() as db:
            cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = await cursor.fetchone()
            if row is None:
                return
            job = _row_to_job(row)
            job.status = JobStatus.COMPLETED.value
            job.completed_at = completed_at
            job.result = result

            try:
                await db.execute("BEGIN IMMEDIATE;")
                await db.execute(
                    "INSERT OR REPLACE INTO completed_log (id, job_json, completed_at) VALUES (?, ?, ?)",
                    (job.id, json.dumps(job.to_dict(), ensure_ascii=False), completed_at),
                )
                await db.execute(
                    """
                    DELETE FROM completed_log
                    WHERE id NOT IN (
                        SELECT id FROM completed_log
                        ORDER BY completed_at DESC
                        LIMIT ?
                    )
                    """,
                    (_COMPLETED_LOG_KEEP,),
                )
                await db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
                await db.commit()
                logger.info(f"Job {job_id} completed")
            except Exception:
                await db.rollback()
                raise

    def retry_or_fail(self, job_id: str, error: str) -> None:
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return
            job = _row_to_job(row)
            job.error_log.append(f"Attempt {job.attempt}: {error}")

            if job.attempt >= job.max_attempts:
                job.status = JobStatus.DEAD.value
                try:
                    conn.execute("BEGIN IMMEDIATE;")
                    conn.execute(
                        "INSERT OR REPLACE INTO dlq (id, job_json, moved_at) VALUES (?, ?, ?)",
                        (
                            job.id,
                            json.dumps(job.to_dict(), ensure_ascii=False),
                            datetime.now(UTC).timestamp(),
                        ),
                    )
                    conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
                    conn.execute("COMMIT;")
                except sqlite3.Error:
                    conn.execute("ROLLBACK;")
                    raise
                logger.error(f"Job {job_id} moved to DLQ after {job.attempt} attempts")
            else:
                # Exponential backoff with bounded ceiling + full jitter so multiple
                # workers with failed jobs don't thunder-herd back at the same second.
                backoff = min(_RETRY_MAX_SECONDS, (2 ** (job.attempt - 1)) * _RETRY_BASE_SECONDS)
                backoff = backoff + random.uniform(0, 0.5 * backoff)  # +0–50% jitter
                job.next_retry_at = datetime.now(UTC).timestamp() + backoff
                job.status = JobStatus.RETRY.value
                conn.execute(
                    """
                    UPDATE jobs
                       SET status = ?, next_retry_at = ?, error_log_json = ?
                     WHERE id = ?
                    """,
                    (
                        job.status,
                        job.next_retry_at,
                        json.dumps(job.error_log, ensure_ascii=False),
                        job_id,
                    ),
                )
                logger.warning(f"Job {job_id} scheduled for retry in {backoff}s (attempt {job.attempt})")

    async def retry_or_fail_async(self, job_id: str, error: str) -> None:
        now = datetime.now(UTC).timestamp()
        async with self._aconn() as db:
            cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = await cursor.fetchone()
            if row is None:
                return
            job = _row_to_job(row)
            job.error_log.append(f"Attempt {job.attempt}: {error}")

            if job.attempt >= job.max_attempts:
                job.status = JobStatus.DEAD.value
                try:
                    await db.execute("BEGIN IMMEDIATE;")
                    await db.execute(
                        "INSERT OR REPLACE INTO dlq (id, job_json, moved_at) VALUES (?, ?, ?)",
                        (
                            job.id,
                            json.dumps(job.to_dict(), ensure_ascii=False),
                            now,
                        ),
                    )
                    await db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
                    await db.commit()
                    logger.error(f"Job {job_id} moved to DLQ after {job.attempt} attempts")
                except Exception:
                    await db.rollback()
                    raise
            else:
                backoff = min(_RETRY_MAX_SECONDS, (2 ** (job.attempt - 1)) * _RETRY_BASE_SECONDS)
                backoff = backoff + random.uniform(0, 0.5 * backoff)
                job.next_retry_at = now + backoff
                job.status = JobStatus.RETRY.value
                await db.execute(
                    """
                    UPDATE jobs
                       SET status = ?, next_retry_at = ?, error_log_json = ?
                     WHERE id = ?
                    """,
                    (
                        job.status,
                        job.next_retry_at,
                        json.dumps(job.error_log, ensure_ascii=False),
                        job_id,
                    ),
                )
                await db.commit()
                logger.warning(f"Job {job_id} scheduled for retry in {backoff:.1f}s (attempt {job.attempt})")

    def get_stats(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
            counts = {r["status"]: r["n"] for r in rows}
            total = sum(counts.values())
            dlq_size = conn.execute("SELECT COUNT(*) AS n FROM dlq").fetchone()["n"]
        return {
            "total": total,
            "by_status": counts,
            "dlq_size": dlq_size,
        }

    async def get_stats_async(self) -> dict:
        async with self._aconn() as db:
            cursor = await db.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
            rows = await cursor.fetchall()
            counts = {r["status"]: r["n"] for r in rows}
            total = sum(counts.values())
            cursor = await db.execute("SELECT COUNT(*) AS n FROM dlq")
            row = await cursor.fetchone()
            dlq_size = row["n"] if row else 0
        return {
            "total": total,
            "by_status": counts,
            "dlq_size": dlq_size,
        }

    def list_pending(self) -> list[Job]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status IN (?, ?) ORDER BY priority ASC, created_at ASC",
                (JobStatus.PENDING.value, JobStatus.RETRY.value),
            ).fetchall()
        return [_row_to_job(r) for r in rows]

    async def list_pending_async(self) -> list[Job]:
        async with self._aconn() as db:
            cursor = await db.execute(
                "SELECT * FROM jobs WHERE status IN (?, ?) ORDER BY priority ASC, created_at ASC",
                (JobStatus.PENDING.value, JobStatus.RETRY.value),
            )
            rows = await cursor.fetchall()
        return [_row_to_job(r) for r in rows]

    def image_path_already_queued(self, image_path: str) -> bool:
        """Return True if a pin_upload job for this exact image_path is already
        pending, processing, or scheduled for retry. Prevents duplicate enqueues
        when the remaster folder enqueue step runs on each boot while the
        supervisor has not yet processed earlier jobs.
        """
        import json
        norm = str(Path(image_path).resolve())
        # json.dumps() adds surrounding quotes, so we strip them to match the inner string
        # This handles Windows backslashes being escaped as double backslashes in JSON
        raw_escaped = json.dumps(image_path)[1:-1]
        norm_escaped = json.dumps(norm)[1:-1]

        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id FROM jobs
                WHERE type = 'pin_upload'
                  AND status IN (?, ?, ?)
                  AND payload_json LIKE ?
                LIMIT 1
                """,
                (
                    JobStatus.PENDING.value,
                    JobStatus.PROCESSING.value,
                    JobStatus.RETRY.value,
                    f'%"{raw_escaped}"%',
                ),
            ).fetchone()
            if row:
                return True
            # Also check the resolved (normalized) path in case stored differently
            row2 = conn.execute(
                """
                SELECT id FROM jobs
                WHERE type = 'pin_upload'
                  AND status IN (?, ?, ?)
                  AND payload_json LIKE ?
                LIMIT 1
                """,
                (
                    JobStatus.PENDING.value,
                    JobStatus.PROCESSING.value,
                    JobStatus.RETRY.value,
                    f'%"{norm_escaped}"%',
                ),
            ).fetchone()
            return row2 is not None

    async def image_path_already_queued_async(self, image_path: str) -> bool:
        return await asyncio.to_thread(self.image_path_already_queued, image_path)

    def purge_completed(self) -> None:
        """Delete completed_log entries older than the TTL."""
        cutoff = datetime.now(UTC).timestamp() - _COMPLETED_TTL_SECONDS
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM completed_log WHERE completed_at < ?", (cutoff,))


# ── Singleton ────────────────────────────────────────────────────────────────
_job_queue: JobQueue | None = None
_job_queues: dict[str, JobQueue] = {}


def get_job_queue(db_file: Path | None = None, domain_handle: str | None = None) -> JobQueue:
    global _job_queue, _job_queues
    if domain_handle:
        from rankstein.domain import get_registry

        try:
            domain = get_registry().get(domain_handle)
            db_file = domain.root / "jobs.db"
        except Exception as e:
            logger.warning("Failed to resolve domain '%s' for job queue: %s", domain_handle, e)

    if db_file:
        db_key = str(db_file.resolve())
        if db_key not in _job_queues:
            _job_queues[db_key] = JobQueue(db_file=db_file)
        return _job_queues[db_key]

    if _job_queue is None:
        _job_queue = JobQueue()
    return _job_queue


def _reset_job_queue_singleton() -> None:
    """Test-only: clear the cached singletons so a new DB path can take effect."""
    global _job_queue, _job_queues
    _job_queue = None
    _job_queues.clear()

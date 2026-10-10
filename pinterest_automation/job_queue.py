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

import asyncio
import json
import logging
import os
import random
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from threading import Lock

import aiosqlite

from .config import QUEUE_DIR, get_config, normalize_board_name

logger = logging.getLogger("rankstein.queue")

# ── Storage paths ─────────────────────────────────────────────────────────────
DB_FILE = Path(os.environ.get("PINTEREST_QUEUE_DB_FILE") or QUEUE_DIR / "jobs.db")

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
_SQLITE_TIMEOUT_SECONDS = max(30, _int_env("PINTEREST_SQLITE_TIMEOUT_SECONDS", 120))


class JobStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    RETRY = "retry"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD = "dead"
    HELD = "held"


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


def _job_identity(job: Job) -> tuple[str, str, str, str, str, str, str]:
    payload = job.payload or {}
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    return (
        job.type or "",
        str(payload.get("image_path") or ""),
        str(payload.get("pin_url") or ""),
        str(payload.get("link") or ""),
        str(payload.get("account_handle") or extra.get("account_handle") or ""),
        str(payload.get("board_name") or ""),
        str(payload.get("title") or ""),
    )


def _normalize_job_payload_board(job: Job) -> None:
    if isinstance(job.payload, dict) and "board_name" in job.payload:
        job.payload["board_name"] = normalize_board_name(job.payload.get("board_name"))


def _dedupe_identity_is_specific(identity: tuple[str, str, str, str, str, str, str]) -> bool:
    """Only dedupe jobs that carry a real Pinterest publication identity."""
    return any(part for part in identity[1:])


_DUPLICATE_ACTIVE_SQL = """
SELECT id FROM jobs
WHERE type = ?
  AND COALESCE(json_extract(payload_json, '$.image_path'), '') = ?
  AND COALESCE(json_extract(payload_json, '$.pin_url'), '') = ?
  AND COALESCE(json_extract(payload_json, '$.link'), '') = ?
  AND COALESCE(
        json_extract(payload_json, '$.account_handle'),
        json_extract(payload_json, '$.extra.account_handle'),
        ''
      ) = ?
  AND COALESCE(json_extract(payload_json, '$.board_name'), '') = ?
  AND COALESCE(json_extract(payload_json, '$.title'), '') = ?
LIMIT 1
"""


_DUPLICATE_DLQ_SQL = """
SELECT id FROM dlq
WHERE COALESCE(json_extract(job_json, '$.type'), '') = ?
  AND COALESCE(json_extract(job_json, '$.payload.image_path'), '') = ?
  AND COALESCE(json_extract(job_json, '$.payload.pin_url'), '') = ?
  AND COALESCE(json_extract(job_json, '$.payload.link'), '') = ?
  AND COALESCE(
        json_extract(job_json, '$.payload.account_handle'),
        json_extract(job_json, '$.payload.extra.account_handle'),
        ''
      ) = ?
  AND COALESCE(json_extract(job_json, '$.payload.board_name'), '') = ?
  AND COALESCE(json_extract(job_json, '$.payload.title'), '') = ?
LIMIT 1
"""


def _find_dedupe_match_sync(conn: sqlite3.Connection, job: Job) -> str | None:
    payload = job.payload or {}
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}

    # 1. Idempotency Key (e.g. from article remaster batches)
    idempotency_key = extra.get("idempotency_key") if isinstance(extra, dict) else None
    if idempotency_key:
        row = conn.execute(
            """
            SELECT id FROM jobs WHERE json_extract(payload_json, '$.extra.idempotency_key') = ?
            UNION ALL
            SELECT id FROM completed_log WHERE json_extract(job_json, '$.payload.extra.idempotency_key') = ?
            UNION ALL
            SELECT id FROM dlq WHERE json_extract(job_json, '$.payload.extra.idempotency_key') = ?
            LIMIT 1
            """,
            (str(idempotency_key), str(idempotency_key), str(idempotency_key)),
        ).fetchone()
        if row:
            return str(row["id"])

    # 2. CROSS_SAVE_AMPLIFIER role for pin_save
    if job.type == "pin_save":
        account = str(payload.get("account_handle") or extra.get("account_handle") or "").strip()
        pin_url = str(payload.get("pin_url") or "").strip()
        src_account = str(payload.get("source_account") or payload.get("originator_account") or "").strip()

        # Rule 1: No self-cross-save
        if src_account and account and src_account == account:
            logger.warning(
                "[CROSS_SAVE_AMPLIFIER] Blocked self-cross-save: %s cannot save own pin %s",
                account,
                pin_url,
            )
            return str(job.id)

        # Rule 2: No duplicate save of the same pin_url by the same account
        if account and pin_url:
            row = conn.execute(
                """
                SELECT id FROM jobs
                WHERE type = 'pin_save'
                  AND json_extract(payload_json, '$.account_handle') = ?
                  AND json_extract(payload_json, '$.pin_url') = ?
                UNION ALL
                SELECT id FROM completed_log
                WHERE json_extract(job_json, '$.type') = 'pin_save'
                  AND json_extract(job_json, '$.payload.account_handle') = ?
                  AND json_extract(job_json, '$.payload.pin_url') = ?
                UNION ALL
                SELECT id FROM dlq
                WHERE json_extract(job_json, '$.type') = 'pin_save'
                  AND json_extract(job_json, '$.payload.account_handle') = ?
                  AND json_extract(job_json, '$.payload.pin_url') = ?
                LIMIT 1
                """,
                (account, pin_url, account, pin_url, account, pin_url),
            ).fetchone()
            if row:
                logger.info(
                    "[CROSS_SAVE_AMPLIFIER] Skipped duplicate save: %s already saved %s (existing=%s)",
                    account,
                    pin_url,
                    row["id"],
                )
                return str(row["id"])

    # 3. PRIMARY_ORIGINATOR role for pin_upload
    if job.type == "pin_upload":
        image_path = str(payload.get("image_path") or "").strip()
        if image_path:
            norm_path = str(Path(image_path).resolve())
            row = conn.execute(
                """
                SELECT id FROM jobs
                WHERE type = 'pin_upload'
                  AND (json_extract(payload_json, '$.image_path') = ? OR json_extract(payload_json, '$.image_path') = ?)
                UNION ALL
                SELECT id FROM completed_log
                WHERE json_extract(job_json, '$.type') = 'pin_upload'
                  AND (json_extract(job_json, '$.payload.image_path') = ? OR json_extract(job_json, '$.payload.image_path') = ?)
                UNION ALL
                SELECT id FROM dlq
                WHERE json_extract(job_json, '$.type') = 'pin_upload'
                  AND (json_extract(job_json, '$.payload.image_path') = ? OR json_extract(job_json, '$.payload.image_path') = ?)
                LIMIT 1
                """,
                (image_path, norm_path, image_path, norm_path, image_path, norm_path),
            ).fetchone()
            if row:
                logger.info(
                    "[PRIMARY_ORIGINATOR] Skipped duplicate upload for %s (existing=%s)",
                    image_path,
                    row["id"],
                )
                return str(row["id"])

    # 4. Standard duplicate identity check
    identity = _job_identity(job)
    if _dedupe_identity_is_specific(identity):
        existing = conn.execute(_DUPLICATE_ACTIVE_SQL, identity).fetchone()
        if existing:
            return str(existing["id"])
        dead = conn.execute(_DUPLICATE_DLQ_SQL, identity).fetchone()
        if dead:
            return str(dead["id"])
    return None


async def _find_dedupe_match_async(db, job: Job) -> str | None:
    payload = job.payload or {}
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}

    # 1. Idempotency Key (e.g. from article remaster batches)
    idempotency_key = extra.get("idempotency_key") if isinstance(extra, dict) else None
    if idempotency_key:
        cursor = await db.execute(
            """
            SELECT id FROM jobs WHERE json_extract(payload_json, '$.extra.idempotency_key') = ?
            UNION ALL
            SELECT id FROM completed_log WHERE json_extract(job_json, '$.payload.extra.idempotency_key') = ?
            UNION ALL
            SELECT id FROM dlq WHERE json_extract(job_json, '$.payload.extra.idempotency_key') = ?
            LIMIT 1
            """,
            (str(idempotency_key), str(idempotency_key), str(idempotency_key)),
        )
        row = await cursor.fetchone()
        if row:
            return str(row["id"])

    # 2. CROSS_SAVE_AMPLIFIER role for pin_save
    if job.type == "pin_save":
        account = str(payload.get("account_handle") or extra.get("account_handle") or "").strip()
        pin_url = str(payload.get("pin_url") or "").strip()
        src_account = str(payload.get("source_account") or payload.get("originator_account") or "").strip()

        # Rule 1: No self-cross-save
        if src_account and account and src_account == account:
            logger.warning(
                "[CROSS_SAVE_AMPLIFIER] Blocked self-cross-save: %s cannot save own pin %s",
                account,
                pin_url,
            )
            return str(job.id)

        # Rule 2: No duplicate save of the same pin_url by the same account
        if account and pin_url:
            cursor = await db.execute(
                """
                SELECT id FROM jobs
                WHERE type = 'pin_save'
                  AND json_extract(payload_json, '$.account_handle') = ?
                  AND json_extract(payload_json, '$.pin_url') = ?
                UNION ALL
                SELECT id FROM completed_log
                WHERE json_extract(job_json, '$.type') = 'pin_save'
                  AND json_extract(job_json, '$.payload.account_handle') = ?
                  AND json_extract(job_json, '$.payload.pin_url') = ?
                UNION ALL
                SELECT id FROM dlq
                WHERE json_extract(job_json, '$.type') = 'pin_save'
                  AND json_extract(job_json, '$.payload.account_handle') = ?
                  AND json_extract(job_json, '$.payload.pin_url') = ?
                LIMIT 1
                """,
                (account, pin_url, account, pin_url, account, pin_url),
            )
            row = await cursor.fetchone()
            if row:
                logger.info(
                    "[CROSS_SAVE_AMPLIFIER] Skipped duplicate save: %s already saved %s (existing=%s)",
                    account,
                    pin_url,
                    row["id"],
                )
                return str(row["id"])

    # 3. PRIMARY_ORIGINATOR role for pin_upload
    if job.type == "pin_upload":
        image_path = str(payload.get("image_path") or "").strip()
        if image_path:
            norm_path = str(Path(image_path).resolve())
            cursor = await db.execute(
                """
                SELECT id FROM jobs
                WHERE type = 'pin_upload'
                  AND (json_extract(payload_json, '$.image_path') = ? OR json_extract(payload_json, '$.image_path') = ?)
                UNION ALL
                SELECT id FROM completed_log
                WHERE json_extract(job_json, '$.type') = 'pin_upload'
                  AND (json_extract(job_json, '$.payload.image_path') = ? OR json_extract(job_json, '$.payload.image_path') = ?)
                UNION ALL
                SELECT id FROM dlq
                WHERE json_extract(job_json, '$.type') = 'pin_upload'
                  AND (json_extract(job_json, '$.payload.image_path') = ? OR json_extract(job_json, '$.payload.image_path') = ?)
                LIMIT 1
                """,
                (image_path, norm_path, image_path, norm_path, image_path, norm_path),
            )
            row = await cursor.fetchone()
            if row:
                logger.info(
                    "[PRIMARY_ORIGINATOR] Skipped duplicate upload for %s (existing=%s)",
                    image_path,
                    row["id"],
                )
                return str(row["id"])

    # 4. Standard duplicate identity check
    identity = _job_identity(job)
    if _dedupe_identity_is_specific(identity):
        cursor = await db.execute(_DUPLICATE_ACTIVE_SQL, identity)
        existing = await cursor.fetchone()
        if existing:
            return str(existing["id"])
        cursor = await db.execute(_DUPLICATE_DLQ_SQL, identity)
        dead = await cursor.fetchone()
        if dead:
            return str(dead["id"])
    return None


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
        self._async_db_lock = asyncio.Lock()
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
            timeout=float(_SQLITE_TIMEOUT_SECONDS),
        )
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {_SQLITE_TIMEOUT_SECONDS * 1000};")
        try:
            yield conn
        finally:
            conn.close()

    @asynccontextmanager
    async def _aconn(self):
        async with self._async_db_lock:
            async with aiosqlite.connect(self._db_file, timeout=float(_SQLITE_TIMEOUT_SECONDS)) as db:
                db.row_factory = aiosqlite.Row
                await db.execute(f"PRAGMA busy_timeout = {_SQLITE_TIMEOUT_SECONDS * 1000};")
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
        jobs = [Job.from_dict(j) for j in data.get("jobs", [])]
        for job in jobs:
            _normalize_job_payload_board(job)
        rows = [_job_to_row(job) for job in jobs]
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
                    (
                        j["id"],
                        json.dumps(self._normalized_job_dict(j), ensure_ascii=False),
                        j.get("completed_at") or 0.0,
                    )
                    for j in data
                    if isinstance(j, dict) and "id" in j
                ],
            )
        return len(data)

    @staticmethod
    def _normalized_job_dict(job_data: dict) -> dict:
        payload = job_data.get("payload")
        if isinstance(payload, dict) and "board_name" in payload:
            payload["board_name"] = normalize_board_name(payload.get("board_name"))
        return job_data

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
        _normalize_job_payload_board(job)
        with self._lock, self._conn() as conn:
            match_id = _find_dedupe_match_sync(conn, job)
            if match_id:
                logger.info("Skipped duplicate job %s (existing=%s)", job.id, match_id)
                return match_id
            conn.execute(_INSERT_OR_REPLACE_JOB, _job_to_row(job))
        logger.info(f"Enqueued job {job.id} (type={job.type}, priority={job.priority})")
        return job.id

    async def enqueue_async(self, job: Job) -> str:
        _normalize_job_payload_board(job)
        async with self._aconn() as db:
            match_id = await _find_dedupe_match_async(db, job)
            if match_id:
                logger.info("Skipped duplicate job %s (existing=%s)", job.id, match_id)
                return match_id
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
            "board_name": normalize_board_name(board_name or self.config.default_board),
            "extra": extra,
        }
        if extra.get("account_handle"):
            payload["account_handle"] = str(extra["account_handle"]).strip()
        if extra.get("domain_handle"):
            payload["domain_handle"] = str(extra["domain_handle"]).strip()
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
            "board_name": normalize_board_name(board_name or self.config.default_board),
            "extra": extra,
        }
        if extra.get("account_handle"):
            payload["account_handle"] = str(extra["account_handle"]).strip()
        if extra.get("domain_handle"):
            payload["domain_handle"] = str(extra["domain_handle"]).strip()
        job = Job(
            type="pin_upload",
            payload=payload,
            priority=priority,
            max_attempts=3,
        )
        return self.enqueue(job)

    def dequeue(self, locked_keys: set[str] | None = None, default_account: str = "rida") -> Job | None:
        """Atomically lease the next ready job, skipping those matching locked keys."""
        now = datetime.now(UTC).timestamp()

        exclude_sql = ""
        params = [JobStatus.PENDING.value, JobStatus.RETRY.value, now]

        if locked_keys:
            clauses = []
            for account_handle in locked_keys:
                clauses.append(
                    """
                    NOT (
                        json_extract(payload_json, '$.account_handle') = ?
                        OR (? = ? AND json_extract(payload_json, '$.account_handle') IS NULL)
                    )
                    """
                )
                params.extend([account_handle, default_account, account_handle])
            if clauses:
                exclude_sql = " AND " + " AND ".join(clauses)

        with self._lock, self._conn() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE;")
                query = f"""
                    SELECT * FROM jobs
                    WHERE status IN (?, ?)
                      AND (next_retry_at IS NULL OR next_retry_at <= ?)
                      {exclude_sql}
                    ORDER BY priority ASC, created_at ASC
                    LIMIT 1
                """
                row = conn.execute(query, params).fetchone()

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

    async def dequeue_async(
        self, locked_keys: set[str] | None = None, default_account: str = "rida"
    ) -> Job | None:
        """Atomically lease the next ready job asynchronously, skipping those matching locked keys."""
        now = datetime.now(UTC).timestamp()

        exclude_sql = ""
        params = [JobStatus.PENDING.value, JobStatus.RETRY.value, now]

        if locked_keys:
            clauses = []
            for account_handle in locked_keys:
                clauses.append(
                    """
                    NOT (
                        json_extract(payload_json, '$.account_handle') = ?
                        OR (? = ? AND json_extract(payload_json, '$.account_handle') IS NULL)
                    )
                    """
                )
                params.extend([account_handle, default_account, account_handle])
            if clauses:
                exclude_sql = " AND " + " AND ".join(clauses)

        async with self._aconn() as db:
            try:
                await db.execute("BEGIN IMMEDIATE;")
                query = f"""
                    SELECT * FROM jobs
                    WHERE status IN (?, ?)
                      AND (next_retry_at IS NULL OR next_retry_at <= ?)
                      {exclude_sql}
                    ORDER BY priority ASC, created_at ASC
                    LIMIT 1
                """
                cursor = await db.execute(query, params)
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

    async def requeue_stale_processing_async(
        self, max_age_seconds: int = _PROCESSING_LEASE_TIMEOUT_SECONDS
    ) -> int:
        return await asyncio.to_thread(self.requeue_stale_processing, max_age_seconds)

    def complete(self, job_id: str, result: dict) -> None:
        completed_at = datetime.now(UTC).timestamp()
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return
            job = _row_to_job(row)
            if job.status == JobStatus.HELD.value:
                return
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
            if job.status == JobStatus.HELD.value:
                return
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

    def complete_from_dlq(self, job_id: str, result: dict) -> bool:
        """Reconcile a dead-lettered job after independent success verification."""
        completed_at = datetime.now(UTC).timestamp()
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT job_json FROM dlq WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return False

            job = Job.from_dict(json.loads(row["job_json"]))
            job.status = JobStatus.COMPLETED.value
            job.completed_at = completed_at
            job.result = result
            try:
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute(
                    "INSERT OR REPLACE INTO completed_log (id, job_json, completed_at) VALUES (?, ?, ?)",
                    (job.id, json.dumps(job.to_dict(), ensure_ascii=False), completed_at),
                )
                conn.execute("DELETE FROM dlq WHERE id = ?", (job_id,))
                conn.execute("COMMIT;")
            except sqlite3.Error:
                conn.execute("ROLLBACK;")
                raise
        logger.info("Reconciled independently verified DLQ job %s as completed", job_id)
        return True

    def retry_or_fail(self, job_id: str, error: str) -> None:
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return
            job = _row_to_job(row)
            if job.status == JobStatus.HELD.value:
                return
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
                backoff = backoff + random.uniform(0, 0.5 * backoff)  # +0-50% jitter
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
            if job.status == JobStatus.HELD.value:
                return
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

    def fail(self, job_id: str, error: str) -> None:
        """Immediately move a job to DLQ without further retries."""
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return
            job = _row_to_job(row)
            job.error_log.append(f"Fatal error: {error}")
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
            logger.error(f"Job {job_id} moved to DLQ: {error}")

    async def fail_async(self, job_id: str, error: str) -> None:
        await asyncio.to_thread(self.fail, job_id, error)

    def hold_campaign_jobs(self, job_ids: list[str], *, pipeline_run_id: str, reason: str) -> dict:
        """Atomically quarantine exact, unleased remaster jobs without deleting them.

        Held rows cannot be dequeued and cannot be released by routine retry
        handling. Replacement creative must receive fresh campaign proof; this
        API intentionally provides no generic automatic unhold operation.
        """
        ids = [str(job_id).strip() for job_id in job_ids]
        if not ids or any(not job_id for job_id in ids) or len(set(ids)) != len(ids):
            raise ValueError("Hold requires distinct, explicit job IDs")
        if not pipeline_run_id.strip() or not reason.strip():
            raise ValueError("Hold requires an exact pipeline run and a reason")
        with self._lock, self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                selected = []
                for job_id in ids:
                    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
                    if row is None:
                        raise ValueError(f"Job {job_id} is missing or already terminal")
                    job = _row_to_job(row)
                    extra = job.payload.get("extra") or {}
                    if (
                        not isinstance(extra, dict)
                        or extra.get("pipeline_run_id") != pipeline_run_id
                        or extra.get("campaign_type") != "article_remaster_pairs"
                    ):
                        raise ValueError(f"Job {job_id} does not belong to the requested remaster run")
                    if job.status not in {
                        JobStatus.PENDING.value,
                        JobStatus.RETRY.value,
                        JobStatus.HELD.value,
                    }:
                        raise ValueError(f"Job {job_id} is leased or terminal; refusing to overwrite it")
                    if job.status != JobStatus.HELD.value:
                        job.error_log.append(f"Source-quality hold: {reason.strip()[:500]}")
                    selected.append(job)
                for job in selected:
                    conn.execute(
                        "UPDATE jobs SET status = ?, next_retry_at = NULL, error_log_json = ? WHERE id = ?",
                        (JobStatus.HELD.value, json.dumps(job.error_log, ensure_ascii=False), job.id),
                    )
                conn.execute("COMMIT;")
            except Exception:
                conn.execute("ROLLBACK;")
                raise
        logger.warning("Held %d exact remaster jobs for run %s", len(ids), pipeline_run_id)
        return {"held": len(ids), "job_ids": ids, "pipeline_run_id": pipeline_run_id}

    def release(self, job_id: str, delay_seconds: float = 15.0) -> None:
        """Release a leased job back to the queue (e.g. if lock couldn't be acquired).
        Resets status to 'pending', schedules next retry, and decrements attempt count.
        """
        now = datetime.now(UTC).timestamp()
        next_retry = now + delay_seconds
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return
            job = _row_to_job(row)
            if job.status == JobStatus.HELD.value:
                return
            new_attempt = max(0, job.attempt - 1)
            try:
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute(
                    """
                    UPDATE jobs
                       SET status = ?, next_retry_at = ?, attempt = ?
                     WHERE id = ?
                    """,
                    (JobStatus.PENDING.value, next_retry, new_attempt, job_id),
                )
                conn.execute("COMMIT;")
            except sqlite3.Error:
                conn.execute("ROLLBACK;")
                raise
        logger.info(
            f"Released job {job_id} back to queue (retry in {delay_seconds}s, attempt reset to {new_attempt})"
        )

    async def release_async(self, job_id: str, delay_seconds: float = 15.0) -> None:
        """Release a leased job back to the queue asynchronously.
        Resets status to 'pending', schedules next retry, and decrements attempt count.
        """
        now = datetime.now(UTC).timestamp()
        next_retry = now + delay_seconds
        async with self._aconn() as db:
            cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = await cursor.fetchone()
            if row is None:
                return
            job = _row_to_job(row)
            if job.status == JobStatus.HELD.value:
                return
            new_attempt = max(0, job.attempt - 1)
            try:
                await db.execute("BEGIN IMMEDIATE;")
                await db.execute(
                    """
                    UPDATE jobs
                       SET status = ?, next_retry_at = ?, attempt = ?
                     WHERE id = ?
                    """,
                    (JobStatus.PENDING.value, next_retry, new_attempt, job_id),
                )
                await db.commit()
                logger.info(
                    f"Released job {job_id} back to queue (retry in {delay_seconds}s, attempt reset to {new_attempt})"
                )
            except Exception:
                await db.rollback()
                raise

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

    def get_job_outcome(self, job_id: str) -> dict:
        """Return the current or terminal state for a job across all queue tables."""

        def outcome(job: Job, state: str) -> dict:
            return {
                "found": True,
                "state": state,
                "type": job.type,
                "priority": job.priority,
                "payload": job.payload,
                "result": job.result,
                "errors": job.error_log,
            }

        with self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is not None:
                job = _row_to_job(row)
                return outcome(job, job.status)

            row = conn.execute(
                "SELECT job_json FROM completed_log WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is not None:
                job = Job.from_dict(json.loads(row["job_json"]))
                return outcome(job, JobStatus.COMPLETED.value)

            row = conn.execute("SELECT job_json FROM dlq WHERE id = ?", (job_id,)).fetchone()
            if row is not None:
                job = Job.from_dict(json.loads(row["job_json"]))
                return outcome(job, JobStatus.DEAD.value)

        return {
            "found": False,
            "state": "missing",
            "type": None,
            "priority": None,
            "payload": {},
            "result": None,
            "errors": [],
        }

    async def get_job_outcome_async(self, job_id: str) -> dict:
        return await asyncio.to_thread(self.get_job_outcome, job_id)

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
                  AND status IN (?, ?, ?, ?)
                  AND payload_json LIKE ?
                LIMIT 1
                """,
                (
                    JobStatus.PENDING.value,
                    JobStatus.PROCESSING.value,
                    JobStatus.RETRY.value,
                    JobStatus.DEAD.value,
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
                  AND status IN (?, ?, ?, ?)
                  AND payload_json LIKE ?
                LIMIT 1
                """,
                (
                    JobStatus.PENDING.value,
                    JobStatus.PROCESSING.value,
                    JobStatus.RETRY.value,
                    JobStatus.DEAD.value,
                    f'%"{norm_escaped}"%',
                ),
            ).fetchone()
            return row2 is not None

    async def image_path_already_queued_async(self, image_path: str) -> bool:
        return await asyncio.to_thread(self.image_path_already_queued, image_path)

    def get_all_queued_image_paths(self) -> set[str]:
        """Fetch all queued image paths in one SQL query to avoid N+1 full table scans."""
        queued_paths = set()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT payload_json FROM jobs
                WHERE type = 'pin_upload'
                  AND status IN (?, ?, ?, ?)
                """,
                (
                    JobStatus.PENDING.value,
                    JobStatus.PROCESSING.value,
                    JobStatus.RETRY.value,
                    JobStatus.DEAD.value,
                ),
            ).fetchall()
            for r in rows:
                try:
                    payload = json.loads(r["payload_json"])
                    img_path = payload.get("image_path")
                    if img_path:
                        queued_paths.add(img_path)
                        queued_paths.add(str(Path(img_path).resolve()))
                except Exception:
                    pass
        return queued_paths

    async def get_all_queued_image_paths_async(self) -> set[str]:
        return await asyncio.to_thread(self.get_all_queued_image_paths)

    def purge_completed(self) -> None:
        """Delete completed_log entries older than the TTL."""
        cutoff = datetime.now(UTC).timestamp() - _COMPLETED_TTL_SECONDS
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM completed_log WHERE completed_at < ?", (cutoff,))

    def normalize_board_names_in_storage(self, include_dlq: bool = True) -> dict:
        """Normalize legacy board names in active jobs and optionally DLQ rows."""
        active_changed = 0
        dlq_changed = 0
        with self._lock, self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                rows = conn.execute("SELECT id, payload_json FROM jobs").fetchall()
                for row in rows:
                    try:
                        payload = json.loads(row["payload_json"])
                    except Exception:
                        continue
                    if not isinstance(payload, dict) or "board_name" not in payload:
                        continue
                    old_board = payload.get("board_name")
                    payload["board_name"] = normalize_board_name(old_board)
                    if payload.get("board_name") != old_board:
                        conn.execute(
                            "UPDATE jobs SET payload_json = ? WHERE id = ?",
                            (json.dumps(payload, ensure_ascii=False), row["id"]),
                        )
                        active_changed += 1

                if include_dlq:
                    rows = conn.execute("SELECT id, job_json FROM dlq").fetchall()
                    for row in rows:
                        try:
                            job_data = json.loads(row["job_json"])
                        except Exception:
                            continue
                        payload = job_data.get("payload")
                        if not isinstance(payload, dict) or "board_name" not in payload:
                            continue
                        old_board = payload.get("board_name")
                        payload["board_name"] = normalize_board_name(old_board)
                        if payload.get("board_name") != old_board:
                            conn.execute(
                                "UPDATE dlq SET job_json = ? WHERE id = ?",
                                (json.dumps(job_data, ensure_ascii=False), row["id"]),
                            )
                            dlq_changed += 1

                conn.execute("COMMIT;")
            except sqlite3.Error:
                conn.execute("ROLLBACK;")
                raise
        return {"active_changed": active_changed, "dlq_changed": dlq_changed}

    def requeue_transient_dlq(self) -> dict:
        """Selectively requeue DLQ jobs whose errors are transient.

        Transient patterns (will be requeued):
            timeout, lock acquisition, file input, publish button, login,
            circuit breaker, navigation, timed out, session lost, connection.

        Permanent patterns (will NOT be requeued):
            missing image, file not found, unknown account, image not found,
            abandoned.

        Returns a dict with ``requeued``, ``skipped``, and ``details`` keys.
        """
        TRANSIENT_PATTERNS = [
            "timeout",
            "lock acquisition",
            "file input",
            "publish button",
            "login",
            "circuit breaker",
            "navigation",
            "timed out",
            "session lost",
            "connection closed",
            "target page",
            "browser has been closed",
            "rate limit",
            "abandoned processing lease",
            "could not be verified",
        ]
        PERMANENT_PATTERNS = [
            "missing image",
            "file not found",
            "image not found",
            "unknown account",
            "unknown pinterest",
        ]

        requeued = 0
        skipped = 0
        details: list[dict] = []
        now = datetime.now(UTC).timestamp()

        with self._lock, self._conn() as conn:
            rows = conn.execute("SELECT id, job_json FROM dlq").fetchall()
            if not rows:
                return {"requeued": 0, "skipped": 0, "details": []}

            to_requeue: list[tuple] = []
            to_remove_ids: list[str] = []

            for row in rows:
                dlq_id = row["id"]
                try:
                    job_data = json.loads(row["job_json"])
                except Exception:
                    skipped += 1
                    details.append({"id": dlq_id, "action": "skip", "reason": "invalid JSON"})
                    continue

                error_log = job_data.get("error_log", [])
                error_text = " ".join(str(e) for e in error_log).lower()

                # Check for permanent errors first
                if any(p in error_text for p in PERMANENT_PATTERNS):
                    skipped += 1
                    details.append({"id": dlq_id, "action": "skip", "reason": "permanent error"})
                    continue

                # Check for transient errors
                if any(p in error_text for p in TRANSIENT_PATTERNS):
                    # Rebuild as a fresh pending job
                    job_data["status"] = JobStatus.PENDING.value
                    job_data["attempt"] = 0
                    job_data["error_log"] = [f"Requeued from DLQ at {datetime.now(UTC).isoformat()}"]
                    job_data["next_retry_at"] = None
                    job_data["started_at"] = None
                    job_data["completed_at"] = None

                    job = Job.from_dict(job_data)
                    _normalize_job_payload_board(job)
                    to_requeue.append(_job_to_row(job))
                    to_remove_ids.append(dlq_id)
                    requeued += 1
                    details.append({"id": dlq_id, "action": "requeue"})
                else:
                    skipped += 1
                    details.append({"id": dlq_id, "action": "skip", "reason": "no transient pattern"})

            if to_requeue:
                try:
                    conn.execute("BEGIN IMMEDIATE;")
                    conn.executemany(_INSERT_OR_REPLACE_JOB, to_requeue)
                    placeholders = ",".join("?" for _ in to_remove_ids)
                    conn.execute(f"DELETE FROM dlq WHERE id IN ({placeholders})", to_remove_ids)
                    conn.execute("COMMIT;")
                except sqlite3.Error:
                    conn.execute("ROLLBACK;")
                    raise

        logger.info("requeue_transient_dlq: requeued=%d, skipped=%d", requeued, skipped)
        return {"requeued": requeued, "skipped": skipped, "details": details[:50]}


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

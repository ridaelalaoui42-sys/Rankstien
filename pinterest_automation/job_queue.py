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
import hashlib
import json
import logging
import math
import os
import random
import re
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

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


def _account_lease_exclusions(
    locked_keys: set[str] | None, default_account: str, active_processing_since: float | None = None
) -> tuple[str, list]:
    """Reserve accounts inside dequeue's transaction, including nested identities."""
    if locked_keys is None:
        return "", []
    account_sql = """COALESCE(
        NULLIF(TRIM(json_extract(payload_json, '$.account_handle')), ''),
        NULLIF(TRIM(json_extract(payload_json, '$.extra.account_handle')), ''), ?
    )"""
    active_sql = " AND started_at >= ?" if active_processing_since is not None else ""
    clauses = [f"{account_sql} NOT IN (SELECT {account_sql} FROM jobs WHERE status = ?{active_sql})"]
    params = [default_account, default_account, "processing"]
    if active_processing_since is not None:
        params.append(active_processing_since)
    if locked_keys:
        keys = sorted(locked_keys)
        placeholders = ", ".join("?" for _ in keys)
        clauses.append(f"{account_sql} NOT IN ({placeholders})")
        params.extend([default_account, *keys])
    return " AND " + " AND ".join(clauses), params


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

CREATE TABLE IF NOT EXISTS completion_evidence (
    id              TEXT PRIMARY KEY,
    job_json        TEXT NOT NULL,
    completed_at    REAL NOT NULL,
    recorded_at     REAL NOT NULL,
    provenance_json TEXT NOT NULL
);
"""


def _validated_completion(job_json: str, job_id: str, completed_at: float) -> dict:
    """Accept only an exact, successful completed upload with a proven pin identity."""
    if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", job_id):
        raise ValueError("Completion evidence has an invalid job ID")
    if not isinstance(job_json, str) or len(job_json.encode("utf-8")) > 1024 * 1024:
        raise ValueError("Completion evidence JSON exceeds its byte limit")
    data = json.loads(job_json)
    if not isinstance(data, dict) or data.get("id") != job_id:
        raise ValueError("Completion evidence JSON identity does not match its row")
    if data.get("type") != "pin_upload" or data.get("status") != "completed":
        raise ValueError("Completion evidence must be a completed pin_upload")
    if (
        isinstance(completed_at, bool)
        or not isinstance(completed_at, (float, int))
        or not math.isfinite(completed_at)
        or completed_at <= 0
        or isinstance(data.get("completed_at"), bool)
        or data.get("completed_at") != completed_at
    ):
        raise ValueError("Completion evidence timestamp does not match its row")
    if not isinstance(data.get("payload"), dict):
        raise ValueError("Completion evidence payload is missing")
    result = data.get("result")
    if not isinstance(result, dict) or result.get("success") is not True:
        raise ValueError("Completion evidence does not prove success")
    pin_id = result.get("pin_id")
    pin_url = result.get("pin_url")
    if not isinstance(pin_id, str) or not re.fullmatch(r"\d{15,20}", pin_id):
        raise ValueError("Completion evidence does not prove a valid pin ID")
    if not isinstance(pin_url, str):
        raise ValueError("Completion evidence does not prove a pin URL")
    parsed = urlparse(pin_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"pinterest.com", "www.pinterest.com"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.path.rstrip("/") != f"/pin/{pin_id}"
    ):
        raise ValueError("Completion evidence pin URL does not match its pin ID")
    return data


def _same_completion(left_json: str, right_json: str) -> bool:
    return json.loads(left_json) == json.loads(right_json)


def _evidence_values(job_json: str, job_id: str, completed_at: float, provenance: dict) -> tuple | None:
    try:
        _validated_completion(job_json, job_id, completed_at)
    except (ValueError, TypeError):
        # Preserve existing queue semantics for non-upload or unverified results;
        # those rows must never become durable proof of a Pinterest publication.
        return None
    return (
        job_id,
        job_json,
        completed_at,
        datetime.now(UTC).timestamp(),
        json.dumps(provenance, ensure_ascii=False, sort_keys=True),
    )


_INSERT_COMPLETION_EVIDENCE = """
INSERT INTO completion_evidence (id, job_json, completed_at, recorded_at, provenance_json)
VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO NOTHING
"""


def _store_completion_evidence(conn: sqlite3.Connection, values: tuple | None) -> None:
    if values is None:
        return
    existing = conn.execute("SELECT job_json FROM completion_evidence WHERE id = ?", (values[0],)).fetchone()
    if existing is not None and not _same_completion(existing["job_json"], values[1]):
        raise ValueError(f"Conflicting durable completion evidence for {values[0]}")
    conn.execute(_INSERT_COMPLETION_EVIDENCE, values)


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
            SELECT id FROM completion_evidence WHERE json_extract(job_json, '$.payload.extra.idempotency_key') = ?
            UNION ALL
            SELECT id FROM dlq WHERE json_extract(job_json, '$.payload.extra.idempotency_key') = ?
            LIMIT 1
            """,
            (str(idempotency_key),) * 4,
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
                UNION ALL
                SELECT id FROM completion_evidence
                WHERE json_extract(job_json, '$.type') = 'pin_upload'
                  AND (json_extract(job_json, '$.payload.image_path') = ? OR json_extract(job_json, '$.payload.image_path') = ?)
                LIMIT 1
                """,
                (image_path, norm_path) * 4,
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
            SELECT id FROM completion_evidence WHERE json_extract(job_json, '$.payload.extra.idempotency_key') = ?
            UNION ALL
            SELECT id FROM dlq WHERE json_extract(job_json, '$.payload.extra.idempotency_key') = ?
            LIMIT 1
            """,
            (str(idempotency_key),) * 4,
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
                UNION ALL
                SELECT id FROM completion_evidence
                WHERE json_extract(job_json, '$.type') = 'pin_upload'
                  AND (json_extract(job_json, '$.payload.image_path') = ? OR json_extract(job_json, '$.payload.image_path') = ?)
                LIMIT 1
                """,
                (image_path, norm_path) * 4,
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
            # Preserve the bounded history before any later upload can trim it.
            conn.execute("BEGIN IMMEDIATE")
            try:
                for row in conn.execute(
                    "SELECT id, job_json, completed_at FROM completed_log "
                    "WHERE id NOT IN (SELECT id FROM completion_evidence)"
                ).fetchall():
                    _store_completion_evidence(
                        conn,
                        _evidence_values(
                            row["job_json"],
                            row["id"],
                            row["completed_at"],
                            {"kind": "completed_log_backfill", "source_table": "completed_log"},
                        ),
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

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
            conn.execute("BEGIN IMMEDIATE")
            try:
                for item in data:
                    if not isinstance(item, dict) or "id" not in item:
                        continue
                    job_json = json.dumps(item, ensure_ascii=False)
                    completed_at = item.get("completed_at") or 0.0
                    conn.execute(
                        "INSERT OR REPLACE INTO completed_log (id, job_json, completed_at) VALUES (?, ?, ?)",
                        (item["id"], job_json, completed_at),
                    )
                    _store_completion_evidence(
                        conn,
                        _evidence_values(
                            job_json,
                            item["id"],
                            completed_at,
                            {"kind": "legacy_completed_import", "source_file": str(path.resolve())},
                        ),
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
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

    def dequeue(
        self,
        locked_keys: set[str] | None = None,
        default_account: str = "rida",
        *,
        active_processing_since: float | None = None,
    ) -> Job | None:
        """Lease a ready job; supplied account locks also reserve already leased accounts."""
        now = time.time()

        exclude_sql, account_params = _account_lease_exclusions(
            locked_keys, default_account, active_processing_since
        )
        params = [JobStatus.PENDING.value, JobStatus.RETRY.value, now]
        params.extend(account_params)

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
                # A current owner's fresh lease must satisfy its account
                # reservation cutoff, even if the wall clock moves backward.
                # Keep retry eligibility above on the actual observed clock.
                job.started_at = (
                    max(now, active_processing_since) if active_processing_since is not None else now
                )
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
        self,
        locked_keys: set[str] | None = None,
        default_account: str = "rida",
        *,
        active_processing_since: float | None = None,
    ) -> Job | None:
        """Lease asynchronously, atomically reserving accounts when account locks are supplied."""
        now = time.time()

        exclude_sql, account_params = _account_lease_exclusions(
            locked_keys, default_account, active_processing_since
        )
        params = [JobStatus.PENDING.value, JobStatus.RETRY.value, now]
        params.extend(account_params)

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
                job.started_at = (
                    max(now, active_processing_since) if active_processing_since is not None else now
                )
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
            job_json = json.dumps(job.to_dict(), ensure_ascii=False)

            try:
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute(
                    "INSERT OR REPLACE INTO completed_log (id, job_json, completed_at) VALUES (?, ?, ?)",
                    (job.id, job_json, completed_at),
                )
                _store_completion_evidence(
                    conn, _evidence_values(job_json, job.id, completed_at, {"kind": "queue.complete"})
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
            except Exception:
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
            job_json = json.dumps(job.to_dict(), ensure_ascii=False)

            try:
                await db.execute("BEGIN IMMEDIATE;")
                await db.execute(
                    "INSERT OR REPLACE INTO completed_log (id, job_json, completed_at) VALUES (?, ?, ?)",
                    (job.id, job_json, completed_at),
                )
                values = _evidence_values(job_json, job.id, completed_at, {"kind": "queue.complete_async"})
                if values is not None:
                    cursor = await db.execute(
                        "SELECT job_json FROM completion_evidence WHERE id = ?", (job.id,)
                    )
                    existing = await cursor.fetchone()
                    if existing is not None and not _same_completion(existing["job_json"], job_json):
                        raise ValueError(f"Conflicting durable completion evidence for {job.id}")
                    await db.execute(_INSERT_COMPLETION_EVIDENCE, values)
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
            job_json = json.dumps(job.to_dict(), ensure_ascii=False)
            try:
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute(
                    "INSERT OR REPLACE INTO completed_log (id, job_json, completed_at) VALUES (?, ?, ?)",
                    (job.id, job_json, completed_at),
                )
                _store_completion_evidence(
                    conn,
                    _evidence_values(job_json, job.id, completed_at, {"kind": "queue.complete_from_dlq"}),
                )
                conn.execute("DELETE FROM dlq WHERE id = ?", (job_id,))
                conn.execute("COMMIT;")
            except Exception:
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

    def prioritize_jobs(self, job_ids: list[str], *, priority: int = 1) -> dict:
        """Prioritize exact unleased jobs without changing attempts or retry deadlines."""
        if isinstance(priority, bool) or not isinstance(priority, int) or not 1 <= priority <= 10:
            raise ValueError("Priority must be an integer from 1 to 10")
        ids = [str(job_id).strip() for job_id in job_ids]
        if not ids or any(not job_id for job_id in ids) or len(set(ids)) != len(ids):
            raise ValueError("Prioritization requires distinct, explicit job IDs")
        with self._lock, self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                changes = []
                for job_id in ids:
                    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
                    if row is None or row["status"] not in {JobStatus.PENDING.value, JobStatus.RETRY.value}:
                        raise ValueError(f"Job {job_id} is missing, held, leased or terminal")
                    changes.append(
                        {
                            "id": job_id,
                            "previous_priority": row["priority"],
                            "priority": priority,
                            "status": row["status"],
                            "attempt": row["attempt"],
                            "next_retry_at": row["next_retry_at"],
                        }
                    )
                for change in changes:
                    conn.execute("UPDATE jobs SET priority = ? WHERE id = ?", (priority, change["id"]))
                conn.execute("COMMIT;")
            except Exception:
                conn.execute("ROLLBACK;")
                raise
        return {"prioritized": len(changes), "jobs": changes}

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

            row = conn.execute(
                "SELECT job_json, completed_at, provenance_json FROM completion_evidence WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is not None:
                data = _validated_completion(row["job_json"], job_id, row["completed_at"])
                result = outcome(Job.from_dict(data), JobStatus.COMPLETED.value)
                result["evidence_provenance"] = json.loads(row["provenance_json"])
                return result

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

    def recover_completion_evidence(
        self, snapshot_path: Path, job_ids: list[str], *, dry_run: bool = True
    ) -> dict:
        """Recover only explicitly selected, authentic completions from one read-only snapshot.

        Never restores queue work, changes retry state, or examines unselected IDs.
        Every selected record must validate before any durable evidence is imported.
        """
        if (
            not isinstance(job_ids, list)
            or not job_ids
            or len(job_ids) > 1000
            or any(
                not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", job_id)
                for job_id in job_ids
            )
            or len(set(job_ids)) != len(job_ids)
        ):
            raise ValueError("Recovery requires a nonempty list of unique exact job IDs (maximum 1000)")
        source = Path(snapshot_path).resolve(strict=True)
        if not source.is_file() or source == self._db_file.resolve():
            raise ValueError("Recovery requires a separate existing queue snapshot file")
        deadline = time.monotonic() + 15

        def fingerprint() -> dict:
            hashes = {}
            for label, path in (("sha256", source), ("wal_sha256", Path(str(source) + "-wal"))):
                if not path.is_file():
                    hashes[label] = None
                    continue
                if path.stat().st_size > 1024 * 1024 * 1024:
                    raise ValueError("Recovery snapshot exceeds the byte limit")
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        if time.monotonic() >= deadline:
                            raise ValueError("Recovery snapshot exceeded its deadline")
                        digest.update(chunk)
                hashes[label] = digest.hexdigest()
            return hashes

        source_hashes = fingerprint()
        placeholders = ",".join("?" for _ in job_ids)
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=0.25) as snapshot:
            snapshot.row_factory = sqlite3.Row
            snapshot.execute("PRAGMA query_only=ON")
            snapshot.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 1024 * 1024)
            snapshot.set_progress_handler(lambda: int(time.monotonic() >= deadline), 100)
            snapshot.execute("BEGIN")
            tables = {
                row[0]
                for row in snapshot.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('jobs', 'dlq')"
                )
            }
            for table in ("jobs", "dlq"):
                if (
                    table in tables
                    and snapshot.execute(
                        f"SELECT 1 FROM {table} WHERE id IN ({placeholders}) LIMIT 1", job_ids
                    ).fetchone()
                ):
                    raise ValueError("Snapshot contains selected active or dead jobs")
            rows = snapshot.execute(
                f"SELECT id, job_json, completed_at FROM completed_log WHERE id IN ({placeholders})",
                job_ids,
            ).fetchall()
        by_id = {row["id"]: row for row in rows}
        if set(by_id) != set(job_ids):
            raise ValueError("Snapshot does not contain every selected exact completed job")
        values_by_id = {}
        for job_id in job_ids:
            row = by_id[job_id]
            _validated_completion(row["job_json"], job_id, row["completed_at"])
            provenance = {
                "kind": "explicit_snapshot_recovery",
                "source_snapshot": str(source),
                "source_table": "completed_log",
                "source_sha256": source_hashes["sha256"],
                "source_wal_sha256": source_hashes["wal_sha256"],
                "source_job_sha256": hashlib.sha256(row["job_json"].encode("utf-8")).hexdigest(),
            }
            values_by_id[job_id] = _evidence_values(row["job_json"], job_id, row["completed_at"], provenance)
        if fingerprint() != source_hashes:
            raise ValueError("Recovery snapshot changed during proof collection")

        imported = []
        already_present = []
        with self._lock, self._conn() as conn:
            conn.execute("BEGIN" if dry_run else "BEGIN IMMEDIATE")
            try:
                # Current pending, held, or dead state always takes precedence.
                for job_id in job_ids:
                    if (
                        conn.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone()
                        or conn.execute("SELECT 1 FROM dlq WHERE id = ?", (job_id,)).fetchone()
                    ):
                        raise ValueError(f"Recovery refuses current active or dead job {job_id}")
                    for table in ("completed_log", "completion_evidence"):
                        existing = conn.execute(
                            f"SELECT job_json FROM {table} WHERE id = ?", (job_id,)
                        ).fetchone()
                        if existing is not None and not _same_completion(
                            existing["job_json"], by_id[job_id]["job_json"]
                        ):
                            raise ValueError(f"Recovery refuses conflicting completion evidence for {job_id}")
                        if table == "completion_evidence" and existing is not None:
                            already_present.append(job_id)
                if not dry_run:
                    for job_id in job_ids:
                        if job_id not in already_present:
                            _store_completion_evidence(conn, values_by_id[job_id])
                            imported.append(job_id)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return {
            "success": True,
            "dry_run": dry_run,
            "job_ids": list(job_ids),
            "eligible": len(job_ids) - len(already_present),
            "imported": imported,
            "already_present": already_present,
            "source_sha256": source_hashes["sha256"],
            "source_wal_sha256": source_hashes["wal_sha256"],
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

    def repair_upload_destinations(self, repairs: list[dict], *, reason: str, dry_run: bool = True) -> dict:
        """Repair exact unleased folder uploads from verified canonical recipe proof.

        Each entry supplies ``id``, ``expected_status``, ``expected_payload`` and
        ``article`` (HTTP ``status``, ``canonical_url``, ``domain_handle`` and
        ``recipe_schema`` containing Recipe/name). The caller obtains the proof
        before this transaction. Paths must name the same configured domain and
        recipe folder. Only destination/title metadata changes; existing images,
        accounts, boards, priorities, attempts and retry deadlines are retained.
        A prior canonical publication or uncertain duplicate holds the repaired
        job for review. Other dead rows and preexisting held work stay untouched.
        """
        from rankstein.domain import get_registry

        if (
            not isinstance(repairs, list)
            or not repairs
            or len(repairs) > 1000
            or any(not isinstance(entry, dict) for entry in repairs)
        ):
            raise ValueError("Destination repair requires one to 1000 explicit repair entries")
        ids = [entry.get("id") for entry in repairs]
        if any(
            not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", job_id)
            for job_id in ids
        ) or len(set(ids)) != len(ids):
            raise ValueError("Destination repair requires unique exact job IDs")
        if not isinstance(dry_run, bool):
            raise ValueError("dry_run must be a boolean")
        if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
            raise ValueError("Destination repair requires an explicit reason (maximum 500 characters)")
        domains = {domain.handle: domain for domain in get_registry().all()}
        accounts = get_config().accounts
        now = datetime.now(UTC).isoformat()
        details = []
        prepared = []
        proposed_keys = {}
        normalized_paths = {}

        def image_key(value):
            if not value:
                return None
            if value not in normalized_paths:
                normalized_paths[value] = os.path.normcase(str(Path(value).resolve()))
            return normalized_paths[value]

        with self._lock, self._conn() as conn:
            conn.create_function("repair_image_path", 1, image_key, deterministic=True)
            conn.execute("BEGIN" if dry_run else "BEGIN IMMEDIATE")
            try:
                for entry in repairs:
                    job_id = entry["id"]
                    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
                    expected_status = entry.get("expected_status")
                    if (
                        row is None
                        or expected_status not in {JobStatus.PENDING.value, JobStatus.RETRY.value}
                        or row["status"] != expected_status
                    ):
                        raise ValueError(f"Repair job {job_id} is missing, changed, held, leased or terminal")
                    job = _row_to_job(row)
                    old_payload = entry.get("expected_payload")
                    if not isinstance(old_payload, dict) or job.payload != old_payload:
                        raise ValueError(f"Repair job {job_id} no longer has its exact expected payload")
                    extra = job.payload.get("extra")
                    if (
                        job.type != "pin_upload"
                        or not isinstance(extra, dict)
                        or extra.get("campaign_type") != "folder_batch"
                        or job.result is not None
                    ):
                        raise ValueError(f"Repair job {job_id} must be an unverified folder upload")
                    account = job.payload.get("account_handle") or extra.get("account_handle")
                    identities = {
                        str(value).strip()
                        for value in (job.payload.get("account_handle"), extra.get("account_handle"))
                        if value is not None and str(value).strip()
                    }
                    if not isinstance(account, str) or account not in accounts or identities != {account}:
                        raise ValueError(f"Repair job {job_id} has an unknown or conflicting account")
                    image = job.payload.get("image_path")
                    if not isinstance(image, str) or not Path(image).is_file():
                        raise ValueError(f"Repair job {job_id} has no retained source image")
                    parts = Path(image).resolve().parts
                    if "remaster_final" not in parts:
                        raise ValueError(f"Repair job {job_id} is outside the article remaster tree")
                    suffix = parts[parts.index("remaster_final") + 1 :]
                    if len(suffix) != 4 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", suffix[1]):
                        raise ValueError(f"Repair job {job_id} has no exact domain/date/recipe folder")
                    datetime.strptime(suffix[1], "%Y-%m-%d")
                    folder_domain, slug = suffix[0], suffix[2]
                    article = entry.get("article")
                    if not isinstance(article, dict) or article.get("status") != 200:
                        raise ValueError(f"Repair job {job_id} requires verified HTTP 200 recipe proof")
                    domain = domains.get(folder_domain)
                    schema = article.get("recipe_schema")
                    schema_type = schema.get("@type") if isinstance(schema, dict) else None
                    name = schema.get("name") if isinstance(schema, dict) else None
                    if (
                        domain is None
                        or article.get("domain_handle") != folder_domain
                        or not (
                            schema_type == "Recipe"
                            or (isinstance(schema_type, list) and "Recipe" in schema_type)
                        )
                        or not isinstance(name, str)
                        or not name.strip()
                        or len(name.strip()) > 500
                    ):
                        raise ValueError(f"Repair job {job_id} has mismatched domain or Recipe name proof")
                    configured_url = domain.domain if "://" in domain.domain else "//" + domain.domain
                    host = (urlparse(configured_url).hostname or "").casefold().removeprefix("www.")
                    canonical = article.get("canonical_url")
                    parsed = urlparse(canonical) if isinstance(canonical, str) else None
                    if (
                        parsed is None
                        or parsed.scheme != "https"
                        or (parsed.hostname or "").casefold().removeprefix("www.") != host
                        or parsed.username is not None
                        or parsed.password is not None
                        or parsed.port not in {None, 443}
                        or parsed.query
                        or parsed.fragment
                        or parsed.path.strip("/") != slug
                        or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug)
                    ):
                        raise ValueError(
                            f"Repair job {job_id} canonical URL does not match its recipe folder"
                        )
                    name = name.strip()
                    payload = json.loads(json.dumps(job.payload, ensure_ascii=False))
                    payload.update(
                        link=canonical,
                        domain_handle=folder_domain,
                        title=name,
                        description=name,
                        alt_text=name,
                    )
                    payload["extra"].update(domain_handle=folder_domain, slug=slug)
                    key = (image_key(image), account, payload.get("board_name") or "", canonical)
                    conflicts = []
                    if key in proposed_keys:
                        conflicts.append({"table": "repair_batch", "id": proposed_keys[key]})
                    proposed_keys.setdefault(key, job_id)
                    idem = extra.get("idempotency_key") or None
                    for table in ("jobs", "dlq", "completed_log", "completion_evidence"):
                        if (
                            table != "jobs"
                            and conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (job_id,)).fetchone()
                        ):
                            conflicts.append({"table": table, "id": job_id})
                        column = "payload_json" if table == "jobs" else "job_json"
                        prefix = "$." if table == "jobs" else "$.payload."
                        matches = conn.execute(
                            f"SELECT * FROM {table} WHERE id <> ? AND (("
                            f"repair_image_path(json_extract({column}, '{prefix}image_path')) = ? AND "
                            f"COALESCE(NULLIF(TRIM(json_extract({column}, '{prefix}account_handle')), ''), "
                            f"NULLIF(TRIM(json_extract({column}, '{prefix}extra.account_handle')), ''), '') = ? AND "
                            f"COALESCE(json_extract({column}, '{prefix}board_name'), '') = ? AND "
                            f"COALESCE(json_extract({column}, '{prefix}link'), '') = ?) OR "
                            f"(? IS NOT NULL AND json_extract({column}, '{prefix}extra.idempotency_key') = ?))",
                            (job_id, *key, idem, idem),
                        ).fetchall()
                        for match in matches:
                            if table == "dlq":
                                dead = json.loads(match["job_json"])
                                history = dead.get("error_log")
                                dead_payload = dead.get("payload") or {}
                                dead_extra = dead_payload.get("extra") or {}
                                # Exact login-only duplicates remain quarantined;
                                # all other earlier failures need human proof.
                                if (
                                    dead.get("type") == "pin_upload"
                                    and dead.get("status") == JobStatus.DEAD.value
                                    and dead.get("result") is None
                                    and dead.get("completed_at") is None
                                    and not (idem and dead_extra.get("idempotency_key") == idem)
                                    and isinstance(history, list)
                                    and history
                                    and all(
                                        isinstance(error, str)
                                        and re.fullmatch(
                                            r"(?:(?:Attempt [1-9]\d*|Fatal error): )?Login failed", error
                                        )
                                        for error in history
                                    )
                                ):
                                    continue
                            conflicts.append({"table": table, "id": match["id"]})
                    action = "hold" if conflicts else "repair"
                    status = JobStatus.HELD.value if conflicts else job.status
                    audit = {
                        "at": now,
                        "reason": reason.strip(),
                        "action": action,
                        "previous_status": job.status,
                        "previous_link": job.payload.get("link"),
                        "canonical_url": canonical,
                        "conflicts": conflicts,
                    }
                    history = list(job.error_log) + [
                        "Canonical destination repair: "
                        + json.dumps(audit, ensure_ascii=False, sort_keys=True)
                    ]
                    prepared.append((row, payload, status, history))
                    details.append(
                        {
                            "id": job_id,
                            "action": action,
                            "previous_status": job.status,
                            "status": status,
                            "previous_link": job.payload.get("link"),
                            "canonical_url": canonical,
                            "domain_handle": folder_domain,
                            "title": name,
                            "account_handle": account,
                            "attempt": job.attempt,
                            "max_attempts": job.max_attempts,
                            "next_retry_at": job.next_retry_at,
                            "conflicts": conflicts,
                        }
                    )
                if not dry_run:
                    for row, payload, status, history in prepared:
                        cursor = conn.execute(
                            "UPDATE jobs SET payload_json = ?, status = ?, error_log_json = ? "
                            "WHERE id = ? AND status = ? AND payload_json = ?",
                            (
                                json.dumps(payload, ensure_ascii=False),
                                status,
                                json.dumps(history, ensure_ascii=False),
                                row["id"],
                                row["status"],
                                row["payload_json"],
                            ),
                        )
                        if cursor.rowcount != 1:
                            raise ValueError(f"Repair job {row['id']} changed during the transaction")
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return {
            "dry_run": dry_run,
            "selected": len(repairs),
            "repair_count": sum(detail["action"] == "repair" for detail in details),
            "hold_count": sum(detail["action"] == "hold" for detail in details),
            "applied": 0 if dry_run else len(repairs),
            "details": details,
        }

    def restore_login_failure_jobs(
        self,
        job_ids: list[str],
        *,
        reason: str,
        dry_run: bool = True,
        additional_attempts: int = 3,
    ) -> dict:
        """Restore exact login-only upload failures after an authorized outage recovery.

        This deliberately does not use the broad transient-error matcher. Every
        selected record must still be dead, have only exact login failures, and
        retain a usable source image. Any invalid record or conflicting queued or
        published identity rejects the entire batch. Retry history and deadlines
        are retained; authorization adds a bounded attempt window instead of
        resetting attempts. Repeating the same reason/budget for an already
        restored job is a no-op, including after that job has completed.
        """
        if (
            not isinstance(job_ids, list)
            or not job_ids
            or len(job_ids) > 1000
            or any(
                not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", job_id)
                for job_id in job_ids
            )
            or len(set(job_ids)) != len(job_ids)
        ):
            raise ValueError("Recovery requires a nonempty list of unique exact job IDs (maximum 1000)")
        if not isinstance(dry_run, bool):
            raise ValueError("dry_run must be a boolean")
        if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
            raise ValueError("Recovery requires an explicit authorization reason (maximum 500 characters)")
        if (
            isinstance(additional_attempts, bool)
            or not isinstance(additional_attempts, int)
            or not 1 <= additional_attempts <= 3
        ):
            raise ValueError("Recovery may authorize one to three additional attempts")
        reason = reason.strip()
        now = datetime.now(UTC).isoformat()
        prepared: list[Job] = []
        details = []
        already_restored = []
        normalized_paths = {}

        def normalized_image_path(value):
            if not value:
                return None
            if value not in normalized_paths:
                normalized_paths[value] = os.path.normcase(str(Path(value).resolve()))
            return normalized_paths[value]

        with self._lock, self._conn() as conn:
            conn.create_function("recovery_image_path", 1, normalized_image_path, deterministic=True)
            conn.execute("BEGIN" if dry_run else "BEGIN IMMEDIATE")
            try:
                for job_id in job_ids:
                    recovery_key = hashlib.sha256(
                        json.dumps([job_id, reason, additional_attempts], ensure_ascii=False).encode("utf-8")
                    ).hexdigest()
                    marker = f"Authorized DLQ login recovery [{recovery_key}]: "
                    row = conn.execute("SELECT job_json FROM dlq WHERE id = ?", (job_id,)).fetchone()
                    current = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
                    terminal = [
                        record
                        for table in ("completed_log", "completion_evidence")
                        if (
                            record := conn.execute(
                                f"SELECT job_json FROM {table} WHERE id = ?", (job_id,)
                            ).fetchone()
                        )
                    ]
                    if row is None:
                        records = ([_row_to_job(current).to_dict()] if current else []) + [
                            json.loads(record["job_json"]) for record in terminal
                        ]
                        if records and all(
                            isinstance(record, dict)
                            and record.get("id") == job_id
                            and any(
                                isinstance(error, str) and error.startswith(marker)
                                for error in record.get("error_log", [])
                            )
                            for record in records
                        ):
                            already_restored.append(job_id)
                            continue
                        raise ValueError(
                            f"Selected DLQ job {job_id} is missing or conflicts with current state"
                        )
                    if current is not None or terminal:
                        raise ValueError(f"Selected DLQ job {job_id} conflicts with active or terminal state")
                    data = json.loads(row["job_json"])
                    if not isinstance(data, dict) or data.get("id") != job_id:
                        raise ValueError(f"Selected DLQ job {job_id} has an invalid stored identity")
                    if data.get("type") != "pin_upload" or data.get("status") != JobStatus.DEAD.value:
                        raise ValueError(f"Selected DLQ job {job_id} must be a dead pin_upload")
                    history = data.get("error_log")
                    if (
                        not isinstance(history, list)
                        or not history
                        or any(
                            not isinstance(error, str)
                            or not re.fullmatch(r"(?:(?:Attempt [1-9]\d*|Fatal error): )?Login failed", error)
                            for error in history
                        )
                    ):
                        raise ValueError(
                            f"Selected DLQ job {job_id} contains non-login or uncertain failures"
                        )
                    attempt, maximum = data.get("attempt"), data.get("max_attempts")
                    if (
                        isinstance(attempt, bool)
                        or not isinstance(attempt, int)
                        or isinstance(maximum, bool)
                        or not isinstance(maximum, int)
                        or not 0 <= attempt <= maximum
                        or maximum < 1
                    ):
                        raise ValueError(f"Selected DLQ job {job_id} has an invalid attempt budget")
                    for name in ("created_at", "next_retry_at"):
                        value = data.get(name)
                        if (name == "created_at" or value is not None) and (
                            isinstance(value, bool)
                            or not isinstance(value, (int, float))
                            or not math.isfinite(value)
                            or value < 0
                        ):
                            raise ValueError(f"Selected DLQ job {job_id} has an invalid {name}")
                    if data.get("result") is not None or data.get("completed_at") is not None:
                        raise ValueError(f"Selected DLQ job {job_id} contains possible publication evidence")
                    payload = data.get("payload")
                    if not isinstance(payload, dict):
                        raise ValueError(f"Selected DLQ job {job_id} has no payload")
                    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
                    account = payload.get("account_handle") or extra.get("account_handle")
                    image = payload.get("image_path")
                    if not isinstance(account, str) or not account.strip():
                        raise ValueError(f"Selected DLQ job {job_id} has no explicit account")
                    if not isinstance(image, str) or not image.strip() or not Path(image).is_file():
                        raise ValueError(f"Selected DLQ job {job_id} has no usable source image")

                    # Reusing an asset across accounts or destinations is valid.
                    # A duplicate upload identity requires the same normalized
                    # path, account, board and destination; idempotency keys are
                    # checked independently across every account and state.
                    image_path = normalized_image_path(image)
                    idempotency_key = extra.get("idempotency_key") or None
                    for table in ("jobs", "dlq", "completed_log", "completion_evidence"):
                        column = "payload_json" if table == "jobs" else "job_json"
                        path_prefix = "$." if table == "jobs" else "$.payload."
                        conflict = conn.execute(
                            f"SELECT id FROM {table} WHERE id <> ? AND ("
                            f"(recovery_image_path(json_extract({column}, '{path_prefix}image_path')) = ? AND "
                            f"COALESCE(NULLIF(TRIM(json_extract({column}, '{path_prefix}account_handle')), ''), "
                            f"NULLIF(TRIM(json_extract({column}, '{path_prefix}extra.account_handle')), ''), '') = ? AND "
                            f"COALESCE(json_extract({column}, '{path_prefix}board_name'), '') = ? AND "
                            f"COALESCE(json_extract({column}, '{path_prefix}link'), '') = ?) OR "
                            f"(? IS NOT NULL AND json_extract({column}, '{path_prefix}extra.idempotency_key') = ?)) "
                            "LIMIT 1",
                            (
                                job_id,
                                image_path,
                                account.strip(),
                                payload.get("board_name") or "",
                                payload.get("link") or "",
                                idempotency_key,
                                idempotency_key,
                            ),
                        ).fetchone()
                        if conflict:
                            raise ValueError(
                                f"Selected DLQ job {job_id} duplicates existing identity {conflict['id']}"
                            )
                    previous_errors = len(history)
                    job = Job.from_dict(data)
                    job.status = JobStatus.PENDING.value
                    job.started_at = None
                    job.max_attempts += additional_attempts
                    job.error_log.append(
                        marker
                        + json.dumps(
                            {"reason": reason, "additional_attempts": additional_attempts, "at": now},
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                    )
                    prepared.append(job)
                    details.append(
                        {
                            "id": job.id,
                            "account_handle": account,
                            "attempt": job.attempt,
                            "previous_max_attempts": maximum,
                            "max_attempts": job.max_attempts,
                            "created_at": job.created_at,
                            "next_retry_at": job.next_retry_at,
                            "previous_errors": previous_errors,
                        }
                    )
                if not dry_run:
                    for job in prepared:
                        # Plain INSERT protects against overwrite even if a new
                        # conflict check is accidentally removed in the future.
                        conn.execute(
                            _INSERT_OR_REPLACE_JOB.replace("INSERT OR REPLACE", "INSERT"),
                            _job_to_row(job),
                        )
                        conn.execute("DELETE FROM dlq WHERE id = ?", (job.id,))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        return {
            "dry_run": dry_run,
            "selected": len(job_ids),
            "eligible": len(prepared),
            "restored": 0 if dry_run else len(prepared),
            "already_restored": already_restored,
            "additional_attempts": additional_attempts,
            "details": details,
        }

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

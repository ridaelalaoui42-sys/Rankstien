"""
RankStein Pinterest Automation — Intelligent Rate Limiter
Token-bucket style with jitter, anti-detection patterns, and adaptive backoff.

Counts are now persisted to a small SQLite table so daily/hourly budgets survive
process restarts (e.g. Windows sleep, crash, manual stop).  On init the persisted
rows are loaded back; on every record_execution / record_failure the rows are
updated atomically.  A fresh row is inserted automatically if one doesn't exist.
"""

import json
import logging
import os
import random
import re
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

from .config import DATA_DIR, get_config

logger = logging.getLogger("rankstein.rate_limiter")

# ── Persistent state DB ───────────────────────────────────────────────────────
_RL_DB_FILE = Path(os.environ.get("PINTEREST_RATE_LIMIT_DB_FILE") or DATA_DIR / "queue" / "rate_limiter.db")
_CONFIGURED_RL_DB_FILE = _RL_DB_FILE
_PROOF_TIMEOUT_SECONDS = 2.0
_PROOF_MAX_ROWS = 20000
_PROOF_MAX_ROW_BYTES = 1024 * 1024
_PROOF_MAX_BYTES = 64 * 1024 * 1024
_BUDGET_REFRESH_SECONDS = 10.0
_UNKNOWN_BUDGET_RETRY_SECONDS = 60.0
_PIN_ID = re.compile(r"\d{15,20}")

_RL_SCHEMA = """
CREATE TABLE IF NOT EXISTS rl_counters (
    operation   TEXT    NOT NULL,
    day_key     TEXT    NOT NULL,  -- YYYY-MM-DD
    hour_key    TEXT    NOT NULL,  -- YYYY-MM-DDTHH
    daily_count INTEGER NOT NULL DEFAULT 0,
    hourly_count INTEGER NOT NULL DEFAULT 0,
    failure_streak INTEGER NOT NULL DEFAULT 0,
    cooldown_until REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (operation, day_key, hour_key)
);
"""


def _rl_conn(db_file: Path) -> sqlite3.Connection:
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_file, isolation_level=None, check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.executescript(_RL_SCHEMA)
    return conn


class RateLimiter:
    """
    Production rate limiter with:
    - Token bucket for burst control
    - Jitter to avoid detectable patterns
    - Adaptive backoff on failures
    - Per-operation-type tracking
    - Persistent counters across restarts (SQLite-backed)
    """

    def __init__(self, db_file: Path | None = None, *, proof_db_file: Path | None = None):
        import copy

        self.config = copy.deepcopy(get_config().rate_limit)
        self._lock = Lock()
        self._db_file = db_file or _RL_DB_FILE
        self._proof_db_file = proof_db_file or self._paired_proof_db(explicit_db=db_file is not None)
        self._budget_available = False
        self._budget_checked_at = float("-inf")
        self._proof_budget_counts: dict[str, int] = {}
        self._proof_available = False
        self._proof_route_cache: dict[str, tuple[str, frozenset[str]]] | None = None
        # In-memory caches (loaded from DB on init, flushed on every mutation)
        self._daily_counts: dict[str, int] = {}
        self._hourly_counts: dict[str, int] = {}
        self._failure_streaks: dict[str, int] = {}
        self._cooldown_until: dict[str, float] = {}
        self._last_reset_day = self._day_key()
        self._last_reset_hour = self._hour_key()
        self._load_persisted()
        self._refresh_budget_evidence(force=True)

    # ── Persistence helpers ───────────────────────────────────────────────────

    def _day_key(self) -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    def _hour_key(self) -> str:
        return datetime.now(UTC).strftime("%Y-%m-%dT%H")

    def _paired_proof_db(self, *, explicit_db: bool = False) -> Path:
        # Explicit/custom limiter databases remain isolated. In particular, a
        # test monkeypatch must never silently consult the production queue.
        configured = self._db_file == _CONFIGURED_RL_DB_FILE and _RL_DB_FILE == _CONFIGURED_RL_DB_FILE
        override = os.environ.get("PINTEREST_QUEUE_DB_FILE") if configured and not explicit_db else None
        return Path(override) if override else self._db_file.parent / "jobs.db"

    def _proof_routes(self) -> dict[str, tuple[str, frozenset[str]]]:
        cached = getattr(self, "_proof_route_cache", None)
        if cached is not None:
            return cached
        from rankstein.domain import get_registry

        from .routing import account_cohort

        config = get_config()
        routes = {}
        for domain in get_registry().all():
            public_domain = domain.domain if "://" in domain.domain else "//" + domain.domain
            host = (urlparse(public_domain).hostname or "").casefold().removeprefix("www.")
            if host:
                routes[domain.handle] = (host, frozenset(account_cohort(domain.handle, config=config)))
        self._proof_route_cache = routes
        return routes

    def _known_upload_operation(self, operation: str) -> bool:
        parts = operation.split(":")
        if len(parts) != 3 or parts[0] != "pin_upload":
            return False
        route = self._proof_routes().get(parts[1])
        return route is not None and parts[2] in route[1]

    @staticmethod
    def _payload_identity(payload: dict, key: str) -> str:
        extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
        values = {str(value).strip() for value in (payload.get(key), extra.get(key)) if value is not None}
        values.discard("")
        return next(iter(values)) if len(values) == 1 else ""

    def _verified_upload_identity(self, job: dict, routes: dict) -> tuple[str, str] | None:
        if job.get("type") != "pin_upload" or job.get("status") != "completed":
            return None
        payload, result = job.get("payload"), job.get("result")
        if not isinstance(payload, dict) or not isinstance(result, dict) or result.get("success") is not True:
            return None
        domain = self._payload_identity(payload, "domain_handle")
        account = self._payload_identity(payload, "account_handle")
        route = routes.get(domain)
        if route is None or account not in route[1]:
            return None
        article = urlparse(str(payload.get("link") or ""))
        if (
            article.scheme not in {"http", "https"}
            or (article.hostname or "").casefold().removeprefix("www.") != route[0]
        ):
            return None
        pin_id = str(result.get("pin_id") or "")
        pin = urlparse(str(result.get("pin_url") or ""))
        # Match the maintained production reconciler's canonical proof hosts.
        if (
            not _PIN_ID.fullmatch(pin_id)
            or pin.scheme != "https"
            or (pin.hostname or "").casefold() not in {"pinterest.com", "www.pinterest.com"}
            or pin.path.rstrip("/") != f"/pin/{pin_id}"
        ):
            return None
        return f"pin_upload:{domain}:{account}", pin_id

    def _proof_daily_counts(self) -> dict[str, int] | None:
        """Read a bounded, complete proof floor; unavailable is never zero."""
        connection = None
        try:
            path = getattr(self, "_proof_db_file", None) or self._paired_proof_db()
            deadline = time.monotonic() + _PROOF_TIMEOUT_SECONDS
            connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.5)
            connection.execute("PRAGMA query_only=ON")
            connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, _PROOF_MAX_ROW_BYTES)
            connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            end = today + 86400
            routes = self._proof_routes()
            # Both tables share one read snapshot: a completion moving a job
            # into the archive between queries cannot disappear from the floor.
            connection.execute("BEGIN")
            pins: dict[str, set[str]] = {}
            row_count = byte_count = 0
            queries = (
                ("SELECT job_json FROM completed_log WHERE completed_at >= ? AND completed_at < ?", False),
                (
                    "SELECT type, payload_json, status, result_json FROM jobs "
                    "WHERE status = 'completed' AND completed_at >= ? AND completed_at < ?",
                    True,
                ),
            )
            for query, current in queries:
                for row in connection.execute(query, (today, end)):
                    row_count += 1
                    byte_count += sum(len(value.encode("utf-8")) for value in row if isinstance(value, str))
                    if (
                        row_count > _PROOF_MAX_ROWS
                        or byte_count > _PROOF_MAX_BYTES
                        or time.monotonic() > deadline
                    ):
                        raise ValueError("proof scan incomplete")
                    if current:
                        job = {
                            "type": row[0],
                            "payload": json.loads(row[1]),
                            "status": row[2],
                            "result": json.loads(row[3] or "{}"),
                        }
                    else:
                        job = json.loads(row[0])
                    if not isinstance(job, dict):
                        continue
                    identity = self._verified_upload_identity(job, routes)
                    if identity:
                        operation, pin_id = identity
                        pins.setdefault(operation, set()).add(pin_id)
            if time.monotonic() > deadline:
                raise ValueError("proof scan incomplete")
            return {operation: len(values) for operation, values in pins.items()}
        except (OSError, sqlite3.Error, TypeError, ValueError, KeyError, AttributeError) as exc:
            logger.warning("Rate limiter: verified daily proof unavailable: %s", type(exc).__name__)
            return None
        finally:
            if connection is not None:
                connection.close()

    def _counter_daily_counts(self) -> dict[str, int] | None:
        connection = None
        try:
            deadline = time.monotonic() + _PROOF_TIMEOUT_SECONDS
            connection = sqlite3.connect(self._db_file.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.5)
            connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            rows = connection.execute(
                "SELECT operation, MAX(daily_count) FROM rl_counters WHERE day_key = ? GROUP BY operation",
                (self._day_key(),),
            ).fetchall()
            return {operation: count for operation, count in rows}
        except (OSError, sqlite3.Error) as exc:
            logger.warning("Rate limiter: persisted daily reporting unavailable: %s", type(exc).__name__)
            return None
        finally:
            if connection is not None:
                connection.close()

    def _refresh_budget_evidence(self, *, force: bool = False) -> None:
        # Cheap shared counters are always fresh, even within the proof cache
        # window. An instance cannot grant another writer's exhausted budget.
        counters = self._counter_daily_counts()
        if force or time.monotonic() - self._budget_checked_at >= _BUDGET_REFRESH_SECONDS:
            proof = self._proof_daily_counts()
            self._proof_available = proof is not None
            self._proof_budget_counts = proof or {}
            self._budget_checked_at = time.monotonic()
        self._budget_available = counters is not None and self._proof_available
        for counts in (counters, self._proof_budget_counts):
            for operation, count in (counts or {}).items():
                self._daily_counts[operation] = max(self._daily_counts.get(operation, 0), count)

    def _load_persisted(self):
        """Load today/this-hour counts from the DB into in-memory dicts."""
        try:
            conn = _rl_conn(self._db_file)
            rows = conn.execute(
                "SELECT * FROM rl_counters WHERE day_key = ? ORDER BY hour_key",
                (self._day_key(),),
            ).fetchall()
            conn.close()
            current_hour = self._hour_key()
            for row in rows:
                op = row["operation"]
                # Hourly rows contain cumulative daily totals. A restart in a
                # new hour must retain earlier usage without summing snapshots.
                self._daily_counts[op] = max(self._daily_counts.get(op, 0), row["daily_count"])
                if row["hour_key"] == current_hour:
                    self._hourly_counts[op] = row["hourly_count"]
                # Ordered rows recover the latest failure/cooldown state even
                # when there has been no execution in the current hour.
                self._failure_streaks[op] = row["failure_streak"]
                self._cooldown_until[op] = row["cooldown_until"]
        except Exception as e:
            logger.warning("Rate limiter: failed to load persisted state: %s", e)

    def get_persisted_daily_counts(self) -> dict[str, int] | None:
        """Read today's shared totals without changing limiter or database state.

        Domain workers have separate limiter instances, so a global observer's
        cache is not an accurate aggregate. ``None`` means unavailable, not zero.
        """
        counters = self._counter_daily_counts()
        if counters is None:
            return None
        proof = self._proof_daily_counts()
        if proof is None:
            return None
        for operation, count in proof.items():
            counters[operation] = max(counters.get(operation, 0), count)
        return counters

    def _persist(self, operation: str, *, execution: bool = False):
        """Serialize updates; stale instances must not lower another writer's usage."""
        conn = None
        try:
            conn = _rl_conn(self._db_file)
            conn.execute("BEGIN IMMEDIATE")
            day, hour = self._day_key(), self._hour_key()
            persisted_daily = conn.execute(
                "SELECT COALESCE(MAX(daily_count), 0) FROM rl_counters WHERE operation=? AND day_key=?",
                (operation, day),
            ).fetchone()[0]
            persisted_hourly = conn.execute(
                "SELECT COALESCE(MAX(hourly_count), 0) FROM rl_counters WHERE operation=? AND day_key=? AND hour_key=?",
                (operation, day, hour),
            ).fetchone()[0]
            self._daily_counts[operation] = max(
                self._daily_counts.get(operation, 0), persisted_daily + int(execution)
            )
            self._hourly_counts[operation] = max(
                self._hourly_counts.get(operation, 0), persisted_hourly + int(execution)
            )
            conn.execute(
                """
                INSERT INTO rl_counters
                    (operation, day_key, hour_key, daily_count, hourly_count, failure_streak, cooldown_until)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(operation, day_key, hour_key) DO UPDATE SET
                    daily_count    = MAX(rl_counters.daily_count, excluded.daily_count),
                    hourly_count   = MAX(rl_counters.hourly_count, excluded.hourly_count),
                    failure_streak = excluded.failure_streak,
                    cooldown_until = excluded.cooldown_until
                """,
                (
                    operation,
                    day,
                    hour,
                    self._daily_counts.get(operation, 0),
                    self._hourly_counts.get(operation, 0),
                    self._failure_streaks.get(operation, 0),
                    self._cooldown_until.get(operation, 0.0),
                ),
            )
            conn.commit()
        except Exception as e:
            logger.debug("Rate limiter: failed to persist state for '%s': %s", operation, e)
        finally:
            if conn is not None:
                conn.close()

    # ── Public API ────────────────────────────────────────────────────────────

    def _reset_if_needed(self):
        now = datetime.now(UTC)
        if now.strftime("%Y-%m-%d") != self._last_reset_day:
            self._daily_counts.clear()
            self._last_reset_day = now.strftime("%Y-%m-%d")
            self._budget_checked_at = float("-inf")
            logger.info("Daily rate limit counters reset")
        if now.strftime("%Y-%m-%dT%H") != self._last_reset_hour:
            self._hourly_counts.clear()
            self._last_reset_hour = now.strftime("%Y-%m-%dT%H")
            logger.info("Hourly rate limit counters reset")

    def _get_jittered_delay(self, base: float) -> float:
        jitter = base * self.config.jitter_percent * (random.random() * 2 - 1)
        return max(1.0, min(base + jitter, self.config.max_delay_seconds))

    def can_execute(self, operation: str = "pin_post") -> bool:
        with self._lock:
            self._reset_if_needed()
            if operation.startswith("pin_upload"):
                self._refresh_budget_evidence()
                if not self._budget_available or not self._known_upload_operation(operation):
                    return False

            # Check cooldown
            cooldown_end = self._cooldown_until.get(operation, 0)
            if time.time() < cooldown_end:
                return False

            # Check daily limit
            if self._daily_counts.get(operation, 0) >= self.config.daily_pin_limit:
                return False

            # Check hourly limit
            if self._hourly_counts.get(operation, 0) >= self.config.hourly_pin_limit:
                return False

            return True

    def retry_after_seconds(self, operation: str = "pin_post") -> float:
        """Return the next useful retry delay when an operation is rate limited."""
        with self._lock:
            self._reset_if_needed()
            if operation.startswith("pin_upload"):
                self._refresh_budget_evidence()
            now_epoch = time.time()
            delays = [max(0.0, self._cooldown_until.get(operation, 0) - now_epoch)]
            if operation.startswith("pin_upload") and (
                not self._budget_available or not self._known_upload_operation(operation)
            ):
                delays.append(_UNKNOWN_BUDGET_RETRY_SECONDS)
            now = datetime.now(UTC)

            if self._daily_counts.get(operation, 0) >= self.config.daily_pin_limit:
                next_day = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                delays.append((next_day - now).total_seconds())

            if self._hourly_counts.get(operation, 0) >= self.config.hourly_pin_limit:
                next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
                delays.append((next_hour - now).total_seconds())

            return max(delays, default=0.0)

    def record_execution(self, operation: str = "pin_post"):
        with self._lock:
            self._reset_if_needed()
            self._refresh_budget_evidence(force=True)
            self._daily_counts[operation] = self._daily_counts.get(operation, 0) + 1
            self._hourly_counts[operation] = self._hourly_counts.get(operation, 0) + 1
            self._failure_streaks[operation] = 0
            self._persist(operation, execution=True)

    def record_failure(self, operation: str = "pin_post"):
        with self._lock:
            self._reset_if_needed()
            self._failure_streaks[operation] = self._failure_streaks.get(operation, 0) + 1
            if self._failure_streaks[operation] >= self.config.cooldown_after_failures:
                cooldown_sec = self.config.cooldown_duration_minutes * 60
                self._cooldown_until[operation] = time.time() + cooldown_sec
                logger.warning(
                    f"Rate limiter: Entering {self.config.cooldown_duration_minutes}min cooldown "
                    f"for '{operation}' after {self._failure_streaks[operation]} failures"
                )
            self._persist(operation)

    def get_delay(self, operation: str = "pin_post") -> float:
        """Calculate recommended delay before next execution."""
        with self._lock:
            self._reset_if_needed()
            base = self.config.base_delay_seconds

            # Increase delay based on recent activity
            hourly = self._hourly_counts.get(operation, 0)
            if hourly >= self.config.burst_limit:
                base *= 1 + (hourly - self.config.burst_limit) * 0.5

            # Increase delay based on failure streak
            failures = self._failure_streaks.get(operation, 0)
            if failures > 0:
                base *= 1.5**failures

            return self._get_jittered_delay(min(base, self.config.max_delay_seconds))

    def wait(self, operation: str = "pin_post"):
        """Sleep for the recommended delay (blocking)."""
        delay = self.get_delay(operation)
        if delay > 0:
            logger.info(f"Rate limiter: sleeping {delay:.1f}s before '{operation}'")
            time.sleep(delay)

    async def wait_async(self, operation: str = "pin_post"):
        """Sleep for the recommended delay (non-blocking)."""
        import asyncio

        delay = self.get_delay(operation)
        if delay > 0:
            logger.info(f"Rate limiter: sleeping {delay:.1f}s before '{operation}'")
            await asyncio.sleep(delay)

    def get_status(self) -> dict:
        with self._lock:
            self._reset_if_needed()
            return {
                "daily_counts": dict(self._daily_counts),
                "hourly_counts": dict(self._hourly_counts),
                "failure_streaks": dict(self._failure_streaks),
                "cooldowns": {k: max(0, v - time.time()) for k, v in self._cooldown_until.items()},
                "limits": {
                    "daily": self.config.daily_pin_limit,
                    "hourly": self.config.hourly_pin_limit,
                    "burst": self.config.burst_limit,
                },
                "upload_budget_evidence_available": self._budget_available,
            }


# ── Singletons ────────────────────────────────────────────────────────────────
_rate_limiter: RateLimiter | None = None
_rate_limiters: dict[str, RateLimiter] = {}


def get_rate_limiter(domain_handle: str | None = None) -> RateLimiter:
    global _rate_limiter, _rate_limiters
    if domain_handle:
        if domain_handle not in _rate_limiters:
            limiter = RateLimiter()
            from rankstein.domain import get_registry

            try:
                domain = get_registry().get(domain_handle)
                # Apply domain-specific daily budget if configured
                if domain.daily_pin_budget:
                    limiter.config.daily_pin_limit = domain.daily_pin_budget
            except Exception as e:
                logger.warning(
                    "Failed to load domain '%s' for rate limiter configuration: %s", domain_handle, e
                )
            _rate_limiters[domain_handle] = limiter
        return _rate_limiters[domain_handle]

    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


def _reset_rate_limiter_singleton() -> None:
    """Test-only: clear cached singletons."""
    global _rate_limiter, _rate_limiters
    _rate_limiter = None
    _rate_limiters.clear()

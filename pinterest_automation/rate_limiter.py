"""
RankStein Pinterest Automation — Intelligent Rate Limiter
Token-bucket style with jitter, anti-detection patterns, and adaptive backoff.

Counts are now persisted to a small SQLite table so daily/hourly budgets survive
process restarts (e.g. Windows sleep, crash, manual stop).  On init the persisted
rows are loaded back; on every record_execution / record_failure the rows are
updated atomically.  A fresh row is inserted automatically if one doesn't exist.
"""

import logging
import os
import random
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock

from .config import DATA_DIR, get_config

logger = logging.getLogger("rankstein.rate_limiter")

# ── Persistent state DB ───────────────────────────────────────────────────────
_RL_DB_FILE = Path(os.environ.get("PINTEREST_RATE_LIMIT_DB_FILE") or DATA_DIR / "queue" / "rate_limiter.db")

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

    def __init__(self, db_file: Path | None = None):
        import copy

        self.config = copy.deepcopy(get_config().rate_limit)
        self._lock = Lock()
        self._db_file = db_file or _RL_DB_FILE
        # In-memory caches (loaded from DB on init, flushed on every mutation)
        self._daily_counts: dict[str, int] = {}
        self._hourly_counts: dict[str, int] = {}
        self._failure_streaks: dict[str, int] = {}
        self._cooldown_until: dict[str, float] = {}
        self._last_reset_day = datetime.now(UTC).day
        self._last_reset_hour = datetime.now(UTC).hour
        self._load_persisted()

    # ── Persistence helpers ───────────────────────────────────────────────────

    def _day_key(self) -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    def _hour_key(self) -> str:
        return datetime.now(UTC).strftime("%Y-%m-%dT%H")

    def _load_persisted(self):
        """Load today/this-hour counts from the DB into in-memory dicts."""
        try:
            conn = _rl_conn(self._db_file)
            rows = conn.execute(
                "SELECT * FROM rl_counters WHERE day_key = ? AND hour_key = ?",
                (self._day_key(), self._hour_key()),
            ).fetchall()
            conn.close()
            for row in rows:
                op = row["operation"]
                self._daily_counts[op] = row["daily_count"]
                self._hourly_counts[op] = row["hourly_count"]
                self._failure_streaks[op] = row["failure_streak"]
                self._cooldown_until[op] = row["cooldown_until"]
        except Exception as e:
            logger.warning("Rate limiter: failed to load persisted state: %s", e)

    def _persist(self, operation: str):
        """Upsert current state for operation into DB."""
        try:
            conn = _rl_conn(self._db_file)
            conn.execute(
                """
                INSERT INTO rl_counters
                    (operation, day_key, hour_key, daily_count, hourly_count, failure_streak, cooldown_until)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(operation, day_key, hour_key) DO UPDATE SET
                    daily_count    = excluded.daily_count,
                    hourly_count   = excluded.hourly_count,
                    failure_streak = excluded.failure_streak,
                    cooldown_until = excluded.cooldown_until
                """,
                (
                    operation,
                    self._day_key(),
                    self._hour_key(),
                    self._daily_counts.get(operation, 0),
                    self._hourly_counts.get(operation, 0),
                    self._failure_streaks.get(operation, 0),
                    self._cooldown_until.get(operation, 0.0),
                ),
            )
            conn.close()
        except Exception as e:
            logger.debug("Rate limiter: failed to persist state for '%s': %s", operation, e)

    # ── Public API ────────────────────────────────────────────────────────────

    def _reset_if_needed(self):
        now = datetime.now(UTC)
        if now.day != self._last_reset_day:
            self._daily_counts.clear()
            self._last_reset_day = now.day
            logger.info("Daily rate limit counters reset")
        if now.hour != self._last_reset_hour:
            self._hourly_counts.clear()
            self._last_reset_hour = now.hour
            logger.info("Hourly rate limit counters reset")

    def _get_jittered_delay(self, base: float) -> float:
        jitter = base * self.config.jitter_percent * (random.random() * 2 - 1)
        return max(1.0, min(base + jitter, self.config.max_delay_seconds))

    def can_execute(self, operation: str = "pin_post") -> bool:
        with self._lock:
            self._reset_if_needed()

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
            now_epoch = time.time()
            delays = [max(0.0, self._cooldown_until.get(operation, 0) - now_epoch)]
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
            self._daily_counts[operation] = self._daily_counts.get(operation, 0) + 1
            self._hourly_counts[operation] = self._hourly_counts.get(operation, 0) + 1
            self._failure_streaks[operation] = 0
            self._persist(operation)

    def record_failure(self, operation: str = "pin_post"):
        with self._lock:
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

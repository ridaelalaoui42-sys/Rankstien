"""
RankStein Pinterest Automation — Health Monitor & Watchdog
Persistent health tracking with automatic recovery triggers.
"""

import json
import logging
import os
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from .config import DATA_DIR, PROJECT_ROOT, get_config

logger = logging.getLogger("rankstein.health")

HEALTH_STATE_FILE = Path(os.environ.get("PINTEREST_HEALTH_STATE_FILE") or DATA_DIR / "health_state.json")


@dataclass
class HealthCheck:
    name: str
    ok: bool
    detail: str
    timestamp: float = field(default_factory=lambda: datetime.now(UTC).timestamp())
    severity: str = "info"  # info, warning, critical


@dataclass
class HealthSnapshot:
    all_ok: bool = False
    checks: dict[str, dict] = field(default_factory=dict)
    timestamp: float = field(default_factory=lambda: datetime.now(UTC).timestamp())
    uptime_seconds: float = 0.0
    consecutive_failures: int = 0


class HealthMonitor:
    """
    Persistent health monitor that tracks system state across restarts.
    Triggers recovery callbacks when health degrades.
    """

    def __init__(self):
        self.config = get_config().health
        self._state_file = HEALTH_STATE_FILE
        self._lock = Lock()
        self._start_time = datetime.now(UTC)
        self._recovery_handlers: list[Callable[[str, dict], None]] = []
        self._last_heartbeat = 0.0
        self._consecutive_failures = 0
        self._last_snapshot = HealthSnapshot()
        self._load_state()
        # Initial check to populate first snapshot
        self.heartbeat()

    def _load_state(self):
        if self._state_file.exists():
            try:
                data = json.loads(self._state_file.read_text(encoding="utf-8"))
                self._consecutive_failures = data.get("consecutive_failures", 0)
                self._last_heartbeat = data.get("last_heartbeat", 0)
            except Exception as e:
                logger.warning(f"Failed to load health state: {e}")

    def _save_state(self):
        try:
            state = {
                "consecutive_failures": self._consecutive_failures,
                "last_heartbeat": self._last_heartbeat,
                "timestamp": datetime.now(UTC).timestamp(),
            }
            self._state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to save health state: {e}")

    def register_recovery_handler(self, handler: Callable[[str, dict], None]):
        """Register a callback for recovery actions: handler(check_name, check_data)"""
        self._recovery_handlers.append(handler)

    def heartbeat(self) -> HealthSnapshot:
        """Run all health checks and update the cached snapshot. (Blocking)"""
        with self._lock:
            now = datetime.now(UTC).timestamp()
            self._last_heartbeat = now
            uptime = now - self._start_time.timestamp()

            checks: dict[str, HealthCheck] = {}

            # 1. Disk space
            try:
                usage = shutil.disk_usage(PROJECT_ROOT)
                free_gb = round(usage.free / (1024**3), 1)
                checks["disk_space"] = HealthCheck(
                    "disk_space",
                    free_gb > self.config.disk_space_threshold_gb,
                    f"{free_gb} GB free",
                    severity="critical" if free_gb < 0.5 else "info",
                )
            except Exception as e:
                checks["disk_space"] = HealthCheck("disk_space", True, f"unknown: {e}")

            # 2. Log size
            log_files = list(DATA_DIR.glob("rankstein_mcp*.log*"))
            if log_files:
                log_mb = round(sum(path.stat().st_size for path in log_files) / (1024 * 1024), 1)
                checks["log_size"] = HealthCheck(
                    "log_size",
                    log_mb < self.config.log_size_threshold_mb,
                    f"{log_mb} MB total",
                    severity="warning" if log_mb >= 50 else "info",
                )
            else:
                checks["log_size"] = HealthCheck("log_size", True, "no log file")

            # 3. Session availability. Cookie modification time is diagnostic
            # only; a successful browser login check is the authentication gate.
            config = get_config()
            configured_sessions = {
                handle: account.session_name
                for handle, account in config.accounts.items()
                if account.session_name
            }
            if not configured_sessions:
                configured_sessions = {"default": config.browser.session_name}

            missing_sessions = []
            session_ages = []
            for handle, session_name in configured_sessions.items():
                session_dir = DATA_DIR / "sessions" / session_name
                cookies = (
                    list(session_dir.glob("*.sqlite")) + list(session_dir.glob("**/Cookies"))
                    if session_dir.exists()
                    else []
                )
                if cookies:
                    newest = max(cookies, key=lambda f: f.stat().st_mtime)
                    age_days = (now - newest.stat().st_mtime) / 86400
                    session_ages.append((handle, age_days))
                else:
                    missing_sessions.append(handle)

            credentials_configured = config.credentials.valid or any(
                account.valid for account in config.accounts.values()
            )
            if missing_sessions:
                checks["session_freshness"] = HealthCheck(
                    "session_freshness",
                    not credentials_configured,
                    f"Missing cookie state for: {', '.join(sorted(missing_sessions))}",
                    severity="warning" if credentials_configured else "info",
                )
            else:
                oldest_handle, oldest_age = max(session_ages, key=lambda item: item[1])
                checks["session_freshness"] = HealthCheck(
                    "session_freshness",
                    True,
                    (
                        f"{len(session_ages)} account profile(s) present; "
                        f"oldest cookie metadata is {oldest_age:.1f} days ({oldest_handle})"
                    ),
                    severity="info",
                )

            # 4. Pinterest credentials
            creds = config.credentials
            valid_account_handles = sorted(
                handle for handle, account in config.accounts.items() if account.valid
            )
            credentials_ok = creds.valid or bool(valid_account_handles)
            checks["pinterest_credentials"] = HealthCheck(
                "pinterest_credentials",
                credentials_ok,
                (
                    "set"
                    if creds.valid
                    else f"set via accounts: {', '.join(valid_account_handles)}"
                    if valid_account_handles
                    else "MISSING"
                ),
                severity="critical" if not credentials_ok else "info",
            )

            # 5. Supabase connectivity
            sb = get_config().supabase
            checks["supabase_config"] = HealthCheck(
                "supabase_config",
                sb.valid,
                "set" if sb.valid else "MISSING",
                severity="warning" if not sb.valid else "info",
            )

            # 6. Queue health
            try:
                from .job_queue import get_job_queue

                qstats = get_job_queue().get_stats()
                pending = qstats.get("total", 0)
                dlq_size = qstats.get("dlq_size", 0)
                by_status = qstats.get("by_status", {})

                # A DLQ row is unresolved production work and must be visible in
                # the top-level health signal, even while workers keep running.
                queue_ok = pending < 50000 and dlq_size == 0
                checks["queue_health"] = HealthCheck(
                    "queue_health",
                    queue_ok,
                    f"{pending} pending ({by_status}), {dlq_size} in DLQ",
                    severity="warning" if not queue_ok else "info",
                )
            except Exception as e:
                checks["queue_health"] = HealthCheck("queue_health", True, f"queue stats error: {e}")

            all_ok = all(c.ok for c in checks.values())
            if not all_ok:
                self._consecutive_failures += 1
            else:
                self._consecutive_failures = 0

            snapshot = HealthSnapshot(
                all_ok=all_ok,
                checks={k: asdict(v) for k, v in checks.items()},
                timestamp=now,
                uptime_seconds=uptime,
                consecutive_failures=self._consecutive_failures,
            )

            self._last_snapshot = snapshot
            self._save_state()

            # Trigger recovery handlers for failing checks
            if not all_ok:
                for name, check in checks.items():
                    if not check.ok and check.severity in ("warning", "critical"):
                        for handler in self._recovery_handlers:
                            try:
                                handler(name, asdict(check))
                            except Exception as e:
                                logger.error(f"Recovery handler error for {name}: {e}")

            return snapshot

    def is_healthy(self) -> bool:
        """Non-blocking check of the last known health state."""
        return self._last_snapshot.all_ok

    def get_snapshot(self) -> HealthSnapshot:
        """Non-blocking access to the last known health state."""
        return self._last_snapshot

    async def start_monitoring(self, interval_seconds: float = 60.0):
        """Background loop to update health periodically without blocking."""
        import asyncio

        logger.info(f"Health monitoring background loop started (interval: {interval_seconds}s)")
        while True:
            try:
                await asyncio.to_thread(self.heartbeat)
            except Exception as e:
                logger.error(f"Health monitor loop error: {e}")
            await asyncio.sleep(interval_seconds)

    def reset_failure_count(self):
        with self._lock:
            self._consecutive_failures = 0
            self._save_state()


# Singleton
_health_monitor: HealthMonitor | None = None


def get_health_monitor() -> HealthMonitor:
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = HealthMonitor()
    return _health_monitor

"""
RankStein Pinterest Automation — Autonomous Supervisor
Keeps the system running 24/7 with automatic recovery, queue processing, and health monitoring.
"""

import asyncio
import logging
import os
import signal
import time
from datetime import datetime
from pathlib import Path

from .circuit_breaker import CircuitBreakerOpenError, get_circuit_breaker
from .config import get_config
from .health_monitor import get_health_monitor
from .job_queue import Job, get_job_queue
from .pinterest_driver import PinterestDriver
from .rate_limiter import get_rate_limiter
from .session_pool import get_session_pool

logger = logging.getLogger("rankstein.supervisor")


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


PIN_UPLOAD_JOB_TIMEOUT_SECONDS = max(60, _int_env("PINTEREST_PIN_UPLOAD_JOB_TIMEOUT_SECONDS", 210))
PIN_SAVE_JOB_TIMEOUT_SECONDS = max(45, _int_env("PINTEREST_PIN_SAVE_JOB_TIMEOUT_SECONDS", 120))
STALE_REQUEUE_INTERVAL_SECONDS = max(30, _int_env("PINTEREST_STALE_REQUEUE_INTERVAL_SECONDS", 60))


class AutonomousSupervisor:
    """
    Production supervisor that:
    - Processes the job queue continuously
    - Runs health checks on interval
    - Recovers from failures automatically
    - Manages graceful shutdown
    - Reports status
    """

    def __init__(self):
        config_obj = get_config()
        self.config = config_obj.supervisor
        # Handle dict if loaded from JSON without proper deserialization
        if isinstance(self.config, dict):
            from .config import SupervisorConfig

            self.config = SupervisorConfig(**self.config)

        self.health = get_health_monitor()
        self.queue = get_job_queue()
        self.circuit = get_circuit_breaker()
        self.rate_limiter = get_rate_limiter()
        self.pool = get_session_pool()
        self._shutdown_event = asyncio.Event()
        self._restart_count = 0
        self._last_restart_time = 0.0
        self._running = False
        self._driver: PinterestDriver | None = None
        self._last_stale_requeue = 0.0
        self._account_locks: dict[str, asyncio.Lock] = {}

        # Register recovery handler
        self.health.register_recovery_handler(self._on_health_issue)

        # Register circuit breaker callback
        self.circuit.register_state_change_callback(self._on_circuit_change)

    def _default_account_handle(self) -> str | None:
        cfg = get_config()
        explicit = (
            os.environ.get("PINTEREST_DEFAULT_ACCOUNT_HANDLE")
            or os.environ.get("PINTEREST_ACCOUNT_HANDLE")
            or ""
        ).strip()
        if explicit:
            if explicit in cfg.accounts:
                return explicit
            logger.error(
                "Configured default Pinterest account handle %r is not present; available handles: %s",
                explicit,
                ", ".join(sorted(cfg.accounts)) or "none",
            )
            return "__unknown__"

        for preferred in ("rida", "media", "r1", "r2", "r3", "r4", "r5", "r6"):
            if preferred in cfg.accounts:
                return preferred

        if cfg.accounts:
            return sorted(cfg.accounts)[0]
        return None

    def _on_health_issue(self, check_name: str, check_data: dict):
        logger.warning(f"Health issue detected: {check_name} = {check_data}")
        if check_name == "session_freshness" and not check_data.get("ok"):
            logger.info("Recovery: Session stale, will force session rotation on next job")
            # Force close current driver so next acquire gets fresh session
            asyncio.create_task(self._rotate_session())
        elif check_name == "disk_space" and not check_data.get("ok"):
            logger.critical("Recovery: Disk space critical! Purging old logs...")
            # Could trigger log cleanup here

    def _on_circuit_change(self, operation: str, state):
        logger.warning(f"Circuit '{operation}' changed to {state.value}")
        if state.value == "open":
            # Force cooldown
            self.rate_limiter.record_failure(operation)

    async def _rotate_session(self):
        if self._driver:
            try:
                await self._driver.close()
            except Exception as e:
                logger.warning(f"Session rotation error: {e}")
            self._driver = None

    async def _get_driver(self) -> PinterestDriver:
        if self._driver is None:
            self._driver = PinterestDriver()
        return self._driver

    def _account_handle_for_job(self, job: Job) -> str | None:
        payload = job.payload or {}
        handle = payload.get("account_handle") or payload.get("extra", {}).get("account_handle")
        if not handle:
            return self._default_account_handle()
        handle = str(handle).strip()
        if not handle:
            return None
        if handle not in get_config().accounts:
            legacy_handle = None
            if handle.startswith("r") and "rida" in get_config().accounts:
                legacy_handle = "rida"
            elif handle.startswith("m") and "media" in get_config().accounts:
                legacy_handle = "media"
            if legacy_handle:
                logger.info("Mapped legacy Pinterest account handle %r to %r", handle, legacy_handle)
                return legacy_handle
        if handle not in get_config().accounts:
            logger.error(
                "Job %s references unknown Pinterest account handle %r; configured handles are: %s",
                job.id,
                handle,
                ", ".join(sorted(get_config().accounts)) or "none",
            )
            return "__unknown__"
        return handle

    def _lock_for_account(self, account_handle: str | None, board_name: str | None = None) -> asyncio.Lock:
        """Get or create an async lock for a specific account-board combination.
        
        Using (handle, board) as the lock key allows parallel uploads for the same 
        account to DIFFERENT boards, increasing throughput while respecting 
        Pinterest's likely per-board session constraints.
        """
        handle_key = account_handle or "default"
        board_key = board_name or "default_board"
        key = f"{handle_key}:{board_key}"
        
        lock = self._account_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._account_locks[key] = lock
        return lock

    async def _process_job(self, job: Job) -> bool:
        """Process a single job. Returns True if successful."""
        driver = await self._get_driver()
        start = time.time()

        try:
            if job.type == "pin_upload":
                payload = job.payload
                # Ensure logged in
                if not await driver.ensure_logged_in():
                    await self.queue.retry_or_fail_async(job.id, "Login failed")
                    return False

                # Create pin
                result = await driver.create_pin(
                    image_path=payload["image_path"],
                    title=payload["title"],
                    description=payload["description"],
                    link=payload.get("link", ""),
                    alt_text=payload.get("alt_text", ""),
                    board_name=payload.get("board_name") or get_config().default_board,
                )

                if result.get("success"):
                    elapsed = time.time() - start
                    logger.info(f"Job {job.id} succeeded in {elapsed:.1f}s")
                    await self.queue.complete_async(job.id, result)
                    
                    # Delete local image to free space after successful upload
                    image_path = payload.get("image_path")
                    if image_path:
                        if os.path.exists(image_path):
                            try:
                                os.remove(image_path)
                                logger.info(f"Deleted uploaded image {image_path}")
                            except Exception as e:
                                logger.warning(f"Failed to delete {image_path}: {e}")
                        
                        # Also try to delete from remaster_raw if it exists
                        _raw_dir = Path(__file__).resolve().parent.parent / "data" / "media" / "remaster_raw"
                        filename = os.path.basename(image_path)
                        raw_path = str(_raw_dir / filename)
                        if os.path.exists(raw_path):
                            try:
                                os.remove(raw_path)
                                logger.info(f"Deleted raw image {raw_path}")
                            except Exception as e:
                                logger.warning(f"Failed to delete raw image {raw_path}: {e}")
                    
                    return True
                else:
                    error = result.get("error", "Unknown error")
                    await self.queue.retry_or_fail_async(job.id, error)
                    return False
            else:
                await self.queue.retry_or_fail_async(job.id, f"Unknown job type: {job.type}")
                return False

        except CircuitBreakerOpenError as e:
            logger.warning(f"Job {job.id} blocked by circuit breaker: {e}")
            # Put back in queue for retry later
            await self.queue.retry_or_fail_async(job.id, str(e))
            return False
        except Exception as e:
            logger.exception(f"Job {job.id} crashed: {e}")
            await self.queue.retry_or_fail_async(job.id, str(e))
            return False

    async def _queue_worker(self, worker_id: int):
        """Continuously process jobs from the queue."""
        logger.info(f"Queue worker {worker_id} started")

        # Each worker gets its own driver instance
        driver = PinterestDriver()

        try:
            while not self._shutdown_event.is_set():
                try:
                    # 1. Health Guard (Fix #17)
                    # Non-blocking check. If system health is degraded (e.g. disk full),
                    # this worker pauses independently. Other workers and the reporter continue.
                    snap = self.health.get_snapshot()
                    if not snap.all_ok:
                        logger.warning(f"Worker {worker_id} pausing: System health DEGRADED")
                        await asyncio.sleep(self.config.watch_interval_seconds * 2)
                        continue

                    # 2. Rate limit wait (non-blocking)
                    await self.rate_limiter.wait_async("pin_upload")

                    # 3. Dequeue
                    job = await self.queue.dequeue_async()
                    if job is None:
                        await asyncio.sleep(self.config.watch_interval_seconds)
                        continue

                    logger.info(f"Worker {worker_id} processing job {job.id}")

                    try:
                        payload = job.payload
                        account_handle = self._account_handle_for_job(job)
                        if account_handle == "__unknown__":
                            await self.queue.retry_or_fail_async(job.id, "Unknown Pinterest account handle")
                            continue

                        # Extract board name for finer-grained locking (Fix #16)
                        board_name = payload.get("board_name") or get_config().default_board
                        
                        account_lock = self._lock_for_account(account_handle, board_name)
                        if account_lock.locked():
                            logger.info(
                                "Worker %s waiting for lock: %s:%s",
                                worker_id,
                                account_handle or "default",
                                board_name
                            )

                        async with account_lock:
                            if job.type == "pin_upload":
                                # Ensure logged in
                                if not await driver.ensure_logged_in(account_handle):
                                    await driver.close()
                                    await self.queue.retry_or_fail_async(job.id, "Login failed")
                                    continue

                                # Create pin
                                start = time.time()
                                result = await asyncio.wait_for(
                                    driver.create_pin(
                                        image_path=payload["image_path"],
                                        title=payload["title"],
                                        description=payload["description"],
                                        link=payload.get("link", ""),
                                        alt_text=payload.get("alt_text", ""),
                                        board_name=payload.get("board_name") or get_config().default_board,
                                        account_handle=account_handle,
                                    ),
                                    timeout=PIN_UPLOAD_JOB_TIMEOUT_SECONDS,
                                )

                                if result.get("success"):
                                    elapsed = time.time() - start
                                    logger.info(
                                        f"Worker {worker_id}: Job {job.id} succeeded in {elapsed:.1f}s"
                                    )
                                    await self.queue.complete_async(job.id, result)

                                    # Dedicated success logging
                                    self._log_success(account_handle, "upload", result, payload.get("title"))

                                    # Cross-save automation
                                    if result.get("pin_url"):
                                        await self._enqueue_cross_save(job, result["pin_url"])
                                        
                                    # Delete local image to free space after successful upload
                                    image_path = payload.get("image_path")
                                    if image_path:
                                        if os.path.exists(image_path):
                                            try:
                                                os.remove(image_path)
                                                logger.info(f"Worker {worker_id}: Deleted uploaded image {image_path}")
                                            except Exception as e:
                                                logger.warning(f"Worker {worker_id}: Failed to delete {image_path}: {e}")
                                                
                                        # Also try to delete from remaster_raw if it exists
                                        _raw_dir = Path(__file__).resolve().parent.parent / "data" / "media" / "remaster_raw"
                                        filename = os.path.basename(image_path)
                                        raw_path = str(_raw_dir / filename)
                                        if os.path.exists(raw_path):
                                            try:
                                                os.remove(raw_path)
                                                logger.info(f"Worker {worker_id}: Deleted raw image {raw_path}")
                                            except Exception as e:
                                                logger.warning(f"Worker {worker_id}: Failed to delete raw image {raw_path}: {e}")
                                else:
                                    error = result.get("error", "Unknown error")
                                    await self.queue.retry_or_fail_async(job.id, error)

                            elif job.type == "pin_save":
                                # Ensure logged in
                                if not await driver.ensure_logged_in(account_handle):
                                    await driver.close()
                                    await self.queue.retry_or_fail_async(job.id, "Login failed")
                                    continue

                                # Save pin
                                start = time.time()
                                result = await asyncio.wait_for(
                                    driver.save_pin(
                                        pin_url=payload["pin_url"],
                                        board_name=payload.get("board_name") or get_config().default_board,
                                        account_handle=account_handle,
                                    ),
                                    timeout=PIN_SAVE_JOB_TIMEOUT_SECONDS,
                                )

                                if result.get("success"):
                                    elapsed = time.time() - start
                                    logger.info(
                                        f"Worker {worker_id}: Save Job {job.id} succeeded in {elapsed:.1f}s"
                                    )
                                    await self.queue.complete_async(job.id, result)

                                    # Dedicated success logging
                                    self._log_success(account_handle, "save", result, payload.get("pin_url"))
                                else:
                                    error = result.get("error", "Unknown error")
                                    await self.queue.retry_or_fail_async(job.id, error)
                            else:
                                await self.queue.retry_or_fail_async(job.id, f"Unknown job type: {job.type}")

                    except CircuitBreakerOpenError as e:
                        logger.warning(f"Worker {worker_id}: Job {job.id} blocked by circuit breaker: {e}")
                        await self.queue.retry_or_fail_async(job.id, str(e))
                    except TimeoutError as e:
                        logger.warning(
                            "Worker %s: Job %s timed out after %ss; rotating session and retrying",
                            worker_id,
                            job.id,
                            PIN_UPLOAD_JOB_TIMEOUT_SECONDS
                            if job.type == "pin_upload"
                            else PIN_SAVE_JOB_TIMEOUT_SECONDS,
                        )
                        await driver.close()
                        driver = PinterestDriver()
                        await self.queue.retry_or_fail_async(job.id, f"Timed out: {e}")
                    except Exception as e:
                        logger.exception(f"Worker {worker_id}: Job {job.id} crashed: {e}")
                        if any(
                            marker in str(e).lower()
                            for marker in (
                                "target page",
                                "browser has been closed",
                                "connection closed",
                                "login",
                            )
                        ):
                            await driver.close()
                            driver = PinterestDriver()
                        await self.queue.retry_or_fail_async(job.id, str(e))

                    # Brief pause between jobs
                    await asyncio.sleep(2)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.exception(f"Queue worker {worker_id} error: {e}")
                    await asyncio.sleep(self.config.watch_interval_seconds)
        finally:
            await driver.close()
            logger.info(f"Queue worker {worker_id} stopped")

    async def _enqueue_cross_save(self, job: Job, pin_url: str):
        """Enqueue save jobs for ALL other configured Pinterest accounts.

        After account X uploads a pin, every other account gets a
        pin_save job so the content is cross-pollinated across the
        full account portfolio.  Scales to N accounts automatically.
        """
        current_handle = (
            job.payload.get("account_handle")
            or job.payload.get("extra", {}).get("account_handle")
            or "default"
        )
        # Normalise legacy handles (r1->rida, m1->media, etc.)
        cfg = get_config()
        if current_handle not in cfg.accounts:
            if current_handle.startswith("r") and "rida" in cfg.accounts:
                current_handle = "rida"
            elif current_handle.startswith("m") and "media" in cfg.accounts:
                current_handle = "media"

        all_handles = sorted(cfg.accounts.keys())
        targets = [h for h in all_handles if h != current_handle]

        for target_handle in targets:
            logger.info(f"Auto-enqueuing cross-save for {target_handle} from {current_handle}")
            await self.queue.enqueue_async(
                Job(
                    type="pin_save",
                    payload={
                        "pin_url": pin_url,
                        "account_handle": target_handle,
                        "board_name": job.payload.get("board_name", ""),
                        "source_job_id": job.id,
                    },
                    # Cross-saves run just after new uploads (priority + 1 = lower urgency),
                    # clamped to [2, 9] so they never starve new content when the queue grows.
                    priority=max(2, min(9, job.priority + 1)),
                )
            )

    def _log_success(self, account: str | None, job_type: str, result: dict, target: str | None):
        """Append success to a dedicated CSV log for tracking."""
        from .config import LOG_DIR

        log_file = LOG_DIR / "success_tracker.csv"

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        account_name = account or "default"
        pin_id = result.get("pin_id") or "N/A"
        pin_url = (
            result.get("pin_url") or f"https://www.pinterest.com/pin/{pin_id}/" if pin_id != "N/A" else "N/A"
        )
        target_info = str(target or "N/A").replace(",", " ")

        # Write header if new
        if not log_file.exists():
            try:
                log_file.write_text("timestamp,account,type,pin_id,pin_url,target\n", encoding="utf-8")
            except:
                pass

        line = f"{timestamp},{account_name},{job_type},{pin_id},{pin_url},{target_info}\n"
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(line)
            logger.info(f"SUCCESS TRACKER: {account_name} | {job_type} | {pin_id}")
        except Exception as e:
            logger.warning(f"Failed to write to success tracker: {e}")

    async def _health_reporter(self):
        """Periodic health and status reporting."""
        while not self._shutdown_event.is_set():
            try:
                snap = self.health.get_snapshot()
                queue_stats = await self.queue.get_stats_async()
                pool_stats = self.pool.get_stats()
                rate_status = self.rate_limiter.get_status()

                status_line = (
                    f"[STATUS] health={'OK' if snap.all_ok else 'DEGRADED'} "
                    f"queue={queue_stats['total']} "
                    f"sessions={pool_stats['active_sessions']} "
                    f"daily_pins={rate_status['daily_counts'].get('pin_upload', 0)}"
                )
                logger.info(status_line)

                now = time.time()
                if now - self._last_stale_requeue >= STALE_REQUEUE_INTERVAL_SECONDS:
                    recovered = await self.queue.requeue_stale_processing_async()
                    self._last_stale_requeue = now
                    if recovered:
                        logger.warning("Recovered %s stale processing job(s)", recovered)

                await asyncio.wait_for(
                    self._shutdown_event.wait(), timeout=self.config.watch_interval_seconds * 6
                )
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health reporter error: {e}")
                await asyncio.sleep(self.config.watch_interval_seconds)

    async def run(self):
        """Start the autonomous supervisor."""
        logger.info("=" * 60)
        logger.info(
            f"RankStein Pinterest Automation Supervisor starting ({self.config.worker_count} workers)"
        )
        logger.info("=" * 60)

        self._running = True
        self._shutdown_event.clear()

        # Setup signal handlers
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, self._request_shutdown)
        except (NotImplementedError, ValueError):
            pass  # Windows or no signals

        # Initial health check
        snap = self.health.heartbeat()
        if not snap.all_ok:
            logger.warning("Initial health check found issues, starting anyway...")

        # Start tasks
        tasks = [
            asyncio.create_task(self._health_reporter()),
            asyncio.create_task(self.health.start_monitoring(self.health.config.heartbeat_interval_seconds)),
        ]

        for i in range(self.config.worker_count):
            tasks.append(asyncio.create_task(self._queue_worker(i)))
            # Stagger startup to prevent resource spikes
            await asyncio.sleep(2)

        try:
            await self._shutdown_event.wait()
        finally:
            logger.info("Shutdown requested, stopping workers...")
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._cleanup()
            self._running = False
            logger.info("Supervisor stopped")

    def _request_shutdown(self):
        logger.info("Shutdown signal received")
        self._shutdown_event.set()

    async def _cleanup(self):
        try:
            if self._driver:
                await self._driver.close()
        except Exception as e:
            logger.warning(f"Driver cleanup error: {e}")
        try:
            await self.pool.close_all()
        except Exception as e:
            logger.warning(f"Pool cleanup error: {e}")

    def shutdown(self):
        self._shutdown_event.set()

    @property
    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "health": self.health.get_snapshot().__dict__,
            "queue": self.queue.get_stats(),
            "pool": self.pool.get_stats(),
            "rate_limiter": self.rate_limiter.get_status(),
        }

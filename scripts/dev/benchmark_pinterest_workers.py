"""Exercise the production queue worker with isolated SQLite and simulated Pinterest I/O.

This measures scheduler scaling, not live Pinterest throughput. It never opens a
browser, instantiates production queue/rate/health singletons, or publishes a pin.
The real queue transactions, worker account locks, session acquire/release, image
cleanup, and verified-result persistence remain in the execution path.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from collections import Counter
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


async def run_scenario(
    root: Path,
    *,
    workers: int,
    accounts: tuple[str, ...] = ("benchmark_a", "benchmark_b", "benchmark_c"),
    jobs_per_account: int = 10,
    io_seconds: float = 0.15,
    pause_seconds: float = 0.01,
    layout: str = "interleaved",
    max_sessions: int | None = None,
    blocked_accounts: tuple[str, ...] = (),
    circuit_blocked_accounts: tuple[str, ...] = (),
    require_first_wave: bool = False,
) -> dict:
    """Run actual ``_queue_worker`` tasks against one disposable remaster queue.

    ``require_first_wave`` is a synchronization assertion for unit tests: first
    uploads wait until the expected number of independent accounts has entered
    the driver. This proves overlap without relying on wall-clock speed ratios.
    Production's fixed two-second inter-job pause is compressed and explicitly
    reported; all SQLite I/O and transaction scheduling run in real time.
    """
    import pinterest_automation.job_queue as queue_module
    import pinterest_automation.supervisor as supervisor_module
    from pinterest_automation.job_queue import Job, JobQueue
    from pinterest_automation.session_pool import SessionInfo, SessionPool

    root.mkdir(parents=True, exist_ok=True)
    max_sessions = max_sessions if max_sessions is not None else len(accounts)
    configured = SimpleNamespace(
        accounts={handle: object() for handle in accounts},
        default_board="Aperitivos",
        browser=SimpleNamespace(max_sessions=max_sessions, session_ttl_minutes=60),
    )
    with patch("pinterest_automation.session_pool.get_config", return_value=configured):
        pool = SessionPool(pause_reader=lambda: set())

    active = Counter()
    peaks = Counter()
    peak_global = 0
    peak_sessions = 0
    session_creations = Counter()
    starts: list[tuple[str, int]] = []
    completions: dict[str, dict] = {}
    releases: dict[str, float] = {}
    leases: list[dict] = []
    first_wave = asyncio.Event()
    drained = asyncio.Event()
    unavailable_accounts = set(blocked_accounts) | set(circuit_blocked_accounts)
    expected_completed = jobs_per_account * (len(accounts) - len(unavailable_accounts))
    expected_releases = jobs_per_account * len(blocked_accounts) + len(
        set(circuit_blocked_accounts) - set(blocked_accounts)
    )
    target_concurrency = min(workers, max_sessions, len(accounts) - len(unavailable_accounts))

    class SimulatedContext:
        def __init__(self) -> None:
            self.pages = [object()]

        async def close(self) -> None:
            return None

    async def create_session(account_handle: str | None = None) -> SessionInfo:
        nonlocal peak_sessions
        info = SessionInfo(
            context=SimulatedContext(),
            page=SimpleNamespace(is_closed=lambda: False),
            playwright=None,
            session_id=account_handle,
            account_handle=account_handle,
            browser_type="chromium",
        )
        pool._sessions[account_handle] = info
        session_creations[account_handle] += 1
        peak_sessions = max(peak_sessions, len(pool._sessions))
        return info

    pool._create_session = create_session

    class SimulatedLimiter:
        def can_execute(self, operation: str) -> bool:
            return operation.rsplit(":", 1)[-1] not in blocked_accounts

        def retry_after_seconds(self, _operation: str) -> float:
            return 300.0

        async def wait_async(self, _operation: str) -> None:
            # Budget eligibility is simulated; tests cover the production
            # worker's deferral behavior, not real rate-limit accounting.
            return None

    class SimulatedDriver:
        def __init__(self) -> None:
            self.session = None
            self.handle = None

        async def ensure_logged_in(self, account_handle: str | None = None) -> bool:
            nonlocal peak_global
            if account_handle in circuit_blocked_accounts:
                from pinterest_automation.circuit_breaker import CircuitBreakerOpenError

                raise CircuitBreakerOpenError(f"Isolated login circuit open for {account_handle}")
            self.session = await pool.acquire(account_handle)
            self.handle = account_handle
            active[account_handle] += 1
            peaks[account_handle] = max(peaks[account_handle], active[account_handle])
            peak_global = max(peak_global, sum(active.values()))
            if sum(active.values()) >= target_concurrency:
                first_wave.set()
            await asyncio.sleep(io_seconds * 0.2)
            return True

        async def create_pin(self, **kwargs) -> dict:
            ordinal = int(Path(kwargs["image_path"]).stem.rsplit("_", 1)[-1])
            starts.append((self.handle, ordinal))
            if require_first_wave:
                await first_wave.wait()
            # Upload/editor latency, then independently delayed confirmation.
            await asyncio.sleep(io_seconds * 0.55)
            await asyncio.sleep(io_seconds * 0.25)
            pin_id = str(1_000_000_000_000_000 + accounts.index(self.handle) * 1_000 + ordinal)
            return {
                "success": True,
                "pin_id": pin_id,
                "pin_url": f"https://www.pinterest.com/pin/{pin_id}/",
                "simulated": True,
            }

        async def close(self, healthy: bool = True) -> None:
            if self.session is not None:
                await pool.release(self.session, healthy=healthy)
                active[self.handle] -= 1
                self.session = None
                self.handle = None

    async def worker_sleep(seconds: float) -> None:
        await asyncio.sleep(pause_seconds if seconds == 2 else seconds)

    worker_asyncio = SimpleNamespace(
        **{name: getattr(asyncio, name) for name in dir(asyncio) if not name.startswith("__")}
    )
    worker_asyncio.sleep = worker_sleep

    # Missing legacy files are explicitly redirected: a temporary queue DB
    # alone would still import and rename the production legacy JSON files.
    with ExitStack() as patches:
        patches.enter_context(patch.dict(os.environ, {"PINTEREST_DEFAULT_ACCOUNT_HANDLE": accounts[0]}))
        patches.enter_context(patch.object(queue_module, "get_config", return_value=configured))
        for name in ("QUEUE_FILE", "DLQ_FILE", "COMPLETED_FILE"):
            patches.enter_context(patch.object(queue_module, name, root / f"{name}.absent.json"))
        patches.enter_context(patch.object(supervisor_module, "get_config", return_value=configured))
        patches.enter_context(patch.object(supervisor_module, "paused_accounts", return_value=set()))
        patches.enter_context(patch.object(supervisor_module, "PinterestDriver", SimulatedDriver))
        patches.enter_context(
            patch.object(supervisor_module, "get_rate_limiter", return_value=SimulatedLimiter())
        )
        patches.enter_context(patch.object(supervisor_module, "asyncio", worker_asyncio))
        # Cross-save routing is irrelevant to draining the fixed upload batch.
        patches.enter_context(patch.object(supervisor_module, "cross_save_targets", return_value=[]))
        queue = JobQueue(db_file=root / "jobs.db")
        all_jobs: dict[str, str] = {}
        if layout == "grouped":
            order = [(handle, ordinal) for handle in accounts for ordinal in range(jobs_per_account)]
        elif layout == "interleaved":
            order = [(handle, ordinal) for ordinal in range(jobs_per_account) for handle in accounts]
        else:
            raise ValueError(f"Unsupported queue layout: {layout}")

        created_at = time.time()
        for index, (handle, ordinal) in enumerate(order):
            image = root / f"{handle}_{ordinal}.jpg"
            image.write_bytes(b"isolated simulated remaster image")
            job = Job(
                id=f"{handle}_{ordinal}",
                created_at=created_at + index * 0.001,
                payload={
                    "image_path": str(image),
                    "title": f"Remastered recipe pin {ordinal}",
                    "description": "Isolated worker scheduler benchmark",
                    "link": f"https://example.invalid/recipe-{ordinal}",
                    "alt_text": "Imagen de receta de prueba",
                    "board_name": "Aperitivos",
                    "account_handle": handle,
                    "domain_handle": "benchmark_domain",
                    "extra": {
                        "account_handle": handle,
                        "domain_handle": "benchmark_domain",
                        "remaster_run_id": "isolated-worker-benchmark",
                        "variant": "recipe_card" if ordinal % 2 else "viral_visual",
                    },
                },
            )
            assert queue.enqueue(job) == job.id, "Unique benchmark jobs must not deduplicate"
            all_jobs[job.id] = handle

        complete_async = queue.complete_async
        release_async = queue.release_async
        dequeue_async = queue.dequeue_async

        async def tracked_dequeue(*args, **kwargs) -> Job | None:
            job = await dequeue_async(*args, **kwargs)
            if job is not None:
                leases.append(
                    {
                        "job_id": job.id,
                        "account_handle": all_jobs[job.id],
                        "started_at": job.started_at,
                        "active_processing_since": kwargs.get("active_processing_since"),
                    }
                )
            return job

        def check_drained() -> None:
            if len(completions) == expected_completed and len(releases) == expected_releases:
                drained.set()

        async def tracked_complete(job_id: str, result: dict) -> None:
            await complete_async(job_id, result)
            completions[job_id] = result
            check_drained()

        async def tracked_release(job_id: str, delay_seconds: float = 15.0) -> None:
            await release_async(job_id, delay_seconds=delay_seconds)
            releases[job_id] = delay_seconds
            check_drained()

        queue.complete_async = tracked_complete
        queue.release_async = tracked_release
        queue.dequeue_async = tracked_dequeue
        supervisor = object.__new__(supervisor_module.AutonomousSupervisor)
        supervisor.config = SimpleNamespace(worker_count=workers, watch_interval_seconds=0.005)
        supervisor.queue = queue
        supervisor.health = SimpleNamespace(get_snapshot=lambda: SimpleNamespace(checks={}))
        supervisor._shutdown_event = asyncio.Event()
        supervisor._session_generation = 0
        supervisor._account_locks = {}
        supervisor._lease = SimpleNamespace(started_at=time.time())
        supervisor._log_success = lambda *_args: None

        started = time.perf_counter()
        tasks = [asyncio.create_task(supervisor._queue_worker(worker)) for worker in range(workers)]
        try:
            await asyncio.wait_for(drained.wait(), timeout=max(30.0, len(order) * io_seconds * 3))
            elapsed = time.perf_counter() - started
        except TimeoutError as exc:
            details = {
                "active_accounts": dict(active),
                "upload_starts": starts,
                "completed_jobs": list(completions),
                "deferred_jobs": list(releases),
                "leases": leases,
            }
            raise RuntimeError(f"Isolated worker benchmark did not drain: {json.dumps(details)}") from exc
        finally:
            supervisor._shutdown_event.set()
            # Finish SQLite connection setup/close before removing Windows temp
            # files. Cancelling aiosqlite during connect can leave its thread's
            # just-opened DB handle alive beyond task cancellation.
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=5.0)
            except TimeoutError:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            await pool.close_all()

        outcomes = {job_id: queue.get_job_outcome(job_id) for job_id in all_jobs}
        pending = queue.list_pending()
        account_completed = Counter(all_jobs[job_id] for job_id in completions)
        fifo_by_account = {
            handle: [ordinal for seen_handle, ordinal in starts if seen_handle == handle]
            for handle in accounts
        }
        return {
            "workers": workers,
            "accounts": list(accounts),
            "max_sessions": max_sessions,
            "queue_layout": layout,
            "jobs_enqueued": len(order),
            "completed_verified": sum(
                outcome["state"] == "completed" and supervisor.is_verified_upload(outcome["result"])
                for outcome in outcomes.values()
            ),
            "elapsed_seconds": round(elapsed, 4),
            "pins_per_second": round(len(completions) / elapsed, 3),
            "peak_global_concurrency": peak_global,
            "peak_account_concurrency": dict(peaks),
            "peak_browser_sessions": peak_sessions,
            "session_creations": dict(session_creations),
            "completed_by_account": dict(account_completed),
            "start_order": [handle for handle, _ordinal in starts],
            "leases": leases,
            "fifo_by_account": fifo_by_account,
            "deferred_jobs": [
                {
                    "id": job.id,
                    "account_handle": all_jobs[job.id],
                    "status": job.status,
                    "attempt": job.attempt,
                    "next_retry_at": job.next_retry_at,
                    "image_preserved": Path(job.payload["image_path"]).exists(),
                }
                for job in pending
            ],
            "dlq_size": queue.get_stats()["dlq_size"],
            "account_cooldowns": getattr(supervisor, "_account_cooldowns", {}),
            "active_sessions_after_shutdown": len(pool._sessions),
            "active_uploads_after_shutdown": sum(active.values()),
        }


async def benchmark(args: argparse.Namespace) -> dict:
    scenarios = []
    with TemporaryDirectory(prefix="rankstein-worker-benchmark-") as directory:
        root = Path(directory)
        for layout in ("interleaved", "grouped"):
            for workers in args.workers:
                scenario = await run_scenario(
                    root / f"{layout}-{workers}",
                    workers=workers,
                    jobs_per_account=args.jobs_per_account,
                    io_seconds=args.io_seconds,
                    layout=layout,
                )
                scenarios.append(scenario)
                print(
                    f"{layout:11} workers={workers:2} "
                    f"elapsed={scenario['elapsed_seconds']:.3f}s "
                    f"throughput={scenario['pins_per_second']:.2f}/s "
                    f"peak={scenario['peak_global_concurrency']} "
                    f"verified={scenario['completed_verified']}/{scenario['jobs_enqueued']}",
                    flush=True,
                )
        deferred = await run_scenario(
            root / "deferred",
            workers=10,
            jobs_per_account=2,
            io_seconds=args.io_seconds,
            blocked_accounts=("benchmark_c",),
        )
    for layout in ("interleaved", "grouped"):
        matching = [scenario for scenario in scenarios if scenario["queue_layout"] == layout]
        baseline = next((scenario for scenario in matching if scenario["workers"] == 1), None)
        if baseline:
            for scenario in matching:
                scenario["speedup_vs_one_worker"] = round(
                    baseline["elapsed_seconds"] / scenario["elapsed_seconds"], 3
                )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "isolated_simulated_pinterest_io",
        "measured_path": "AutonomousSupervisor._queue_worker / JobQueue SQLite / SessionPool",
        "limitations": [
            "No real Pinterest requests, browsers, account authentication or uploads.",
            "No claim about measured live Pinterest throughput or safe posting limits.",
            "Simulated login/upload/confirmation I/O replaces the driver.",
            "Production inter-job pause is compressed from 2s to 0.01s.",
            "Rate budget eligibility is simulated; blocked jobs retain real SQLite retry timestamps.",
            "Browser launches are simulated without launch latency; this does not test launch-capacity races.",
            "Worker tasks are instantiated directly; production startup/configuration caps have separate tests.",
        ],
        "simulated_io_seconds_per_pin": args.io_seconds,
        "scenarios": scenarios,
        "rate_deferral_scenario": deferred,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", nargs="+", type=int, default=[1, 2, 3, 6, 10])
    parser.add_argument("--jobs-per-account", type=int, default=10)
    parser.add_argument("--io-seconds", type=float, default=0.15)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if any(workers < 1 for workers in args.workers) or args.jobs_per_account < 1 or args.io_seconds <= 0:
        parser.error("Workers, jobs per account and I/O seconds must be positive")
    logging.basicConfig(level=logging.ERROR)
    report = asyncio.run(benchmark(args))
    output = args.output or (
        PROJECT_ROOT
        / "data/reports/pinterest_scaling"
        / f"workers_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Report: {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

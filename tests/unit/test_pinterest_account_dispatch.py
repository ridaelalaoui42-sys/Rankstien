"""Account reservations are atomic even before workers acquire their Python locks."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from pinterest_automation.job_queue import Job, JobQueue

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _job(account: str, number: int, *, nested: bool = False) -> Job:
    payload = {"image_path": f"{account}-{number}.jpg", "title": f"{account}-{number}"}
    if nested:
        payload["extra"] = {"account_handle": account}
    else:
        payload["account_handle"] = account
    return Job(payload=payload)


async def test_parallel_dequeues_reserve_distinct_accounts_with_stale_lock_snapshots(tmp_path: Path):
    queue = JobQueue(db_file=tmp_path / "jobs.db")
    for account in ("a", "b", "c"):
        for number in range(3):
            queue.enqueue(_job(account, number))

    jobs = await asyncio.gather(*(queue.dequeue_async(locked_keys=set()) for _ in range(3)))

    assert all(job is not None for job in jobs)
    assert {job.payload["account_handle"] for job in jobs} == {"a", "b", "c"}
    assert await queue.dequeue_async(locked_keys=set()) is None
    await queue.complete_async(jobs[0].id, {"success": True, "pin_id": "1234567890123456"})
    next_job = await queue.dequeue_async(locked_keys=set())
    assert next_job.payload["account_handle"] == jobs[0].payload["account_handle"]


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_nested_accounts_and_default_identity_are_excluded_consistently(tmp_path, asynchronous):
    queue = JobQueue(db_file=tmp_path / "jobs.db")
    queue.enqueue(Job(payload={"title": "default account"}))
    queue.enqueue(_job("rida", 1, nested=True))
    allowed = _job("media", 1, nested=True)
    queue.enqueue(allowed)

    if asynchronous:
        leased = await queue.dequeue_async(locked_keys={"rida"}, default_account="rida")
    else:
        leased = queue.dequeue(locked_keys={"rida"}, default_account="rida")

    assert leased.id == allowed.id
    assert leased.payload["extra"]["account_handle"] == "media"


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_new_supervisor_preserves_prior_leases_without_blocking_new_account_work(
    tmp_path, asynchronous
):
    queue = JobQueue(db_file=tmp_path / "jobs.db")
    abandoned = _job("media", 1)
    queue.enqueue(abandoned)
    old_lease = queue.dequeue(locked_keys=set())
    owner_started = time.time()
    fresh = _job("media", 2)
    queue.enqueue(fresh)
    assert queue.dequeue(locked_keys=set()) is None

    if asynchronous:
        leased = await queue.dequeue_async(locked_keys=set(), active_processing_since=owner_started)
    else:
        leased = queue.dequeue(locked_keys=set(), active_processing_since=owner_started)

    assert leased.id == fresh.id
    outcome = queue.get_job_outcome(old_lease.id)
    assert outcome["state"] == "processing"
    assert outcome["result"] is None


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_owner_cutoff_reserves_new_leases_when_wall_clock_is_earlier(
    tmp_path, monkeypatch, asynchronous
):
    import pinterest_automation.job_queue as queue_module

    queue = JobQueue(db_file=tmp_path / "jobs.db")
    owner_started = 100.5
    observed_now = owner_started - 0.000001
    monkeypatch.setattr(queue_module, "time", SimpleNamespace(time=lambda: observed_now))
    delayed = _job("c", 0)
    delayed.priority = 1
    delayed.next_retry_at = owner_started
    queue.enqueue(delayed)
    first, same_account, other_account = _job("a", 0), _job("a", 1), _job("b", 0)
    for index, job in enumerate((first, same_account, other_account)):
        job.created_at = float(index)
        queue.enqueue(job)

    async def lease():
        options = {"locked_keys": set(), "active_processing_since": owner_started}
        return await queue.dequeue_async(**options) if asynchronous else queue.dequeue(**options)

    first_lease = await lease()
    second_lease = await lease()

    assert first_lease.id == first.id
    assert first_lease.started_at == owner_started
    assert second_lease.id == other_account.id
    assert second_lease.started_at == owner_started
    assert await lease() is None
    assert queue.get_job_outcome(same_account.id)["state"] == "pending"
    # Flooring ownership stamps must not make a future retry eligible early.
    assert queue.get_job_outcome(delayed.id)["state"] == "pending"


async def test_prioritization_preserves_deferred_job_and_retry_metadata(tmp_path):
    queue = JobQueue(db_file=tmp_path / "jobs.db")
    delayed = _job("media", 1)
    delayed.status = "retry"
    delayed.attempt = 2
    delayed.next_retry_at = time.time() + 3600
    delayed.priority = 5
    queue.enqueue(delayed)

    changes = queue.prioritize_jobs([delayed.id], priority=1)

    assert changes["jobs"][0]["next_retry_at"] == delayed.next_retry_at
    assert changes["jobs"][0]["attempt"] == 2
    assert queue.dequeue() is None
    pending = queue.list_pending()[0]
    assert pending.priority == 1
    assert pending.attempt == 2
    assert pending.next_retry_at == delayed.next_retry_at


async def test_prioritization_is_atomic_when_any_requested_job_is_leased(tmp_path):
    queue = JobQueue(db_file=tmp_path / "jobs.db")
    first, second = _job("media", 1), _job("rida", 1)
    queue.enqueue(first)
    queue.enqueue(second)
    leased = queue.dequeue()
    with pytest.raises(ValueError, match="leased"):
        queue.prioritize_jobs([second.id, leased.id], priority=1)
    assert queue.get_job_outcome(second.id)["priority"] == second.priority

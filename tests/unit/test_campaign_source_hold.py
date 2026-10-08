from __future__ import annotations

import pytest

from pinterest_automation.job_queue import Job, JobQueue


def _job(job_id: str, *, run_id: str = "review-run", status: str = "pending") -> Job:
    return Job(
        id=job_id,
        status=status,
        payload={"extra": {"pipeline_run_id": run_id, "campaign_type": "article_remaster_pairs"}},
    )


def test_exact_campaign_hold_preserves_payload_and_blocks_dequeue(tmp_path):
    queue = JobQueue(db_file=tmp_path / "jobs.db")
    queue.enqueue(_job("one"))
    queue.enqueue(_job("two"))
    before = queue.get_job_outcome("one")["payload"]
    result = queue.hold_campaign_jobs(
        ["one", "two"], pipeline_run_id="review-run", reason="Embedded instructions"
    )
    assert result["held"] == 2
    assert queue.get_job_outcome("one")["state"] == "held"
    assert queue.get_job_outcome("one")["payload"] == before
    assert queue.get_stats()["by_status"] == {"held": 2}
    assert queue.dequeue() is None
    queue.release("one", delay_seconds=0)
    queue.retry_or_fail("one", error="Late worker callback")
    queue.complete("one", result={"pin_id": "123"})
    assert queue.get_job_outcome("one")["state"] == "held"
    queue.hold_campaign_jobs(["one", "two"], pipeline_run_id="review-run", reason="Repeated review")
    assert len(queue.get_job_outcome("one")["errors"]) == 1


@pytest.mark.asyncio
async def test_async_worker_callbacks_cannot_release_quality_holds(tmp_path):
    queue = JobQueue(db_file=tmp_path / "jobs.db")
    queue.enqueue(_job("one"))
    queue.hold_campaign_jobs(["one"], pipeline_run_id="review-run", reason="Bad source")
    await queue.release_async("one", delay_seconds=0)
    await queue.retry_or_fail_async("one", error="Late worker callback")
    await queue.complete_async("one", result={"pin_id": "123"})
    outcome = queue.get_job_outcome("one")
    assert outcome["state"] == "held"
    assert len(outcome["errors"]) == 1
    assert await queue.dequeue_async() is None


@pytest.mark.parametrize("bad_state", ["processing", "completed", "dead", "failed"])
def test_hold_never_overwrites_leased_or_terminal_jobs(tmp_path, bad_state):
    queue = JobQueue(db_file=tmp_path / "jobs.db")
    queue.enqueue(_job("one"))
    queue.enqueue(_job("two", status=bad_state))
    with pytest.raises(ValueError, match="leased or terminal"):
        queue.hold_campaign_jobs(["one", "two"], pipeline_run_id="review-run", reason="Bad source")
    assert queue.get_job_outcome("one")["state"] == "pending"
    assert queue.get_job_outcome("two")["state"] == bad_state


def test_hold_rolls_back_on_mismatched_run(tmp_path):
    queue = JobQueue(db_file=tmp_path / "jobs.db")
    queue.enqueue(_job("one"))
    queue.enqueue(_job("other", run_id="another-run"))
    with pytest.raises(ValueError, match="does not belong"):
        queue.hold_campaign_jobs(["one", "other"], pipeline_run_id="review-run", reason="Bad source")
    assert queue.get_job_outcome("one")["state"] == "pending"
    assert queue.get_job_outcome("other")["state"] == "pending"

"""Tests for the SQLite-backed JobQueue.

Coverage targets:
  - Public API parity (enqueue, enqueue_pin_upload, dequeue, complete,
    retry_or_fail, get_stats, list_pending, purge_completed).
  - Atomic dequeue: two consecutive dequeues never return the same job.
  - Persistence: writing in one JobQueue instance is visible from a fresh
    instance pointing at the same DB.
  - Retry/DLQ: a job exhausting attempts ends up in dlq, not jobs.
  - Priority ordering: lower priority value wins.
  - Backoff: next_retry_at is set in the future on retry.
  - Legacy-JSON migration: a pre-existing pending_jobs.json is imported and
    renamed to .migrated.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pinterest_automation.job_queue import (
    Job,
    JobQueue,
    JobStatus,
)


@pytest.fixture
def queue(tmp_path: Path) -> JobQueue:
    db = tmp_path / "jobs.db"
    return JobQueue(db_file=db)


@pytest.mark.unit
class TestEnqueueDequeue:
    def test_enqueue_returns_job_id(self, queue: JobQueue) -> None:
        job_id = queue.enqueue(Job(payload={"x": 1}))
        assert isinstance(job_id, str) and len(job_id) > 0

    def test_dequeue_empty_returns_none(self, queue: JobQueue) -> None:
        assert queue.dequeue() is None

    def test_dequeue_returns_enqueued_job(self, queue: JobQueue) -> None:
        queue.enqueue(Job(id="abc12345", payload={"k": "v"}))
        job = queue.dequeue()
        assert job is not None
        assert job.id == "abc12345"
        assert job.status == JobStatus.PROCESSING.value
        assert job.attempt == 1
        assert job.started_at is not None

    def test_dequeue_is_atomic_no_duplicate_lease(self, queue: JobQueue) -> None:
        queue.enqueue(Job(id="only-one"))
        first = queue.dequeue()
        second = queue.dequeue()
        assert first is not None and first.id == "only-one"
        # Second dequeue must not return the same job; queue is empty of ready jobs.
        assert second is None

    def test_priority_ordering_lower_value_first(self, queue: JobQueue) -> None:
        # priority=1 should outrank priority=5 even when enqueued later.
        queue.enqueue(Job(id="low-pri", priority=5, created_at=1.0))
        queue.enqueue(Job(id="high-pri", priority=1, created_at=2.0))
        first = queue.dequeue()
        assert first is not None and first.id == "high-pri"

    def test_age_breaks_priority_tie(self, queue: JobQueue) -> None:
        queue.enqueue(Job(id="newer", priority=5, created_at=2.0))
        queue.enqueue(Job(id="older", priority=5, created_at=1.0))
        first = queue.dequeue()
        assert first is not None and first.id == "older"


@pytest.mark.unit
class TestEnqueuePinUpload:
    def test_payload_shape(self, queue: JobQueue) -> None:
        job_id = queue.enqueue_pin_upload(
            image_path="/tmp/x.png",
            title="t",
            description="d",
            link="https://example.invalid/r",
            alt_text="alt",
            board_name="my-board",
            priority=2,
            extra={"slug": "test-slug"},
        )
        pending = queue.list_pending()
        assert len(pending) == 1
        j = pending[0]
        assert j.id == job_id
        assert j.type == "pin_upload"
        assert j.priority == 2
        assert j.payload["board_name"] == "my-board"
        assert j.payload["extra"]["slug"] == "test-slug"

    def test_account_handle_is_hoisted_from_extra(self, queue: JobQueue) -> None:
        queue.enqueue_pin_upload(
            image_path="/tmp/x.png",
            title="t",
            description="d",
            link="https://example.invalid/r",
            extra={"account_handle": "r1"},
        )

        pending = queue.list_pending()
        assert pending[0].payload["account_handle"] == "r1"
        assert pending[0].payload["extra"]["account_handle"] == "r1"


@pytest.mark.unit
class TestCompleteAndDLQ:
    def test_complete_removes_from_jobs_and_appends_to_log(self, queue: JobQueue) -> None:
        queue.enqueue(Job(id="done"))
        queue.dequeue()
        queue.complete("done", {"ok": True})
        assert queue.list_pending() == []
        # completed_log row exists
        with queue._conn() as conn:
            row = conn.execute("SELECT * FROM completed_log WHERE id = ?", ("done",)).fetchone()
        assert row is not None
        body = json.loads(row["job_json"])
        assert body["result"] == {"ok": True}
        assert body["status"] == JobStatus.COMPLETED.value

    def test_retry_or_fail_schedules_backoff(self, queue: JobQueue) -> None:
        queue.enqueue(Job(id="retryable", max_attempts=3))
        queue.dequeue()  # attempt -> 1
        queue.retry_or_fail("retryable", "transient")

        pending = queue.list_pending()
        assert len(pending) == 1
        j = pending[0]
        assert j.status == JobStatus.RETRY.value
        assert j.next_retry_at is not None
        assert j.next_retry_at > datetime.now(UTC).timestamp()
        assert j.error_log == ["Attempt 1: transient"]

    def test_exhausted_job_lands_in_dlq(self, queue: JobQueue) -> None:
        queue.enqueue(Job(id="doomed", max_attempts=2))
        queue.dequeue()
        queue.retry_or_fail("doomed", "first")
        # Move it back to ready by clearing next_retry_at directly
        with queue._conn() as conn:
            conn.execute("UPDATE jobs SET next_retry_at = 0 WHERE id = 'doomed'")
        queue.dequeue()  # attempt -> 2
        queue.retry_or_fail("doomed", "second")

        # Job table should no longer contain it
        assert queue.list_pending() == []
        with queue._conn() as conn:
            jobs_row = conn.execute("SELECT * FROM jobs WHERE id = ?", ("doomed",)).fetchone()
            dlq_row = conn.execute("SELECT * FROM dlq WHERE id = ?", ("doomed",)).fetchone()
        assert jobs_row is None
        assert dlq_row is not None


@pytest.mark.unit
class TestStats:
    def test_get_stats_counts_by_status(self, queue: JobQueue) -> None:
        queue.enqueue(Job(id="a"))
        queue.enqueue(Job(id="b"))
        queue.enqueue(Job(id="c"))
        queue.dequeue()  # one moves to processing

        stats = queue.get_stats()
        assert stats["total"] == 3
        assert stats["by_status"][JobStatus.PROCESSING.value] == 1
        assert stats["by_status"][JobStatus.PENDING.value] == 2
        assert stats["dlq_size"] == 0


@pytest.mark.unit
class TestLeaseRecovery:
    def test_stale_processing_jobs_are_requeued(self, queue: JobQueue) -> None:
        queue.enqueue(Job(id="stale"))
        leased = queue.dequeue()
        assert leased is not None

        with queue._conn() as conn:
            conn.execute(
                "UPDATE jobs SET started_at = ? WHERE id = ?",
                (datetime.now(UTC).timestamp() - 7200, "stale"),
            )

        recovered = queue.requeue_stale_processing(max_age_seconds=60)

        assert recovered == 1
        pending = queue.list_pending()
        assert len(pending) == 1
        assert pending[0].id == "stale"
        assert pending[0].status == JobStatus.RETRY.value
        assert "Recovered abandoned processing lease" in pending[0].error_log


@pytest.mark.unit
class TestPersistenceAcrossInstances:
    def test_jobs_visible_from_new_instance(self, tmp_path: Path) -> None:
        db = tmp_path / "jobs.db"
        q1 = JobQueue(db_file=db)
        q1.enqueue(Job(id="persistent", payload={"hello": "world"}))

        q2 = JobQueue(db_file=db)
        pending = q2.list_pending()
        assert len(pending) == 1
        assert pending[0].id == "persistent"
        assert pending[0].payload == {"hello": "world"}


@pytest.mark.unit
class TestLegacyMigration:
    def test_pending_jobs_json_is_imported_and_renamed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Point all legacy paths and DB into tmp_path
        from pinterest_automation import job_queue as jq

        legacy_pending = tmp_path / "pending_jobs.json"
        legacy_pending.write_text(
            json.dumps(
                {
                    "jobs": [
                        {
                            "id": "legacy1",
                            "type": "pin_upload",
                            "payload": {"image_path": "x.png"},
                            "status": "pending",
                            "created_at": 1.0,
                            "attempt": 0,
                            "max_attempts": 3,
                            "error_log": [],
                            "priority": 5,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(jq, "QUEUE_FILE", legacy_pending)
        # DLQ + completed don't exist — that's fine, importer is path-aware
        monkeypatch.setattr(jq, "DLQ_FILE", tmp_path / "dead_letter.json")
        monkeypatch.setattr(jq, "COMPLETED_FILE", tmp_path / "completed_jobs.json")

        q = JobQueue(db_file=tmp_path / "jobs.db")

        # Original file should be renamed
        assert not legacy_pending.exists()
        assert (tmp_path / "pending_jobs.json.migrated").exists()

        # Job is queryable
        pending = q.list_pending()
        assert len(pending) == 1
        assert pending[0].id == "legacy1"

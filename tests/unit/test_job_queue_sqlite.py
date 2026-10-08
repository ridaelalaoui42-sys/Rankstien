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

    def test_locked_account_skips_every_board_for_that_account(self, queue: JobQueue) -> None:
        queue.enqueue(
            Job(
                id="rida-a",
                payload={"account_handle": "rida", "board_name": "Aperitivos"},
            )
        )
        queue.enqueue(
            Job(
                id="rida-b",
                payload={"account_handle": "rida", "board_name": "Chocolate"},
            )
        )
        queue.enqueue(
            Job(
                id="media-a",
                payload={"account_handle": "media", "board_name": "Aperitivos"},
            )
        )

        leased = queue.dequeue(locked_keys={"rida"})

        assert leased is not None
        assert leased.id == "media-a"


@pytest.mark.unit
class TestEnqueuePinUpload:
    def test_payload_shape(self, queue: JobQueue) -> None:
        job_id = queue.enqueue_pin_upload(
            image_path="/tmp/x.png",
            title="t",
            description="d",
            link="https://example.invalid/r",
            alt_text="alt",
            board_name="Postres y Dulces",
            priority=2,
            extra={"slug": "test-slug"},
        )
        pending = queue.list_pending()
        assert len(pending) == 1
        j = pending[0]
        assert j.id == job_id
        assert j.type == "pin_upload"
        assert j.priority == 2
        assert j.payload["board_name"] == "Chocolate"
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

    def test_domain_handle_is_hoisted_from_extra(self, queue: JobQueue) -> None:
        queue.enqueue_pin_upload(
            image_path="/tmp/x.png",
            title="t",
            description="d",
            link="https://example.invalid/r",
            extra={"account_handle": "r1", "domain_handle": "blog"},
        )

        pending = queue.list_pending()
        assert pending[0].payload["domain_handle"] == "blog"
        assert pending[0].payload["extra"]["domain_handle"] == "blog"

    def test_direct_pin_save_jobs_normalize_board_name(self, queue: JobQueue) -> None:
        queue.enqueue(
            Job(
                id="save-old-board",
                type="pin_save",
                payload={"pin_url": "https://www.pinterest.com/pin/123/", "board_name": "recetas"},
            )
        )

        pending = queue.list_pending()
        assert pending[0].payload["board_name"] == "Aperitivos"

    def test_storage_normalizer_updates_active_and_dlq_boards(self, queue: JobQueue) -> None:
        active = Job(id="active-old", payload={"board_name": "Postres y Dulces"})
        dead = Job(id="dead-old", payload={"board_name": "recetas"})

        with queue._conn() as conn:
            conn.execute(
                """
                INSERT INTO jobs
                (id, type, payload_json, status, created_at, started_at, completed_at,
                 attempt, max_attempts, next_retry_at, error_log_json, result_json, priority)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    active.id,
                    active.type,
                    json.dumps(active.payload),
                    active.status,
                    active.created_at,
                    active.started_at,
                    active.completed_at,
                    active.attempt,
                    active.max_attempts,
                    active.next_retry_at,
                    json.dumps(active.error_log),
                    None,
                    active.priority,
                ),
            )
            conn.execute(
                "INSERT INTO dlq (id, job_json, moved_at) VALUES (?, ?, ?)",
                (dead.id, json.dumps(dead.to_dict()), 1.0),
            )

        result = queue.normalize_board_names_in_storage()

        assert result == {"active_changed": 1, "dlq_changed": 1}
        with queue._conn() as conn:
            active_payload = json.loads(
                conn.execute("SELECT payload_json FROM jobs WHERE id = ?", (active.id,)).fetchone()[
                    "payload_json"
                ]
            )
            dead_job = json.loads(
                conn.execute("SELECT job_json FROM dlq WHERE id = ?", (dead.id,)).fetchone()["job_json"]
            )
        assert active_payload["board_name"] == "Chocolate"
        assert dead_job["payload"]["board_name"] == "Aperitivos"


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
        outcome = queue.get_job_outcome("done")
        assert outcome["state"] == JobStatus.COMPLETED.value
        assert outcome["result"] == {"ok": True}

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
        outcome = queue.get_job_outcome("doomed")
        assert outcome["state"] == JobStatus.DEAD.value
        assert outcome["errors"][-1] == "Attempt 2: second"

    def test_verified_dlq_job_can_be_reconciled_as_completed(self, queue: JobQueue) -> None:
        queue.enqueue(Job(id="verified-late", max_attempts=1))
        queue.dequeue()
        queue.retry_or_fail("verified-late", "confirmation timed out")

        result = {
            "success": True,
            "pin_id": "1148488342513342707",
            "pin_url": "https://www.pinterest.com/pin/1148488342513342707/",
            "method": "public-profile-verification",
        }
        assert queue.complete_from_dlq("verified-late", result) is True

        with queue._conn() as conn:
            dlq_row = conn.execute(
                "SELECT * FROM dlq WHERE id = ?",
                ("verified-late",),
            ).fetchone()
            completed_row = conn.execute(
                "SELECT job_json FROM completed_log WHERE id = ?",
                ("verified-late",),
            ).fetchone()
        assert dlq_row is None
        assert json.loads(completed_row["job_json"])["result"] == result

    def test_job_outcome_exposes_identity_for_active_completed_and_dlq(self, queue: JobQueue) -> None:
        jobs = {
            "active-proof": Job(
                id="active-proof",
                type="pin_upload",
                payload={"domain_handle": "recetagenial", "link": "https://example.test/a"},
                priority=1,
            ),
            "complete-proof": Job(
                id="complete-proof",
                type="pin_upload",
                payload={"domain_handle": "recetagenial", "link": "https://example.test/b"},
                priority=1,
            ),
            "dead-proof": Job(
                id="dead-proof",
                type="pin_upload",
                payload={"domain_handle": "recetagenial", "link": "https://example.test/c"},
                priority=1,
                max_attempts=1,
            ),
        }
        for job in jobs.values():
            queue.enqueue(job)

        assert queue.dequeue().id == "active-proof"
        queue.complete(
            "active-proof",
            {
                "success": True,
                "pin_id": "1148488342515527632",
                "pin_url": "https://www.pinterest.com/pin/1148488342515527632/",
            },
        )
        assert queue.dequeue().id == "complete-proof"
        queue.complete(
            "complete-proof",
            {
                "success": True,
                "pin_id": "1148488342515527633",
                "pin_url": "https://www.pinterest.com/pin/1148488342515527633/",
            },
        )
        assert queue.dequeue().id == "dead-proof"
        queue.retry_or_fail("dead-proof", "confirmation failed")

        outcomes = {
            job_id: queue.get_job_outcome(job_id)
            for job_id in ("active-proof", "complete-proof", "dead-proof")
        }
        for job_id, outcome in outcomes.items():
            assert outcome["type"] == "pin_upload"
            assert outcome["priority"] == 1
            assert outcome["payload"] == jobs[job_id].payload


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
class TestDLQRecovery:
    def test_uncertain_publish_and_abandoned_lease_are_transient(
        self,
        queue: JobQueue,
    ) -> None:
        errors = {
            "uncertain": "Pin creation could not be verified; no pin_id or pin_url found",
            "abandoned": "Recovered abandoned processing lease",
        }
        with queue._conn() as conn:
            for job_id, error in errors.items():
                job = Job(
                    id=job_id,
                    status=JobStatus.DEAD.value,
                    attempt=3,
                    error_log=[error],
                )
                conn.execute(
                    "INSERT INTO dlq (id, job_json, moved_at) VALUES (?, ?, ?)",
                    (
                        job_id,
                        json.dumps(job.to_dict()),
                        datetime.now(UTC).timestamp(),
                    ),
                )

        result = queue.requeue_transient_dlq()

        assert result["requeued"] == 2
        assert result["skipped"] == 0
        assert {job.id for job in queue.list_pending()} == set(errors)
        assert queue.get_stats()["dlq_size"] == 0


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

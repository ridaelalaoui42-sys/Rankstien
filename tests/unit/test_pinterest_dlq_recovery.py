"""Explicit DLQ recovery preserves identity/history and rejects uncertain uploads."""

from __future__ import annotations

import json
import os
import sqlite3
import time

import pytest

import pinterest_automation.job_queue as queue_module
from pinterest_automation.job_queue import Job, JobQueue

pytestmark = pytest.mark.unit
REASON = "Authorized recovery after the Pinterest DNS outage was resolved"


@pytest.fixture
def queue(tmp_path, monkeypatch):
    for name in ("QUEUE_FILE", "DLQ_FILE", "COMPLETED_FILE"):
        monkeypatch.setattr(queue_module, name, tmp_path / name)
    return JobQueue(db_file=tmp_path / "jobs.db")


def _dead(queue, job_id="dead-upload", **changes):
    image = queue._db_file.parent / f"{job_id}.jpg"
    image.write_bytes(b"retained image")
    job = Job(
        id=job_id,
        status="dead",
        payload={
            "image_path": str(image),
            "account_handle": "media",
            "domain_handle": "recetadolce",
            "board_name": "Chocolate",
            "title": job_id,
            "link": "https://recetadolce.com/recipe",
            "extra": {"domain_handle": "recetadolce", "idempotency_key": f"key-{job_id}"},
        },
        created_at=123.25,
        started_at=456.5,
        next_retry_at=time.time() + 3600,
        attempt=3,
        max_attempts=3,
        error_log=[f"Attempt {number}: Login failed" for number in (1, 2, 3)],
        priority=4,
    ).to_dict()
    job.update(changes)
    with queue._conn() as conn:
        conn.execute("INSERT INTO dlq VALUES (?, ?, ?)", (job_id, json.dumps(job), 789.5))
    return job


def _snapshot(queue):
    with queue._conn() as conn:
        return {
            table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id")]  # noqa: S608
            for table in ("jobs", "dlq", "completed_log", "completion_evidence")
        }


def test_dry_run_is_default_and_does_not_change_any_queue_table(queue):
    original = _dead(queue)
    before = _snapshot(queue)

    result = queue.restore_login_failure_jobs([original["id"]], reason=REASON)

    assert result["dry_run"] is True
    assert result["eligible"] == 1
    assert result["restored"] == 0
    assert result["details"][0]["max_attempts"] == 6
    assert result["details"][0]["previous_errors"] == 3
    assert _snapshot(queue) == before


def test_restore_preserves_exact_payload_history_identity_and_future_deadline(queue):
    original = _dead(queue)
    unaffected = _dead(queue, "unselected")

    result = queue.restore_login_failure_jobs([original["id"]], reason=REASON, dry_run=False)

    assert result["restored"] == 1
    with queue._conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (original["id"],)).fetchone()
        restored = queue_module._row_to_job(row).to_dict()
        untouched = json.loads(conn.execute("SELECT job_json FROM dlq").fetchone()[0])
    assert untouched == unaffected
    for name in ("id", "type", "payload", "created_at", "attempt", "next_retry_at", "priority", "result"):
        assert restored[name] == original[name]
    assert restored["status"] == "pending"
    assert restored["started_at"] is None
    assert restored["max_attempts"] == 6
    assert restored["error_log"][:-1] == original["error_log"]
    assert REASON in restored["error_log"][-1]
    assert '"additional_attempts": 3' in restored["error_log"][-1]
    assert queue.dequeue() is None  # A future deadline was not bypassed.
    assert (queue._db_file.parent / "dead-upload.jpg").read_bytes() == b"retained image"


@pytest.mark.parametrize("completed", [False, True])
def test_repeated_authorization_never_adds_budget_or_overwrites_progress(queue, completed):
    original = _dead(queue)
    queue.restore_login_failure_jobs([original["id"]], reason=REASON, dry_run=False)
    if completed:
        queue.complete(original["id"], {"success": True, "pin_id": "1234567890123456"})
    before = _snapshot(queue)

    result = queue.restore_login_failure_jobs([original["id"]], reason=REASON, dry_run=False)

    assert result["restored"] == 0
    assert result["already_restored"] == [original["id"]]
    assert _snapshot(queue) == before


def test_retrying_authorization_does_not_restore_a_second_dlq_failure_window(queue):
    original = _dead(queue, next_retry_at=None)
    queue.restore_login_failure_jobs([original["id"]], reason=REASON, dry_run=False)
    queue.fail(original["id"], "Publish result could not be verified")
    before = _snapshot(queue)

    with pytest.raises(ValueError, match="non-login or uncertain"):
        queue.restore_login_failure_jobs([original["id"]], reason=REASON, dry_run=False)

    assert _snapshot(queue) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"type": "pin_save"},
        {"status": "pending"},
        {"id": "different-id"},
        {"error_log": []},
        {"error_log": ["Attempt 1: Login failed", "Attempt 2: Publish result could not be verified"]},
        {"error_log": ["Attempt 3: board selection failed"]},
        {"error_log": ["Attempt 3: Login failed after publish"]},
        {"error_log": ["Recovered abandoned processing lease", "Attempt 3: Login failed"]},
        {"error_log": [None]},
        {"attempt": True},
        {"attempt": 4},
        {"max_attempts": 0},
        {"created_at": float("nan")},
        {"next_retry_at": float("inf")},
        {"completed_at": 123},
        {"result": {"success": False, "pin_id": "1234567890123456"}},
        {"payload": {}},
    ],
)
def test_invalid_record_rejects_whole_batch_before_any_mutation(queue, changes):
    first = _dead(queue, "valid-first")
    second = _dead(queue, "invalid-last", **changes)
    before = _snapshot(queue)

    with pytest.raises(ValueError):
        queue.restore_login_failure_jobs([first["id"], "invalid-last"], reason=REASON, dry_run=False)

    assert _snapshot(queue) == before
    assert second is not None


def test_missing_source_image_is_not_recovered(queue):
    original = _dead(queue)
    (queue._db_file.parent / "dead-upload.jpg").unlink()
    before = _snapshot(queue)

    with pytest.raises(ValueError, match="usable source image"):
        queue.restore_login_failure_jobs([original["id"]], reason=REASON, dry_run=False)

    assert _snapshot(queue) == before


@pytest.mark.parametrize("error", ["Login failed", "Fatal error: Login failed"])
def test_exact_legacy_login_failures_and_nested_accounts_remain_supported(queue, error):
    original = _dead(queue, error_log=[error])
    original["payload"]["extra"]["account_handle"] = original["payload"].pop("account_handle")
    original["payload"]["extra"]["idempotency_key"] = ""
    with queue._conn() as conn:
        conn.execute("UPDATE dlq SET job_json = ? WHERE id = ?", (json.dumps(original), original["id"]))

    result = queue.restore_login_failure_jobs([original["id"]], reason=REASON, dry_run=False)

    assert result["restored"] == 1
    assert queue.get_job_outcome(original["id"])["payload"] == original["payload"]


def test_corrupt_json_rejects_batch_and_retains_exact_original_rows(queue):
    original = _dead(queue)
    with queue._conn() as conn:
        conn.execute("INSERT INTO dlq VALUES (?, ?, ?)", ("invalid-json", "{", 999))
    before = _snapshot(queue)

    # SQLite's identity scan may encounter the corrupt row before its explicit
    # JSON validation; either failure must roll back the entire transaction.
    with pytest.raises((ValueError, sqlite3.OperationalError)):
        queue.restore_login_failure_jobs([original["id"], "invalid-json"], reason=REASON, dry_run=False)

    assert _snapshot(queue) == before


@pytest.mark.parametrize("table", ["jobs", "completed_log", "completion_evidence"])
def test_same_id_conflict_is_never_overwritten(queue, table):
    original = _dead(queue)
    with queue._conn() as conn:
        if table == "jobs":
            conn.execute(
                queue_module._INSERT_OR_REPLACE_JOB, queue_module._job_to_row(Job.from_dict(original))
            )
        elif table == "completed_log":
            conn.execute(
                "INSERT INTO completed_log VALUES (?, ?, ?)", (original["id"], json.dumps(original), 999)
            )
        else:
            conn.execute(
                "INSERT INTO completion_evidence VALUES (?, ?, ?, ?, ?)",
                (original["id"], json.dumps(original), 999, 999, "{}"),
            )
    before = _snapshot(queue)

    with pytest.raises(ValueError, match="conflicts with active or terminal"):
        queue.restore_login_failure_jobs([original["id"]], reason=REASON, dry_run=False)

    assert _snapshot(queue) == before


@pytest.mark.parametrize("table", ["jobs", "dlq", "completed_log", "completion_evidence"])
@pytest.mark.parametrize("identity", ["image", "idempotency"])
def test_other_id_with_same_image_or_idempotency_identity_blocks_restore(queue, table, identity):
    original = _dead(queue)
    other = Job.from_dict(original)
    other.id = "conflicting-job"
    if identity == "image":
        other.payload["extra"]["idempotency_key"] = "different-key"
    else:
        other.payload["image_path"] = "different-image.jpg"
    with queue._conn() as conn:
        if table == "jobs":
            conn.execute(queue_module._INSERT_OR_REPLACE_JOB, queue_module._job_to_row(other))
        elif table == "dlq":
            conn.execute("INSERT INTO dlq VALUES (?, ?, ?)", (other.id, json.dumps(other.to_dict()), 999))
        elif table == "completed_log":
            conn.execute(
                "INSERT INTO completed_log VALUES (?, ?, ?)", (other.id, json.dumps(other.to_dict()), 999)
            )
        else:
            conn.execute(
                "INSERT INTO completion_evidence VALUES (?, ?, ?, ?, ?)",
                (other.id, json.dumps(other.to_dict()), 999, 999, "{}"),
            )
    before = _snapshot(queue)

    with pytest.raises(ValueError, match="duplicates existing identity"):
        queue.restore_login_failure_jobs([original["id"]], reason=REASON, dry_run=False)

    assert _snapshot(queue) == before


def test_database_error_after_first_insert_rolls_back_entire_batch(queue):
    first = _dead(queue, "first")
    second = _dead(queue, "second")
    with queue._conn() as conn:
        conn.execute(
            "CREATE TRIGGER reject_second BEFORE INSERT ON jobs WHEN NEW.id = 'second' BEGIN SELECT RAISE(ABORT, 'test failure'); END"
        )
    before = _snapshot(queue)

    with pytest.raises(sqlite3.IntegrityError, match="test failure"):
        queue.restore_login_failure_jobs([first["id"], second["id"]], reason=REASON, dry_run=False)

    assert _snapshot(queue) == before


@pytest.mark.parametrize("difference", ["account", "board", "destination"])
@pytest.mark.parametrize("table", ["jobs", "dlq", "completed_log", "completion_evidence"])
def test_shared_image_with_distinct_upload_identity_does_not_block_recovery(queue, difference, table):
    original = _dead(queue)
    other = Job.from_dict(original)
    other.id = "shared-image-job"
    other.payload = json.loads(json.dumps(original["payload"]))
    other.payload["extra"]["idempotency_key"] = "other-key"
    if difference == "account":
        other.payload["account_handle"] = "rida"
    elif difference == "board":
        other.payload["board_name"] = "Aperitivos"
    else:
        other.payload["link"] = "https://recetadolce.com/another-recipe"
    with queue._conn() as conn:
        if table == "jobs":
            conn.execute(queue_module._INSERT_OR_REPLACE_JOB, queue_module._job_to_row(other))
        elif table == "dlq":
            conn.execute("INSERT INTO dlq VALUES (?, ?, ?)", (other.id, json.dumps(other.to_dict()), 999))
        elif table == "completed_log":
            conn.execute(
                "INSERT INTO completed_log VALUES (?, ?, ?)", (other.id, json.dumps(other.to_dict()), 999)
            )
        else:
            conn.execute(
                "INSERT INTO completion_evidence VALUES (?, ?, ?, ?, ?)",
                (other.id, json.dumps(other.to_dict()), 999, 999, "{}"),
            )
    before = _snapshot(queue)[table]

    result = queue.restore_login_failure_jobs([original["id"]], reason=REASON, dry_run=False)

    assert result["restored"] == 1
    if table != "jobs":
        expected = before if table != "dlq" else [row for row in before if row[0] != original["id"]]
        assert _snapshot(queue)[table] == expected
    with queue._conn() as conn:
        column = "payload_json" if table == "jobs" else "job_json"
        assert conn.execute(f"SELECT {column} FROM {table} WHERE id = ?", (other.id,)).fetchone() is not None  # noqa: S608


def test_same_image_with_absolute_and_relative_paths_is_still_a_conflict(queue):
    original = _dead(queue)
    other = Job.from_dict(original)
    other.id = "relative-path-job"
    other.payload["image_path"] = os.path.relpath(other.payload["image_path"])
    other.payload["extra"]["idempotency_key"] = "other-key"
    with queue._conn() as conn:
        conn.execute("INSERT INTO dlq VALUES (?, ?, ?)", (other.id, json.dumps(other.to_dict()), 999))

    with pytest.raises(ValueError, match="duplicates existing identity"):
        queue.restore_login_failure_jobs([original["id"]], reason=REASON, dry_run=False)


@pytest.mark.parametrize(
    "ids,options",
    [
        ([], {}),
        (["missing"], {}),
        (["dead-upload", "dead-upload"], {}),
        (["dead-upload"], {"reason": ""}),
        (["dead-upload"], {"additional_attempts": 0}),
        (["dead-upload"], {"additional_attempts": 4}),
        (["dead-upload"], {"additional_attempts": True}),
        (["dead-upload"], {"dry_run": "false"}),
    ],
)
def test_explicit_scope_and_bounded_authorization_are_required(queue, ids, options):
    _dead(queue)
    before = _snapshot(queue)

    with pytest.raises(ValueError):
        queue.restore_login_failure_jobs(ids, **({"reason": REASON, "dry_run": False} | options))

    assert _snapshot(queue) == before

"""Durable exact upload proof survives bounded queue history without restoring work."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest

from pinterest_automation import job_queue as module
from pinterest_automation.job_queue import Job, JobQueue

PIN_ID = "1148488342519565283"
RESULT = {"success": True, "pin_id": PIN_ID, "pin_url": f"https://www.pinterest.com/pin/{PIN_ID}/"}


@pytest.fixture
def queue(tmp_path, monkeypatch):
    for name in ("QUEUE_FILE", "DLQ_FILE", "COMPLETED_FILE"):
        monkeypatch.setattr(module, name, tmp_path / f"absent-{name}.json")
    monkeypatch.setattr(module, "get_config", lambda: SimpleNamespace(default_account="rida"))
    return JobQueue(tmp_path / "active.db")


def completed(job_id="primary", **changes):
    data = Job(
        id=job_id,
        priority=1,
        payload={"link": "https://recetadolce.com/recipe", "account_handle": "rida"},
        status="completed",
        completed_at=1.0,
        result=dict(RESULT),
    ).to_dict()
    data.update(changes)
    return data


def snapshot(tmp_path, jobs):
    path = tmp_path / "snapshot.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE completed_log (id TEXT PRIMARY KEY, job_json TEXT, completed_at REAL)"
        )
        for row_id, data in jobs:
            connection.execute(
                "INSERT INTO completed_log VALUES (?, ?, ?)",
                (row_id, json.dumps(data), data.get("completed_at", 1.0)),
            )
    return path


def rows(queue, table):
    if table not in {"jobs", "dlq", "completed_log", "completion_evidence"}:
        raise ValueError("Unknown test table")
    with sqlite3.connect(queue._db_file) as connection:
        return connection.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()  # noqa: S608


@pytest.mark.parametrize("async_completion", [False, True])
@pytest.mark.parametrize("priority", [1, 5])
def test_upload_evidence_survives_count_trim_ttl_and_deduplicates(
    queue, monkeypatch, async_completion, priority
):
    monkeypatch.setattr(module, "_COMPLETED_LOG_KEEP", 1)
    for job_id in ("first", "newest"):
        queue.enqueue(Job(id=job_id, priority=priority, payload={"image_path": f"{job_id}.jpg"}))
        if async_completion:
            asyncio.run(queue.complete_async(job_id, RESULT))
        else:
            queue.complete(job_id, RESULT)
    assert len(rows(queue, "completed_log")) == 1
    assert queue.get_job_outcome("first")["state"] == "completed"
    monkeypatch.setattr(module, "_COMPLETED_TTL_SECONDS", -1)
    queue.purge_completed()
    assert rows(queue, "completed_log") == []
    assert len(rows(queue, "completion_evidence")) == 2
    assert queue.get_job_outcome("newest")["result"] == RESULT
    duplicate = Job(id="duplicate", payload={"image_path": "first.jpg"})
    if async_completion:
        assert asyncio.run(queue.enqueue_async(duplicate)) == "first"
    else:
        assert queue.enqueue(duplicate) == "first"
    assert rows(queue, "jobs") == []


def test_initialization_backfills_existing_valid_history_only(queue):
    with sqlite3.connect(queue._db_file) as connection:
        for data in (completed(), completed("unverified", result={"success": True})):
            connection.execute(
                "INSERT INTO completed_log VALUES (?, ?, ?)", (data["id"], json.dumps(data), 1.0)
            )
    second = JobQueue(queue._db_file)
    assert [row[0] for row in rows(second, "completion_evidence")] == ["primary"]
    assert json.loads(rows(second, "completion_evidence")[0][4])["kind"] == "completed_log_backfill"


def test_dlq_independent_completion_and_legacy_import_preserve_evidence(queue, tmp_path):
    dead = completed("dead", status="dead", result=None)
    with sqlite3.connect(queue._db_file) as connection:
        connection.execute("INSERT INTO dlq VALUES (?, ?, ?)", ("dead", json.dumps(dead), 1.0))
    assert queue.complete_from_dlq("dead", RESULT)
    legacy = tmp_path / "completed.json"
    legacy.write_text(json.dumps([completed("legacy")]), encoding="utf-8")
    queue._import_legacy_completed(legacy)
    assert {row[0] for row in rows(queue, "completion_evidence")} == {"dead", "legacy"}
    assert rows(queue, "dlq") == []


def test_snapshot_recovery_preview_exact_scope_provenance_and_idempotency(queue, tmp_path):
    source = snapshot(
        tmp_path, [("selected", completed("selected")), ("unselected", completed("unselected"))]
    )
    source_bytes = source.read_bytes()
    preview = queue.recover_completion_evidence(source, ["selected"])
    assert preview["dry_run"] is True and preview["eligible"] == 1
    assert rows(queue, "completion_evidence") == []
    result = queue.recover_completion_evidence(source, ["selected"], dry_run=False)
    assert result["imported"] == ["selected"]
    assert source.read_bytes() == source_bytes
    assert all(rows(queue, table) == [] for table in ("jobs", "dlq", "completed_log"))
    assert queue.get_job_outcome("unselected")["found"] is False
    outcome = queue.get_job_outcome("selected")
    assert outcome["state"] == "completed" and outcome["result"] == RESULT
    assert outcome["evidence_provenance"]["source_sha256"] == hashlib.sha256(source_bytes).hexdigest()
    assert outcome["evidence_provenance"]["source_table"] == "completed_log"
    repeat = queue.recover_completion_evidence(source, ["selected"], dry_run=False)
    assert repeat["imported"] == [] and repeat["already_present"] == ["selected"]


@pytest.mark.parametrize(
    "bad",
    [
        {"status": "pending"},
        {"type": "pin_save"},
        {"id": "different"},
        {"result": {"success": True}},
        {"result": {**RESULT, "success": False}},
        {"result": {**RESULT, "pin_url": "https://www.pinterest.com/pin/1148488342519565000/"}},
        {"result": {**RESULT, "pin_url": f"https://evil.invalid/pin/{PIN_ID}/"}},
    ],
)
def test_snapshot_recovery_rejects_invalid_proof_atomically(queue, tmp_path, bad):
    source = snapshot(tmp_path, [("valid", completed("valid")), ("invalid", completed("invalid", **bad))])
    with pytest.raises(ValueError):
        queue.recover_completion_evidence(source, ["valid", "invalid"], dry_run=False)
    assert rows(queue, "completion_evidence") == []


@pytest.mark.parametrize("state", ["pending", "held", "dead"])
def test_snapshot_recovery_never_overrides_current_active_or_dead_state(queue, tmp_path, state):
    source = snapshot(tmp_path, [("selected", completed("selected"))])
    if state == "dead":
        with sqlite3.connect(queue._db_file) as connection:
            connection.execute(
                "INSERT INTO dlq VALUES (?, ?, ?)",
                ("selected", json.dumps(completed("selected", status=state)), 1.0),
            )
    else:
        queue.enqueue(Job(id="selected", status=state))
    with pytest.raises(ValueError, match="active or dead"):
        queue.recover_completion_evidence(source, ["selected"], dry_run=False)
    assert queue.get_job_outcome("selected")["state"] == state
    assert rows(queue, "completion_evidence") == []


def test_existing_durable_proof_never_hides_current_job_or_dlq(queue, tmp_path):
    source = snapshot(tmp_path, [("selected", completed("selected"))])
    queue.recover_completion_evidence(source, ["selected"], dry_run=False)
    queue.enqueue(Job(id="selected", status="held"))
    assert queue.get_job_outcome("selected")["state"] == "held"
    with sqlite3.connect(queue._db_file) as connection:
        connection.execute("DELETE FROM jobs")
        connection.execute(
            "INSERT INTO dlq VALUES (?, ?, ?)",
            ("selected", json.dumps(completed("selected", status="dead")), 1.0),
        )
    assert queue.get_job_outcome("selected")["state"] == "dead"


def test_snapshot_recovery_rejects_conflicts_and_missing_exact_ids(queue, tmp_path):
    source = snapshot(tmp_path, [("selected", completed("selected"))])
    queue.recover_completion_evidence(source, ["selected"], dry_run=False)
    with sqlite3.connect(source) as connection:
        changed = completed("selected", payload={"link": "https://recetagenial.com/different"})
        connection.execute("UPDATE completed_log SET job_json=?", (json.dumps(changed),))
    with pytest.raises(ValueError, match="conflicting"):
        queue.recover_completion_evidence(source, ["selected"], dry_run=False)
    with pytest.raises(ValueError, match="every selected"):
        queue.recover_completion_evidence(source, ["missing"], dry_run=False)
    with pytest.raises(ValueError, match="nonempty"):
        queue.recover_completion_evidence(source, [], dry_run=False)
    assert len(rows(queue, "completion_evidence")) == 1


@pytest.mark.parametrize("async_completion", [False, True])
def test_evidence_write_failure_rolls_back_queue_completion(queue, async_completion):
    queue.enqueue(Job(id="selected"))
    with sqlite3.connect(queue._db_file) as connection:
        connection.execute(
            "CREATE TRIGGER fail_evidence BEFORE INSERT ON completion_evidence "
            "BEGIN SELECT RAISE(ABORT, 'forced evidence failure'); END"
        )
    with pytest.raises(sqlite3.DatabaseError, match="forced evidence failure"):
        if async_completion:
            asyncio.run(queue.complete_async("selected", RESULT))
        else:
            queue.complete("selected", RESULT)
    assert queue.get_job_outcome("selected")["state"] == "pending"
    assert rows(queue, "completed_log") == []
    assert rows(queue, "completion_evidence") == []

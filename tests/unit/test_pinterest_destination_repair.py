"""Canonical destination repair is explicit, atomic and preserves queue history."""

from __future__ import annotations

import copy
import json
import sqlite3
from types import SimpleNamespace

import pytest

import pinterest_automation.job_queue as queue_module
from pinterest_automation.job_queue import Job, JobQueue

pytestmark = pytest.mark.unit
REASON = "Repair verified legacy folder destinations after worker drain"


@pytest.fixture
def queue(tmp_path, monkeypatch):
    for name in ("QUEUE_FILE", "DLQ_FILE", "COMPLETED_FILE"):
        monkeypatch.setattr(queue_module, name, tmp_path / name)
    monkeypatch.setattr(
        queue_module, "get_config", lambda: SimpleNamespace(accounts={"rida": object(), "media": object()})
    )
    monkeypatch.setattr(
        "rankstein.domain.get_registry",
        lambda: SimpleNamespace(
            all=lambda: [
                SimpleNamespace(handle="recetagenial", domain="recetagenial.com"),
                SimpleNamespace(handle="recetadolce", domain="recetadolce.com"),
            ]
        ),
    )
    return JobQueue(db_file=tmp_path / "jobs.db")


def _entry(queue, job_id="folder-upload", *, status="pending", image=None):
    image = (
        image
        or queue._db_file.parent
        / "remaster_final"
        / "recetagenial"
        / "2026-10-10"
        / "mango-sin-horno"
        / f"{job_id}-source-01.jpg"
    )
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"retained image")
    payload = {
        "image_path": str(image),
        "account_handle": "rida",
        "domain_handle": "recetadolce",
        "board_name": "Chocolate",
        "title": "Mango Source 01 Recipe Card",
        "description": "Legacy description",
        "alt_text": "Legacy alt",
        "link": "https://recetadolce.com/mango-sin-horno-source-01-recipe-card",
        "extra": {
            "account_handle": "rida",
            "domain_handle": "recetadolce",
            "campaign_type": "folder_batch",
            "slug": "mango-source-01",
            "preserved": "campaign metadata",
        },
    }
    job = Job(
        id=job_id,
        payload=payload,
        status=status,
        attempt=2,
        max_attempts=3,
        created_at=123.25,
        next_retry_at=9999999999,
        priority=7,
        error_log=["Attempt 1: Login failed"],
    )
    with queue._conn() as conn:
        conn.execute(queue_module._INSERT_OR_REPLACE_JOB, queue_module._job_to_row(job))
    return {
        "id": job_id,
        "expected_status": status,
        "expected_payload": copy.deepcopy(payload),
        "article": {
            "status": 200,
            "domain_handle": "recetagenial",
            "canonical_url": "https://recetagenial.com/mango-sin-horno",
            "recipe_schema": {"@type": "Recipe", "name": "Tarta de queso con mango sin horno"},
        },
    }


def _snapshot(queue):
    queries = {
        "jobs": "SELECT * FROM jobs ORDER BY id",
        "dlq": "SELECT * FROM dlq ORDER BY id",
        "completed_log": "SELECT * FROM completed_log ORDER BY id",
        "completion_evidence": "SELECT * FROM completion_evidence ORDER BY id",
    }
    with queue._conn() as conn:
        return {table: [tuple(row) for row in conn.execute(query)] for table, query in queries.items()}


def _row(queue, job_id):
    with queue._conn() as conn:
        return dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())


def _duplicate(queue, entry, table, history=None, *, same_id=False, same_idempotency=False):
    payload = copy.deepcopy(entry["expected_payload"])
    payload["domain_handle"] = "recetagenial"
    payload["extra"]["domain_handle"] = "recetagenial"
    payload["link"] = entry["article"]["canonical_url"]
    if same_idempotency:
        payload["image_path"] = "different-image.jpg"
    duplicate_id = entry["id"] if same_id else "previous-canonical-job"
    job = Job(
        id=duplicate_id,
        payload=payload,
        status="dead" if table == "dlq" else "completed",
        attempt=3,
        max_attempts=3,
        error_log=history or ["Attempt 3: Login failed"],
    )
    with queue._conn() as conn:
        if table == "jobs":
            conn.execute(queue_module._INSERT_OR_REPLACE_JOB, queue_module._job_to_row(job))
        elif table == "dlq":
            conn.execute("INSERT INTO dlq VALUES (?, ?, ?)", (job.id, json.dumps(job.to_dict()), 555))
        elif table == "completed_log":
            conn.execute(
                "INSERT INTO completed_log VALUES (?, ?, ?)", (job.id, json.dumps(job.to_dict()), 555)
            )
        else:
            conn.execute(
                "INSERT INTO completion_evidence VALUES (?, ?, ?, ?, ?)",
                (job.id, json.dumps(job.to_dict()), 555, 555, "{}"),
            )


def test_default_dry_run_reports_changes_without_writing_any_table(queue):
    entry = _entry(queue)
    before = _snapshot(queue)

    result = queue.repair_upload_destinations([entry], reason=REASON)

    assert result["dry_run"] is True
    assert result["repair_count"] == 1
    assert result["applied"] == 0
    assert _snapshot(queue) == before


def test_apply_changes_only_canonical_metadata_and_audit_history(queue):
    entry = _entry(queue, status="retry")
    before = _row(queue, entry["id"])
    result = queue.repair_upload_destinations([entry], reason=REASON, dry_run=False)
    after = _row(queue, entry["id"])

    assert result["applied"] == 1
    assert {k: v for k, v in before.items() if k not in {"payload_json", "error_log_json"}} == {
        k: v for k, v in after.items() if k not in {"payload_json", "error_log_json"}
    }
    payload = json.loads(after["payload_json"])
    assert payload["link"] == entry["article"]["canonical_url"]
    assert payload["domain_handle"] == payload["extra"]["domain_handle"] == "recetagenial"
    assert payload["extra"]["slug"] == "mango-sin-horno"
    assert payload["extra"]["preserved"] == "campaign metadata"
    for key in ("title", "description", "alt_text"):
        assert payload[key] == entry["article"]["recipe_schema"]["name"]
    for key in ("image_path", "account_handle", "board_name"):
        assert payload[key] == entry["expected_payload"][key]
    errors = json.loads(after["error_log_json"])
    assert errors[:-1] == json.loads(before["error_log_json"])
    assert REASON in errors[-1]
    assert queue.dequeue() is None


@pytest.mark.parametrize("table", ["jobs", "completed_log", "completion_evidence"])
def test_existing_canonical_identity_holds_job_without_touching_previous_record(queue, table):
    entry = _entry(queue)
    _duplicate(queue, entry, table)
    old_table = _snapshot(queue)[table]

    result = queue.repair_upload_destinations([entry], reason=REASON, dry_run=False)

    assert result["hold_count"] == 1
    assert _row(queue, entry["id"])["status"] == "held"
    if table != "jobs":
        assert _snapshot(queue)[table] == old_table


@pytest.mark.parametrize("table", ["dlq", "completed_log", "completion_evidence"])
def test_same_id_terminal_record_cannot_be_republished(queue, table):
    entry = _entry(queue)
    _duplicate(queue, entry, table, same_id=True)

    result = queue.repair_upload_destinations([entry], reason=REASON, dry_run=False)

    assert result["hold_count"] == 1
    assert result["details"][0]["conflicts"] == [{"table": table, "id": entry["id"]}]


@pytest.mark.parametrize(
    "history,expected_action",
    [
        (["Attempt 1: Login failed", "Attempt 2: Login failed", "Attempt 3: Login failed"], "repair"),
        (["Attempt 1: Pin creation could not be verified; no pin_id or pin_url found"], "hold"),
        (["Requeued from DLQ at prior recovery", "Attempt 3: Login failed"], "hold"),
        (["Attempt 1: input file timeout", "Attempt 3: Login failed"], "hold"),
    ],
)
def test_dead_duplicates_are_left_quarantined_and_uncertain_history_holds_repaired_job(
    queue, history, expected_action
):
    entry = _entry(queue)
    _duplicate(queue, entry, "dlq", history)
    before = _snapshot(queue)["dlq"]

    result = queue.repair_upload_destinations([entry], reason=REASON, dry_run=False)

    assert result["details"][0]["action"] == expected_action
    assert _snapshot(queue)["dlq"] == before


def test_global_idempotency_conflict_remains_held_even_with_login_only_history(queue):
    entry = _entry(queue)
    entry["expected_payload"]["extra"]["idempotency_key"] = "same-global-key"
    with queue._conn() as conn:
        conn.execute(
            "UPDATE jobs SET payload_json = ? WHERE id = ?",
            (json.dumps(entry["expected_payload"]), entry["id"]),
        )
    _duplicate(queue, entry, "dlq", same_idempotency=True)

    result = queue.repair_upload_destinations([entry], reason=REASON, dry_run=False)

    assert result["hold_count"] == 1


def test_batch_proposed_duplicate_has_only_one_unheld_canonical_job(queue):
    first = _entry(queue, "first")
    second = _entry(queue, "second", image=queue_module.Path(first["expected_payload"]["image_path"]))

    result = queue.repair_upload_destinations([first, second], reason=REASON, dry_run=False)

    assert result["repair_count"] == 1
    assert result["hold_count"] == 1
    assert _row(queue, "first")["status"] == "pending"
    assert _row(queue, "second")["status"] == "held"


@pytest.mark.parametrize(
    "invalid",
    [
        "processing",
        "held",
        "status_changed",
        "payload_changed",
        "account",
        "conflicting_account",
        "no_image",
        "folder",
        "canonical",
        "domain",
        "schema",
        "name",
        "http_status",
    ],
)
def test_invalid_last_entry_rolls_back_whole_batch(queue, invalid):
    first = _entry(queue, "first")
    second = _entry(queue, "second")
    if invalid in {"processing", "held"}:
        second["expected_status"] = invalid
        with queue._conn() as conn:
            conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (invalid, second["id"]))
    elif invalid == "status_changed":
        second["expected_status"] = "retry"
    elif invalid == "payload_changed":
        second["expected_payload"]["title"] = "outdated payload"
    elif invalid in {"account", "conflicting_account"}:
        second["expected_payload"]["account_handle"] = "unknown" if invalid == "account" else "media"
        with queue._conn() as conn:
            conn.execute(
                "UPDATE jobs SET payload_json = ? WHERE id = ?",
                (json.dumps(second["expected_payload"]), second["id"]),
            )
    elif invalid == "no_image":
        queue_module.Path(second["expected_payload"]["image_path"]).unlink()
    elif invalid == "folder":
        second["article"]["canonical_url"] = "https://recetagenial.com/different-slug"
    elif invalid == "canonical":
        second["article"]["canonical_url"] = "https://unrelated.example/mango-sin-horno"
    elif invalid == "domain":
        second["article"]["domain_handle"] = "recetadolce"
    elif invalid == "schema":
        second["article"]["recipe_schema"]["@type"] = "WebPage"
    elif invalid == "name":
        second["article"]["recipe_schema"]["name"] = ""
    elif invalid == "http_status":
        second["article"]["status"] = 404
    before = _snapshot(queue)

    with pytest.raises(ValueError):
        queue.repair_upload_destinations([first, second], reason=REASON, dry_run=False)

    assert _snapshot(queue) == before


def test_unselected_existing_held_work_is_preserved(queue):
    entry = _entry(queue)
    held = _entry(queue, "original-held", status="held")
    before = _row(queue, held["id"])

    queue.repair_upload_destinations([entry], reason=REASON, dry_run=False)

    assert _row(queue, held["id"]) == before


def test_update_failure_rolls_back_every_payload_and_hold(queue):
    first = _entry(queue, "first")
    second = _entry(queue, "second")
    with queue._conn() as conn:
        conn.execute(
            "CREATE TRIGGER reject_second BEFORE UPDATE ON jobs WHEN NEW.id = 'second' BEGIN SELECT RAISE(ABORT, 'test failure'); END"
        )
    before = _snapshot(queue)

    with pytest.raises(sqlite3.IntegrityError, match="test failure"):
        queue.repair_upload_destinations([first, second], reason=REASON, dry_run=False)

    assert _snapshot(queue) == before

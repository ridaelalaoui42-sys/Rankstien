"""The throughput observer must count archive proof and leave the queue alone."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from scripts.dev.observe_pinterest_workers import read_queue_snapshot, summarize, verified_pin


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"success": True, "pin_id": "1148488342513342877"}, True),
        ({"success": True, "pin_url": "https://www.pinterest.com/pin/1148488342513342877/"}, True),
        ({"success": False, "pin_id": "1148488342513342877"}, False),
        ({"success": True}, False),
        ({"success": True, "pin_id": "123"}, False),
        ({"success": True, "pin_url": "https://attacker.example/pin/1148488342513342877/"}, False),
        ({"success": True, "pin_url": "https://www.pinterest.com/pin/123/"}, False),
        ({"success": True, "pin_url": "https://[invalid/pin/1148488342513342877/"}, False),
    ],
)
def test_only_success_with_pin_proof_is_counted(result: dict, expected: bool) -> None:
    assert (verified_pin(result) is not None) is expected


def _database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            "CREATE TABLE jobs (id TEXT PRIMARY KEY, type TEXT, payload_json TEXT, status TEXT, "
            "started_at REAL, completed_at REAL, next_retry_at REAL, result_json TEXT);"
            "CREATE TABLE completed_log (id TEXT PRIMARY KEY, job_json TEXT, completed_at REAL);"
        )
        rows = [
            (
                "processing-r1",
                "pin_upload",
                {"account_handle": "r1", "extra": {"campaign_type": "article_remaster_pairs"}},
                "processing",
                970,
                None,
                None,
                None,
            ),
            ("stale-r1", "pin_upload", {"account_handle": "r1"}, "processing", 100, None, None, None),
            (
                "processing-r2",
                "pin_save",
                {"extra": {"account_handle": "r2"}},
                "processing",
                990,
                None,
                None,
                None,
            ),
            (
                "ready-r2",
                "pin_upload",
                {"extra": {"account_handle": "r2", "campaign_type": "folder_batch"}},
                "pending",
                None,
                None,
                None,
                None,
            ),
            ("deferred-r2", "pin_upload", {"account_handle": "r2"}, "retry", None, None, 1200, None),
            (
                "unknown",
                "pin_upload",
                {
                    "account_handle": "secret@example.test",
                    "description": "sensitive article",
                    "image_path": "private/profile/path",
                },
                "held",
                None,
                None,
                None,
                None,
            ),
            (
                "completed-duplicate",
                "pin_upload",
                {"account_handle": "r1"},
                "completed",
                950,
                970,
                None,
                {"success": True, "pin_id": "1148488342513342877"},
            ),
            (
                "unverified",
                "pin_upload",
                {"account_handle": "r2"},
                "completed",
                950,
                970,
                None,
                {"success": True},
            ),
        ]
        for job_id, job_type, payload, status, started, completed, retry, result in rows:
            connection.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    job_type,
                    json.dumps(payload),
                    status,
                    started,
                    completed,
                    retry,
                    json.dumps(result),
                ),
            )
        for job_id, account, pin_id in [
            ("completed-duplicate", "r1", "1148488342513342877"),
            ("archived-only", "r2", "1148488342513342878"),
        ]:
            archived = {
                "id": job_id,
                "type": "pin_upload",
                "status": "completed",
                "payload": {"account_handle": account, "extra": {"campaign_type": "article_remaster_pairs"}},
                "result": {"success": True, "pin_id": pin_id},
                "started_at": 940,
                "completed_at": 970,
            }
            connection.execute(
                "INSERT INTO completed_log VALUES (?, ?, ?)", (job_id, json.dumps(archived), 970)
            )


def test_snapshot_unions_archived_proof_deduplicates_and_sanitizes(tmp_path: Path) -> None:
    path = tmp_path / "jobs.db"
    _database(path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    snapshot, completed = read_queue_snapshot(path, ["r1", "r2"], observed_at=1000)

    assert set(completed) == {"completed-duplicate", "archived-only"}
    assert snapshot["verified_completions_in_window"] == 2
    assert snapshot["unverified_completed_jobs_in_window"] == 1
    assert snapshot["distinct_processing_accounts"] == 2
    assert snapshot["accounts"]["r1"]["processing"] == 2
    assert snapshot["accounts"]["r1"]["stale_processing"] == 1
    assert snapshot["accounts"]["r1"]["processing_remasters"] == 1
    assert snapshot["accounts"]["r2"]["ready_remasters"] == 1
    assert snapshot["accounts"]["r2"]["deferred"] == 1
    assert snapshot["accounts"]["_unconfigured"]["held"] == 1
    assert snapshot["processing_by_type"] == {"pin_upload": 2, "pin_save": 1}
    serialized = json.dumps({"snapshot": snapshot, "completed": completed})
    assert "secret@example.test" not in serialized
    assert "sensitive article" not in serialized
    assert "private/profile/path" not in serialized
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_window_filter_applies_to_active_and_archived_completions(tmp_path: Path) -> None:
    path = tmp_path / "jobs.db"
    _database(path)
    snapshot, completed = read_queue_snapshot(path, ["r1", "r2"], observed_at=1000, completed_since=980)
    assert completed == {}
    assert snapshot["verified_completions_in_window"] == 0


def test_missing_database_is_not_created(tmp_path: Path) -> None:
    path = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        read_queue_snapshot(path, ["r1"])
    assert not path.exists()


def test_previous_supervisor_leases_are_visible_but_not_active(tmp_path: Path) -> None:
    path = tmp_path / "jobs.db"
    _database(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "current-owner",
                "pin_upload",
                json.dumps({"account_handle": "r2"}),
                "processing",
                997,
                None,
                None,
                None,
            ),
        )

    snapshot, _ = read_queue_snapshot(path, ["r1", "r2"], observed_at=1000, active_processing_since=995)

    assert snapshot["distinct_processing_accounts"] == 1
    assert snapshot["processing_accounts"] == ["r2"]
    assert snapshot["accounts"]["r1"]["processing"] == 2
    assert snapshot["accounts"]["r1"]["previous_supervisor_processing"] == 2
    assert snapshot["accounts"]["r1"]["active_processing"] == 0
    assert snapshot["accounts"]["r2"]["processing"] == 2
    assert snapshot["accounts"]["r2"]["previous_supervisor_processing"] == 1
    assert snapshot["accounts"]["r2"]["active_processing"] == 1
    assert snapshot["active_processing_by_type"] == {"pin_upload": 1}
    previous = next(row for row in snapshot["processing_jobs"] if row["job_id"] == "processing-r1")
    assert previous["age_seconds"] == 30
    assert previous["stale"] is False
    assert previous["previous_supervisor"] is True
    assert previous["active"] is False

    without_known_owner, _ = read_queue_snapshot(path, ["r1", "r2"], observed_at=1000)
    assert without_known_owner["distinct_processing_accounts"] == 2
    assert without_known_owner["accounts"]["r1"]["active_processing"] == 1


def test_summary_measures_actual_window_and_per_account_delta(tmp_path: Path) -> None:
    path = tmp_path / "jobs.db"
    _database(path)
    first, _ = read_queue_snapshot(path, ["r1", "r2"], observed_at=1000)
    last, completed = read_queue_snapshot(path, ["r1", "r2"], observed_at=1060)
    first["supervisor"] = last["supervisor"] = {"worker_count": 2}

    summary = summarize([first, last], completed, ["r1", "r2"])

    assert summary["verified_completion_delta"] == 2
    assert summary["pins_per_minute"] == 2
    assert summary["peak_observed_distinct_account_concurrency"] == 2
    assert summary["fixed_worker_count"] is True
    assert summary["per_account"]["r1"]["pins_per_minute"] == 1
    assert summary["per_account"]["r2"]["verified_remaster_completions"] == 1
    assert summary["per_account"]["r2"]["mean_processing_seconds"] == 30
    assert summarize([first], {}, ["r1", "r2"])["pins_per_minute"] is None


def test_saved_existing_pins_and_generic_publishes_do_not_inflate_upload_throughput(tmp_path: Path) -> None:
    path = tmp_path / "jobs.db"
    _database(path)
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM jobs WHERE status = 'completed'")
        connection.execute("DELETE FROM completed_log")
        for index, (job_type, account, remaster) in enumerate(
            [
                ("pin_upload", "r1", True),
                ("pin_save", "r1", True),
                ("pin_upload", "r2", False),
                ("pin_save", "r2", True),
                ("publish_article", "r2", True),
            ]
        ):
            job = {
                "id": f"completion-{index}",
                "type": job_type,
                "status": "completed",
                "payload": {
                    "account_handle": account,
                    "extra": {"campaign_type": "article_remaster_pairs" if remaster else "article_hero"},
                },
                "result": {"success": True, "pin_id": str(1148488342513342877 + index)},
                "started_at": 1000,
                "completed_at": 1020,
            }
            connection.execute(
                "INSERT INTO completed_log VALUES (?, ?, ?)", (job["id"], json.dumps(job), 1020)
            )

    first, _ = read_queue_snapshot(path, ["r1", "r2"], observed_at=1000, completed_since=1000)
    last, completed = read_queue_snapshot(path, ["r1", "r2"], observed_at=1120, completed_since=1000)
    summary = summarize([first, last], completed, ["r1", "r2"])

    assert len(completed) == 4
    assert summary["verified_completion_delta"] == 4
    assert summary["verified_remaster_completion_delta"] == 3
    assert summary["verified_upload_completion_delta"] == 2
    assert summary["verified_remaster_upload_completion_delta"] == 1
    assert summary["pins_per_minute"] == 2
    assert summary["verified_uploads_per_minute"] == 1
    assert summary["verified_remaster_uploads_per_minute"] == 0.5
    for account in ["r1", "r2"]:
        assert summary["per_account"][account]["verified_completions"] == 2
        assert summary["per_account"][account]["verified_upload_completions"] == 1
        assert summary["per_account"][account]["verified_uploads_per_minute"] == 0.5
    assert summary["per_account"]["r1"]["verified_remaster_upload_completions"] == 1
    assert summary["per_account"]["r1"]["verified_remaster_uploads_per_minute"] == 0.5
    assert summary["per_account"]["r2"]["verified_remaster_upload_completions"] == 0
    assert summary["per_account"]["r2"]["verified_remaster_uploads_per_minute"] == 0
    assert summarize([first], completed, ["r1", "r2"])["verified_uploads_per_minute"] is None

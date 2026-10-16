"""Durable completion evidence must not override a current held or dead job."""

from __future__ import annotations

import json
import sqlite3
import time

from backend.scripts.turbo_articles import _read_remaster_job_outcomes


def test_snapshot_uses_durable_completion_after_bounded_history_eviction(tmp_path):
    path = tmp_path / "data" / "queue" / "jobs.db"
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(
            "CREATE TABLE jobs(id TEXT, status TEXT, type TEXT, payload_json TEXT, result_json TEXT);"
            "CREATE TABLE completed_log(id TEXT, job_json TEXT);"
            "CREATE TABLE dlq(id TEXT, job_json TEXT);"
            "CREATE TABLE completion_evidence(id TEXT, job_json TEXT);"
        )
        completed = json.dumps(
            {"type": "pin_upload", "payload": {"pair_id": "exact"}, "result": {"success": True}}
        )
        connection.executemany(
            "INSERT INTO completion_evidence VALUES (?, ?)",
            [(value, completed) for value in ("evicted", "held", "dead", "pending")],
        )
        connection.executemany(
            "INSERT INTO jobs VALUES (?, ?, 'pin_upload', '{}', NULL)",
            [("held", "held"), ("pending", "pending")],
        )
        connection.execute("INSERT INTO dlq VALUES ('dead', ?)", (completed,))

    outcomes = _read_remaster_job_outcomes(
        ["evicted", "held", "dead", "pending", "missing"],
        project_root=tmp_path,
        deadline=time.monotonic() + 2,
    )

    assert outcomes["evicted"]["state"] == "completed"
    assert outcomes["evicted"]["payload"] == {"pair_id": "exact"}
    assert outcomes["held"]["state"] == "held"
    assert outcomes["dead"]["state"] == "dead"
    assert outcomes["pending"]["state"] == "pending"
    assert "missing" not in outcomes

"""Worker previews must describe current evidence without inventing live browsers."""

import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from backend.api import operator_routes as routes

NOW = 2_000.0


@pytest.fixture
def worker_runtime(tmp_path, monkeypatch):
    (tmp_path / "data/queue").mkdir(parents=True)
    (tmp_path / "data/runtime").mkdir()
    (tmp_path / "data/logs").mkdir()
    (tmp_path / "data/pinterest_accounts.json").write_text(
        json.dumps({"accounts": [{"handle": "culinary-account"}]}), encoding="utf-8"
    )
    database = tmp_path / "data/queue/jobs.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE jobs (id TEXT, type TEXT, payload_json TEXT, status TEXT, started_at REAL)"
        )
    monkeypatch.setattr(routes, "RANKSTEIN_ROOT", tmp_path)
    monkeypatch.setattr(routes.time, "time", lambda: NOW)
    monkeypatch.setattr(
        routes,
        "_worker_supervisor_evidence",
        lambda _: {"running": True, "started_at": NOW - 100, "heartbeat_at": NOW - 1},
    )
    return tmp_path, database


def add_job(database, *, account="culinary-account", started_at=NOW - 30, status="processing"):
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO jobs VALUES (?, ?, ?, ?, ?)",
            ("job-1", "pin_upload", json.dumps({"account_handle": account}), status, started_at),
        )


def screenshot(root, filename, recorded_at):
    path = root / "data/logs" / filename
    path.write_bytes(b"test screenshot fixture")
    os.utime(path, (recorded_at, recorded_at))
    return path


def test_no_processing_leases_do_not_invent_accounts_from_old_screenshots(worker_runtime):
    root, database = worker_runtime
    screenshot(root, "pin_timeout_driver-rida_1000.png", NOW - 900)
    add_job(database, status="held")
    before = database.read_bytes()

    assert routes._collect_workers_snapshots() == []
    assert database.read_bytes() == before


def test_current_lease_is_not_claimed_as_browser_health(worker_runtime):
    root, database = worker_runtime
    add_job(database)
    screenshot(root, "snapshot_driver-culinary-account_1990.png", NOW - 10)
    row = routes._collect_workers_snapshots()[0]

    assert row["account"] == "culinary-account"
    assert row["worker_id"] is None
    assert row["job_id"] == "job-1"
    assert row["status"] == "leased"
    assert row["lease"] == "current queue lease"
    assert "browser activity unavailable" in row["action"]
    assert row["updated_at"] == NOW - 30
    assert row["snapshot_updated_at"] == NOW - 10
    assert row["snapshot_url"].endswith("data/logs/snapshot_driver-culinary-account_1990.png")
    assert "healthy" not in json.dumps(row)


@pytest.mark.parametrize("recorded_at", [NOW - 1_000, NOW - 31, NOW + 20])
def test_old_prelease_or_future_screenshots_are_not_current_previews(worker_runtime, recorded_at):
    root, database = worker_runtime
    add_job(database)
    screenshot(root, "pin_timeout_driver-culinary-account_1990.png", recorded_at)
    row = routes._collect_workers_snapshots()[0]

    assert row["snapshot_url"] == row["snapshot_path"] == ""
    assert row["snapshot_updated_at"] is None
    assert row["updated_at"] == NOW - 30


def test_account_name_substrings_do_not_match_another_accounts_screenshot(worker_runtime):
    root, database = worker_runtime
    add_job(database)
    screenshot(root, "snapshot_driver-other-culinary-account_1990.png", NOW - 10)

    assert routes._collect_workers_snapshots()[0]["snapshot_url"] == ""


@pytest.mark.parametrize(
    ("started_at", "owner", "account", "reason"),
    [
        (NOW - 700, True, "culinary-account", "stale processing lease"),
        (NOW + 10, True, "culinary-account", "stale processing lease"),
        (None, True, "culinary-account", "stale processing lease"),
        (NOW - 30, False, "culinary-account", "supervisor ownership unconfirmed"),
        (NOW - 120, True, "culinary-account", "lease belongs to an earlier supervisor"),
        (NOW - 30, True, "unknown-account", "account is not configured"),
    ],
)
def test_stale_or_unowned_leases_do_not_claim_live_activity(
    worker_runtime, monkeypatch, started_at, owner, account, reason
):
    root, database = worker_runtime
    monkeypatch.setattr(
        routes, "_worker_supervisor_evidence", lambda _: {"running": owner, "started_at": NOW - 100}
    )
    add_job(database, account=account, started_at=started_at)
    screenshot(root, f"snapshot_driver-{account}_1990.png", NOW - 10)
    row = routes._collect_workers_snapshots()[0]

    assert row["status"] == "unconfirmed"
    assert row["lease"] == reason
    assert row["snapshot_url"] == ""


def test_missing_queue_does_not_create_runtime_files(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, "RANKSTEIN_ROOT", tmp_path)
    monkeypatch.setattr(routes, "_worker_supervisor_evidence", lambda _: {})

    assert routes._collect_workers_snapshots() == []
    assert list(tmp_path.iterdir()) == []


def test_unreadable_queue_is_not_reported_as_healthy(worker_runtime):
    _, database = worker_runtime
    database.write_bytes(b"not a sqlite database")

    assert routes._collect_workers_snapshots() == []
    assert database.read_bytes() == b"not a sqlite database"


@pytest.mark.parametrize(
    ("heartbeat", "created_at", "command_kind", "running"),
    [
        (NOW - 1, NOW - 101, "owned", True),
        (NOW - 121, NOW - 101, "owned", False),
        (NOW - 1, NOW - 90, "owned", False),
        (NOW - 1, NOW - 101, "unrelated", False),
        ("invalid", NOW - 101, "owned", False),
    ],
)
def test_supervisor_identity_and_heartbeat_are_required(
    tmp_path, monkeypatch, heartbeat, created_at, command_kind, running
):
    import psutil

    runtime = tmp_path / "data/runtime"
    runtime.mkdir(parents=True)
    state = {"pid": 42, "started_at": NOW - 100, "heartbeat_at": heartbeat}
    path = runtime / "supervisor.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setattr(routes, "RANKSTEIN_ROOT", tmp_path)

    class Process:
        def __init__(self, pid):
            assert pid == 42

        def cmdline(self):
            script = "run_autonomous.py" if command_kind == "owned" else "unrelated.py"
            return ["python", str(tmp_path / script), "run"]

        def create_time(self):
            return created_at

    monkeypatch.setattr(psutil, "Process", Process)

    assert routes._worker_supervisor_evidence(NOW)["running"] is running
    assert path.read_bytes() == before


def test_worker_cards_clear_stale_content_and_label_unknown_activity():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the isolated worker-card rendering check")
    source = Path(__file__).resolve().parents[2] / "backend/static/operator/operator.js"
    script = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const source = fs.readFileSync(process.argv[1], 'utf8');
const renderer = source.slice(source.indexOf('function renderWorkerViewports('), source.indexOf('function updateTelemetryHud('));
const cards = { 'worker-viewports': {innerHTML: 'old healthy worker'}, 'services-worker-viewports': {innerHTML: 'old healthy worker'} };
const context = { $: id => cards[id], esc: value => String(value ?? ''), date: value => value || '-', icons: () => {}, empty: (title, detail) => `${title} ${detail}` };
vm.runInNewContext(renderer, context);
context.renderWorkerViewports([]);
for (const card of Object.values(cards)) {
  assert(card.innerHTML.includes('No current worker evidence'));
  assert(!card.innerHTML.includes('old healthy worker'));
}
context.renderWorkerViewports([{worker_id: null, account: 'culinary-account', status: 'unconfirmed', snapshot_url: '/old.png'}]);
for (const card of Object.values(cards)) {
  assert(card.innerHTML.includes('Queue lease'));
  assert(card.innerHTML.includes('No current browser preview'));
  assert(card.innerHTML.includes('Worker activity unavailable'));
  assert(!card.innerHTML.includes('Headless Viewport Active'));
  assert(!card.innerHTML.includes('src="/old.png"'));
  assert(!card.innerHTML.includes('badge ok'));
}
"""
    result = subprocess.run([node, "-e", script, str(source)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr

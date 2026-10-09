import json
import sqlite3
from types import SimpleNamespace

import pytest

from rankstein import production_safety as safety


@pytest.fixture(autouse=True)
def safe_resources(monkeypatch):
    monkeypatch.setattr(safety.log_manager, "check_resource_budget", lambda: {"ok": True, "issues": []})


def test_fresh_campaign_admitted_without_creating_database(tmp_path):
    path = tmp_path / "absent.db"
    report = safety.campaign_admission([SimpleNamespace(handle="a", daily_pin_budget=25)], queue_path=path)
    assert report["ok"]
    assert not path.exists()


def test_future_queue_backlog_cannot_hide_from_admission(tmp_path):
    path = tmp_path / "queue.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE jobs (type TEXT, status TEXT, payload_json TEXT)")
        conn.executemany(
            "INSERT INTO jobs VALUES ('pin_upload', 'pending', ?)",
            [(json.dumps({"domain_handle": "a"}),)] * 100,
        )
    before = path.read_bytes()
    report = safety.campaign_admission([SimpleNamespace(handle="a", daily_pin_budget=25)], queue_path=path)
    assert not report["ok"]
    assert report["delivery"]["a"]["pending_pins"] == 100
    assert path.read_bytes() == before


def test_unknown_schema_fails_closed(tmp_path):
    path = tmp_path / "queue.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE unrelated (id INTEGER)")
    assert not safety.campaign_admission([], queue_path=path)["ok"]


def test_memory_pressure_blocks_work(tmp_path, monkeypatch):
    monkeypatch.setattr(
        safety.log_manager, "check_resource_budget", lambda: {"ok": False, "issues": ["memory"]}
    )
    assert not safety.campaign_admission([], queue_path=tmp_path / "absent.db")["ok"]


def test_invalid_budget_and_limits_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("RANKSTEIN_MAX_QUEUE_DAYS", "nan")
    report = safety.campaign_admission([SimpleNamespace(handle="a", daily_pin_budget=0)], queue_path=tmp_path / "absent.db")
    assert not report["ok"]

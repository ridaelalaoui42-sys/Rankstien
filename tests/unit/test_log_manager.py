import os
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from rankstein import log_manager


@pytest.fixture
def temp_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    logs_dir = tmp_path / "logs"
    reports_dir = tmp_path / "reports"
    report_launch_dir = reports_dir / "launch"
    
    monkeypatch.setattr(log_manager, "LOGS_DIR", logs_dir)
    monkeypatch.setattr(log_manager, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(log_manager, "REPORT_LAUNCH_DIR", report_launch_dir)
    monkeypatch.setattr(log_manager, "DATA_DIR", tmp_path)
    
    log_manager.ensure_directories()
    
    return {
        "logs": logs_dir,
        "reports": report_launch_dir
    }


def test_rotate_logs(temp_logs):
    logs_dir = temp_logs["logs"]
    
    # Create a log from yesterday
    old_log = logs_dir / "service.log"
    old_log.write_text("old data")
    yesterday = time.time() - 86400
    os.utime(old_log, (yesterday, yesterday))
    
    # Create a log from today
    new_log = logs_dir / "other.log"
    new_log.write_text("new data")
    
    log_manager.rotate_logs()
    
    # Old log should be rotated
    assert not old_log.exists()
    rotated = list(logs_dir.glob("service.*.log"))
    assert len(rotated) == 1
    assert rotated[0].read_text() == "old data"
    
    # New log should not be rotated
    assert new_log.exists()
    assert len(list(logs_dir.glob("other.*.log"))) == 0


def test_cleanup_retained_files(temp_logs, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(log_manager, "RANKSTEIN_LOG_RETENTION_DAYS", 7)
    monkeypatch.setattr(log_manager, "RANKSTEIN_REPORT_RETENTION_DAYS", 30)
    
    logs_dir = temp_logs["logs"]
    reports_dir = temp_logs["reports"]
    
    # Create an old rotated log
    old_log = logs_dir / "service.20200101.log"
    old_log.write_text("old")
    too_old = time.time() - (8 * 86400)
    os.utime(old_log, (too_old, too_old))
    
    # Create a recent rotated log
    recent_log = logs_dir / "service.20230101.log"
    recent_log.write_text("recent")
    recent = time.time() - (2 * 86400)
    os.utime(recent_log, (recent, recent))
    
    # Create an old report
    old_report = reports_dir / "launch_old.json"
    old_report.write_text("{}")
    report_too_old = time.time() - (31 * 86400)
    os.utime(old_report, (report_too_old, report_too_old))
    
    log_manager.cleanup_retained_files()
    
    assert not old_log.exists()
    assert recent_log.exists()
    assert not old_report.exists()


def test_check_disk_space(temp_logs, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(log_manager, "RANKSTEIN_MIN_DISK_GB", 1000000.0) # Impossibly high
    
    res = log_manager.check_disk_space()
    assert not res["ok"]
    assert "Insufficient disk space" in res["error"]
    
    monkeypatch.setattr(log_manager, "RANKSTEIN_MIN_DISK_GB", 0.0) # Always ok
    res = log_manager.check_disk_space()
    assert res["ok"]
    assert res["error"] is None


def test_disk_measurement_failure_blocks_work(temp_logs, monkeypatch):
    def fail(_path):
        raise OSError("unavailable")

    monkeypatch.setattr(shutil, "disk_usage", fail)
    assert log_manager.check_disk_space()["ok"] is False


def test_nested_rotated_logs_follow_retention(temp_logs):
    nested = temp_logs["logs"] / "operator"
    nested.mkdir()
    old = nested / "production.20200101.log"
    old.write_text("old diagnostic", encoding="utf-8")
    os.utime(old, (time.time() - 90 * 86400,) * 2)
    active = nested / "production.log"
    active.write_text("current", encoding="utf-8")
    log_manager.cleanup_retained_files()
    assert not old.exists()
    assert active.exists()


def test_memory_pressure_blocks_production(temp_logs, monkeypatch):
    from types import SimpleNamespace

    import psutil

    monkeypatch.setattr(log_manager, "RANKSTEIN_MIN_DISK_GB", 0)
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(percent=97, available=2**30))
    assert not log_manager.check_resource_budget()["ok"]


def test_resources_allow_safe_work(temp_logs, monkeypatch):
    from types import SimpleNamespace

    import psutil

    monkeypatch.setattr(log_manager, "RANKSTEIN_MIN_DISK_GB", 0)
    monkeypatch.setattr(psutil, "virtual_memory", lambda: SimpleNamespace(percent=70, available=4 * 2**30))
    assert log_manager.check_resource_budget()["ok"]

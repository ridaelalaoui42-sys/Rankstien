import json
import os
import time
from pathlib import Path

import pytest

from rankstein import suite_controller
from rankstein.suite_controller import CampaignLease, ServiceSpec


@pytest.fixture
def temp_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setattr(suite_controller, "RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(suite_controller, "CAMPAIGN_LEASE_FILE", runtime_dir / "campaign_lease.json")
    monkeypatch.setattr(suite_controller, "SERVICES_STATE_FILE", runtime_dir / "services_state.json")
    return runtime_dir


def test_campaign_lease(temp_runtime):
    lease1 = CampaignLease()
    assert lease1.acquire() is True
    
    # Try acquiring second time from same process (simulating concurrent script)
    lease2 = CampaignLease()
    # It should fail since lease1 has it and PID is alive
    assert lease2.acquire() is False
    
    lease1.release()
    assert lease2.acquire() is True
    lease2.release()


def test_preflight_checks(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(suite_controller.log_manager, "check_disk_space", lambda: {"ok": True})
    
    # Preflight should pass assuming python and hermes exist in the test env
    res = suite_controller.preflight()
    # It might fail if hermes isn't really on path in CI, so we just check it doesn't crash
    assert isinstance(res, dict)
    assert "ok" in res
    assert isinstance(res.get("issues"), list)


def test_start_services_idempotent(monkeypatch: pytest.MonkeyPatch, temp_runtime):
    # Mock preflight and log manager
    monkeypatch.setattr(suite_controller, "preflight", lambda: {"ok": True, "issues": []})
    monkeypatch.setattr(suite_controller.log_manager, "maintain", lambda: {"ok": True})
    
    # Create a mock service
    mock_service = ServiceSpec(
        name="test_service",
        port=9999,
        cmd=["echo", "test"],
        cwd=Path("."),
        health_url=None,
        depends_on=[]
    )
    monkeypatch.setattr(suite_controller, "SERVICES", [mock_service])
    
    # Mock port open and health to simulate already running
    monkeypatch.setattr(suite_controller, "_port_open", lambda p: True)
    
    res = suite_controller.start_services()
    assert res["ok"] is True
    assert res["services"]["test_service"]["already_running"] is True
    assert res["services"]["test_service"]["started_now"] is False


def test_start_services_backoff(monkeypatch: pytest.MonkeyPatch, temp_runtime):
    # Mock preflight and log manager
    monkeypatch.setattr(suite_controller, "preflight", lambda: {"ok": True, "issues": []})
    monkeypatch.setattr(suite_controller.log_manager, "maintain", lambda: {"ok": True})
    
    mock_service = ServiceSpec(
        name="test_service",
        port=9999,
        cmd=["echo", "test"],
        cwd=Path("."),
        health_url=None,
        depends_on=[],
        max_restart_per_hour=3
    )
    monkeypatch.setattr(suite_controller, "SERVICES", [mock_service])
    
    # Mock port never opens
    monkeypatch.setattr(suite_controller, "_port_open", lambda p: False)
    # Mock start background to do nothing
    monkeypatch.setattr(suite_controller, "_start_background", lambda s: None)
    
    # Mock sleep and time to run fast
    fake_time = [0.0]
    def mock_time():
        fake_time[0] += 50.0  # Fast-forward past 45s timeout immediately
        return fake_time[0]
    monkeypatch.setattr(suite_controller.time, "time", mock_time)
    monkeypatch.setattr(suite_controller.time, "sleep", lambda s: None)
    
    res = suite_controller.start_services()
    assert res["ok"] is False
    assert res["services"]["test_service"]["ok"] is False
    assert "Failed all 3 startup attempts" in res["services"]["test_service"]["error"]
    
    # Check that state was updated with restarts
    state_file = suite_controller.SERVICES_STATE_FILE
    assert state_file.exists()
    state = json.loads(state_file.read_text())
    assert state["test_service"]["restarts"] == 3  # Failed all 3 attempts

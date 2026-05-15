from __future__ import annotations

import pytest


@pytest.mark.unit
def test_health_accepts_valid_multiaccount_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    import pinterest_automation.config as config_mod
    import pinterest_automation.health_monitor as health_mod

    monkeypatch.delenv("PINTEREST_EMAIL", raising=False)
    monkeypatch.delenv("PINTEREST_PASSWORD", raising=False)
    monkeypatch.setenv(
        "PINTEREST_ACCOUNTS",
        '[{"name":"m1","email":"m@example.test","password":"pw","session":"m1"},'
        '{"name":"r1","email":"r@example.test","password":"pw","session":"r1"}]',
    )

    config_mod._config = None
    health_mod._health_monitor = None

    snap = health_mod.HealthMonitor().heartbeat()

    assert snap.checks["pinterest_credentials"]["ok"] is True
    assert snap.checks["pinterest_credentials"]["detail"] == "set via accounts: m1, r1"

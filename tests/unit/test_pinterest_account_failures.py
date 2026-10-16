"""A failing account must not exhaust other accounts or unattempted queue jobs."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts.dev.benchmark_pinterest_workers import run_scenario


@pytest.mark.asyncio
async def test_login_circuit_is_isolated_to_its_account(monkeypatch, tmp_path):
    import pinterest_automation.circuit_breaker as circuit_module
    from pinterest_automation.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, CircuitState
    from pinterest_automation.pinterest_driver import PinterestDriver

    monkeypatch.setattr(circuit_module, "CIRCUIT_STATE_FILE", tmp_path / "circuits.json")
    config = SimpleNamespace(
        failure_threshold=1,
        recovery_timeout_seconds=60,
        success_threshold_to_close=1,
        half_open_max_calls=1,
        save_interval_seconds=60,
    )
    monkeypatch.setattr(circuit_module, "get_config", lambda: SimpleNamespace(circuit_breaker=config))
    circuit = CircuitBreaker()
    circuit.record_failure("pinterest_login:blocked")
    driver = object.__new__(PinterestDriver)
    driver.circuit = circuit
    driver.account_handle = None
    driver.info = lambda *_args: None
    driver._acquire_session = AsyncMock(
        return_value=SimpleNamespace(page=SimpleNamespace(url="https://www.pinterest.com/pin-creation-tool/"))
    )

    with pytest.raises(CircuitBreakerOpenError, match="blocked"):
        await driver.ensure_logged_in("blocked")
    assert await driver.ensure_logged_in("healthy") is True
    assert circuit.get_state("pinterest_login:blocked") == CircuitState.OPEN
    driver._acquire_session.assert_awaited_once_with("healthy")


@pytest.mark.asyncio
async def test_open_circuit_defers_without_burning_attempts_while_other_accounts_drain(tmp_path):
    started = time.time()
    report = await run_scenario(
        tmp_path,
        workers=3,
        jobs_per_account=2,
        io_seconds=0.01,
        circuit_blocked_accounts=("benchmark_c",),
        require_first_wave=True,
    )
    assert report["completed_verified"] == 4
    assert report["completed_by_account"] == {"benchmark_a": 2, "benchmark_b": 2}
    assert report["peak_global_concurrency"] == 2
    assert report["dlq_size"] == 0
    assert len(report["deferred_jobs"]) == 2
    assert all(job["attempt"] == 0 for job in report["deferred_jobs"])
    postponed = [job for job in report["deferred_jobs"] if job["next_retry_at"] is not None]
    assert len(postponed) == 1
    assert postponed[0]["next_retry_at"] >= started + 60
    assert report["account_cooldowns"]["benchmark_c"] >= started + 60
    assert all(job["image_preserved"] for job in report["deferred_jobs"])

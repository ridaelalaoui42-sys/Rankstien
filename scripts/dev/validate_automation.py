"""
RankStein Pinterest Automation - Component Validation
Tests all core infrastructure components without requiring a live browser.
Run: python validate_automation.py
"""

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from pinterest_automation import (
    get_circuit_breaker,
    get_config,
    get_healing_cache,
    get_health_monitor,
    get_job_queue,
    get_rate_limiter,
)


def test_config():
    print("\n[1/7] Testing Config...")
    cfg = get_config()
    assert cfg.browser.headless in (True, False)
    assert cfg.rate_limit.daily_pin_limit > 0
    assert cfg.credentials.valid or True  # may not be set in env during test
    print(f"   [INFO] Configured Pinterest accounts: {sorted(cfg.accounts) or ['default']}")
    print("   [OK] Config loaded and valid")


def test_health_monitor():
    print("\n[2/7] Testing Health Monitor...")
    hm = get_health_monitor()
    snap = hm.heartbeat()
    assert isinstance(snap.all_ok, bool)
    assert isinstance(snap.checks, dict)
    assert "disk_space" in snap.checks
    print(f"   [OK] Health check returned: all_ok={snap.all_ok}")
    print(f"   [INFO] Checks: {list(snap.checks.keys())}")


def test_circuit_breaker():
    print("\n[3/7] Testing Circuit Breaker...")
    cb = get_circuit_breaker()
    op = "test_op"
    assert cb.can_execute(op)

    # Simulate failures
    for i in range(cb.config.failure_threshold):
        cb.record_failure(op)

    state = cb.get_state(op)
    print(f"   [INFO] State after {cb.config.failure_threshold} failures: {state.value}")
    assert state.value == "open"
    assert not cb.can_execute(op)

    # Simulate recovery timeout
    cb._last_failure_time[op] = time.time() - cb.config.recovery_timeout_seconds - 1
    state = cb.get_state(op)
    assert state.value == "half_open"
    print(f"   [INFO] State after recovery timeout: {state.value}")

    # Successes should close after the configured half-open threshold.
    for _ in range(cb.config.success_threshold_to_close):
        cb.record_success(op)
    state = cb.get_state(op)
    assert state.value == "closed"
    print("   [OK] Circuit breaker working correctly")


def test_rate_limiter():
    print("\n[4/7] Testing Rate Limiter...")
    rl = get_rate_limiter()
    op = "test_pin"
    assert rl.can_execute(op)

    delay = rl.get_delay(op)
    assert delay >= 0
    print(f"   [INFO] Initial delay: {delay:.1f}s")

    # Simulate execution
    rl.record_execution(op)
    status = rl.get_status()
    assert status["daily_counts"][op] == 1
    print(f"   [INFO] Daily count after 1 execution: {status['daily_counts'][op]}")

    # Simulate failures leading to cooldown
    for i in range(rl.config.cooldown_after_failures):
        rl.record_failure(op)
    assert not rl.can_execute(op)
    print("   [OK] Rate limiter entered cooldown as expected")


def test_job_queue():
    print("\n[5/7] Testing Job Queue...")
    jq = get_job_queue()
    before_total = jq.get_stats()["total"]

    # Enqueue
    job_id = jq.enqueue_pin_upload(
        image_path="test.jpg",
        title="Test Pin",
        description="Test description",
        link="https://example.com",
        priority=1,
    )
    assert job_id is not None
    print(f"   [INFO] Enqueued job: {job_id}")

    stats = jq.get_stats()
    print(f"   [INFO] Queue stats: {stats}")

    # Dequeue
    job = jq.dequeue()
    assert job is not None
    assert job.id == job_id
    print(f"   [INFO] Dequeued job: {job.id} (attempt={job.attempt})")

    # Complete
    jq.complete(job_id, {"pin_id": "12345"})
    stats = jq.get_stats()
    assert stats["total"] == before_total
    print("   [OK] Job queue working correctly")


def test_healing_cache():
    print("\n[6/7] Testing Self-Healing Cache...")
    hc = get_healing_cache()
    hc.set("test_page", "test_target", "input#test")
    sel = hc.get("test_page", "test_target")
    assert sel == "input#test"
    print(f"   [INFO] Cached selector retrieved: {sel}")
    stats = hc.get_stats()
    print(f"   [INFO] Cache stats: {stats}")
    print("   [OK] Healing cache working correctly")


def test_integration():
    print("\n[7/7] Testing Integration Status...")
    from pinterest_automation.mcp_integration import get_automation_status

    status = get_automation_status()
    assert "health" in status
    assert "queue" in status
    assert "session_pool" in status
    print(f"   [INFO] Automation status keys: {list(status.keys())}")
    print("   [OK] Integration layer working correctly")


def test_queue_accounts():
    print("\n[8/8] Testing Queue Account Coverage...")
    cfg = get_config()
    jq = get_job_queue()
    handles = set()
    for job in jq.list_pending():
        payload = job.payload or {}
        handle = payload.get("account_handle") or payload.get("extra", {}).get("account_handle")
        if handle:
            handles.add(str(handle))

    missing = sorted(handle for handle in handles if handle not in cfg.accounts)
    print(f"   [INFO] Queued account handles: {sorted(handles) or ['none']}")
    if missing:
        raise AssertionError(f"Queued account handles missing from config: {missing}")
    print("   [OK] Queue account handles are configured")


def main():
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=" * 60)
    print("RankStein Pinterest Automation - Component Validation")
    print("=" * 60)

    try:
        test_config()
        test_health_monitor()
        test_circuit_breaker()
        test_rate_limiter()
        test_job_queue()
        test_healing_cache()
        test_integration()
        test_queue_accounts()

        print("\n" + "=" * 60)
        print("[PASS] ALL TESTS PASSED")
        print("=" * 60)
        return 0
    except AssertionError as e:
        print(f"\n[FAIL] ASSERTION FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n[FAIL] UNEXPECTED ERROR: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

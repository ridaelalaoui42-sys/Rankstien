import threading
import time

from backend.api import operator_routes as routes
from backend.services.operator_pipeline import (
    _campaign_is_ongoing,
    _finalize_campaign,
    _new_campaign,
    _set_stage,
)


def test_stopped_worker_is_current_during_a_slow_artifact_refresh(monkeypatch):
    lock = threading.Lock()
    lock.acquire()
    cached = {
        "actions": {"production": {"alive": True}},
        "pipeline": {
            "ongoing_campaigns": [
                {
                    "id": "current",
                    "batch_id": "production-test",
                    "overall_state": "active",
                    "queue": {"active": 0},
                },
                {"id": "queued", "batch_id": "older", "overall_state": "active", "queue": {"active": 1}},
            ],
            "ongoing_total": 2,
            "summary": {"ongoing": 2, "active": 2},
        },
    }
    monkeypatch.setattr(routes, "STATUS_CACHE_LOCK", lock)
    monkeypatch.setattr(routes, "_STATUS_CACHE", (time.monotonic() - 100, cached))
    monkeypatch.setattr(
        routes,
        "_load_processes",
        lambda: {
            "production": {"command": ["python", "--batch-id", "production-test"], "stop_requested": True}
        },
    )
    monkeypatch.setattr(
        routes, "_process_status", lambda data: {k: {**v, "alive": False} for k, v in data.items()}
    )
    monkeypatch.setattr(
        routes, "_action_snapshots", lambda _: {"production": {"alive": False, "state": "stopped"}}
    )
    monkeypatch.setattr(
        routes,
        "_latest_production_batch",
        lambda: {"batch_id": "production-test", "state": "running", "domains": {}},
    )
    try:
        result = routes._cached_status_payload()
    finally:
        lock.release()
    assert result["actions"]["production"]["state"] == "stopped"
    assert result["production_batch"]["state"] == "stopped"
    assert [row["id"] for row in result["pipeline"]["ongoing_campaigns"]] == ["queued"]
    assert result["pipeline"]["summary"]["active"] == 1
    assert cached["actions"]["production"]["alive"] is True


def test_failed_article_does_not_show_a_running_writer():
    now = time.time()
    campaign = _new_campaign(
        domain="recetadolce",
        keyword="tarta de coco",
        title="Tarta",
        slug="tarta-coco",
        updated_at=now,
        run_id="failed-run",
    )
    campaign["run_status"] = "failed"
    campaign["roadmap_status"] = "Failed"
    _set_stage(campaign, "article_write", "running", "Writing", now)
    _set_stage(campaign, "hero_image", "failed", "Hero generation failed", now)
    _finalize_campaign(campaign, now=now)
    assert campaign["overall_state"] == "attention"
    assert _campaign_is_ongoing(campaign) is False
    assert (
        next(s for s in campaign["stages"] if s["key"] == "article_write")["metrics"]["interrupted"] is True
    )

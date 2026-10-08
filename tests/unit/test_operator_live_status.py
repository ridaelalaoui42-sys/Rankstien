import threading
import time

import pytest

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


@pytest.mark.parametrize("genial_keywords", [["tarta de queso saludable"], []])
@pytest.mark.parametrize("cached_research", [True, False])
def test_live_status_replaces_cached_research_after_keyword_reservation(
    monkeypatch, genial_keywords, cached_research
):
    lock = threading.Lock()
    lock.acquire()
    lanes = (
        [
            {
                "id": f"research-{domain}",
                "domain_handle": domain,
                "batch_id": "production-test",
                "overall_state": "active",
                "queue": {},
            }
            for domain in ("recetadolce", "recetagenial")
        ]
        if cached_research
        else []
    )
    initial_count = len(lanes) + 1
    article = {"id": "current-article", "keyword": "galletas de avena coco", "queue": {"active": 0}}
    cached = {
        "pipeline": {
            "campaigns": [*lanes, article],
            "ongoing_campaigns": [*lanes, article],
            "research_lanes": lanes,
            "total_campaigns": initial_count,
            "ongoing_total": initial_count,
            "summary": {"ongoing": initial_count, "active": initial_count},
        }
    }
    batch = {
        "batch_id": "production-test",
        "state": "running",
        "domains": {
            "recetadolce": {"target": 10, "verified": 1, "running_keywords": ["galletas de avena coco"]},
            "recetagenial": {"target": 10, "verified": 0, "running_keywords": genial_keywords},
        },
    }
    monkeypatch.setattr(routes, "STATUS_CACHE_LOCK", lock)
    monkeypatch.setattr(routes, "_STATUS_CACHE", (time.monotonic() - 100, cached))
    monkeypatch.setattr(routes, "_load_processes", lambda: {})
    monkeypatch.setattr(routes, "_process_status", lambda _: {})
    monkeypatch.setattr(
        routes,
        "_action_snapshots",
        lambda _: {
            "production": {"alive": True, "stage": "Researching and writing articles", "updated_at": 123}
        },
    )
    monkeypatch.setattr(routes, "_latest_production_batch", lambda: batch)
    try:
        first = routes._cached_status_payload()
        second = routes._cached_status_payload()
    finally:
        lock.release()

    expected_research = [] if genial_keywords else ["research-recetagenial"]
    for result in (first, second):
        assert result["production_batch"]["domains"]["recetadolce"]["running_keywords"] == [
            "galletas de avena coco"
        ]
        pipeline = result["pipeline"]
        assert [row["id"] for row in pipeline["research_lanes"]] == expected_research
        assert [row["id"] for row in pipeline["ongoing_campaigns"]] == [*expected_research, "current-article"]
        assert [row["id"] for row in pipeline["campaigns"]] == [*expected_research, "current-article"]
        assert pipeline["ongoing_total"] == pipeline["summary"]["ongoing"] == 1 + len(expected_research)
        assert pipeline["total_campaigns"] == pipeline["summary"]["active"] == 1 + len(expected_research)
    assert cached["pipeline"]["research_lanes"] == lanes
    assert cached["pipeline"]["ongoing_total"] == cached["pipeline"]["summary"]["active"] == initial_count

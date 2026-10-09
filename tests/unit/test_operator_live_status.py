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


def test_batch_display_separates_latest_produced_keywords_from_failed_attempts():
    import copy

    batch = {
        "failed_total": 5,
        "domains": {
            "recetadolce": {
                "failed": 5,
                "articles": [
                    {"keyword": "tarta de coco", "state": "failed"},
                    {"keyword": "tarta de coco", "state": "needs verification"},
                    {"keyword": "tarta de limón", "state": "verified"},
                    {"keyword": "tarta de limon", "state": "needs_verification"},
                    {"keyword": "Tarta de coco", "state": "needs verification"},
                    {"keyword": "galletas", "state": "needs verification"},
                    {"keyword": "galletas", "state": "interrupted"},
                ],
            }
        },
    }
    before = copy.deepcopy(batch)
    displayed = routes._production_batch_presentation(batch)
    assert displayed["presentation_counts"] == {
        "produced": 4,
        "awaiting_verification": 3,
        "failed_attempts": 1,
        "interrupted_attempts": 1,
    }
    assert displayed["domains"]["recetadolce"]["presentation_counts"] == displayed["presentation_counts"]
    assert displayed["failed_total"] == 5
    assert batch == before


def test_waiting_research_lane_is_not_executing_and_counts_do_not_accumulate():
    pipeline = {"ongoing_campaigns": [], "campaigns": [], "summary": {}, "ongoing_total": 0}
    batch = {
        "batch_id": "current",
        "domains": {
            "recetadolce": {
                "target": 10,
                "verified": 1,
                "state": "waiting",
                "running_keywords": [],
                "detail": "No unattempted Pinterest keyword",
            }
        },
    }
    action = {"alive": True, "stage": "Validating Pinterest candidates"}
    for _ in range(2):
        routes._attach_live_research_lanes(pipeline, production_batch=batch, production_action=action)
        lane = pipeline["ongoing_campaigns"][0]
        assert lane["overall_state"] == "waiting"
        assert lane["stages"][0]["state"] == "waiting"
        assert lane["current_detail"] == "No unattempted Pinterest keyword"
        assert pipeline["summary"]["active"] == 0
        assert pipeline["summary"]["waiting"] == pipeline["ongoing_total"] == 1


@pytest.mark.parametrize(
    ("reason", "expected_state", "stage_state", "label"),
    [
        (
            "research_in_progress stage=pinterest_collection deadline_seconds=300",
            "active",
            "running",
            "Pinterest candidate collection",
        ),
        (
            "research_in_progress stage=exact_validation deadline_seconds=600",
            "active",
            "running",
            "Exact Pinterest-phrase demand validation",
        ),
        (
            "research_timeout stage=exact_validation deadline_seconds=600",
            "attention",
            "warning",
            "Exact validation reached its 600s deadline",
        ),
        (
            "research_failed stage=pinterest_collection error_type=RuntimeError",
            "attention",
            "warning",
            "Pinterest candidate collection failed",
        ),
    ],
)
def test_research_reason_reports_actual_work_or_terminal_attention(
    reason, expected_state, stage_state, label
):
    pipeline = {"ongoing_campaigns": [], "campaigns": [], "summary": {}}
    batch = {
        "batch_id": "current",
        "domains": {"recetadolce": {"target": 10, "verified": 0, "state": "waiting", "detail": reason}},
    }
    action = {"alive": True, "stage": "Researching Pinterest candidates"}
    for _ in range(2):
        routes._attach_live_research_lanes(pipeline, production_batch=batch, production_action=action)
        lane = pipeline["ongoing_campaigns"][0]
        assert lane["overall_state"] == expected_state
        assert lane["stages"][0]["state"] == stage_state
        assert lane["current_label"] == label
        assert pipeline["summary"].get(expected_state, 0) == 1
        assert pipeline["summary"].get("active", 0) == int(expected_state == "active")


def test_explicit_research_reason_does_not_require_stale_action_label():
    pipeline = {"ongoing_campaigns": [], "campaigns": [], "summary": {}}
    batch = {
        "batch_id": "current",
        "domains": {
            "recetadolce": {
                "target": 10,
                "state": "waiting",
                "detail": "research_in_progress stage=exact_validation deadline_seconds=600",
            }
        },
    }
    routes._attach_live_research_lanes(
        pipeline, production_batch=batch, production_action={"alive": True, "stage": "Awaiting keyword"}
    )
    assert pipeline["ongoing_campaigns"][0]["overall_state"] == "active"


def test_stopped_worker_preserves_current_campaign_quality_hold(monkeypatch):
    campaign = {
        "id": "held-run",
        "batch_id": "current",
        "overall_state": "attention",
        "quality_hold": True,
        "queue": {"active": 0, "held": 30},
    }
    monkeypatch.setattr(routes, "_load_processes", lambda: {})
    monkeypatch.setattr(routes, "_process_status", lambda _: {})
    monkeypatch.setattr(
        routes, "_action_snapshots", lambda _: {"production": {"alive": False, "state": "stopped"}}
    )
    monkeypatch.setattr(
        routes, "_latest_production_batch", lambda: {"batch_id": "current", "state": "stopped", "domains": {}}
    )
    result = routes._live_runtime_status(
        {"pipeline": {"ongoing_campaigns": [campaign], "ongoing_total": 1, "summary": {"active": 0}}}
    )
    assert result["pipeline"]["ongoing_campaigns"] == [campaign]
    assert result["pipeline"]["ongoing_total"] == 1

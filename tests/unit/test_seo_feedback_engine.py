import json
from types import SimpleNamespace

import pytest

from rankstein.seo_feedback_engine import SEOFeedbackEngine


@pytest.fixture
def engine(tmp_path, monkeypatch):
    instance = SEOFeedbackEngine(tmp_path)
    instance.registry = SimpleNamespace(all=lambda: [SimpleNamespace(handle="recetadolce", domain="recetadolce.com")])
    disconnected = SimpleNamespace(check_connection=lambda: {"ok": False, "status": "NOT_CONFIGURED"})
    instance.gsc = disconnected
    instance.ga4 = disconnected
    instance.pinterest = disconnected
    monkeypatch.delenv("GA4_RECETADOLCE_PROPERTY_ID", raising=False)
    monkeypatch.setattr(instance, "_read_daily_best_keywords", lambda: [])
    return instance


def test_unavailable_metrics_are_not_fabricated(engine):
    report = engine.run_full_feedback_analysis()
    stats = report.summary_stats
    assert stats["total_search_impressions"] is None
    assert stats["total_organic_clicks_90d"] is None
    assert stats["health_score"] is None
    assert stats["ga4_metrics"]["sessions_28d"] is None
    assert not report.gsc_top_queries
    assert not report.avoid_recommendations


def test_successful_zero_is_distinct_from_api_failure(engine):
    calls = []
    engine.gsc = SimpleNamespace(
        check_connection=lambda: {"ok": True, "verified_sites": ["https://recetadolce.com/", "sc-domain:recetadolce.com"]},
        query_search_analytics=lambda site, **kwargs: calls.append(site) or [],
    )
    report = engine.run_full_feedback_analysis()
    assert report.summary_stats["total_search_impressions"] == 0
    assert report.summary_stats["total_organic_clicks_90d"] == 0
    assert set(calls) == {"sc-domain:recetadolce.com"}
    assert report.summary_stats["average_ctr_pct"] is None


def test_query_failure_cannot_become_zero(engine):
    def failed(*args, **kwargs):
        raise RuntimeError("API unavailable")

    engine.gsc = SimpleNamespace(check_connection=lambda: {"ok": True, "verified_sites": ["sc-domain:recetadolce.com"]}, query_search_analytics=failed)
    assert engine.run_full_feedback_analysis().summary_stats["total_search_impressions"] is None


def test_old_fabricated_cache_is_not_loaded(engine):
    engine.reports_dir.mkdir(parents=True)
    (engine.reports_dir / "seo_trend_feedback_report_latest.json").write_text(json.dumps({"summary_stats": {"health_score": 96}}))
    assert engine.load_latest_report() is None


def test_getting_report_does_not_create_directories(engine):
    assert engine.load_latest_report() is None
    assert not engine.reports_dir.exists()

"""Evidence-only SEO reports. Unknown, empty and successful zero are distinct."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from rankstein.domain import DomainRegistry
from rankstein.ga4_connector import GA4Connector
from rankstein.google_trends_connector import GoogleTrendsConnector
from rankstein.gsc_connector import GSCConnector
from rankstein.pinterest_connector import PinterestConnector

logger = logging.getLogger("rankstein.seo_feedback")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_VERSION = 2


@dataclass
class GSCPerformanceRow:
    query: str
    page_url: str
    slug: str
    domain: str
    clicks: int
    impressions: int
    ctr: float
    position: float
    opportunity_type: str
    recommended_action: str


@dataclass
class TrendSignal:
    term: str
    source: str
    velocity_pct: float | None
    search_volume_score: float | None
    seasonality: str
    intent: str


@dataclass
class StrategicRecommendation:
    keyword: str
    cluster: str
    target_domain: str
    status_type: str
    growth_velocity: str
    demand_index: float | None
    competition_level: str
    rationale: str
    action_item: str


@dataclass
class SEOFeedbackReport:
    generated_at: str
    domains: list[str]
    summary_stats: dict[str, Any]
    post_more_recommendations: list[StrategicRecommendation]
    avoid_recommendations: list[StrategicRecommendation]
    remaster_quick_wins: list[StrategicRecommendation]
    gsc_top_queries: list[GSCPerformanceRow]
    google_trends_radar: list[TrendSignal]
    pinterest_trends_radar: list[TrendSignal]
    action_plan_markdown: str


class SEOFeedbackEngine:
    def __init__(self, project_root: Path | None = None) -> None:
        self.root = project_root or PROJECT_ROOT
        self.reports_dir = self.root / "data" / "reports" / "seo_feedback"
        self.registry = DomainRegistry(self.root)
        self.gsc = GSCConnector()
        self.ga4 = GA4Connector()
        self.google_trends = GoogleTrendsConnector(region="ES")
        self.pinterest = PinterestConnector()

    @staticmethod
    def _diagnose(connector) -> dict[str, Any]:
        try:
            return connector.check_connection()
        except Exception as exc:
            return {"ok": False, "status": "ERROR", "error": type(exc).__name__}

    def _gsc_data(self, diagnostics: dict) -> tuple[list[GSCPerformanceRow], dict]:
        now = datetime.now(UTC)
        end = (now - timedelta(days=3)).strftime("%Y-%m-%d")
        rows = []
        metrics = {}
        for domain in self.registry.all():
            # Domain properties cover URL prefixes. Never double-count them.
            properties = [
                site
                for site in diagnostics.get("verified_sites", [])
                if site == f"sc-domain:{domain.domain}" or site.rstrip("/") == f"https://{domain.domain}"
            ]
            site = next(
                (value for value in properties if value.startswith("sc-domain:")),
                properties[0] if properties else None,
            )
            item: dict[str, Any] = {"status": "UNAVAILABLE", "site_url": site}
            metrics[domain.handle] = item
            if not diagnostics.get("ok") or not site:
                continue
            for days in (28, 90):
                start = (now - timedelta(days=days + 2)).strftime("%Y-%m-%d")
                try:
                    totals = self.gsc.query_search_analytics(
                        site,
                        start_date=start,
                        end_date=end,
                        dimensions=["date"],
                        row_limit=5000,
                        raise_on_error=True,
                    )
                    item[f"impressions_{days}d"] = sum(value["impressions"] for value in totals)
                    item[f"clicks_{days}d"] = sum(value["clicks"] for value in totals)
                    item[f"status_{days}d"] = "OBSERVED"
                    item[f"start_{days}d"] = start
                    item["end_date"] = end
                except Exception as exc:
                    item[f"status_{days}d"] = "ERROR"
                    item[f"error_{days}d"] = type(exc).__name__
            item["status"] = (
                "OBSERVED"
                if all(item.get(f"status_{days}d") == "OBSERVED" for days in (28, 90))
                else "PARTIAL"
            )
            try:
                queries = self.gsc.query_search_analytics(site, row_limit=250, raise_on_error=True)
                for query in queries:
                    position = float(query["position"])
                    opportunity = (
                        "striking_distance"
                        if 3 < position <= 15
                        else ("low_ctr_fix" if query["ctr"] < 3 else "stable")
                    )
                    page = query.get("page") or ""
                    rows.append(
                        GSCPerformanceRow(
                            query=query["query"],
                            page_url=page,
                            slug=urlparse(page).path.rstrip("/").split("/")[-1],
                            domain=domain.handle,
                            clicks=query["clicks"],
                            impressions=query["impressions"],
                            ctr=query["ctr"],
                            position=position,
                            opportunity_type=opportunity,
                            recommended_action="Review exact search intent and recipe-backed title; retain verified cooking times.",
                        )
                    )
            except Exception as exc:
                item["query_status"] = "ERROR"
                item["query_error"] = type(exc).__name__
        return sorted(rows, key=lambda row: row.impressions, reverse=True), metrics

    def _ga4_data(self) -> dict[str, Any]:
        per_domain = {}
        channels: dict[str, int] = {}
        for domain in self.registry.all():
            property_id = os.getenv(f"GA4_{domain.handle.upper()}_PROPERTY_ID", "").strip()
            if not property_id:
                per_domain[domain.handle] = {"status": "NOT_CONFIGURED"}
                continue
            try:
                traffic = self.ga4.query_traffic_overview(property_id, days=28)
                per_domain[domain.handle] = {
                    "property_id": property_id,
                    **traffic,
                    "status": "OBSERVED" if traffic else "UNAVAILABLE",
                }
                for name, values in traffic.get("channels", {}).items():
                    channels[name] = channels.get(name, 0) + values.get("sessions", 0)
            except Exception as exc:
                per_domain[domain.handle] = {"status": "ERROR", "error": type(exc).__name__}
        complete = bool(per_domain) and all(value["status"] == "OBSERVED" for value in per_domain.values())
        sessions = sum(value.get("total_sessions", 0) for value in per_domain.values()) if complete else None
        engaged = (
            sum(value.get("total_engaged_sessions", 0) for value in per_domain.values()) if complete else None
        )

        def share(names):
            return (
                round(sum(channels.get(name, 0) for name in names) * 100 / sessions, 1) if sessions else None
            )

        return {
            "status": "OBSERVED" if complete else "UNAVAILABLE",
            "sessions_28d": sessions,
            "active_users_28d": sum(value.get("total_active_users", 0) for value in per_domain.values())
            if complete
            else None,
            "engagement_rate_pct": round(engaged * 100 / sessions, 2) if sessions else None,
            "avg_engagement_time": None,
            "traffic_sources": {
                "pinterest_social_pct": None,
                "social_pct": share(["Organic Social", "Paid Social"]),
                "google_organic_pct": share(["Organic Search"]),
                "direct_and_referral_pct": share(["Direct", "Referral"]),
            },
            "per_domain": per_domain,
        }

    def _read_daily_best_keywords(self) -> list[dict[str, Any]]:
        from rankstein.trend_intelligence import load_qualified_keyword_keys

        items = []
        for domain in self.registry.all():
            keys, _reason = load_qualified_keyword_keys(domain)
            if not keys:
                continue
            try:
                payload = json.loads((domain.root / "daily_best_keywords.json").read_text(encoding="utf-8"))
                items.extend(
                    {**item, "domain": domain.handle}
                    for item in payload.get("items", [])
                    if item.get("qualified") is True
                    and str(item.get("keyword", "")).strip().casefold() in keys
                )
            except (OSError, ValueError, TypeError):
                logger.warning("Qualified keyword report unavailable for %s", domain.handle)
        return items

    def run_full_feedback_analysis(self) -> SEOFeedbackReport:
        gsc_diag = self._diagnose(self.gsc)
        ga4_diag = self._diagnose(self.ga4)
        pinterest_diag = self._diagnose(self.pinterest)
        queries, per_domain = self._gsc_data(gsc_diag)
        ga4_metrics = self._ga4_data()
        items = self._read_daily_best_keywords()
        google = [
            TrendSignal(
                item["keyword"],
                "Qualified Google demand proxy",
                None,
                item.get("search_demand_score"),
                "Not measured",
                "Recipe",
            )
            for item in items[:10]
        ]
        pinterest = [
            TrendSignal(
                item["keyword"],
                "Observed Pinterest keyword",
                None,
                item.get("pinterest_score"),
                "Not measured",
                "Recipe",
            )
            for item in items
            if item.get("pinterest_origin") is True
        ][:10]
        recommendations = [
            StrategicRecommendation(
                item["keyword"],
                item.get("cluster") or "General",
                item["domain"],
                "POST_MORE",
                "Not measured",
                None,
                "Not measured",
                "Fresh qualified keyword evidence; demand is a proxy, not monthly search volume or growth.",
                "Revalidate source evidence and delivery capacity before production.",
            )
            for item in items[:10]
            if item.get("pinterest_origin") is True
        ]
        quick_wins = [
            StrategicRecommendation(
                row.query,
                "Existing recipe",
                row.domain,
                "REMASTER_QUICK_WIN",
                "Not measured",
                None,
                "Not measured",
                f"Observed position {row.position} with {row.impressions} impressions.",
                "Audit the existing recipe and campaign before creating new assets.",
            )
            for row in queries
            if row.opportunity_type == "striking_distance"
        ]
        summary: dict[str, Any] = {
            "report_version": REPORT_VERSION,
            "metric_provenance": "live_connector_results_only",
            "per_domain_gsc": per_domain,
            "ga4_metrics": ga4_metrics,
            "connectors_status": {
                "gsc": gsc_diag,
                "ga4": ga4_diag,
                "pinterest": pinterest_diag,
                "google_trends": {
                    "ok": bool(google),
                    "status": "QUALIFIED_CACHE" if google else "NO_FRESH_EVIDENCE",
                },
            },
            "health_score": None,
            "average_serp_position": None,
            "average_ctr_pct": None,
            "striking_distance_keywords": len(quick_wins),
            "post_more_count": len(recommendations),
            "avoid_topics_count": 0,
            "remaster_opportunities_count": len(quick_wins),
            "monitored_domains": [domain.handle for domain in self.registry.all()],
        }
        for days in (28, 90):
            complete = bool(per_domain) and all(
                value.get(f"status_{days}d") == "OBSERVED" for value in per_domain.values()
            )
            suffix = "" if days == 28 else "_90d"
            summary[f"total_search_impressions{suffix}"] = (
                sum(value[f"impressions_{days}d"] for value in per_domain.values()) if complete else None
            )
            summary[f"total_organic_clicks{suffix}"] = (
                sum(value[f"clicks_{days}d"] for value in per_domain.values()) if complete else None
            )
        impressions = summary["total_search_impressions"]
        if impressions:
            summary["average_ctr_pct"] = round(summary["total_organic_clicks"] * 100 / impressions, 2)
        query_impressions = sum(row.impressions for row in queries)
        if query_impressions:
            summary["average_serp_position"] = round(
                sum(row.position * row.impressions for row in queries) / query_impressions, 1
            )
        report = SEOFeedbackReport(
            datetime.now(UTC).isoformat(),
            summary["monitored_domains"],
            summary,
            recommendations,
            [],
            quick_wins,
            queries,
            google,
            pinterest,
            "",
        )
        report.action_plan_markdown = self._render_markdown_report(report)
        self._persist_report(report)
        return report

    @staticmethod
    def _render_markdown_report(report: SEOFeedbackReport) -> str:
        lines = [
            "# SEO Feedback",
            "",
            f"Collected: {report.generated_at}",
            "",
            "Unknown values mean unavailable evidence, not zero traffic.",
            "",
            "| Metric | Value |",
            "| --- | --- |",
        ]
        for key in (
            "total_search_impressions",
            "total_organic_clicks",
            "total_search_impressions_90d",
            "total_organic_clicks_90d",
            "average_ctr_pct",
            "average_serp_position",
        ):
            value = report.summary_stats.get(key)
            lines.append(f"| {key} | {value if value is not None else 'Unavailable'} |")
        lines.extend(["", "## Recommendations", ""])
        lines.extend(
            f"- {item.target_domain}: {item.keyword}. {item.rationale}"
            for item in report.post_more_recommendations + report.remaster_quick_wins
        )
        return "\n".join(lines) + "\n"

    def _persist_report(self, report: SEOFeedbackReport) -> None:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        for suffix, content in (
            ("json", json.dumps(asdict(report), ensure_ascii=False, indent=2)),
            ("md", report.action_plan_markdown),
        ):
            target = self.reports_dir / f"seo_trend_feedback_report_latest.{suffix}"
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.reports_dir, delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(content)
            try:
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)

    def load_latest_report(self) -> dict[str, Any] | None:
        try:
            report = json.loads(
                (self.reports_dir / "seo_trend_feedback_report_latest.json").read_text(encoding="utf-8")
            )
            return report if report.get("summary_stats", {}).get("report_version") == REPORT_VERSION else None
        except (OSError, ValueError, TypeError):
            return None

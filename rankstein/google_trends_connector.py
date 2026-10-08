"""Live Google Trends Data Connector for RankStein domains.

Ingests real Google search volume velocity, seasonal breakout curves, and
rising related queries for Spain (ES) using pytrends, Google Trends RSS, and
Google Autocomplete APIs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests
from defusedxml import ElementTree as ET

logger = logging.getLogger("rankstein.google_trends")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@dataclass
class TrendSignal:
    query: str
    velocity: str
    interest_index: int
    is_rising: bool
    source: str


class GoogleTrendsConnector:
    """Connects to Google Trends live feeds and interest calculation services."""

    def __init__(self, region: str = "ES", language: str = "es-ES") -> None:
        self.region = region
        self.language = language

    def fetch_live_trending_topics(self, limit: int = 25) -> list[dict[str, Any]]:
        """Fetch real-time daily trending topics in Spain from Google Trends RSS."""
        url = "https://trends.google.com/trending/rss"
        items = []
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                params={"geo": self.region},
                timeout=15,
            )
            if resp.ok:
                root = ET.fromstring(resp.content)
                for item in root.findall(".//item"):
                    title_elem = item.find("title")
                    approx_traffic = item.find("{https://trends.google.com/trending/rss}approx_traffic")
                    pub_date = item.find("pubDate")

                    title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
                    traffic = (
                        approx_traffic.text.strip()
                        if approx_traffic is not None and approx_traffic.text
                        else "N/A"
                    )
                    date = pub_date.text.strip() if pub_date is not None and pub_date.text else ""

                    if title:
                        items.append(
                            {
                                "query": title,
                                "approx_traffic": traffic,
                                "published_at": date,
                                "region": self.region,
                                "source": "Google Trends RSS",
                            }
                        )
                        if len(items) >= limit:
                            break
        except Exception as exc:
            logger.warning("Failed to fetch Google Trends RSS: %s", exc)

        return items

    def get_keyword_interest(self, keywords: list[str], timeframe: str = "today 3-m") -> dict[str, Any]:
        """Fetch real 0-100 search interest index over time using pytrends."""
        if not keywords:
            return {}

        results = {}
        try:
            from pytrends.request import TrendReq

            # Chunk into groups of 5 (pytrends limit)
            for i in range(0, min(len(keywords), 10), 5):
                batch = keywords[i : i + 5]
                pytrend = TrendReq(hl=self.language, tz=0, timeout=(10, 25))
                pytrend.build_payload(kw_list=batch, geo=self.region, timeframe=timeframe)
                df = pytrend.interest_over_time()

                if df is not None and not df.empty:
                    for kw in batch:
                        if kw in df.columns:
                            series = df[kw].tolist()
                            recent_avg = sum(series[-4:]) / max(1, len(series[-4:]))
                            earlier_avg = sum(series[:4]) / max(1, len(series[:4]))
                            velocity_pct = (
                                round(((recent_avg - earlier_avg) / max(1, earlier_avg)) * 100, 1)
                                if earlier_avg > 0
                                else 0.0
                            )

                            results[kw] = {
                                "current_interest": int(series[-1]) if series else 0,
                                "peak_interest": int(max(series)) if series else 0,
                                "recent_avg_interest": round(recent_avg, 1),
                                "growth_velocity_pct": f"+{velocity_pct}%"
                                if velocity_pct >= 0
                                else f"{velocity_pct}%",
                                "timeline_points": len(series),
                                "data_source": "pytrends (Google Trends)",
                            }
        except Exception as exc:
            logger.warning("pytrends interest calculation failed: %s", exc)

        return results

    def fetch_live_autocomplete_suggestions(self, seed: str, limit: int = 10) -> list[str]:
        """Fetch live Google autocomplete search queries for high-intent culinary topics."""
        try:
            resp = requests.get(
                "https://suggestqueries.google.com/complete/search",
                headers={"User-Agent": USER_AGENT},
                params={"client": "firefox", "hl": "es", "q": seed},
                timeout=10,
            )
            if resp.ok:
                data = resp.json()
                if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
                    return data[1][:limit]
        except Exception as exc:
            logger.debug("Autocomplete failed for %s: %s", seed, exc)
        return []

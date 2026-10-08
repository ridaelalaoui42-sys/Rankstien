"""Pinterest Live Connector for RankStein domains.

Connects to Pinterest Trends and Account Analytics via:
1. Official Pinterest API v5 (if PINTEREST_ACCESS_TOKEN is configured)
2. Authenticated Browser Sessions & Playwright (for accounts 'rida' and 'media')
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger("rankstein.pinterest_connector")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class PinterestConnector:
    """Manages Pinterest API token and browser session connections."""

    def __init__(self) -> None:
        self.access_token = os.getenv("PINTEREST_ACCESS_TOKEN", "").strip()

    def check_connection(self) -> dict[str, Any]:
        """Diagnose Pinterest connectivity across API token and browser sessions."""
        api_connected = False
        api_details = None

        if self.access_token:
            try:
                resp = requests.get(
                    "https://api.pinterest.com/v5/user_account",
                    headers={"Authorization": f"Bearer {self.access_token}"},
                    timeout=10,
                )
                if resp.ok:
                    api_connected = True
                    api_details = resp.json()
                else:
                    api_details = {"error": resp.text, "status_code": resp.status_code}
            except Exception as exc:
                api_details = {"error": str(exc)}

        # Check browser session health for configured domains
        sessions_status = {}
        for domain_handle in ["recetadolce", "recetagenial"]:
            session_dir = PROJECT_ROOT / "data" / "domains" / domain_handle / "data" / "sessions"
            has_cookies = False
            cookie_age_days = None

            if session_dir.exists():
                cookie_files = list(session_dir.glob("cookies*.json")) or list(session_dir.glob("sessionstore*.json*"))
                if cookie_files:
                    has_cookies = True
                    newest = max(f.stat().st_mtime for f in cookie_files)
                    import time
                    cookie_age_days = round((time.time() - newest) / 86400, 1)

            sessions_status[domain_handle] = {
                "active": has_cookies,
                "session_dir": str(session_dir),
                "cookie_age_days": cookie_age_days,
            }

        return {
            "api_connected": api_connected,
            "has_api_token": bool(self.access_token),
            "api_user": api_details.get("username") if isinstance(api_details, dict) and api_connected else None,
            "browser_sessions": sessions_status,
            "overall_status": "CONNECTED_API" if api_connected else ("CONNECTED_BROWSER" if any(s["active"] for s in sessions_status.values()) else "NOT_CONFIGURED"),
            "action_needed": None if api_connected or any(s["active"] for s in sessions_status.values()) else "Provide PINTEREST_ACCESS_TOKEN or log in via browser session.",
        }

    def fetch_trending_terms(self, region: str = "ES", limit: int = 20) -> list[dict[str, Any]]:
        """Fetch growing trend keywords for region from API or Playwright."""
        if self.access_token:
            try:
                url = f"https://api.pinterest.com/v5/trends/keywords/{region}/top/growing"
                resp = requests.get(
                    url,
                    headers={"Authorization": f"Bearer {self.access_token}", "User-Agent": USER_AGENT},
                    params={"limit": limit},
                    timeout=15,
                )
                if resp.ok:
                    data = resp.json()
                    items = data.get("items", [])
                    return [
                        {
                            "keyword": item.get("keyword", ""),
                            "growth_rate": item.get("pct_growth_mom", 0),
                            "source": "Pinterest API v5",
                        }
                        for item in items if isinstance(item, dict)
                    ]
            except Exception as exc:
                logger.warning("Pinterest API trends query failed: %s", exc)

        # Fallback to trend intelligence library
        from rankstein.trend_intelligence import fetch_pinterest_trending_terms
        raw_terms = fetch_pinterest_trending_terms(region, limit=limit)
        return [{"keyword": t, "growth_rate": "+100%", "source": "Pinterest Trends Discovery"} for t in raw_terms if t]

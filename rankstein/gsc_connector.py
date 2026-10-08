"""Google Search Console (GSC) API Connector for RankStein domains.

Uses a Google Cloud Service Account JSON key to fetch real Search Console
performance data (impressions, clicks, CTR, and SERP positions) for verified
domains (e.g. https://recetadolce.com and https://recetagenial.com).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger("rankstein.gsc")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_KEY_PATH = PROJECT_ROOT / "config" / "gsc_service_account.json"


class GSCConnector:
    """Manages authentication and queries against Google Search Console API v3."""

    def __init__(self, key_path: str | Path | None = None) -> None:
        raw_path = key_path or os.getenv("GSC_SERVICE_ACCOUNT_JSON") or DEFAULT_KEY_PATH
        self.key_path = Path(raw_path) if raw_path else None
        if self.key_path and not self.key_path.is_absolute():
            self.key_path = PROJECT_ROOT / self.key_path

    @property
    def is_configured(self) -> bool:
        return self.key_path is not None and self.key_path.is_file()

    def get_service_account_email(self) -> str | None:
        if not self.is_configured or not self.key_path:
            return None
        try:
            with open(self.key_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("client_email")
        except Exception:
            return None

    def get_project_id(self) -> str | None:
        if not self.is_configured or not self.key_path:
            return None
        try:
            with open(self.key_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("project_id")
        except Exception:
            return None

    def get_access_token(self) -> str | None:
        """Obtain a short-lived OAuth2 bearer token from the service account."""
        if not self.is_configured or not self.key_path:
            return None
        try:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account

            scopes = ["https://www.googleapis.com/auth/webmasters.readonly"]
            creds = service_account.Credentials.from_service_account_file(
                str(self.key_path), scopes=scopes
            )
            creds.refresh(Request())
            return creds.token
        except Exception as exc:
            logger.error("Failed to generate GSC bearer token: %s", exc)
            return None

    def check_connection(self) -> dict[str, Any]:
        """Diagnose connection status, API enablement, and property access permissions."""
        if not self.is_configured:
            return {
                "status": "NOT_CONFIGURED",
                "ok": False,
                "email": None,
                "project_id": None,
                "message": "Service account JSON key not found at config/gsc_service_account.json.",
                "action_needed": "Provide a Google Cloud Service Account JSON key.",
            }

        email = self.get_service_account_email()
        project_id = self.get_project_id()

        token = self.get_access_token()
        if not token:
            return {
                "status": "AUTH_ERROR",
                "ok": False,
                "email": email,
                "project_id": project_id,
                "message": "Unable to exchange JWT for access token with oauth2.googleapis.com.",
                "action_needed": "Verify key integrity and clock synchronization.",
            }

        # Query sites endpoint to test API enablement and list authorized properties
        try:
            resp = requests.get(
                "https://www.googleapis.com/webmasters/v3/sites",
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            if resp.status_code == 403:
                body = resp.json().get("error", {})
                message = body.get("message", "")
                if "has not been used" in message or "disabled" in message:
                    return {
                        "status": "API_DISABLED",
                        "ok": False,
                        "email": email,
                        "project_id": project_id,
                        "message": "Google Search Console API is disabled in your Google Cloud Project.",
                        "action_needed": f"Enable Search Console API at: https://console.developers.google.com/apis/api/searchconsole.googleapis.com/overview?project={project_id}",
                    }
                return {
                    "status": "PERMISSION_DENIED",
                    "ok": False,
                    "email": email,
                    "project_id": project_id,
                    "message": f"Service account lacks Search Console permissions: {message}",
                    "action_needed": f"Add {email} to Search Console properties under Settings -> Users & Permissions.",
                }

            if not resp.ok:
                return {
                    "status": f"HTTP_{resp.status_code}",
                    "ok": False,
                    "email": email,
                    "project_id": project_id,
                    "message": resp.text,
                    "action_needed": "Inspect response and retry.",
                }

            payload = resp.json()
            site_entries = payload.get("siteEntry", [])
            verified_sites = [s.get("siteUrl") for s in site_entries if s.get("siteUrl")]

            return {
                "status": "CONNECTED",
                "ok": True,
                "email": email,
                "project_id": project_id,
                "verified_sites": verified_sites,
                "message": f"Successfully connected! Verified access to {len(verified_sites)} property(ies).",
                "action_needed": None if verified_sites else f"Add {email} to Search Console properties.",
            }

        except Exception as exc:
            return {
                "status": "CONNECTION_FAILED",
                "ok": False,
                "email": email,
                "project_id": project_id,
                "message": str(exc),
                "action_needed": "Check network connectivity.",
            }

    def query_search_analytics(
        self,
        site_url: str,
        start_date: str | None = None,
        end_date: str | None = None,
        dimensions: list[str] | None = None,
        row_limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Query Search Analytics metrics for a given verified siteUrl."""
        token = self.get_access_token()
        if not token:
            return []

        # Default date range: past 28 days (ending 3 days ago for data maturity)
        now = datetime.now(UTC)
        if not end_date:
            end_date = (now - timedelta(days=3)).strftime("%Y-%m-%d")
        if not start_date:
            start_date = (now - timedelta(days=31)).strftime("%Y-%m-%d")

        dimensions = dimensions or ["query", "page"]

        # Encoded siteUrl in URL path
        encoded_site = urllib.parse.quote(site_url, safe="")
        endpoint = f"https://www.googleapis.com/webmasters/v3/sites/{encoded_site}/searchAnalytics/query"

        payload = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": dimensions,
            "rowLimit": min(row_limit, 5000),
            "aggregationType": "auto",
        }

        try:
            resp = requests.post(
                endpoint,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
                timeout=30,
            )
            if not resp.ok:
                logger.warning("GSC query failed for %s: %s %s", site_url, resp.status_code, resp.text)
                return []

            data = resp.json()
            rows = data.get("rows", [])
            results = []
            for r in rows:
                keys = r.get("keys", [])
                query_val = keys[0] if len(keys) > 0 else ""
                page_val = keys[1] if len(keys) > 1 else ""
                results.append(
                    {
                        "query": query_val,
                        "page": page_val,
                        "clicks": int(r.get("clicks", 0)),
                        "impressions": int(r.get("impressions", 0)),
                        "ctr": round(float(r.get("ctr", 0.0)) * 100, 2),
                        "position": round(float(r.get("position", 0.0)), 1),
                    }
                )
            return results

        except Exception as exc:
            logger.error("Error querying GSC search analytics for %s: %s", site_url, exc)
            return []

    def get_top_queries(self, site_url: str, days: int = 28, row_limit: int = 25) -> list[dict[str, Any]]:
        """Convenience method to retrieve top performing queries sorted by impressions."""
        now = datetime.now(UTC)
        end_date = (now - timedelta(days=3)).strftime("%Y-%m-%d")
        start_date = (now - timedelta(days=days + 3)).strftime("%Y-%m-%d")
        rows = self.query_search_analytics(
            site_url=site_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=["query", "page"],
            row_limit=row_limit,
        )
        return sorted(rows, key=lambda x: x.get("impressions", 0), reverse=True)

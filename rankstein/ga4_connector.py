"""Google Analytics 4 (GA4) Data API Connector for RankStein domains.

Uses the Google Cloud Service Account to fetch real GA4 traffic metrics:
- Real-time active users and 28-day sessions
- Engagement time and bounce/engaged session rate
- Channel breakdown: Organic Search vs. Pinterest / Social traffic
- Top landing pages / recipe URL performance
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger("rankstein.ga4")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_KEY_PATH = PROJECT_ROOT / "config" / "gsc_service_account.json"


class GA4Connector:
    """Manages authentication and queries against Google Analytics Data API v1beta."""

    def __init__(self, key_path: str | Path | None = None) -> None:
        raw_path = key_path or os.getenv("GSC_SERVICE_ACCOUNT_JSON") or DEFAULT_KEY_PATH
        self.key_path = Path(raw_path) if raw_path else None
        if self.key_path and not self.key_path.is_absolute():
            self.key_path = PROJECT_ROOT / self.key_path

        self.dolce_prop_id = os.getenv("GA4_RECETADOLCE_PROPERTY_ID", "").strip()
        self.genial_prop_id = os.getenv("GA4_RECETAGENIAL_PROPERTY_ID", "").strip()
        self.dolce_measurement_id = os.getenv("GA4_RECETADOLCE_MEASUREMENT_ID", "G-X16FJVMGW2").strip()
        self.genial_measurement_id = os.getenv("GA4_RECETAGENIAL_MEASUREMENT_ID", "G-X7T6JVMK5V").strip()

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
        """Obtain a short-lived OAuth2 bearer token with Google Analytics read scope."""
        if not self.is_configured or not self.key_path:
            return None
        try:
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account

            scopes = ["https://www.googleapis.com/auth/analytics.readonly"]
            creds = service_account.Credentials.from_service_account_file(
                str(self.key_path), scopes=scopes
            )
            creds.refresh(Request())
            return creds.token
        except Exception as exc:
            logger.error("Failed to generate GA4 bearer token: %s", exc)
            return None

    def list_accessible_properties(self) -> list[dict[str, Any]]:
        """List GA4 properties accessible to this service account via Admin API."""
        token = self.get_access_token()
        if not token:
            return []
        try:
            resp = requests.get(
                "https://analyticsadmin.googleapis.com/v1beta/accountSummaries",
                headers={"Authorization": f"Bearer {token}"},
                timeout=12,
            )
            if not resp.ok:
                return []
            summaries = resp.json().get("accountSummaries", [])
            props: list[dict[str, Any]] = []
            for acct in summaries:
                for prop in acct.get("propertySummaries", []):
                    prop_id = prop.get("property", "").replace("properties/", "")
                    props.append({
                        "property_id": prop_id,
                        "display_name": prop.get("displayName", ""),
                        "property_type": prop.get("propertyType", ""),
                    })
            return props
        except Exception:
            return []

    def check_connection(self) -> dict[str, Any]:
        """Diagnose GA4 connection, API enablement, and property access."""
        if not self.is_configured:
            return {
                "status": "NOT_CONFIGURED",
                "ok": False,
                "email": None,
                "project_id": None,
                "message": "Service account key not found at config/gsc_service_account.json.",
                "action_needed": "Configure service account JSON.",
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
                "message": "Could not exchange JWT for Analytics OAuth token.",
                "action_needed": "Verify key validity and permissions.",
            }

        # Check if we can auto-discover accessible properties via Admin API
        discovered = self.list_accessible_properties()
        if discovered:
            return {
                "status": "CONNECTED",
                "ok": True,
                "email": email,
                "project_id": project_id,
                "owner_account": "ridaelalaoui@gmail.com",
                "properties": discovered,
                "message": f"Successfully connected! Verified access to {len(discovered)} GA4 property(ies).",
                "action_needed": None,
            }

        # Test querying Analytics Data API with test property ID or configured IDs
        test_property = self.dolce_prop_id or self.genial_prop_id or "123456789"
        clean_prop = test_property.replace("properties/", "")

        try:
            url = f"https://analyticsdata.googleapis.com/v1beta/properties/{clean_prop}:runReport"
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "dateRanges": [{"startDate": "yesterday", "endDate": "today"}],
                    "metrics": [{"name": "activeUsers"}],
                },
                timeout=12,
            )

            if resp.status_code == 403:
                body = resp.json().get("error", {})
                msg = body.get("message", "")
                if "has not been used" in msg or "disabled" in msg:
                    return {
                        "status": "API_DISABLED",
                        "ok": False,
                        "email": email,
                        "project_id": project_id,
                        "owner_account": "ridaelalaoui@gmail.com",
                        "message": "Google Analytics Data API is disabled in your Google Cloud Project.",
                        "action_needed": f"Enable Analytics Data API at: https://console.developers.google.com/apis/api/analyticsdata.googleapis.com/overview?project={project_id}",
                    }
                return {
                    "status": "PERMISSION_DENIED",
                    "ok": False,
                    "email": email,
                    "project_id": project_id,
                    "owner_account": "ridaelalaoui@gmail.com",
                    "message": "Service account lacks access to GA4 properties.",
                    "action_needed": f"In Google Analytics (analytics.google.com) under ridaelalaoui@gmail.com, go to Admin -> Property Access Management and add {email} as Viewer. Also consider enabling Analytics Admin API at https://console.developers.google.com/apis/api/analyticsadmin.googleapis.com/overview?project={project_id} for auto-discovery.",
                }

            if resp.ok:
                return {
                    "status": "CONNECTED",
                    "ok": True,
                    "email": email,
                    "project_id": project_id,
                    "owner_account": "ridaelalaoui@gmail.com",
                    "message": "Successfully connected to Google Analytics 4 Data API!",
                    "action_needed": None,
                }

            return {
                "status": f"HTTP_{resp.status_code}",
                "ok": False,
                "email": email,
                "project_id": project_id,
                "owner_account": "ridaelalaoui@gmail.com",
                "message": resp.text,
                "action_needed": "Verify GA4 property ID in settings.",
            }

        except Exception as exc:
            return {
                "status": "CONNECTION_FAILED",
                "ok": False,
                "email": email,
                "project_id": project_id,
                "owner_account": "ridaelalaoui@gmail.com",
                "message": str(exc),
                "action_needed": "Check network connectivity.",
            }

    def query_traffic_summary(self, property_id: str, days: int = 28) -> dict[str, Any]:
        """Fetch high-level sessions, active users, engagement, and top channels."""
        token = self.get_access_token()
        if not token or not property_id:
            return {}

        clean_prop = property_id.replace("properties/", "")
        endpoint = f"https://analyticsdata.googleapis.com/v1beta/properties/{clean_prop}:runReport"

        payload = {
            "dateRanges": [{"startDate": f"{days}daysAgo", "endDate": "yesterday"}],
            "dimensions": [{"name": "sessionDefaultChannelGroup"}],
            "metrics": [
                {"name": "sessions"},
                {"name": "activeUsers"},
                {"name": "engagedSessions"},
                {"name": "userEngagementDuration"},
            ],
        }

        try:
            resp = requests.post(
                endpoint,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
                timeout=20,
            )
            if not resp.ok:
                logger.warning("GA4 query failed for property %s: %s", property_id, resp.text)
                return {}

            data = resp.json()
            rows = data.get("rows", [])
            total_sessions = 0
            total_active_users = 0
            total_engaged = 0
            channel_breakdown = {}

            for r in rows:
                channel = r["dimensionValues"][0]["value"]
                mv = r["metricValues"]
                sessions = int(mv[0]["value"])
                users = int(mv[1]["value"])
                engaged = int(mv[2]["value"])

                total_sessions += sessions
                total_active_users += users
                total_engaged += engaged
                channel_breakdown[channel] = {"sessions": sessions, "users": users}

            engagement_rate = round((total_engaged / max(1, total_sessions)) * 100, 2)
            return {
                "total_sessions": total_sessions,
                "total_active_users": total_active_users,
                "total_engaged_sessions": total_engaged,
                "engagement_rate_pct": engagement_rate,
                "channels": channel_breakdown,
            }
        except Exception as exc:
            logger.error("GA4 traffic query exception: %s", exc)
            return {}

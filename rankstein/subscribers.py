"""CLI-oriented subscriber management for RankStein.

This module intentionally keeps newsletter/subscriber operations out of the
frontend admin surface. The CLI uses Supabase's REST API with the service-role
key already configured for publishing workflows.
"""

from __future__ import annotations

import csv
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from rankstein.config import get_settings
from rankstein.domain import Domain, get_registry

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DEFAULT_COLUMNS = "id,email,status,source,created_at,updated_at"


class SubscriberError(RuntimeError):
    """Raised when subscriber operations cannot complete."""


@dataclass(frozen=True)
class SupabaseTarget:
    url: str
    service_role_key: str


def _secret_value(value: str | SecretStr) -> str:
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return str(value or "")


def resolve_supabase_target(domain_handle: str | None = None) -> SupabaseTarget:
    """Resolve Supabase credentials from a domain manifest or global settings."""
    if domain_handle:
        domain: Domain = get_registry().get(domain_handle)
        return SupabaseTarget(
            url=domain.supabase_url,
            service_role_key=_secret_value(domain.supabase_service_role_key),
        )

    settings = get_settings()
    return SupabaseTarget(
        url=settings.supabase_url,
        service_role_key=_secret_value(settings.supabase_service_role_key),
    )


class SupabaseSubscribersClient:
    """Small REST client for the ``subscribers`` table."""

    def __init__(
        self,
        target: SupabaseTarget,
        opener: Callable[[urllib.request.Request], Any] | None = None,
    ) -> None:
        self.target = target
        self._opener = opener or urllib.request.urlopen
        self.base_url = target.url.rstrip("/")
        if not self.base_url:
            raise SubscriberError("Supabase URL is not configured")
        if not target.service_role_key:
            raise SubscriberError("Supabase service role key is not configured")

    def _request(
        self,
        method: str,
        path: str,
        payload: dict | list[dict] | None = None,
        prefer: str | None = None,
    ) -> Any:
        body = None
        headers = {
            "apikey": self.target.service_role_key,
            "Authorization": f"Bearer {self.target.service_role_key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(  # noqa: S310 - base_url comes from validated Supabase config.
            f"{self.base_url}/rest/v1/{path.lstrip('/')}",
            data=body,
            headers=headers,
            method=method,
        )

        try:
            with self._opener(request) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SubscriberError(f"Supabase request failed ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise SubscriberError(f"Supabase request failed: {exc.reason}") from exc

        if not raw:
            return None
        return json.loads(raw)

    def list(self, status: str | None = "active", limit: int = 100) -> list[dict]:
        query = {
            "select": DEFAULT_COLUMNS,
            "order": "created_at.desc",
            "limit": str(limit),
        }
        if status:
            query["status"] = f"eq.{status}"
        return self._request("GET", "subscribers?" + urllib.parse.urlencode(query)) or []

    def get_by_email(self, email: str) -> dict | None:
        query = urllib.parse.urlencode(
            {
                "select": DEFAULT_COLUMNS,
                "email": f"eq.{email.lower()}",
                "limit": "1",
            }
        )
        rows = self._request("GET", f"subscribers?{query}") or []
        return rows[0] if rows else None

    def add(self, email: str, source: str = "cli") -> dict:
        email = normalize_email(email)
        existing = self.get_by_email(email)
        if existing:
            if existing.get("status") == "active":
                return existing
            return self.update_status(email, "active")

        rows = self._request(
            "POST",
            "subscribers",
            [{"email": email, "status": "active", "source": source}],
            prefer="return=representation",
        )
        return rows[0] if rows else {"email": email, "status": "active", "source": source}

    def update_status(self, email: str, status: str) -> dict:
        email = normalize_email(email)
        rows = self._request(
            "PATCH",
            "subscribers?" + urllib.parse.urlencode({"email": f"eq.{email}"}),
            {"status": status},
            prefer="return=representation",
        )
        if not rows:
            raise SubscriberError(f"No subscriber found for {email}")
        return rows[0]


def normalize_email(email: str) -> str:
    normalized = str(email or "").strip().lower()
    if not EMAIL_RE.match(normalized):
        raise SubscriberError(f"Invalid email address: {email!r}")
    return normalized


def export_subscribers_csv(rows: list[dict], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["email", "status", "source", "created_at", "updated_at", "id"]
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return output_path

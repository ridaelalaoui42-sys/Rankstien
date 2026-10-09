"""Read-only production admission checks, separate from queue execution."""

from __future__ import annotations

import math
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from rankstein import log_manager
from rankstein.config import PROJECT_ROOT
from rankstein.domain import Domain

PINS_PER_CAMPAIGN = 31


def campaign_admission(
    domains: list[Domain], *, campaigns_per_domain: int = 1, queue_path: Path | None = None
) -> dict[str, Any]:
    """Do not start new campaigns faster than their configured delivery budget.

    This deliberately counts future retries too. Moving a job into tomorrow's
    schedule must not hide a large backlog from today's admission decision.
    """
    resources = log_manager.check_resource_budget()
    issues = list(resources["issues"])
    path = queue_path or Path(
        os.environ.get("PINTEREST_QUEUE_DB_FILE") or PROJECT_ROOT / "data" / "queue" / "jobs.db"
    )
    counts: dict[str, int] = {}
    try:
        max_days = float(os.environ.get("RANKSTEIN_MAX_QUEUE_DAYS", "3"))
        if not math.isfinite(max_days) or max_days <= 0 or campaigns_per_domain < 1:
            raise ValueError("Invalid campaign admission limits")
        if path.exists():
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)) as conn:
                rows = conn.execute(
                    "SELECT COALESCE(json_extract(payload_json, '$.domain_handle'), "
                    "json_extract(payload_json, '$.extra.domain_handle'), ''), COUNT(*) "
                    "FROM jobs WHERE type = 'pin_upload' AND status IN ('pending','retry','processing') "
                    "GROUP BY 1"
                ).fetchall()
            counts = {str(handle): int(count) for handle, count in rows}
            if counts.get("", 0):
                issues.append("Active queue contains jobs without domain identity")
    except (OSError, sqlite3.Error, ValueError):
        max_days = None
        issues.append("Queue admission could not be verified")

    delivery = {}
    for domain in domains:
        budget = domain.daily_pin_budget
        backlog = counts.get(domain.handle, 0)
        proposed = PINS_PER_CAMPAIGN * campaigns_per_domain
        projected_days = (backlog + proposed) / budget if budget > 0 else None
        allowed = max_days is not None and projected_days is not None and projected_days <= max_days
        delivery[domain.handle] = {
            "pending_pins": backlog,
            "new_pins": proposed,
            "daily_pin_budget": budget,
            "projected_days": round(projected_days, 2) if projected_days is not None else None,
            "max_days": max_days,
            "ok": allowed,
        }
        if not allowed:
            issues.append(f"{domain.handle}: new campaign exceeds the delivery backlog limit")
    return {"ok": not issues, "resources": resources, "delivery": delivery, "issues": issues}

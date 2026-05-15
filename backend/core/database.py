"""RankStein — Async Database Layer
Complete async SQLite layer with full CRUD for all entities.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from backend.core.config import get_settings

# Whitelists for dynamic update fields — prevents SQL injection via field names
_DOMAIN_FIELDS = {
    "name",
    "url",
    "niche",
    "status",
    "eeat_threshold",
    "schedule_cron",
    "auto_pinterest",
    "updated_at",
}
_PROJECT_FIELDS = {
    "name",
    "mode",
    "status",
    "total_missions",
    "total_words",
    "avg_eeat",
    "total_credits_spent",
    "updated_at",
}
_CAMPAIGN_FIELDS = {
    "keyword",
    "domain",
    "niche",
    "mode",
    "status",
    "eeat_score",
    "word_count",
    "context_blob",
    "completed_at",
    "updated_at",
}
_PIN_FIELDS = {
    "pinterest_pin_id",
    "pin_url",
    "board_id",
    "title",
    "description",
    "image_url",
    "status",
    "impressions",
    "saves",
    "clicks",
}
_INTEGRATION_FIELDS = {"type", "credentials_json", "status", "last_tested_at", "updated_at"}


def _safe_fields(fields: dict, whitelist: set) -> dict:
    """Filter fields to only whitelisted column names."""
    return {k: v for k, v in fields.items() if k in whitelist}


_db: aiosqlite.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS domains (
    id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, url TEXT NOT NULL,
    niche TEXT NOT NULL DEFAULT 'General', status TEXT NOT NULL DEFAULT 'active',
    eeat_threshold INTEGER NOT NULL DEFAULT 75, schedule_cron TEXT DEFAULT '',
    auto_pinterest INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY, domain_id TEXT REFERENCES domains(id), name TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'supervised', status TEXT NOT NULL DEFAULT 'active',
    total_missions INTEGER NOT NULL DEFAULT 0, total_words INTEGER NOT NULL DEFAULT 0,
    avg_eeat REAL NOT NULL DEFAULT 0, total_credits_spent INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id),
    keyword TEXT NOT NULL, domain TEXT NOT NULL DEFAULT '', niche TEXT NOT NULL DEFAULT 'General',
    mode TEXT NOT NULL DEFAULT 'supervised', status TEXT NOT NULL DEFAULT 'pending',
    eeat_score INTEGER, word_count INTEGER, context_blob TEXT DEFAULT '',
    created_at TEXT NOT NULL, completed_at TEXT
);
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id),
    agent_role TEXT NOT NULL, output_text TEXT, tokens_used INTEGER DEFAULT 0,
    latency_ms INTEGER DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS credits (
    user_id TEXT PRIMARY KEY DEFAULT 'default', balance INTEGER NOT NULL DEFAULT 500,
    tier TEXT NOT NULL DEFAULT 'free', total_consumed INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS publish_log (
    id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id),
    cms_type TEXT NOT NULL, target_url TEXT, status TEXT NOT NULL DEFAULT 'pending',
    response_data TEXT, published_at TEXT
);
CREATE TABLE IF NOT EXISTS pins (
    id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id),
    pinterest_pin_id TEXT, pin_url TEXT, board_id TEXT, title TEXT, description TEXT,
    image_url TEXT, status TEXT NOT NULL DEFAULT 'pending', impressions INTEGER DEFAULT 0,
    saves INTEGER DEFAULT 0, clicks INTEGER DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS integrations (
    id TEXT PRIMARY KEY, domain_id TEXT REFERENCES domains(id),
    type TEXT NOT NULL, credentials_json TEXT DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'disconnected', last_tested_at TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS competitor_scan (
    id TEXT PRIMARY KEY, domain_id TEXT REFERENCES domains(id),
    competitor_domain TEXT NOT NULL, authority_score INTEGER DEFAULT 0,
    traffic_estimate INTEGER DEFAULT 0, top_keywords TEXT DEFAULT '[]',
    gap_analysis TEXT DEFAULT '{}', scanned_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS keyword_map (
    id TEXT PRIMARY KEY, domain_id TEXT REFERENCES domains(id),
    keyword TEXT NOT NULL, search_volume INTEGER DEFAULT 0,
    difficulty INTEGER DEFAULT 0, intent TEXT DEFAULT 'informational',
    current_rank INTEGER DEFAULT 0, target_url TEXT DEFAULT '', mapped_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS seo_audit (
    id TEXT PRIMARY KEY, domain_id TEXT REFERENCES domains(id),
    audit_type TEXT NOT NULL, score INTEGER DEFAULT 0,
    issues_json TEXT DEFAULT '[]', recommendations_json TEXT DEFAULT '[]',
    audited_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_campaigns_project ON campaigns(project_id);
CREATE INDEX IF NOT EXISTS idx_campaigns_status ON campaigns(status);
CREATE INDEX IF NOT EXISTS idx_artifacts_campaign ON artifacts(campaign_id);
CREATE INDEX IF NOT EXISTS idx_projects_domain ON projects(domain_id);
CREATE INDEX IF NOT EXISTS idx_integrations_domain ON integrations(domain_id);
CREATE INDEX IF NOT EXISTS idx_competitor_domain ON competitor_scan(domain_id);
CREATE INDEX IF NOT EXISTS idx_keyword_domain ON keyword_map(domain_id);
CREATE INDEX IF NOT EXISTS idx_audit_domain ON seo_audit(domain_id);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _id() -> str:
    return uuid.uuid4().hex[:16]


def _row_to_dict(row: aiosqlite.Row) -> dict:
    return dict(row) if row else {}


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        settings = get_settings()
        db_path = settings.db_file
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _db = await aiosqlite.connect(str(db_path))
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
        await _db.execute("PRAGMA busy_timeout=5000")
        await _db.executescript(_SCHEMA)
        await _db.commit()
        row = await _db.execute_fetchall("SELECT 1 FROM credits WHERE user_id='default'")
        if not row:
            await _db.execute(
                "INSERT INTO credits (user_id, balance, tier, total_consumed, updated_at) VALUES ('default', 500, 'free', 0, ?)",
                (_now(),),
            )
            await _db.commit()
    return _db


async def close_db() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None


# ── Domains ──────────────────────────────────────────


async def create_domain(name: str, url: str, niche: str = "General", schedule: str = "") -> dict:
    db = await get_db()
    did = _id()
    now = _now()
    await _db.execute(
        "INSERT INTO domains (id, name, url, niche, status, schedule_cron, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
        (did, name, url, niche, "active", schedule, now, now),
    )
    await _db.commit()
    return {"id": did, "name": name, "url": url, "niche": niche, "status": "active", "created_at": now}


async def list_domains(status: str | None = None) -> list[dict]:
    db = await get_db()
    q = (
        "SELECT * FROM domains WHERE status=? ORDER BY created_at DESC"
        if status
        else "SELECT * FROM domains ORDER BY created_at DESC"
    )
    args = (status,) if status else ()
    rows = await _db.execute_fetchall(q, args)
    return [_row_to_dict(r) for r in rows]


async def get_domain(domain_id: str) -> dict | None:
    db = await get_db()
    rows = await _db.execute_fetchall("SELECT * FROM domains WHERE id=?", (domain_id,))
    return _row_to_dict(rows[0]) if rows else None


async def get_domain_by_name(name: str) -> dict | None:
    db = await get_db()
    rows = await _db.execute_fetchall("SELECT * FROM domains WHERE name=?", (name,))
    return _row_to_dict(rows[0]) if rows else None


async def update_domain(domain_id: str, **fields: Any) -> None:
    db = await get_db()
    fields["updated_at"] = _now()
    fields = _safe_fields(fields, _DOMAIN_FIELDS)
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    await _db.execute(f"UPDATE domains SET {sets} WHERE id=?", list(fields.values()) + [domain_id])
    await _db.commit()


async def delete_domain(domain_id: str) -> None:
    db = await get_db()
    await _db.execute("UPDATE domains SET status='archived', updated_at=? WHERE id=?", (_now(), domain_id))
    await _db.commit()


# ── Projects ─────────────────────────────────────────


async def create_project(domain_id: str, name: str, mode: str = "supervised") -> dict:
    db = await get_db()
    pid = _id()
    now = _now()
    await _db.execute(
        "INSERT INTO projects (id, domain_id, name, mode, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (pid, domain_id, name, mode, "active", now, now),
    )
    await _db.commit()
    return {
        "id": pid,
        "domain_id": domain_id,
        "name": name,
        "mode": mode,
        "status": "active",
        "created_at": now,
    }


async def list_projects(domain_id: str | None = None) -> list[dict]:
    db = await get_db()
    if domain_id:
        rows = await _db.execute_fetchall(
            "SELECT * FROM projects WHERE domain_id=? ORDER BY created_at DESC", (domain_id,)
        )
    else:
        rows = await _db.execute_fetchall("SELECT * FROM projects ORDER BY created_at DESC")
    return [_row_to_dict(r) for r in rows]


async def get_project(project_id: str) -> dict | None:
    db = await get_db()
    rows = await _db.execute_fetchall("SELECT * FROM projects WHERE id=?", (project_id,))
    return _row_to_dict(rows[0]) if rows else None


async def update_project(project_id: str, **fields: Any) -> None:
    db = await get_db()
    fields["updated_at"] = _now()
    fields = _safe_fields(fields, _PROJECT_FIELDS)
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    await _db.execute(f"UPDATE projects SET {sets} WHERE id=?", list(fields.values()) + [project_id])
    await _db.commit()


# ── Campaigns ────────────────────────────────────────


async def create_campaign(
    project_id: str, keyword: str, domain: str = "", niche: str = "General", mode: str = "supervised"
) -> dict:
    db = await get_db()
    cid = _id()
    now = _now()
    await _db.execute(
        "INSERT INTO campaigns (id, project_id, keyword, domain, niche, mode, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (cid, project_id, keyword, domain, niche, mode, "active", now),
    )
    await _db.commit()
    return {
        "id": cid,
        "project_id": project_id,
        "keyword": keyword,
        "domain": domain,
        "niche": niche,
        "status": "active",
        "created_at": now,
    }


async def update_campaign(campaign_id: str, **fields: Any) -> None:
    db = await get_db()
    fields = _safe_fields(fields, _CAMPAIGN_FIELDS)
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    await _db.execute(f"UPDATE campaigns SET {sets} WHERE id=?", list(fields.values()) + [campaign_id])
    await _db.commit()


async def get_campaign(campaign_id: str) -> dict | None:
    db = await get_db()
    rows = await _db.execute_fetchall("SELECT * FROM campaigns WHERE id=?", (campaign_id,))
    return _row_to_dict(rows[0]) if rows else None


async def list_campaigns(status: str | None = None, limit: int = 50) -> list[dict]:
    db = await get_db()
    if status:
        rows = await _db.execute_fetchall(
            "SELECT * FROM campaigns WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit)
        )
    else:
        rows = await _db.execute_fetchall(
            "SELECT * FROM campaigns ORDER BY created_at DESC LIMIT ?", (limit,)
        )
    return [_row_to_dict(r) for r in rows]


async def get_campaigns_for_project(project_id: str, limit: int = 50) -> list[dict]:
    db = await get_db()
    rows = await _db.execute_fetchall(
        "SELECT * FROM campaigns WHERE project_id=? ORDER BY created_at DESC LIMIT ?", (project_id, limit)
    )
    return [_row_to_dict(r) for r in rows]


# ── Artifacts ────────────────────────────────────────


async def save_artifact(
    campaign_id: str, agent_role: str, output_text: str, tokens_used: int = 0, latency_ms: int = 0
) -> str:
    db = await get_db()
    aid = _id()
    await _db.execute(
        "INSERT INTO artifacts (id, campaign_id, agent_role, output_text, tokens_used, latency_ms, created_at) VALUES (?,?,?,?,?,?,?)",
        (aid, campaign_id, agent_role, output_text, tokens_used, latency_ms, _now()),
    )
    await _db.commit()
    return aid


async def get_artifacts(campaign_id: str) -> list[dict]:
    db = await get_db()
    rows = await _db.execute_fetchall(
        "SELECT * FROM artifacts WHERE campaign_id=? ORDER BY created_at", (campaign_id,)
    )
    return [_row_to_dict(r) for r in rows]


# ── Credits ──────────────────────────────────────────


async def get_credits(user_id: str = "default") -> dict:
    db = await get_db()
    rows = await _db.execute_fetchall("SELECT * FROM credits WHERE user_id=?", (user_id,))
    return _row_to_dict(rows[0]) if rows else {"balance": 0, "tier": "free", "total_consumed": 0}


async def deduct_credits(amount: int, user_id: str = "default") -> dict:
    db = await get_db()
    current = await get_credits(user_id)
    new_balance = max(0, current["balance"] - amount)
    new_total = current["total_consumed"] + amount
    await _db.execute(
        "UPDATE credits SET balance=?, total_consumed=?, updated_at=? WHERE user_id=?",
        (new_balance, new_total, _now(), user_id),
    )
    await _db.commit()
    return {"balance": new_balance, "consumed": amount, "total_consumed": new_total}


async def add_credits(amount: int, user_id: str = "default") -> dict:
    db = await get_db()
    current = await get_credits(user_id)
    new_balance = current["balance"] + amount
    await _db.execute(
        "UPDATE credits SET balance=?, updated_at=? WHERE user_id=?", (new_balance, _now(), user_id)
    )
    await _db.commit()
    return {"balance": new_balance}


# ── Publish Log ──────────────────────────────────────


async def log_publish(
    campaign_id: str, cms_type: str, target_url: str = "", status: str = "pending", response_data: str = ""
) -> str:
    db = await get_db()
    pid = _id()
    await _db.execute(
        "INSERT INTO publish_log (id, campaign_id, cms_type, target_url, status, response_data, published_at) VALUES (?,?,?,?,?,?,?)",
        (pid, campaign_id, cms_type, target_url, status, response_data, _now()),
    )
    await _db.commit()
    return pid


# ── Pins ─────────────────────────────────────────────


async def save_pin(campaign_id: str, **fields: Any) -> str:
    db = await get_db()
    pid = _id()
    fields.setdefault("status", "pending")
    fields = _safe_fields(fields, _PIN_FIELDS)
    cols = "id, campaign_id, created_at, " + ", ".join(fields.keys())
    placeholders = "?, ?, ?, " + ", ".join("?" for _ in fields)
    vals = [pid, campaign_id, _now()] + list(fields.values())
    await _db.execute(f"INSERT INTO pins ({cols}) VALUES ({placeholders})", vals)
    await _db.commit()
    return pid


async def get_pins(campaign_id: str) -> list[dict]:
    db = await get_db()
    rows = await _db.execute_fetchall(
        "SELECT * FROM pins WHERE campaign_id=? ORDER BY created_at", (campaign_id,)
    )
    return [_row_to_dict(r) for r in rows]


# ── Integrations ─────────────────────────────────────


async def save_integration(
    domain_id: str, integration_type: str, credentials: dict | None = None, status: str = "disconnected"
) -> dict:
    db = await get_db()
    iid = _id()
    now = _now()
    creds_json = json.dumps(credentials or {})
    await _db.execute(
        "INSERT INTO integrations (id, domain_id, type, credentials_json, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (iid, domain_id, integration_type, creds_json, status, now, now),
    )
    await _db.commit()
    return {"id": iid, "domain_id": domain_id, "type": integration_type, "status": status}


async def get_integration(integration_id: str) -> dict | None:
    db = await get_db()
    rows = await _db.execute_fetchall("SELECT * FROM integrations WHERE id=?", (integration_id,))
    if not rows:
        return None
    row = _row_to_dict(rows[0])
    row["credentials"] = json.loads(row.get("credentials_json", "{}"))
    return row


async def list_integrations(domain_id: str | None = None) -> list[dict]:
    db = await get_db()
    if domain_id:
        rows = await _db.execute_fetchall(
            "SELECT * FROM integrations WHERE domain_id=? ORDER BY type", (domain_id,)
        )
    else:
        rows = await _db.execute_fetchall("SELECT * FROM integrations ORDER BY type")
    result = []
    for r in rows:
        d = _row_to_dict(r)
        credentials = json.loads(d.get("credentials_json", "{}"))
        d["credentials_configured"] = bool(credentials)
        d.pop("credentials_json", None)
        result.append(d)
    return result


async def update_integration(integration_id: str, **fields: Any) -> None:
    db = await get_db()
    fields["updated_at"] = _now()
    if "credentials" in fields and isinstance(fields["credentials"], dict):
        fields["credentials_json"] = json.dumps(fields.pop("credentials"))
    fields = _safe_fields(fields, _INTEGRATION_FIELDS)
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    await _db.execute(f"UPDATE integrations SET {sets} WHERE id=?", list(fields.values()) + [integration_id])
    await _db.commit()


async def delete_integration(integration_id: str) -> None:
    db = await get_db()
    await _db.execute("DELETE FROM integrations WHERE id=?", (integration_id,))
    await _db.commit()


# ── Competitor Scan ──────────────────────────────────


async def save_competitor_scan(
    domain_id: str,
    competitor_domain: str,
    authority_score: int = 0,
    traffic_estimate: int = 0,
    top_keywords: list | None = None,
    gap_analysis: dict | None = None,
) -> str:
    db = await get_db()
    sid = _id()
    await _db.execute(
        "INSERT INTO competitor_scan (id, domain_id, competitor_domain, authority_score, traffic_estimate, top_keywords, gap_analysis, scanned_at) VALUES (?,?,?,?,?,?,?,?)",
        (
            sid,
            domain_id,
            competitor_domain,
            authority_score,
            traffic_estimate,
            json.dumps(top_keywords or []),
            json.dumps(gap_analysis or {}),
            _now(),
        ),
    )
    await _db.commit()
    return sid


async def list_competitors(domain_id: str) -> list[dict]:
    db = await get_db()
    rows = await _db.execute_fetchall(
        "SELECT * FROM competitor_scan WHERE domain_id=? ORDER BY authority_score DESC", (domain_id,)
    )
    result = []
    for r in rows:
        d = _row_to_dict(r)
        d["top_keywords"] = json.loads(d.get("top_keywords", "[]"))
        d["gap_analysis"] = json.loads(d.get("gap_analysis", "{}"))
        result.append(d)
    return result


# ── Keyword Map ──────────────────────────────────────


async def save_keyword_map(
    domain_id: str,
    keyword: str,
    search_volume: int = 0,
    difficulty: int = 0,
    intent: str = "informational",
    current_rank: int = 0,
    target_url: str = "",
) -> str:
    db = await get_db()
    kid = _id()
    await _db.execute(
        "INSERT INTO keyword_map (id, domain_id, keyword, search_volume, difficulty, intent, current_rank, target_url, mapped_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (kid, domain_id, keyword, search_volume, difficulty, intent, current_rank, target_url, _now()),
    )
    await _db.commit()
    return kid


async def list_keywords(domain_id: str) -> list[dict]:
    db = await get_db()
    rows = await _db.execute_fetchall(
        "SELECT * FROM keyword_map WHERE domain_id=? ORDER BY search_volume DESC", (domain_id,)
    )
    return [_row_to_dict(r) for r in rows]


# ── SEO Audit ────────────────────────────────────────


async def save_seo_audit(
    domain_id: str,
    audit_type: str,
    score: int = 0,
    issues: list | None = None,
    recommendations: list | None = None,
) -> str:
    db = await get_db()
    aid = _id()
    await _db.execute(
        "INSERT INTO seo_audit (id, domain_id, audit_type, score, issues_json, recommendations_json, audited_at) VALUES (?,?,?,?,?,?,?)",
        (
            aid,
            domain_id,
            audit_type,
            score,
            json.dumps(issues or []),
            json.dumps(recommendations or []),
            _now(),
        ),
    )
    await _db.commit()
    return aid


async def list_audits(domain_id: str) -> list[dict]:
    db = await get_db()
    rows = await _db.execute_fetchall(
        "SELECT * FROM seo_audit WHERE domain_id=? ORDER BY audited_at DESC", (domain_id,)
    )
    result = []
    for r in rows:
        d = _row_to_dict(r)
        d["issues"] = json.loads(d.get("issues_json", "[]"))
        d["recommendations"] = json.loads(d.get("recommendations_json", "[]"))
        result.append(d)
    return result

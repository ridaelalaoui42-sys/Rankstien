"""Production startup orchestration for the multidomain RankStein system."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.core import database as db
from backend.services.memory_service import memory as agent_memory
from pinterest_automation import get_job_queue
from rankstein.domain import Domain, get_registry, reload_registry
from rankstein.keyword_roadmap import (
    clean_keyword_roadmap,
    keyword_counts,
    read_keyword_rows,
)
from rankstein.trend_intelligence import refresh_domain_trend_lists

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMPLETED_STATUSES = {"approved", "complete", "completed", "published", "live"}

logger = logging.getLogger("rankstein.startup")


@dataclass
class StartupOptions:
    domains: list[str] | None = None
    keywords_per_domain: int = 3
    workers_per_domain: int = 1
    launch: bool = True
    json_output: bool = False
    refresh_trends: bool = False
    trend_limit_per_domain: int = 10


async def build_startup_plan(options: StartupOptions) -> dict[str, Any]:
    """Audit, clean roadmaps, seed campaign records, and optionally launch workers."""
    reload_registry()
    domains = _resolve_domains(options.domains)
    await db.get_db()
    memory_health = await asyncio.to_thread(agent_memory.health)

    campaigns = await db.list_campaigns(limit=10000)
    campaign_index = _campaign_index(campaigns)
    completed_by_domain = _completed_keywords_by_domain(campaigns)

    domain_reports = []
    created_campaigns = []
    skipped_existing = []
    trend_report: dict[str, Any] | None = None
    pre_trend_cleanup = []

    if options.refresh_trends:
        for domain in domains:
            title = f"{domain.display_name} Keyword Roadmap"
            completed_keywords = completed_by_domain.get(domain.domain, set()) | completed_by_domain.get(
                domain.handle, set()
            )
            pre_trend_cleanup.append(
                {
                    "domain": domain.handle,
                    "cleanup": clean_keyword_roadmap(domain.keywords_file, title, completed_keywords),
                }
            )
        trend_report = await asyncio.to_thread(
            refresh_domain_trend_lists,
            domains,
            limit_per_domain=options.trend_limit_per_domain,
            append_to_roadmap=True,
        )

    for domain in domains:
        db_refs = await _ensure_domain_project(domain)
        memory_hits = await asyncio.to_thread(
            agent_memory.search,
            (
                f"RankStein startup lessons for domain {domain.handle}, "
                f"niche {domain.niche}, account {domain.handle}"
            ),
            5,
        )
        title = f"{domain.display_name} Keyword Roadmap"
        completed_keywords = completed_by_domain.get(domain.domain, set()) | completed_by_domain.get(
            domain.handle, set()
        )
        cleanup = clean_keyword_roadmap(domain.keywords_file, title, completed_keywords)
        rows = read_keyword_rows(domain.keywords_file)
        pending = [row for row in rows if row.status.lower() == "pending"]

        seeded = 0
        for row in pending[: options.keywords_per_domain]:
            key = (domain.domain.casefold(), row.keyword.casefold())
            handle_key = (domain.handle.casefold(), row.keyword.casefold())
            if key in campaign_index or handle_key in campaign_index:
                skipped_existing.append({"domain": domain.handle, "keyword": row.keyword})
                continue
            campaign = await db.create_campaign(
                db_refs["project"]["id"], row.keyword, domain.domain, domain.niche, "autonomous"
            )
            campaign_index[key] = campaign
            created_campaigns.append(campaign)
            seeded += 1

        queue = get_job_queue(domain_handle=domain.handle)
        domain_reports.append(
            {
                "handle": domain.handle,
                "domain": domain.domain,
                "niche": domain.niche,
                "db_domain_id": db_refs["domain"]["id"],
                "project_id": db_refs["project"]["id"],
                "keywords_file": str(domain.keywords_file),
                "keyword_counts": keyword_counts(read_keyword_rows(domain.keywords_file)),
                "cleanup": cleanup,
                "pending_selected": min(len(pending), options.keywords_per_domain),
                "campaigns_seeded": seeded,
                "memory_hits": len(memory_hits),
                "queue": queue.get_stats(),
                "credentials": {
                    "pinterest": bool(
                        domain.pinterest_email and domain.pinterest_password.get_secret_value()
                    ),
                    "supabase": bool(
                        domain.supabase_url and domain.supabase_service_role_key.get_secret_value()
                    ),
                },
            }
        )

    await asyncio.to_thread(
        agent_memory.log_event,
        "rankstein_startup",
        "Startup audited domains, cleaned roadmaps, seeded campaigns, and prepared workers.",
        {
            "domains": len(domains),
            "campaigns_seeded": len(created_campaigns),
            "launch": options.launch,
            "agentmemory_ok": bool(memory_health.get("ok")),
        },
    )

    launched = []
    if options.launch:
        # Launch a single worker process covering ALL domains simultaneously
        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "backend" / "scripts" / "turbo_articles.py"),
            "--all-domains",
            "--workers",
            str(options.workers_per_domain),
            "--limit",
            str(options.keywords_per_domain),
        ]
        proc = await asyncio.create_subprocess_exec(*cmd, cwd=PROJECT_ROOT)
        launched.append({"domain": "all", "pid": proc.pid, "cmd": cmd})
        logger.info("Launched turbo_articles --all-domains pid=%d", proc.pid)


    return {
        "brief": {
            "domains": len(domains),
            "campaigns_total": len(campaigns),
            "campaigns_seeded": len(created_campaigns),
            "skipped_existing": len(skipped_existing),
            "launch": options.launch,
            "agentmemory_ok": bool(memory_health.get("ok")),
            "trends_refreshed": bool(trend_report),
        },
        "domains": domain_reports,
        "trend_report": trend_report,
        "pre_trend_cleanup": pre_trend_cleanup,
        "created_campaigns": created_campaigns,
        "skipped_existing": skipped_existing,
        "launched": launched,
    }


def run_startup(options: StartupOptions) -> dict[str, Any]:
    return asyncio.run(_run_startup_and_close(options))


async def _run_startup_and_close(options: StartupOptions) -> dict[str, Any]:
    try:
        return await build_startup_plan(options)
    finally:
        await db.close_db()


def print_startup_report(report: dict[str, Any], *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        return

    brief = report["brief"]
    print("\nRankStein Startup Brief")
    print("=" * 24)
    print(f"Domains audited:       {brief['domains']}")
    print(f"DB campaigns:          {brief['campaigns_total']}")
    print(f"Campaigns seeded:      {brief['campaigns_seeded']}")
    print(f"Existing skipped:      {brief['skipped_existing']}")
    print(f"Trends refreshed:      {'yes' if brief.get('trends_refreshed') else 'no'}")
    print(f"AgentMemory:           {'ok' if brief['agentmemory_ok'] else 'unavailable'}")
    print(f"Workers launched:      {len(report['launched'])}")

    print("\nDomain Readiness")
    for item in report["domains"]:
        counts = item["keyword_counts"]
        creds = item["credentials"]
        cleanup = item["cleanup"]
        print(
            f"- {item['handle']} ({item['domain']}): "
            f"pending={counts.get('Pending', 0)}, live={counts.get('Live', 0)}, "
            f"seeded={item['campaigns_seeded']}, queue={item['queue']['total']}, "
            f"memory={item['memory_hits']}, "
            f"pinterest={'ok' if creds['pinterest'] else 'missing'}, "
            f"supabase={'ok' if creds['supabase'] else 'missing'}"
        )
        if cleanup["duplicates_removed"] or cleanup["reset_in_progress"] or cleanup["marked_live_from_db"]:
            print(
                "  cleanup: "
                f"duplicates={cleanup['duplicates_removed']}, "
                f"reset={cleanup['reset_in_progress']}, "
                f"db_live={cleanup['marked_live_from_db']}"
            )

    if report["launched"]:
        print("\nLaunched Workers")
        for item in report["launched"]:
            print(f"- {item['domain']}: pid={item['pid']}")


def _resolve_domains(handles: list[str] | None) -> list[Domain]:
    registry = get_registry()
    if not handles:
        return registry.all()
    return [registry.get(handle) for handle in handles]


async def _ensure_domain_project(domain: Domain) -> dict[str, dict]:
    domains = await db.list_domains()
    domain_url = _normalized_url(domain.domain)
    domain_names = {domain.display_name.casefold(), domain.handle.casefold(), domain.domain.casefold()}
    domain_row = next(
        (
            item
            for item in domains
            if str(item.get("name") or "").casefold() in domain_names
            or _normalized_url(str(item.get("url") or "")) == domain_url
        ),
        None,
    )
    if domain_row is None:
        domain_row = await db.create_domain(domain.display_name, f"https://{domain.domain}", domain.niche)

    projects = await db.list_projects(domain_row["id"])
    project_names = {
        f"{domain.display_name} Autonomous".casefold(),
        f"{domain.handle} autonomous".casefold(),
        "autonomous",
    }
    project_row = next(
        (
            item
            for item in projects
            if str(item.get("mode") or "").casefold() == "autonomous"
            or str(item.get("name") or "").casefold() in project_names
        ),
        None,
    )
    if project_row is None:
        project_row = await db.create_project(
            domain_row["id"], f"{domain.display_name} Autonomous", "autonomous"
        )

    return {"domain": domain_row, "project": project_row}


def _normalized_url(value: str) -> str:
    value = value.strip().casefold().rstrip("/")
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    return value


def _campaign_index(campaigns: list[dict]) -> dict[tuple[str, str], dict]:
    index = {}
    for campaign in campaigns:
        domain = str(campaign.get("domain") or "").casefold()
        keyword = str(campaign.get("keyword") or "").casefold()
        if domain and keyword:
            index[(domain, keyword)] = campaign
    return index


def _completed_keywords_by_domain(campaigns: list[dict]) -> dict[str, set[str]]:
    done: dict[str, set[str]] = {}
    for campaign in campaigns:
        status = str(campaign.get("status") or "").casefold()
        if status not in COMPLETED_STATUSES:
            continue
        domain = str(campaign.get("domain") or "").casefold()
        keyword = str(campaign.get("keyword") or "")
        if domain and keyword:
            done.setdefault(domain, set()).add(keyword)
    return done

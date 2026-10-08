"""Production startup orchestration for the multidomain RankStein system."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
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
from rankstein.runtime_env import clean_python_env
from rankstein.trend_intelligence import load_qualified_keyword_keys, refresh_domain_trend_lists

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
    research_domains: list[str] = []

    if options.refresh_trends:
        for domain in domains:
            title = f"{domain.display_name} Keyword Roadmap"
            completed_keywords = completed_by_domain.get(domain.domain, set()) | completed_by_domain.get(
                domain.handle, set()
            )
            cleanup = clean_keyword_roadmap(domain.keywords_file, title, completed_keywords)
            pre_trend_cleanup.append({"domain": domain.handle, "cleanup": cleanup})
            if int(cleanup["counts"].get("Pending", 0)) == 0:
                research_domains.append(domain.handle)
        trend_report = await asyncio.to_thread(
            refresh_domain_trend_lists,
            domains,
            limit_per_domain=options.trend_limit_per_domain,
            append_to_roadmap=True,
            candidate_origin_policy="pinterest_required",
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
        eligible_keywords, research_status = load_qualified_keyword_keys(domain)
        pending = [
            row
            for row in rows
            if row.status.lower() == "pending" and row.keyword.strip().casefold() in eligible_keywords
        ]
        unresearched_pending = [
            row
            for row in rows
            if row.status.lower() == "pending" and row.keyword.strip().casefold() not in eligible_keywords
        ]

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
                "keyword_research_status": research_status,
                "qualified_pending": len(pending),
                "unresearched_pending": len(unresearched_pending),
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

    publishable_pending = sum(int(item["qualified_pending"]) for item in domain_reports)
    keywords_discovered = sum(
        int(item.get("roadmap_added", 0)) for item in (trend_report or {}).get("domains", {}).values()
    )
    launched = []
    launch_blocked_reason = ""
    if options.launch and publishable_pending:
        launched.append(
            _launch_article_worker(
                workers_per_domain=options.workers_per_domain,
                keywords_per_domain=options.keywords_per_domain,
            )
        )
    elif options.launch:
        launch_blocked_reason = (
            "No qualified Pending keywords have fresh Pinterest-first research and external demand proof."
        )
        logger.error(launch_blocked_reason)

    return {
        "brief": {
            "domains": len(domains),
            "campaigns_total": len(campaigns),
            "campaigns_seeded": len(created_campaigns),
            "skipped_existing": len(skipped_existing),
            "launch": options.launch,
            "agentmemory_ok": bool(memory_health.get("ok")),
            "trends_refreshed": bool(trend_report),
            "research_triggered": bool(research_domains),
            "research_domains": research_domains,
            "keywords_discovered": keywords_discovered,
            "publishable_pending": publishable_pending,
            "work_ready": publishable_pending > 0,
            "launch_blocked_reason": launch_blocked_reason,
        },
        "domains": domain_reports,
        "trend_report": trend_report,
        "pre_trend_cleanup": pre_trend_cleanup,
        "created_campaigns": created_campaigns,
        "skipped_existing": skipped_existing,
        "launched": launched,
    }


def _launch_article_worker(
    *,
    workers_per_domain: int,
    keywords_per_domain: int,
) -> dict[str, Any]:
    """Launch the continuous article worker independently of the short CLI process."""

    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "backend" / "scripts" / "turbo_articles.py"),
        "--all-domains",
        "--workers",
        str(workers_per_domain),
        "--limit",
        str(keywords_per_domain),
    ]
    log_dir = PROJECT_ROOT / "data" / "logs" / "services"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout = (log_dir / "articles.log").open("ab")
    stderr = (log_dir / "articles_err.log").open("ab")
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | 0x01000000
        )
    kwargs = {
        "cwd": PROJECT_ROOT,
        "env": clean_python_env(),
        "stdin": subprocess.DEVNULL,
        "stdout": stdout,
        "stderr": stderr,
        "creationflags": creationflags,
        "close_fds": True,
    }
    try:
        try:
            proc = subprocess.Popen(cmd, **kwargs)
        except OSError:
            if os.name != "nt" or not creationflags:
                raise
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.Popen(cmd, **kwargs)
    finally:
        stdout.close()
        stderr.close()
    logger.info("Launched detached turbo_articles --all-domains pid=%d", proc.pid)
    return {"domain": "all", "pid": proc.pid, "cmd": cmd, "detached": True}


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
    print(
        "Keyword research:      "
        + (
            f"triggered for {', '.join(brief.get('research_domains', []))}"
            if brief.get("research_triggered")
            else "not required by an empty roadmap"
        )
    )
    print(f"Keywords discovered:   {brief.get('keywords_discovered', 0)}")
    print(f"Publishable pending:    {brief.get('publishable_pending', 0)}")
    print(f"AgentMemory:           {'ok' if brief['agentmemory_ok'] else 'unavailable'}")
    print(f"Workers launched:      {len(report['launched'])}")
    if brief.get("launch_blocked_reason"):
        print(f"Publishing blocked:    {brief['launch_blocked_reason']}")

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

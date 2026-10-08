"""Root CLI for the production RankStein multidomain system.

Key subcommands:
- ``add-domain <domain>`` provisions a new blog manifest and keyword roadmap.
- ``list-domains`` prints the configured domain roster.
- ``show-domain <handle>`` dumps one domain's resolved runtime configuration.
- ``run`` audits DB/domain/keyword/queue state, seeds campaigns, and launches
  domain-aware Gemini workers unless ``--no-launch`` is supplied.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rankstein.domain import get_registry, reload_registry
from rankstein.runtime_env import clean_python_env, sanitize_current_process_env

sanitize_current_process_env()

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _configure_utf8_stdio() -> None:
    """Keep JSON and live provider text printable on Windows terminals."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                continue


# ───────────────────────────────────────────────────────────────────────────
# Subcommand handlers
# ───────────────────────────────────────────────────────────────────────────


def cmd_add_domain(args: argparse.Namespace) -> int:
    # Lazy import — the provisioner imports niche_detector which calls
    # gemini CLI. Don't pay the import cost for unrelated subcommands.
    from rankstein.provisioner import provision_domain

    result = provision_domain(
        args.domain,
        PROJECT_ROOT,
        interactive=not args.non_interactive,
        skip_branding=args.skip_branding,
        keyword_count=args.keywords,
        category_count=args.categories,
        clone_site=args.clone_site,
        template_path=args.template_path,
        projects_root=args.projects_root,
        overwrite_site=args.overwrite_site,
    )

    print("\n" + "=" * 60)
    print(f"Provisioned: {result.domain} → handle '{result.handle}'")
    print(f"  Manifest: {result.manifest_path}")
    print(f"  Niche: {result.niche_info.niche}")
    print(f"  Language: {result.niche_info.language}")
    print(f"  Display: {result.niche_info.display_name}")
    print(f"  Categories ({len(result.categories)}): {result.categories}")
    print(f"  Keywords: {result.keyword_count}")
    if result.fallbacks_used:
        print(f"  ⚠ Fallback used for: {', '.join(result.fallbacks_used)}")
        print(f"    Re-run individual steps with: rankstein regenerate {result.handle} --step <name>")
    if result.branding.get("logo_path"):
        print(f"  Logo: {result.branding['logo_path']}")
    if result.site_project:
        print(f"  Site project: {result.site_project.project_path}")
        print(f"  Site blueprint: {result.site_project.blueprint_path}")
        print(f"  Launch prompt: {result.site_project.launch_prompt_path}")
    print("\nNext steps:")
    for step in result.next_steps:
        print(f"  • {step}")
    print()
    return 0


def cmd_list_domains(_: argparse.Namespace) -> int:
    reload_registry()
    reg = get_registry()
    domains = reg.all()
    if not domains:
        print("No domains configured. Run 'python rankstein.py add-domain <domain>'.")
        return 0
    print(f"Default: {reg.default_handle}\n")
    print(f"{'HANDLE':<24}{'DOMAIN':<32}{'NICHE':<40}{'STATUS'}")
    print(f"{'-' * 24}{'-' * 32}{'-' * 40}{'-' * 12}")
    for d in domains:
        status = "synthesized" if d.is_synthesized else "manifest"
        print(f"{d.handle:<24}{d.domain:<32}{d.niche[:38]:<40}{status}")
    return 0


def cmd_show_domain(args: argparse.Namespace) -> int:
    reload_registry()
    reg = get_registry()
    try:
        d = reg.get(args.handle)
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    info = {
        "handle": d.handle,
        "domain": d.domain,
        "display_name": d.display_name,
        "language": d.language,
        "niche": d.niche,
        "is_synthesized": d.is_synthesized,
        "root": str(d.root),
        "keywords_file": str(d.keywords_file),
        "sessions_dir": str(d.sessions_dir),
        "output_dir": str(d.output_dir),
        "branding_dir": str(d.branding_dir),
        "categories": list(d.categories),
        "boards_default": d.boards_default,
        "primary_color": d.primary_color,
        "accent_color": d.accent_color,
        "brand_name_short": d.brand_name_short,
        "cta_text": d.cta_text,
        "daily_pin_budget": d.daily_pin_budget,
        "pinterest_email": d.pinterest_email or "(not set)",
        "supabase_url": d.supabase_url,
    }
    print(json.dumps(info, indent=2, ensure_ascii=False))
    return 0


def _boot_mcp_servers() -> None:
    """Launch all MCP servers via start_all_mcp.ps1 before the startup plan runs."""
    import subprocess

    mcp_script = PROJECT_ROOT / "scripts" / "dev" / "start_all_mcp.ps1"
    if not mcp_script.exists():
        print(f"[boot] WARNING: {mcp_script} not found — skipping MCP server boot.", file=sys.stderr)
        return

    pwsh = "powershell.exe"
    try:
        result = subprocess.run(
            [
                pwsh,
                "-NonInteractive",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(mcp_script),
                "-NoGemini",  # Don't launch Gemini CLI from here — we're already inside it
            ],
            cwd=str(PROJECT_ROOT),
            timeout=60,  # AgentMemory health-wait is max 20s + buffer
            env=clean_python_env(),
        )
        if result.returncode != 0:
            print(
                f"[boot] WARNING: MCP boot script exited {result.returncode} — continuing anyway.",
                file=sys.stderr,
            )
        else:
            print("[boot] All MCP servers ready.", file=sys.stderr)
    except FileNotFoundError:
        print("[boot] WARNING: powershell.exe not found — skipping MCP server boot.", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print("[boot] WARNING: MCP boot timed out after 60s — continuing anyway.", file=sys.stderr)
    except Exception as e:
        print(f"[boot] WARNING: MCP boot failed: {e} — continuing anyway.", file=sys.stderr)


def cmd_run(args: argparse.Namespace) -> int:
    """Run the production startup sequence for one domain or the full fleet."""
    from rankstein.startup import StartupOptions, print_startup_report, run_startup

    # Boot all MCP servers (agentmemory HTTP + validate stdio servers) before anything else
    _boot_mcp_servers()

    report = run_startup(
        StartupOptions(
            domains=[args.domain] if args.domain else None,
            keywords_per_domain=args.keywords,
            workers_per_domain=args.workers,
            launch=not args.no_launch,
            json_output=args.json,
            refresh_trends=not args.skip_trends,
            trend_limit_per_domain=args.trend_limit,
        )
    )
    print_startup_report(report, as_json=args.json)
    if not args.no_launch and not report["brief"].get("work_ready"):
        return 2
    return 0


def cmd_production_reconcile(args: argparse.Namespace) -> int:
    """Finish one article whose priority primary-pin job completed late."""

    import asyncio

    from rankstein.production_reconcile import (
        ReconciliationError,
        reconcile_production_article,
    )

    try:
        result = asyncio.run(
            reconcile_production_article(
                project_root=PROJECT_ROOT,
                batch_id=args.batch_id,
                domain_handle=args.domain,
                pipeline_run_id=args.pipeline_run_id,
                primary_job_id=args.primary_job_id,
            )
        )
    except ReconciliationError as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "batch_id": args.batch_id,
                    "domain_handle": args.domain,
                    "pipeline_run_id": args.pipeline_run_id,
                    "primary_job_id": args.primary_job_id,
                    "error": str(exc),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_trends(args: argparse.Namespace) -> int:
    """Refresh Pinterest-first, externally validated keyword intelligence."""
    from rankstein.trend_intelligence import refresh_domain_trend_lists

    reload_registry()
    registry = get_registry()
    domains = [registry.get(args.domain)] if args.domain else registry.all()
    report = refresh_domain_trend_lists(
        domains,
        limit_per_domain=args.limit,
        append_to_roadmap=not args.no_roadmap,
        candidate_origin_policy=args.candidate_origin_policy,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0


def cmd_autonomous(args: argparse.Namespace) -> int:
    """Run the self-sustaining autonomous cycle loop."""
    from rankstein.autonomous import AutonomousLoopOptions, run_autonomous_loop

    run_autonomous_loop(
        AutonomousLoopOptions(
            domains=[args.domain] if args.domain else None,
            keywords_per_domain=args.keywords,
            workers_per_domain=args.workers,
            interval_hours=args.interval_hours,
            cycles=args.cycles,
            launch=not args.no_launch,
            refresh_trends=not args.skip_trends,
            trend_limit_per_domain=args.trend_limit,
        )
    )
    return 0


def cmd_launch(args: argparse.Namespace) -> int:
    """Launch and monitor the full RankStein/Odysseus/Pinterest pipeline."""
    from rankstein.launcher import LaunchOptions, print_launch_report, run_launch

    report = run_launch(
        LaunchOptions(
            domains=[args.domain] if args.domain else None,
            keywords_per_domain=args.keywords,
            workers_per_domain=args.workers,
            refresh_trends=not args.skip_trends,
            trend_limit_per_domain=args.trend_limit,
            monitor_seconds=args.monitor_seconds,
            monitor_interval_seconds=args.monitor_interval,
            start_services=not args.no_services,
            start_articles=not args.no_articles,
            start_supervisor=not args.no_supervisor,
            start_frontend=args.frontend,
            skip_odysseus_server=args.skip_odysseus_server,
            skip_validation=args.skip_validation,
            json_output=args.json,
        )
    )
    print_launch_report(report, as_json=args.json)
    if report.get("article_start_blocked"):
        return 2
    return 0


def _subscriber_client(args: argparse.Namespace):
    from rankstein.subscribers import SupabaseSubscribersClient, resolve_supabase_target

    return SupabaseSubscribersClient(resolve_supabase_target(getattr(args, "domain", None)))


# ───────────────────────────────────────────────────────────────────────────
# Keyword cleaning interface
# ───────────────────────────────────────────────────────────────────────────


def _iter_target_domains(handle: str | None):
    reload_registry()
    reg = get_registry()
    if handle:
        return [reg.get(handle)]
    return reg.all()


def cmd_keywords_list(args: argparse.Namespace) -> int:
    from rankstein.keyword_roadmap import keyword_counts, read_keyword_rows

    for domain in _iter_target_domains(args.domain):
        rows = read_keyword_rows(domain.keywords_file)
        counts = keyword_counts(rows)
        print(f"\n[{domain.handle}] {len(rows)} total — {counts}")
        if args.status:
            filtered = [r for r in rows if r.status.casefold() == args.status.casefold()]
            print(f"  {len(filtered)} with status '{args.status}':")
            for r in filtered[: args.limit]:
                print(f"    {r.keyword[:60]:60} | {r.cluster[:20]}")
            if len(filtered) > args.limit:
                print(f"    ... and {len(filtered) - args.limit} more")
    return 0


def cmd_keywords_retry(args: argparse.Namespace) -> int:
    """Reset keywords from a failed/blocked status back to Pending for retry."""
    from rankstein.keyword_roadmap import read_keyword_rows, write_keyword_rows

    source_statuses = {s.casefold() for s in args.from_status.split(",")}
    total_reset = 0
    for domain in _iter_target_domains(args.domain):
        rows = read_keyword_rows(domain.keywords_file)
        reset = 0
        for r in rows:
            if r.status.casefold() in source_statuses:
                r.status = "Pending"
                reset += 1
        if reset:
            title = f"{domain.display_name} Keyword Roadmap"
            write_keyword_rows(domain.keywords_file, title, rows)
        print(f"[{domain.handle}] reset {reset} keywords ({args.from_status}) -> Pending")
        total_reset += reset
    print(f"\nTotal reset for retry: {total_reset}")
    return 0


def cmd_keywords_remove(args: argparse.Namespace) -> int:
    """Permanently remove keywords with the given status from the roadmap."""
    from rankstein.keyword_roadmap import read_keyword_rows, write_keyword_rows

    source_statuses = {s.casefold() for s in args.status.split(",")}
    total_removed = 0
    for domain in _iter_target_domains(args.domain):
        rows = read_keyword_rows(domain.keywords_file)
        before = len(rows)
        kept = [r for r in rows if r.status.casefold() not in source_statuses]
        removed = before - len(kept)
        if removed:
            if not args.yes:
                print(f"[{domain.handle}] would remove {removed} keywords with status {args.status}")
                for r in [r for r in rows if r.status.casefold() in source_statuses][:10]:
                    print(f"    - {r.keyword[:60]}")
                print("  Re-run with --yes to confirm.")
                continue
            title = f"{domain.display_name} Keyword Roadmap"
            write_keyword_rows(domain.keywords_file, title, kept)
        print(f"[{domain.handle}] removed {removed} keywords with status {args.status}")
        total_removed += removed
    print(f"\nTotal removed: {total_removed}")
    return 0


def cmd_keywords_clean_campaigns(args: argparse.Namespace) -> int:
    """Close stale DB campaigns that never completed (active but abandoned)."""
    import sqlite3

    db_path = PROJECT_ROOT / "data" / "rankstein.db"
    con = sqlite3.connect(str(db_path))
    stale = con.execute(
        "SELECT COUNT(*) FROM campaigns WHERE status='active' AND completed_at IS NULL"
    ).fetchone()[0]
    print(f"Stale active campaigns (never completed): {stale}")
    if stale and not args.yes:
        print("Re-run with --yes to mark them 'archived'.")
        con.close()
        return 0
    if stale:
        con.execute("UPDATE campaigns SET status='archived' WHERE status='active' AND completed_at IS NULL")
        con.commit()
        print(f"Archived {stale} stale campaigns.")
    con.close()
    return 0


_JUNK_SUBSTRINGS = (
    "pin page",
    "pin de ",
    "cargando los resultados",
)
_JUNK_EXACT = {
    "receta",
    "recetas",
    "recetas de",
    "postres recetas",
    "galletas recetas",
    "pasteles recetas",
    "aperitivos faciles",
    "receta cremosa y rapida",
    "ale en la cocina",
    "antojo en tu cocina",
    "de aperitivos para fiestas",
    "de aperitivos para fiestas faciles",
    "de aperitivos faciles",
}


def _is_junk_keyword(keyword: str) -> bool:
    k = " ".join(keyword.lower().split())
    if any(token in k for token in _JUNK_SUBSTRINGS):
        return True
    return k in _JUNK_EXACT


def cmd_keywords_purge_junk(args: argparse.Namespace) -> int:
    """Remove Pinterest pin-page artifacts and garbage keywords from roadmaps."""
    from rankstein.keyword_roadmap import read_keyword_rows, write_keyword_rows

    total_removed = 0
    for domain in _iter_target_domains(args.domain):
        rows = read_keyword_rows(domain.keywords_file)
        junk = [r for r in rows if _is_junk_keyword(r.keyword)]
        if not junk:
            print(f"[{domain.handle}] no junk keywords found")
            continue
        print(f"[{domain.handle}] {len(junk)} junk keywords:")
        for r in junk[: args.limit]:
            print(f"    - {r.keyword[:60]} [{r.status}]")
        if len(junk) > args.limit:
            print(f"    ... and {len(junk) - args.limit} more")
        if not args.yes:
            print("  Re-run with --yes to remove them.")
            continue
        kept = [r for r in rows if not _is_junk_keyword(r.keyword)]
        title = f"{domain.display_name} Keyword Roadmap"
        write_keyword_rows(domain.keywords_file, title, kept)
        print(f"  Removed {len(junk)} junk keywords.")
        total_removed += len(junk)
    print(f"\nTotal junk removed: {total_removed}")
    return 0


def cmd_subscribers_add(args: argparse.Namespace) -> int:
    client = _subscriber_client(args)
    row = client.add(args.email, source=args.source)
    print(f"Subscriber active: {row.get('email')}")
    return 0


def cmd_subscribers_list(args: argparse.Namespace) -> int:
    client = _subscriber_client(args)
    rows = client.list(status=args.status, limit=args.limit)
    if not rows:
        print("No subscribers found.")
        return 0
    print(f"{'EMAIL':<42}{'STATUS':<16}{'SOURCE':<20}{'CREATED'}")
    print(f"{'-' * 42}{'-' * 16}{'-' * 20}{'-' * 24}")
    for row in rows:
        print(
            f"{row.get('email', '')!s:<42}"
            f"{row.get('status', '')!s:<16}"
            f"{row.get('source', '')!s:<20}"
            f"{str(row.get('created_at', ''))[:24]}"
        )
    return 0


def cmd_subscribers_unsubscribe(args: argparse.Namespace) -> int:
    client = _subscriber_client(args)
    row = client.update_status(args.email, "unsubscribed")
    print(f"Subscriber unsubscribed: {row.get('email')}")
    return 0


def cmd_subscribers_export(args: argparse.Namespace) -> int:
    from rankstein.subscribers import export_subscribers_csv

    client = _subscriber_client(args)
    rows = client.list(status=args.status, limit=args.limit)
    output = export_subscribers_csv(rows, args.output)
    print(f"Exported {len(rows)} subscribers to {output}")
    return 0


def cmd_suite_status(args: argparse.Namespace) -> int:
    from rankstein.suite_controller import get_service_status

    status = get_service_status()
    print(json.dumps(status, indent=2))
    return 0


def cmd_suite_preflight(args: argparse.Namespace) -> int:
    from rankstein.suite_controller import preflight

    report = preflight()
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


def cmd_suite_start(args: argparse.Namespace) -> int:
    from rankstein.suite_controller import start_services

    report = start_services()
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


def cmd_suite_stop(args: argparse.Namespace) -> int:
    from rankstein.suite_controller import stop_services

    print("Stopping suite services...")
    stop_services()
    print("Suite services stopped.")
    return 0


def cmd_suite_restart(args: argparse.Namespace) -> int:
    from rankstein.suite_controller import restart_services

    print("Restarting suite services...")
    report = restart_services()
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


def cmd_suite_install(args: argparse.Namespace) -> int:
    from rankstein.suite_controller import install_tasks

    install_tasks()
    return 0


def cmd_suite_uninstall(args: argparse.Namespace) -> int:
    from rankstein.suite_controller import uninstall_tasks

    uninstall_tasks()
    return 0


# ───────────────────────────────────────────────────────────────────────────
# Argparse builder
# ───────────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rankstein",
        description="RankStein — multi-domain autonomous SEO content engine.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add-domain", help="Provision a new blog (wizard)")
    add.add_argument("domain", help="Domain name (e.g. keto-dinners.com)")
    add.add_argument(
        "--non-interactive",
        action="store_true",
        help="Skip credential prompts (write blank .env, fill in later)",
    )
    add.add_argument("--skip-branding", action="store_true", help="Skip logo + theme generation")
    add.add_argument("--keywords", type=int, default=30, help="Number of seed keywords")
    add.add_argument("--categories", type=int, default=6, help="Number of category buckets")
    add.add_argument(
        "--clone-site",
        action="store_true",
        help="Clone and rebrand the RecetaDolce Next.js template into a new site project",
    )
    add.add_argument(
        "--template-path",
        type=Path,
        default=None,
        help="Template project path; default is the sibling recetadolce folder",
    )
    add.add_argument(
        "--projects-root",
        type=Path,
        default=None,
        help="Directory where the generated site project is created; default is the parent of RankStein",
    )
    add.add_argument(
        "--overwrite-site",
        action="store_true",
        help="Replace an existing generated site folder with the same handle",
    )
    add.set_defaults(func=cmd_add_domain)

    lst = sub.add_parser("list-domains", help="List all configured domains")
    lst.set_defaults(func=cmd_list_domains)

    show = sub.add_parser("show-domain", help="Show a domain's resolved configuration")
    show.add_argument("handle", help="Domain handle (e.g. keto-dinners)")
    show.set_defaults(func=cmd_show_domain)

    run = sub.add_parser("run", help="Brief, clean, seed, and start autonomous campaigns")
    run.add_argument("--domain", default=None, help="Domain handle; default = registry default")
    run.add_argument("--all", action="store_true", help="Run every configured domain (default)")
    run.add_argument("--keywords", type=int, default=3, help="Pending keywords to seed per domain")
    run.add_argument("--workers", type=int, default=1, help="Article workers to launch per domain")
    run.add_argument("--no-launch", action="store_true", help="Only audit, clean, and seed DB records")
    run.add_argument("--skip-trends", action="store_true", help="Do not refresh daily trend keyword lists")
    run.add_argument("--trend-limit", type=int, default=10, help="Daily trend keywords to add per domain")
    run.add_argument("--json", action="store_true", help="Print machine-readable startup report")
    run.set_defaults(func=cmd_run)

    production = sub.add_parser("production", help="Manage bounded production-batch proof")
    production_sub = production.add_subparsers(dest="production_command", required=True)
    production_reconcile = production_sub.add_parser(
        "reconcile",
        help="Reconcile a late completed priority primary-pin job",
    )
    production_reconcile.add_argument("--batch-id", required=True, help="Production batch identifier")
    production_reconcile.add_argument("--domain", required=True, help="Domain handle")
    production_reconcile.add_argument(
        "--pipeline-run-id",
        required=True,
        help="Exact pipeline run identifier stored in the batch report",
    )
    production_reconcile.add_argument(
        "--primary-job-id",
        required=True,
        help="Completed priority-1 Pinterest job identifier",
    )
    production_reconcile.set_defaults(func=cmd_production_reconcile)

    trends = sub.add_parser("trends", help="Refresh precise Pinterest-first keyword intelligence")
    trends.add_argument("--domain", default=None, help="Domain handle; default = every configured domain")
    trends.add_argument("--limit", type=int, default=10, help="Best keywords to keep per domain")
    trends.add_argument(
        "--no-roadmap", action="store_true", help="Write reports but do not append roadmap rows"
    )
    trends.add_argument(
        "--candidate-origin-policy",
        choices=("pinterest_required", "multi_source"),
        default="pinterest_required",
        help=(
            "Candidate origin policy; default requires Pinterest evidence. "
            "Use multi_source only for explicitly requested broad discovery."
        ),
    )
    trends.set_defaults(func=cmd_trends)

    keywords = sub.add_parser("keywords", help="Clean, retry, or remove roadmap keywords")
    kw_sub = keywords.add_subparsers(dest="keywords_command", required=True)

    kw_list = kw_sub.add_parser("list", help="List keywords with counts, optionally filter by status")
    kw_list.add_argument("--domain", default=None, help="Domain handle; default = all domains")
    kw_list.add_argument("--status", default=None, help="Filter by status (e.g. Failed, Live, Pending)")
    kw_list.add_argument("--limit", type=int, default=50, help="Max rows to display per domain")
    kw_list.set_defaults(func=cmd_keywords_list)

    kw_retry = kw_sub.add_parser("retry", help="Reset failed/blocked keywords back to Pending")
    kw_retry.add_argument("--domain", default=None, help="Domain handle; default = all domains")
    kw_retry.add_argument(
        "--from-status",
        default="Failed,Needs Verification",
        help="Comma-separated statuses to reset (default: Failed,Needs Verification)",
    )
    kw_retry.set_defaults(func=cmd_keywords_retry)

    kw_remove = kw_sub.add_parser("remove", help="Permanently remove keywords with a given status")
    kw_remove.add_argument("--domain", default=None, help="Domain handle; default = all domains")
    kw_remove.add_argument("--status", required=True, help="Comma-separated statuses to remove")
    kw_remove.add_argument("--yes", action="store_true", help="Confirm removal (required)")
    kw_remove.set_defaults(func=cmd_keywords_remove)

    kw_camps = kw_sub.add_parser("clean-campaigns", help="Archive stale DB campaigns that never completed")
    kw_camps.add_argument("--yes", action="store_true", help="Confirm archiving (required)")
    kw_camps.set_defaults(func=cmd_keywords_clean_campaigns)

    kw_junk = kw_sub.add_parser("purge-junk", help="Remove Pinterest pin-page artifacts and garbage keywords")
    kw_junk.add_argument("--domain", default=None, help="Domain handle; default = all domains")
    kw_junk.add_argument("--limit", type=int, default=20, help="Max junk rows to preview per domain")
    kw_junk.add_argument("--yes", action="store_true", help="Confirm removal (required)")
    kw_junk.set_defaults(func=cmd_keywords_purge_junk)

    autonomous = sub.add_parser("autonomous", help="Run continuous trend+audit+campaign cycles")
    autonomous.add_argument("--domain", default=None, help="Domain handle; default = every configured domain")
    autonomous.add_argument("--keywords", type=int, default=3, help="Pending keywords to seed per domain")
    autonomous.add_argument("--workers", type=int, default=1, help="Article workers to launch per domain")
    autonomous.add_argument("--interval-hours", type=float, default=24.0, help="Hours between cycles")
    autonomous.add_argument(
        "--cycles", type=int, default=0, help="0 = forever; otherwise stop after N cycles"
    )
    autonomous.add_argument("--no-launch", action="store_true", help="Audit/seed only; do not start workers")
    autonomous.add_argument(
        "--skip-trends", action="store_true", help="Do not refresh daily trend keyword lists"
    )
    autonomous.add_argument(
        "--trend-limit", type=int, default=10, help="Daily trend keywords to add per domain"
    )
    autonomous.set_defaults(func=cmd_autonomous)

    launch = sub.add_parser(
        "launch",
        help="Boot services, preflight campaigns, start workers/supervisor, and monitor health",
    )
    launch.add_argument("--domain", default=None, help="Domain handle; default = every configured domain")
    launch.add_argument("--all", action="store_true", help="Run every configured domain (default)")
    launch.add_argument("--keywords", type=int, default=3, help="Pending keywords to seed per domain")
    launch.add_argument("--workers", type=int, default=1, help="Article workers to launch")
    launch.add_argument("--skip-trends", action="store_true", help="Do not refresh daily trend keyword lists")
    launch.add_argument("--trend-limit", type=int, default=10, help="Daily trend keywords to add per domain")
    launch.add_argument("--monitor-seconds", type=int, default=180, help="Seconds to monitor after launch")
    launch.add_argument("--monitor-interval", type=int, default=30, help="Seconds between monitor snapshots")
    launch.add_argument("--no-services", action="store_true", help="Do not boot MCP/Hermes/operator services")
    launch.add_argument("--no-articles", action="store_true", help="Do not start article workers")
    launch.add_argument("--no-supervisor", action="store_true", help="Do not start Pinterest supervisor")
    launch.add_argument(
        "--frontend",
        action="store_true",
        help="Compatibility flag; the RankStein operator starts with services",
    )
    launch.add_argument(
        "--skip-odysseus-server",
        action="store_true",
        help="Deprecated compatibility flag; Odysseus is no longer started",
    )
    launch.add_argument("--skip-validation", action="store_true", help="Skip isolated automation validation")
    launch.add_argument("--json", action="store_true", help="Print machine-readable launch report")
    launch.set_defaults(func=cmd_launch)

    subscribers = sub.add_parser("subscribers", help="Manage newsletter subscribers from the CLI")
    subscribers_sub = subscribers.add_subparsers(dest="subscribers_command", required=True)

    sub_add = subscribers_sub.add_parser("add", help="Add or reactivate a subscriber")
    sub_add.add_argument("email", help="Subscriber email address")
    sub_add.add_argument("--source", default="cli", help="Source label to store")
    sub_add.add_argument("--domain", default=None, help="Domain handle; default = global Supabase")
    sub_add.set_defaults(func=cmd_subscribers_add)

    sub_list = subscribers_sub.add_parser("list", help="List subscribers")
    sub_list.add_argument("--status", default="active", help="Filter by status; use empty string for all")
    sub_list.add_argument("--limit", type=int, default=100, help="Maximum rows to fetch")
    sub_list.add_argument("--domain", default=None, help="Domain handle; default = global Supabase")
    sub_list.set_defaults(func=cmd_subscribers_list)

    sub_unsub = subscribers_sub.add_parser("unsubscribe", help="Mark a subscriber as unsubscribed")
    sub_unsub.add_argument("email", help="Subscriber email address")
    sub_unsub.add_argument("--domain", default=None, help="Domain handle; default = global Supabase")
    sub_unsub.set_defaults(func=cmd_subscribers_unsubscribe)

    sub_export = subscribers_sub.add_parser("export", help="Export subscribers to CSV")
    sub_export.add_argument("output", type=Path, help="CSV output path")
    sub_export.add_argument("--status", default="active", help="Filter by status; use empty string for all")
    sub_export.add_argument("--limit", type=int, default=1000, help="Maximum rows to fetch")
    sub_export.add_argument("--domain", default=None, help="Domain handle; default = global Supabase")
    sub_export.set_defaults(func=cmd_subscribers_export)

    suite = sub.add_parser("suite", help="Manage RankStein background services and processes")
    suite_sub = suite.add_subparsers(dest="suite_command", required=True)

    suite_status = suite_sub.add_parser("status", help="Get status of all background services")
    suite_status.set_defaults(func=cmd_suite_status)

    suite_preflight = suite_sub.add_parser("preflight", help="Verify prerequisites without starting")
    suite_preflight.set_defaults(func=cmd_suite_preflight)

    suite_start = suite_sub.add_parser("start", help="Start all background services idempotently")
    suite_start.set_defaults(func=cmd_suite_start)

    suite_stop = suite_sub.add_parser("stop", help="Gracefully stop all background services")
    suite_stop.set_defaults(func=cmd_suite_stop)

    suite_restart = suite_sub.add_parser("restart", help="Restart all background services")
    suite_restart.set_defaults(func=cmd_suite_restart)

    suite_install = suite_sub.add_parser("install", help="Register Windows Scheduled Tasks")
    suite_install.set_defaults(func=cmd_suite_install)

    suite_uninstall = suite_sub.add_parser("uninstall", help="Remove Windows Scheduled Tasks")
    suite_uninstall.set_defaults(func=cmd_suite_uninstall)

    return p


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except Exception as exc:
        if exc.__class__.__name__ == "SubscriberError":
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())

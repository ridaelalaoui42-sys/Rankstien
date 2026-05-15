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

PROJECT_ROOT = Path(__file__).resolve().parent.parent


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
    import os
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
                "-ExecutionPolicy", "Bypass",
                "-File", str(mcp_script),
                "-NoGemini",      # Don't launch Gemini CLI from here — we're already inside it
            ],
            cwd=str(PROJECT_ROOT),
            timeout=60,           # AgentMemory health-wait is max 20s + buffer
        )
        if result.returncode != 0:
            print(f"[boot] WARNING: MCP boot script exited {result.returncode} — continuing anyway.", file=sys.stderr)
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
    return 0


def cmd_trends(args: argparse.Namespace) -> int:
    """Refresh Pinterest/Google News trend lists without launching workers."""
    from rankstein.trend_intelligence import refresh_domain_trend_lists

    reload_registry()
    registry = get_registry()
    domains = [registry.get(args.domain)] if args.domain else registry.all()
    report = refresh_domain_trend_lists(
        domains,
        limit_per_domain=args.limit,
        append_to_roadmap=not args.no_roadmap,
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


def _subscriber_client(args: argparse.Namespace):
    from rankstein.subscribers import SupabaseSubscribersClient, resolve_supabase_target

    return SupabaseSubscribersClient(resolve_supabase_target(getattr(args, "domain", None)))


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

    trends = sub.add_parser("trends", help="Refresh daily Pinterest/Google News keyword intelligence")
    trends.add_argument("--domain", default=None, help="Domain handle; default = every configured domain")
    trends.add_argument("--limit", type=int, default=10, help="Best keywords to keep per domain")
    trends.add_argument(
        "--no-roadmap", action="store_true", help="Write reports but do not append roadmap rows"
    )
    trends.set_defaults(func=cmd_trends)

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

    return p


def main(argv: list[str] | None = None) -> int:
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

"""cli-rankstein — Agent-native CLI for RankStein Enterprise SEO Platform.

Usage:
    cli-rankstein --help
    cli-rankstein health
    cli-rankstein domains list
    cli-rankstein domains add --name myblog --url https://myblog.com --niche Technology
    cli-rankstein campaigns list --status active
    cli-rankstein campaigns launch --keyword "best seo tools" --domain myblog.com --niche General
    cli-rankstein campaigns launch --keyword "best seo tools" --domain myblog.com --json
    cli-rankstein seo analyze --domain myblog.com --niche Technology
    cli-rankstein seo keywords --seed "ai seo" --niche Technology
    cli-rankstein seo competitors --domain myblog.com --niche Technology
    cli-rankstein seo audit --domain myblog.com
    cli-rankstein seo onpage --url https://myblog.com/post-1
    cli-rankstein integrations list --domain-id abc123
    cli-rankstein credits
    cli-rankstein analytics overview
"""

import argparse
import json
import os
import sys
from typing import Any

import httpx

API_BASE = os.environ.get("RANKSTEIN_API_URL", "http://127.0.0.1:8080")
API_KEY = os.environ.get("RANKSTEIN_API_KEY", "")

TIMEOUT = 120.0  # Long timeout for pipeline execution


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if API_KEY:
        h["X-RankStein-Key"] = API_KEY
    return h


def _output(data: Any, json_mode: bool = False) -> None:
    """Output data as JSON (for agents) or formatted text (for humans)."""
    if json_mode:
        print(json.dumps(data, indent=2, default=str))
    else:
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, (dict, list)):
                    print(f"  {k}: {json.dumps(v, default=str)}")
                else:
                    print(f"  {k}: {v}")
        elif isinstance(data, list):
            for i, item in enumerate(data):
                if isinstance(item, dict):
                    print(f"  [{i}] {json.dumps(item, default=str)}")
                else:
                    print(f"  [{i}] {item}")
        else:
            print(data)


def _request(method: str, path: str, body: dict | None = None, timeout: float = 30.0) -> tuple[bool, Any]:
    """Make HTTP request to RankStein API. Returns (success, data)."""
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.request(method, f"{API_BASE}{path}", json=body, headers=_headers())
            if resp.status_code >= 400:
                return False, {"error": resp.text, "status_code": resp.status_code}
            try:
                return True, resp.json()
            except Exception:
                return True, resp.text
    except httpx.ConnectError:
        return False, {"error": f"Cannot connect to RankStein API at {API_BASE}. Is the server running?"}
    except httpx.TimeoutException:
        return False, {"error": "Request timed out"}
    except Exception as e:
        return False, {"error": str(e)}


# ── Health ──────────────────────────────────────────────
def cmd_health(args) -> None:
    ok, data = _request("GET", "/api/health", timeout=10)
    _output(data, args.json)


# ── Domains ─────────────────────────────────────────────
def cmd_domains(args) -> None:
    sub = args.domain_command
    if sub == "list":
        ok, data = _request("GET", f"/api/domains{'?status=' + args.status if args.status else ''}")
        _output(data, args.json)
    elif sub == "add":
        ok, data = _request(
            "POST",
            "/api/domains",
            {"name": args.name, "url": args.url, "niche": args.niche, "schedule": args.schedule or ""},
        )
        _output(data, args.json)
    elif sub == "get":
        ok, data = _request("GET", f"/api/domains/{args.id}")
        _output(data, args.json)
    elif sub == "update":
        ok, data = _request(
            "PATCH",
            f"/api/domains/{args.id}",
            {"name": args.name, "url": args.url, "niche": args.niche}
            if any([args.name, args.url, args.niche])
            else {},
        )
        _output(data, args.json)
    elif sub == "archive":
        ok, data = _request("DELETE", f"/api/domains/{args.id}")
        _output(data, args.json)
    elif sub == "activate":
        ok, data = _request("POST", f"/api/domains/{args.id}/activate")
        _output(data, args.json)
    elif sub == "pause":
        ok, data = _request("POST", f"/api/domains/{args.id}/pause")
        _output(data, args.json)


# ── Campaigns ───────────────────────────────────────────
def cmd_campaigns(args) -> None:
    sub = args.campaign_command
    if sub == "list":
        params = []
        if args.status:
            params.append(f"status={args.status}")
        params.append(f"limit={args.limit}")
        ok, data = _request("GET", f"/api/campaigns?{'&'.join(params)}")
        _output(data, args.json)
    elif sub == "get":
        ok, data = _request("GET", f"/api/campaigns/{args.id}")
        _output(data, args.json)
    elif sub == "artifacts":
        ok, data = _request("GET", f"/api/campaigns/{args.id}/artifacts")
        _output(data, args.json)
    elif sub == "approve":
        ok, data = _request("POST", f"/api/campaigns/{args.id}/approve")
        _output(data, args.json)
    elif sub == "reject":
        ok, data = _request("POST", f"/api/campaigns/{args.id}/reject", {"reason": args.reason or ""})
        _output(data, args.json)
    elif sub == "launch":
        # SSE streaming pipeline execution
        print(f"Launching pipeline for '{args.keyword}' on {args.domain}...", file=sys.stderr)
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                with client.stream(
                    "POST",
                    f"{API_BASE}/api/orchestrate",
                    json={
                        "keyword": args.keyword,
                        "domain": args.domain,
                        "niche": args.niche or "General",
                        "project_id": args.project_id or "",
                    },
                    headers=_headers(),
                ) as resp:
                    if resp.status_code >= 400:
                        _output({"error": resp.text, "status_code": resp.status_code}, args.json)
                        return
                    campaign_id = resp.headers.get("X-Campaign-Id", "unknown")
                    print(f"Campaign ID: {campaign_id}", file=sys.stderr)
                    buffer = ""
                    for line in resp.iter_lines():
                        if not line.startswith("data: "):
                            continue
                        try:
                            event = json.loads(line[6:])
                            if args.json:
                                print(json.dumps(event))
                            else:
                                etype = event.get("type", "")
                                if etype == "agent_start":
                                    print(
                                        f"  ▶ {event.get('agent', '?')} starting (step {event.get('step', '?')}/{event.get('total', '?')})",
                                        file=sys.stderr,
                                    )
                                elif etype == "agent_done":
                                    print(
                                        f"  ✓ {event.get('agent', '?')} done ({event.get('tokens', 0)} tokens, {event.get('latency_ms', 0)}ms)",
                                        file=sys.stderr,
                                    )
                                elif etype == "quality_gate":
                                    status = "PASS ✓" if event.get("passed") else "FAIL ✗"
                                    print(
                                        f"  ⚡ Quality Gate: EEAT {event.get('score', 0)}/{event.get('threshold', 75)} — {status}",
                                        file=sys.stderr,
                                    )
                                elif etype == "credit_update":
                                    print(
                                        f"  💰 Credits: -{event.get('consumed', 0)} (total: {event.get('total_consumed', 0)})",
                                        file=sys.stderr,
                                    )
                                elif etype == "done":
                                    print(
                                        f"\n  ✓ Pipeline complete! Tokens: {event.get('total_tokens', 0)}, Credits: {event.get('total_credits', 0)}, Time: {event.get('total_latency_ms', 0) / 1000:.1f}s",
                                        file=sys.stderr,
                                    )
                                elif etype == "error":
                                    print(
                                        f"  ✗ Error in {event.get('agent', '?')}: {event.get('message', '')}",
                                        file=sys.stderr,
                                    )
                        except json.JSONDecodeError:
                            pass
        except httpx.ConnectError:
            _output({"error": f"Cannot connect to {API_BASE}"}, args.json)


# ── SEO Tools ───────────────────────────────────────────
def cmd_seo(args) -> None:
    sub = args.seo_command
    if sub == "analyze":
        ok, data = _request(
            "POST", "/api/seo/analyze", {"domain": args.domain, "niche": args.niche or "General"}
        )
        _output(data, args.json)
    elif sub == "audit":
        ok, data = _request(
            "POST", "/api/seo/audit", {"domain": args.domain, "niche": args.niche or "General"}
        )
        _output(data, args.json)
    elif sub == "keywords":
        ok, data = _request(
            "POST",
            "/api/seo/keywords",
            {"seed_keyword": args.seed, "domain": args.domain or "", "depth": "deep"},
        )
        _output(data, args.json)
    elif sub == "competitors":
        ok, data = _request(
            "POST", "/api/seo/competitors", {"domain": args.domain, "niche": args.niche or "General"}
        )
        _output(data, args.json)
    elif sub == "keyword-map":
        # Read keywords from stdin or file
        keywords = []
        if args.keywords_file:
            with open(args.keywords_file) as f:
                keywords = json.load(f)
        ok, data = _request("POST", "/api/seo/keyword-map", {"domain": args.domain, "keywords": keywords})
        _output(data, args.json)
    elif sub == "onpage":
        ok, data = _request("POST", "/api/seo/onpage", {"url": args.url, "domain": args.domain or ""})
        _output(data, args.json)
    elif sub == "content-optimize":
        content = ""
        if args.content_file:
            with open(args.content_file) as f:
                content = f.read()
        elif args.content:
            content = args.content
        ok, data = _request(
            "POST",
            "/api/seo/content-optimize",
            {"content": content, "keyword": args.keyword, "niche": args.niche or "General"},
        )
        _output(data, args.json)
    elif sub == "backlinks":
        ok, data = _request("POST", "/api/seo/backlinks", {"domain": args.domain})
        _output(data, args.json)


# ── Integrations ────────────────────────────────────────
def cmd_integrations(args) -> None:
    sub = args.integration_command
    if sub == "list":
        ok, data = _request(
            "GET", f"/api/integrations{'?domain_id=' + args.domain_id if args.domain_id else ''}"
        )
        _output(data, args.json)
    elif sub == "add":
        ok, data = _request(
            "POST",
            "/api/integrations",
            {
                "domain_id": args.domain_id,
                "type": args.type,
                "credentials": json.loads(args.credentials) if args.credentials else {},
            },
        )
        _output(data, args.json)
    elif sub == "test":
        ok, data = _request(
            "POST",
            "/api/integrations/test",
            {
                "type": args.type,
                "url": args.url or "",
                "username": args.username or "",
                "password": args.password or "",
            },
        )
        _output(data, args.json)
    elif sub == "remove":
        ok, data = _request("DELETE", f"/api/integrations/{args.id}")
        _output(data, args.json)


# ── Analytics ───────────────────────────────────────────
def cmd_analytics(args) -> None:
    sub = args.analytics_command
    if sub == "overview":
        ok, data = _request("GET", "/api/analytics/overview")
        _output(data, args.json)
    elif sub == "campaigns":
        ok, data = _request("GET", "/api/analytics/campaigns")
        _output(data, args.json)


# ── Credits ─────────────────────────────────────────────
def cmd_credits(args) -> None:
    ok, data = _request("GET", "/api/credits")
    _output(data, args.json)


# ── Main Parser ─────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cli-rankstein",
        description="Agent-native CLI for RankStein — Enterprise AI SEO Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cli-rankstein health
  cli-rankstein domains list --json
  cli-rankstein domains add --name myblog --url https://myblog.com --niche Technology
  cli-rankstein campaigns launch --keyword "best seo tools" --domain myblog.com
  cli-rankstein seo keywords --seed "ai seo" --json
  cli-rankstein analytics overview

Environment Variables:
  RANKSTEIN_API_URL   API base URL (default: http://127.0.0.1:8080)
  RANKSTEIN_API_KEY   API key for authentication
""",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON (for AI agents)")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # health
    subparsers.add_parser("health", help="Check API health")

    # domains
    dp = subparsers.add_parser("domains", help="Manage domains")
    dsub = dp.add_subparsers(dest="domain_command")
    dsub.add_parser("list").add_argument("--status", default=None)
    da = dsub.add_parser("add")
    da.add_argument("--name", required=True)
    da.add_argument("--url", required=True)
    da.add_argument("--niche", default="General")
    da.add_argument("--schedule", default="")
    dg = dsub.add_parser("get")
    dg.add_argument("id")
    du = dsub.add_parser("update")
    du.add_argument("id")
    du.add_argument("--name", default="")
    du.add_argument("--url", default="")
    du.add_argument("--niche", default="")
    darc = dsub.add_parser("archive")
    darc.add_argument("id")
    dact = dsub.add_parser("activate")
    dact.add_argument("id")
    dpause = dsub.add_parser("pause")
    dpause.add_argument("id")

    # campaigns
    cp = subparsers.add_parser("campaigns", help="Manage campaigns")
    csub = cp.add_subparsers(dest="campaign_command")
    cl = csub.add_parser("list")
    cl.add_argument("--status", default=None)
    cl.add_argument("--limit", type=int, default=50)
    cg = csub.add_parser("get")
    cg.add_argument("id")
    ca = csub.add_parser("artifacts")
    ca.add_argument("id")
    capp = csub.add_parser("approve")
    capp.add_argument("id")
    crj = csub.add_parser("reject")
    crj.add_argument("id")
    crj.add_argument("--reason", default="")
    cln = csub.add_parser("launch", help="Launch full SEO pipeline (SSE streaming)")
    cln.add_argument("--keyword", required=True)
    cln.add_argument("--domain", required=True)
    cln.add_argument("--niche", default="General")
    cln.add_argument("--project-id", default="")

    # seo
    sp = subparsers.add_parser("seo", help="SEO tools")
    ssub = sp.add_subparsers(dest="seo_command")
    sa = ssub.add_parser("analyze")
    sa.add_argument("--domain", required=True)
    sa.add_argument("--niche", default="General")
    sau = ssub.add_parser("audit")
    sau.add_argument("--domain", required=True)
    sau.add_argument("--niche", default="General")
    sk = ssub.add_parser("keywords")
    sk.add_argument("--seed", required=True)
    sk.add_argument("--domain", default="")
    sc = ssub.add_parser("competitors")
    sc.add_argument("--domain", required=True)
    sc.add_argument("--niche", default="General")
    skm = ssub.add_parser("keyword-map")
    skm.add_argument("--domain", required=True)
    skm.add_argument("--keywords-file", required=True)
    sop = ssub.add_parser("onpage")
    sop.add_argument("--url", required=True)
    sop.add_argument("--domain", default="")
    sco = ssub.add_parser("content-optimize")
    sco.add_argument("--keyword", required=True)
    sco.add_argument("--niche", default="General")
    sco.add_argument("--content", default="")
    sco.add_argument("--content-file", default="")
    sb = ssub.add_parser("backlinks")
    sb.add_argument("--domain", required=True)

    # integrations
    ip = subparsers.add_parser("integrations", help="Manage integrations")
    isub = ip.add_subparsers(dest="integration_command")
    isub.add_parser("list").add_argument("--domain-id", default="")
    ia = isub.add_parser("add")
    ia.add_argument("--domain-id", required=True)
    ia.add_argument("--type", required=True)
    ia.add_argument("--credentials", default="{}")
    it = isub.add_parser("test")
    it.add_argument("--type", required=True)
    it.add_argument("--url", default="")
    it.add_argument("--username", default="")
    it.add_argument("--password", default="")
    ir = isub.add_parser("remove")
    ir.add_argument("id")

    # analytics
    ap = subparsers.add_parser("analytics", help="View analytics")
    asub = ap.add_subparsers(dest="analytics_command")
    asub.add_parser("overview")
    asub.add_parser("campaigns")

    # credits
    subparsers.add_parser("credits", help="View credit balance")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "health": cmd_health,
        "domains": cmd_domains,
        "campaigns": cmd_campaigns,
        "seo": cmd_seo,
        "integrations": cmd_integrations,
        "analytics": cmd_analytics,
        "credits": cmd_credits,
    }

    cmd = commands.get(args.command)
    if cmd:
        cmd(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

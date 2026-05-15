"""
RankStein MCP Server — Connects Gemini CLI to RankStein tools.
Gemini CLI handles all AI/LLM calls. This server handles:
  - Keyword roadmap management
  - Editorial image overlay (Luxury V3 / NanaBanana style)
  - EXIF metadata injection
  - Supabase Storage upload
  - Supabase posts table publish/upsert
  - Pinterest session management helpers

Run: python rankstein_mcp_server.py
Register: gemini mcp add rankstein python <path_to_repo>/rankstein_mcp_server.py
"""

import json
import logging
import os
import random
import re
import sys
import textwrap
from datetime import datetime
from pathlib import Path

# ── Load .env FIRST (before any other project imports) ───────────────────────
_env_path = Path(__file__).resolve().parent / ".env"
try:
    from dotenv import load_dotenv as _load_dotenv

    _result = _load_dotenv(_env_path, override=False)
    # Using a temporary logger or print before full logging is configured
    _key_check = os.environ.get("RECETAGENIAL_SUPABASE_KEY", "NOT_FOUND")
    _masked_key = f"{_key_check[:4]}...{_key_check[-4:]}" if len(_key_check) > 10 else _key_check
    if os.environ.get("RANKSTEIN_DEBUG_ENV_LOAD", "").lower() in {"1", "true", "yes"}:
        sys.stderr.write(f"DEBUG: .env loaded={_result}, path={_env_path}, key={_masked_key}\n")
except ImportError:
    if _env_path.exists():
        for _line in _env_path.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

# ── Logging ───────────────────────────────────────────────────────────────────
from logging.handlers import RotatingFileHandler

import requests
import cloudinary
import cloudinary.uploader
from mcp.server.fastmcp import FastMCP

from backend.services.memory_service import memory

# Domain registry — resolves a Domain by handle (or default).
from rankstein.domain import get_registry

_log_dir = Path(__file__).resolve().parent / "data"
_log_dir.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        RotatingFileHandler(
            str(_log_dir / "rankstein_mcp.log"),
            maxBytes=5 * 1024 * 1024,  # 5 MB per file
            backupCount=3,
            encoding="utf-8",
        ),
        logging.StreamHandler(sys.stderr),
    ],
)
logger = logging.getLogger("rankstein")

# ── Paths ─────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
KEYWORDS_FILE = PROJECT_ROOT / "memory" / "keywords.md"
OUTPUT_DIR = PROJECT_ROOT / "nanobanana-output"
REMASTER_DIR = PROJECT_ROOT / "data" / "media" / "remaster_final"
DOWNLOAD_DIR = PROJECT_ROOT / "data" / "media" / "remaster_raw"
for d in [OUTPUT_DIR, REMASTER_DIR, DOWNLOAD_DIR]:
    d.mkdir(parents=True, exist_ok=True)
FAILURES_FILE = PROJECT_ROOT / "data" / "keyword_failures.json"

mcp = FastMCP("rankstein")

# ── Supabase & Cloudinary config from config.py ──────────────────────────────
from rankstein.config import get_settings, reset_settings_cache

_settings = get_settings()
SUPABASE_URL = _settings.supabase_url
SUPABASE_KEY = _settings.supabase_service_role_key.get_secret_value()
BUCKET = _settings.supabase_bucket

# Configure Cloudinary
cloudinary.config(
    cloud_name=_settings.cloudinary_cloud_name,
    api_key=_settings.cloudinary_api_key.get_secret_value(),
    api_secret=_settings.cloudinary_api_secret.get_secret_value(),
    secure=True
)


def _reload_supabase_config():
    """Reload settings from .env and update global variables."""
    global SUPABASE_URL, SUPABASE_KEY, BUCKET
    reset_settings_cache()
    new_settings = get_settings()
    SUPABASE_URL = new_settings.supabase_url
    SUPABASE_KEY = new_settings.supabase_service_role_key.get_secret_value()
    BUCKET = new_settings.supabase_bucket
    
    # Also reload Cloudinary
    cloudinary.config(
        cloud_name=new_settings.cloudinary_cloud_name,
        api_key=new_settings.cloudinary_api_key.get_secret_value(),
        api_secret=new_settings.cloudinary_api_secret.get_secret_value(),
        secure=True
    )


@mcp.tool()
def upload_image_to_cloudinary(local_path: str, public_id: str = "", folder: str = "") -> dict:
    """
    Upload a local image file to Cloudinary.
    Returns: {public_url, success}
    """
    try:
        path = Path(local_path)
        if not path.exists():
            return {"success": False, "error": f"File not found: {local_path}"}

        # Auto-folder based on public_id if not provided
        if not folder:
            if "dolce" in local_path.lower() or "dolce" in public_id.lower():
                folder = "RecetaDolce"
            else:
                folder = "RecetaGenial"

        upload_params = {
            "folder": folder,
            "resource_type": "image"
        }
        if public_id:
            upload_params["public_id"] = public_id

        result = cloudinary.uploader.upload(str(path), **upload_params)
        
        logger.info(f"Image uploaded to Cloudinary: {result.get('secure_url')}")
        return {
            "success": True, 
            "public_url": result.get("secure_url"),
            "public_id": result.get("public_id"),
            "width": result.get("width"),
            "height": result.get("height"),
            "format": result.get("format")
        }
    except Exception as e:
        logger.error(f"Cloudinary upload failed: {e}")
        return {"success": False, "error": str(e)}


# ── Gemini CLI path resolution (cached) ──────────────────────────────────────
# The MCP server is itself spawned by Gemini CLI, but the spawned process may
# have a different PATH. ``shutil.which`` finds Windows shims (.cmd/.bat) that
# a bare ``["gemini", ...]`` subprocess call won't find — that produced the
# repeated ``WinError 2`` errors in the self-healing layer. Resolve once,
# allow override via ``GEMINI_CLI_PATH``.
import shutil as _shutil

_GEMINI_CLI_PATH: str | None = None
_GEMINI_CLI_RESOLVED = False


def _resolve_gemini_cli() -> str | None:
    """Return absolute path to gemini CLI executable, or None if not found.

    Resolution order:
      1. ``GEMINI_CLI_PATH`` env var (operator override)
      2. ``shutil.which("gemini")`` — finds .cmd/.bat shims on Windows
      3. Common Windows install locations under %APPDATA%\\npm
    Result is cached across calls.
    """
    global _GEMINI_CLI_PATH, _GEMINI_CLI_RESOLVED
    if _GEMINI_CLI_RESOLVED:
        return _GEMINI_CLI_PATH

    override = os.environ.get("GEMINI_CLI_PATH", "").strip()
    if override and Path(override).exists():
        _GEMINI_CLI_PATH = override
    else:
        for candidate in ("gemini", "gemini.cmd", "gemini.exe", "gemini.bat"):
            found = _shutil.which(candidate)
            if found:
                _GEMINI_CLI_PATH = found
                break
        else:
            # Last-ditch: check the common npm global install location on Windows
            appdata = os.environ.get("APPDATA", "")
            if appdata:
                for ext in ("cmd", "exe", "bat"):
                    guess = Path(appdata) / "npm" / f"gemini.{ext}"
                    if guess.exists():
                        _GEMINI_CLI_PATH = str(guess)
                        break

    _GEMINI_CLI_RESOLVED = True
    if _GEMINI_CLI_PATH:
        logger.info(f"Resolved gemini CLI: {_GEMINI_CLI_PATH}")
    else:
        logger.warning(
            "gemini CLI not found. Self-healing will be disabled. Set GEMINI_CLI_PATH in .env to override."
        )
    return _GEMINI_CLI_PATH


mcp = FastMCP("rankstein")

# ═══════════════════════════════════════════════════════════════════════════════
# MEMORY TOOLS
# ═══════════════════════════════════════════════════════════════════════════════


def _csv_list(value: str) -> list[str]:
    """Parse comma-separated MCP string input into clean values."""
    return [item.strip() for item in (value or "").split(",") if item.strip()]


@mcp.tool()
async def memorize_insight(content: str, concepts: str, type: str = "fact", files: str = "") -> dict:
    """
    Save an important insight, decision, or pattern to the RankStein semantic memory.
    Use this to persist knowledge across autonomous cycles that doesn't belong in code or .md files.

    type: 'pattern' | 'preference' | 'architecture' | 'bug' | 'workflow' | 'fact'
    concepts: comma-separated keywords
    files: comma-separated relevant file paths
    """
    concept_list = _csv_list(concepts)
    file_list = _csv_list(files)
    memory_type = {
        "bug": "episodic",
        "workflow": "procedural",
        "pattern": "semantic",
        "preference": "semantic",
        "architecture": "semantic",
        "fact": "semantic",
    }.get(type, type)
    result = memory.remember(
        content=content,
        concepts=sorted(set(["rankstein", type, *concept_list])),
        type=memory_type,
        files=file_list,
    )
    return {"success": bool(result.get("success", False)), "memory_type": memory_type, "result": result}


@mcp.tool()
async def memory_stats() -> dict:
    """Get current statistics from the agentmemory engine."""
    return memory.health()


@mcp.tool()
async def search_project_memory(query: str, limit: int = 5) -> dict:
    """Search RankStein long-term memory before choosing strategy or retrying work."""
    limit = max(1, min(int(limit), 20))
    return {"success": True, "query": query, "results": memory.search(query, limit)}


@mcp.tool()
async def remember_pipeline_event(
    event_type: str,
    message: str,
    keyword: str = "",
    domain_handle: str = "",
    status: str = "",
    metadata_json: str = "{}",
) -> dict:
    """Record a RankStein pipeline event for future autonomous runs."""
    try:
        metadata = json.loads(metadata_json) if metadata_json else {}
        if not isinstance(metadata, dict):
            metadata = {"value": metadata}
    except json.JSONDecodeError:
        metadata = {"raw_metadata": metadata_json}
    if keyword:
        metadata["keyword"] = keyword
    if domain_handle:
        metadata["domain_handle"] = domain_handle
    if status:
        metadata["status"] = status
    result = memory.log_event(event_type, message, metadata)
    return {"success": bool(result.get("success", False)), "result": result}


@mcp.tool()
def debug_env_vars() -> dict:
    """List all RECETA and SUPABASE related environment variables (masked)."""

    def mask(v):
        if not v:
            return "MISSING"
        if len(v) < 8:
            return "***"
        return f"{v[:4]}...{v[-4:]}"

    return {
        k: mask(os.environ.get(k))
        for k in os.environ.keys()
        if any(x in k for x in ["RECETA", "SUPABASE", "PINTEREST", "CLOUDINARY"])
    }


# ═══════════════════════════════════════════════════════════════════════════════
# DOMAIN MANAGEMENT TOOLS  ← CALL THESE FIRST ON EVERY SESSION
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def list_domains() -> dict:
    """
    *** MANDATORY FIRST CALL ON EVERY SESSION ***

    List ALL configured domains in the RankStein portfolio.
    Returns each domain's handle, public domain, niche, credential status,
    keyword counts, and daily pin budget.

    ALWAYS call this first before doing any content, keyword, or Pinterest work.
    Never assume you are only working on one domain — iterate over ALL domains
    returned here unless the user explicitly restricts the scope.

    Returns: {domains: [...], total: int, default_handle: str}
    """
    from rankstein.domain import get_registry, reload_registry
    from rankstein.keyword_roadmap import keyword_counts, read_keyword_rows

    reload_registry()
    registry = get_registry()
    all_domains = registry.all()

    domain_list = []
    for d in all_domains:
        # Keyword counts (safe — missing file → empty counts)
        try:
            counts = keyword_counts(read_keyword_rows(d.keywords_file)) if d.keywords_file.exists() else {}
        except Exception:
            counts = {}

        domain_list.append({
            "handle": d.handle,
            "domain": d.domain,
            "display_name": d.display_name,
            "niche": d.niche,
            "language": d.language,
            "supabase_url": d.supabase_url,
            "is_synthesized": d.is_synthesized,
            "daily_pin_budget": d.daily_pin_budget,
            "keywords_file": str(d.keywords_file),
            "keyword_counts": counts,
            "credentials": {
                "pinterest": bool(
                    d.pinterest_email and d.pinterest_password.get_secret_value()
                ),
                "supabase": bool(
                    d.supabase_url and d.supabase_service_role_key.get_secret_value()
                ),
            },
        })

    logger.info("list_domains: found %d domain(s): %s", len(all_domains), [d.handle for d in all_domains])
    return {
        "domains": domain_list,
        "total": len(domain_list),
        "default_handle": registry.default_handle,
        "instruction": (
            "Work on ALL domains listed above unless the user restricts scope. "
            "Pick pending keywords from each domain independently and run the full pipeline per domain."
        ),
    }


@mcp.tool()
def multidomain_startup_brief(refresh_trends: bool = False) -> dict:
    """
    *** CALL THIS AT SESSION START AFTER list_domains ***

    Full startup audit across ALL configured domains simultaneously:
    - Checks credentials (Pinterest + Supabase) for each domain
    - Reports keyword roadmap health (pending / live / in-progress / failed)
    - Summarizes Pinterest queue depth per domain
    - Searches AgentMemory for recent failures or lessons per domain
    - Optionally refreshes trend keyword lists

    Returns a per-domain readiness summary so you can immediately begin
    multidomain content work without manual inspection.

    refresh_trends: set True to pull fresh Pinterest/Google News trends
                    before generating content (costs extra time).
    """
    from rankstein.domain import get_registry, reload_registry
    from rankstein.keyword_roadmap import keyword_counts, read_keyword_rows
    from pinterest_automation import get_job_queue

    reload_registry()
    registry = get_registry()
    all_domains = registry.all()

    briefings = []
    for d in all_domains:
        # Keyword health
        try:
            rows = read_keyword_rows(d.keywords_file) if d.keywords_file.exists() else []
            counts = keyword_counts(rows)
        except Exception as e:
            rows, counts = [], {"error": str(e)}

        # Queue health
        try:
            queue = get_job_queue(domain_handle=d.handle)
            queue_stats = queue.get_stats()
        except Exception as e:
            queue_stats = {"error": str(e)}

        # AgentMemory recent lessons
        try:
            hits = memory.search(
                f"RankStein {d.handle} {d.niche} failures lessons",
                limit=3,
            )
            memory_lessons = [h.get("content", "")[:120] for h in hits]
        except Exception:
            memory_lessons = []

        has_pinterest = bool(d.pinterest_email and d.pinterest_password.get_secret_value())
        has_supabase = bool(d.supabase_url and d.supabase_service_role_key.get_secret_value())

        pending_count = counts.get("Pending", 0)
        in_progress_count = counts.get("In Progress", 0)

        briefings.append({
            "handle": d.handle,
            "domain": d.domain,
            "display_name": d.display_name,
            "niche": d.niche,
            "ready": has_pinterest and has_supabase and pending_count > 0,
            "credentials": {"pinterest": has_pinterest, "supabase": has_supabase},
            "keyword_counts": counts,
            "pending_keywords": [r.keyword for r in rows if r.status.lower() == "pending"][:5],
            "in_progress_keywords": [r.keyword for r in rows if r.status.lower() == "in progress"],
            "queue": queue_stats,
            "memory_lessons": memory_lessons,
            "supabase_url": d.supabase_url,
            "daily_pin_budget": d.daily_pin_budget,
        })

    # Optionally refresh trends
    trend_report = None
    if refresh_trends:
        try:
            from rankstein.trend_intelligence import refresh_domain_trend_lists
            trend_report = refresh_domain_trend_lists(
                all_domains, limit_per_domain=10, append_to_roadmap=True
            )
        except Exception as e:
            trend_report = {"error": str(e)}

    ready_domains = [b["handle"] for b in briefings if b["ready"]]
    blocked_domains = [b["handle"] for b in briefings if not b["ready"]]

    logger.info(
        "multidomain_startup_brief: %d domains, %d ready, %d blocked",
        len(briefings), len(ready_domains), len(blocked_domains),
    )

    return {
        "summary": {
            "total_domains": len(briefings),
            "ready_for_work": ready_domains,
            "blocked": blocked_domains,
            "instruction": (
                "Process all ready domains. For blocked domains, check credentials. "
                "Always run the full pipeline (keyword → article → image → pin → publish) "
                "for EACH ready domain before cycling back."
            ),
        },
        "domains": briefings,
        "trends_refreshed": bool(trend_report and "error" not in trend_report),
        "trend_report": trend_report,
    }


@mcp.tool()
def process_pinterest_backlog(force_all: bool = False) -> dict:
    """
    Process memory/pinterest_backlog.md and enqueue ALL Failed/Pending/Missing entries
    into the job queue immediately — no prompting, no confirmation.

    Call this as part of the mandatory startup sequence after multidomain_startup_brief.
    Also called automatically when python run_autonomous.py starts.

    force_all: if True, re-enqueue entries already marked Queued.
    Returns: {enqueued: int, skipped_no_image: int, details: [...]}
    """
    import re
    import sys

    from pinterest_automation import get_config, get_job_queue
    from rankstein.domain import get_registry

    PROJECT_ROOT = Path(__file__).resolve().parent
    BACKLOG_FILE = PROJECT_ROOT / "memory" / "pinterest_backlog.md"

    if not BACKLOG_FILE.exists():
        return {"enqueued": 0, "skipped_no_image": 0, "message": "No backlog file found"}

    config = get_config()
    queue = get_job_queue()
    registry = get_registry()
    account_handles = sorted(config.accounts.keys())
    if not account_handles:
        return {"enqueued": 0, "skipped_no_image": 0, "error": "No Pinterest accounts configured"}

    MEDIA_DIR = PROJECT_ROOT / "data" / "media"
    REMASTER_DIR = MEDIA_DIR / "remaster_final"
    media_dirs = [REMASTER_DIR, MEDIA_DIR]

    def _find_image(slug: str) -> Path | None:
        import re as _re
        slug_u = slug.replace("-", "_")
        slug_n = slug.replace("-", "")
        for d in media_dirs:
            if not d.exists():
                continue
            for f in d.iterdir():
                if not f.is_file() or f.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
                    continue
                fname = f.name.lower()
                stripped = _re.sub(r"^(luxury|remastered(?:_v\d+_\w+)?)_", "", fname)
                if slug in stripped or slug in fname or slug_u in fname or slug_n in fname:
                    return f
        return None

    statuses = {"failed", "pending", "missing"}
    if force_all:
        statuses.add("queued")

    table_row = re.compile(
        r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(\w+)\s*\|", re.IGNORECASE
    )
    enqueued = 0
    skipped = 0
    details = []
    updated_lines = []

    lines = BACKLOG_FILE.read_text(encoding="utf-8").splitlines()
    for line in lines:
        m = table_row.match(line)
        if not m:
            updated_lines.append(line)
            continue

        slug, title, status = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        if slug.startswith("Article Slug") or slug.startswith("---"):
            updated_lines.append(line)
            continue

        if status.lower() not in statuses:
            updated_lines.append(line)
            continue

        best = _find_image(slug)
        if not best:
            skipped += 1
            details.append({"slug": slug, "status": "no_image"})
            updated_lines.append(line)
            continue

        domain = registry.default
        link = f"https://{domain.domain}/{slug}"
        board_map = getattr(domain, "boards_default", {})
        board = board_map.get("_default", config.default_board)
        slug_lower = slug.lower()
        for cat, brd in board_map.items():
            if cat != "_default" and cat.lower() in slug_lower:
                board = brd
                break

        desc = f"Aprende a preparar {title} paso a paso. Receta auténtica con fotos."

        for account_handle in account_handles:
            queue.enqueue_pin_upload(
                image_path=str(best),
                title=title[:100],
                description=desc[:499],
                link=link,
                board_name=board,
                priority=3,
                extra={
                    "slug": slug,
                    "account_handle": account_handle,
                    "domain_handle": domain.handle,
                    "source": "backlog_mcp",
                },
            )
            enqueued += 1

        updated_lines.append(line.replace(f"| {status} |", "| Queued |"))
        details.append({"slug": slug, "title": title, "status": "queued", "accounts": len(account_handles)})
        logger.info("process_pinterest_backlog: queued '%s'", slug)

    BACKLOG_FILE.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")

    logger.info(
        "process_pinterest_backlog: %d jobs enqueued, %d skipped (no image)", enqueued, skipped
    )
    return {
        "enqueued": enqueued,
        "skipped_no_image": skipped,
        "articles": enqueued // max(1, len(account_handles)),
        "accounts": len(account_handles),
        "details": details,
        "instruction": (
            "Backlog processed. Now call start_automation_supervisor to start the Pinterest worker, "
            "or check queue status with get_queue_status."
        ),
    }


@mcp.tool()
def start_automation_supervisor(dry_run: bool = False) -> dict:
    """
    Start the Pinterest automation supervisor in the background.

    This launches 'python run_autonomous.py run' as a non-blocking background process.
    The supervisor will process the queue for ALL domains and ALL Pinterest accounts.

    Call this after process_pinterest_backlog to begin pin uploads.
    dry_run: if True, returns the command that would be run without launching it.

    Returns: {launched: bool, pid: int | None, command: str}
    """
    import subprocess
    import sys

    PROJECT_ROOT = Path(__file__).resolve().parent
    cmd = [sys.executable, str(PROJECT_ROOT / "run_autonomous.py"), "run"]
    cmd_str = " ".join(cmd)

    if dry_run:
        return {"launched": False, "pid": None, "command": cmd_str, "dry_run": True}

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        logger.info("start_automation_supervisor: launched pid=%d", proc.pid)
        return {
            "launched": True,
            "pid": proc.pid,
            "command": cmd_str,
            "instruction": (
                "Supervisor started. It will process the job queue for all domains. "
                "Monitor via get_queue_status or check data/logs/automation.log."
            ),
        }
    except Exception as e:
        logger.error("start_automation_supervisor: failed to launch: %s", e)
        return {"launched": False, "pid": None, "error": str(e), "command": cmd_str}


# ═══════════════════════════════════════════════════════════════════════════════
# KEYWORD TOOLS
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def debug_mcp_state() -> dict:
    """Debug tool to check server paths and module locations."""
    import news_scraper

    return {
        "sys_path": sys.path,
        "news_scraper_file": getattr(news_scraper, "__file__", "unknown"),
        "project_root": str(PROJECT_ROOT),
    }


@mcp.tool()
def debug_supabase_env() -> dict:
    """Debug tool to check Supabase environment variables."""
    return {
        "SUPABASE_URL": os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "NOT_SET"),
        "SUPABASE_KEY": os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "NOT_SET"),
    }


# Dummy comment to force reload - word count policy updated to 900-1500
@mcp.tool()
def get_pending_keyword(domain_handle: str = "") -> dict:
    """
    Read keywords.md and return the next keyword to process.
    Priority: High+Pending first, then auto-promotes first Medium+Pending to High.
    Returns: {keyword, cluster, priority} or {keyword: null} if nothing pending.
    """
    domain = get_registry().get(domain_handle)
    kw_file = domain.keywords_file
    if not kw_file.exists():
        return {"keyword": None, "cluster": None, "error": f"keywords file not found for {domain.handle}"}

    lines = kw_file.read_text(encoding="utf-8").splitlines()

    # Pass 1: High + Pending
    for line in lines:
        if "Pending" in line and "High" in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) > 2 and parts[1]:
                return {"keyword": parts[1], "cluster": parts[2], "priority": "High", "domain": domain.handle}

    # Pass 2: Auto-promote Medium + Pending
    for line in lines:
        if "Pending" in line and "Medium" in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) > 2 and parts[1]:
                keyword = parts[1]
                _update_keyword_field(keyword, priority="High", kw_file=kw_file)
                return {
                    "keyword": keyword,
                    "cluster": parts[2],
                    "priority": "High",
                    "auto_promoted": True,
                    "domain": domain.handle,
                }

    return {"keyword": None, "cluster": None, "message": f"No pending keywords for {domain.handle}"}


@mcp.tool()
def mark_keyword_status(keyword: str, status: str, domain_handle: str = "") -> dict:
    """
    Update a keyword's status in keywords.md.
    status: 'In Progress' | 'Live' | 'Failed' | 'Pending' | 'Staged'
    Auto-abandons keywords that fail 3+ times to prevent infinite retry loops.
    """
    domain = get_registry().get(domain_handle)
    kw_file = domain.keywords_file

    if status == "Failed":
        count = _increment_fail_count(keyword, domain_handle=domain.handle)
        logger.warning(f"Keyword '{keyword}' (domain={domain.handle}) failed (attempt #{count})")
        if count >= 3:
            _update_keyword_field(keyword, status="Failed", kw_file=kw_file)
            logger.error(
                f"Keyword '{keyword}' (domain={domain.handle}) auto-abandoned after {count} failures"
            )
            return {
                "success": True,
                "keyword": keyword,
                "status": "Abandoned",
                "fail_count": count,
                "domain": domain.handle,
                "message": f"Auto-abandoned after {count} failures. Delete entry from data/keyword_failures.json to retry.",
            }
    elif status == "Live":
        _clear_fail_count(keyword, domain_handle=domain.handle)
    result = _update_keyword_field(keyword, status=status, kw_file=kw_file)
    logger.info(f"Keyword '{keyword}' (domain={domain.handle}) -> {status} (success={result})")
    return {"success": result, "keyword": keyword, "status": status, "domain": domain.handle}


@mcp.tool()
def list_keywords(domain_handle: str = "") -> dict:
    """Return all keywords from keywords.md with their priority and status."""
    domain = get_registry().get(domain_handle)
    kw_file = domain.keywords_file
    if not kw_file.exists():
        return {"error": f"keywords file not found for {domain.handle}"}
    rows = []
    for line in kw_file.read_text(encoding="utf-8").splitlines():
        if "|" in line and (
            "Pending" in line
            or "Live" in line
            or "In Progress" in line
            or "Failed" in line
            or "Staged" in line
        ):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 7 and parts[1]:
                rows.append(
                    {
                        "keyword": parts[1],
                        "cluster": parts[2],
                        "source": parts[3],
                        "target": parts[4],
                        "priority": parts[5],
                        "status": parts[6],
                    }
                )
    return {"keywords": rows, "total": len(rows), "domain": domain.handle}


@mcp.tool()
def refresh_trend_keywords(domain_handle: str = "", limit: int = 10, append_to_roadmap: bool = True) -> dict:
    """
    Refresh daily Pinterest trend intelligence for one domain or every domain.

    Uses the project Playwright browser automation layer first to search
    Pinterest Trends/Search by domain niche, validates candidates against
    Google News RSS, writes daily best keyword reports, and optionally appends
    unique Pending rows to each domain roadmap.
    """
    from rankstein.trend_intelligence import refresh_domain_trend_lists

    registry = get_registry()
    domains = [registry.get(domain_handle)] if domain_handle else registry.all()
    return refresh_domain_trend_lists(
        domains,
        limit_per_domain=max(1, limit),
        append_to_roadmap=append_to_roadmap,
        use_playwright=True,
    )


def _update_keyword_field(
    keyword: str, priority: str = None, status: str = None, kw_file: Path = None
) -> bool:
    if kw_file is None:
        kw_file = KEYWORDS_FILE
    if not kw_file.exists():
        return False
    content = kw_file.read_text(encoding="utf-8")
    lines = content.split("\n")
    changed = False
    for i, line in enumerate(lines):
        if f"| {keyword} |" in line:
            parts = line.split("|")
            if len(parts) >= 7:
                if priority:
                    parts[-3] = f" {priority} "
                if status:
                    parts[-2] = f" {status} "
                lines[i] = "|".join(parts)
                changed = True
            break
    if changed:
        kw_file.write_text("\n".join(lines), encoding="utf-8")
    return changed


def _load_failures() -> dict:
    """Load keyword failure counts from persistent JSON file."""
    if FAILURES_FILE.exists():
        try:
            return json.loads(FAILURES_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_failures(data: dict):
    """Persist keyword failure counts."""
    FAILURES_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _increment_fail_count(keyword: str, domain_handle: str = "") -> int:
    """Increment and return failure count for a keyword (domain-aware)."""
    domain = get_registry().get(domain_handle)
    key = f"{domain.handle}:{keyword}"
    failures = _load_failures()
    failures[key] = failures.get(key, 0) + 1
    _save_failures(failures)
    return failures[key]


def _clear_fail_count(keyword: str, domain_handle: str = ""):
    """Clear failure count when a keyword succeeds (domain-aware)."""
    domain = get_registry().get(domain_handle)
    key = f"{domain.handle}:{keyword}"
    failures = _load_failures()
    if key in failures:
        del failures[key]
        _save_failures(failures)


# ═══════════════════════════════════════════════════════════════════════════════
# NEWS SCRAPING & CONTENT PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

# Import news scraper module
import importlib as _importlib
import sys as _sys

_sys.path.insert(0, str(PROJECT_ROOT / "backend" / "services"))
try:
    import news_scraper

    _importlib.reload(news_scraper)
    from news_scraper import (
        extract_article as _extract,
    )
    from news_scraper import (
        scrape_google_news as _scrape_news,
    )
    from news_scraper import (
        validate_article as _validate,
    )

    _NEWS_AVAILABLE = True
except ImportError as _ie:
    logger.warning("news_scraper module not available: %s", _ie)
    _NEWS_AVAILABLE = False


@mcp.tool()
def scrape_news_sources(keyword: str, language: str = "es", count: int = 5) -> dict:
    """
    Scrape Google News for articles about a keyword.
    Returns top articles with title, url, snippet, source, date.
    Uses fallback chain: Google News RSS → DuckDuckGo → empty.
    Call this BEFORE generating content to get real source material.
    """
    if not _NEWS_AVAILABLE:
        return {
            "success": False,
            "error": "news_scraper module not installed. Check backend/services/news_scraper.py",
        }
    try:
        results = _scrape_news(keyword, lang=language, count=count)
        logger.info("scrape_news_sources('%s') returned %d results", keyword, len(results))
        return {"success": True, "keyword": keyword, "count": len(results), "articles": results}
    except Exception as e:
        logger.error("scrape_news_sources failed: %s", e)
        return {"success": False, "error": str(e)}


@mcp.tool()
def extract_article_content(url: str) -> dict:
    """
    Extract full article text from any URL.
    Multi-strategy extraction: <article> tag → CSS selectors → largest block → all <p>.
    Returns: {success, title, content, author, date, word_count, key_sections}
    Use the extracted content as SOURCE MATERIAL for rewriting — never copy verbatim.
    """
    if not _NEWS_AVAILABLE:
        return {"success": False, "error": "news_scraper module not installed"}
    try:
        result = _extract(url)
        if result.get("success"):
            logger.info("Extracted %d words from %s", result.get("word_count", 0), url)
        else:
            logger.warning("Extraction failed for %s: %s", url, result.get("error"))
        return result
    except Exception as e:
        logger.error("extract_article_content failed: %s", e)
        return {"success": False, "error": str(e), "url": url}


@mcp.tool()
def validate_article_quality(article_json: str) -> dict:
    """
    HARD pre-publish quality gate. Returns ``success=False`` when the article
    fails — the caller MUST treat this as a blocking error and revise the
    article before calling ``publish_article_to_supabase``.

    Scored on:
      - Word count (min 900, target 1200-1500)
      - E-E-A-T authority citations (AESAN, EFSA)
      - Humanization markers (first-person, anecdotes)
      - Structure (headings, bold text)
      - Excerpt, category, schema completeness
      - Unreplaced placeholders

    Returns:
      {success, score, passed, word_count, issues[], recommendations[],
       revision_feedback (when failed) — copy-pasteable instructions for
       revision}.

    Workflow:
      1. Call this with the generated article_json.
      2. If ``success=False``: read ``revision_feedback`` and ``issues``,
         revise the article, call again. Up to 3 revision attempts.
      3. Only proceed to publish_article_to_supabase when ``success=True``.
    """
    if not _NEWS_AVAILABLE:
        return {"success": False, "error": "news_scraper module not installed"}
    try:
        data = json.loads(article_json) if isinstance(article_json, str) else article_json
        result = _validate(data)
        passed = bool(result.get("passed"))
        result["success"] = passed
        logger.info(
            "validate_article_quality: score=%d passed=%s issues=%d",
            result.get("score", 0),
            passed,
            len(result.get("issues", [])),
        )
        if not passed:
            issues = result.get("issues", [])
            recs = result.get("recommendations", [])
            feedback_lines = [
                f"Article FAILED quality gate (score={result.get('score', 0)}).",
                "You MUST revise the article and re-call validate_article_quality before publishing.",
                "",
                "Issues to address:",
            ]
            feedback_lines.extend(f"  - {iss}" for iss in issues)
            if recs:
                feedback_lines.append("")
                feedback_lines.append("Recommendations:")
                feedback_lines.extend(f"  - {r}" for r in recs)
            result["revision_feedback"] = "\n".join(feedback_lines)
        return result
    except json.JSONDecodeError as e:
        return {
            "success": False,
            "score": 0,
            "passed": False,
            "issues": [f"Invalid JSON: {e}"],
            "recommendations": ["Fix JSON syntax (likely a quoting/escape error) and re-call this tool."],
        }
    except Exception as e:
        logger.error("validate_article_quality failed: %s", e)
        return {
            "success": False,
            "score": 0,
            "passed": False,
            "issues": [str(e)],
            "recommendations": [],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# IMAGE TOOLS  (NanoBanana / Editorial Overlay)
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def apply_luxury_overlay(image_path: str, title_text: str, brand: str = "RECETA GENIAL | 2026") -> dict:
    """
    Apply the Luxury V3 editorial overlay (NanoBanana style) to an image.
    Creates a 1000x1500 vertical Pinterest pin with gold border card and CTA.
    Returns: {output_path, success}
    """
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont

        src = Path(image_path)
        if not src.exists():
            return {"success": False, "error": f"Image not found: {image_path}"}

        with Image.open(src) as img:
            if img.mode != "RGBA":
                img = img.convert("RGBA")

            W, H = 1000, 1500
            bg = img.resize((W, H), Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(15))
            img.thumbnail((900, 1300), Image.Resampling.LANCZOS)
            x = (W - img.size[0]) // 2
            y = (H - img.size[1]) // 2 - 100
            bg.paste(img, (x, y), img if img.mode == "RGBA" else None)

            canvas = bg
            draw = ImageDraw.Draw(canvas)

            # Floating card
            cw, ch = 920, 480
            cx = (W - cw) // 2
            cy = H - ch - 40
            draw.rectangle([cx + 5, cy + 5, cx + cw + 5, cy + ch + 5], fill=(0, 0, 0, 80))
            draw.rectangle([cx, cy, cx + cw, cy + ch], fill=(255, 255, 255, 245))
            draw.rectangle([cx + 10, cy + 10, cx + cw - 10, cy + ch - 10], outline="#D4AF37", width=2)

            try:
                font_brand = ImageFont.truetype("arial.ttf", 30)
                font_title = ImageFont.truetype("georgia.ttf", 85)
            except Exception:
                font_brand = ImageFont.load_default(size=30)
                font_title = ImageFont.load_default(size=60)

            # Brand header
            bb = draw.textbbox((0, 0), brand, font=font_brand)
            draw.text(((W - (bb[2] - bb[0])) // 2, cy + 30), brand, font=font_brand, fill="#D4AF37")

            # Title (max 3 lines)
            clean = title_text.replace(":", "").upper()
            for idx, line in enumerate(textwrap.wrap(clean, width=15)[:3]):
                tb = draw.textbbox((0, 0), line, font=font_title)
                draw.text(
                    ((W - (tb[2] - tb[0])) // 2, cy + 90 + idx * 100), line, font=font_title, fill="#1a1a1a"
                )

            # CTA button
            cta = "TOCA PARA VER LA RECETA"
            cb = draw.textbbox((0, 0), cta, font=font_brand)
            draw.rectangle([W // 2 - 200, cy + ch - 80, W // 2 + 200, cy + ch - 30], fill="#E60023")
            draw.text(((W - (cb[2] - cb[0])) // 2, cy + ch - 70), cta, font=font_brand, fill="white")

            out = REMASTER_DIR / f"remastered_{src.name.replace('.png', '.jpg')}"
            canvas.convert("RGB").save(str(out), "JPEG", quality=95)

        return {"success": True, "output_path": str(out)}

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def inject_exif_metadata(image_path: str, title: str, description: str, keywords: str) -> dict:
    """
    Inject SEO EXIF metadata (Title, Description, Keywords) into a JPEG image.

    Non-JPEG inputs (PNG/WEBP/GIF) are transparently re-encoded as JPEG quality
    95 with a white background, then EXIF is injected on the JPEG. The new path
    is returned in ``output_path`` (replaces the original on disk via different
    extension; the original file is removed).

    Returns: {success, message, output_path}
    """
    try:
        import piexif
        from PIL import Image

        src = Path(image_path)
        if not src.exists():
            return {"success": False, "error": f"image not found: {image_path}"}

        if src.suffix.lower() in (".jpg", ".jpeg"):
            jpeg_path = src
        else:
            jpeg_path = src.with_suffix(".jpg")
            with Image.open(src) as im:
                if im.mode in ("RGBA", "LA", "P"):
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    rgba = im.convert("RGBA")
                    bg.paste(rgba, mask=rgba.split()[-1])
                    im_to_save = bg
                else:
                    im_to_save = im.convert("RGB")
                im_to_save.save(str(jpeg_path), "JPEG", quality=95)
            try:
                src.unlink()
            except OSError:
                pass

        exif = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "Interop": {}}
        exif["0th"][piexif.ImageIFD.ImageDescription] = description.encode("utf-8")
        exif["0th"][piexif.ImageIFD.XPTitle] = title.encode("utf-16le")
        exif["0th"][piexif.ImageIFD.XPComment] = description.encode("utf-16le")
        exif["0th"][piexif.ImageIFD.XPKeywords] = keywords.encode("utf-16le")
        piexif.insert(piexif.dump(exif), str(jpeg_path))
        return {
            "success": True,
            "message": f"EXIF injected into {jpeg_path.name}",
            "output_path": str(jpeg_path),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


_IMAGE_MAGIC = {
    b"\xff\xd8\xff": "jpg",
    b"\x89PNG\r\n\x1a\n": "png",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
    b"RIFF": "webp",  # actually WEBP container starts RIFF....WEBP
}


def _detect_image_extension(raw: bytes) -> str:
    """Sniff magic bytes to pick the correct extension. Defaults to jpg."""
    for magic, ext in _IMAGE_MAGIC.items():
        if raw.startswith(magic):
            if ext == "webp" and len(raw) >= 12 and raw[8:12] == b"WEBP":
                return "webp"
            elif ext != "webp":
                return ext
    return "jpg"  # safe default — most generators return JPEG


_MIN_HERO_WIDTH = 1280
_MIN_HERO_HEIGHT = 800


def _validate_image_dimensions(path: Path) -> tuple[bool, str, int, int]:
    """Open with PIL and assert min dimensions. Returns (ok, error, width, height)."""
    try:
        from PIL import Image

        with Image.open(path) as im:
            w, h = im.size
    except Exception as e:
        return False, f"PIL could not open image: {e}", 0, 0
    if w < _MIN_HERO_WIDTH or h < _MIN_HERO_HEIGHT:
        return False, f"image too small: {w}x{h} (min {_MIN_HERO_WIDTH}x{_MIN_HERO_HEIGHT})", w, h
    return True, "", w, h


@mcp.tool()
def save_image_from_base64(
    base64_data: str,
    slug: str,
    suffix: str = "hero",
    min_bytes: int = 5000,
) -> dict:
    """
    Save a base64-encoded image (e.g. from Antigravity's Nano Banana output, or
    Gemini CLI image generation) to disk under nanobanana-output/.

    Accepts:
      - Raw base64 string ("iVBORw0KGgo...")
      - Data URL ("data:image/png;base64,iVBORw0KGgo...")
      - Whitespace / newlines anywhere (stripped)

    Auto-detects image format from magic bytes so PNGs aren't saved as .jpg.
    Rejects images smaller than ``min_bytes`` (default 5 KB — production heroes
    are 50 KB+; lower for tests) and images smaller than 800x600 pixels so a
    truncated/refused generation cannot be silently published as a hero.

    Returns: {success, output_path, format, size_bytes, width, height}
    """
    import base64 as _b64

    try:
        raw_str = (base64_data or "").strip()
        if not raw_str:
            return {"success": False, "error": "base64_data is empty"}

        if raw_str.startswith("data:"):
            comma = raw_str.find(",")
            if comma == -1:
                return {"success": False, "error": "Malformed data URL (no comma)"}
            raw_str = raw_str[comma + 1 :]

        raw_str = "".join(raw_str.split())

        try:
            data = _b64.b64decode(raw_str, validate=False)
        except Exception as e:
            return {"success": False, "error": f"base64 decode failed: {e}"}

        if len(data) < min_bytes:
            return {
                "success": False,
                "error": f"Decoded image suspiciously small ({len(data)} bytes < {min_bytes}); likely not a real image",
            }

        ext = _detect_image_extension(data)
        out = OUTPUT_DIR / f"{slug}-{suffix}.{ext}"
        out.write_bytes(data)

        ok, dim_err, w, h = _validate_image_dimensions(out)
        if not ok:
            try:
                out.unlink()
            except OSError:
                pass
            return {"success": False, "error": dim_err}

        logger.info(
            f"save_image_from_base64: saved {len(data):,} bytes -> {out.name} (format={ext}, {w}x{h})"
        )
        return {
            "success": True,
            "output_path": str(out),
            "format": ext,
            "size_bytes": len(data),
            "width": w,
            "height": h,
        }
    except Exception as e:
        logger.error(f"save_image_from_base64 failed: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
def save_image_from_path(
    source_path: str,
    slug: str,
    suffix: str = "hero",
    convert_to_jpeg: bool = True,
    min_bytes: int = 5000,
) -> dict:
    """
    Ingest an image file written to disk by Antigravity's native image-generation
    tool (or any external generator) into nanobanana-output/. Use this when the
    native tool returns a file path instead of inline base64.

    If ``convert_to_jpeg`` is True (default), PNG/WEBP/GIF inputs are re-encoded
    as JPEG quality 95 with a white background — this keeps the downstream EXIF
    injection happy. JPEGs are copied byte-for-byte. The source file is left in
    place.

    Same dimension/size guards as ``save_image_from_base64`` (min 800x600,
    min ``min_bytes`` raw bytes).

    Returns: {success, output_path, format, size_bytes, width, height}
    """
    try:
        from PIL import Image

        src = Path(source_path)
        if not src.exists():
            return {"success": False, "error": f"source_path not found: {source_path}"}
        if not src.is_file():
            return {"success": False, "error": f"source_path is not a file: {source_path}"}

        raw = src.read_bytes()
        if len(raw) < min_bytes:
            return {
                "success": False,
                "error": f"Source image suspiciously small ({len(raw)} bytes < {min_bytes})",
            }

        sniffed = _detect_image_extension(raw)

        if convert_to_jpeg and sniffed != "jpg":
            with Image.open(src) as im:
                if im.mode in ("RGBA", "LA", "P"):
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    rgba = im.convert("RGBA")
                    bg.paste(rgba, mask=rgba.split()[-1])
                    im_to_save = bg
                else:
                    im_to_save = im.convert("RGB")
                out = OUTPUT_DIR / f"{slug}-{suffix}.jpg"
                im_to_save.save(str(out), "JPEG", quality=95)
            ext = "jpg"
        else:
            ext = sniffed
            out = OUTPUT_DIR / f"{slug}-{suffix}.{ext}"
            out.write_bytes(raw)

        ok, dim_err, w, h = _validate_image_dimensions(out)
        if not ok:
            try:
                out.unlink()
            except OSError:
                pass
            return {"success": False, "error": dim_err}

        size_bytes = out.stat().st_size
        logger.info(
            f"save_image_from_path: ingested {src.name} -> {out.name} "
            f"(format={ext}, {w}x{h}, {size_bytes:,} bytes)"
        )
        return {
            "success": True,
            "output_path": str(out),
            "format": ext,
            "size_bytes": size_bytes,
            "width": w,
            "height": h,
        }
    except Exception as e:
        logger.error(f"save_image_from_path failed: {e}")
        return {"success": False, "error": str(e)}


_POLLINATIONS_MIN_RAW_WIDTH = 800
_POLLINATIONS_MIN_RAW_HEIGHT = 500


@mcp.tool()
def create_hero_image_pollinations(
    prompt: str,
    slug: str,
    suffix: str = "hero",
    width: int = 1920,
    height: int = 1280,
    model: str = "flux",
    enhance: bool = True,
    seed: int = 0,
    upscale_if_smaller: bool = True,
    timeout_seconds: int = 120,
) -> dict:
    """
    Fallback hero generator using Pollinations.ai (free, keyless). Use this only
    when Antigravity's native image generation is unavailable or returns a
    too-small image.

    Sends ``prompt`` to https://image.pollinations.ai, downloads the resulting
    JPEG, and persists it via the same path/dimension/byte-floor pipeline as
    save_image_from_path. Default 1920x1280 / model=flux / enhance=true gives
    high-resolution editorial-quality output that clears the 1280x800 floor.

    model: "flux" (default, photoreal), "flux-realism", "flux-3d", "turbo".
    enhance: when True, Pollinations applies prompt enhancement.
    seed: pass non-zero to get reproducible output; 0 lets Pollinations randomize.

    Returns: {success, output_path, format, size_bytes, width, height}
    """
    try:
        import urllib.parse as _urlparse

        clean_prompt = (prompt or "").strip()
        if not clean_prompt:
            return {"success": False, "error": "prompt is empty"}

        encoded = _urlparse.quote(clean_prompt, safe="")
        url = f"https://image.pollinations.ai/prompt/{encoded}"
        params: dict = {
            "width": int(width),
            "height": int(height),
            "nologo": "true",
            "model": model,
            "enhance": "true" if enhance else "false",
        }
        if seed:
            params["seed"] = int(seed)

        logger.info(
            f"create_hero_image_pollinations: requesting {width}x{height} "
            f"model={model} enhance={enhance} prompt={clean_prompt[:80]}..."
        )
        resp = requests.get(url, params=params, timeout=timeout_seconds, allow_redirects=True)
        resp.raise_for_status()
        data = resp.content

        if len(data) < 5000:
            return {
                "success": False,
                "error": f"Pollinations returned suspiciously small payload ({len(data)} bytes)",
            }

        ext = _detect_image_extension(data)
        out = OUTPUT_DIR / f"{slug}-{suffix}.{ext}"
        out.write_bytes(data)

        # Pre-upscale "real source" check — reject obviously-junk small payloads
        # before we'd otherwise paper over them with LANCZOS.
        try:
            from PIL import Image as _PILImage

            with _PILImage.open(out) as _im0:
                raw_w, raw_h = _im0.size
        except Exception as e:
            try:
                out.unlink()
            except OSError:
                pass
            return {"success": False, "error": f"PIL could not open Pollinations output: {e}"}

        if raw_w < _POLLINATIONS_MIN_RAW_WIDTH or raw_h < _POLLINATIONS_MIN_RAW_HEIGHT:
            try:
                out.unlink()
            except OSError:
                pass
            return {
                "success": False,
                "error": f"Pollinations source too small: {raw_w}x{raw_h} "
                f"(need ≥{_POLLINATIONS_MIN_RAW_WIDTH}x{_POLLINATIONS_MIN_RAW_HEIGHT} before upscale)",
            }

        # Pollinations free caps near ~1024 px max edge; LANCZOS-upscale to the
        # requested target so the rest of the pipeline (Pinterest pin, OG image,
        # blog hero) gets the dimensions it needs.
        upscaled = False
        if upscale_if_smaller and (raw_w < width or raw_h < height):
            try:
                from PIL import Image as _PILImage

                with _PILImage.open(out) as _im:
                    rgb = _im.convert("RGB")
                    rgb = rgb.resize((int(width), int(height)), _PILImage.Resampling.LANCZOS)
                    out_jpg = out.with_suffix(".jpg")
                    rgb.save(str(out_jpg), "JPEG", quality=95)
                if out_jpg != out:
                    try:
                        out.unlink()
                    except OSError:
                        pass
                out = out_jpg
                ext = "jpg"
                upscaled = True
            except Exception as e:
                try:
                    out.unlink()
                except OSError:
                    pass
                return {"success": False, "error": f"upscale failed: {e}"}

        ok, dim_err, w, h = _validate_image_dimensions(out)
        if not ok:
            try:
                out.unlink()
            except OSError:
                pass
            return {"success": False, "error": dim_err}

        size_bytes = out.stat().st_size
        logger.info(
            f"create_hero_image_pollinations: saved {size_bytes:,} bytes -> "
            f"{out.name} (format={ext}, raw={raw_w}x{raw_h}, "
            f"final={w}x{h}, upscaled={upscaled})"
        )
        return {
            "success": True,
            "output_path": str(out),
            "format": ext,
            "size_bytes": size_bytes,
            "width": w,
            "height": h,
            "raw_width": raw_w,
            "raw_height": raw_h,
            "upscaled": upscaled,
        }
    except requests.RequestException as e:
        logger.error(f"create_hero_image_pollinations HTTP error: {e}")
        return {"success": False, "error": f"Pollinations HTTP error: {e}"}
    except Exception as e:
        logger.error(f"create_hero_image_pollinations failed: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# PINTEREST PIN LIFECYCLE TOOLS
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def create_article_pin(
    hero_image_path: str,
    title_text: str,
    subtitle: str = "",
    brand: str = "RECETA GENIAL | 2026",
    cta_text: str = "TOCA PARA VER LA RECETA",
    style_variant: str = "classic",
) -> dict:
    """
    Generate a Luxury V3 editorial Pinterest pin (1000x1500) from the article's
    hero image. This is the ARTICLE-SPECIFIC pin that gets uploaded to Pinterest
    and embedded as an iframe in the blog post.

    style_variant: 'classic' (gold border), 'dark' (charcoal card), 'warm' (terracotta accent)
    Returns: {success, output_path}
    """
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont

        src = Path(hero_image_path)
        if not src.exists():
            return {"success": False, "error": f"Hero image not found: {hero_image_path}"}

        with Image.open(src) as img:
            if img.mode != "RGBA":
                img = img.convert("RGBA")

            W, H = 1000, 1500

            # Style variants for subtle design diversity
            styles = {
                "classic": {
                    "card_bg": (255, 255, 255, 245),
                    "border": "#D4AF37",
                    "title_fill": "#1a1a1a",
                    "brand_fill": "#D4AF37",
                    "cta_bg": "#E60023",
                    "cta_text": "white",
                    "shadow": (0, 0, 0, 80),
                },
                "dark": {
                    "card_bg": (30, 30, 30, 240),
                    "border": "#D4AF37",
                    "title_fill": "#FFFFFF",
                    "brand_fill": "#D4AF37",
                    "cta_bg": "#D4AF37",
                    "cta_text": "#1a1a1a",
                    "shadow": (0, 0, 0, 120),
                },
                "warm": {
                    "card_bg": (255, 248, 240, 245),
                    "border": "#C67B3C",
                    "title_fill": "#3D1C00",
                    "brand_fill": "#C67B3C",
                    "cta_bg": "#E60023",
                    "cta_text": "white",
                    "shadow": (0, 0, 0, 80),
                },
            }
            s = styles.get(style_variant, styles["classic"])

            # Background: blurred hero stretched to pin dimensions
            bg = img.resize((W, H), Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(18))
            # Sharp hero overlay centered in top 2/3
            img.thumbnail((920, 950), Image.Resampling.LANCZOS)
            x = (W - img.size[0]) // 2
            y = max(30, (950 - img.size[1]) // 2)
            bg.paste(img, (x, y), img if img.mode == "RGBA" else None)

            canvas = bg
            draw = ImageDraw.Draw(canvas)

            # Floating card in bottom third
            cw, ch = 920, 480
            cx = (W - cw) // 2
            cy = H - ch - 40

            # Drop shadow
            draw.rectangle([cx + 5, cy + 5, cx + cw + 5, cy + ch + 5], fill=s["shadow"])
            # Card background
            draw.rectangle([cx, cy, cx + cw, cy + ch], fill=s["card_bg"])
            # Gold/accent border inset
            draw.rectangle([cx + 10, cy + 10, cx + cw - 10, cy + ch - 10], outline=s["border"], width=2)

            # Fonts
            try:
                font_brand = ImageFont.truetype("arial.ttf", 28)
                font_title = ImageFont.truetype("georgia.ttf", 80)
                font_sub = ImageFont.truetype("arial.ttf", 26)
                font_cta = ImageFont.truetype("arial.ttf", 28)
            except Exception:
                font_brand = ImageFont.load_default(size=28)
                font_title = ImageFont.load_default(size=55)
                font_sub = ImageFont.load_default(size=24)
                font_cta = ImageFont.load_default(size=28)

            # Brand header
            bb = draw.textbbox((0, 0), brand, font=font_brand)
            draw.text(((W - (bb[2] - bb[0])) // 2, cy + 25), brand, font=font_brand, fill=s["brand_fill"])

            # Title (max 3 lines, uppercase)
            clean = title_text.replace(":", "").upper()
            lines = textwrap.wrap(clean, width=16)[:3]
            for idx, line in enumerate(lines):
                tb = draw.textbbox((0, 0), line, font=font_title)
                draw.text(
                    ((W - (tb[2] - tb[0])) // 2, cy + 75 + idx * 95),
                    line,
                    font=font_title,
                    fill=s["title_fill"],
                )

            # Optional subtitle
            if subtitle:
                sub_clean = subtitle[:60]
                sb = draw.textbbox((0, 0), sub_clean, font=font_sub)
                sub_y = cy + 75 + len(lines) * 95 + 5
                draw.text(((W - (sb[2] - sb[0])) // 2, sub_y), sub_clean, font=font_sub, fill=s["brand_fill"])

            # CTA button
            cb = draw.textbbox((0, 0), cta_text, font=font_cta)
            btn_w = (cb[2] - cb[0]) + 60
            btn_x = (W - btn_w) // 2
            draw.rectangle([btn_x, cy + ch - 80, btn_x + btn_w, cy + ch - 35], fill=s["cta_bg"])
            draw.text(((W - (cb[2] - cb[0])) // 2, cy + ch - 75), cta_text, font=font_cta, fill=s["cta_text"])

            # Save
            stem = src.stem.replace("-hero", "")
            out = OUTPUT_DIR / f"{stem}-pin.jpg"
            canvas.convert("RGB").save(str(out), "JPEG", quality=95)

        logger.info(f"Created article pin: {out.name} (style={style_variant})")
        return {"success": True, "output_path": str(out)}

    except Exception as e:
        logger.error(f"create_article_pin failed: {e}")
        return {"success": False, "error": str(e)}


async def gemini_heal_selector(page, target_description: str) -> str:
    js_code = """
    () => {
        const elements = [];
        const selectors = ['input', 'textarea', 'select', 'button', 'a', '[role="button"]', '[role="textbox"]', '[role="checkbox"]', '[role="radio"]', '[contenteditable="true"]'];
        
        for (const sel of selectors) {
            try {
                const els = document.querySelectorAll(sel);
                for (const el of els) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        const style = window.getComputedStyle(el);
                        if (style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0') {
                            elements.push({
                                tag: el.tagName.toLowerCase(),
                                type: el.type || '',
                                name: el.name || '',
                                id: el.id || '',
                                className: el.className || '',
                                placeholder: el.placeholder || '',
                                ariaLabel: el.getAttribute('aria-label') || '',
                                text: (el.innerText || '').substring(0, 50),
                                selector: ''
                            });
                        }
                    }
                }
            } catch(e) {}
        }
        
        // Generate unique selectors
        for (let i = 0; i < elements.length; i++) {
            const el = elements[i];
            if (el.id) {
                elements[i].selector = `#${el.id}`;
            } else if (el.name) {
                elements[i].selector = `${el.tag}[name="${el.name}"]`;
            } else if (el.className && typeof el.className === 'string') {
                const cls = el.className.split(' ')[0];
                if (cls) elements[i].selector = `${el.tag}.${cls}`;
            }
        }
        
        return JSON.stringify(elements.slice(0, 50));
    }
    """
    try:
        dom_context = await page.evaluate(js_code)
    except Exception as e:
        logger.warning(f"Failed to extract elements for self-healing: {e}")
        return ""

    if not dom_context or dom_context == "[]":
        return ""

    prompt = f"""You are an expert Playwright automation engineer.
The standard locator for "{target_description}" on Pinterest just failed.

Here is a JSON list of all visible interactive elements currently on the page:
```json
{dom_context}
```

Identify the single element that most likely represents "{target_description}".
Return ONLY a valid Playwright CSS selector string that will uniquely match this element.
DO NOT wrap the response in code blocks, quotes, or JSON. Just return the raw selector string.
Example valid responses:
input[name="title"]
div[role="textbox"]
textarea[id="pin-draft-alttext"]
"""
    gemini_path = _resolve_gemini_cli()
    if not gemini_path:
        # Single, actionable warning instead of repeated WinError 2 spam.
        # Operators can set GEMINI_CLI_PATH to point at the executable directly
        # if `shutil.which("gemini")` can't find it (common when the MCP server
        # is spawned from a parent process whose PATH differs).
        logger.warning(
            "Self-healing skipped: gemini CLI not found on PATH. "
            "Set GEMINI_CLI_PATH=<absolute path to gemini.cmd|gemini.exe> in .env to enable."
        )
        return ""
    try:
        import subprocess

        logger.info(f"Invoking Gemini CLI self-healing for: {target_description}...")
        env = os.environ.copy()
        if env.get("GEMINI_API_KEY") and not env.get("GOOGLE_API_KEY"):
            env["GOOGLE_API_KEY"] = env["GEMINI_API_KEY"]
        elif env.get("GOOGLE_API_KEY") and not env.get("GEMINI_API_KEY"):
            env["GEMINI_API_KEY"] = env["GOOGLE_API_KEY"]
        model = os.environ.get("RANKSTEIN_FALLBACK_MODEL", "auto")
        cmd = [gemini_path, "-p", prompt]
        if model.lower() != "auto":
            cmd.extend(["--model", model])
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=45,
            env=env,
        )
        selector = result.stdout.strip().strip("`").strip('"').strip("'")
        if "\n" in selector or len(selector) > 150:
            logger.warning(f"Gemini returned invalid selector format: {selector[:50]}...")
            return ""
        logger.info(f"Gemini proposed new selector: {selector}")
        return selector
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or "").strip()[-500:]
        logger.warning(f"Gemini self-healing failed: {e}; stderr={stderr_tail}")
        return ""
    except Exception as e:
        logger.warning(f"Gemini self-healing failed: {e}")
        return ""


@mcp.tool()
async def upload_pin_to_pinterest(
    image_path: str,
    title: str,
    description: str,
    link: str,
    alt_text: str = "",
    board_name: str = "Recetas Geniales",
    domain_handle: str = "",
) -> dict:
    """
    Upload a single pin image to Pinterest via headless Playwright browser.
    Includes Alt Text support for SEO and more aggressive Firefox lock handling.
    Returns: {success, pin_id, pin_url}
    """
    import asyncio

    local = Path(image_path)
    if not local.exists():
        return {"success": False, "error": f"Image not found: {image_path}"}

    domain = get_registry().get(domain_handle)
    session_dir = domain.sessions_dir
    # Ensure session dir is absolute and exists
    if not session_dir.is_absolute():
        session_dir = PROJECT_ROOT / session_dir
    session_dir.mkdir(parents=True, exist_ok=True)

    async def _upload_shared_core() -> dict:
        from backend.scripts.pinterest_batch_core import (
            DEFAULT_BROWSER_MAP,
            PinterestAccount,
            close_turbo_browser,
            create_pin_from_fields,
            create_turbo_browser,
            ensure_account_logged_in,
        )

        browser_type = DEFAULT_BROWSER_MAP.get(
            session_dir.name, os.environ.get("PINTEREST_BROWSER", "firefox")
        )
        password = (
            domain.pinterest_password.get_secret_value()
            if domain.pinterest_password and domain.pinterest_password.get_secret_value()
            else os.environ.get("PINTEREST_PASSWORD", "")
        )
        account = PinterestAccount(
            name=session_dir.name,
            session_dir=session_dir,
            email=domain.pinterest_email or os.environ.get("PINTEREST_EMAIL", ""),
            password=password,
            browser=browser_type,
        )
        pw = context = page = None
        try:
            pw, context, page = await create_turbo_browser(
                account, "rankstein_mcp_upload", headless=True
            )
            if not await ensure_account_logged_in(page, account):
                return {"success": False, "error": "Pinterest session is not logged in"}
            pin_id = await create_pin_from_fields(
                page,
                local,
                title,
                link,
                description,
                board_name,
                "rankstein_mcp_upload",
            )
            return {
                "success": bool(pin_id),
                "pin_id": pin_id or "",
                "pin_url": f"https://www.pinterest.com/pin/{pin_id}/" if pin_id else "",
                "metadata": {"title": title, "desc_len": len(description), "alt": bool(alt_text)},
                "method": "shared-core",
            }
        finally:
            await close_turbo_browser(pw, context)

    try:
        shared_result = await _upload_shared_core()
        if shared_result.get("success"):
            logger.info(f"Pinterest upload success via shared core: pin_id={shared_result.get('pin_id')}")
            return shared_result
        logger.warning(
            f"Shared Pinterest upload returned no pin id; falling back to legacy MCP flow: {shared_result.get('error', '')}"
        )
    except Exception as shared_exc:
        logger.warning(f"Shared Pinterest upload failed; falling back to legacy MCP flow: {shared_exc}")

    async def _upload() -> dict:
        import json

        from playwright.async_api import async_playwright

        logger.info("Starting _upload() process...")

        # Nuclear cleanup before every attempt
        lock_actions = _kill_firefox_locks(session_dir)
        await asyncio.sleep(2)  # Give OS time to release handles

        logger.info("Launching Playwright...")
        async with async_playwright() as p:
            try:
                browser = await p.firefox.launch_persistent_context(
                    str(session_dir),
                    headless=True,
                    locale="es-ES",
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0"
                    ),
                    viewport={"width": 1280, "height": 900},
                    args=["--no-remote", "--allow-downgrade"],
                    firefox_user_prefs={
                        "browser.startup.page": 0,
                        "browser.cache.disk.enable": False,
                    },
                    timeout=60000,
                )
            except Exception as launch_err:
                # If launch fails due to lock, try one more rescue kill
                if "already running" in str(launch_err).lower():
                    _kill_firefox_locks(session_dir)
                    await asyncio.sleep(3)
                    browser = await p.firefox.launch_persistent_context(
                        str(session_dir),
                        headless=True,
                        args=["--no-remote", "--allow-downgrade"],
                        timeout=60000,
                    )
                else:
                    raise launch_err

            page = browser.pages[0] if browser.pages else await browser.new_page()

            pin_create_data = {"pin_id": None, "pin_url": None, "creation_seen": False}
            pin_create_event = asyncio.Event()

            async def _on_response(response) -> None:
                url = response.url
                method = response.request.method
                if method != "POST":
                    return
                if not any(
                    p in url.lower()
                    for p in [
                        "/v3/pins",
                        "pinresource/create",
                        "storypinresource/create",
                        "pin-builder",
                        "/resource/pin",
                    ]
                ):
                    return
                pin_create_data["creation_seen"] = True
                try:
                    try:
                        data = await response.json()
                    except Exception:
                        data = await response.text()
                    pin_data = data
                    if isinstance(data, str):
                        m = re.search(r'"id"\s*:\s*"?(\d{15,20})', data)
                        if m:
                            pin_data = {"id": m.group(1)}
                    if isinstance(data, dict):
                        if "resource_response" in data:
                            pin_data = data["resource_response"]
                        if isinstance(pin_data, dict) and "data" in pin_data:
                            pin_data = pin_data["data"]
                    pin_id = None
                    if isinstance(pin_data, dict):
                        pin_id = pin_data.get("id")
                    if pin_id:
                        pin_create_data["pin_id"] = str(pin_id)
                        pin_create_data["pin_url"] = f"https://www.pinterest.com/pin/{pin_id}/"
                        pin_create_event.set()
                        logger.info(f"Intercepted pin creation response: pin_id={pin_id}")
                except Exception:
                    if response.ok:
                        pin_create_event.set()

            async def _lookup_recent_published_pin_id() -> str:
                """Find the newest created pin when Firefox hides the create response body."""
                try:
                    await page.goto(
                        "https://www.pinterest.com/", wait_until="domcontentloaded", timeout=45000
                    )
                    await asyncio.sleep(5)
                    profile_href = ""
                    profile_link = page.locator('a:has-text("Your profile"), a:has-text("Tu perfil")').first
                    if await profile_link.count() > 0:
                        profile_href = await profile_link.get_attribute("href") or ""
                    if not profile_href:
                        profile_href = await page.evaluate(
                            """() => {
                                const links = Array.from(document.querySelectorAll('a[href]'));
                                const hit = links.find(a => new RegExp('^/[^/]+/?$').test(a.getAttribute('href') || '')
                                    && (a.innerText || a.getAttribute('aria-label') || '').toLowerCase().includes('profile'));
                                return hit ? hit.getAttribute('href') : '';
                            }"""
                        )
                    if not profile_href:
                        return ""
                    if profile_href.startswith("/"):
                        profile_href = f"https://www.pinterest.com{profile_href}"
                    created_url = profile_href.rstrip("/") + "/_created/"
                    await page.goto(created_url, wait_until="domcontentloaded", timeout=60000)
                    await asyncio.sleep(8)
                    html = await page.content()
                    pin_ids = list(dict.fromkeys(re.findall(r"/pin/(\d{15,20})", html)))
                    for candidate in pin_ids[:20]:
                        await page.goto(
                            f"https://www.pinterest.com/pin/{candidate}/",
                            wait_until="domcontentloaded",
                            timeout=45000,
                        )
                        await asyncio.sleep(5)
                        body_text = await page.locator("body").inner_text(timeout=5000)
                        page_html = await page.content()
                        if title in body_text and (not link or link in body_text or link in page_html):
                            logger.info(
                                f"Recovered published Pinterest pin_id={candidate} from profile lookup."
                            )
                            return candidate
                except Exception as lookup_err:
                    logger.warning(f"Published pin lookup failed: {lookup_err}")
                return ""

            try:
                page.on("response", _on_response)

                # NEW: Pre-check session status at home page
                logger.info("Verifying session status at Pinterest home page...")
                try:
                    await page.goto("https://www.pinterest.com/", wait_until="networkidle", timeout=30000)
                    await asyncio.sleep(3)

                    # NEW: Hide Google One Tap and other blocking overlays
                    await page.evaluate("""
                        () => {
                            const selectors = [
                                '#credential_picker_container',
                                '.L5Fo6c-PQbLGe',
                                '[title="Sign in with Google Dialog"]'
                            ];
                            selectors.forEach(sel => {
                                const el = document.querySelector(sel);
                                if (el) el.style.display = 'none';
                            });
                        }
                    """)

                    avatar = await page.query_selector('[data-test-id="header-avatar"]')
                    if (
                        avatar
                        or "pinterest.com/home" in page.url
                        or ("pinterest.com" in page.url and "login" not in page.url)
                    ):
                        logger.info("Session verified as active.")
                    else:
                        logger.warning("Session might be inactive. Proceeding with caution.")
                except Exception as home_err:
                    logger.warning(f"Session pre-check failed (timeout or error): {home_err}")

                # Navigate to pin creation page with retries
                logger.info("Navigating to Pinterest pin creation tool...")
                success_nav = False
                urls_to_try = [
                    "https://www.pinterest.com/pin-creation-tool/",
                    "https://www.pinterest.com/pin-builder/",
                ]
                for url in urls_to_try:
                    if success_nav:
                        break
                    for nav_attempt in range(2):
                        try:
                            logger.info(f"Trying URL: {url} (Attempt {nav_attempt + 1})")
                            await page.goto(url, timeout=45000, wait_until="networkidle")
                            await asyncio.sleep(5)

                            # Check if redirected to login
                            if "login" in page.url:
                                avatar = await page.query_selector('[data-test-id="header-avatar"]')
                                if not avatar:
                                    logger.warning(f"Redirected to login from {url}")
                                    continue

                            # Check if we are actually on a builder page
                            if any(
                                x in page.url for x in ["pin-creation-tool", "pin-builder"]
                            ) or await page.query_selector('input[type="file"]'):
                                logger.info(f"Successfully reached pin creation tool via {url}")
                                success_nav = True
                                break
                            else:
                                logger.warning(f"Unexpected URL: {page.url}")
                        except Exception as nav_e:
                            logger.warning(f"Navigation to {url} failed: {nav_e}")
                            await asyncio.sleep(3)

                if not success_nav:
                    logger.info(
                        "Direct URL navigation failed. Attempting to find and click 'Create' button on home page..."
                    )
                    try:
                        await page.goto("https://www.pinterest.com/", wait_until="networkidle", timeout=30000)
                        await asyncio.sleep(5)

                        # Hide overlays again
                        await page.evaluate(
                            "() => { document.querySelectorAll('#credential_picker_container, .L5Fo6c-PQbLGe').forEach(el => el.style.display = 'none'); }"
                        )

                        # Look for Create button
                        create_btn = page.locator(
                            'button:has-text("Create"), button:has-text("Crear"), a:has-text("Create"), a:has-text("Crear")'
                        ).first
                        if await create_btn.count() > 0:
                            logger.info("Found 'Create' button, clicking...")
                            await create_btn.click(force=True)
                            await asyncio.sleep(3)

                            # Check for "Create Pin" in the dropdown
                            create_pin_opt = page.locator(
                                'div[role="menuitem"]:has-text("Create Pin"), div[role="menuitem"]:has-text("Crear Pin")'
                            ).first
                            if await create_pin_opt.count() > 0:
                                await create_pin_opt.click(force=True)
                                await asyncio.sleep(5)

                            if any(
                                x in page.url for x in ["pin-creation-tool", "pin-builder"]
                            ) or await page.query_selector('input[type="file"]'):
                                logger.info("Successfully reached pin creation tool via button click.")
                                success_nav = True
                    except Exception as btn_err:
                        logger.warning(f"Fallback button click failed: {btn_err}")

                if not success_nav:
                    await browser.close()
                    return {
                        "success": False,
                        "error": f"Failed to reach pin creation tool. Last URL: {page.url}",
                    }

                async def _clear_draft_limit_if_needed(max_delete: int = 1) -> int:
                    """Free a small amount of draft capacity when Pinterest blocks publishing."""
                    try:
                        body_text = await page.locator("body").inner_text(timeout=3000)
                    except Exception:
                        body_text = ""
                    draft_count_match = re.search(r"Pin drafts\s*\((\d+)\)", body_text, re.I)
                    draft_count = int(draft_count_match.group(1)) if draft_count_match else None
                    at_draft_limit = (
                        (draft_count is not None and draft_count >= 50)
                        or "50 drafts" in body_text
                        or ("limit" in body_text.lower() and "draft" in body_text.lower())
                    )
                    if not at_draft_limit:
                        return 0

                    deleted = 0
                    for _ in range(max_delete):
                        try:
                            actions = page.locator('button[aria-label="Pin draft actions"]')
                            if await actions.count() == 0:
                                break
                            await actions.first.click(force=True)
                            await asyncio.sleep(0.5)

                            delete_action = page.locator('[data-test-id="delete-draft-action"]').first
                            await delete_action.wait_for(state="visible", timeout=5000)
                            await delete_action.click(force=True)
                            await asyncio.sleep(0.5)

                            confirm = page.locator(
                                'button:has-text("Delete"), button:has-text("Eliminar")'
                            ).last
                            await confirm.wait_for(state="visible", timeout=5000)
                            await confirm.click(force=True)
                            deleted += 1
                            await asyncio.sleep(3)
                        except Exception as delete_err:
                            logger.warning(
                                f"Pinterest draft cleanup stopped after {deleted} deletion(s): {delete_err}"
                            )
                            break

                    if deleted:
                        logger.info(f"Deleted {deleted} stale Pinterest draft(s) to clear the draft limit.")
                    return deleted

                cleared_drafts = await _clear_draft_limit_if_needed(max_delete=2)
                if cleared_drafts:
                    await page.goto(
                        "https://www.pinterest.com/pin-creation-tool/",
                        timeout=45000,
                        wait_until="networkidle",
                    )
                    await asyncio.sleep(5)

                # Upload image via file input
                logger.info("Uploading image via file input...")
                file_input = page.locator('input[type="file"]')
                try:
                    await file_input.set_input_files(str(local), timeout=15000)
                    logger.info("Image uploaded successfully.")
                except Exception as e:
                    logger.error(f"Image upload failed: {e}")
                    await browser.close()
                    return {"success": False, "error": "Could not find file upload input on Pinterest."}

                await asyncio.sleep(4)

                # Scroll down so form fields are visible
                logger.info("Scrolling down for form fields...")
                await page.evaluate("window.scrollTo(0, 300)")
                await asyncio.sleep(1)

                # Pinterest's current builder uses React-controlled inputs
                # with stable IDs. Set them directly first, then keep the
                # locator strategy below as a fallback for older layouts.
                try:
                    direct_fill = await page.evaluate(
                        """({title, link, description}) => {
                            const setNativeValue = (el, value) => {
                                if (!el) return false;
                                const proto = el instanceof HTMLTextAreaElement
                                    ? window.HTMLTextAreaElement.prototype
                                    : window.HTMLInputElement.prototype;
                                const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                                if (setter) setter.call(el, value);
                                else el.value = value;
                                el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: value}));
                                el.dispatchEvent(new Event('change', {bubbles: true}));
                                el.dispatchEvent(new Event('blur', {bubbles: true}));
                                return true;
                            };
                            const titleOk = setNativeValue(document.querySelector('#storyboard-selector-title'), title);
                            const linkOk = link ? setNativeValue(document.querySelector('#WebsiteField'), link) : true;
                            const descEl = document.querySelector('textarea[name="description"], textarea[placeholder*="description" i], div[role="textbox"]');
                            let descOk = false;
                            if (descEl && descEl.tagName === 'TEXTAREA') {
                                descOk = setNativeValue(descEl, description);
                            } else if (descEl && descEl.isContentEditable) {
                                descEl.focus();
                                document.execCommand('selectAll', false, null);
                                document.execCommand('insertText', false, description);
                                descEl.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: description}));
                                descOk = true;
                            }
                            return {
                                titleOk,
                                linkOk,
                                descOk,
                                titleValue: document.querySelector('#storyboard-selector-title')?.value || '',
                                linkValue: document.querySelector('#WebsiteField')?.value || ''
                            };
                        }""",
                        {"title": title[:100], "link": link, "description": description[:499]},
                    )
                    logger.info(f"Direct Pinterest field fill result: {direct_fill}")
                except Exception as direct_fill_err:
                    logger.warning(f"Direct field fill failed: {direct_fill_err}")

                # --- Fill Title ---
                title_filled = False
                title_strategies = [
                    page.locator("#storyboard-selector-title").first,
                    page.locator('div[contenteditable="true"][role="textbox"]').first,
                    page.locator('input[id="pin-draft-title"]').first,
                    page.locator('input[name="title"]').first,
                    page.locator('input[placeholder*="título" i]').first,
                    page.locator('input[placeholder*="title" i]').first,
                    page.locator('input[placeholder*="Add a title" i]').first,
                    page.locator('h1[contenteditable="true"]').first,
                ]
                for loc in title_strategies:
                    try:
                        if await loc.count() > 0 and await loc.is_visible():
                            await loc.scroll_into_view_if_needed()
                            await asyncio.sleep(random.uniform(0.3, 0.6))
                            await loc.click(force=True)
                            await asyncio.sleep(random.uniform(0.3, 0.5))
                            await loc.fill(title[:100])
                            await loc.evaluate(
                                "(el) => { el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); }"
                            )
                            title_filled = True
                            break
                    except Exception:
                        continue

                if not title_filled:
                    try:
                        title_filled = await page.evaluate(f"""
                            () => {{
                                const editors = document.querySelectorAll('div[contenteditable="true"][role="textbox"]');
                                for (const el of editors) {{
                                    const rect = el.getBoundingClientRect();
                                    if (rect.width > 0 && rect.height > 0 && rect.top < 600) {{
                                        el.focus();
                                        document.execCommand('selectAll', false, null);
                                        document.execCommand('insertText', false, {json.dumps(title[:100])});
                                        el.dispatchEvent(new Event('input', {{bubbles: true}}));
                                        el.dispatchEvent(new Event('change', {{bubbles: true}}));
                                        return true;
                                    }}
                                }}
                                const inputs = document.querySelectorAll('input[type="text"]');
                                for (const inp of inputs) {{
                                    const ph = (inp.placeholder || '').toLowerCase();
                                    if (ph.includes('title') || ph.includes('título') || ph.includes('add a title') || inp.id.includes('title')) {{
                                        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                                            window.HTMLInputElement.prototype, 'value'
                                        ).set;
                                        nativeInputValueSetter.call(inp, {json.dumps(title[:100])});
                                        inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                                        return true;
                                    }}
                                }}
                                return false;
                            }}
                        """)
                    except Exception:
                        pass

                if not title_filled:
                    healed_sel = await gemini_heal_selector(page, "the pin title input field")
                    if healed_sel:
                        try:
                            loc = page.locator(healed_sel).first
                            if await loc.count() > 0 and await loc.is_visible():
                                await loc.scroll_into_view_if_needed()
                                await asyncio.sleep(0.5)
                                await loc.click(force=True)
                                await loc.press_sequentially(title[:100], delay=random.uniform(30, 70))
                                title_filled = True
                        except Exception:
                            pass
                await asyncio.sleep(random.uniform(1, 2))

                # --- Fill Description ---
                desc_filled = False
                try:
                    desc_opener = page.locator(
                        'div[role="button"]:has-text("Add a detailed description"), '
                        'div[role="button"]:has-text("Agregar una descripción"), '
                        'div[role="button"]:has-text("Añadir una descripción")'
                    ).first
                    if await desc_opener.count() > 0 and await desc_opener.is_visible():
                        await desc_opener.click(force=True)
                        await asyncio.sleep(random.uniform(0.5, 1.0))
                except Exception:
                    pass
                try:
                    desc_locator = page.locator(
                        '.public-DraftEditor-content, textarea, div[contenteditable="true"], '
                        'div[aria-label*="descripción" i], div[aria-label*="description" i]'
                    ).first
                    if await desc_locator.is_visible():
                        await desc_locator.scroll_into_view_if_needed()
                        await asyncio.sleep(random.uniform(0.3, 0.5))
                        await desc_locator.click(force=True)
                        await asyncio.sleep(random.uniform(0.3, 0.5))
                        await page.keyboard.type(description[:499], delay=random.uniform(20, 50))
                        desc_filled = True
                except Exception:
                    pass

                if not desc_filled:
                    try:
                        all_textboxes = page.locator('div[role="textbox"], div[role="combobox"]')
                        count = await all_textboxes.count()
                        for i in range(count):
                            try:
                                loc = all_textboxes.nth(i)
                                if await loc.is_visible():
                                    box = await loc.bounding_box()
                                    if box and box["height"] > 30 and box["width"] > 100:
                                        await loc.scroll_into_view_if_needed()
                                        await loc.click(force=True)
                                        await asyncio.sleep(random.uniform(0.3, 0.5))
                                        await page.keyboard.type(
                                            description[:499], delay=random.uniform(20, 50)
                                        )
                                        desc_filled = True
                                        break
                            except Exception:
                                continue
                    except Exception:
                        pass

                if not desc_filled:
                    try:
                        desc_input = page.locator('textarea[name="description"]')
                        if await desc_input.is_visible():
                            await desc_input.fill(description[:499])
                            desc_filled = True
                    except Exception:
                        pass

                if not desc_filled:
                    healed_sel = await gemini_heal_selector(page, "the pin description input field")
                    if healed_sel:
                        try:
                            loc = page.locator(healed_sel).first
                            if await loc.count() > 0 and await loc.is_visible():
                                await loc.scroll_into_view_if_needed()
                                await loc.click(force=True)
                                await asyncio.sleep(0.5)
                                await page.keyboard.type(description[:499], delay=random.uniform(20, 50))
                                desc_filled = True
                        except Exception:
                            pass

                await asyncio.sleep(random.uniform(1, 2))

                # --- Fill Alt Text ---
                if alt_text:
                    try:
                        more_options = page.locator(
                            'div:has-text("More options"), div:has-text("المزيد من الخيارات"), div:has-text("Más opciones"), button:has-text("Más opciones"), button:has-text("More options")'
                        ).last
                        if await more_options.is_visible():
                            await more_options.click()
                            await asyncio.sleep(random.uniform(0.5, 1.0))
                    except Exception:
                        pass

                    alt_locators = [
                        page.locator('textarea[id="pin-draft-alttext"]').first,
                        page.locator('textarea[placeholder*="alt" i]').first,
                        page.locator('textarea[aria-label*="alt" i]').first,
                        page.locator('textarea[placeholder*="texto alternativo" i]').first,
                        page.locator('textarea[aria-label*="texto alternativo" i]').first,
                        page.locator('input[placeholder*="texto alternativo" i]').first,
                        page.locator('input[aria-label*="texto alternativo" i]').first,
                    ]
                    for loc in alt_locators:
                        try:
                            if await loc.count() > 0 and await loc.is_visible():
                                await loc.fill(alt_text[:499])
                                break
                        except Exception:
                            continue
                await asyncio.sleep(random.uniform(0.5, 1))

                # --- Fill Destination Link ---
                if link:
                    link_locators = [
                        page.locator("#WebsiteField").first,
                        page.locator('input[id="pin-draft-link"]').first,
                        page.locator('input[placeholder*="enlace" i]').first,
                        page.locator('input[placeholder*="link" i]').first,
                        page.locator('input[placeholder*="website" i]').first,
                        page.locator('input[aria-label*="link" i]').first,
                        page.locator('input[name="link"]').first,
                    ]
                    for loc in link_locators:
                        try:
                            if await loc.count() > 0 and await loc.is_visible():
                                await loc.fill(link)
                                await loc.evaluate(
                                    "(el) => { el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true})); }"
                                )
                                logger.info("Destination link filled.")
                                break
                        except Exception:
                            continue

                if link:
                    # Check if link was filled
                    val = ""
                    try:
                        for loc in link_locators:
                            if await loc.count() > 0 and await loc.is_visible():
                                val = await loc.input_value()
                                break
                    except:
                        pass

                    if not val:
                        healed_sel = await gemini_heal_selector(page, "the destination link input field")
                        if healed_sel:
                            try:
                                loc = page.locator(healed_sel).first
                                if await loc.count() > 0 and await loc.is_visible():
                                    await loc.fill(link)
                            except Exception:
                                pass
                await asyncio.sleep(random.uniform(1, 2))

                # --- Select Board ---
                if board_name:
                    try:
                        board_btn = page.locator(
                            '[data-test-id="board-dropdown-select-button"], '
                            'button[data-test-id="board-dropdown-select-button"], '
                            'div[data-test-id="board-selector"] button, '
                            'button[aria-label*="board" i], '
                            'button[aria-label*="tablero" i]'
                        ).first
                        if await board_btn.count() > 0 and await board_btn.is_visible():
                            await board_btn.click()
                            await asyncio.sleep(random.uniform(1, 2))

                            board_option = page.locator(
                                f'div[data-test-id="board-row"] >> text="{board_name}"'
                            ).first
                            try:
                                await board_option.wait_for(state="visible", timeout=3000)
                                await board_option.click()
                                logger.info(f"Selected configured Pinterest board: {board_name}")
                                await asyncio.sleep(random.uniform(1, 2))
                            except Exception:
                                try:
                                    await page.locator(
                                        'text="All boards", text="Todos los tableros"'
                                    ).first.wait_for(state="visible", timeout=15000)
                                except Exception:
                                    pass

                                board_search = page.locator(
                                    'input[placeholder*="Search" i], input[placeholder*="Buscar" i], input[aria-label*="Search" i]'
                                ).first
                                if await board_search.count() > 0 and await board_search.is_visible():
                                    await board_search.fill(board_name)
                                    await asyncio.sleep(random.uniform(1, 2))

                                selected_board = False
                                board_candidates = [board_name, "Postres", "Aperitivos", "Arroces"]
                                for candidate in board_candidates:
                                    if not candidate:
                                        continue
                                    try:
                                        candidate_loc = page.locator(
                                            f'div[role="dialog"] >> text="{candidate}"'
                                        ).first
                                        if (
                                            await candidate_loc.count() > 0
                                            and await candidate_loc.is_visible()
                                        ):
                                            await candidate_loc.click(force=True)
                                            logger.info(f"Selected Pinterest board: {candidate}")
                                            selected_board = True
                                            await asyncio.sleep(random.uniform(1, 2))
                                            break
                                    except Exception:
                                        continue

                                if not selected_board and await board_search.count() > 0:
                                    try:
                                        await board_search.fill("")
                                        await asyncio.sleep(random.uniform(1, 2))
                                    except Exception:
                                        pass
                                if not selected_board:
                                    first_visible_board = page.locator(
                                        'div[role="dialog"] div:has-text("All boards") ~ div, '
                                        'div[role="dialog"] div:has-text("Aperitivos"), '
                                        'div[role="dialog"] div:has-text("Postres")'
                                    ).first
                                    if (
                                        await first_visible_board.count() > 0
                                        and await first_visible_board.is_visible()
                                    ):
                                        await first_visible_board.click(force=True)
                                        logger.info(
                                            f"Selected fallback Pinterest board while looking for {board_name!r}."
                                        )
                                        await asyncio.sleep(random.uniform(1, 2))
                        else:
                            logger.warning("Pinterest board picker was not visible.")
                    except Exception as e:
                        logger.warning(f"Board selection failed: {e}")

                await asyncio.sleep(random.uniform(1, 2))

                # Scroll to publish button
                logger.info("Scrolling to publish button...")
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(random.uniform(1, 2))

                # --- Publish ---
                logger.info("Looking for publish button...")
                publish_btn = page.locator(
                    '[data-test-id="storyboard-creation-nav-done"], '
                    'button[data-test-id*="publish" i], button[data-test-id*="done" i], '
                    'button[aria-label*="Publish" i], button[aria-label*="Publicar" i], '
                    'button:has-text("Publish"), button:has-text("Publicar")'
                ).first
                publish_clicked = False
                try:
                    await publish_btn.wait_for(state="visible", timeout=10000)
                    logger.info("Clicking publish button...")
                    await publish_btn.click(force=True)
                    publish_clicked = True
                except Exception as e:
                    logger.warning(f"Publish button click failed: {e}. Trying self-healing...")

                if not publish_clicked:
                    healed_sel = await gemini_heal_selector(page, "the publish or save pin button")
                    if healed_sel:
                        try:
                            btn = page.locator(healed_sel).first
                            if await btn.count() > 0 and await btn.is_visible():
                                await btn.click(force=True)
                                publish_clicked = True
                        except Exception:
                            pass

                if not publish_clicked:
                    logger.warning("All publish attempts failed, trying Ctrl+Enter...")
                    await page.keyboard.press("Control+Enter")

                # Wait for pin creation response from API using event
                logger.info("Waiting for API response...")
                try:
                    await asyncio.wait_for(pin_create_event.wait(), timeout=20)
                    logger.info("API response intercepted successfully.")
                except TimeoutError:
                    logger.info("Timeout waiting for API response.")

                logger.info("Extracting final pin_id...")
                current_url = page.url
                pin_id = pin_create_data["pin_id"]

                if not pin_id:
                    # Fallback JS state extraction
                    logger.info("Using JS state extraction fallback...")
                    try:
                        extracted_url = await page.evaluate("""
                            () => {
                                if (window.__PINTEREST_DATA__) {
                                    const data = window.__PINTEREST_DATA__;
                                    if (data && data.resourceResponses) {
                                        for (const resp of data.resourceResponses) {
                                            if (resp.response && resp.response.data && resp.response.data.id) {
                                                return '/pin/' + resp.response.data.id + '/';
                                            }
                                        }
                                    }
                                }
                                const pinLinks = document.querySelectorAll('a[href*="/pin/"]');
                                for (const link of pinLinks) {
                                    const href = link.getAttribute('href');
                                    if (href && /\\/pin\\/\\d+/.test(href)) {
                                        return href;
                                    }
                                }
                                return null;
                            }
                        """)
                        if extracted_url:
                            m = re.search(r"/pin/(\d+)", extracted_url)
                            if m:
                                pin_id = m.group(1)
                    except Exception:
                        pass

                if not pin_id:
                    pin_match = re.search(r"/pin/(\d{15,20})", current_url)
                    if pin_match:
                        pin_id = pin_match.group(1)

                if not pin_id and pin_create_data.get("creation_seen"):
                    pin_id = await _lookup_recent_published_pin_id()

                # Final validation — refuse to return junk pin_ids that
                # would later get persisted into Supabase.
                if pin_id and not _is_valid_pinterest_pin_id(pin_id):
                    logger.warning(f"Discarding bogus pin_id {pin_id!r} (not 15-20 digits).")
                    pin_id = None

                await browser.close()

                return {
                    "success": bool(pin_id),
                    "pin_id": pin_id or "",
                    "pin_url": f"https://www.pinterest.com/pin/{pin_id}/" if pin_id else current_url,
                    "lock_actions": lock_actions,
                    "metadata": {"title": title, "desc_len": len(description), "alt": bool(alt_text)},
                }

            except Exception as inner_e:
                try:
                    await browser.close()
                except:
                    pass
                return {"success": False, "error": f"Internal automation error: {str(inner_e)[:300]}"}

    # Retry loop with backoff
    for attempt in range(1, 3):
        try:
            result = await _upload()
            if result.get("success"):
                logger.info(f"Pinterest upload success: pin_id={result.get('pin_id', '?')}")
                return result
        except Exception as e:
            logger.error(f"Asyncio wrapper failure (attempt {attempt}): {e}")
            result = {"success": False, "error": str(e)}

        await asyncio.sleep(attempt * 4)

    return result


_PINTEREST_PIN_ID_PATTERN = re.compile(r"^\d{15,20}$")


def _is_valid_pinterest_pin_id(pin_id: str) -> bool:
    """Pinterest pin IDs are 15–20 digit integers. Anything else (empty,
    short numbers from a stale URL, alphanumeric junk) is rejected to prevent
    storing fake pin_ids that came from the JS-state-extraction fallback."""
    return bool(pin_id) and bool(_PINTEREST_PIN_ID_PATTERN.match(str(pin_id).strip()))


@mcp.tool()
def update_pinterest_pin_id(slug: str, pin_id: str) -> dict:
    """
    Update an existing Supabase post record with the Pinterest Pin ID.
    Call this after upload_pin_to_pinterest returns a pin_id.
    Returns: {success, slug, pin_id}
    """
    if not SUPABASE_KEY:
        return {"success": False, "error": "SUPABASE_SERVICE_ROLE_KEY not set"}
    if not pin_id:
        return {"success": False, "error": "pin_id is empty"}
    if not _is_valid_pinterest_pin_id(pin_id):
        return {
            "success": False,
            "error": (
                f"pin_id {pin_id!r} is not a valid Pinterest pin ID "
                "(must be 15–20 digits). Refusing to write garbage to Supabase. "
                "Re-run upload_pin_to_pinterest or skip this article."
            ),
        }
    try:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        resp = requests.patch(
            f"{SUPABASE_URL}/rest/v1/posts?slug=eq.{slug}",
            headers=headers,
            json={"pinterest_pin_id": pin_id},
        )
        if resp.status_code in [200, 204]:
            logger.info(f"Updated pinterest_pin_id={pin_id} for slug={slug}")
            return {"success": True, "slug": slug, "pin_id": pin_id}
        return {"success": False, "status": resp.status_code, "error": resp.text}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# SUPABASE TOOLS
# ═══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def upload_image_to_supabase(local_path: str, storage_path: str, domain_handle: str = "") -> dict:
    """
    Upload a local image file to Supabase Storage (recipe-images bucket).
    Returns: {public_url, success}
    """
    domain = get_registry().get(domain_handle)
    url = domain.supabase_url
    key = domain.supabase_service_role_key.get_secret_value()

    if not key:
        return {"success": False, "error": f"Supabase key not set for domain {domain.handle}"}
    try:
        ext = Path(local_path).suffix.lower()
        content_type = "image/jpeg" if ext in [".jpg", ".jpeg"] else "image/png"
        target_url = f"{url}/storage/v1/object/{BUCKET}/{storage_path}"
        with open(local_path, "rb") as f:
            resp = requests.post(
                target_url,
                headers={
                    "Authorization": f"Bearer {key}",
                    "x-upsert": "true",
                    "Content-Type": content_type,
                },
                data=f,
            )
        if resp.status_code in [200, 201]:
            public_url = f"{url}/storage/v1/object/public/{BUCKET}/{storage_path}"
            return {"success": True, "public_url": public_url}
        return {"success": False, "status": resp.status_code, "error": resp.text}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def publish_article_to_supabase(
    title: str,
    slug: str,
    content: str,
    excerpt: str,
    category: str,
    featured_image_url: str,
    meta_title: str = "",
    meta_description: str = "",
    keywords: str = "",
    difficulty: str = "Media",
    prep_time: int = 15,
    cook_time: int = 30,
    image_alt: str = "",
    chef_tip: str = "",
    recipe_schema: str = "{}",
    faq_schema: str = "[]",
    pinterest_pin_id: str = "",
    domain_handle: str = "",
) -> dict:
    """
    Publish (upsert) an article to the Supabase posts table.
    Performs PATCH if slug exists, POST if new.
    category must be one of the configured categories for the domain.
    domain_handle="" resolves to the default domain.
    Returns: {success, action, slug, url}
    """
    domain = get_registry().get(domain_handle)
    url = domain.supabase_url
    key = domain.supabase_service_role_key.get_secret_value()

    valid_cats = (
        set(domain.categories)
        if domain.categories
        else {"Aperitivos", "Postres", "Carnes", "Pescados", "Ensaladas"}
    )
    if category not in valid_cats:
        return {
            "success": False,
            "error": f"Invalid category '{category}'. Must be one of {sorted(valid_cats)}",
        }

    if not key:
        return {"success": False, "error": f"Supabase key not set for domain {domain.handle}"}

    try:
        kw_list = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else [slug]

        def _parse_schema(val, default):
            if not val:
                return default
            if isinstance(val, (dict, list)):
                return val
            try:
                return json.loads(val)
            except Exception as e:
                logger.error(f"Schema parse error: {e} | Raw: {val[:100]}...")
                return default

        # ── Universal Article Payload (Superset for Legacy & V2) ──
        # This payload fulfills both the Receta Genial (Legacy) and Receta Dolce (V2) schemas.
        # Once SQL Parity is achieved, both instances will accept all these fields.

        # Prepare structured data for V2
        r_schema = _parse_schema(recipe_schema, {})
        v2_instructions = r_schema.get("recipeInstructions", [])
        v2_ingredients = r_schema.get("recipeIngredient", [])
        v2_faq = _parse_schema(faq_schema, [])

        payload = {
            # Core
            "title": title,
            "slug": slug,
            "content": content,
            "excerpt": excerpt[:155],
            # Images (Dual)
            "hero_image": featured_image_url,
            "featured_image": featured_image_url,
            "image_alt": image_alt or title,
            # Category (Dual)
            "category_id": None,  # Resolve below
            # SEO (Dual)
            "seo_title": meta_title or title[:60],
            "meta_title": meta_title or title[:60],
            "seo_description": meta_description[:155],
            "meta_description": meta_description[:155],
            "keywords": kw_list,
            # Time & Difficulty
            "cooking_time": f"PT{cook_time}M",
            "cook_time": cook_time,
            "prep_time": prep_time,
            "difficulty": difficulty,
            "servings": "4 raciones",  # Default or extract from schema
            # Structured Content (Dual)
            "instructions": v2_instructions,
            "ingredients": v2_ingredients,
            "faq": v2_faq,
            "recipe_schema": r_schema,
            "faq_schema": v2_faq,
            "chef_tip": chef_tip,
            # Status & Metadata
            "is_published": True,
            "status": "published",
            "author": "Isabella Dolce" if "dolce" in domain.domain else "Chef Receta Genial",
            "pinterest_pin_id": pinterest_pin_id,
        }

        # Resolve category_id for V2 compatibility
        if category:
            try:
                # Try to find category by name in the categories table
                cat_resp = requests.get(
                    f"{url}/rest/v1/categories?name=eq.{category}",
                    headers={"apikey": key, "Authorization": f"Bearer {key}"},
                )
                if cat_resp.status_code == 200 and cat_resp.json():
                    payload["category_id"] = cat_resp.json()[0].get("id")
            except Exception as e:
                logger.warning(f"Could not resolve category_id: {e}")

        headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",  # Prevents errors if return schema is inconsistent
        }

        base = f"{url}/rest/v1/posts"
        # Check existence using minimal selection
        check = requests.get(f"{base}?slug=eq.{slug}&select=slug", headers=headers)

        if check.status_code == 200 and check.json():
            resp = requests.patch(f"{base}?slug=eq.{slug}", headers=headers, json=payload)
            action = "updated"
        else:
            resp = requests.post(base, headers=headers, json=payload)
            action = "created"

        if resp.status_code in [200, 201, 204]:
            result = {"success": True, "action": action, "slug": slug, "url": f"https://{domain.domain}/{slug}"}
            # ── Auto-create Pinterest Campaign ──
            try:
                from pinterest_automation.campaign import create_pinterest_campaign
                campaign = create_pinterest_campaign(
                    slug=slug, title=title, excerpt=excerpt,
                    domain_handle=domain_handle, domain_url=domain.domain,
                )
                result["pinterest_campaign"] = campaign
                logger.info("Auto-created Pinterest campaign for %s: %s jobs", slug, campaign.get("jobs_created", 0))
            except Exception as camp_err:
                logger.warning("Pinterest campaign auto-create failed for %s: %s", slug, camp_err)
                result["pinterest_campaign"] = {"success": False, "error": str(camp_err)}
            return result

        # Domain schemas are not always perfectly in lock-step. PostgREST reports
        # a missing payload column as PGRST204; remove unsupported fields and retry
        # the same upsert so one older domain does not block the whole campaign.
        retried_missing: list[str] = []
        for _ in range(12):
            missing_match = re.search(r"Could not find the '([^']+)' column", resp.text or "")
            if not missing_match:
                break
            missing = missing_match.group(1)
            if missing not in payload:
                break
            retried_missing.append(missing)
            payload.pop(missing, None)
            logger.warning(
                "Retrying publish without unsupported column %s for domain=%s", missing, domain.handle
            )
            if action == "updated":
                resp = requests.patch(f"{base}?slug=eq.{slug}", headers=headers, json=payload)
            else:
                resp = requests.post(base, headers=headers, json=payload)
            if resp.status_code in [200, 201, 204]:
                result = {
                    "success": True,
                    "action": action,
                    "slug": slug,
                    "url": f"https://{domain.domain}/{slug}",
                    "omitted_columns": retried_missing,
                }
                # ── Auto-create Pinterest Campaign (retry path) ──
                try:
                    from pinterest_automation.campaign import create_pinterest_campaign
                    campaign = create_pinterest_campaign(
                        slug=slug, title=title, excerpt=excerpt,
                        domain_handle=domain_handle, domain_url=domain.domain,
                    )
                    result["pinterest_campaign"] = campaign
                    logger.info("Auto-created Pinterest campaign for %s: %s jobs", slug, campaign.get("jobs_created", 0))
                except Exception as camp_err:
                    logger.warning("Pinterest campaign auto-create failed for %s: %s", slug, camp_err)
                    result["pinterest_campaign"] = {"success": False, "error": str(camp_err)}
                return result

        # If it fails with "column does not exist", we help the user with the SQL Parity script
        err_text = resp.text
        if ("column" in err_text and "does not exist" in err_text) or "PGRST204" in err_text:
            return {
                "success": False,
                "error": "Schema mismatch. Please run the 'SQL Parity Script' in your Supabase Dashboard.",
                "details": err_text,
                "payload_sent": list(payload.keys()),
            }

        return {"success": False, "status": resp.status_code, "error": err_text}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def check_supabase_connection(domain_handle: str = "") -> dict:
    """Verify Supabase credentials are working. Returns status and post count."""
    domain = get_registry().get(domain_handle)
    url = domain.supabase_url
    key = domain.supabase_service_role_key.get_secret_value()

    if not key:
        return {"connected": False, "error": f"Supabase key not set for domain {domain.handle}"}
    try:
        resp = requests.get(
            f"{url}/rest/v1/posts?select=count",
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Prefer": "count=exact",
            },
        )
        count = resp.headers.get("content-range", "?")
        return {
            "connected": resp.status_code in [200, 206],
            "post_count": count,
            "status": resp.status_code,
            "domain": domain.handle,
        }
    except Exception as e:
        return {"connected": False, "error": str(e), "domain": domain.handle}


@mcp.tool()
def get_article_data_from_supabase_by_slug(slug: str, domain_handle: str = "") -> dict:
    """
    Retrieve article data from Supabase 'posts' table by slug.
    Returns: {success, title, featured_image_url, error}
    """
    domain = get_registry().get(domain_handle)
    url = domain.supabase_url
    key = domain.supabase_service_role_key.get_secret_value()

    if not key:
        return {"success": False, "error": f"Supabase key not set for domain {domain.handle}"}
    try:
        headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        resp = requests.get(
            f"{url}/rest/v1/posts?slug=eq.{slug}&select=title,hero_image",
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data:
                article = data[0]
                return {
                    "success": True,
                    "title": article.get("title"),
                    "featured_image_url": article.get("hero_image"),
                    "domain": domain.handle,
                }
            else:
                return {
                    "success": False,
                    "error": f"Article with slug '{slug}' not found on {domain.handle}.",
                }
        else:
            return {"success": False, "status": resp.status_code, "error": resp.text, "domain": domain.handle}
    except Exception as e:
        return {"success": False, "error": str(e), "domain": domain.handle}


@mcp.tool()
def health_check(domain_handle: str = "") -> dict:
    """
    Comprehensive pre-flight system health check.
    Validates ALL dependencies in one call: env vars, files, Supabase, sessions, disk space.
    Call this at the start of every autonomous cycle.
    Returns: {all_ok, checks: {name: {ok, detail}}}
    """
    import shutil

    _reload_supabase_config()
    domain = get_registry().get(domain_handle)
    kw_file = domain.keywords_file
    checks = {}

    # 1. Keywords file
    checks["keywords_file"] = {
        "ok": kw_file.exists(),
        "detail": str(kw_file) if kw_file.exists() else "MISSING",
    }

    # 2. Pending keyword count
    pending = 0
    if kw_file.exists():
        for line in kw_file.read_text(encoding="utf-8").splitlines():
            if "|" in line and ("Pending" in line):
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 7 and parts[1] and "High" in line:
                    pending += 1
    checks["pending_high_keywords"] = {"ok": pending > 0, "detail": f"{pending} High+Pending keywords"}

    # 3. Supabase key
    key = domain.supabase_service_role_key.get_secret_value()
    checks["supabase_key"] = {"ok": bool(key), "detail": "set" if key else "MISSING"}

    # 4. Supabase connectivity
    try:
        resp = requests.get(
            f"{domain.supabase_url}/rest/v1/posts?select=count",
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Prefer": "count=exact",
            },
            timeout=10,
        )
        checks["supabase_connection"] = {
            "ok": resp.status_code in [200, 206],
            "detail": f"status={resp.status_code}",
        }
    except Exception as e:
        checks["supabase_connection"] = {"ok": False, "detail": str(e)}

    # 5. Pinterest credentials
    pe = bool(domain.pinterest_email)
    pp = bool(domain.pinterest_password.get_secret_value())
    checks["pinterest_credentials"] = {
        "ok": pe and pp,
        "detail": f"email={'set' if pe else 'MISSING'}, password={'set' if pp else 'MISSING'}",
    }

    # 6. Disk space
    try:
        usage = shutil.disk_usage(PROJECT_ROOT)
        free_gb = round(usage.free / (1024**3), 1)
        checks["disk_space"] = {"ok": free_gb > 1.0, "detail": f"{free_gb} GB free"}
    except Exception:
        checks["disk_space"] = {"ok": True, "detail": "unknown"}

    # 7. Log file size
    log_file = PROJECT_ROOT / "data" / "rankstein_mcp.log"
    if log_file.exists():
        log_mb = round(log_file.stat().st_size / (1024 * 1024), 1)
        checks["log_size"] = {"ok": log_mb < 50, "detail": f"{log_mb} MB"}
    else:
        checks["log_size"] = {"ok": True, "detail": "no log file yet"}

    # 8. Failure circuit breaker status
    failures = _load_failures()
    # Check failures for this domain
    abandoned = {k: v for k, v in failures.items() if k.startswith(f"{domain.handle}:") and v >= 3}
    checks["circuit_breaker"] = {
        "ok": len(abandoned) == 0,
        "detail": f"{len(abandoned)} abandoned keywords for {domain.handle}" if abandoned else "clean",
    }

    all_ok = all(c["ok"] for c in checks.values())
    logger.info(f"Health check ({domain.handle}): {'ALL OK' if all_ok else 'ISSUES FOUND'} — {checks}")
    return {
        "all_ok": all_ok,
        "checks": checks,
        "domain": domain.handle,
        "debug_env_path": str(_env_path.absolute()),
        "debug_env_exists": _env_path.exists(),
        "debug_env_first_line": _env_path.read_text(encoding="utf-8").splitlines()[0]
        if _env_path.exists()
        else "N/A",
    }


@mcp.tool()
def check_pinterest_session(session_type: str = "uploader") -> dict:
    """
    Check if a Pinterest browser session is likely still valid by inspecting
    the session directory for recent cookie files.
    session_type: 'uploader' | 'remasterer' | 'harvester'
    Returns: {likely_valid, session_dir, cookie_files, warning}
    """
    dirs = {
        "uploader": Path("data/sessions/pinterest_rida_v7"),
        "remasterer": Path("data/sessions/remasterer_v1"),
        "harvester": Path("data/sessions/harvester_v1"),
    }
    d = PROJECT_ROOT / dirs.get(session_type, dirs["uploader"])
    if not d.exists():
        return {"likely_valid": False, "warning": f"Session dir missing: {d}"}
    cookies = list(d.glob("*.sqlite"))
    if not cookies:
        return {
            "likely_valid": False,
            "session_dir": str(d),
            "warning": "No cookie SQLite files found. Pinterest login required.",
        }
    newest = max(cookies, key=lambda f: f.stat().st_mtime)
    age_days = (datetime.now().timestamp() - newest.stat().st_mtime) / 86400
    warning = None
    if age_days > 30:
        warning = f"Cookies are {age_days:.0f} days old — Pinterest session likely expired. Re-login needed."
    return {
        "likely_valid": age_days <= 30,
        "session_dir": str(d),
        "cookie_files": len(cookies),
        "newest_cookie_age_days": round(age_days, 1),
        "warning": warning,
    }


# NOTE: This logic is duplicated as the canonical implementation in
# ``pinterest_automation/browser_utils.py`` (used by the supervisor /
# session_pool path). The two copies must stay in lock-step. They will be
# unified once P1.2 (split MCP server) lands and pinterest_automation can
# be imported at module top of the rankstein.mcp package without the
# conditional sys.path dance currently used at line ~2014. If you change
# one, change the other.
def _firefox_is_running() -> bool:
    """Best-effort check: is any firefox.exe running on this machine?
    Returns False if tasklist itself errors (assume safe to proceed)."""
    import subprocess as sp

    try:
        out = sp.run(
            ["tasklist", "/NH", "/FI", "IMAGENAME eq firefox.exe"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return "firefox.exe" in (out.stdout or "").lower()
    except Exception:
        return False


def _kill_firefox_locks(session_dir: Path) -> list:
    """
    Kill stale Firefox processes and remove profile lock files. Must be
    called before every Playwright Firefox launch to prevent
    'Firefox is already running' errors on Windows.

    Stronger than the previous version:
      - taskkill is non-blocking on Windows; we poll tasklist until
        firefox.exe is actually gone (up to ~6 s) before continuing
      - covers more lock patterns
      - removes SQLite -shm/-wal sidecars that block re-open

    Returns list of actions taken.
    """
    from pinterest_automation.browser_utils import kill_firefox_locks

    return kill_firefox_locks(session_dir)

    import subprocess as sp
    import time as _time

    actions: list = []

    # 1. Kill any running firefox.exe processes (Windows)
    try:
        result = sp.run(
            ["tasklist"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if "SUCCESS" in result.stdout or "УСПЕШНО" in result.stdout:
            actions.append("Killed stale firefox.exe processes")
    except Exception:
        pass  # taskkill not available or no process running

    # 2. Poll until firefox.exe is actually gone — taskkill is async and the
    #    OS can take a couple of seconds to release file handles after the
    #    process terminates. Skipping this wait is what produced the
    #    cascade of 60 s launch_persistent_context timeouts.
    deadline = _time.time() + 6.0
    while _time.time() < deadline:
        if not _firefox_is_running():
            break
        _time.sleep(0.4)
    else:
        actions.append("Warning: firefox.exe still visible after 6s; proceeding anyway")

    # 3. Remove all known Firefox profile lock files (incl. SQLite sidecars)
    lock_files = [
        "parent.lock",
        ".parentlock",
        "lock",
        "places.sqlite-shm",
        "places.sqlite-wal",
        "cookies.sqlite-shm",
        "cookies.sqlite-wal",
        "webappsstore.sqlite-shm",
        "webappsstore.sqlite-wal",
        "storage.sqlite-shm",
        "storage.sqlite-wal",
    ]
    for lock_name in lock_files:
        lock_path = session_dir / lock_name
        if lock_path.exists():
            try:
                lock_path.unlink()
                actions.append(f"Removed lock file: {lock_name}")
            except Exception as e:
                actions.append(f"Could not remove {lock_name}: {e}")

    # 4. Remove Playwright-specific pid / lock files
    for glob_pat in ("*.pid", "*.tmp", "lock.*"):
        for stale in session_dir.glob(glob_pat):
            try:
                stale.unlink()
                actions.append(f"Removed stale file: {stale.name}")
            except Exception:
                pass

    return actions


@mcp.tool()
def kill_firefox_and_cleanup(session_type: str = "all") -> dict:
    """
    Emergency tool: clean targeted Firefox profile locks
    from Pinterest session directories. Call this if you see
    'Firefox is already running' errors.
    session_type: 'uploader' | 'remasterer' | 'harvester' | 'all'
    Returns: {success, actions_taken}
    """
    session_dirs = {
        "uploader": PROJECT_ROOT / "data" / "sessions" / "pinterest_rida_v7",
        "remasterer": PROJECT_ROOT / "data" / "sessions" / "remasterer_v1",
        "harvester": PROJECT_ROOT / "data" / "sessions" / "harvester_v1",
    }
    targets = (
        list(session_dirs.values())
        if session_type == "all"
        else [session_dirs.get(session_type, session_dirs["uploader"])]
    )
    all_actions = []
    for d in targets:
        all_actions.extend(_kill_firefox_locks(d))
    return {"success": True, "actions_taken": all_actions or ["Nothing to clean up"]}


async def _do_pinterest_login_attempt(session_dir: Path, email: str, password: str, attempt: int) -> dict:
    """One Pinterest login attempt. Hoisted out of pinterest_relogin to avoid
    the unawaited-closure-coroutine quirk that produced
    ``RuntimeWarning: coroutine '_attempt_login' was never awaited`` in the
    previous nested-closure form. Top-level helpers also make this testable.
    """
    import asyncio

    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import async_playwright

    lock_actions = _kill_firefox_locks(session_dir)
    await asyncio.sleep(2)

    try:
        async with async_playwright() as p:
            browser = await p.firefox.launch_persistent_context(
                str(session_dir),
                headless=True,
                locale="es-ES",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0"
                ),
                viewport={"width": 1280, "height": 900},
                args=["--no-remote"],
                firefox_user_prefs={
                    "browser.startup.page": 0,
                    "browser.cache.disk.enable": False,
                },
                timeout=45000,
            )

            page = browser.pages[0] if browser.pages else await browser.new_page()

            try:
                await page.goto("https://www.pinterest.com/", timeout=30000)
                await page.wait_for_timeout(3000)
                avatar = await page.query_selector('[data-test-id="header-avatar"]')
                if avatar or "pinterest.com/home" in page.url:
                    await browser.close()
                    return {
                        "success": True,
                        "message": "Already logged in — session still valid.",
                        "actions_taken": lock_actions,
                    }
            except PlaywrightError:
                pass  # try login page directly

            await page.goto("https://www.pinterest.com/login/", timeout=30000)
            await page.wait_for_timeout(2000)

            try:
                await page.wait_for_selector('input[name="id"]', timeout=10000)
            except PlaywrightError:
                await page.wait_for_selector('input[type="email"]', timeout=5000)

            email_sel = (
                'input[name="id"]' if await page.query_selector('input[name="id"]') else 'input[type="email"]'
            )
            await page.fill(email_sel, email)
            await page.wait_for_timeout(600)

            pwd_sel = (
                'input[name="password"]'
                if await page.query_selector('input[name="password"]')
                else 'input[type="password"]'
            )
            await page.fill(pwd_sel, password)
            await page.wait_for_timeout(600)

            try:
                await page.click('button[type="submit"]')
            except PlaywrightError:
                await page.keyboard.press("Enter")

            await page.wait_for_timeout(6000)

            logged_in = "login" not in page.url and "pinterest.com" in page.url
            current_url = page.url
            await browser.close()

            if logged_in:
                return {
                    "success": True,
                    "message": f"Logged in. Session saved: {session_dir.name}",
                    "actions_taken": lock_actions,
                }
            return {
                "success": False,
                "retryable": True,
                "message": f"Login unclear. URL after submit: {current_url}",
                "actions_taken": lock_actions,
            }

    except Exception as e:
        err_str = str(e)
        retryable = (
            "already running" in err_str.lower()
            or "profile" in err_str.lower()
            or "timeout" in err_str.lower()
        )
        return {
            "success": False,
            "retryable": retryable,
            "error": f"Playwright error (attempt {attempt}): {err_str[:300]}",
            "actions_taken": lock_actions,
        }


@mcp.tool()
async def pinterest_relogin(session_type: str = "uploader", domain_handle: str = "") -> dict:
    """
    Auto-relogin to Pinterest using credentials from PINTEREST_EMAIL / PINTEREST_PASSWORD env vars.
    Fully self-healing: kills stale Firefox processes, clears lock files, retries up to 3 times.
    session_type: 'uploader' | 'remasterer' | 'harvester'
    Returns: {success, message, actions_taken}
    """
    import asyncio

    domain = get_registry().get(domain_handle)

    # Use domain-specific creds if available, otherwise global env
    email = domain.pinterest_email or os.environ.get("PINTEREST_EMAIL", "")
    password = (
        domain.pinterest_password.get_secret_value()
        if domain.pinterest_password.get_secret_value()
        else os.environ.get("PINTEREST_PASSWORD", "")
    )

    if not email or not password:
        return {"success": False, "error": "Pinterest credentials not set for domain or environment"}

    session_dirs = {
        "uploader": domain.sessions_dir,
        "remasterer": PROJECT_ROOT / "data" / "sessions" / "remasterer_v1",
        "harvester": PROJECT_ROOT / "data" / "sessions" / "harvester_v1",
    }
    session_dir = session_dirs.get(session_type, session_dirs["uploader"])

    if not session_dir.is_absolute():
        session_dir = PROJECT_ROOT / session_dir

    session_dir.mkdir(parents=True, exist_ok=True)

    MAX_ATTEMPTS = 3
    last_result: dict = {}
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = await _do_pinterest_login_attempt(session_dir, email, password, attempt)
        except Exception as e:
            result = {
                "success": False,
                "retryable": True,
                "error": f"login attempt crashed: {e}",
            }

        if result.get("success"):
            result["attempt"] = attempt
            return result

        if not result.get("retryable", True):
            result["attempt"] = attempt
            return result

        last_result = result
        if attempt < MAX_ATTEMPTS:
            await asyncio.sleep(attempt * 3)

    last_result["attempt"] = MAX_ATTEMPTS
    last_result["message"] = f"All {MAX_ATTEMPTS} attempts failed. Manual login may be required."
    return last_result


@mcp.tool()
def reset_stuck_keywords(domain_handle: str = "") -> dict:
    """
    Startup watchdog: resets any keywords stuck in 'In Progress' back to 'Pending'.
    Call this at the start of every session to ensure no keywords are permanently blocked.
    Returns: {reset_count, keywords_reset}
    """
    domain = get_registry().get(domain_handle)
    kw_file = domain.keywords_file
    if not kw_file.exists():
        return {"reset_count": 0, "error": f"keywords file not found for {domain.handle}"}
    content = kw_file.read_text(encoding="utf-8")
    lines = content.split("\n")
    reset = []
    for i, line in enumerate(lines):
        if "In Progress" in line and "|" in line:
            parts = line.split("|")
            if len(parts) >= 7:
                keyword = parts[1].strip()
                parts[-2] = " Pending "
                lines[i] = "|".join(parts)
                reset.append(keyword)
    if reset:
        kw_file.write_text("\n".join(lines), encoding="utf-8")
    return {"reset_count": len(reset), "keywords_reset": reset, "domain": domain.handle}


@mcp.tool()
def slugify(text: str) -> dict:
    """Convert a Spanish recipe title to a clean URL slug."""
    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ñ": "n",
        "ü": "u",
        "Á": "a",
        "É": "e",
        "Í": "i",
        "Ó": "o",
        "Ú": "u",
        "Ñ": "n",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    return {"slug": slug}


@mcp.tool()
def list_available_images(directory: str = "nanobanana-output") -> dict:
    """List all images available in nanobanana-output or data/media directories."""
    dirs = {
        "nanobanana-output": OUTPUT_DIR,
        "remaster_final": REMASTER_DIR,
        "remaster_raw": DOWNLOAD_DIR,
    }
    target = dirs.get(directory, OUTPUT_DIR)
    images = [str(p.name) for p in target.glob("*") if p.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]]
    return {"directory": str(target), "images": images, "count": len(images)}


@mcp.tool()
def get_project_status(domain_handle: str = "") -> dict:
    """Return current RankStein project status including pending keywords and image counts."""
    domain = get_registry().get(domain_handle)
    kw_file = domain.keywords_file
    pending = []
    live = []
    if kw_file.exists():
        for line in kw_file.read_text(encoding="utf-8").splitlines():
            if "|" not in line:
                continue
            if "Pending" in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) > 1 and parts[1]:
                    pending.append(parts[1])
            elif "Live" in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) > 1 and parts[1]:
                    live.append(parts[1])

    # Use domain-specific output dir
    output_dir = domain.output_dir
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir

    hero_count = len(list(output_dir.glob("*"))) if output_dir.exists() else 0

    return {
        "domain": domain.handle,
        "pending_keywords": pending,
        "live_keywords": live,
        "hero_images_in_output": hero_count,
        "remastered_pins": len(list(REMASTER_DIR.glob("*"))),
        "supabase_url": domain.supabase_url,
    }


@mcp.tool()
def build_supabase_content(
    keyword: str, 
    hero_image_url: str, 
    article_json: str,
    pinterest_pin_id: str = ""
) -> dict:
    """
    Merge a generated article JSON string with the hero image URL and
    replace content placeholders ([HERO_IMAGE], [HERO_IMAGE_URL], etc.).
    Ensures Schema.org compliance by injecting real URLs into schema objects.
    Returns the final ready-to-publish payload as JSON string.
    """
    try:
        article = json.loads(article_json)
        slug = article.get("slug", re.sub(r"[^a-z0-9]+", "-", keyword.lower()).strip("-"))

        # 1. Prepare HTML for content replacement
        hero_html = f'<img src="{hero_image_url}" alt="{keyword}" class="w-full rounded-xl shadow-lg mb-8">'

        # 2. Global string replacement in content
        content = article.get("content", "")
        content = content.replace("[HERO_IMAGE]", hero_html)
        content = content.replace("[HERO_IMAGE_URL]", hero_image_url)
        
        # Pinterest Iframe Replacement
        pin_html = ""
        if pinterest_pin_id:
            pin_html = (
                f'<div class="pinterest-container my-8 flex justify-center">\n'
                f'  <iframe src="https://assets.pinterest.com/ext/embed.html?id={pinterest_pin_id}" '
                f'height="714" width="450" frameborder="0" scrolling="no" class="rounded-xl shadow-md max-w-full"></iframe>\n'
                f'</div>'
            )
        
        content = content.replace("[PINTEREST_IFRAME]", pin_html)
        content = content.replace("[PINTEREST_IFRAME_STEPS]", "")
        content = content.replace("[PINTEREST_IFRAME_FINAL]", "")
        
        # New: YouTube Video placeholder replacement
        # Matches [YOUTUBE_VIDEO:https://www.youtube.com/embed/XXXXXX]
        video_pattern = r"\[YOUTUBE_VIDEO:(https?://(?:www\.)?youtube\.com/embed/[^\]]+)\]"
        
        def _make_video_html(match):
            url = match.group(1)
            return (
                f'<div class="video-container my-8 relative pb-[56.25%] h-0 overflow-hidden rounded-xl shadow-lg">\n'
                f'  <iframe src="{url}" frameborder="0" allowfullscreen '
                f'class="absolute top-0 left-0 w-full h-full"></iframe>\n'
                f'</div>'
            )
            
        content = re.sub(video_pattern, _make_video_html, content)
        article["content"] = content

        # 3. Handle Recipe Schema (Replace placeholders in strings or objects)
        schema = article.get("recipe_schema", {})
        if isinstance(schema, str):
            schema = schema.replace("[HERO_IMAGE_URL]", hero_image_url)
            schema = schema.replace("[HERO_IMAGE]", hero_image_url)
            try:
                schema = json.loads(schema)
            except:
                pass  # Keep as string if it fails, publish_article_to_supabase will try again
        elif isinstance(schema, dict):
            # Surgical replacement in dictionary
            schema_str = json.dumps(schema)
            schema_str = schema_str.replace("[HERO_IMAGE_URL]", hero_image_url)
            schema = json.loads(schema_str)

        article["recipe_schema"] = schema
        article["featured_image"] = hero_image_url

        # 4. Set defaults for missing fields
        article.setdefault("slug", slug)
        article.setdefault("excerpt", f"Aprende a preparar {keyword} paso a paso.")
        article.setdefault("difficulty", "Media")
        article.setdefault("prep_time", 15)
        article.setdefault("cook_time", 30)

        return {"success": True, "payload": json.dumps(article, ensure_ascii=False)}
    except Exception as e:
        logger.error(f"build_supabase_content failed: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
def publish_from_payload(payload_json: str) -> dict:
    """
    Convenience tool: publish an article from a JSON payload string
    (as returned by build_supabase_content). Unpacks the JSON and calls
    publish_article_to_supabase with all fields automatically.
    Returns: {success, action, slug}
    """
    try:
        p = json.loads(payload_json)
        return publish_article_to_supabase(
            title=p.get("title", ""),
            slug=p.get("slug", ""),
            content=p.get("content", ""),
            excerpt=p.get("excerpt", ""),
            category=p.get("category", "Aperitivos"),
            featured_image_url=p.get("featured_image", ""),
            meta_title=p.get("meta_title", ""),
            meta_description=p.get("meta_description", ""),
            keywords=", ".join(p.get("keywords", []))
            if isinstance(p.get("keywords"), list)
            else p.get("keywords", ""),
            difficulty=p.get("difficulty", "Media"),
            prep_time=p.get("prep_time", 15),
            cook_time=p.get("cook_time", 30),
            image_alt=p.get("image_alt", ""),
            chef_tip=p.get("chef_tip", ""),
            recipe_schema=json.dumps(p.get("recipe_schema", {}))
            if isinstance(p.get("recipe_schema"), dict)
            else p.get("recipe_schema", "{}"),
            faq_schema=json.dumps(p.get("faq_schema", []))
            if isinstance(p.get("faq_schema"), list)
            else p.get("faq_schema", "[]"),
            pinterest_pin_id=p.get("pinterest_pin_id", ""),
        )
    except Exception as e:
        logger.error(f"publish_from_payload failed: {e}")
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# PINTEREST AUTOMATION ENGINE INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════════


def _ensure_automation_on_path():
    project_root = Path(__file__).resolve().parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))


_ensure_automation_on_path()

try:
    from pinterest_automation.mcp_integration import (
        enqueue_pin_mcp,
        get_automation_status,
        start_supervisor_background,
        stop_supervisor,
        upload_pin_via_driver,
    )

    _AUTO_AVAILABLE = True
except ImportError as _auto_err:
    logger.warning(f"Pinterest automation engine not available: {_auto_err}")
    _AUTO_AVAILABLE = False


@mcp.tool()
def automation_status() -> dict:
    """
    Get full status of the Pinterest automation engine.
    Returns: {supervisor_running, health, queue, session_pool, rate_limiter, healing_cache}
    """
    if not _AUTO_AVAILABLE:
        return {"success": False, "error": "Automation engine not available"}
    try:
        return get_automation_status()
    except Exception as e:
        logger.error(f"automation_status failed: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
def automation_start() -> dict:
    """
    Start the autonomous Pinterest supervisor in the background.
    The supervisor will continuously process the job queue, monitor health,
    and self-heal from failures.
    """
    if not _AUTO_AVAILABLE:
        return {"success": False, "error": "Automation engine not available"}
    try:
        return start_supervisor_background()
    except Exception as e:
        logger.error(f"automation_start failed: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
def automation_stop() -> dict:
    """Stop the autonomous Pinterest supervisor."""
    if not _AUTO_AVAILABLE:
        return {"success": False, "error": "Automation engine not available"}
    try:
        return stop_supervisor()
    except Exception as e:
        logger.error(f"automation_stop failed: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
def automation_enqueue_pin(
    image_path: str,
    title: str,
    description: str,
    link: str = "",
    alt_text: str = "",
    board_name: str = "",
    priority: int = 5,
) -> dict:
    """
    Enqueue a pin upload job to the persistent queue.
    The supervisor will process it when ready, respecting rate limits.
    priority: 1 = highest, 10 = lowest
    """
    if not _AUTO_AVAILABLE:
        return {"success": False, "error": "Automation engine not available"}
    try:
        return enqueue_pin_mcp(
            image_path=image_path,
            title=title,
            description=description,
            link=link,
            alt_text=alt_text,
            board_name=board_name,
            priority=priority,
        )
    except Exception as e:
        logger.error(f"automation_enqueue_pin failed: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
async def automation_upload_pin_direct(
    image_path: str,
    title: str,
    description: str,
    link: str = "",
    alt_text: str = "",
    board_name: str = "",
) -> dict:
    """
    Upload a pin IMMEDIATELY using the new production driver with self-healing.
    This bypasses the queue and runs synchronously.
    Returns: {success, pin_id, pin_url, error}
    """
    if not _AUTO_AVAILABLE:
        return {"success": False, "error": "Automation engine not available"}
    try:
        return await upload_pin_via_driver(
            image_path=image_path,
            title=title,
            description=description,
            link=link,
            alt_text=alt_text,
            board_name=board_name,
        )
    except Exception as e:
        logger.error(f"automation_upload_pin_direct failed: {e}")
        return {"success": False, "error": str(e)}


@mcp.tool()
def automation_healing_stats() -> dict:
    """Get self-healing cache statistics."""
    if not _AUTO_AVAILABLE:
        return {"success": False, "error": "Automation engine not available"}
    try:
        from pinterest_automation import get_healing_cache

        return {"success": True, **get_healing_cache().get_stats()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def automation_purge_queue() -> dict:
    """
    Remove dead/completed jobs from queue files to prevent bloat.
    Call this weekly as maintenance.
    """
    if not _AUTO_AVAILABLE:
        return {"success": False, "error": "Automation engine not available"}
    try:
        from pinterest_automation import get_job_queue

        get_job_queue().purge_completed()
        return {"success": True, "message": "Completed jobs purged"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logger.info("[RankStein MCP] Server starting...")
    logger.info(f"   Root: {PROJECT_ROOT}")
    logger.info(f"   Keywords: {KEYWORDS_FILE}")
    logger.info(f"   Supabase: {SUPABASE_URL}")
    logger.info(f"   Env loaded: {_env_path.exists()}")
    logger.info("   Tools: keyword, image, exif, supabase, pinterest, utility, automation")
    mcp.run()

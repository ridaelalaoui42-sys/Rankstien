"""
RankStein Pinterest Automation — Autonomous Runner
Entry point for 24/7 self-healing Pinterest automation.

Usage:
    python run_autonomous.py                  ← starts supervisor (default, no args needed)
    python run_autonomous.py run              ← explicit run
    python run_autonomous.py enqueue-batch   ← queue all unpinned posts from all domains
    python run_autonomous.py enqueue-backlog ← process memory/pinterest_backlog.md into queue
    python run_autonomous.py status          ← show queue/health status

The supervisor auto-enqueues the Pinterest backlog on every start.
"""

import os
import sys

# Re-exec with a clean Python environment before importing modules such as re.
# A mismatched PYTHONHOME inherited from uv/Hermes can point Python 3.12 at a
# Python 3.11 stdlib and trigger "SRE module mismatch" during startup imports.
_clean_env = dict(os.environ)
_reexec_needed = False
for _name in ("PYTHONHOME",):
    if _clean_env.pop(_name, None):
        _reexec_needed = True
_clean_env.pop("UV_INTERNAL__PYTHONHOME", None)
if _reexec_needed:
    _exe = sys.executable.replace("\\", "/")
    os.execve(_exe, [_exe, *sys.argv], _clean_env)  # noqa: S606

import argparse
import asyncio
import json
import logging
import re
import subprocess as _subprocess
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Ensure project root on path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Article workers and Pinterest workers are separate.
# We let config.py handle the loading from .env.


from backend.services.memory_service import memory as agent_memory
from pinterest_automation import (
    AutonomousSupervisor,
    get_config,
    get_health_monitor,
    get_job_queue,
)
from pinterest_automation.campaign import find_best_image as _find_best_image
from pinterest_automation.config import normalize_board_name
from rankstein.runtime_env import clean_python_env, sanitize_current_process_env

sanitize_current_process_env()

# ── Logging
LOG_DIR = PROJECT_ROOT / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-25s | %(levelname)-8s | %(message)s",
    handlers=[
        RotatingFileHandler(
            str(LOG_DIR / "automation.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        ),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("rankstein.runner")


def _bounded_int_env(name: str, default: int, max_env_name: str, max_default: int) -> int:
    """Read a positive int env var, capped for unattended production launches."""
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    try:
        max_value = int(os.environ.get(max_env_name, str(max_default)))
    except ValueError:
        max_value = max_default
    return max(1, min(value, max(1, max_value)))


def _env_enabled(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _process_running(needle: str) -> bool:
    if os.name == "nt":
        safe = needle.replace("'", "''")
        ps = (
            f"$needle = '{safe}'; "
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.CommandLine -and $_.CommandLine.Contains($needle) "
            "-and -not $_.CommandLine.Contains('Get-CimInstance Win32_Process') } | "
            "Select-Object -First 1 ProcessId,CommandLine | ConvertTo-Json -Compress"
        )
        try:
            result = _subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return bool(result.stdout.strip())
        except Exception:
            return False
    try:
        result = _subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True, timeout=10)
        return needle in result.stdout
    except Exception:
        return False


def enqueue_pin(args):
    queue = get_job_queue()
    job_id = queue.enqueue_pin_upload(
        image_path=args.image,
        title=args.title,
        description=args.description,
        link=args.link or "",
        alt_text=args.alt or "",
        board_name=args.board or get_config().default_board,
        priority=args.priority,
    )
    print(f"Enqueued job {job_id}")
    return job_id


# Global session for Supabase pooling
_SUPABASE_SESSION = None


def get_supabase_session():
    """Get or create a requests.Session with connection pooling for Supabase."""
    global _SUPABASE_SESSION
    if _SUPABASE_SESSION is None:
        import requests
        from requests.adapters import HTTPAdapter

        session = requests.Session()
        # pool_connections=10 because we might have many domains
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        _SUPABASE_SESSION = session
    return _SUPABASE_SESSION


def _fetch_unpinned_posts(supabase_url: str, supabase_key: str) -> list[dict]:
    """Fetch unpinned published posts from a Supabase project using pooled session."""
    session = get_supabase_session()

    try:
        headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
        }
        resp = session.get(
            f"{supabase_url}/rest/v1/posts?select=id,title,slug,excerpt,pinterest_pin_id&status=eq.published&order=created_at.desc",
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        posts = resp.json()
        if not isinstance(posts, list):
            return []
        return [
            p for p in posts if not p.get("pinterest_pin_id") or len(str(p.get("pinterest_pin_id", ""))) < 15
        ]
    except Exception as e:
        logger.warning("Failed to fetch posts from %s: %s", supabase_url, e)
        return []


def _get_board_for_slug(slug: str, boards_default: dict[str, str], fallback: str) -> str:
    """Pick a board name based on slug keywords, or return fallback."""
    config = get_config()
    slug_lower = slug.lower()
    for board_name, keywords in config.boards.items():
        if isinstance(keywords, list):
            for kw in keywords:
                if kw in slug_lower:
                    return normalize_board_name(board_name)
    # Try domain-specific boards
    for category, board in boards_default.items():
        if category != "_default" and category.lower() in slug_lower:
            return normalize_board_name(board)
    return normalize_board_name(boards_default.get("_default", fallback))


def enqueue_backlog(args=None) -> int:
    """Process memory/pinterest_backlog.md — enqueue Failed/Pending/Missing pins into the queue.

    Returns the number of jobs enqueued.
    """
    from rankstein.domain import get_registry

    BACKLOG_FILE = PROJECT_ROOT / "memory" / "pinterest_backlog.md"
    if not BACKLOG_FILE.exists():
        print("No pinterest_backlog.md found — nothing to enqueue.")
        return 0

    config = get_config()
    queue = get_job_queue()
    registry = get_registry()
    account_handles = sorted(config.accounts.keys())
    if not account_handles:
        print("No Pinterest accounts configured.")
        return 0

    MEDIA_DIR = PROJECT_ROOT / "data" / "media"
    REMASTER_DIR = MEDIA_DIR / "remaster_final"
    media_dirs = [REMASTER_DIR, MEDIA_DIR]

    # Parse backlog table rows
    table_row = re.compile(
        r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(Failed|Pending|Missing)\s*\|", re.IGNORECASE
    )
    enqueued = 0
    updated_lines = []

    lines = BACKLOG_FILE.read_text(encoding="utf-8").splitlines()
    for line in lines:
        m = table_row.match(line)
        if not m:
            updated_lines.append(line)
            continue

        slug, title, status = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
        if slug.startswith("Article Slug"):  # header
            updated_lines.append(line)
            continue

        best = _find_best_image(slug, media_dirs)
        if not best:
            logger.info("backlog: no image for slug '%s', leaving as %s", slug, status)
            updated_lines.append(line)
            continue

        # Determine domain from slug (prefer recetadolce if image found)
        domain = registry.default
        link = f"https://{domain.domain}/{slug}"
        board = _get_board_for_slug(slug, domain.boards_default, config.default_board)
        desc = f"Aprende a preparar {title} paso a paso. Receta auténtica con fotos."

        for account_handle in account_handles:
            queue.enqueue_pin_upload(
                image_path=str(best),
                title=title[:100],
                description=desc[:499],
                link=link,
                board_name=board,
                priority=3,  # Higher priority than regular batch
                extra={
                    "slug": slug,
                    "account_handle": account_handle,
                    "domain_handle": domain.handle,
                    "source": "backlog",
                },
            )
            enqueued += 1

        # Mark as Queued in the backlog file
        updated_lines.append(line.replace(f"| {status} |", "| Queued |"))
        logger.info("backlog: enqueued '%s' (%s) for %d accounts", slug, status, len(account_handles))

    BACKLOG_FILE.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
    print(
        f"Backlog: enqueued {enqueued} pin jobs ({enqueued // max(1, len(account_handles))} articles × {len(account_handles)} accounts)"
    )
    return enqueued


def enqueue_batch(args):
    """Enqueue unpinned posts from ALL domains for ALL Pinterest accounts."""
    from rankstein.domain import get_registry

    config = get_config()
    queue = get_job_queue()
    registry = get_registry()

    # Image directories to search (shared across domains)
    MEDIA_DIR = PROJECT_ROOT / "data" / "media"
    REMASTER_DIR = MEDIA_DIR / "remaster_final"
    media_dirs = [REMASTER_DIR, MEDIA_DIR]  # Prefer remaster_final

    # Get all configured Pinterest accounts
    account_handles = sorted(config.accounts.keys())
    if not account_handles:
        print("No Pinterest accounts configured. Set PINTEREST_ACCOUNTS in .env")
        return

    print(f"Pinterest accounts: {', '.join(account_handles)}")

    total_matched = 0
    total_skipped = 0

    for domain in registry.all():
        supabase_url = domain.supabase_url
        supabase_key = (
            domain.supabase_service_role_key.get_secret_value() if domain.supabase_service_role_key else ""
        )
        if not supabase_key:
            print(f"  [{domain.handle}] Supabase key missing, skipping")
            continue

        print(f"\n{'=' * 60}")
        print(f"  Domain: {domain.handle} ({domain.domain})")
        print(f"  Supabase: {supabase_url}")

        unpinned = _fetch_unpinned_posts(supabase_url, supabase_key)
        print(f"  Unpinned posts: {len(unpinned)}")

        domain_matched = 0
        for post in unpinned:
            slug = post.get("slug", "")
            if not slug:
                continue

            best = _find_best_image(slug, media_dirs)
            if not best:
                total_skipped += 1
                continue

            desc = post.get("excerpt", "") or f"Aprende a preparar {post['title']} paso a paso."
            link = f"https://{domain.domain}/{slug}"
            board = _get_board_for_slug(
                slug,
                domain.boards_default,
                config.default_board,
            )

            # Enqueue for EACH Pinterest account
            for account_handle in account_handles:
                queue.enqueue_pin_upload(
                    image_path=str(best),
                    title=post["title"],
                    description=desc[:499],
                    link=link,
                    board_name=board,
                    priority=5,
                    extra={
                        "post_id": post["id"],
                        "slug": slug,
                        "account_handle": account_handle,
                        "domain_handle": domain.handle,
                    },
                )
                domain_matched += 1

        total_matched += domain_matched
        print(
            f"  Enqueued: {domain_matched} jobs ({domain_matched // max(1, len(account_handles))} posts × {len(account_handles)} accounts)"
        )

    print(f"\n{'=' * 60}")
    print(f"TOTAL: Enqueued {total_matched} pin jobs across all domains/accounts")
    if total_skipped:
        print(f"  Skipped {total_skipped} posts (no matching image found)")


def show_status(args):
    from pinterest_automation.runtime_state import supervisor_status

    health = get_health_monitor()
    queue = get_job_queue()
    snap = health.get_snapshot()
    stats = queue.get_stats()
    print(
        json.dumps(
            {
                "supervisor": supervisor_status(),
                "health": {
                    "all_ok": snap.all_ok,
                    "checks": snap.checks,
                    "consecutive_failures": snap.consecutive_failures,
                },
                "queue": stats,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


def stop_supervisor(args):
    from pinterest_automation.runtime_state import request_supervisor_stop

    print(json.dumps(request_supervisor_stop(), indent=2))


def normalize_queue_boards(args):
    queue = get_job_queue()
    result = queue.normalize_board_names_in_storage(include_dlq=not args.active_only)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


async def run_supervisor(args):
    """Full autonomous boot: enqueue backlog + enqueue unpinned posts + enqueue remaster folder + start supervisor."""
    agent_memory.log_event("startup", "Starting Autonomous Pinterest Supervisor", {"pid": os.getpid()})

    # ── Step 1: Process Pinterest backlog (no prompting) ──────────────────────
    logger.info("[boot] Enqueuing pinterest backlog...")
    try:
        n = enqueue_backlog()
        agent_memory.log_event("startup", f"Backlog enqueued: {n} jobs", {"jobs": n})
    except Exception as e:
        logger.warning("[boot] Backlog enqueue failed (non-fatal): %s", e)

    # ── Step 2: Enqueue all unpinned posts from ALL domains ───────────────────
    if _env_enabled("RANKSTEIN_ENQUEUE_UNPINNED_POSTS", False):
        logger.info("[boot] Enqueuing unpinned posts from all domains...")
        try:
            import argparse as _argparse

            enqueue_batch(_argparse.Namespace())
        except Exception as e:
            logger.warning("[boot] Batch enqueue failed (non-fatal): %s", e)
    else:
        logger.info("[boot] Unpinned post enqueue skipped by RANKSTEIN_ENQUEUE_UNPINNED_POSTS")

    # ── Step 2.5: Enqueue ALL remastered images from remaster_final ───────────
    if _env_enabled("RANKSTEIN_ENQUEUE_REMASTER_FOLDER", False):
        logger.info("[boot] Enqueuing remastered pins from data/media/remaster_final/...")
        try:
            from pinterest_automation.campaign import enqueue_folder as _enqueue_folder
            from rankstein.domain import get_registry

            default_domain = get_registry().default.domain
            result = _enqueue_folder(domain_url=default_domain)
            agent_memory.log_event("startup", "Remaster folder enqueue complete", result)
        except Exception as e:
            logger.warning("[boot] Remaster folder enqueue failed (non-fatal): %s", e)

    # ── Step 2.6: Launch social siphon worker as background process ────────────
    if _env_enabled("RANKSTEIN_ENABLE_REMASTER_SIPHON", False):
        if _process_running("backend\\services\\remasterer.py") or _process_running(
            "backend/services/remasterer.py"
        ):
            logger.info("[boot] Social siphon already running; not starting a duplicate")
        else:
            pins_per_keyword = _bounded_int_env(
                "RANKSTEIN_REMASTER_PINS_PER_KEYWORD",
                default=30,
                max_env_name="RANKSTEIN_MAX_REMASTER_PINS_PER_KEYWORD",
                max_default=30,
            )
            keyword_limit = _bounded_int_env(
                "RANKSTEIN_REMASTER_KEYWORDS_PER_CYCLE",
                default=3,
                max_env_name="RANKSTEIN_MAX_REMASTER_KEYWORDS_PER_CYCLE",
                max_default=10,
            )
            logger.info(
                "[boot] Launching social siphon: limit=%s pins_per_keyword=%s",
                keyword_limit,
                pins_per_keyword,
            )
            try:
                _subprocess.Popen(
                    [
                        sys.executable,
                        str(PROJECT_ROOT / "backend" / "services" / "remasterer.py"),
                        "--all-domains",
                        "--continuous",
                        "--limit",
                        str(keyword_limit),
                        "--pins-per-keyword",
                        str(pins_per_keyword),
                    ],
                    cwd=str(PROJECT_ROOT),
                    stdout=open(str(LOG_DIR / "remasterer.log"), "a", encoding="utf-8"),
                    stderr=open(str(LOG_DIR / "remasterer_err.log"), "a", encoding="utf-8"),
                    env=clean_python_env(),
                )
            except Exception as e:
                logger.warning("[boot] Social siphon launch failed (non-fatal): %s", e)

    # ── Step 2.7: Launch article workers for ALL domains as background process ─
    if os.environ.get("RANKSTEIN_SKIP_SUPERVISOR_ARTICLES", "").lower() in {"1", "true", "yes"}:
        logger.info("[boot] Article worker launch skipped by RANKSTEIN_SKIP_SUPERVISOR_ARTICLES")
    else:
        logger.info("[boot] Launching turbo_articles --all-domains...")
        try:
            article_workers = _bounded_int_env(
                "RANKSTEIN_ARTICLE_WORKERS",
                default=2,
                max_env_name="RANKSTEIN_MAX_ARTICLE_WORKERS",
                max_default=3,
            )
            keywords_per_cycle = _bounded_int_env(
                "RANKSTEIN_KEYWORDS_PER_CYCLE",
                default=3,
                max_env_name="RANKSTEIN_MAX_KEYWORDS_PER_CYCLE",
                max_default=5,
            )
            _subprocess.Popen(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "backend" / "scripts" / "turbo_articles.py"),
                    "--all-domains",
                    "--workers",
                    str(article_workers),
                    "--limit",
                    str(keywords_per_cycle),
                ],
                cwd=str(PROJECT_ROOT),
                stdout=open(str(LOG_DIR / "articles.log"), "a"),
                stderr=open(str(LOG_DIR / "articles_err.log"), "a"),
                env=clean_python_env(),
            )
            logger.info(
                "[boot] Article workers started: workers=%s limit=%s (log: data/logs/articles.log)",
                article_workers,
                keywords_per_cycle,
            )
        except Exception as e:
            logger.warning("[boot] Article worker launch failed (non-fatal): %s", e)

    # ── Step 3: Start Pinterest supervisor ────────────────────────────────────
    try:
        supervisor = AutonomousSupervisor()
        await supervisor.run()
    except Exception as e:
        agent_memory.log_event("failure", f"Supervisor crashed: {str(e)}", {"error": str(e)})
        raise e


def main():
    parser = argparse.ArgumentParser(
        description="RankStein Pinterest Automation Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Run with no arguments to start the autonomous supervisor (default).",
    )
    sub = parser.add_subparsers(dest="command")

    # run
    sub.add_parser("run", help="Start the autonomous supervisor (enqueues backlog first)")

    # enqueue-pin
    enq_p = sub.add_parser("enqueue-pin", help="Enqueue a single pin upload")
    enq_p.add_argument("image", help="Path to image file")
    enq_p.add_argument("title", help="Pin title")
    enq_p.add_argument("description", help="Pin description")
    enq_p.add_argument("--link", default="", help="Destination link")
    enq_p.add_argument("--alt", default="", help="Alt text")
    enq_p.add_argument("--board", default="", help="Board name")
    enq_p.add_argument("--priority", type=int, default=5, help="Priority (1=highest)")

    # enqueue-batch
    sub.add_parser("enqueue-batch", help="Enqueue unpinned posts from Supabase (all domains)")

    # enqueue-backlog
    sub.add_parser("enqueue-backlog", help="Process memory/pinterest_backlog.md into the job queue")

    # enqueue-folder
    folder_p = sub.add_parser(
        "enqueue-folder", help="Enqueue ALL images from remaster_final for all accounts"
    )
    folder_p.add_argument(
        "--folder", default="", help="Override image folder (default: data/media/remaster_final)"
    )
    folder_p.add_argument("--domain", default="", help="Domain URL for pin links")

    # siphon
    siphon_p = sub.add_parser("siphon", help="Start social siphon worker (download, remaster, enqueue)")
    siphon_p.add_argument("--once", action="store_true", help="Run one cycle and exit")
    siphon_p.add_argument("--limit", type=int, default=0, help="Max keywords per cycle")
    siphon_p.add_argument("--domain", type=str, default="", help="Filter by domain handle")

    # status
    sub.add_parser("status", help="Show system status")
    sub.add_parser("stop", help="Request a graceful supervisor shutdown")

    # normalize-queue-boards
    normalize_p = sub.add_parser(
        "normalize-queue-boards", help="Normalize legacy Pinterest board names in queued jobs"
    )
    normalize_p.add_argument("--active-only", action="store_true", help="Skip DLQ rows")

    args = parser.parse_args()

    if args.command == "enqueue-pin":
        enqueue_pin(args)
    elif args.command == "enqueue-batch":
        enqueue_batch(args)
    elif args.command == "enqueue-backlog":
        enqueue_backlog(args)
    elif args.command == "enqueue-folder":
        from pinterest_automation.campaign import enqueue_folder as _enqueue_folder
        from rankstein.domain import get_registry

        folder_path = Path(args.folder) if args.folder else None
        reg = get_registry()
        domain_obj = reg.get(args.domain) if args.domain else reg.default
        result = _enqueue_folder(
            folder=folder_path,
            domain_url=domain_obj.domain,
            domain_handle=domain_obj.handle,
            boards_default=domain_obj.boards_default,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "siphon":
        from backend.services.remasterer import run_all_domains

        asyncio.run(
            run_all_domains(
                limit=args.limit,
                enqueue=not args.once,  # auto-enqueue unless --once
            )
        )
    elif args.command == "status":
        show_status(args)
    elif args.command == "stop":
        stop_supervisor(args)
    elif args.command == "normalize-queue-boards":
        normalize_queue_boards(args)
    else:
        # Default (no subcommand OR explicit 'run'): boot the full autonomous pipeline
        asyncio.run(run_supervisor(args))


if __name__ == "__main__":
    main()

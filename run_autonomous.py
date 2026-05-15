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

import argparse
import asyncio
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Ensure project root on path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Stable production default: queued legacy jobs often have no explicit
# account_handle, so high worker counts hammer one Pinterest account/session.
os.environ.setdefault("PINTEREST_WORKER_COUNT", "2")

from backend.services.memory_service import memory as agent_memory
from pinterest_automation import (
    AutonomousSupervisor,
    get_config,
    get_health_monitor,
    get_job_queue,
)

# ── Logging ───────────────────────────────────────────────────────────────────
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


from pinterest_automation.campaign import find_best_image as _find_best_image
from pinterest_automation.utils import extract_slug_from_filename, get_title_from_slug



# Global session for Supabase pooling
_SUPABASE_SESSION = None

def get_supabase_session():
    """Get or create a requests.Session with connection pooling for Supabase."""
    global _SUPABASE_SESSION
    if _SUPABASE_SESSION is None:
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

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
            p for p in posts
            if not p.get("pinterest_pin_id") or len(str(p.get("pinterest_pin_id", ""))) < 15
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
                    return board_name
    # Try domain-specific boards
    for category, board in boards_default.items():
        if category != "_default" and category.lower() in slug_lower:
            return board
    return boards_default.get("_default", fallback)


def enqueue_backlog(args=None) -> int:
    """Process memory/pinterest_backlog.md — enqueue Failed/Pending/Missing pins into the queue.

    Returns the number of jobs enqueued.
    """
    import re
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
    table_row = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(Failed|Pending|Missing)\s*\|", re.IGNORECASE)
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
    print(f"Backlog: enqueued {enqueued} pin jobs ({enqueued // max(1, len(account_handles))} articles × {len(account_handles)} accounts)")
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
        supabase_key = domain.supabase_service_role_key.get_secret_value() if domain.supabase_service_role_key else ""
        if not supabase_key:
            print(f"  [{domain.handle}] Supabase key missing, skipping")
            continue

        print(f"\n{'='*60}")
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
        print(f"  Enqueued: {domain_matched} jobs ({domain_matched // max(1, len(account_handles))} posts × {len(account_handles)} accounts)")

    print(f"\n{'='*60}")
    print(f"TOTAL: Enqueued {total_matched} pin jobs across all domains/accounts")
    if total_skipped:
        print(f"  Skipped {total_skipped} posts (no matching image found)")


def show_status(args):
    health = get_health_monitor()
    queue = get_job_queue()
    snap = health.get_snapshot()
    stats = queue.get_stats()
    print(
        json.dumps(
            {
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
    logger.info("[boot] Enqueuing unpinned posts from all domains...")
    try:
        import argparse as _argparse
        enqueue_batch(_argparse.Namespace())
    except Exception as e:
        logger.warning("[boot] Batch enqueue failed (non-fatal): %s", e)

    # ── Step 2.5: Enqueue ALL remastered images from remaster_final ───────────
    logger.info("[boot] Enqueuing remastered pins from data/media/remaster_final/...")
    try:
        from rankstein.domain import get_registry as _get_registry
        import re as _re

        _config = get_config()
        _queue = get_job_queue()
        _registry = _get_registry()
        _remaster_dir = PROJECT_ROOT / "data" / "media" / "remaster_final"
        _remaster_dir.mkdir(parents=True, exist_ok=True)
        _account_handles = sorted(_config.accounts.keys())
        _domain = _registry.default

        _images = [
            f for f in _remaster_dir.iterdir()
            if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
        ] if _remaster_dir.exists() else []

        # ── Generate new pins when folder is empty ─────────────────────────────
        if not _images:
            logger.info("[boot] remaster_final/ is empty — generating fresh pins via remasterer")
            try:
                from backend.services.remasterer import run_remasterer as _run_remasterer

                # Pick a keyword from the first ready domain's roadmap
                _kw, _title = "recetas virales 2026", "Recetas Virales"
                for _d in _registry.all():
                    _kf = _d.keywords_file
                    if _kf and _kf.exists():
                        for _line in _kf.read_text(encoding="utf-8").splitlines():
                            if "Pending" in _line and "|" in _line:
                                _parts = [p.strip() for p in _line.split("|")]
                                if len(_parts) > 2 and _parts[1]:
                                    _kw = _parts[1]
                                    _title = _parts[1].replace("-", " ").title()
                                    break
                    if _kw != "recetas virales 2026":
                        break

                brand = getattr(_domain, "brand_name", None) or _domain.handle.replace("-", " ").title()
                logger.info("[boot] Running remasterer for keyword: %s | brand: %s", _kw, brand)
                import asyncio as _asyncio
                _new_assets = _asyncio.run(_run_remasterer(_kw, _title, brand_name=brand))
                _images = [
                    f for f in _remaster_dir.iterdir()
                    if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
                ] if _remaster_dir.exists() else []
                logger.info("[boot] Remasterer generated %d new pins", len(_new_assets))
                agent_memory.log_event("startup", f"Remasterer generated {len(_new_assets)} pins for '{_kw}'", {})
            except Exception as _re_err:
                logger.warning("[boot] Remasterer generation failed (non-fatal): %s", _re_err)

        # ── Enqueue images, skipping those already in queue ────────────────────
        if _images and _account_handles:
            _enqueued = 0
            _skipped = 0
            for _img in _images:
                # Skip images already in queue (prevents duplicate jobs on re-boot)
                if _queue.image_path_already_queued(str(_img)):
                    _skipped += 1
                    logger.debug("[boot] Skipping already-queued remaster: %s", _img.name)
                    continue

                # Extract slug from filename using unified utility
                _slug = extract_slug_from_filename(_img.name)
                _link = f"https://{_domain.domain}/{_slug}"
                
                # Resolve board name correctly - handle both dict and string
                _board = _config.default_board
                if _domain.boards_default:
                    if isinstance(_domain.boards_default, dict):
                        _board = _get_board_for_slug(_slug, _domain.boards_default, _config.default_board)
                    else:
                        _board = _domain.boards_default

                _desc = f"Receta auténtica paso a paso. {_slug.replace('-', ' ').title()}"

                for _account in _account_handles:
                    _queue.enqueue_pin_upload(
                        image_path=str(_img),
                        title=get_title_from_slug(_slug)[:100],
                        description=_desc[:499],
                        link=_link,
                        board_name=_board,
                        priority=2,
                        extra={
                            "slug": _slug,
                            "account_handle": _account,
                            "domain_handle": _domain.handle,
                            "source": "remaster_final",
                        },
                    )
                    _enqueued += 1

            logger.info(
                "[boot] Remaster folder: enqueued %d new pin jobs | skipped %d already-queued | from %d images",
                _enqueued, _skipped, len(_images),
            )
            agent_memory.log_event("startup", f"Remaster enqueued: {_enqueued} new | {_skipped} skipped", {"images": len(_images)})
        else:
            logger.info("[boot] Remaster folder still empty after generation attempt or no accounts configured — skipping")
    except Exception as e:
        logger.warning("[boot] Remaster folder enqueue failed (non-fatal): %s", e)

    # ── Step 2.7: Launch article workers for ALL domains as background process ─
    logger.info("[boot] Launching turbo_articles --all-domains...")
    try:
        import subprocess as _subprocess
        _subprocess.Popen(
            [
                sys.executable,
                str(PROJECT_ROOT / "backend" / "scripts" / "turbo_articles.py"),
                "--all-domains",
                "--workers", os.environ.get("RANKSTEIN_ARTICLE_WORKERS", "2"),
                "--limit", os.environ.get("RANKSTEIN_KEYWORDS_PER_CYCLE", "3"),
            ],
            cwd=str(PROJECT_ROOT),
            stdout=open(str(LOG_DIR / "articles.log"), "a"),
            stderr=open(str(LOG_DIR / "articles_err.log"), "a"),
        )
        logger.info("[boot] Article workers started (log: data/logs/articles.log)")
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
    folder_p = sub.add_parser("enqueue-folder", help="Enqueue ALL images from remaster_final for all accounts")
    folder_p.add_argument("--folder", default="", help="Override image folder (default: data/media/remaster_final)")
    folder_p.add_argument("--domain", default="", help="Domain URL for pin links")

    # status
    sub.add_parser("status", help="Show system status")

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
        default_domain = get_registry().default.domain
        result = _enqueue_folder(folder=folder_path, domain_url=args.domain or default_domain)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "status":
        show_status(args)
    else:
        # Default (no subcommand OR explicit 'run'): boot the full autonomous pipeline
        asyncio.run(run_supervisor(args))


if __name__ == "__main__":
    main()

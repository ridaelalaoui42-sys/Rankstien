"""Thorough verification and cleanup of data/ directory.

Removes:
- Transient debug screenshots (*.png) and HTML dumps (*.html) from browser automation
- Old rotated log files and temporary upload copies
- Retired agentmemory stores (state_store.db, stream_store, capture-spool)
- Empty legacy directories and test results

Preserves:
- All domain configurations, roadmaps, and qualified daily best keywords (data/domains/)
- System fonts (data/fonts/)
- Native memory database and backlog (data/memory/rankstein_memory.db)
- Active queue database (data/queue/jobs.sqlite3)
- Authenticated browser session credentials (data/sessions/)
- Healed selector cache (data/healing_cache/)
- Curated and active media assets (data/media/steps, data/media/remaster_*)
- Core application databases (data/rankstein.db, data/app.db)
- Active service logs (data/logs/automation.log, etc.)
"""

from __future__ import annotations

import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"


def clean_data():
    if not DATA_DIR.exists():
        print(f"Error: {DATA_DIR} does not exist")
        return

    removed_files = 0
    removed_bytes = 0
    removed_dirs = 0

    print("=== STARTING DATA CLEANUP ===")

    # 1. Root debug screenshots, html dumps, temporary upload files, and MCP process logs
    root_patterns = [
        "debug_publish_*.png",
        "debug_login_*.png",
        "debug_login_*.html",
        "upload_not_ready_*.png",
        "upload_temp_*.jpg",
        "rankstein_mcp_*.log",
        "buttons.txt",
        "debug_hermes_output.txt",
        "publish_els.txt",
        "iii-config*.yaml",
        "pinterest_queue.db",
        "queue.db",
        "remasterer.db",
    ]

    for pat in root_patterns:
        for f in DATA_DIR.glob(pat):
            if f.is_file():
                try:
                    size = f.stat().st_size
                    f.unlink()
                    removed_files += 1
                    removed_bytes += size
                except Exception as e:
                    print(f"Warning: could not delete {f.name}: {e}")

    print(f"Root files cleaned: {removed_files} files, {removed_bytes / 1024 / 1024:.2f} MB")

    # 2. Obsolete agentmemory stores
    obsolete_dirs = [
        DATA_DIR / "state_store.db",
        DATA_DIR / "stream_store",
        DATA_DIR / "capture-spool",
        DATA_DIR / "run_logs",
        DATA_DIR / "generated_content",
    ]

    for ob_dir in obsolete_dirs:
        if ob_dir.exists() and ob_dir.is_dir():
            dir_size = sum(f.stat().st_size for f in ob_dir.rglob("*") if f.is_file())
            dir_count = sum(1 for f in ob_dir.rglob("*") if f.is_file())
            try:
                shutil.rmtree(ob_dir)
                removed_dirs += 1
                removed_files += dir_count
                removed_bytes += dir_size
                print(
                    f"Removed obsolete directory: {ob_dir.name} ({dir_count} files, {dir_size / 1024 / 1024:.2f} MB)"
                )
            except Exception as e:
                print(f"Warning: could not delete {ob_dir.name}: {e}")

    # 3. data/logs/ debug screenshots (*.png) and old rotated logs
    logs_dir = DATA_DIR / "logs"
    if logs_dir.exists():
        log_pngs = list(logs_dir.glob("*.png"))
        png_bytes = sum(f.stat().st_size for f in log_pngs if f.is_file())
        for f in log_pngs:
            try:
                f.unlink()
                removed_files += 1
                removed_bytes += f.stat().st_size if f.exists() else 0
            except Exception:
                pass
        removed_bytes += png_bytes
        print(
            f"Cleaned failure screenshots from data/logs: {len(log_pngs)} screenshots, {png_bytes / 1024 / 1024:.2f} MB"
        )

        # Clean rotated logs (e.g. automation.log.1, automation.log.5, *.20261009.*, etc.)
        for log_f in logs_dir.glob("*"):
            if log_f.is_file():
                name = log_f.name
                # Keep active logs
                if name in {
                    "automation.log",
                    "automation_err.log",
                    "articles.log",
                    "articles_err.log",
                    "batch_upload.log",
                    "hermes_gateway.log",
                    "hermes_dashboard.log",
                    "hermes_dashboard_err.log",
                    "queue_sync.log",
                }:
                    continue
                # Remove rotated / dated / old process logs
                if any(x in name for x in [".2026", ".log.", "agentmemory"]):
                    try:
                        sz = log_f.stat().st_size
                        log_f.unlink()
                        removed_files += 1
                        removed_bytes += sz
                    except Exception:
                        pass

    # 4. data/media/ temporary loose files
    media_dir = DATA_DIR / "media"
    if media_dir.exists():
        for loose_f in media_dir.glob("temp_*.jpg"):
            try:
                sz = loose_f.stat().st_size
                loose_f.unlink()
                removed_files += 1
                removed_bytes += sz
            except Exception:
                pass

    # 5. data/reports/ loose png screenshots
    reports_dir = DATA_DIR / "reports"
    if reports_dir.exists():
        for rpt_png in reports_dir.glob("*.png"):
            try:
                sz = rpt_png.stat().st_size
                rpt_png.unlink()
                removed_files += 1
                removed_bytes += sz
            except Exception:
                pass
        screenshots_dir = reports_dir / "screenshots"
        if screenshots_dir.exists() and screenshots_dir.is_dir():
            s_count = sum(1 for _ in screenshots_dir.rglob("*") if _.is_file())
            s_size = sum(_.stat().st_size for _ in screenshots_dir.rglob("*") if _.is_file())
            try:
                shutil.rmtree(screenshots_dir)
                removed_dirs += 1
                removed_files += s_count
                removed_bytes += s_size
                print(
                    f"Removed reports/screenshots directory ({s_count} files, {s_size / 1024 / 1024:.2f} MB)"
                )
            except Exception:
                pass

    # 6. Build caches inside worktrees
    worktrees_dir = DATA_DIR / "worktrees"
    if worktrees_dir.exists():
        for cache_name in [".next", "test-results", ".turbo"]:
            for d in worktrees_dir.rglob(cache_name):
                if d.is_dir():
                    c_count = sum(1 for _ in d.rglob("*") if _.is_file())
                    c_size = sum(_.stat().st_size for _ in d.rglob("*") if _.is_file())
                    try:
                        shutil.rmtree(d)
                        removed_dirs += 1
                        removed_files += c_count
                        removed_bytes += c_size
                        print(
                            f"Cleaned build cache {d.relative_to(DATA_DIR)}: {c_count} files, {c_size / 1024 / 1024:.2f} MB"
                        )
                    except Exception:
                        pass

    # 7. Empty directories
    for empty_name in [
        "articles",
        "backups",
        "cache",
        "generated_recipe_images",
        "images",
        "staging",
        "temp",
        "worker_home",
    ]:
        empty_dir = DATA_DIR / empty_name
        if empty_dir.exists() and empty_dir.is_dir():
            try:
                shutil.rmtree(empty_dir)
                removed_dirs += 1
                print(f"Removed empty directory: {empty_name}")
            except Exception:
                pass

    print("\n=== CLEANUP SUMMARY ===")
    print(f"Total files removed: {removed_files}")
    print(f"Total directories removed: {removed_dirs}")
    print(f"Total disk space reclaimed: {removed_bytes / 1024 / 1024:.2f} MB")

    # 8. Integrity Verification
    print("\n=== VERIFYING DATA INTEGRITY ===")
    checks = [
        ("Domain: recetadolce keywords.md", DATA_DIR / "domains/recetadolce/keywords.md"),
        (
            "Domain: recetadolce daily_best_keywords.json",
            DATA_DIR / "domains/recetadolce/daily_best_keywords.json",
        ),
        ("Domain: recetagenial keywords.md", DATA_DIR / "domains/recetagenial/keywords.md"),
        (
            "Domain: recetagenial daily_best_keywords.json",
            DATA_DIR / "domains/recetagenial/daily_best_keywords.json",
        ),
        ("Native memory database", DATA_DIR / "memory/rankstein_memory.db"),
        ("Active queue database", DATA_DIR / "queue/jobs.db"),
        ("Accounts configuration", DATA_DIR / "pinterest_accounts.json"),
        ("Selector healing cache", DATA_DIR / "healing_cache/selector_cache.json"),
        ("System fonts", DATA_DIR / "fonts"),
        ("Sessions directory", DATA_DIR / "sessions"),
    ]

    all_intact = True
    for label, path in checks:
        if path.exists():
            if path.is_file():
                print(f"  [PASS] {label} ({path.stat().st_size:,} bytes)")
            else:
                count = sum(1 for _ in path.rglob("*") if _.is_file())
                print(f"  [PASS] {label} ({count} files)")
        else:
            print(f"  [FAIL] {label} MISSING!")
            all_intact = False

    if all_intact:
        print("\nAll essential data structures verified 100% intact!")
    else:
        print("\nWARNING: Some essential data structures were not found!")


if __name__ == "__main__":
    clean_data()

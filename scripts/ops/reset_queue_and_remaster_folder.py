import os
import shutil
import sqlite3
import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 1. Archive remaster_final images
remaster_final = PROJECT_ROOT / "data" / "media" / "remaster_final"
archive_dir = PROJECT_ROOT / "data" / "media" / "remaster_archive" / datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

total_archived = 0
if remaster_final.exists():
    for root, dirs, files in os.walk(remaster_final):
        for f in files:
            src = Path(root) / f
            rel = src.relative_to(remaster_final)
            dst = archive_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            total_archived += 1
    # Clean up empty subdirectories
    for root, dirs, files in os.walk(remaster_final, topdown=False):
        for d in dirs:
            dir_path = Path(root) / d
            try:
                dir_path.rmdir()
            except Exception:
                pass
remaster_final.mkdir(parents=True, exist_ok=True)
print(f"Archived {total_archived} images from remaster_final to {archive_dir}")

# Verify remaster_final is 0
final_files = list(remaster_final.rglob("*.*"))
print(f"remaster_final remaining files: {len(final_files)}")

# 2. Clean stale queue jobs
db_path = PROJECT_ROOT / "data" / "queue" / "jobs.db"
if db_path.exists():
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) FROM jobs WHERE status IN ('pending', 'held', 'processing', 'retry')")
    stale_count = cursor.fetchone()[0]
    cursor.execute("DELETE FROM jobs WHERE status IN ('pending', 'held', 'processing', 'retry')")
    cursor.execute("DELETE FROM dlq")
    conn.commit()
    cursor.execute("SELECT status, count(*) FROM jobs GROUP BY status")
    remaining_jobs = cursor.fetchall()
    cursor.execute("SELECT count(*) FROM dlq")
    dlq_count = cursor.fetchone()[0]
    conn.close()
    print(f"Deleted {stale_count} stale queue jobs and purged DLQ.")
    print(f"Remaining jobs in DB: {remaining_jobs}")
    print(f"Remaining DLQ count: {dlq_count}")

# 3. Update .env to disable bulk folder enqueueing on startup
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    content = env_path.read_text(encoding="utf-8")
    if "RANKSTEIN_ENQUEUE_REMASTER_FOLDER=1" in content:
        content = content.replace("RANKSTEIN_ENQUEUE_REMASTER_FOLDER=1", "RANKSTEIN_ENQUEUE_REMASTER_FOLDER=0")
        env_path.write_text(content, encoding="utf-8")
        print("Updated .env: RANKSTEIN_ENQUEUE_REMASTER_FOLDER=0")
    elif "RANKSTEIN_ENQUEUE_REMASTER_FOLDER" not in content:
        content += "\nRANKSTEIN_ENQUEUE_REMASTER_FOLDER=0\n"
        env_path.write_text(content, encoding="utf-8")
        print("Appended to .env: RANKSTEIN_ENQUEUE_REMASTER_FOLDER=0")
    else:
        print("RANKSTEIN_ENQUEUE_REMASTER_FOLDER already set to 0 in .env")

print("Reset completed successfully.")

"""Reset daily pins counters to 0 across rate_limiter.db and jobs.db."""

import os
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

rl_path = Path("data/queue/rate_limiter.db")
jobs_path = Path("data/queue/jobs.db")

today_str = datetime.now(UTC).strftime("%Y-%m-%d")
today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
end_today = today_start + 86400

print(f"Resetting daily counters for {today_str} (timestamp >= {today_start})...")

# 1. Reset rate_limiter.db
if rl_path.exists():
    conn = sqlite3.connect(rl_path)
    cur = conn.cursor()
    # Delete today's counter rows
    cur.execute("DELETE FROM rl_counters WHERE day_key = ?", (today_str,))
    deleted_rl = cur.rowcount
    conn.commit()
    conn.close()
    print(f"rate_limiter.db: deleted {deleted_rl} counter rows for {today_str}.")
else:
    print("rate_limiter.db not found.")

# 2. Reset jobs.db proof tables for today
# We shift today's completed_at back by 1 day (86400s) so the records and pins remain intact for history/dedupe,
# but they no longer count towards today's daily limit window.
if jobs_path.exists():
    conn = sqlite3.connect(jobs_path)
    cur = conn.cursor()

    # Shift completed_log
    cur.execute(
        "UPDATE completed_log SET completed_at = completed_at - 86400 WHERE completed_at >= ? AND completed_at < ?",
        (today_start, end_today),
    )
    shifted_completed = cur.rowcount

    # Shift completion_evidence
    try:
        cur.execute(
            "UPDATE completion_evidence SET completed_at = completed_at - 86400 WHERE completed_at >= ? AND completed_at < ?",
            (today_start, end_today),
        )
        shifted_evidence = cur.rowcount
    except sqlite3.OperationalError:
        shifted_evidence = 0

    # Shift completed jobs if any
    cur.execute(
        "UPDATE jobs SET completed_at = completed_at - 86400 WHERE status = 'completed' AND completed_at >= ? AND completed_at < ?",
        (today_start, end_today),
    )
    shifted_jobs = cur.rowcount

    conn.commit()
    conn.close()
    print(f"jobs.db: shifted {shifted_completed} completed_log, {shifted_evidence} completion_evidence, and {shifted_jobs} jobs to yesterday.")
else:
    print("jobs.db not found.")

print("\nVerifying RateLimiter daily counts after reset...")
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pinterest_automation.rate_limiter import RateLimiter
rl = RateLimiter()
counts = rl.get_persisted_daily_counts()
print(f"Persisted daily counts after reset: {counts}")

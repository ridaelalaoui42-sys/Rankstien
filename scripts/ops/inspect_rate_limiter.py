"""Inspect rate limiter counters and proof records for today."""

import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

rl_path = Path("data/queue/rate_limiter.db")
jobs_path = Path("data/queue/jobs.db")

print("=== RATE LIMITER DB ===")
if rl_path.exists():
    conn = sqlite3.connect(rl_path)
    rows = conn.execute("SELECT operation, day_key, hour_key, daily_count, hourly_count FROM rl_counters").fetchall()
    print(f"Total rows in rl_counters: {len(rows)}")
    for r in rows:
        print(f"  {r[0]} | day={r[1]} | hour={r[2]} | daily={r[3]} | hourly={r[4]}")
    conn.close()
else:
    print("rate_limiter.db not found")

print("\n=== JOBS DB (Proof) ===")
if jobs_path.exists():
    conn = sqlite3.connect(jobs_path)
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    end_today = today_start + 86400
    print(f"Today UTC window: {today_start} ({datetime.fromtimestamp(today_start, UTC)}) -> {end_today}")

    for table in ["completed_log", "completion_evidence", "jobs"]:
        try:
            if table == "jobs":
                c = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='completed' AND completed_at >= ? AND completed_at < ?", (today_start, end_today)).fetchone()[0]
            else:
                c = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE completed_at >= ? AND completed_at < ?", (today_start, end_today)).fetchone()[0]
            print(f"  Table '{table}' completed today: {c}")
        except sqlite3.OperationalError as e:
            print(f"  Table '{table}': {e}")
    conn.close()
else:
    print("jobs.db not found")

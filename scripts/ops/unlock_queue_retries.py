import sqlite3
import time
from pathlib import Path

db_path = Path("data/queue/jobs.db")
if not db_path.exists():
    print(f"Error: {db_path} does not exist")
    exit(1)

conn = sqlite3.connect(db_path)
c = conn.cursor()

# Check before
c.execute("SELECT status, count(*) FROM jobs GROUP BY status")
print("Before status counts:", c.fetchall())

now = time.time()
c.execute(
    "SELECT count(*) FROM jobs WHERE status IN ('pending', 'retry') AND (next_retry_at IS NULL OR next_retry_at <= ?)",
    (now,),
)
print("Before ready count:", c.fetchone()[0])

# Reset next_retry_at to NULL for all pending and retry jobs
c.execute("UPDATE jobs SET next_retry_at = NULL WHERE status IN ('pending', 'retry')")
updated = c.rowcount
conn.commit()

# Check after
c.execute(
    "SELECT count(*) FROM jobs WHERE status IN ('pending', 'retry') AND (next_retry_at IS NULL OR next_retry_at <= ?)",
    (now,),
)
ready_after = c.fetchone()[0]

conn.close()

print(f"Successfully cleared next_retry_at on {updated} jobs!")
print(f"Ready to dequeue now: {ready_after} jobs")

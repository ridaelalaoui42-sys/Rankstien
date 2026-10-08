import json
import sqlite3
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pinterest_automation.config import normalize_board_name

db_path = PROJECT_ROOT / "data" / "queue" / "jobs.db"

if not db_path.exists():
    print(f"Error: Database not found at {db_path}")
    sys.exit(1)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

try:
    # Get all from DLQ
    dlq_jobs = conn.execute("SELECT * FROM dlq").fetchall()
    if not dlq_jobs:
        print("DLQ is empty. No jobs to re-enqueue.")
        sys.exit(0)

    print(f"Moving {len(dlq_jobs)} jobs from DLQ back to queue...")

    for row in dlq_jobs:
        job_id = row["id"]
        job_data = json.loads(row["job_json"])
        payload = job_data.get("payload", {})
        if isinstance(payload, dict) and "board_name" in payload:
            payload["board_name"] = normalize_board_name(payload.get("board_name"))

        # Prepare for re-enqueue: reset status and attempts
        status = "pending"
        attempt = 0
        started_at = None
        completed_at = None
        next_retry_at = None
        error_log = []

        # Insert back into jobs
        conn.execute(
            """
            INSERT OR REPLACE INTO jobs
            (id, type, payload_json, status, created_at, started_at, completed_at, attempt, max_attempts, next_retry_at, error_log_json, result_json, priority)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                job_id,
                job_data.get("type", "pin_upload"),
                json.dumps(payload, ensure_ascii=False),
                status,
                job_data.get("created_at", 0),
                started_at,
                completed_at,
                attempt,
                job_data.get("max_attempts", 3),
                next_retry_at,
                json.dumps(error_log, ensure_ascii=False),
                json.dumps(job_data.get("result"), ensure_ascii=False),
                job_data.get("priority", 5),
            ),
        )

        # Remove from DLQ
        conn.execute("DELETE FROM dlq WHERE id = ?", (job_id,))

    conn.commit()
    print(f"Successfully re-enqueued {len(dlq_jobs)} jobs.")
except Exception as e:
    conn.rollback()
    print(f"Error during re-enqueue: {e}")
finally:
    conn.close()

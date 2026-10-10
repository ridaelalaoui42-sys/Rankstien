"""Rebalance pending pin_upload jobs across all configured Pinterest accounts."""

import json
import sqlite3
import hashlib
from pathlib import Path

DB_FILE = Path("data/queue/jobs.db")
ACCOUNTS = ["rida", "media", "medridaelalaoui6"]

def rebalance():
    if not DB_FILE.exists():
        print("Database not found:", DB_FILE)
        return

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("SELECT id, payload_json FROM jobs WHERE status = 'pending' AND type = 'pin_upload'")
    rows = cur.fetchall()
    print(f"Total pending pin_upload jobs to rebalance: {len(rows)}")

    counts = {acc: 0 for acc in ACCOUNTS}
    updated = 0

    for job_id, payload_str in rows:
        try:
            payload = json.loads(payload_str)
        except Exception:
            continue

        img_path = str(payload.get("image_path") or payload.get("link") or job_id)
        # Deterministic assignment using hash
        h = int.from_bytes(hashlib.sha256(img_path.encode()).digest()[:4], "big")
        assigned_account = ACCOUNTS[h % len(ACCOUNTS)]

        # Update payload
        payload["account_handle"] = assigned_account
        if isinstance(payload.get("extra"), dict):
            payload["extra"]["account_handle"] = assigned_account

        counts[assigned_account] += 1
        new_payload_json = json.dumps(payload, ensure_ascii=False)

        cur.execute(
            "UPDATE jobs SET payload_json = ? WHERE id = ?",
            (new_payload_json, job_id)
        )
        updated += 1

    conn.commit()
    conn.close()

    print(f"Rebalanced {updated} jobs successfully:")
    for acc, count in counts.items():
        print(f"  {acc}: {count} jobs")

if __name__ == "__main__":
    rebalance()

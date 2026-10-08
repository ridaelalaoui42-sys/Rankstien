"""Inspect recently completed Pinterest upload jobs across all account handles."""

import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
db_path = PROJECT_ROOT / "data" / "queue" / "jobs.db"

if not db_path.exists():
    print(f"Database not found at {db_path}")
    sys.exit(1)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# Query completed_log table
completed_rows = conn.execute(
    "SELECT * FROM completed_log ORDER BY completed_at DESC LIMIT 50"
).fetchall()

print(f"--- RECENTLY COMPLETED PINTEREST JOBS (Total found: {len(completed_rows)}) ---")

account_counts = {}
live_pins = []

for row in completed_rows:
    job_data = json.loads(row["job_json"] or "{}")
    payload = job_data.get("payload", {})
    result = job_data.get("result", {})
    extra = payload.get("extra", {})
    
    acc = payload.get("account_handle") or extra.get("account_handle") or job_data.get("account_handle") or "default"
    account_counts[acc] = account_counts.get(acc, 0) + 1
    
    pin_id = result.get("pin_id") or payload.get("pin_id")
    pin_url = result.get("pin_url") or (f"https://www.pinterest.com/pin/{pin_id}/" if pin_id else None)
    
    title = payload.get("title") or payload.get("keyword") or extra.get("slug") or "Pin Upload"
    board = payload.get("board_name") or payload.get("board") or "Default"
    
    if pin_url or pin_id:
        live_pins.append({
            "account": acc,
            "title": title,
            "board": board,
            "pin_id": pin_id,
            "pin_url": pin_url,
            "domain": payload.get("domain_handle") or extra.get("domain_handle") or "general"
        })

print("\n--- ACCOUNT COMPLETED BREAKDOWN ---")
for acc, cnt in account_counts.items():
    print(f"Account: {acc} -> {cnt} completed uploads")

print(f"\n--- NEWLY UPLOADED LIVE PINS ({len(live_pins)}) ---")
for p in live_pins[:15]:
    print(f"[{p['account'].upper()}] [{p['domain']}] {p['title'][:65]}")
    print(f"   -> Board: {p['board']} | Live Pin: {p['pin_url']}")

# Query active queue by account
pending_jobs = conn.execute(
    "SELECT payload_json FROM jobs WHERE status = 'pending'"
).fetchall()

account_pending = {}
for row in pending_jobs:
    payload = json.loads(row["payload_json"] or "{}")
    acc = payload.get("account_handle") or payload.get("extra", {}).get("account_handle") or "default"
    account_pending[acc] = account_pending.get(acc, 0) + 1

print("\n--- PENDING QUEUE BREAKDOWN BY ACCOUNT ---")
for acc, cnt in account_pending.items():
    print(f"Account: {acc} -> {cnt} pending jobs in queue")

conn.close()

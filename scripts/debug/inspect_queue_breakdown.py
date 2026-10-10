import sqlite3
import json

conn = sqlite3.connect("data/queue/jobs.db")
cur = conn.cursor()
rows = cur.execute("SELECT type, payload_json, status FROM jobs").fetchall()

breakdown = {}
for jtype, payload, status in rows:
    try:
        data = json.loads(payload)
    except Exception:
        data = {}
    account = data.get("account_handle") or data.get("extra", {}).get("account_handle") or "none"
    domain = data.get("domain_handle") or data.get("extra", {}).get("domain_handle") or "none"
    key = (status, jtype, domain, account)
    breakdown[key] = breakdown.get(key, 0) + 1

print(f"{'STATUS':<12} {'TYPE':<15} {'DOMAIN':<15} {'ACCOUNT':<20} {'COUNT':<5}")
print("-" * 70)
for (status, jtype, domain, account), count in sorted(breakdown.items()):
    print(f"{status:<12} {jtype:<15} {domain:<15} {account:<20} {count:<5}")

import sqlite3
import json

conn = sqlite3.connect("data/queue/jobs.db")
c = conn.cursor()
c.execute("SELECT type, status, count(*) FROM jobs GROUP BY type, status")
print("Jobs breakdown:", c.fetchall())

c.execute("SELECT payload_json FROM jobs WHERE type = 'pin_upload' AND status = 'pending'")
accounts = set()
missing_files = 0
existing_files = 0
import os
for r in c.fetchall():
    try:
        p = json.loads(r[0])
        accounts.add(p.get("account_handle"))
        img = p.get("image_path")
        if img:
            if os.path.exists(img):
                existing_files += 1
            else:
                missing_files += 1
    except Exception:
        pass
print("Accounts in pending pin_upload:", accounts)
print(f"Pending pin_upload files: {existing_files} exist, {missing_files} MISSING")

c.execute("SELECT payload_json FROM jobs WHERE type = 'pin_save' AND status = 'pending'")
accounts_save = set()
for r in c.fetchall():
    try:
        p = json.loads(r[0])
        accounts_save.add(p.get("account_handle"))
    except Exception:
        pass
print("Accounts in pending pin_save:", accounts_save)
conn.close()

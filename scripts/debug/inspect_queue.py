import sqlite3
import json
from pathlib import Path

conn = sqlite3.connect('data/queue/jobs.db')
cur = conn.cursor()
cur.execute("SELECT id, type, status, json_extract(payload_json, '$.account_handle'), json_extract(payload_json, '$.domain_handle'), json_extract(payload_json, '$.image_path'), json_extract(payload_json, '$.board_name') FROM jobs WHERE status = 'pending' LIMIT 10")
for row in cur.fetchall():
    print(row)

print("\nDistinct links and domains in pending:")
cur.execute("SELECT DISTINCT json_extract(payload_json, '$.domain_handle'), substr(json_extract(payload_json, '$.link'), 1, 35), count(*) FROM jobs WHERE status = 'pending' GROUP BY 1, 2")
for row in cur.fetchall():
    print(row)


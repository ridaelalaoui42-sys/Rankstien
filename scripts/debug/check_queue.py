import sqlite3
import json
from pathlib import Path

db_path = Path("data/queue/jobs.db")
conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

try:
    cursor.execute("SELECT id, payload_json FROM jobs WHERE status = 'pending' LIMIT 20")
    rows = cursor.fetchall()
    print("Pending Jobs (ID, Board Name from Payload):")
    for row in rows:
        payload = json.loads(row[1])
        board = payload.get("board_name")
        print(f"ID: {row[0]} | Board: {board} (Type: {type(board).__name__})")
except Exception as e:
    print(f"Error: {e}")

conn.close()

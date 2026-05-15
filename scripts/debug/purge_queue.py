import sqlite3
from pathlib import Path

db_path = Path("data/queue/jobs.db")
conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

cursor.execute("DELETE FROM jobs")
conn.commit()
print("Queue purged successfully.")

conn.close()

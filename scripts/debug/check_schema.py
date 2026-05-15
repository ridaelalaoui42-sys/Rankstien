import sqlite3
from pathlib import Path

db_path = Path("data/queue/jobs.db")
conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

cursor.execute("PRAGMA table_info(jobs)")
print("Columns in 'jobs' table:")
for col in cursor.fetchall():
    print(col)

conn.close()

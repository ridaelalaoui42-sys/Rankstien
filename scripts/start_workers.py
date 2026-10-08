"""Launch article workers as detached background processes."""

import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
log_dir = PROJECT_ROOT / "data" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
log_name = f"turbo_worker_{time.strftime('%Y%m%d_%H%M%S')}.log"
log_file = open(log_dir / log_name, "a", encoding="utf-8")

env = os.environ.copy()
env["PYTHONUNBUFFERED"] = "1"
env["PYTHONIOENCODING"] = "utf-8"

proc = subprocess.Popen(
    [
        sys.executable,
        str(PROJECT_ROOT / "backend" / "scripts" / "turbo_articles.py"),
        "--all-domains",
        "--workers",
        "2",
        "--limit",
        "3",
    ],
    cwd=str(PROJECT_ROOT),
    stdout=log_file,
    stderr=subprocess.STDOUT,
    env=env,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
)
print(f"Launched turbo_articles worker pid={proc.pid}")
print(f"Log: {log_dir / log_name}")

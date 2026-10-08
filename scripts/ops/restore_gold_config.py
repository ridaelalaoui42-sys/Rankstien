import json
import os
import subprocess
from pathlib import Path

# Paths
PROJECT_ROOT = Path(os.getcwd())
ENV_FILE = PROJECT_ROOT / ".env"
SESSIONS_DIR = PROJECT_ROOT / "data" / "sessions"

GOLD_CONFIG = {
    "PINTEREST_DEFAULT_BROWSER": "chromium",
    "PINTEREST_WORKER_COUNT": "6",
    "PINTEREST_WORKERS": "6",
    "PINTEREST_MAX_ITEM_ATTEMPTS": "3",
    "PINTEREST_ALLOW_LEGACY_WORKER_COUNT": "true",
}


def restore_env():
    print("--- Restoring Gold Standard .env ---")
    if not ENV_FILE.exists():
        print("Error: .env not found.")
        return

    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    new_lines = []
    found_keys = set()

    for line in lines:
        updated = False
        for key, val in GOLD_CONFIG.items():
            if line.startswith(f"{key}="):
                new_lines.append(f"{key}={val}")
                found_keys.add(key)
                updated = True
                break
        if not updated:
            # Handle PINTEREST_ACCOUNTS special case to force chromium
            if line.startswith("PINTEREST_ACCOUNTS="):
                try:
                    raw = line.split("=", 1)[1].strip()
                    if (raw.startswith("'") and raw.endswith("'")) or (
                        raw.startswith('"') and raw.endswith('"')
                    ):
                        raw = raw[1:-1]
                    accounts = json.loads(raw)
                    for acc in accounts:
                        acc["browser"] = "chromium"
                    new_lines.append(f"PINTEREST_ACCOUNTS={json.dumps(accounts)}")
                    print("Forced Chromium in PINTEREST_ACCOUNTS.")
                except:
                    new_lines.append(line)
            else:
                new_lines.append(line)

    for key, val in GOLD_CONFIG.items():
        if key not in found_keys:
            new_lines.append(f"{key}={val}")

    ENV_FILE.write_text("\n".join(new_lines), encoding="utf-8")
    print("Gold Standard .env variables applied.")


def purge_locks():
    print("--- Purging Session Locks ---")
    lock_patterns = ["parent.lock", "singletonlock", "lock", "*.pid", "lock.*"]
    count = 0
    for session in SESSIONS_DIR.glob("*"):
        if session.is_dir():
            for pattern in lock_patterns:
                for lock in session.glob(pattern):
                    try:
                        lock.unlink()
                        count += 1
                    except:
                        pass
    print(f"Removed {count} lock files.")


def kill_processes():
    print("--- Killing Rogue Processes ---")
    for proc in ["firefox.exe", "chrome.exe", "chromium.exe", "python.exe"]:
        try:
            subprocess.run(["taskkill", "/F", "/IM", proc, "/T"], capture_output=True)
        except:
            pass
    print("Processes cleaned.")


if __name__ == "__main__":
    restore_env()
    purge_locks()
    # kill_processes() # Optional: uncomment if calling from outside
    print("\n✅ GOLD STANDARD RESTORED. Run 'python run_autonomous.py run' to start.")

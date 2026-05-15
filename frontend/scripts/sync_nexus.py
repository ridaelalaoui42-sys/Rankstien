import os
import requests
import json
from pathlib import Path

# Load env variables
def load_env():
    env_path = Path(__file__).parent.parent / ".env.local"
    if env_path.exists():
        with open(env_path, "r") as f:
            for line in f:
                if "=" in line:
                    key, value = line.strip().split("=", 1)
                    os.environ[key] = value

load_env()

NEXUS_API_URL = os.environ.get("NEXUS_API_URL")
NEXUS_CONNECTION_ID = os.environ.get("NEXUS_CONNECTION_ID")
CONFIG_FILE = Path(__file__).parent.parent / "nexus_config.json"

def sync():
    if not NEXUS_API_URL or not NEXUS_CONNECTION_ID:
        print("[ERROR] NEXUS_API_URL or NEXUS_CONNECTION_ID not set in .env.local")
        return

    print(f"[SYNC] Syncing configuration from Nexus: {NEXUS_API_URL}")
    
    url = f"{NEXUS_API_URL}/api/cms/config"
    headers = {
        "X-Connection-ID": NEXUS_CONNECTION_ID
    }

    try:
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            config_data = resp.json()
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            print(f"[SUCCESS] Configuration synced successfully! Saved to {CONFIG_FILE.name}")
            print(f"   Project: {config_data.get('project_name')}")
            print(f"   Niche: {config_data.get('niche')}")
            print(f"   Voice: {config_data.get('voice')}")
        else:
            print(f"[ERROR] Failed to sync: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"[ERROR] Error during sync: {e}")

if __name__ == "__main__":
    sync()

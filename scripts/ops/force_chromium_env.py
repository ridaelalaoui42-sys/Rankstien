import json
import os
from pathlib import Path

project_root = Path(os.getcwd())
env_file = project_root / ".env"


def fix_env_accounts():
    if not env_file.exists():
        print(".env not found")
        return

    lines = env_file.read_text(encoding="utf-8").splitlines()
    new_lines = []
    for line in lines:
        if line.startswith("PINTEREST_ACCOUNTS="):
            # Extract JSON
            try:
                raw_json = line.split("=", 1)[1]
                # Strip quotes if present
                if (raw_json.startswith("'") and raw_json.endswith("'")) or (
                    raw_json.startswith('"') and raw_json.endswith('"')
                ):
                    raw_json = raw_json[1:-1]

                accounts = json.loads(raw_json)
                for acc in accounts:
                    acc["browser"] = "chromium"

                # Re-serialize
                fixed_json = json.dumps(accounts)
                new_lines.append(f"PINTEREST_ACCOUNTS={fixed_json}")
                print("Updated PINTEREST_ACCOUNTS to Chromium for all.")
            except Exception as e:
                print(f"Failed to parse PINTEREST_ACCOUNTS: {e}")
                new_lines.append(line)
        else:
            new_lines.append(line)

    env_file.write_text("\n".join(new_lines), encoding="utf-8")


if __name__ == "__main__":
    fix_env_accounts()

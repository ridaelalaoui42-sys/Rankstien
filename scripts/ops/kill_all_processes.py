"""Comprehensive emergency process killer for RankStein suite and automation."""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def kill_process_by_pid(pid: int, name: str = ""):
    if pid == os.getpid():
        return
    try:
        subprocess.run(["taskkill", "/F", "/PID", str(pid), "/T"], capture_output=True)
        print(f"Killed PID {pid} ({name})")
    except Exception as e:
        print(f"Error killing PID {pid}: {e}")


def kill_ports(ports: list[int]):
    print("\n--- Checking and freeing ports ---")
    try:
        netstat = subprocess.run(["netstat", "-ano"], capture_output=True, text=True)
        for line in netstat.stdout.splitlines():
            for port in ports:
                if f":{port} " in line and "LISTENING" in line:
                    parts = line.split()
                    pid = int(parts[-1])
                    if pid != 0 and pid != os.getpid():
                        print(f"Freeing port {port} (PID {pid})")
                        kill_process_by_pid(pid, f"port {port}")
    except Exception as e:
        print(f"Error checking ports: {e}")


def kill_targeted_processes():
    print("\n--- Scanning and terminating RankStein processes ---")
    current_pid = os.getpid()

    ps_cmd = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -match 'python|node|chrome|firefox|msedge' } | "
        "Select-Object ProcessId, Name, CommandLine | "
        "ConvertTo-Json -Compress"
    )

    try:
        res = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True, timeout=30
        )
        import json

        raw = res.stdout.strip()
        if not raw:
            print("No matching processes found.")
            return

        procs = json.loads(raw)
        if isinstance(procs, dict):
            procs = [procs]

        rankstein_markers = [
            "rankstein",
            "turbo_articles",
            "run_autonomous",
            "agentmemory",
            "hermes",
            "odysseus",
            "remasterer",
            "start_workers",
            "3111",
            "8642",
            "9119",
            "7000",
            "3001",
            "upload_temp",
            "pinterest_automation",
        ]

        killed_count = 0
        for p in procs:
            pid = p.get("ProcessId")
            name = p.get("Name") or ""
            cmd = (p.get("CommandLine") or "").lower()

            if not pid or pid == current_pid:
                continue

            if any(marker in cmd for marker in rankstein_markers):
                print(f"Matching process detected: PID {pid} [{name}] -> {cmd[:120]}...")
                kill_process_by_pid(pid, name)
                killed_count += 1

        print(f"Terminated {killed_count} matching RankStein processes.")
    except Exception as e:
        print(f"Error querying CIM processes: {e}")


def cleanup_stale_files():
    print("\n--- Cleaning stale runtime files ---")
    runtime_dir = PROJECT_ROOT / "data" / "runtime"
    if runtime_dir.exists():
        for f in runtime_dir.glob("*"):
            try:
                if f.is_file():
                    f.unlink(missing_ok=True)
                    print(f"Removed runtime file: {f.name}")
            except Exception as e:
                print(f"Could not remove {f.name}: {e}")


def main():
    print("=== RANKSTEIN PROCESS KILLER STARTING ===")

    # 1. Stop services gracefully first if possible
    try:
        from rankstein import suite_controller

        suite_controller.stop_services()
        suite_controller.force_clear_stale_lease()
    except Exception as e:
        print(f"suite_controller.stop_services warning: {e}")

    # 2. Kill all targeted processes
    kill_targeted_processes()

    # 3. Kill all suite ports
    ports_to_kill = [3111, 8642, 9119, 7000, 3001, 8080]
    kill_ports(ports_to_kill)

    # 4. Clean runtime locks
    cleanup_stale_files()

    print("\n=== ALL RANKSTEIN PROCESSES TERMINATED ===")


if __name__ == "__main__":
    main()

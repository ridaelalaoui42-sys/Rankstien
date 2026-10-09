"""Suite controller for managing RankStein background services and processes."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from . import log_manager
from .config import PROJECT_ROOT

DATA_DIR = PROJECT_ROOT / "data"
PROJECT_PYTHON = PROJECT_ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if not PROJECT_PYTHON.exists():
    PROJECT_PYTHON = Path(sys.executable)

RUNTIME_DIR = DATA_DIR / "runtime"
CAMPAIGN_LEASE_FILE = RUNTIME_DIR / "campaign_lease.json"
SERVICES_STATE_FILE = RUNTIME_DIR / "services_state.json"

logger = logging.getLogger(__name__)

EXTERNAL_SERVICES_ENV = "RANKSTEIN_EXTERNAL_SERVICES"


def external_services() -> set[str]:
    """Service names owned by an external runtime (e.g. Docker compose).

    External services are health-probed only. The suite never starts,
    restarts, or kills the process holding their port, because on Docker
    Desktop that process is the Docker port proxy, not the service itself.
    """
    raw = os.environ.get(EXTERNAL_SERVICES_ENV, "")
    return {name.strip().lower() for name in raw.split(",") if name.strip()}


@dataclass
class ServiceSpec:
    name: str
    port: int
    cmd: list[str]
    cwd: Path
    health_url: str | None
    depends_on: list[str]
    optional: bool = False
    max_restart_per_hour: int = 3
    stdout_name: str = ""
    stderr_name: str = ""


# Default Hermes CLI resolution
_hermes_exe = shutil.which("hermes.exe") or shutil.which("hermes") or "hermes"

SERVICES: list[ServiceSpec] = [
    ServiceSpec(
        name="operator",
        port=7000,
        cmd=[
            str(PROJECT_PYTHON),
            "-m",
            "uvicorn",
            "backend.operator:app",
            "--host",
            "127.0.0.1",
            "--port",
            "7000",
            "--no-proxy-headers",
        ],
        cwd=PROJECT_ROOT,
        health_url="http://127.0.0.1:7000/health",
        depends_on=[],
        stdout_name="operator.log",
        stderr_name="operator_err.log",
    ),
    ServiceSpec(
        name="agentmemory",
        port=3111,
        cmd=[
            "powershell.exe",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PROJECT_ROOT / "scripts" / "dev" / "start_agentmemory.ps1"),
        ],
        cwd=PROJECT_ROOT,
        health_url="http://127.0.0.1:3111/agentmemory/health",
        depends_on=[],
        stdout_name="agentmemory.worker.log",
        stderr_name="agentmemory.worker.err.log",
    ),
    ServiceSpec(
        name="hermes_codex",
        port=8642,
        cmd=[_hermes_exe, "gateway", "run", "--accept-hooks"],
        cwd=PROJECT_ROOT,
        health_url="http://127.0.0.1:8642/health",
        depends_on=["agentmemory"],
        stdout_name="hermes_gateway.log",
        stderr_name="hermes_gateway_err.log",
    ),
    ServiceSpec(
        name="hermes_dashboard",
        port=9119,
        cmd=[_hermes_exe, "dashboard", "--port", "9119", "--host", "127.0.0.1", "--no-open", "--skip-build"],
        cwd=PROJECT_ROOT,
        health_url="http://127.0.0.1:9119",
        depends_on=["hermes_codex"],
        stdout_name="hermes_dashboard.log",
        stderr_name="hermes_dashboard_err.log",
    ),
]


class CampaignLease:
    """Singleton file-based lease for the RankStein campaign."""

    def __init__(self):
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        self.pid = os.getpid()
        self.started_at = time.time()

    def acquire(self) -> bool:
        if CAMPAIGN_LEASE_FILE.exists():
            try:
                data = json.loads(CAMPAIGN_LEASE_FILE.read_text(encoding="utf-8"))
                existing_pid = int(data.get("pid", 0))
                if existing_pid and self._process_alive(existing_pid):
                    logger.warning(f"Campaign already running with PID {existing_pid}")
                    return False
            except (ValueError, OSError):
                pass

        try:
            # Atomic lock (kinda) by creating exclusively if possible
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            fd = os.open(CAMPAIGN_LEASE_FILE, flags)
            os.write(fd, json.dumps({"pid": self.pid, "started_at": self.started_at}).encode("utf-8"))
            os.close(fd)
            return True
        except FileExistsError:
            return False

    def release(self) -> None:
        try:
            if CAMPAIGN_LEASE_FILE.exists():
                data = json.loads(CAMPAIGN_LEASE_FILE.read_text(encoding="utf-8"))
                if int(data.get("pid", 0)) == self.pid:
                    CAMPAIGN_LEASE_FILE.unlink()
        except (ValueError, OSError):
            pass

    @staticmethod
    def _process_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            import ctypes

            process_query_limited_information = 0x1000
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_int
            handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
            if not handle:
                return False
            kernel32.CloseHandle(handle)
            return True
        try:
            os.kill(pid, 0)
        except (OSError, SystemError):
            return False
        return True


def force_clear_stale_lease() -> None:
    """Remove campaign lease if the holder process is dead."""
    if not CAMPAIGN_LEASE_FILE.exists():
        return
    try:
        data = json.loads(CAMPAIGN_LEASE_FILE.read_text(encoding="utf-8"))
        pid = int(data.get("pid", 0))
        if pid and CampaignLease._process_alive(pid):
            return  # Lease holder is still running
    except (ValueError, OSError):
        pass
    try:
        CAMPAIGN_LEASE_FILE.unlink(missing_ok=True)
        logger.info("Cleared stale campaign lease")
    except OSError:
        pass


def reset_stale_service_state() -> None:
    """Clear restart budgets for services whose port holder is dead.

    Called before ``start_services`` to prevent permanent startup lockouts
    when a previous session crashed without cleaning up.
    """
    if not SERVICES_STATE_FILE.exists():
        return
    try:
        state = json.loads(SERVICES_STATE_FILE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return

    changed = False
    for spec in SERVICES:
        svc = state.get(spec.name)
        if not svc or svc.get("restarts", 0) < spec.max_restart_per_hour:
            continue
        # Budget is exhausted — check if the port is actually held by a live process
        if _port_open(spec.port):
            # Something is listening; leave the budget alone
            continue
        # Port is free but budget is exhausted from a previous crash — reset it
        logger.info(
            "Resetting restart budget for %s (port %d free, budget was %d/%d)",
            spec.name,
            spec.port,
            svc["restarts"],
            spec.max_restart_per_hour,
        )
        state[spec.name] = {"hour": svc.get("hour", ""), "restarts": 0}
        changed = True

    if changed:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        SERVICES_STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def _port_open(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _http_probe(url: str, timeout: float = 2.0) -> dict[str, Any]:
    if not (url.startswith("http://") or url.startswith("https://")):
        return {"ok": False, "error": f"Unsupported URL scheme: {url}"}
    try:
        from urllib.request import Request

        headers = {"User-Agent": "rankstein-suite"}
        if ":3111" in url:
            secret = os.environ.get("AGENTMEMORY_SECRET")
            if not secret:
                secret_path = Path.home() / ".agentmemory" / "secret"
                if secret_path.exists():
                    import contextlib

                    with contextlib.suppress(Exception):
                        secret = secret_path.read_text(encoding="utf-8").strip()
            if secret:
                headers["Authorization"] = f"Bearer {secret}"
        req = Request(url, headers=headers)  # noqa: S310
        with urlopen(req, timeout=timeout) as response:  # noqa: S310
            status = response.getcode()
            body = response.read(4096).decode("utf-8", errors="replace")[:200]
        return {"ok": 200 <= status < 300, "status": status, "body": body}
    except URLError as e:
        return {"ok": False, "error": str(e.reason)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _start_background(spec: ServiceSpec) -> subprocess.Popen:
    log_dir = DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    stdout_path = log_dir / spec.stdout_name
    stderr_path = log_dir / spec.stderr_name

    out = open(stdout_path, "a")
    err = open(stderr_path, "a")

    flags = 0
    if os.name == "nt":
        flags = (
            subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )

    return subprocess.Popen(
        spec.cmd, cwd=str(spec.cwd), stdout=out, stderr=err, creationflags=flags, env=os.environ.copy()
    )


def preflight() -> dict[str, Any]:
    """Verify prerequisites before starting any service."""
    report = {"ok": True, "issues": []}

    # Check disk
    disk = log_manager.check_disk_space()
    if not disk["ok"]:
        report["ok"] = False
        report["issues"].append(disk["error"])

    # Check python env
    if not PROJECT_PYTHON.exists():
        report["ok"] = False
        report["issues"].append(f"Virtualenv python missing: {PROJECT_PYTHON}")

    # Check Hermes
    if "hermes_codex" not in external_services() and (not _hermes_exe or not shutil.which(_hermes_exe)):
        report["ok"] = False
        report["issues"].append("Hermes CLI not found on PATH")

    # Try compiling MCP server
    mcp_script = PROJECT_ROOT / "rankstein_mcp_server.py"
    if mcp_script.exists():
        try:
            subprocess.run(
                [str(PROJECT_PYTHON), "-m", "py_compile", str(mcp_script)], check=True, capture_output=True
            )
        except subprocess.CalledProcessError:
            report["ok"] = False
            report["issues"].append("Syntax error in rankstein_mcp_server.py")

    return report


def _service_probe(spec: ServiceSpec) -> dict[str, Any]:
    result = _http_probe(spec.health_url) if spec.health_url else {"ok": True}
    if spec.name == "operator" and result.get("ok"):
        try:
            result["ok"] = json.loads(result.get("body", "{}")).get("service") == "rankstein-operator"
        except ValueError:
            result["ok"] = False
    return result


def get_service_status() -> dict[str, Any]:
    """Get the current running status of all services."""
    statuses = {}
    external = external_services()
    for spec in SERVICES:
        is_open = _port_open(spec.port)
        health = _service_probe(spec) if is_open else None
        statuses[spec.name] = {
            "port_open": is_open,
            "healthy": health.get("ok") if health else False,
            "health_details": health,
            "optional": spec.optional,
            "external": spec.name in external,
        }
    return statuses


def start_services() -> dict[str, Any]:
    """Start all services in dependency order with backoff and retry budget."""
    force_clear_stale_lease()

    # Rotate logs before starting
    log_manager.maintain()

    pre = preflight()
    if not pre["ok"]:
        logger.error(f"Preflight failed: {pre['issues']}")
        return {"ok": False, "preflight": pre, "services": {}}

    # Load restart state
    state = {}
    if SERVICES_STATE_FILE.exists():
        try:
            state = json.loads(SERVICES_STATE_FILE.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug("Could not load services state file: %s", exc)

    current_hour = datetime.now(UTC).strftime("%Y%m%d%H")

    results = {}
    external = external_services()
    for spec in SERVICES:
        # Externally owned (e.g. Docker): probe only, never start or kill.
        if spec.name in external:
            is_open = _port_open(spec.port)
            health = _service_probe(spec) if is_open else None
            healthy = bool(is_open and (health is None or health.get("ok")))
            results[spec.name] = {
                "ok": healthy or spec.optional,
                "started_now": False,
                "external": True,
                "healthy": healthy,
            }
            if not healthy:
                logger.warning(f"External service {spec.name} on port {spec.port} is not healthy")
            continue

        # Check dependencies
        deps_met = all(results.get(dep, {}).get("ok", False) for dep in spec.depends_on)
        if not deps_met:
            results[spec.name] = {"ok": False, "skipped": True, "error": "Dependencies not met"}
            continue

        # Check if already running
        if _port_open(spec.port):
            health = _service_probe(spec)
            if health.get("ok"):
                results[spec.name] = {"ok": True, "started_now": False, "already_running": True}
                continue

        # Never kill an unrelated process merely because it owns a desired port.
        if _port_open(spec.port):
            results[spec.name] = {
                "ok": False,
                "error": f"Port {spec.port} is occupied by an unhealthy or different service; no process was killed",
            }
            continue

        # Check restart budget
        service_state = state.setdefault(spec.name, {"hour": current_hour, "restarts": 0})
        if service_state.get("hour") != current_hour:
            service_state = {"hour": current_hour, "restarts": 0}
            state[spec.name] = service_state

        if service_state["restarts"] >= spec.max_restart_per_hour:
            logger.warning(f"Service {spec.name} exceeded restart budget ({spec.max_restart_per_hour}/hour)")
            results[spec.name] = {"ok": False, "skipped": True, "error": "Restart budget exceeded"}
            if not spec.optional:
                # Failing a required service blocks dependents but doesn't necessarily crash the suite
                pass
            continue

        # Try to start with retries
        max_attempts = 3
        startup_timeout = 45  # seconds to wait for port & health per attempt
        success = False

        for attempt in range(max_attempts):
            logger.info(f"Starting {spec.name} on port {spec.port} (attempt {attempt + 1}/{max_attempts})")
            proc = _start_background(spec)

            # Wait up to startup_timeout seconds for port and health check
            start_time = time.time()
            while time.time() - start_time < startup_timeout:
                if _port_open(spec.port):
                    if spec.health_url:
                        h = _service_probe(spec)
                        if h.get("ok"):
                            success = True
                            break
                    else:
                        success = True
                        break
                time.sleep(1)

            if success:
                results[spec.name] = {"ok": True, "started_now": True}
                service_state["restarts"] += 1
                if proc is not None:
                    service_state["pid"] = proc.pid
                break

            logger.warning(
                f"{spec.name} failed to become healthy within {startup_timeout}s (attempt {attempt + 1})"
            )
            if proc is not None and proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=10)
            time.sleep(2)

        if not success:
            results[spec.name] = {"ok": False, "error": f"Failed all {max_attempts} startup attempts"}
            service_state["restarts"] += max_attempts

    # Save state
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    SERVICES_STATE_FILE.write_text(json.dumps(state), encoding="utf-8")

    return {"ok": all(r.get("ok", False) for r in results.values()), "services": results}


def _kill_port(port: int) -> None:
    """Kill whatever is listening on a port."""
    if os.name == "nt":
        try:
            # netstat -ano | findstr :PORT
            netstat = subprocess.run(["netstat", "-ano"], capture_output=True, text=True)
            for line in netstat.stdout.splitlines():
                if f":{port} " in line and "LISTENING" in line:
                    parts = line.split()
                    pid = parts[-1]
                    if pid != "0":
                        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
        except Exception as exc:
            logger.debug("Failed to kill port %s: %s", port, exc)


def stop_services() -> None:
    """Stop services gracefully in reverse dependency order."""
    # First request supervisor stop if it's running
    try:
        # Import dynamically to avoid circular dependencies if any
        from pinterest_automation.runtime_state import request_supervisor_stop, supervisor_status

        status = supervisor_status()
        if status["running"]:
            request_supervisor_stop()
            # Wait up to 30 seconds for graceful shutdown
            for _ in range(30):
                if not supervisor_status()["running"]:
                    break
                time.sleep(1)
    except Exception as exc:
        logger.debug("Failed to gracefully stop supervisor: %s", exc)

    # Stop services in reverse order (externally owned services are left alone)
    external = external_services()
    for spec in reversed(SERVICES):
        if spec.name in external:
            continue
        _stop_owned_service(spec)


def _stop_owned_service(spec: ServiceSpec) -> bool:
    """Stop only the process whose command matches this suite service."""
    import psutil

    try:
        state = json.loads(SERVICES_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    pid = (state.get(spec.name) or {}).get("pid")
    if not pid and spec.name == "operator":
        health = _service_probe(spec)
        if health.get("ok"):
            pid = json.loads(health.get("body", "{}")).get("pid")
    if not pid:
        logger.warning("Leaving %s alone: no owned PID recorded", spec.name)
        return False
    try:
        process = psutil.Process(int(pid))
        args = process.cmdline()
        expected = [str(arg).casefold() for arg in spec.cmd[1:]]
        if any(arg not in [value.casefold() for value in args] for arg in expected):
            logger.warning("Leaving PID %s alone: %s command identity does not match", pid, spec.name)
            return False
        if os.name == "nt":
            result = subprocess.run(
                ["taskkill.exe", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15
            )
            return result.returncode == 0
        process.terminate()
        process.wait(timeout=10)
        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
        return False


def restart_services() -> dict[str, Any]:
    """Stop and then start services."""
    stop_services()
    time.sleep(2)
    return start_services()


def install_tasks(*, daily_at: str = "06:30") -> None:
    """Install Windows Scheduled Tasks."""
    if os.name != "nt":
        raise RuntimeError("Windows tasks are only supported on Windows")
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", daily_at):
        raise ValueError("Daily time must be HH:MM in local time")
    script_path = str(PROJECT_ROOT / "rankstein.py")
    python_exe = str(PROJECT_PYTHON)

    # 1. Logon Task (starts infrastructure)
    cmd1 = f"""
    $Action = New-ScheduledTaskAction -Execute "{python_exe}" -Argument '"{script_path}" suite start' -WorkingDirectory "{PROJECT_ROOT}"
    $Trigger = New-ScheduledTaskTrigger -AtLogOn
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)
    Register-ScheduledTask -TaskName "RankStein-Suite-Startup" -Action $Action -Trigger $Trigger -Settings $Settings -Force
    """

    # 2. Daily Campaign Task (starts the pipeline)
    cmd2 = f"""
    $Action = New-ScheduledTaskAction -Execute "{python_exe}" -Argument '"{script_path}" launch --all --keywords 1 --workers 1' -WorkingDirectory "{PROJECT_ROOT}"
    $Trigger = New-ScheduledTaskTrigger -Daily -At {daily_at}
    $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    Register-ScheduledTask -TaskName "RankStein-Daily-Campaign" -Action $Action -Trigger $Trigger -Settings $Settings -Force
    """

    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd1], check=True)
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd2], check=True)
    print("Installed Windows Scheduled Tasks: RankStein-Suite-Startup, RankStein-Daily-Campaign")


def uninstall_tasks() -> None:
    """Uninstall Windows Scheduled Tasks."""
    cmd = """
    $Tasks = @("RankStein-Suite-Startup", "RankStein-Daily-Campaign")
    foreach ($T in $Tasks) {
        if (Get-ScheduledTask -TaskName $T -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $T -Confirm:$false
            Write-Host "Removed $T"
        }
    }
    """
    subprocess.run(["powershell.exe", "-Command", cmd], check=True)
    print("Uninstalled Windows Scheduled Tasks")


def restart_service(name: str) -> dict[str, Any]:
    """Restart one suite-owned service, never unrelated or externally owned processes."""
    spec = next((service for service in SERVICES if service.name == name), None)
    if spec is None:
        return {"ok": False, "error": "Unknown suite service"}
    if name in external_services():
        return {"ok": False, "error": "Service is externally managed; restart it through its owner"}
    if _port_open(spec.port) and not _stop_owned_service(spec):
        return {"ok": False, "error": "Service ownership could not be verified; no process was stopped"}
    deadline = time.monotonic() + 10
    while _port_open(spec.port) and time.monotonic() < deadline:
        time.sleep(0.2)
    if _port_open(spec.port):
        return {"ok": False, "error": "Service port remains occupied"}
    return start_services()


def ensure_services_running() -> dict[str, Any]:
    """Helper for launcher.py to ensure dependencies are met."""
    return start_services()

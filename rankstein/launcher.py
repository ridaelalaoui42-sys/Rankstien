"""Unified launch and health orchestration for RankStein production runs."""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from rankstein import log_manager, suite_controller
from rankstein.domain import DomainRegistry
from rankstein.production_safety import campaign_admission
from rankstein.runtime_env import clean_python_env
from rankstein.startup import StartupOptions, run_startup

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECT_PYTHON = (
    PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if os.name == "nt"
    else PROJECT_ROOT / ".venv" / "bin" / "python"
)
if not PROJECT_PYTHON.exists():
    PROJECT_PYTHON = Path(sys.executable)
LOG_DIR = PROJECT_ROOT / "data" / "logs"
SERVICE_LOG_DIR = LOG_DIR / "services"
REPORT_DIR = PROJECT_ROOT / "data" / "reports" / "launcher"
logger = logging.getLogger("rankstein.launcher")


@dataclass
class LaunchOptions:
    domains: list[str] | None = None
    keywords_per_domain: int = 3
    workers_per_domain: int = 1
    refresh_trends: bool = True
    trend_limit_per_domain: int = 10
    monitor_seconds: int = 180
    monitor_interval_seconds: int = 30
    start_services: bool = True
    start_articles: bool = True
    start_supervisor: bool = True
    start_frontend: bool = False
    skip_odysseus_server: bool = False
    skip_validation: bool = False
    json_output: bool = False


def run_launch(options: LaunchOptions) -> dict[str, Any]:
    SERVICE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    started_local = datetime.now()
    started_at = datetime.now(UTC)
    report: dict[str, Any] = {
        "started_at": started_at.isoformat(),
        "project_root": str(PROJECT_ROOT),
        "options": _serializable_options(options),
        "mcp": {},
        "services": {},
        "preflight": {},
        "queue_normalization": {},
        "validation": {},
        "processes": {},
        "monitor": [],
        "issues": [],
    }

    _remember("rankstein_launcher_start", "RankStein unified launcher started.", report["options"])

    suite_controller.force_clear_stale_lease()
    if options.start_services:
        suite_controller.reset_stale_service_state()

    if options.start_services:
        _launch_progress(options, "Starting production services")
        suite_res = suite_controller.start_services()
        report["mcp"] = {"ok": suite_res.get("ok", False)}
        report["services"].update(suite_res.get("services", {}))
    else:
        report["mcp"] = {"skipped": True}

    report["services"].update(_collect_service_status(options))

    # Verify AgentMemory is actually healthy, not just port-open
    if not _http_probe("http://127.0.0.1:3111/agentmemory/health").get("ok"):
        _add_issue(report, "AgentMemory port open but health check failed")

    report["processes"] = _collect_process_status()
    _dedupe_singleton_processes(report)
    _add_duplicate_process_issues(report)

    report["queue_normalization"] = _normalize_queue_boards()

    if not options.skip_validation:
        _launch_progress(options, "Running production validation")
        report["validation"] = _run_validation()
    else:
        report["validation"] = {"skipped": True}

    _launch_progress(
        options,
        "Running Pinterest-first keyword research preflight "
        "(precise Pinterest candidates, then independent Google demand/freshness validation)",
    )
    domains = DomainRegistry(PROJECT_ROOT).all()
    if options.domains:
        domains = [domain for domain in domains if domain.handle in options.domains]
    report["production_admission"] = campaign_admission(
        domains, campaigns_per_domain=options.keywords_per_domain
    )
    if options.start_articles and not report["production_admission"]["ok"]:
        reason = "; ".join(report["production_admission"]["issues"])
        report["preflight"] = {"brief": {"work_ready": False, "launch_blocked_reason": reason}}
    else:
        report["preflight"] = run_startup(
            StartupOptions(
                domains=options.domains,
                keywords_per_domain=options.keywords_per_domain,
                workers_per_domain=options.workers_per_domain,
                launch=False,
                refresh_trends=options.refresh_trends,
                trend_limit_per_domain=options.trend_limit_per_domain,
            )
        )

    if options.start_articles:
        if report["preflight"]["brief"].get("work_ready"):
            _launch_progress(options, "Starting article creation and publishing workers")
            report["services"]["article_workers"] = _ensure_article_workers(options)
        else:
            reason = report["preflight"]["brief"].get(
                "launch_blocked_reason",
                "No publishable Pending keywords were discovered.",
            )
            report["services"]["article_workers"] = {
                "running": False,
                "started": False,
                "error": reason,
            }
            report["article_start_blocked"] = True
            report["issues"].append(reason)
    else:
        report["services"]["article_workers"] = {"skipped": True}

    if options.start_supervisor:
        report["services"]["pinterest_supervisor"] = _ensure_supervisor()
    else:
        report["services"]["pinterest_supervisor"] = {"skipped": True}

    report["services"].update(_collect_service_status(options))
    report["processes"] = _collect_process_status()
    _dedupe_singleton_processes(report)
    _add_duplicate_process_issues(report)

    if options.monitor_seconds > 0:
        _launch_progress(options, "Monitoring live workflow services")
        report["monitor"] = _monitor(options.monitor_seconds, options.monitor_interval_seconds)

    report["log_scan"] = _scan_recent_logs(since=started_local)
    report["issues"].extend(report["log_scan"].get("issues", []))
    report["issues"] = sorted(set(report["issues"]))
    report["finished_at"] = datetime.now(UTC).isoformat()
    report["ok"] = not report["issues"] and not report.get("article_start_blocked", False)
    report["report_path"] = str(_write_report(report))
    _remember(
        "rankstein_launcher_finish",
        "RankStein unified launcher finished.",
        {
            "report_path": report["report_path"],
            "issues": len(report["issues"]),
            "services": report["services"],
        },
    )
    return report


def _launch_progress(options: LaunchOptions, message: str) -> None:
    if not options.json_output:
        print(f"[launch] {message}", flush=True)


def print_launch_report(report: dict[str, Any], *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        return

    print("\nRankStein Launch Brief")
    print("=" * 24)
    for name, status in report.get("services", {}).items():
        state = "running" if status.get("running") else "started" if status.get("started") else "skipped"
        if status.get("error"):
            state = f"error: {status['error']}"
        print(f"- {name}: {state}")

    queue = _latest_queue(report)
    if queue:
        by_status = queue.get("by_status", {})
        print(
            f"\nQueue: total={queue.get('total', 0)} pending={by_status.get('pending', 0)} "
            f"processing={by_status.get('processing', 0)} retry={by_status.get('retry', 0)} "
            f"dlq={queue.get('dlq_size', 0)}"
        )

    issues = report.get("issues", [])
    if issues:
        print("\nIssues")
        for issue in issues[:10]:
            print(f"- {issue}")
    else:
        print("\nIssues: none detected in current launcher scan")

    print(f"\nReport: {report.get('report_path')}")


def _serializable_options(options: LaunchOptions) -> dict[str, Any]:
    return {
        "domains": options.domains,
        "keywords_per_domain": options.keywords_per_domain,
        "workers_per_domain": options.workers_per_domain,
        "refresh_trends": options.refresh_trends,
        "trend_limit_per_domain": options.trend_limit_per_domain,
        "monitor_seconds": options.monitor_seconds,
        "monitor_interval_seconds": options.monitor_interval_seconds,
        "start_services": options.start_services,
        "start_articles": options.start_articles,
        "start_supervisor": options.start_supervisor,
        "start_frontend": options.start_frontend,
        "skip_odysseus_server": options.skip_odysseus_server,
        "skip_validation": options.skip_validation,
    }


def _ensure_article_workers(options: LaunchOptions) -> dict[str, Any]:
    resources = log_manager.check_resource_budget()
    if not resources["ok"]:
        return {"running": False, "started": False, "error": "; ".join(resources["issues"])}
    matches = _find_processes("turbo_articles.py")
    if matches:
        return {"running": True, "started": False, "processes": matches}
    proxy_url = _model_proxy_url()
    command = [
        str(PROJECT_PYTHON),
        str(PROJECT_ROOT / "backend" / "scripts" / "turbo_articles.py"),
        "--workers",
        str(options.workers_per_domain),
        "--limit",
        str(options.keywords_per_domain),
        "--once",
    ]
    if options.domains:
        if len(options.domains) != 1:
            return {"running": False, "started": False, "error": "Select one domain or all domains"}
        command.extend(["--domain", options.domains[0]])
    else:
        command.append("--all-domains")
    proc = _start_background(
        command,
        PROJECT_ROOT,
        "articles.log",
        "articles_err.log",
        env_extra={"RANKSTEIN_GEMINI_PROXY_URL": proxy_url},
    )
    return {"running": True, "started": True, "pid": proc.pid, "model_proxy_url": proxy_url}


def _model_proxy_url() -> str:
    # The operator on 7000 is not a model proxy. Legacy proxy use is opt-in.
    return "http://127.0.0.1:8000/gemini/v1/chat/completions"


def _ensure_supervisor() -> dict[str, Any]:
    matches = _find_processes("run_autonomous.py")
    if matches:
        cleanup = _dedupe_matches(matches)
        if cleanup["stopped"]:
            return {
                "running": True,
                "started": False,
                "processes": cleanup["kept"],
                "dedupe": cleanup,
            }
        return {"running": True, "started": False, "processes": matches}
    proc = _start_background(
        [str(PROJECT_PYTHON), "-u", str(PROJECT_ROOT / "run_autonomous.py"), "run"],
        PROJECT_ROOT,
        "rankstein_supervisor.log",
        "rankstein_supervisor_err.log",
        env_extra={"RANKSTEIN_SKIP_SUPERVISOR_ARTICLES": "1"},
    )
    return {"running": True, "started": True, "pid": proc.pid}


def _start_background(
    cmd: list[str],
    cwd: Path,
    stdout_name: str,
    stderr_name: str,
    env_extra: dict[str, str] | None = None,
) -> subprocess.Popen:
    env = clean_python_env()
    if env_extra:
        env.update(env_extra)
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | 0x01000000  # CREATE_BREAKAWAY_FROM_JOB
        )
    stdout_path = SERVICE_LOG_DIR / stdout_name
    stderr_path = SERVICE_LOG_DIR / stderr_name
    stdout = stdout_path.open("ab")
    stderr = stderr_path.open("ab")
    try:
        kwargs = {
            "cwd": cwd,
            "env": env,
            "stdout": stdout,
            "stderr": stderr,
            "stdin": subprocess.DEVNULL,
            "creationflags": creationflags,
            "close_fds": True,
        }
        try:
            return subprocess.Popen(cmd, **kwargs)
        except OSError:
            if os.name != "nt" or not creationflags:
                raise
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            return subprocess.Popen(cmd, **kwargs)
    finally:
        stdout.close()
        stderr.close()


def _collect_service_status(options: LaunchOptions) -> dict[str, dict[str, Any]]:
    statuses = {
        "agentmemory": {"running": _port_open(3111), "port": 3111},
        "hermes_codex": {
            "running": _port_open(8642),
            "port": 8642,
            "health": _http_probe("http://127.0.0.1:8642/health"),
        },
        "hermes_dashboard": {
            "running": _port_open(9119),
            "port": 9119,
            "health": _http_probe("http://127.0.0.1:9119"),
        },
        "odysseus_proxy": (
            {
                "running": _port_open(8000),
                "port": 8000,
                "health": _http_probe("http://127.0.0.1:8000/health"),
            }
            if os.environ.get("RANKSTEIN_ENABLE_ODYSSEUS_PROXY", "").lower() in {"1", "true", "yes", "on"}
            else {"skipped": True, "optional": True}
        ),
    }
    health = _http_probe("http://127.0.0.1:7000/health")
    statuses["operator"] = {
        "running": health.get("ok", False),
        "port": 7000,
        "url": "http://127.0.0.1:7000/operator",
    }
    return statuses


def _collect_process_status() -> dict[str, Any]:
    return {
        "mcp_servers": _find_processes("rankstein_mcp_server.py"),
        "article_workers": _find_processes("turbo_articles.py"),
        "remasterers": _find_processes("backend\\services\\remasterer.py")
        + _find_processes("backend/services/remasterer.py"),
        "pinterest_supervisors": _find_processes("run_autonomous.py"),
        "odysseus_proxy": _find_processes("ody_proxy.py"),
    }


def _add_duplicate_process_issues(report: dict[str, Any]) -> None:
    processes = report.get("processes", {})
    for label in ("article_workers", "pinterest_supervisors", "odysseus_proxy"):
        count = len(processes.get(label, []))
        if count > 1:
            _add_issue(report, f"duplicate {label}: {count} processes detected")


def _dedupe_singleton_processes(report: dict[str, Any]) -> None:
    # Python virtualenv shims and their child interpreter share a command.
    # Matching text is not ownership proof and must never authorize a kill.
    report["process_cleanup"] = {"automatic_kills": False, "reason": "Lease-owned execution only"}


def _dedupe_matches(matches: list[dict[str, Any]]) -> dict[str, Any]:
    if len(matches) <= 1:
        return {"kept": matches, "stopped": []}
    ordered = sorted(matches, key=_process_preference, reverse=True)
    kept = [ordered[0]]
    stopped = []
    for item in ordered[1:]:
        pid = item.get("pid")
        stopped.append({**item, "stopped": _stop_pid(pid)})
    return {"kept": kept, "stopped": stopped}


def _process_preference(item: dict[str, Any]) -> tuple[int, int, int]:
    command = str(item.get("command") or "").lower()
    preferred_env = int("\\.venv\\" in command or "/.venv/" in command)
    try:
        pid = int(item.get("pid") or 0)
    except Exception:
        pid = 0
    try:
        from pinterest_automation.runtime_state import supervisor_status

        lease_owner = int(pid == int(supervisor_status().get("pid") or 0))
    except Exception:
        lease_owner = 0
    return lease_owner, preferred_env, pid


def _stop_pid(pid: Any) -> bool:
    if not pid:
        return False
    try:
        if os.name == "nt":
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    f"Stop-Process -Id {int(pid)} -Force -ErrorAction SilentlyContinue",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        os.kill(int(pid), 15)
        return True
    except Exception:
        return False


def _add_issue(report: dict[str, Any], issue: str) -> None:
    issues = report.setdefault("issues", [])
    if issue not in issues:
        issues.append(issue)


def _normalize_queue_boards() -> dict[str, Any]:
    try:
        from pinterest_automation import get_job_queue

        return get_job_queue().normalize_board_names_in_storage(include_dlq=True)
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _run_validation() -> dict[str, Any]:
    script = PROJECT_ROOT / "scripts" / "dev" / "validate_automation.py"
    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=PROJECT_ROOT,
            env=clean_python_env(),
            capture_output=True,
            text=True,
            timeout=120,
        )
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout_tail": result.stdout[-3000:],
            "stderr_tail": result.stderr[-3000:],
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _monitor(seconds: int, interval: int) -> list[dict[str, Any]]:
    snapshots = []
    deadline = time.monotonic() + seconds
    while True:
        snapshots.append(_snapshot())
        if time.monotonic() >= deadline:
            return snapshots
        time.sleep(max(5, min(interval, int(deadline - time.monotonic()) or interval)))


def _snapshot() -> dict[str, Any]:
    snap: dict[str, Any] = {"timestamp": datetime.now(UTC).isoformat()}
    try:
        from pinterest_automation import get_health_monitor, get_job_queue

        health = get_health_monitor().get_snapshot()
        snap["health"] = {
            "all_ok": health.all_ok,
            "checks": health.checks,
            "consecutive_failures": health.consecutive_failures,
        }
        snap["queue"] = get_job_queue().get_stats()
    except Exception as exc:
        snap["health_error"] = str(exc)
    snap["ports"] = {str(port): _port_open(port) for port in (3111, 7000, 8000, 8642, 9119, 3001)}
    return snap


def _scan_recent_logs(since: datetime | None = None) -> dict[str, Any]:
    files = [
        LOG_DIR / "automation.log",
        LOG_DIR / "articles_err.log",
        SERVICE_LOG_DIR / "rankstein_supervisor_err.log",
        SERVICE_LOG_DIR / "articles_err.log",
        LOG_DIR / "remasterer_err.log",
        SERVICE_LOG_DIR / "ody_proxy_err.log",
        SERVICE_LOG_DIR / "operator_err.log",
    ]
    patterns = {
        "pinterest login/session issue": (
            "login failed",
            "not logged in",
            "login_required",
            "pinterest login",
        ),
        "invalid article category": ("invalid category",),
        "api authentication issue": ("http 401", "authenticationerror", "token_invalidated"),
        "service connection issue": ("connection error", "connection refused", "not reachable"),
        "worker crash": ("traceback", "crash:", "failed after", "exception"),
    }
    issues: list[str] = []
    scanned: dict[str, int] = {}
    for path in files:
        if not path.exists():
            continue
        text = _filter_log_since(_tail_text(path, 80_000), since).lower()
        scanned[str(path)] = len(text)
        for label, needles in patterns.items():
            if any(needle in text for needle in needles):
                issues.append(f"{label} in {path.name}")
    return {"scanned": scanned, "issues": sorted(set(issues))}


def _filter_log_since(text: str, since: datetime | None) -> str:
    if since is None:
        return text
    kept: list[str] = []
    include_continuation = False
    for line in text.splitlines():
        line_time = _parse_log_timestamp(line)
        if line_time is not None:
            include_continuation = line_time >= since
        if include_continuation:
            kept.append(line)
    return "\n".join(kept)


def _parse_log_timestamp(line: str) -> datetime | None:
    if len(line) < 19:
        return None
    try:
        return datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _latest_queue(report: dict[str, Any]) -> dict[str, Any] | None:
    monitor = report.get("monitor") or []
    for item in reversed(monitor):
        if item.get("queue"):
            return item["queue"]
    try:
        from pinterest_automation import get_job_queue

        return get_job_queue().get_stats()
    except Exception:
        return None


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _wait_for_port(port: int, timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_open(port):
            return True
        time.sleep(1)
    return _port_open(port)


def _http_probe(url: str) -> dict[str, Any]:
    try:
        headers = {"User-Agent": "rankstein-launcher"}
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
        with urlopen(req, timeout=5) as resp:  # noqa: S310
            resp.read(1)
        return {"ok": True, "status": resp.status}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _find_processes(needle: str) -> list[dict[str, Any]]:
    if os.name == "nt":
        safe = needle.replace("'", "''")
        ps = (
            f"$needle = '{safe}'; "
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.CommandLine -and $_.CommandLine.Contains($needle) } | "
            "Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress"
        )
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
                capture_output=True,
                text=True,
                timeout=20,
            )
            raw = result.stdout.strip()
            if not raw:
                return []
            parsed = json.loads(raw)
            items = parsed if isinstance(parsed, list) else [parsed]
            matching_pids = {int(item.get("ProcessId") or 0) for item in items if item.get("ProcessId")}
            parent_pids = {
                int(item.get("ParentProcessId") or 0)
                for item in items
                if int(item.get("ParentProcessId") or 0) in matching_pids
            }
            matches = []
            for item in items:
                command = item.get("CommandLine", "") or ""
                if not item.get("ProcessId") or "Get-CimInstance Win32_Process" in command:
                    continue
                if int(item["ProcessId"]) in parent_pids:
                    continue
                matches.append({"pid": item.get("ProcessId"), "command": command})
            return matches
        except Exception:
            return []

    try:
        result = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True, text=True, timeout=20)
    except Exception:
        return []
    matches = []
    for line in result.stdout.splitlines():
        if needle not in line:
            continue
        pid, _, command = line.strip().partition(" ")
        if pid.isdigit():
            matches.append({"pid": int(pid), "command": command})
    return matches


def _tail_text(path: Path, max_bytes: int) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(-max_bytes, os.SEEK_END)
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _write_report(report: dict[str, Any]) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    path = REPORT_DIR / f"launch_{stamp}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def _remember(event_type: str, message: str, metadata: dict[str, Any]) -> None:
    if os.environ.get("RANKSTEIN_LAUNCHER_MEMORY", "").lower() not in {"1", "true", "yes"}:
        return
    try:
        from backend.services.memory_service import memory as agent_memory

        health = agent_memory.health()
        if not health.get("ok"):
            return
        agent_memory.search("RankStein launch Odysseus MCP Pinterest queue lessons", 5)
        agent_memory.log_event(event_type, message, metadata)
    except Exception as exc:
        logger.debug("AgentMemory launch event was not recorded: %s", exc)

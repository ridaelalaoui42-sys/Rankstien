from __future__ import annotations

import json
import os
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path

RANKSTEIN = Path(r"C:\Users\REDX420\Desktop\Rankstein")
PYTHON = Path(r"C:\Program Files\Python312\python.exe")
LOG_DIR = RANKSTEIN / "data" / "logs"
REPORT_DIR = RANKSTEIN / "data" / "reports" / "campaigns"


def _now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except OSError:
        return False


def _clean_env() -> dict[str, str]:
    env = os.environ.copy()
    for var in (
        "PYTHONHOME",
        "UV_INTERNAL__PYTHONHOME",
        "PYTHONPATH",
        "VIRTUAL_ENV",
    ):
        env.pop(var, None)
    env.setdefault("HERMES_HOME", r"C:\ProgramData\hermes")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("RANKSTEIN_ENABLE_REMASTER_SIPHON", "1")
    return env


def _run(args: list[str], timeout: int = 60) -> tuple[int, str]:
    env = _clean_env()
    try:
        proc = subprocess.run(
            args,
            cwd=str(RANKSTEIN),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        out = "\n".join(part for part in [stdout, stderr] if part)
        return proc.returncode, out.strip()
    except Exception as exc:
        return 1, str(exc)


def _ps_contains(needle: str) -> bool:
    if os.name != "nt":
        code, out = _run(["ps", "-eo", "args"], timeout=10)
        return code == 0 and needle in out
    safe = needle.replace("'", "''")
    ps = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        f"$needle = '{safe}'; "
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -and ($_.CommandLine -like ('*' + $needle + '*')) "
        "-and ($_.CommandLine -notlike '*Get-CimInstance Win32_Process*') } | "
        "Select-Object -First 1 ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    code, out = _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps], timeout=15)
    return code == 0 and bool(out.strip())


def _start_background(args: list[str], log_name: str) -> int | None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    env = _clean_env()
    stdout = open(LOG_DIR / log_name, "a", encoding="utf-8")
    stderr = open(LOG_DIR / f"{Path(log_name).stem}_err.log", "a", encoding="utf-8")
    proc = subprocess.Popen(
        args,
        cwd=str(RANKSTEIN),
        env=env,
        stdout=stdout,
        stderr=stderr,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    return proc.pid


def _latest_report() -> dict:
    reports = sorted(REPORT_DIR.glob("*_remaster_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        return {}
    path = reports[0]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"path": str(path), "error": str(exc)}
    enqueue = data.get("enqueue") if isinstance(data.get("enqueue"), dict) else {}
    return {
        "path": str(path),
        "slug": data.get("slug", ""),
        "domain": data.get("domain_handle", ""),
        "generated": data.get("generated_count", 0),
        "target": data.get("target_count", 30),
        "missing": data.get("missing_count", 0),
        "jobs_enqueued": enqueue.get("jobs_enqueued", 0),
        "success": bool(data.get("success")),
    }


def _file_age_minutes(path: Path) -> float | None:
    try:
        return (datetime.now(UTC).timestamp() - path.stat().st_mtime) / 60
    except OSError:
        return None


def _health_json() -> dict:
    code, out = _run([str(PYTHON), "run_autonomous.py", "status"], timeout=90)
    return {"ok": code == 0, "summary": "\n".join(out.splitlines()[:16])}


def _pinterest_admission() -> dict:
    code, out = _run(
        [
            str(PYTHON),
            "-c",
            "import json; from pinterest_automation.runtime_state import supervisor_admission_status; "
            "print(json.dumps(supervisor_admission_status()))",
        ],
        timeout=30,
    )
    if code == 0:
        try:
            status = json.loads(out)
            if (
                isinstance(status, dict)
                and isinstance(status.get("can_start"), bool)
                and isinstance(status.get("reason"), str)
                and status["reason"]
            ):
                return status
        except (ValueError, TypeError):
            pass
    return {"can_start": False, "reason": "ownership_unverified"}


def main() -> int:
    actions: list[str] = []
    warnings: list[str] = []
    blockers: list[str] = []

    if not RANKSTEIN.exists():
        print(f"RankStein watchdog failed: project not found at {RANKSTEIN}")
        return 2

    ports = {
        "hermes_api": _port_open(8642),
        "hermes_dashboard": _port_open(9119),
        "whatsapp_bridge": _port_open(3000),
        "odysseus_proxy": _port_open(8000),
        "odysseus_server": _port_open(7000),
    }

    if not ports["hermes_api"]:
        blockers.append("Hermes API server is not listening on 8642; Codex article generation cannot run.")
    if not ports["whatsapp_bridge"]:
        warnings.append("WhatsApp bridge is not listening on 3000 (session inactive).")

    supervisor_admission = _pinterest_admission()
    supervisor_state = {
        "live_owner": "running",
        "maintenance": "maintenance",
    }.get(supervisor_admission["reason"], "blocked")
    remaster_running = _ps_contains("backend\\services\\remasterer.py") or _ps_contains(
        "backend/services/remasterer.py"
    )
    articles_running = _ps_contains("backend\\scripts\\turbo_articles.py") or _ps_contains(
        "backend/scripts/turbo_articles.py"
    )
    article_log_age = min(
        [
            age
            for age in (
                _file_age_minutes(LOG_DIR / "articles.log"),
                _file_age_minutes(LOG_DIR / "articles_err.log"),
            )
            if age is not None
        ]
        or [None]
    )
    article_idle = articles_running and (article_log_age is None or article_log_age > 90)

    if supervisor_admission["can_start"]:
        pid = _start_background(
            [str(PYTHON), "-u", str(RANKSTEIN / "run_autonomous.py"), "run"], "automation.log"
        )
        actions.append(f"started Pinterest supervisor pid={pid}")
        supervisor_state = "started"
    elif supervisor_admission["reason"] in {"ownership_unverified", "conflicting_owners"}:
        blockers.append("Pinterest supervisor startup deferred: lease ownership could not be verified.")

    if not remaster_running:
        pid = _start_background(
            [
                str(PYTHON),
                str(RANKSTEIN / "backend" / "services" / "remasterer.py"),
                "--all-domains",
                "--continuous",
                "--limit",
                "3",
                "--pins-per-keyword",
                "30",
            ],
            "remasterer.log",
        )
        actions.append(f"started continuous remasterer pid={pid}")

    if not articles_running or article_idle:
        pid = _start_background(
            [
                str(PYTHON),
                str(RANKSTEIN / "backend" / "scripts" / "turbo_articles.py"),
                "--all-domains",
                "--workers",
                "1",
                "--limit",
                "1",
                "--once",
            ],
            "articles.log",
        )
        reason = "idle existing worker" if article_idle else "missing worker"
        actions.append(f"started Codex-first all-domain article batch pid={pid} ({reason})")

    health = _health_json()
    report = _latest_report()

    if not actions and not blockers:
        print("[SILENT]")
        return 0

    lines = [
        "RankStein campaign watchdog",
        f"Time: {_now()}",
        "",
        "Provider default: Hermes Codex article generation via http://127.0.0.1:8642/v1",
        "Ports: " + ", ".join(f"{name}={'ok' if ok else 'down'}" for name, ok in ports.items()),
        "Workers: "
        + ", ".join(
            [
                f"pinterest_supervisor={supervisor_state}",
                f"remasterer={'running' if remaster_running else 'started'}",
                f"article_worker={'running' if articles_running and not article_idle else 'started'}",
            ]
        ),
    ]
    if actions:
        lines.extend(["", "Actions:", *[f"- {item}" for item in actions]])
    if report:
        lines.extend(
            [
                "",
                "Latest remaster report:",
                f"- slug: {report.get('slug')}",
                f"- domain: {report.get('domain')}",
                f"- remasters: {report.get('generated')}/{report.get('target')} missing={report.get('missing')}",
                f"- jobs enqueued: {report.get('jobs_enqueued')}",
                f"- path: {report.get('path')}",
            ]
        )
    if not health.get("ok"):
        blockers.append("RankStein status command failed.")
    if warnings:
        lines.extend(["", "Warnings:", *[f"- {item}" for item in warnings]])
    if blockers:
        lines.extend(["", "Blockers:", *[f"- {item}" for item in blockers]])
    if health.get("summary"):
        lines.extend(["", "Status excerpt:", health["summary"]])

    print("\n".join(lines))
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())

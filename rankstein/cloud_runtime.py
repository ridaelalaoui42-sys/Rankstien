"""Opt-in Linux worker entrypoints with bounded daily attempts and private state."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from filelock import FileLock, Timeout

from rankstein.config import PROJECT_ROOT

RUNTIME = PROJECT_ROOT / "data" / "runtime" / "cloud"


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def due(now: datetime, daily_at: str, journal: dict) -> bool:
    hour, minute = (int(value) for value in daily_at.split(":"))
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError("Daily time must be HH:MM")
    return (now.hour, now.minute) >= (hour, minute) and journal.get("date") != now.date().isoformat()


def configured_domains(root: Path = PROJECT_ROOT) -> list:
    from rankstein.domain import DomainRegistry

    registry = DomainRegistry(root)
    manifests = sorted((root / "data" / "domains").glob("*/domain.json"))
    if not manifests:
        raise ValueError(
            "Explicit private domain manifests are required; legacy defaults are not cloud configuration"
        )
    expected = {path.parent.name for path in manifests}
    domains = registry.all()
    if {domain.handle for domain in domains if not domain.is_synthesized} != expected:
        raise ValueError("At least one private domain manifest is invalid")
    return [domain for domain in domains if not domain.is_synthesized]


def doctor(*, root: Path = PROJECT_ROOT, probe: bool = True) -> dict:
    from rankstein.suite_controller import _http_probe

    issues = []
    rows = []
    try:
        domains = configured_domains(root)
        account_map = json.loads(os.environ.get("PINTEREST_DOMAIN_ACCOUNT_MAP", "{}"))
        if not isinstance(account_map, dict):
            raise ValueError("Invalid account routing")
        for domain in domains:
            accounts = account_map.get(domain.handle, [])
            ready = bool(domain.supabase_url and domain.supabase_service_role_key.get_secret_value())
            if not ready or not isinstance(accounts, list) or not accounts:
                issues.append(f"{domain.handle}: missing Supabase credentials or explicit account routing")
            rows.append({"handle": domain.handle, "supabase_configured": ready, "account_handles": accounts})
    except (ValueError, KeyError, OSError):
        issues.append("Cloud domain configuration is incomplete")
    if os.environ.get("RANKSTEIN_ARTICLE_PROVIDER", "hermes-codex") != "hermes-codex":
        issues.append("Cloud article provider must explicitly use hermes-codex")
    services = {}
    if probe:
        hermes = os.environ.get("RANKSTEIN_HERMES_CODEX_URL", "http://127.0.0.1:8642/v1").rstrip("/")
        for name, url in {
            "operator": "http://127.0.0.1:7000/health",
            "hermes_codex": hermes.removesuffix("/v1") + "/health",
            "agentmemory": "http://127.0.0.1:3111/agentmemory/health",
        }.items():
            services[name] = bool(_http_probe(url).get("ok"))
            if not services[name]:
                issues.append(f"{name}: health check failed")
    return {
        "ok": not issues,
        "issues": issues,
        "domains": rows,
        "services": services,
        "browser_login_verified": False,
        "provider_generation_verified": False,
    }


class Runner:
    def __init__(self, role: str):
        self.role = role
        self.stop = threading.Event()
        self.child: subprocess.Popen | None = None
        self.state = "starting"

    def shutdown(self, *_args) -> None:
        self.stop.set()

    def heartbeat(self) -> None:
        while not self.stop.is_set():
            atomic_json(
                RUNTIME / f"{self.role}.json",
                {
                    "role": self.role,
                    "pid": os.getpid(),
                    "heartbeat_at": datetime.now(UTC).isoformat(),
                    "state": self.state,
                    "child_pid": self.child.pid if self.child and self.child.poll() is None else None,
                },
            )
            self.stop.wait(10)

    def command(self, args: list[str], *, timeout: int) -> int:
        log = PROJECT_ROOT / "data" / "logs" / f"cloud_{self.role}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        with log.open("ab") as output:
            self.child = subprocess.Popen(
                args, cwd=PROJECT_ROOT, stdout=output, stderr=subprocess.STDOUT, start_new_session=True
            )
            try:
                while self.child.poll() is None:
                    if self.stop.wait(1) or time.monotonic() - started > timeout:
                        os.killpg(self.child.pid, signal.SIGTERM)
                        try:
                            self.child.wait(timeout=60)
                        except subprocess.TimeoutExpired:
                            os.killpg(self.child.pid, signal.SIGKILL)
                            self.child.wait()
                        return 124 if not self.stop.is_set() else 143
                return self.child.returncode
            finally:
                self.child = None

    def run(self) -> int:
        if sys.platform != "linux":
            raise ValueError("Cloud worker entrypoints require Linux")
        if os.environ.get("RANKSTEIN_CLOUD_PRODUCTION_ENABLED") != "1":
            raise ValueError("Cloud publishing is disabled; complete the migration gates before activation")
        readiness = doctor()
        if not readiness["ok"]:
            print(json.dumps(readiness))
            return 2
        signal.signal(signal.SIGTERM, self.shutdown)
        signal.signal(signal.SIGINT, self.shutdown)
        RUNTIME.mkdir(parents=True, exist_ok=True)
        with FileLock(str(RUNTIME / f"{self.role}.lock"), timeout=0):
            thread = threading.Thread(target=self.heartbeat, daemon=True)
            thread.start()
            try:
                if self.role == "supervisor":
                    self.state = "running"
                    return self.command(
                        [sys.executable, "-u", "run_autonomous.py", "run"], timeout=365 * 86400
                    )
                return self.schedule()
            finally:
                self.stop.set()
                thread.join(timeout=15)
                atomic_json(
                    RUNTIME / f"{self.role}.json",
                    {"role": self.role, "state": "stopped", "heartbeat_at": datetime.now(UTC).isoformat()},
                )

    def schedule(self) -> int:
        from rankstein.production_safety import campaign_admission

        zone = ZoneInfo(os.environ.get("RANKSTEIN_CLOUD_TIMEZONE", "Africa/Casablanca"))
        daily_at = os.environ.get("RANKSTEIN_CLOUD_DAILY_AT", "06:30")
        timeout = int(os.environ.get("RANKSTEIN_CLOUD_CAMPAIGN_TIMEOUT_SECONDS", "3600"))
        if not 60 <= timeout <= 14400:
            raise ValueError("Daily attempt timeout must be between 60 and 14400 seconds")
        journal_path = RUNTIME / "daily_attempt.json"
        while not self.stop.is_set():
            journal = json.loads(journal_path.read_text(encoding="utf-8")) if journal_path.exists() else {}
            now = datetime.now(zone)
            self.state = "idle"
            if due(now, daily_at, journal):
                admission = campaign_admission(configured_domains())
                if not admission["ok"]:
                    self.state = "admission_blocked"
                elif not doctor()["ok"]:
                    self.state = "dependency_unavailable"
                else:
                    # Claim before any write/publish. A restart never repeats the same day automatically.
                    journal = {
                        "date": now.date().isoformat(),
                        "state": "claimed",
                        "started_at": datetime.now(UTC).isoformat(),
                        "publishing_verified": False,
                    }
                    atomic_json(journal_path, journal)
                    self.state = "preflight"
                    code = self.command(
                        [
                            sys.executable,
                            "rankstein.py",
                            "launch",
                            "--all",
                            "--keywords",
                            "1",
                            "--workers",
                            "1",
                            "--no-services",
                            "--no-articles",
                            "--no-supervisor",
                            "--monitor-seconds",
                            "0",
                            "--json",
                        ],
                        timeout=timeout,
                    )
                    if code == 0 and not self.stop.is_set():
                        self.state = "campaign_attempt"
                        code = self.command(
                            [
                                sys.executable,
                                "backend/scripts/turbo_articles.py",
                                "--all-domains",
                                "--workers",
                                "1",
                                "--limit",
                                "1",
                                "--once",
                            ],
                            timeout=timeout,
                        )
                    journal.update(
                        state="attempt_finished" if code == 0 else "attempt_failed",
                        returncode=code,
                        finished_at=datetime.now(UTC).isoformat(),
                    )
                    atomic_json(journal_path, journal)
            self.stop.wait(60)
        return 0


def health(role: str) -> bool:
    try:
        payload = json.loads((RUNTIME / f"{role}.json").read_text(encoding="utf-8"))
        heartbeat = datetime.fromisoformat(payload["heartbeat_at"])
        age = (datetime.now(UTC) - heartbeat).total_seconds()
        return 0 <= age < 90 and payload.get("state") != "stopped"
    except (OSError, ValueError, KeyError, TypeError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("doctor", "scheduler", "supervisor", "health"))
    parser.add_argument("--role", choices=("scheduler", "supervisor"), default="scheduler")
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            report = doctor()
            print(json.dumps(report, indent=2))
            return 0 if report["ok"] else 2
        if args.command == "health":
            return 0 if health(args.role) else 1
        return Runner(args.command).run()
    except (ValueError, OSError, Timeout) as exc:
        print(f"Cloud runtime stopped: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

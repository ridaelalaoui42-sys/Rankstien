"""RankStein operator bridge routes.

RankStein owns this control plane and uses its maintained production entrypoints.
Auth/config files are reported only as present or missing.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
import tomllib
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from backend.api.operator_auth import require_admin
from backend.services.operator_pipeline import STAGE_DEFINITIONS, build_pipeline_payload

RANKSTEIN_ROOT = Path(os.getenv("RANKSTEIN_ROOT", str(Path(__file__).resolve().parents[2])))
LOG_DIR = RANKSTEIN_ROOT / "data" / "logs" / "operator"
PROCESS_FILE = RANKSTEIN_ROOT / "data" / "runtime" / "operator_processes.json"
CODEX_HOME = Path(os.getenv("CODEX_HOME", str(Path.home() / ".codex")))
OPENCODE_CONFIG = Path.home() / ".config" / "opencode" / "opencode.json"
RUN_START_PATTERN = re.compile(r"(?m)^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] START ")
PROCESS_LOCK = threading.RLock()
STATUS_CACHE_LOCK = threading.Lock()
STATUS_CACHE_TTL_SECONDS = max(
    1.0,
    float(os.getenv("RANKSTEIN_STATUS_CACHE_TTL_SECONDS", "10")),
)
_STATUS_CACHE: tuple[float, dict[str, Any]] | None = None
PREVIEW_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

ACTION_LABELS = {
    "production": "Production Batch",
    "full": "Start Publishing",
    "audit": "Audit",
    "trends": "Trend Discovery",
    "mcp": "MCP Check",
    "supervisor": "Supervisor",
    "remaster": "Remaster",
    "normalize-boards": "Normalize Boards",
    "launch": "Launch",
}

ACTION_STAGES = {
    "production": (
        (5, "Starting bounded production batch", "] START "),
        (12, "Selecting domain keywords", "worker started"),
        (
            22,
            "Finding Pinterest-origin keyword candidates",
            "Triggering trend refresh",
        ),
        (
            24,
            "Validating Pinterest candidates with independent demand signals",
            "Queue empty —",
        ),
        (28, "Researching and writing articles", "Processing keyword"),
        (50, "Publishing verified articles", "Article published"),
        (68, "Publishing primary pins", "Primary pin published"),
        (82, "Launching paired pin campaigns", "Pinterest siphon launched"),
        (90, "Waiting for Pinterest pin and campaign verification", "Published article target reached"),
        (96, "Waiting for final domain target", "production target reached"),
    ),
    "mcp": (
        (8, "Starting process", "] START "),
        (24, "Loading environment", "Loading environment"),
        (42, "Checking AgentMemory", "AgentMemory"),
        (62, "Validating MCP server", "Validating rankstein_mcp_server"),
        (80, "Checking Supabase", "Supabase URL detected"),
        (96, "Infrastructure ready", "All MCP infrastructure checks passed"),
    ),
    "full": (
        (8, "Starting production launcher", "] START "),
        (22, "Starting workflow services", "Starting production services"),
        (48, "Researching new keywords", "multi-source keyword research preflight"),
        (
            72,
            "Starting article workers",
            "Starting article creation and publishing workers",
        ),
        (88, "Monitoring live workflow", "Monitoring live workflow services"),
        (98, "Writing launch report", "RankStein Launch Brief"),
    ),
    "audit": (
        (8, "Starting process", "] START "),
        (20, "Booting MCP services", "MCP Bootstrapping"),
        (38, "Checking AgentMemory", "AgentMemory"),
        (55, "Validating infrastructure", "All MCP servers ready"),
        (75, "Auditing domains", '"domains"'),
        (92, "Writing audit report", '"created_campaigns"'),
    ),
    "launch": (
        (8, "Starting launcher", "] START "),
        (24, "Checking services", "service"),
        (45, "Running preflight", "preflight"),
        (65, "Starting workers", "worker"),
        (82, "Monitoring health", "monitor"),
        (96, "Writing launch report", "report"),
    ),
    "supervisor": (
        (8, "Starting supervisor", "] START "),
        (30, "Opening queue", "queue"),
        (52, "Starting workers", "Worker"),
        (70, "Publishing Pinterest jobs", "publish"),
        (78, "Monitoring automation", "[STATUS]"),
    ),
    "remaster": (
        (8, "Starting remaster enqueue", "] START "),
        (36, "Scanning generated images", "images"),
        (68, "Enqueuing Pinterest jobs", "jobs_enqueued"),
        (92, "Finalizing batch", '"success"'),
    ),
    "normalize-boards": (
        (8, "Starting board normalization", "] START "),
        (45, "Normalizing active queue", "active_changed"),
        (78, "Normalizing dead-letter queue", "dlq_changed"),
    ),
}


def _resolve_production_batch_request(
    requested_batch_id: str,
    target_per_domain: int,
) -> tuple[str, int]:
    """Create a new batch ID or safely inherit an incomplete batch target."""
    target = max(1, min(int(target_per_domain), 20))
    if not requested_batch_id:
        return f"production-{time.strftime('%Y%m%d-%H%M%S')}", target
    if not re.fullmatch(r"production-\d{8}-\d{6}", requested_batch_id):
        raise HTTPException(400, "Invalid production batch ID")

    report_path = RANKSTEIN_ROOT / "data" / "reports" / "production_batches" / f"{requested_batch_id}.json"
    if not report_path.is_file():
        raise HTTPException(404, "Production batch report not found")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        persisted_target = int(report["target_per_domain"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(409, "Production batch report is not resumable") from exc
    if report.get("batch_id") != requested_batch_id:
        raise HTTPException(409, "Production batch identity mismatch")
    if report.get("state") == "complete":
        raise HTTPException(409, "Completed production batches cannot be resumed")
    if not 1 <= persisted_target <= 20:
        raise HTTPException(409, "Production batch target is invalid")
    return requested_batch_id, persisted_target


def setup_rankstein_routes() -> APIRouter:
    router = APIRouter(prefix="/api/rankstein", tags=["rankstein"])

    @router.get("/status")
    def status(request: Request) -> dict[str, Any]:
        require_admin(request)
        return _cached_status_payload()

    @router.get("/asset-preview")
    def asset_preview(path: str, request: Request) -> FileResponse:
        require_admin(request)
        try:
            asset = _resolve_rankstein_preview(path)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        media_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }
        return FileResponse(
            asset,
            media_type=media_types[asset.suffix.lower()],
            headers={"Cache-Control": "private, max-age=60"},
        )

    @router.get("/architecture")
    def architecture(request: Request) -> dict[str, Any]:
        require_admin(request)
        doc_path = RANKSTEIN_ROOT / "docs" / "system" / "SYSTEM_ARCHITECTURE.md"
        content = ""
        if doc_path.exists():
            content = doc_path.read_text(encoding="utf-8")
        return {
            "ok": True,
            "title": "RankStein System Architecture",
            "path": str(doc_path),
            "content": content,
            "links": {
                "operator_ui": "http://127.0.0.1:7000/operator",
                "hermes_codex": "http://127.0.0.1:8642",
                "agentmemory": "http://127.0.0.1:3111",
                "agentmemory_viewer": "http://127.0.0.1:3113",
                "recetadolce": "https://recetadolce.com",
                "recetagenial": "https://recetagenial.com",
                "supabase_dolce": "https://xjvmnmfczvwkjiasirsl.supabase.co",
                "supabase_genial": "https://hokcljsrrnjxzgdhjice.supabase.co",
            },
        }

    @router.post("/start/{mode}")
    def start(
        mode: str,
        request: Request,
        target_per_domain: int = 10,
        workers: int = 1,
        batch_id: str = "",
        domain: str = "",
    ) -> dict[str, Any]:
        require_admin(request)
        workers = max(1, min(int(workers), 2))
        batch_id, target_per_domain = _resolve_production_batch_request(
            batch_id,
            target_per_domain,
        )
        commands = {
            "production": [
                _rankstein_python(),
                str(RANKSTEIN_ROOT / "backend" / "scripts" / "turbo_articles.py"),
                "--all-domains",
                "--workers",
                str(workers),
                "--limit",
                str(target_per_domain),
                "--success-target-per-domain",
                str(target_per_domain),
                "--batch-id",
                batch_id,
            ],
            "mcp": [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(RANKSTEIN_ROOT / "scripts" / "dev" / "start_all_mcp.ps1"),
                "-StatusOnly",
            ],
            "audit": [
                _rankstein_python(),
                str(RANKSTEIN_ROOT / "rankstein.py"),
                "run",
                "--no-launch",
                "--json",
            ],
            "full": [
                _rankstein_python(),
                str(RANKSTEIN_ROOT / "rankstein.py"),
                "launch",
                "--skip-validation",
                "--monitor-seconds",
                "60",
                "--monitor-interval",
                "10",
            ],
            "supervisor": [
                _rankstein_python(),
                str(RANKSTEIN_ROOT / "run_autonomous.py"),
                "run",
            ],
            "launch": [
                _rankstein_python(),
                str(RANKSTEIN_ROOT / "rankstein.py"),
                "launch",
                "--skip-validation",
                "--monitor-seconds",
                "60",
            ],
            "remaster": [
                _rankstein_python(),
                str(RANKSTEIN_ROOT / "run_autonomous.py"),
                "enqueue-folder",
            ],
            "normalize-boards": [
                _rankstein_python(),
                str(RANKSTEIN_ROOT / "run_autonomous.py"),
                "normalize-queue-boards",
            ],
        }
        if mode not in commands:
            raise HTTPException(404, "Unknown RankStein mode")
        _apply_domain_scope(commands[mode], mode, domain)
        proc = _start_background(mode, commands[mode])
        return {
            "ok": True,
            "mode": mode,
            "pid": proc.pid,
            "log": str(LOG_DIR / f"{mode}.log"),
            **({"batch_id": batch_id} if mode == "production" else {}),
        }

    @router.get("/logs/{mode}")
    def logs(mode: str, request: Request) -> dict[str, str]:
        require_admin(request)
        if not mode.replace("-", "").replace("_", "").isalnum():
            raise HTTPException(400, "Invalid log name")
        text, _updated_at = _read_action_log(mode)
        return {"log": _redact_log(text)}

    @router.get("/control/status")
    def control_status(request: Request) -> dict[str, Any]:
        require_admin(request)
        return _control_payload()

    @router.post("/control/start/rankstein/{mode}")
    def control_start_rankstein(
        mode: str,
        request: Request,
        target_per_domain: int = 10,
        workers: int = 1,
        batch_id: str = "",
        domain: str = "",
    ) -> dict[str, Any]:
        require_admin(request)
        supervisor_workers = max(1, min(int(workers or 2), 10))
        article_workers = max(1, min(int(workers), 2))
        batch_id, target_per_domain = _resolve_production_batch_request(
            batch_id,
            target_per_domain,
        )
        modes = {
            "production": [
                _rankstein_python(),
                str(RANKSTEIN_ROOT / "backend" / "scripts" / "turbo_articles.py"),
                "--all-domains",
                "--workers",
                str(article_workers),
                "--limit",
                str(target_per_domain),
                "--success-target-per-domain",
                str(target_per_domain),
                "--batch-id",
                batch_id,
            ],
            "audit": [
                _rankstein_python(),
                str(RANKSTEIN_ROOT / "rankstein.py"),
                "run",
                "--no-launch",
                "--json",
            ],
            "full": [
                _rankstein_python(),
                str(RANKSTEIN_ROOT / "rankstein.py"),
                "launch",
                "--skip-validation",
                "--monitor-seconds",
                "60",
                "--monitor-interval",
                "10",
            ],
            "supervisor": [
                _rankstein_python(),
                str(RANKSTEIN_ROOT / "run_autonomous.py"),
                "run",
                "--workers",
                str(supervisor_workers),
            ],
            "launch": [
                _rankstein_python(),
                str(RANKSTEIN_ROOT / "rankstein.py"),
                "launch",
                "--skip-validation",
                "--monitor-seconds",
                "60",
            ],
            "mcp": [
                "powershell",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(RANKSTEIN_ROOT / "scripts" / "dev" / "start_all_mcp.ps1"),
                "-StatusOnly",
            ],
            "remaster": [
                _rankstein_python(),
                str(RANKSTEIN_ROOT / "run_autonomous.py"),
                "enqueue-folder",
            ],
            "normalize-boards": [
                _rankstein_python(),
                str(RANKSTEIN_ROOT / "run_autonomous.py"),
                "normalize-queue-boards",
            ],
        }
        if mode not in modes:
            raise HTTPException(404, f"Unsupported mode: {mode}")
        _apply_domain_scope(modes[mode], mode, domain)
        proc = _start_background(mode, modes[mode])
        return {
            "ok": True,
            "mode": mode,
            "pid": proc.pid,
            **({"batch_id": batch_id} if mode == "production" else {}),
        }

    @router.post("/control/stop/{mode}")
    def control_stop_rankstein(mode: str, request: Request) -> dict[str, Any]:
        require_admin(request)
        if mode == "supervisor":
            from pinterest_automation.runtime_state import request_supervisor_stop

            result = request_supervisor_stop()
            return {"ok": result.get("success", False), **result}
        if mode not in ACTION_LABELS:
            raise HTTPException(404, "Unsupported tracked process")
        with PROCESS_LOCK:
            processes = _load_processes()
            info = dict(processes.get(mode) or {})
            pid = int(info.get("pid", 0) or 0)
            if not pid or not _pid_alive(pid, info.get("command"), info.get("started_at")):
                return {"ok": True, "mode": mode, "stopped": False, "reason": "not_running"}
            if not _kill_pid_tree(pid):
                raise HTTPException(
                    503, "The owned process could not be stopped; no stopped state was recorded"
                )
            info["stop_requested"] = True
            info["finished_at"] = int(time.time())
            info["returncode"] = None
            processes[mode] = info
            _save_processes(processes)
            return {"ok": True, "mode": mode, "pid": pid, "stopped": True}

    @router.get("/control/agentmemory/status")
    def control_agentmemory_status(request: Request) -> dict[str, Any]:
        require_admin(request)
        from rankstein.suite_controller import _http_probe

        probe = _http_probe("http://127.0.0.1:3111/agentmemory/livez")
        if not probe.get("ok"):
            probe = _http_probe("http://127.0.0.1:3111/agentmemory/health")
        return probe

    @router.post("/control/agentmemory/restart")
    def control_agentmemory_restart(request: Request):
        require_admin(request)
        from rankstein.suite_controller import restart_service

        return restart_service("agentmemory")

    @router.get("/pins")
    def list_pins(
        request: Request,
        limit: int = 100,
        account: str = "",
        search: str = "",
    ) -> dict[str, Any]:
        require_admin(request)
        return _get_recent_pins(limit=limit, account=account, search=search)

    @router.get("/keywords")
    def list_keywords(
        request: Request,
        domain: str = "recetadolce",
        search: str = "",
        status: str = "",
    ) -> dict[str, Any]:
        require_admin(request)
        return _get_domain_keywords(domain=domain, search=search, status=status)

    @router.get("/articles")
    def list_articles(
        request: Request,
        domain: str = "recetadolce",
        limit: int = 40,
    ) -> dict[str, Any]:
        require_admin(request)
        return _fetch_supabase_articles(domain=domain, limit=limit)

    @router.post("/control/requeue-dlq")
    def control_requeue_dlq(request: Request) -> dict[str, Any]:
        require_admin(request)
        return _requeue_dlq_jobs()

    @router.post("/control/refresh-trends")
    def control_refresh_trends(
        request: Request,
        domain: str = "recetadolce",
    ) -> dict[str, Any]:
        require_admin(request)
        return _trigger_trend_refresh(domain=domain)

    @router.get("/board-mappings")
    def get_board_mappings(request: Request) -> dict[str, Any]:
        require_admin(request)
        return _get_board_mappings()

    @router.get("/seo-feedback")
    def get_seo_feedback(request: Request) -> dict[str, Any]:
        require_admin(request)
        return _get_seo_feedback_report()

    @router.post("/control/seo-feedback/refresh")
    def refresh_seo_feedback(request: Request) -> dict[str, Any]:
        require_admin(request)
        return _run_seo_feedback_refresh()

    @router.post("/control/seo-feedback/add-to-roadmap")
    async def add_seo_recommendation_to_roadmap(request: Request) -> dict[str, Any]:
        require_admin(request)
        body = await request.json()
        return _add_recommendation_to_roadmap(body)

    @router.post("/control/seo-feedback/add-all-post-more")
    def add_all_post_more_keywords(request: Request) -> dict[str, Any]:
        require_admin(request)
        return _add_all_post_more_to_roadmap()

    @router.post("/control/seo-feedback/purge-avoid-topics")
    def purge_avoid_topics(request: Request) -> dict[str, Any]:
        require_admin(request)
        return _purge_avoid_topics_from_roadmap()

    @router.post("/control/seo-feedback/launch-remaster")
    async def launch_seo_remaster(request: Request) -> dict[str, Any]:
        require_admin(request)
        body = await request.json()
        return _launch_seo_remaster(body)

    @router.post("/control/seo-feedback/launch-single-turbo")
    async def launch_seo_turbo(request: Request) -> dict[str, Any]:
        require_admin(request)
        body = await request.json()
        return _launch_seo_single_turbo(body)

    @router.get("/stream/events")
    async def stream_events(request: Request):
        require_admin(request)
        return StreamingResponse(_event_stream_generator(request), media_type="text/event-stream")

    @router.get("/telemetry/gauges")
    def get_telemetry_gauges(request: Request) -> dict[str, Any]:
        require_admin(request)
        return {"ok": True, "telemetry": _collect_telemetry_gauges()}

    @router.get("/workers/snapshots")
    def get_workers_snapshots(request: Request) -> dict[str, Any]:
        require_admin(request)
        return {"ok": True, "workers": _collect_workers_snapshots()}

    @router.post("/services/{service_name}/action")
    async def service_action(service_name: str, request: Request) -> dict[str, Any]:
        require_admin(request)
        body = (
            await request.json()
            if request.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        action = body.get("action", "start")
        workers = body.get("workers")
        return _manage_service_action(service_name, action, workers=workers)

    @router.post("/control/purge-locks")
    def purge_locks(request: Request) -> dict[str, Any]:
        require_admin(request)
        return _purge_system_locks()

    @router.post("/control/clear-drafts")
    def clear_drafts(request: Request) -> dict[str, Any]:
        require_admin(request)
        return _run_clear_drafts_script()

    @router.get("/accounts/cohorts")
    def get_accounts_cohorts(request: Request) -> dict[str, Any]:
        require_admin(request)
        return _get_accounts_management_payload()

    @router.post("/control/accounts/save")
    async def save_pinterest_account(request: Request) -> dict[str, Any]:
        require_admin(request)
        body = await request.json()
        return _save_account(body)

    @router.post("/control/accounts/connect-blog")
    async def connect_account_blog(request: Request) -> dict[str, Any]:
        require_admin(request)
        body = await request.json()
        return _connect_account_blog(body)

    @router.post("/control/accounts/delete")
    async def delete_pinterest_account(request: Request) -> dict[str, Any]:
        require_admin(request)
        body = await request.json()
        return _delete_account(body)

    @router.post("/campaigns/launch")
    async def launch_custom_campaign(request: Request) -> dict[str, Any]:
        require_admin(request)
        body = await request.json()
        return _launch_campaign(body)

    @router.post("/campaigns/{campaign_id}/pause")
    def pause_campaign(campaign_id: str, request: Request) -> dict[str, Any]:
        require_admin(request)
        return _toggle_campaign_pause(campaign_id, paused=True)

    @router.post("/campaigns/{campaign_id}/resume")
    def resume_campaign(campaign_id: str, request: Request) -> dict[str, Any]:
        require_admin(request)
        return _toggle_campaign_pause(campaign_id, paused=False)

    @router.post("/campaigns/{campaign_id}/rerun-step")
    async def rerun_campaign_step(campaign_id: str, request: Request) -> dict[str, Any]:
        require_admin(request)
        body = (
            await request.json()
            if request.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        return _rerun_step(campaign_id, body.get("step", ""))

    @router.post("/campaigns/{campaign_id}/override-step")
    async def override_campaign_step(campaign_id: str, request: Request) -> dict[str, Any]:
        require_admin(request)
        body = await request.json()
        return _override_step(campaign_id, body)

    @router.post("/campaigns/{campaign_id}/force-verify")
    def force_verify_campaign(campaign_id: str, request: Request) -> dict[str, Any]:
        require_admin(request)
        return _force_verify_campaign(campaign_id)

    @router.delete("/campaigns/{campaign_id}")
    def delete_campaign(campaign_id: str, request: Request) -> dict[str, Any]:
        require_admin(request)
        return _abort_and_delete_campaign(campaign_id)

    @router.get("/queue/jobs")
    def list_queue_jobs(
        request: Request,
        page: int = 1,
        limit: int = 50,
        status: str = "all",
        search: str = "",
    ) -> dict[str, Any]:
        require_admin(request)
        return _get_queue_jobs_paged(page=page, limit=limit, status=status, search=search)

    @router.post("/queue/jobs/{job_id}/requeue")
    def requeue_queue_job(job_id: str, request: Request) -> dict[str, Any]:
        require_admin(request)
        return _requeue_single_job(job_id)

    @router.put("/queue/jobs/{job_id}")
    async def update_queue_job(job_id: str, request: Request) -> dict[str, Any]:
        require_admin(request)
        body = await request.json()
        return _update_queue_job_payload(job_id, body)

    @router.delete("/queue/jobs/{job_id}")
    def delete_queue_job(job_id: str, request: Request) -> dict[str, Any]:
        require_admin(request)
        return _delete_queue_job(job_id)

    @router.post("/queue/purge-dlq")
    def purge_queue_dlq(request: Request) -> dict[str, Any]:
        require_admin(request)
        return _purge_dlq()

    @router.post("/queue/retry-all-dlq")
    def retry_all_dlq_jobs(request: Request) -> dict[str, Any]:
        require_admin(request)
        return _retry_all_dlq()

    @router.post("/queue/normalize-boards")
    def normalize_queue_boards_action(request: Request) -> dict[str, Any]:
        require_admin(request)
        return _run_normalize_boards()

    @router.post("/queue/pause-processing")
    async def toggle_queue_pause(request: Request) -> dict[str, Any]:
        require_admin(request)
        body = (
            await request.json()
            if request.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        return _set_queue_processing_paused(body.get("paused"))

    @router.post("/keywords")
    async def create_keyword(request: Request) -> dict[str, Any]:
        require_admin(request)
        body = await request.json()
        return _create_keyword_entry(body)

    @router.patch("/keywords/{domain}/{keyword}")
    async def patch_keyword(domain: str, keyword: str, request: Request) -> dict[str, Any]:
        require_admin(request)
        body = await request.json()
        return _update_keyword_status(domain, keyword, body)

    @router.delete("/keywords/{domain}/{keyword}")
    def delete_keyword(domain: str, keyword: str, request: Request) -> dict[str, Any]:
        require_admin(request)
        return _delete_keyword_entry(domain, keyword)

    @router.post("/keywords/{domain}/{keyword}/run")
    def run_keyword_pipeline(domain: str, keyword: str, request: Request) -> dict[str, Any]:
        require_admin(request)
        return _run_single_keyword_pipeline(domain, keyword)

    return router


def _get_recent_pins(limit: int = 100, account: str = "", search: str = "") -> dict[str, Any]:
    csv_path = RANKSTEIN_ROOT / "data" / "logs" / "success_tracker.csv"
    if not csv_path.exists():
        return {
            "ok": True,
            "total": 0,
            "today_count": 0,
            "last_timestamp": "",
            "pins": [],
            "accounts": [],
        }
    try:
        with open(csv_path, encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "total": 0, "pins": []}

    rows = [
        row
        for row in rows
        if str(row.get("pin_id", "")).isdigit()
        or re.fullmatch(r"https://(?:[a-z]+\.)?pinterest\.com/pin/\d+/?", row.get("pin_url", ""))
    ]
    total = len(rows)
    accounts = sorted(list({r.get("account", "").strip() for r in rows if r.get("account", "").strip()}))
    today_prefix = datetime.now(UTC).strftime("%Y-%m-%d")
    today_count = sum(1 for r in rows if (r.get("timestamp") or "").startswith(today_prefix))
    by_account = Counter(r.get("account", "unknown") for r in rows)

    filtered = []
    search_lower = search.strip().lower()
    for row in reversed(rows):
        if account and row.get("account", "").strip().lower() != account.lower():
            continue
        if search_lower:
            target = (row.get("target") or "").lower()
            pin_id = (row.get("pin_id") or "").lower()
            if search_lower not in target and search_lower not in pin_id:
                continue
        filtered.append(
            {
                "timestamp": row.get("timestamp", ""),
                "account": row.get("account", ""),
                "type": row.get("type", "upload"),
                "pin_id": row.get("pin_id", ""),
                "pin_url": row.get("pin_url", ""),
                "target": row.get("target", ""),
            }
        )
        if len(filtered) >= max(1, min(limit, 500)):
            break

    return {
        "ok": True,
        "total": total,
        "today_count": today_count,
        "last_timestamp": rows[-1].get("timestamp") if rows else "",
        "by_account": dict(by_account),
        "accounts": accounts,
        "pins": filtered,
    }


def _get_domain_keywords(domain: str = "recetadolce", search: str = "", status: str = "") -> dict[str, Any]:
    domain = re.sub(r"[^a-zA-Z0-9_\-]", "", domain) or "recetadolce"
    path = RANKSTEIN_ROOT / "data" / "domains" / domain / "keywords.md"
    if not path.exists():
        return {
            "ok": False,
            "error": f"Keywords file not found for {domain}",
            "keywords": [],
        }

    rows = []
    status_counts: Counter[str] = Counter()
    search_lower = search.strip().lower()
    status_filter = status.strip().lower()

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("|") or line.startswith("|---") or "Keyword" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 6:
            continue
        item_status = cells[5] or "Pending"
        status_counts[item_status] += 1

        if status_filter and status_filter != "all" and item_status.lower() != status_filter:
            continue
        if search_lower:
            combined = f"{cells[0]} {cells[1]} {cells[2]}".lower()
            if search_lower not in combined:
                continue
        rows.append(
            {
                "keyword": cells[0],
                "cluster": cells[1],
                "source": cells[2],
                "target_blog": cells[3],
                "priority": cells[4],
                "status": item_status,
            }
        )

    return {
        "ok": True,
        "domain": domain,
        "total": sum(status_counts.values()),
        "status_counts": dict(status_counts),
        "filtered_count": len(rows),
        "keywords": rows[:250],
    }


def _fetch_supabase_articles(domain: str = "recetadolce", limit: int = 40) -> dict[str, Any]:
    domain = re.sub(r"[^a-zA-Z0-9_\-]", "", domain) or "recetadolce"
    domain_file = RANKSTEIN_ROOT / "data" / "domains" / domain / "domain.json"
    if not domain_file.exists():
        return {"ok": False, "error": f"Domain {domain} not found", "articles": []}

    try:
        domain_cfg = json.loads(domain_file.read_text(encoding="utf-8"))
        supabase_url = domain_cfg.get("supabase_url", "").rstrip("/")
        key_env = domain_cfg.get("supabase_key_env", "")
        key = _rankstein_setting(key_env)
        if not key or not supabase_url:
            return {
                "ok": False,
                "error": "Missing Supabase URL or credentials",
                "articles": [],
            }

        parsed_url = urlsplit(supabase_url)
        if (
            parsed_url.scheme != "https"
            or not parsed_url.hostname
            or not parsed_url.hostname.endswith(".supabase.co")
        ):
            return {"ok": False, "error": "Invalid configured Supabase origin", "articles": []}
        req = urllib.request.Request(  # noqa: S310 - validated Supabase HTTPS origin
            f"{supabase_url}/rest/v1/posts?select=id,title,slug,created_at,hero_image,pinterest_pin_id,category,chef_tip,excerpt,recipe_schema&order=created_at.desc&limit={max(1, min(limit, 100))}",
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 - validated Supabase origin
            data = json.loads(resp.read().decode("utf-8", errors="replace"))

        articles = []
        for p in data:
            schema = p.get("recipe_schema")
            if isinstance(schema, str):
                try:
                    schema = json.loads(schema)
                except Exception:
                    schema = {}
            articles.append(
                {
                    "id": p.get("id"),
                    "title": p.get("title", ""),
                    "slug": p.get("slug", ""),
                    "created_at": p.get("created_at", ""),
                    "hero_image": p.get("hero_image", ""),
                    "pinterest_pin_id": p.get("pinterest_pin_id", ""),
                    "category": p.get("category", ""),
                    "chef_tip": p.get("chef_tip", ""),
                    "excerpt": p.get("excerpt", ""),
                    "recipe_schema": schema if isinstance(schema, dict) else {},
                }
            )
        return {
            "ok": True,
            "domain": domain,
            "count": len(articles),
            "articles": articles,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "articles": []}


def _requeue_dlq_jobs() -> dict[str, Any]:
    db_path = RANKSTEIN_ROOT / "data" / "queue" / "jobs.db"
    if not db_path.exists():
        return {"ok": False, "error": "jobs.db does not exist", "requeued": 0}
    try:
        from pinterest_automation.job_queue import JobQueue

        queue = JobQueue(db_file=db_path)
        result = queue.requeue_transient_dlq()
        normalization = queue.normalize_board_names_in_storage()
        return {"ok": True, **result, "normalization": normalization}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "requeued": 0}


def _trigger_trend_refresh(domain: str = "recetadolce") -> dict[str, Any]:
    _validate_domain(domain)
    cmd = [_rankstein_python(), "rankstein.py", "trends", "--domain", domain, "--limit", "10"]
    proc = _start_background("trends", cmd)
    return {"ok": True, "pid": proc.pid, "message": f"Trend refresh started for {domain}"}


def _get_board_mappings() -> dict[str, Any]:
    return {
        "canonical_boards": {
            "recetadolce": ["Fresas", "Chocolate"],
            "recetagenial": [
                "Aperitivos",
                "Arroces",
                "Carnes",
                "Chocolate",
                "ENSALADES",
                "Pescados",
            ],
        },
        "known_aliases": [
            {
                "from": "Postres y Dulces",
                "to": "Chocolate",
                "reason": "Legacy board consolidation",
            },
            {
                "from": "Arroces y Paellas",
                "to": "Arroces",
                "reason": "Exact board match",
            },
            {
                "from": "Aperitivos y Tapas",
                "to": "Aperitivos",
                "reason": "Standard tapas taxonomy",
            },
            {
                "from": "Ensaladas y Saludable",
                "to": "ENSALADES",
                "reason": "Canonical casing on Pinterest",
            },
            {
                "from": "Carnes y Tradición",
                "to": "Carnes",
                "reason": "Standard meat board",
            },
            {
                "from": "Recetas Españolas",
                "to": "Aperitivos",
                "reason": "Fallback redirection",
            },
            {"from": "recetas", "to": "Aperitivos", "reason": "Obsolete generic board"},
        ],
        "accounts": [
            {
                "handle": "rida",
                "boards": [
                    "Chocolate",
                    "Fresas",
                    "Aperitivos",
                    "Arroces",
                    "Carnes",
                    "ENSALADES",
                    "Pescados",
                ],
                "role": "Primary Authority Publisher",
            },
            {
                "handle": "media",
                "boards": ["Chocolate", "Aperitivos", "Carnes", "Pescados"],
                "role": "Secondary Syndication Publisher",
            },
        ],
    }


def _latest_run_log(text: str, limit: int = 12000) -> str:
    """Return the newest dashboard run without discarding the history on disk."""

    matches = list(RUN_START_PATTERN.finditer(text))
    latest = text[matches[-1].start() :] if matches else text
    return latest[-limit:]


def _read_text_tail(path: Path, max_bytes: int = 64 * 1024) -> str:
    """Read only the useful tail of an append-only dashboard log."""

    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - max_bytes), os.SEEK_SET)
        return stream.read().decode("utf-8", errors="replace")


def _control_payload() -> dict[str, Any]:
    processes = _load_processes()
    process_status = _process_status(processes)
    rankstein_status: dict[str, Any] = _queue_counts()

    domain_reports: list[dict[str, Any]] = []
    domains_dir = RANKSTEIN_ROOT / "data" / "domains"
    if domains_dir.exists():
        for domain_file in sorted(domains_dir.glob("*/domain.json")):
            try:
                data = json.loads(domain_file.read_text(encoding="utf-8"))
                domain_reports.append(
                    {
                        "handle": data.get("handle") or domain_file.parent.name,
                        "domain": data.get("domain") or data.get("public_domain") or "",
                        "niche": data.get("niche") or "",
                        "status": data.get("status") or "manifest",
                        "cred_ready": bool(data.get("pinterest_email") and data.get("pinterest_password")),
                    }
                )
            except Exception:
                domain_reports.append(
                    {
                        "handle": domain_file.parent.name,
                        "domain": "",
                        "niche": "",
                        "status": "error",
                    }
                )

    return {
        "operator": {"alive": True, "port": 7000},
        "rankstein": {
            "root": str(RANKSTEIN_ROOT),
            "exists": RANKSTEIN_ROOT.exists(),
            "processes": process_status,
            "actions": _action_snapshots(process_status),
            "queue": rankstein_status,
            "domains": domain_reports,
        },
        "agentmemory": _http_health("http://127.0.0.1:3111/agentmemory/health"),
        "updated_at": int(time.time()),
    }


def _cached_status_payload() -> dict[str, Any]:
    """Return immediately while one daemon thread refreshes the live snapshot.

    Starlette runs this synchronous route in a worker thread.  A slow Windows
    filesystem/import scheduling interval can therefore outlive the request
    timeout.  Waiting for ``STATUS_CACHE_LOCK`` here would make every poll pile
    up behind that abandoned request.  Serve the last good (or a well-shaped
    warming) snapshot instead and let exactly one background refresh continue.
    """

    now = time.monotonic()
    cached = _STATUS_CACHE
    if cached and now - cached[0] < STATUS_CACHE_TTL_SECONDS:
        return _live_runtime_status(cached[1])

    _schedule_status_refresh()
    latest = _STATUS_CACHE
    if latest:
        if time.monotonic() - latest[0] < STATUS_CACHE_TTL_SECONDS:
            return _live_runtime_status(latest[1])
        response = dict(latest[1])
        response["status_refresh"] = {
            "state": "refreshing" if STATUS_CACHE_LOCK.locked() else "stale",
            "stale": True,
        }
        return _live_runtime_status(response)
    return _live_runtime_status(_warming_status_payload())


def _live_runtime_status(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep process and batch state live while expensive artifact scans refresh."""
    import copy

    response = dict(payload)
    processes = _process_status(_load_processes())
    actions = _action_snapshots(processes)
    batch = _latest_production_batch()
    production = actions.get("production") or {}
    if batch and not production.get("alive"):
        command = (processes.get("production") or {}).get("command") or []
        if batch.get("batch_id") in command and batch.get("state") in {"running", "waiting"}:
            batch = copy.deepcopy(batch)
            state = "stopped" if (processes.get("production") or {}).get("stop_requested") else "interrupted"
            batch["state"] = state
            for domain in batch.get("domains", {}).values():
                if domain.get("state") in {"running", "waiting"}:
                    domain["state"] = state
                    domain["running_keywords"] = []
                for article in domain.get("articles", []):
                    if article.get("state") == "running":
                        article["state"] = "interrupted"
    pipeline = payload.get("pipeline")
    is_warming = payload.get("status_refresh", {}).get("state") == "warming"
    if pipeline and not is_warming:
        pipeline = dict(pipeline)
        _attach_live_research_lanes(
            pipeline,
            production_batch=batch,
            production_action=production,
        )
        response["pipeline"] = pipeline
    if pipeline and not production.get("alive"):
        pipeline = dict(pipeline)
        ongoing = pipeline.get("ongoing_campaigns") or []
        removed = [
            item
            for item in ongoing
            if (
                str(item.get("id") or "").startswith("research-")
                or (batch and item.get("batch_id") == batch.get("batch_id"))
            )
            and not int((item.get("queue") or {}).get("active") or 0)
            and not int((item.get("queue") or {}).get("held") or 0)
        ]
        pipeline["ongoing_campaigns"] = [item for item in ongoing if item not in removed]
        pipeline["ongoing_total"] = max(0, int(pipeline.get("ongoing_total") or 0) - len(removed))
        summary = dict(pipeline.get("summary") or {})
        summary["ongoing"] = pipeline["ongoing_total"]
        summary["active"] = max(
            0,
            int(summary.get("active") or 0) - sum(item.get("overall_state") == "active" for item in removed),
        )
        summary["waiting"] = max(
            0,
            int(summary.get("waiting") or 0)
            - sum(item.get("overall_state") == "waiting" for item in removed),
        )
        pipeline["summary"] = summary
        response["pipeline"] = pipeline
    response.update(
        {
            "processes": processes,
            "actions": actions,
            "production_batch": _production_batch_presentation(batch),
            "runtime_updated_at": int(time.time()),
        }
    )
    return response


def _schedule_status_refresh() -> bool:
    """Start one non-blocking cache refresh and report whether it was started."""

    if not STATUS_CACHE_LOCK.acquire(blocking=False):
        return False
    try:
        thread = threading.Thread(
            target=_refresh_status_cache,
            name="rankstein-status-refresh",
            daemon=True,
        )
        thread.start()
    except Exception:
        STATUS_CACHE_LOCK.release()
        return False
    return True


def _refresh_status_cache() -> None:
    """Build the expensive snapshot without holding an HTTP request open."""

    global _STATUS_CACHE

    try:
        payload = _status_payload()
        payload["status_refresh"] = {"state": "ready", "stale": False}
        _STATUS_CACHE = (time.monotonic(), payload)
    except Exception:
        # Keep serving the last good/warming snapshot.  The next stale poll can
        # schedule a fresh attempt without leaking a daemon-thread traceback.
        return
    finally:
        STATUS_CACHE_LOCK.release()


def _warming_status_payload() -> dict[str, Any]:
    """Return the stable API shape before the first full snapshot is ready."""

    return {
        "rankstein_root": str(RANKSTEIN_ROOT),
        "rankstein_exists": None,
        "agentmemory": {"ok": None, "state": "warming"},
        "domains": [],
        "keyword_counts": {},
        "queue": {},
        "mcp": {},
        "processes": {},
        "actions": {},
        "production_batch": None,
        "pipeline": {
            "campaigns": [],
            "ongoing_campaigns": [],
            "history_campaigns": [],
            "summary": {"ongoing": 0, "active": 0},
            "total_campaigns": 0,
            "ongoing_total": 0,
        },
        "codex": {},
        "article_provider": {"provider": "checking"},
        "opencode": {},
        "status_refresh": {"state": "warming", "stale": False},
        "updated_at": int(time.time()),
    }


def _status_payload() -> dict[str, Any]:
    processes = _load_processes()
    process_status = _process_status(processes)
    actions = _action_snapshots(process_status)
    production_batch = _production_batch_presentation(_latest_production_batch())
    pipeline = build_pipeline_payload(RANKSTEIN_ROOT, live_only=True, history_limit=12)
    _attach_live_research_lanes(
        pipeline,
        production_batch=production_batch,
        production_action=actions.get("production") or {},
    )
    return {
        "rankstein_root": str(RANKSTEIN_ROOT),
        "rankstein_exists": RANKSTEIN_ROOT.exists(),
        "agentmemory": _http_health("http://127.0.0.1:3111/agentmemory/health"),
        "domains": _domains(),
        "keyword_counts": _keyword_counts(),
        "queue": _queue_counts(),
        "mcp": _mcp_status(),
        "processes": process_status,
        "actions": actions,
        "production_batch": production_batch,
        "pipeline": pipeline,
        "codex": {
            "home": str(CODEX_HOME),
            "auth_present": (CODEX_HOME / "auth.json").exists(),
            "config_present": (CODEX_HOME / "config.toml").exists(),
            "project_trusted": _codex_project_trusted(),
        },
        "links": {
            "operator_ui": "http://127.0.0.1:7000/operator",
            "hermes_codex": "http://127.0.0.1:8642",
            "agentmemory": "http://127.0.0.1:3111",
            "agentmemory_viewer": "http://127.0.0.1:3113",
            "recetadolce": "https://recetadolce.com",
            "recetagenial": "https://recetagenial.com",
            "supabase_dolce": "https://xjvmnmfczvwkjiasirsl.supabase.co",
            "supabase_genial": "https://hokcljsrrnjxzgdhjice.supabase.co",
            "architecture_doc": "/api/rankstein/architecture",
        },
        "article_provider": _article_provider_status(),
        "opencode": _opencode_status(),
        "runtime": _runtime_snapshot(),
        "updated_at": int(time.time()),
    }


def _attach_live_research_lanes(
    pipeline: dict[str, Any],
    *,
    production_batch: dict[str, Any] | None,
    production_action: dict[str, Any],
) -> None:
    """Show per-domain keyword research before a concrete keyword is reserved."""

    # Artifact snapshots can outlive keyword reservation. Replace their synthetic
    # research rows with the current batch state on every live status response.
    previous_lanes = {
        str(item.get("id")): item
        for collection in ("campaigns", "ongoing_campaigns", "research_lanes")
        for item in pipeline.get(collection) or []
        if str(item.get("id") or "").startswith("research-")
    }
    if previous_lanes:
        for collection in ("campaigns", "ongoing_campaigns", "research_lanes"):
            pipeline[collection] = [
                item
                for item in pipeline.get(collection) or []
                if str(item.get("id") or "") not in previous_lanes
            ]
        for count in ("total_campaigns", "ongoing_total"):
            pipeline[count] = max(0, int(pipeline.get(count) or 0) - len(previous_lanes))
        summary = dict(pipeline.get("summary") or {})
        summary["ongoing"] = max(0, int(summary.get("ongoing") or 0) - len(previous_lanes))
        summary["active"] = max(
            0,
            int(summary.get("active") or 0)
            - sum(item.get("overall_state") == "active" for item in previous_lanes.values()),
        )
        summary["waiting"] = max(
            0,
            int(summary.get("waiting") or 0)
            - sum(item.get("overall_state") == "waiting" for item in previous_lanes.values()),
        )
        summary["attention"] = max(
            0,
            int(summary.get("attention") or 0)
            - sum(item.get("overall_state") == "attention" for item in previous_lanes.values()),
        )
        pipeline["summary"] = summary
    if not production_batch or not production_action.get("alive"):
        return
    stage = str(production_action.get("stage") or "").casefold()
    domains = production_batch.get("domains") or {}
    has_explicit_research = any(
        str(domain.get("detail") or "").startswith("research_") for domain in domains.values()
    )
    if not has_explicit_research and not any(marker in stage for marker in ("research", "candidate")):
        return
    lanes: list[dict[str, Any]] = []
    sources = [
        "Pinterest Trends/Search (candidate origin)",
        "Google News (exact-phrase validation)",
        "Google Trends (exact-phrase validation)",
        "Suggestions (exact-phrase validation)",
    ]
    now = time.time()
    for handle, domain in sorted(domains.items()):
        target = int(domain.get("target") or 0)
        verified = int(domain.get("verified") or 0)
        if target and verified >= target:
            continue
        if domain.get("running_keywords"):
            continue
        remaining = max(0, target - verified)
        waiting = str(domain.get("state") or "").casefold() == "waiting"
        detail = (
            "Pinterest Trends/Search supplies candidates; Google News, Trends, and "
            "Suggestions validate the same exact phrase; waiting for a qualified Pending keyword"
        )
        if waiting:
            detail = str(domain.get("detail") or "Waiting for a fresh qualified Pinterest keyword")
        activity = _research_activity(domain, default_active=not waiting)
        lane_state = activity["state"]
        stage_state = {"active": "running", "attention": "warning", "waiting": "waiting"}[lane_state]
        stages = []
        for key, label, phase, service in STAGE_DEFINITIONS:
            is_research = key == "keyword_search"
            stages.append(
                {
                    "key": key,
                    "label": label,
                    "phase": phase,
                    "service": service,
                    "state": stage_state if is_research else "pending",
                    "detail": detail if is_research else "Waiting for keyword selection",
                    "updated_at": production_action.get("updated_at") if is_research else None,
                    "metrics": {"sources": sources, **activity["metrics"]} if is_research else {},
                }
            )
        lanes.append(
            {
                "id": f"research-{handle}",
                "domain_handle": handle,
                "keyword": "Discovering the next domain-aware keyword",
                "title": f"{handle} live keyword research",
                "slug": f"research-{handle}",
                "article_url": "",
                "pin_url": "",
                "latest_campaign_pin_url": "",
                "campaign_pins": [],
                "campaign_job_ids": [],
                "historical_queue": {},
                "other_jobs": {},
                "roadmap_status": "Researching",
                "run_status": "researching",
                "updated_at": float(production_action.get("updated_at") or now),
                "stages": stages,
                "queue": {},
                "remaster": {},
                "previews": {},
                "research": {
                    "sources": sources,
                    "qualified_candidates": 0,
                    "remaining_articles": remaining,
                },
                "in_current_batch": True,
                "batch_id": production_batch.get("batch_id") or "",
                "batch_state": "researching" if lane_state == "active" else lane_state,
                "overall_state": lane_state,
                "is_ongoing": True,
                "current_stage": "keyword_search",
                "current_label": activity["label"],
                "current_detail": detail,
                "progress": 5,
                "age_seconds": int(production_action.get("elapsed_seconds") or 0),
            }
        )

    if not lanes:
        return
    campaigns = list(pipeline.get("campaigns") or [])
    pipeline["campaigns"] = lanes + campaigns
    ongoing = list(pipeline.get("ongoing_campaigns") or [])
    pipeline["ongoing_campaigns"] = lanes + ongoing
    pipeline["research_lanes"] = lanes
    pipeline["total_campaigns"] = int(pipeline.get("total_campaigns") or 0) + len(lanes)
    pipeline["ongoing_total"] = int(pipeline.get("ongoing_total") or 0) + len(lanes)
    summary = dict(pipeline.get("summary") or {})
    summary["ongoing"] = int(summary.get("ongoing") or 0) + len(lanes)
    summary["active"] = int(summary.get("active") or 0) + sum(
        lane["overall_state"] == "active" for lane in lanes
    )
    summary["waiting"] = int(summary.get("waiting") or 0) + sum(
        lane["overall_state"] == "waiting" for lane in lanes
    )
    summary["attention"] = int(summary.get("attention") or 0) + sum(
        lane["overall_state"] == "attention" for lane in lanes
    )
    pipeline["summary"] = summary


def _research_activity(domain: dict[str, Any], *, default_active: bool = False) -> dict[str, Any]:
    """Interpret existing tracker reasons without crediting a fictitious article run."""

    reason = str(domain.get("detail") or "")
    prefix = reason.split(" ", 1)[0]
    fields = dict(re.findall(r"\b([a-z_]+)=([^\s]+)", reason))
    stage = fields.get("stage")
    label = {
        "pinterest_collection": "Pinterest candidate collection",
        "exact_validation": "Exact Pinterest-phrase demand validation",
    }.get(stage, "Keyword search")
    metrics = {
        key: fields[key]
        for key in (
            "stage",
            "deadline_seconds",
            "deadline_at",
            "elapsed_seconds",
            "observed_count",
            "eligible_count",
        )
        if key in fields
    }
    if prefix == "research_in_progress":
        state = "active"
    elif prefix in {"research_timeout", "research_failed", "research_cancelled"}:
        state = "attention"
        if prefix == "research_timeout":
            short_label = "Pinterest collection" if stage == "pinterest_collection" else "Exact validation"
            label = f"{short_label} reached its {fields.get('deadline_seconds', '?')}s deadline"
        else:
            label += " cancelled" if prefix == "research_cancelled" else " failed"
    else:
        state = "active" if default_active else "waiting"
        label = label if default_active else "Waiting for qualified keywords"
    return {"state": state, "label": label, "metrics": metrics}


def _production_batch_presentation(batch: dict[str, Any] | None) -> dict[str, Any] | None:
    """Derive truthful display counts without rewriting legacy tracker counters."""

    if batch is None:
        return None
    totals = {
        "produced": 0,
        "awaiting_verification": 0,
        "failed_attempts": 0,
        "interrupted_attempts": 0,
    }
    domains = {}
    for handle, domain in (batch.get("domains") or {}).items():
        latest = {}
        counts = dict.fromkeys(totals, 0)
        for article in domain.get("articles") or []:
            state = str(article.get("state") or "").replace("_", " ").strip().casefold()
            counts["failed_attempts"] += state == "failed"
            counts["interrupted_attempts"] += state == "interrupted"
            keyword = str(article.get("keyword") or "").strip()
            if keyword:
                latest[keyword] = state
        counts["produced"] = sum(
            state in {"verified", "live", "needs verification"} for state in latest.values()
        )
        counts["awaiting_verification"] = sum(state == "needs verification" for state in latest.values())
        domains[handle] = {**domain, "presentation_counts": counts}
        for key, count in counts.items():
            totals[key] += count
    return {**batch, "domains": domains, "presentation_counts": totals}


def _latest_production_batch() -> dict[str, Any] | None:
    report_dir = RANKSTEIN_ROOT / "data" / "reports" / "production_batches"
    if not report_dir.exists():
        return None
    reports = sorted(
        [*report_dir.glob("production-*.json"), *report_dir.glob("production-*.tmp")],
        key=lambda path: (path.stem, path.suffix == ".tmp"),
        reverse=True,
    )
    if not reports:
        return None
    latest_stem = reports[0].stem
    for path in reports:
        if path.stem != latest_stem:
            continue
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(report, dict):
                report["report_path"] = str(path)
                return report
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _rankstein_python() -> str:
    candidates = [
        RANKSTEIN_ROOT / ".venv" / "Scripts" / "python.exe",
        RANKSTEIN_ROOT / "venv" / "Scripts" / "python.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return "python"


def _resolve_rankstein_preview(requested_path: str) -> Path:
    """Resolve an image path inside RankStein's preview-safe asset roots."""

    raw = str(requested_path or "").strip()
    if not raw:
        raise ValueError("Preview path is required")
    root = RANKSTEIN_ROOT.resolve()
    candidate = Path(raw)
    candidate = candidate if candidate.is_absolute() else root / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ValueError("Preview asset was not found") from exc
    allowed_roots = (
        root / "data" / "media",
        root / "data" / "domains",
        root / "data" / "reports",
        root / "data" / "sessions",
        root / "data" / "logs",
        root / "data",
        root / "nanobanana-output",
    )
    if not any(resolved.is_relative_to(path.resolve()) for path in allowed_roots):
        raise ValueError("Preview asset is outside the allowed RankStein media roots")
    if not resolved.is_file() or resolved.suffix.lower() not in PREVIEW_EXTENSIONS:
        raise ValueError("Preview asset must be a supported image file")
    return resolved


def _start_background(mode: str, command: list[str]) -> subprocess.Popen:
    if not RANKSTEIN_ROOT.exists():
        raise HTTPException(500, "RankStein root not found")
    if mode in {"production", "full", "launch"}:
        from rankstein.domain import DomainRegistry
        from rankstein.production_safety import campaign_admission

        registry = DomainRegistry(RANKSTEIN_ROOT)
        selected = registry.all()
        if "--domain" in command:
            selected = [registry.get(command[command.index("--domain") + 1])]
        count = int(command[command.index("--limit") + 1]) if "--limit" in command else 1
        admission = campaign_admission(selected, campaigns_per_domain=count)
        if not admission["ok"]:
            raise HTTPException(409, {"reason": "production_admission_blocked", **admission})
    with PROCESS_LOCK:
        from pinterest_automation.runtime_state import supervisor_status

        if mode == "supervisor" and supervisor_status()["running"]:
            raise HTTPException(409, "Pinterest supervisor is already running")
        if mode in {"production", "full", "launch"}:
            import psutil

            for process in psutil.process_iter(["cmdline"]):
                args = process.info.get("cmdline") or []
                if any(Path(arg).name.lower() == "turbo_articles.py" for arg in args):
                    raise HTTPException(409, "Article workers are already running; inspect live workflows")
        processes = _load_processes()
        existing = processes.get(mode) or {}
        if mode in {"production", "full", "launch"}:
            for name in {"production", "full", "launch"}:
                info = processes.get(name) or {}
                if _pid_alive(info.get("pid"), info.get("command"), info.get("started_at")):
                    raise HTTPException(409, "A production launcher or batch is already running")
        if _pid_alive(existing.get("pid"), existing.get("command"), existing.get("started_at")):
            raise HTTPException(409, f"{ACTION_LABELS.get(mode, mode)} is already running")

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIR / f"{mode}.log"
        log = open(log_path, "a", encoding="utf-8", errors="replace")
        log.write(f"\n\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] START {' '.join(command)}\n")
        log.flush()
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.Popen(
            command,
            cwd=str(RANKSTEIN_ROOT),
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            env=_rankstein_subprocess_env(),
        )
        processes[mode] = {
            "pid": proc.pid,
            "command": command,
            "started_at": int(time.time()),
            "log": str(log_path),
        }
        _save_processes(processes)

    threading.Thread(
        target=_record_process_exit,
        args=(mode, proc, log),
        name=f"rankstein-{mode}-watcher",
        daemon=True,
    ).start()
    return proc


def _rankstein_subprocess_env() -> dict[str, str]:
    """Force dashboard-launched Python actions to emit Unicode safely on Windows."""

    from rankstein.runtime_env import clean_python_env

    env = clean_python_env()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["RANKSTEIN_SKIP_SUPERVISOR_ARTICLES"] = "1"
    return env


def _validate_domain(domain: str) -> None:
    if domain not in {item["handle"] for item in _domains()}:
        raise HTTPException(400, "Unknown configured domain")


def _apply_domain_scope(command: list[str], mode: str, domain: str) -> None:
    if not domain:
        return
    _validate_domain(domain)
    if mode == "production":
        command.remove("--all-domains")
        command.extend(["--domain", domain])
    elif mode in {"full", "launch", "audit"}:
        command.extend(["--domain", domain])


def _get_accounts_file_path() -> Path:
    from pinterest_automation.config import DATA_DIR

    return DATA_DIR / "pinterest_accounts.json"


def _load_accounts_file_data() -> dict[str, Any]:
    path = _get_accounts_file_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    from pinterest_automation.config import get_config

    cfg = get_config()
    raw_map = os.environ.get("PINTEREST_DOMAIN_ACCOUNT_MAP", "")
    domain_map: dict[str, list[str]] = {}
    if raw_map:
        try:
            domain_map = json.loads(raw_map)
        except Exception:
            domain_map = {}

    accounts = []
    for h, acc in cfg.accounts.items():
        connected = [d for d, accs in domain_map.items() if isinstance(accs, list) and h in accs]
        accounts.append(
            {
                "handle": h,
                "email": acc.email,
                "session_name": acc.session_name,
                "browser": acc.browser or "chromium",
                "connected_domains": connected,
            }
        )
    initial = {"accounts": accounts, "domain_account_map": domain_map}
    try:
        _save_accounts_file_data(initial)
    except Exception:
        pass
    return initial


def _save_accounts_file_data(data: dict[str, Any]) -> None:
    path = _get_accounts_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temp.replace(path)


def _get_account_connected_domains(handle: str) -> list[str]:
    data = _load_accounts_file_data()
    handle_lower = handle.strip().lower()
    acc_list = data.get("accounts", [])
    if isinstance(acc_list, dict):
        acc_list = list(acc_list.values())
    for acc in acc_list:
        if isinstance(acc, dict) and str(acc.get("handle") or acc.get("name") or "").lower() == handle_lower:
            domains = acc.get("connected_domains", [])
            if isinstance(domains, list):
                return sorted(set(domains))
    domain_map = data.get("domain_account_map", {})
    return sorted(
        d
        for d, accs in domain_map.items()
        if isinstance(accs, list) and handle_lower in [str(a).lower() for a in accs]
    )


def _get_accounts_management_payload() -> dict[str, Any]:
    from pinterest_automation.config import SESSION_DIR, get_config
    from rankstein.domain import DomainRegistry

    registry = DomainRegistry(RANKSTEIN_ROOT)
    domains = [
        {"handle": d.handle, "display_name": d.display_name, "domain": d.domain}
        for d in registry.all()
    ]

    data = _load_accounts_file_data()
    cfg = get_config()

    file_accounts = {
        str(a.get("handle") or a.get("name") or "").lower(): a
        for a in data.get("accounts", [])
        if isinstance(a, dict)
    }

    all_handles = sorted(set(cfg.accounts.keys()) | set(file_accounts.keys()))
    domain_map = data.get("domain_account_map", {})

    accounts = []
    for handle in all_handles:
        acc_obj = cfg.accounts.get(handle)
        file_acc = file_accounts.get(handle.lower(), {})

        email = (acc_obj.email if acc_obj else "") or file_acc.get("email", "")
        masked_email = ""
        if email and "@" in email:
            parts = email.split("@")
            masked_email = f"{parts[0][:2]}***@{parts[1]}"
        elif email:
            masked_email = "***"

        session_name = (acc_obj.session_name if acc_obj else None) or file_acc.get("session_name") or handle
        profile = SESSION_DIR / session_name
        browser = (acc_obj.browser if acc_obj else None) or file_acc.get("browser") or "chromium"

        connected_domains = file_acc.get("connected_domains") or [
            d for d, accs in domain_map.items() if handle in accs
        ]

        has_password = bool((acc_obj and acc_obj.password) or file_acc.get("password"))

        accounts.append(
            {
                "handle": handle,
                "email": masked_email,
                "has_password": has_password,
                "session_name": session_name,
                "browser": browser,
                "profile_present": profile.is_dir(),
                "credentials_configured": bool(email and has_password),
                "connected_domains": sorted(set(connected_domains)),
            }
        )

    return {
        "ok": True,
        "accounts": accounts,
        "domains": domains,
        "domain_account_map": domain_map,
    }


def _save_account(body: dict[str, Any]) -> dict[str, Any]:
    import re

    handle = str(body.get("handle") or "").strip().lower()
    if not handle:
        raise HTTPException(400, "Account handle is required")
    handle = re.sub(r"[^a-z0-9_\-]", "", handle)
    if not handle:
        raise HTTPException(400, "Invalid account handle: use lowercase letters, numbers, hyphens or underscores")

    email = str(body.get("email") or "").strip()
    password = str(body.get("password") or "").strip()
    session_name = str(body.get("session_name") or handle).strip()
    browser = str(body.get("browser") or "chromium").strip().lower()
    if browser not in {"chromium", "firefox"}:
        browser = "chromium"
    connected_domains = [str(d).strip().lower() for d in body.get("connected_domains", []) if str(d).strip()]

    data = _load_accounts_file_data()
    acc_list = data.get("accounts", [])
    if isinstance(acc_list, dict):
        acc_list = list(acc_list.values())

    found = False
    for acc in acc_list:
        if str(acc.get("handle") or acc.get("name") or "").lower() == handle:
            if email:
                acc["email"] = email
            if password:
                acc["password"] = password
            acc["session_name"] = session_name or acc.get("session_name", handle)
            acc["browser"] = browser
            acc["connected_domains"] = connected_domains
            found = True
            break

    if not found:
        new_entry = {
            "handle": handle,
            "email": email,
            "session_name": session_name or handle,
            "browser": browser,
            "connected_domains": connected_domains,
        }
        if password:
            new_entry["password"] = password
        acc_list.append(new_entry)

    domain_map = data.get("domain_account_map", {})
    for d, accs in domain_map.items():
        if isinstance(accs, list) and handle in accs:
            accs.remove(handle)
    for d in connected_domains:
        if d not in domain_map:
            domain_map[d] = []
        if handle not in domain_map[d]:
            domain_map[d].append(handle)

    data["accounts"] = acc_list
    data["domain_account_map"] = domain_map
    _save_accounts_file_data(data)

    from pinterest_automation.config import get_config

    get_config()._load_accounts_file()

    return {"ok": True, "message": f"Pinterest account '{handle}' saved successfully."}


def _connect_account_blog(body: dict[str, Any]) -> dict[str, Any]:
    account_handle = str(body.get("account_handle") or "").strip().lower()
    domain_handle = str(body.get("domain_handle") or "").strip().lower()
    connected = bool(body.get("connected", True))

    if not account_handle or not domain_handle:
        raise HTTPException(400, "Both account_handle and domain_handle are required")

    data = _load_accounts_file_data()
    acc_list = data.get("accounts", [])
    if isinstance(acc_list, dict):
        acc_list = list(acc_list.values())

    for acc in acc_list:
        if str(acc.get("handle") or acc.get("name") or "").lower() == account_handle:
            current_domains = set(acc.get("connected_domains", []))
            if connected:
                current_domains.add(domain_handle)
            else:
                current_domains.discard(domain_handle)
            acc["connected_domains"] = sorted(current_domains)
            break

    domain_map = data.get("domain_account_map", {})
    if domain_handle not in domain_map:
        domain_map[domain_handle] = []
    if connected:
        if account_handle not in domain_map[domain_handle]:
            domain_map[domain_handle].append(account_handle)
    else:
        if account_handle in domain_map[domain_handle]:
            domain_map[domain_handle].remove(account_handle)

    data["accounts"] = acc_list
    data["domain_account_map"] = domain_map
    _save_accounts_file_data(data)

    from pinterest_automation.config import get_config

    get_config()._load_accounts_file()

    action_label = "connected to" if connected else "disconnected from"
    return {
        "ok": True,
        "message": f"Account '{account_handle}' {action_label} blog '{domain_handle}'.",
        "domain_account_map": domain_map,
    }


def _delete_account(body: dict[str, Any]) -> dict[str, Any]:
    handle = str(body.get("handle") or "").strip().lower()
    if not handle:
        raise HTTPException(400, "Account handle is required")

    data = _load_accounts_file_data()
    acc_list = [
        acc
        for acc in data.get("accounts", [])
        if str(acc.get("handle") or acc.get("name") or "").lower() != handle
    ]
    domain_map = data.get("domain_account_map", {})
    for d, accs in domain_map.items():
        if isinstance(accs, list) and handle in accs:
            accs.remove(handle)

    data["accounts"] = acc_list
    data["domain_account_map"] = domain_map
    _save_accounts_file_data(data)

    from pinterest_automation.config import get_config

    cfg = get_config()
    cfg.accounts.pop(handle, None)
    cfg._load_accounts_file()

    return {"ok": True, "message": f"Pinterest account '{handle}' deleted."}


def _runtime_snapshot() -> dict[str, Any]:
    import shutil

    import psutil

    from pinterest_automation.config import SESSION_DIR, get_config
    from pinterest_automation.runtime_state import supervisor_status
    from rankstein.domain import DomainRegistry
    from rankstein.suite_controller import SERVICES, get_service_status

    config = get_config()
    config._load_accounts_file()
    accounts = []
    for handle, account in config.accounts.items():
        profile = SESSION_DIR / account.session_name
        accounts.append(
            {
                "handle": handle,
                "browser": account.browser,
                "credentials_configured": bool(account.valid),
                "profile_present": profile.is_dir(),
                "session_state": "profile present; login unverified"
                if profile.is_dir()
                else "profile missing",
                "connected_domains": _get_account_connected_domains(handle),
            }
        )
    services = get_service_status()
    ports = {spec.name: spec.port for spec in SERVICES}
    memory = psutil.virtual_memory()
    domains = [
        {"handle": d.handle, "display_name": d.display_name, "domain": d.domain}
        for d in DomainRegistry(RANKSTEIN_ROOT).all()
    ]
    return {
        "supervisor": supervisor_status(),
        "accounts": accounts,
        "domains": domains,
        "services": [
            {
                "name": name,
                "port": ports[name],
                "healthy": row["healthy"],
                "port_open": row["port_open"],
                "optional": row["optional"],
            }
            for name, row in services.items()
        ],
        "resources": {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": memory.percent,
            "memory_available_gb": round(memory.available / 1024**3, 1),
            "disk_free_gb": round(shutil.disk_usage(RANKSTEIN_ROOT).free / 1024**3, 1),
        },
        "headless": True,
        "max_sessions": config.browser.max_sessions,
    }


def _load_processes() -> dict[str, Any]:
    with PROCESS_LOCK:
        try:
            return json.loads(PROCESS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}


def _save_processes(processes: dict[str, Any]) -> None:
    with PROCESS_LOCK:
        PROCESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = PROCESS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(processes, indent=2), encoding="utf-8")
        tmp.replace(PROCESS_FILE)


def _record_process_exit(mode: str, proc: subprocess.Popen, log) -> None:
    returncode = proc.wait()
    finished_at = int(time.time())
    try:
        log.flush()
    finally:
        log.close()

    with PROCESS_LOCK:
        processes = _load_processes()
        info = processes.get(mode)
        if info and int(info.get("pid", 0) or 0) == proc.pid:
            info["returncode"] = returncode
            info["finished_at"] = finished_at
            processes[mode] = info
            _save_processes(processes)


def _kill_windows_pid_tree(pid: int) -> bool:
    """Force-stop one exact Windows PID and the descendants rooted beneath it."""

    if pid <= 0:
        return False
    result = subprocess.run(
        ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        text=True,
        timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return result.returncode == 0


def _kill_pid_tree(pid: int) -> bool:
    try:
        if os.name == "nt":
            return _kill_windows_pid_tree(pid)
        os.kill(pid, 9)
        return True
    except Exception:
        return False


def _pid_alive(
    pid: Any,
    expected_command: list[str] | None = None,
    expected_started_at: Any = None,
) -> bool:
    if not pid:
        return False
    try:
        if os.name == "nt":
            identity = _windows_process_identity(int(pid))
            if not identity:
                return False
            executable, created_at = identity
            if expected_command:
                expected_executable = str(expected_command[0])
                if "\\" in expected_executable or "/" in expected_executable:
                    if os.path.normcase(os.path.abspath(executable)) != os.path.normcase(
                        os.path.abspath(expected_executable)
                    ):
                        return False
                elif Path(executable).stem.casefold() != Path(expected_executable).stem.casefold():
                    return False
            if expected_started_at:
                if abs(created_at - int(expected_started_at)) > 8:
                    return False
            return True
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _windows_process_identity(pid: int) -> tuple[str, int] | None:
    """Return executable and creation epoch for PID-reuse-safe tracking."""
    import psutil

    try:
        process = psutil.Process(pid)
        return process.exe(), int(process.create_time())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def _action_snapshots(
    processes: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    processes = processes or {}
    now = int(time.time())
    return {mode: _action_snapshot(mode, processes.get(mode) or {}, now=now) for mode in ACTION_LABELS}


def _process_status(processes: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        name: {
            **info,
            "alive": _pid_alive(
                info.get("pid"),
                info.get("command"),
                info.get("started_at"),
            ),
        }
        for name, info in processes.items()
    }


def _action_snapshot(mode: str, info: dict[str, Any], *, now: int | None = None) -> dict[str, Any]:
    now = int(time.time()) if now is None else now
    started_at = int(info.get("started_at", 0) or 0)
    finished_at = int(info.get("finished_at", 0) or 0)
    pid = int(info.get("pid", 0) or 0)
    alive = (
        bool(info.get("alive"))
        if "alive" in info
        else (_pid_alive(pid, info.get("command"), info.get("started_at")) if pid else False)
    )
    returncode = info.get("returncode")
    stop_requested = bool(info.get("stop_requested"))
    log, log_updated_at = _read_action_log(mode)
    log_lower = log.casefold()
    failed = _log_failed(log_lower)
    succeeded = _log_succeeded(mode, log_lower)

    if not started_at:
        state = "idle"
    elif alive:
        state = "running"
    elif stop_requested:
        state = "stopped"
    elif returncode is not None:
        state = "succeeded" if int(returncode) == 0 else "failed"
    elif failed:
        state = "failed"
    elif succeeded:
        state = "succeeded"
    else:
        state = "stopped"

    progress, stage = _action_progress(mode, log, state)
    end_at = now if alive else (finished_at or log_updated_at or started_at)
    elapsed_seconds = max(0, end_at - started_at) if started_at else 0

    if state == "failed":
        detail = _failure_detail(log) or (
            f"Exited with code {returncode}" if returncode is not None else "Action failed"
        )
    elif state == "succeeded":
        detail = "Completed successfully"
    elif state == "stopped":
        detail = "Stopped before reporting completion"
    elif state == "running":
        detail = (
            f"PID {pid} · live output {max(0, now - log_updated_at)}s ago" if log_updated_at else f"PID {pid}"
        )
    else:
        detail = "Not started in this dashboard session"

    return {
        "mode": mode,
        "label": ACTION_LABELS.get(mode, mode),
        "state": state,
        "stage": stage,
        "detail": detail,
        "progress": progress,
        "indeterminate": state == "running" and mode == "supervisor",
        "alive": alive,
        "pid": pid or None,
        "returncode": returncode,
        "started_at": started_at or None,
        "finished_at": finished_at or None,
        "updated_at": log_updated_at or None,
        "elapsed_seconds": elapsed_seconds,
        "log_available": bool(log),
    }


def _read_action_log(mode: str) -> tuple[str, int]:
    path = LOG_DIR / f"{mode}.log"
    if mode == "supervisor":
        from pinterest_automation.runtime_state import supervisor_status

        maintained = RANKSTEIN_ROOT / "data" / "logs" / "services" / "rankstein_supervisor.log"
        if (
            supervisor_status()["running"]
            and maintained.exists()
            and (not path.exists() or maintained.stat().st_mtime > path.stat().st_mtime)
        ):
            path = maintained
    if not path.exists():
        return "", 0
    try:
        text = _read_text_tail(path)
        return _latest_run_log(text), int(path.stat().st_mtime)
    except OSError:
        return "", 0


def _redact_log(text: str) -> str:
    for name, value in os.environ.items():
        if len(value) >= 12 and any(
            marker in name.upper() for marker in ("SECRET", "PASSWORD", "TOKEN", "API_KEY", "SERVICE_ROLE")
        ):
            text = text.replace(value, "[redacted]")
    return re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9_.\-]+", r"\1[redacted]", text)


def _log_failed(log_lower: str) -> bool:
    return any(
        marker in log_lower
        for marker in (
            "traceback (most recent call last)",
            "modulenotfounderror",
            "unicodeencodeerror",
            '"success": false',
            "fatal:",
        )
    )


def _log_succeeded(mode: str, log_lower: str) -> bool:
    markers = {
        "mcp": ("all mcp infrastructure checks passed",),
        "full": ("rankstein launch brief", "report:"),
        "audit": ('"created_campaigns"', '"launched"'),
        "launch": ("launch report",),
        "remaster": ('"success": true',),
        "normalize-boards": ("active_changed", "dlq_changed"),
        "supervisor": (),
    }
    required = markers.get(mode, ())
    return bool(required) and all(marker in log_lower for marker in required)


def _action_progress(mode: str, log: str, state: str) -> tuple[int, str]:
    if state == "idle":
        return 0, "Idle"
    if state == "succeeded":
        return 100, "Complete"
    if state == "failed":
        return 100, "Failed"
    if state == "stopped":
        return 100, "Stopped"

    progress = 5
    stage = "Starting"
    log_lower = log.casefold()
    latest_position = -1
    for value, label, marker in ACTION_STAGES.get(mode, ()):
        marker_position = log_lower.rfind(marker.casefold())
        if marker_position > latest_position:
            latest_position = marker_position
            progress = value
            stage = label
    return progress, stage


def _failure_detail(log: str) -> str:
    for line in reversed(log.splitlines()):
        clean = line.strip()
        lowered = clean.casefold()
        if clean and any(
            word in lowered for word in ("error", "failed", "traceback", "fatal", "publishing blocked")
        ):
            return clean[:180]
    return ""


def _http_health(url: str) -> dict[str, Any]:
    try:
        request: str | urllib.request.Request = url
        if ":3111" in url:
            # Check fast unauthenticated livez first
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:3111/agentmemory/livez", timeout=1.5
                ) as live_resp:
                    if 200 <= live_resp.status < 300:
                        return {"ok": True, "status": live_resp.status}
            except Exception:
                pass
            secret = os.environ.get("AGENTMEMORY_SECRET", "").strip()
            if not secret:
                user_root = Path(os.environ.get("USERPROFILE") or Path.home())
                secret_path = user_root / ".agentmemory" / "secret"
                try:
                    secret = secret_path.read_text(encoding="utf-8").strip()
                except OSError:
                    secret = ""
            if secret:
                request = urllib.request.Request(  # noqa: S310 - fixed loopback health probe
                    url,
                    headers={"Authorization": f"Bearer {secret}"},
                )
        with urllib.request.urlopen(request, timeout=2) as response:  # noqa: S310 - fixed local probes
            return {"ok": 200 <= response.status < 300, "status": response.status}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


def _domains() -> list[dict[str, str]]:
    domains_dir = RANKSTEIN_ROOT / "data" / "domains"
    out = []
    if not domains_dir.exists():
        return out
    for domain_file in sorted(domains_dir.glob("*/domain.json")):
        try:
            data = json.loads(domain_file.read_text(encoding="utf-8"))
            out.append(
                {
                    "handle": data.get("handle") or domain_file.parent.name,
                    "domain": data.get("domain") or data.get("public_domain") or "",
                    "niche": data.get("niche") or "",
                    "status": data.get("status") or "manifest",
                }
            )
        except Exception:
            out.append(
                {
                    "handle": domain_file.parent.name,
                    "domain": "",
                    "niche": "",
                    "status": "error",
                }
            )
    return out


def _keyword_counts() -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for path in sorted((RANKSTEIN_ROOT / "data" / "domains").glob("*/keywords.md")):
        counter: Counter[str] = Counter()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.startswith("|") or line.startswith("|---") or "Keyword" in line:
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 6:
                counter[cells[5] or "Unknown"] += 1
        counts[path.parent.name] = dict(counter)
    return counts


def _queue_counts() -> dict[str, Any]:
    db_path = RANKSTEIN_ROOT / "data" / "queue" / "jobs.db"
    if not db_path.exists():
        return {"exists": False}
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            by_status = {
                row["status"]: row["n"]
                for row in conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
            }
            dlq = conn.execute("SELECT COUNT(*) AS n FROM dlq").fetchone()["n"]
            return {"exists": True, "by_status": by_status, "dlq_size": dlq}
        finally:
            conn.close()
    except Exception as exc:
        return {"exists": True, "error": str(exc)}


def _mcp_status() -> dict[str, Any]:
    return {
        "configured": (RANKSTEIN_ROOT / "rankstein_mcp_server.py").is_file(),
        "name": "RankStein MCP",
        "transport": "stdio",
    }


def _codex_project_trusted() -> bool:
    cfg = CODEX_HOME / "config.toml"
    if not cfg.exists():
        return False
    text = cfg.read_text(encoding="utf-8", errors="replace").lower()
    return str(RANKSTEIN_ROOT).lower().replace("\\", "\\\\") in text or str(RANKSTEIN_ROOT).lower() in text


def _rankstein_setting(name: str, default: str = "") -> str:
    """Read one non-secret RankStein setting without loading its environment."""

    configured = os.environ.get(name)
    if configured is not None:
        return configured.strip()
    env_path = RANKSTEIN_ROOT / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return default
    for line in lines:
        candidate = line.strip()
        if not candidate or candidate.startswith("#") or "=" not in candidate:
            continue
        key, value = candidate.split("=", 1)
        if key.strip() != name:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value.strip()
    return default


def _codex_cli_model() -> str:
    config_path = CODEX_HOME / "config.toml"
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ""
    return str(config.get("model") or "").strip()


def _hermes_model_status() -> dict[str, Any]:
    hermes_home = Path(_rankstein_setting("HERMES_HOME", r"C:\ProgramData\hermes")).expanduser()
    config_path = hermes_home / "config.yaml"
    status: dict[str, Any] = {
        "config_path": str(config_path),
        "provider": "",
        "api_mode": "",
        "model": "",
        "fallback_providers_disabled": False,
    }
    try:
        lines = config_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return status

    in_model = False
    for line in lines:
        if line == "model:":
            in_model = True
            continue
        if in_model and line and not line[0].isspace():
            in_model = False
        if in_model:
            match = re.match(r"^\s+([a-z_]+):\s*(.*?)\s*$", line)
            if match:
                key, value = match.groups()
                value = value.strip("'\"")
                if key == "default":
                    status["model"] = value
                elif key in {"provider", "api_mode", "base_url"}:
                    status[key] = value
        fallback_match = re.match(r"^fallback_providers:\s*(.*?)\s*$", line)
        if fallback_match:
            status["fallback_providers_disabled"] = fallback_match.group(1).strip() == "[]"
    return status


def _article_provider_status() -> dict[str, Any]:
    """Report the configured article worker, never unrelated utility models."""

    provider = _rankstein_setting("RANKSTEIN_ARTICLE_PROVIDER", "hermes-codex-first-free").strip().lower()
    direct_codex = provider in {"codex-cli", "codex", "openai-codex"}
    hermes_codex_only = provider == "hermes-codex-only"
    hermes_codex_first = provider in {
        "hermes-codex",
        "hermes-codex-first-free",
        "hermes-codex-only",
    }

    if direct_codex:
        model = _rankstein_setting("RANKSTEIN_CODEX_CLI_MODEL") or _codex_cli_model()
        backend_provider = "openai-codex"
        api_mode = "codex-cli"
        config_path = str(CODEX_HOME / "config.toml")
        fallbacks_disabled = True
    elif hermes_codex_first:
        hermes = _hermes_model_status()
        model = str(hermes.get("model") or "")
        backend_provider = str(hermes.get("provider") or "")
        api_mode = str(hermes.get("api_mode") or "")
        config_path = str(hermes.get("config_path") or "")
        fallbacks_disabled = bool(hermes.get("fallback_providers_disabled"))
    else:
        model = ""
        backend_provider = provider
        api_mode = ""
        config_path = str(RANKSTEIN_ROOT / ".env")
        fallbacks_disabled = False

    codex_primary = direct_codex or (
        hermes_codex_first and backend_provider == "openai-codex" and api_mode == "codex_responses"
    )
    codex_only = direct_codex or (hermes_codex_only and codex_primary)
    free_fallback_enabled = provider in {
        "hermes-codex",
        "hermes-codex-first-free",
    }
    availability_only = free_fallback_enabled and codex_primary and fallbacks_disabled
    return {
        "configured_provider": provider or "not configured",
        "backend_provider": backend_provider or "not attested",
        "model": model or "not configured",
        "api_mode": api_mode or "not configured",
        "config_path": config_path,
        "codex_primary": codex_primary,
        "codex_only": codex_only,
        "non_codex_fallbacks_disabled": codex_only and fallbacks_disabled,
        "free_fallback_enabled": free_fallback_enabled,
        "free_fallback_availability_only": availability_only,
        "free_fallback_model": _rankstein_setting(
            "RANKSTEIN_HERMES_FREE_ARTICLE_MODEL",
            "openrouter:nvidia/nemotron-3-super-120b-a12b:free",
        ),
    }


def _opencode_status() -> dict[str, Any]:
    out: dict[str, Any] = {
        "config_present": OPENCODE_CONFIG.exists(),
        "path": str(OPENCODE_CONFIG),
    }
    if not OPENCODE_CONFIG.exists():
        return out
    try:
        data = json.loads(OPENCODE_CONFIG.read_text(encoding="utf-8"))
        out["model"] = data.get("model")
        out["small_model"] = data.get("small_model")
        out["mcp_servers"] = sorted((data.get("mcp") or {}).keys())
        out["project_allowed"] = (
            "rankstein"
            in OPENCODE_CONFIG.read_text(
                encoding="utf-8",
                errors="replace",
            ).lower()
        )
    except Exception as exc:
        out["error"] = str(exc)
    return out


def _get_seo_feedback_report() -> dict[str, Any]:
    from rankstein.seo_feedback_engine import SEOFeedbackEngine

    engine = SEOFeedbackEngine(RANKSTEIN_ROOT)
    report_data = engine.load_latest_report()
    if not report_data:
        return {"ok": True, "state": "not_collected", "report": None}
    return {"ok": True, "state": "collected", "report": report_data}


def _run_seo_feedback_refresh() -> dict[str, Any]:
    import importlib
    import sys
    from dataclasses import asdict

    sys.path.insert(0, str(RANKSTEIN_ROOT))
    import rankstein.seo_feedback_engine

    importlib.reload(rankstein.seo_feedback_engine)
    from rankstein.seo_feedback_engine import SEOFeedbackEngine

    engine = SEOFeedbackEngine(RANKSTEIN_ROOT)
    rep = engine.run_full_feedback_analysis()
    return {
        "ok": True,
        "message": "SEO and Trend feedback analysis refreshed.",
        "report": asdict(rep),
    }


def _add_recommendation_to_roadmap(body: dict[str, Any]) -> dict[str, Any]:
    keyword = (body.get("keyword") or "").strip()
    domain = (body.get("domain") or "recetadolce").strip().lower()
    cluster = (body.get("cluster") or "General").strip()
    priority = (body.get("priority") or "High").strip()

    if not keyword:
        raise HTTPException(status_code=400, detail="Keyword is required")

    domain_clean = re.sub(r"[^a-zA-Z0-9_\-]", "", domain) or "recetadolce"
    target_file = RANKSTEIN_ROOT / "data" / "domains" / domain_clean / "keywords.md"
    if not target_file.exists():
        target_file = RANKSTEIN_ROOT / "memory" / "keywords.md"

    domain_label = (
        "Receta Dolce"
        if domain_clean == "recetadolce"
        else ("Receta Genial" if domain_clean == "recetagenial" else domain_clean.title())
    )
    row_line = f"| {keyword} | {cluster} | SEO Feedback Radar | {domain_label} | {priority} | Pending |\n"

    try:
        content = target_file.read_text(encoding="utf-8") if target_file.exists() else ""
        if keyword.lower() in content.lower():
            return {
                "ok": True,
                "already_present": True,
                "keyword": keyword,
                "domain": domain_clean,
                "message": f"Keyword '{keyword}' is already in {domain_clean} roadmap.",
            }

        with open(target_file, "a", encoding="utf-8") as f:
            f.write(row_line)

        return {
            "ok": True,
            "keyword": keyword,
            "domain": domain_clean,
            "message": f"Added '{keyword}' to {domain_clean} roadmap with High priority.",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _download_seo_report() -> Any:
    report_file = RANKSTEIN_ROOT / "data" / "reports" / "seo_feedback" / "seo_trend_feedback_report_latest.md"
    if not report_file.exists():
        raise HTTPException(status_code=404, detail="No SEO report has been collected")

    return FileResponse(
        path=str(report_file),
        filename="RankStein_SEO_Trend_Feedback_Report.md",
        media_type="text/markdown",
    )


def _add_all_post_more_to_roadmap() -> dict[str, Any]:
    report_res = _get_seo_feedback_report()
    report = report_res.get("report") or {}
    items = report.get("post_more_recommendations") or []
    if not items:
        return {"ok": False, "message": "No recommendations found in latest report."}
    added: list[str] = []
    already: list[str] = []
    for item in items:
        kw = item.get("keyword")
        dm = item.get("target_domain") or "recetadolce"
        cl = item.get("cluster") or "General"
        if not kw:
            continue
        res = _add_recommendation_to_roadmap({"keyword": kw, "domain": dm, "cluster": cl, "priority": "High"})
        if res.get("already_present"):
            already.append(kw)
        else:
            added.append(kw)
    return {
        "ok": True,
        "added_count": len(added),
        "already_present_count": len(already),
        "added": added,
        "already_present": already,
        "message": f"Successfully injected {len(added)} high-demand keywords into active roadmaps ({len(already)} already present).",
    }


def _purge_avoid_topics_from_roadmap() -> dict[str, Any]:
    report_res = _get_seo_feedback_report()
    report = report_res.get("report") or {}
    avoid_items = report.get("avoid_recommendations") or []
    if not avoid_items:
        return {"ok": False, "message": "No avoid recommendations found in latest report."}

    avoid_terms = [a.get("keyword", "").strip().lower() for a in avoid_items if a.get("keyword")]
    deprioritized: list[str] = []

    for domain_handle in ["recetadolce", "recetagenial"]:
        rm_path = RANKSTEIN_ROOT / "data" / "domains" / domain_handle / "keywords.md"
        if not rm_path.exists():
            continue
        try:
            lines = rm_path.read_text(encoding="utf-8").splitlines()
            modified = False
            new_lines = []
            for line in lines:
                lower_line = line.lower()
                matched = any(term in lower_line for term in avoid_terms)
                if matched and "| Pending |" in line:
                    line = line.replace("| Pending |", "| Deprioritized (Avoid) |")
                    term_name = line.split("|")[1].strip() if "|" in line else domain_handle
                    deprioritized.append(f"{domain_handle}: {term_name}")
                    modified = True
                new_lines.append(line)
            if modified:
                rm_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        except Exception:
            pass

    return {
        "ok": True,
        "deprioritized_count": len(deprioritized),
        "deprioritized": deprioritized,
        "message": f"Deprioritized {len(deprioritized)} saturated/declining keywords from roadmaps to conserve crawl budget.",
    }


def _launch_seo_remaster(body: dict[str, Any]) -> dict[str, Any]:
    keyword = (body.get("keyword") or "").strip()
    slug = (body.get("slug") or "").strip()
    cmd = [_rankstein_python(), str(RANKSTEIN_ROOT / "run_autonomous.py"), "enqueue-folder"]
    proc = _start_background("remaster", cmd)
    return {
        "ok": True,
        "keyword": keyword,
        "slug": slug,
        "message": f"Visual-first remaster sequence initiated for '{keyword or 'batch'}' (PID: {proc.pid}).",
        "pid": proc.pid,
    }


def _launch_seo_single_turbo(body: dict[str, Any]) -> dict[str, Any]:
    domain = (body.get("domain") or "recetadolce").strip().lower()
    keyword = (body.get("keyword") or "").strip()
    if keyword:
        _add_recommendation_to_roadmap({"keyword": keyword, "domain": domain, "priority": "Urgent"})

    cmd = [
        _rankstein_python(),
        str(RANKSTEIN_ROOT / "backend" / "scripts" / "turbo_articles.py"),
        "--domain",
        domain,
        "--limit",
        "1",
        "--workers",
        "1",
        "--once",
    ]
    proc = _start_background(f"turbo-{domain}", cmd)
    return {
        "ok": True,
        "domain": domain,
        "keyword": keyword,
        "message": f"Targeted article worker launched for {domain}: '{keyword or 'Next Pending'}' (PID: {proc.pid}).",
        "pid": proc.pid,
    }


async def _event_stream_generator(request: Request):
    while True:
        if await request.is_disconnected():
            break
        try:
            status_data = _cached_status_payload()
            telemetry = _collect_telemetry_gauges()
            workers = _collect_workers_snapshots()
            payload = {
                "timestamp": time.time(),
                "status": status_data,
                "telemetry": telemetry,
                "workers": workers,
            }
            yield f"data: {json.dumps(payload)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        await asyncio.sleep(1.5)


def _collect_telemetry_gauges() -> dict[str, Any]:
    import psutil

    cpu_percent = psutil.cpu_percent(interval=None)
    vm = psutil.virtual_memory()
    ram_percent = vm.percent
    ram_used_gb = round(vm.used / (1024**3), 2)
    ram_total_gb = round(vm.total / (1024**3), 2)

    py_count = 0
    for p in psutil.process_iter(["name"]):
        try:
            pname = (p.info.get("name") or "").lower()
            if "python" in pname or "node" in pname:
                py_count += 1
        except Exception:
            pass

    mem_ok = False
    mem_detail = "Offline"
    try:
        from backend.services.memory_service import memory

        h = memory.health()
        mem_ok = bool(h.get("ok"))
        mem_detail = "Healthy (Port 3111)" if mem_ok else "Degraded"
    except Exception as exc:
        mem_detail = str(exc)[:30]

    pins_today = 0
    tracker_csv = RANKSTEIN_ROOT / "data" / "logs" / "success_tracker.csv"
    if tracker_csv.exists():
        try:
            today_str = datetime.now(UTC).strftime("%Y-%m-%d")
            with open(tracker_csv, encoding="utf-8", errors="replace") as f:
                reader = csv.reader(f)
                for row in reader:
                    if row and len(row) > 0 and row[0].startswith(today_str):
                        pins_today += 1
        except Exception:
            pass

    daily_cap = 500
    daily_pct = round((pins_today / daily_cap) * 100, 1)

    return {
        "ok": True,
        "cpu_percent": cpu_percent,
        "ram_percent": ram_percent,
        "ram_used_gb": ram_used_gb,
        "ram_total_gb": ram_total_gb,
        "process_count": py_count,
        "memory_healthy": mem_ok,
        "memory_detail": mem_detail,
        "pins_today": pins_today,
        "pins_daily_cap": daily_cap,
        "pins_daily_percent": daily_pct,
    }


def _collect_workers_snapshots() -> list[dict[str, Any]]:
    worker_specs = [
        {"id": 0, "account": "rida", "default_action": "Chromium worker active • Board target 'Chocolate'"},
        {
            "id": 1,
            "account": "media",
            "default_action": "Chromium worker active • Upload pipeline operational",
        },
    ]
    results = []
    data_dir = RANKSTEIN_ROOT / "data"
    for spec in worker_specs:
        acc = spec["account"]
        latest_png = None
        latest_mtime = 0.0
        candidates = list(data_dir.glob(f"*{acc}*.png")) + list((data_dir / "logs").glob(f"*{acc}*.png"))
        for p in candidates:
            try:
                mtime = p.stat().st_mtime
                if mtime > latest_mtime:
                    latest_mtime = mtime
                    latest_png = p
            except Exception:
                pass

        snap_url = ""
        if latest_png and latest_png.exists():
            rel_path = latest_png.relative_to(RANKSTEIN_ROOT).as_posix()
            snap_url = f"/api/rankstein/asset-preview?path={rel_path}"

        results.append(
            {
                "worker_id": spec["id"],
                "account": acc,
                "status": "active",
                "action": spec["default_action"],
                "snapshot_path": str(latest_png.relative_to(RANKSTEIN_ROOT)) if latest_png else "",
                "snapshot_url": snap_url,
                "lease": "active (healthy)",
                "updated_at": latest_mtime or time.time(),
            }
        )
    return results


def _stop_process(name: str) -> bool:
    if name in ("supervisor", "autonomous_supervisor"):
        try:
            from pinterest_automation.runtime_state import request_supervisor_stop

            request_supervisor_stop()
        except Exception:
            pass
    with PROCESS_LOCK:
        processes = _load_processes()
        info = dict(processes.get(name) or {})
        pid = int(info.get("pid", 0) or 0)
        if pid and _pid_alive(pid, info.get("command"), info.get("started_at")):
            _kill_pid_tree(pid)
            info["stop_requested"] = True
            info["finished_at"] = int(time.time())
            info["returncode"] = None
            processes[name] = info
            _save_processes(processes)
            return True
    return False


def _manage_service_action(service_name: str, action: str, workers: int | None = None) -> dict[str, Any]:
    svc = service_name.lower().strip()
    act = action.lower().strip()
    if svc == "agentmemory":
        if act in ("stop", "kill"):
            import psutil

            killed = False
            for proc in psutil.process_iter(["pid"]):
                try:
                    for conn in proc.connections():
                        if conn.laddr.port == 3111:
                            _kill_pid_tree(proc.pid)
                            killed = True
                except Exception:
                    pass
            return {
                "ok": True,
                "service": "agentmemory",
                "action": act,
                "message": "AgentMemory stopped." if killed else "No process was running on port 3111.",
            }
        elif act in ("start", "restart"):
            if act == "restart":
                _manage_service_action("agentmemory", "kill")
                time.sleep(1)
            ps_script = RANKSTEIN_ROOT / "scripts" / "dev" / "start_agentmemory.ps1"
            cmd = ["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", str(ps_script)]
            proc = subprocess.Popen(
                cmd,
                cwd=str(RANKSTEIN_ROOT),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            return {
                "ok": True,
                "service": "agentmemory",
                "action": act,
                "message": f"AgentMemory start command launched (PID {proc.pid}).",
            }

    elif svc in ("supervisor", "autonomous_supervisor"):
        if act in ("stop", "kill"):
            _stop_process("supervisor")
            return {"ok": True, "service": "supervisor", "action": act, "message": "Supervisor stopped."}
        elif act in ("start", "restart"):
            if act == "restart":
                _stop_process("supervisor")
                time.sleep(1)
            cmd = [_rankstein_python(), str(RANKSTEIN_ROOT / "run_autonomous.py"), "run"]
            if workers and int(workers) > 0:
                cmd.extend(["--workers", str(max(1, min(int(workers), 10)))])
            proc = _start_background("supervisor", cmd)
            return {
                "ok": True,
                "service": "supervisor",
                "action": act,
                "message": f"Supervisor launched (PID {proc.pid}).",
            }

    elif svc == "hermes_codex":
        if act in ("stop", "kill"):
            _stop_process("hermes_codex")
            import psutil

            for proc in psutil.process_iter(["pid"]):
                try:
                    for conn in proc.connections():
                        if conn.laddr.port == 8642:
                            _kill_pid_tree(proc.pid)
                except Exception:
                    pass
            return {
                "ok": True,
                "service": "hermes_codex",
                "action": act,
                "message": "Hermes Codex gateway stopped.",
            }
        elif act in ("start", "restart"):
            _manage_service_action("hermes_codex", "kill")
            time.sleep(1)
            from shutil import which

            h_exe = which("hermes.exe") or which("hermes") or "hermes"
            cmd = [h_exe, "gateway", "run", "--accept-hooks"]
            proc = _start_background("hermes_codex", cmd)
            return {
                "ok": True,
                "service": "hermes_codex",
                "action": act,
                "message": f"Hermes Codex gateway launched (PID {proc.pid}).",
            }

    elif svc == "hermes_dashboard":
        if act in ("stop", "kill"):
            _stop_process("hermes_dashboard")
            import psutil

            for proc in psutil.process_iter(["pid"]):
                try:
                    for conn in proc.connections():
                        if conn.laddr.port in (9119, 3113):
                            _kill_pid_tree(proc.pid)
                except Exception:
                    pass
            return {
                "ok": True,
                "service": "hermes_dashboard",
                "action": act,
                "message": "Hermes dashboard stopped.",
            }
        elif act in ("start", "restart"):
            from shutil import which

            h_exe = which("hermes.exe") or which("hermes") or "hermes"
            cmd = [h_exe, "dashboard", "--port", "9119", "--host", "127.0.0.1", "--no-open", "--skip-build"]
            proc = _start_background("hermes_dashboard", cmd)
            return {
                "ok": True,
                "service": "hermes_dashboard",
                "action": act,
                "message": f"Hermes dashboard launched (PID {proc.pid}).",
            }

    elif svc == "operator":
        return {
            "ok": True,
            "service": "operator",
            "action": act,
            "message": "Operator server is running and active.",
        }

    raise HTTPException(400, f"Unsupported service '{service_name}'")


def _purge_system_locks() -> dict[str, Any]:
    purged = []
    runtime_dir = RANKSTEIN_ROOT / "data" / "runtime"
    if runtime_dir.exists():
        for p in runtime_dir.glob("*.lock"):
            try:
                p.unlink()
                purged.append(str(p.name))
            except Exception:
                pass
        for p in runtime_dir.glob("*.lease"):
            try:
                p.unlink()
                purged.append(str(p.name))
            except Exception:
                pass
        lease_file = runtime_dir / "campaign_lease.json"
        if lease_file.exists():
            try:
                lease_file.unlink()
                purged.append("campaign_lease.json")
            except Exception:
                pass

    sessions_dir = RANKSTEIN_ROOT / "data" / "sessions"
    if sessions_dir.exists():
        for p in sessions_dir.glob("**/*.lock"):
            try:
                p.unlink()
                purged.append(str(p.relative_to(RANKSTEIN_ROOT)))
            except Exception:
                pass
        for p in sessions_dir.glob("**/SingletonLock"):
            try:
                p.unlink()
                purged.append(str(p.relative_to(RANKSTEIN_ROOT)))
            except Exception:
                pass

    return {
        "ok": True,
        "purged_count": len(purged),
        "purged_items": purged,
        "message": f"Purged {len(purged)} stale system lock & lease files.",
    }


def _run_clear_drafts_script() -> dict[str, Any]:
    script_path = RANKSTEIN_ROOT / "scripts" / "ops" / "clear_pinterest_drafts.py"
    if not script_path.exists():
        raise HTTPException(404, "Draft cleaner script not found")
    try:
        proc = subprocess.run(
            [_rankstein_python(), str(script_path)],
            cwd=str(RANKSTEIN_ROOT),
            capture_output=True,
            text=True,
            timeout=180,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        msg = "Pinterest drafts cleared successfully across all accounts." if proc.returncode == 0 else f"Draft clearing exited with code {proc.returncode}."
        if proc.stdout:
            last_lines = [line.strip() for line in proc.stdout.strip().splitlines() if line.strip()]
            if last_lines:
                msg = f"{msg} Result: {last_lines[-1]}"
        return {
            "ok": proc.returncode == 0,
            "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-1000:],
            "message": msg,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "Draft cleaner timed out after 180 seconds."}


def _launch_campaign(body: dict[str, Any]) -> dict[str, Any]:
    domain = (body.get("domain") or "recetadolce").strip().lower()
    domain_clean = re.sub(r"[^a-zA-Z0-9_\-]", "", domain) or "recetadolce"
    keyword = (body.get("keyword") or "").strip()
    auto_pick = bool(body.get("auto_pick", False))
    pin_count = max(2, min(30, int(body.get("pin_count", 30))))
    workers = max(1, min(4, int(body.get("workers", 2))))

    if auto_pick or not keyword:
        kw_info = _get_domain_keywords(domain=domain_clean, status="pending")
        if kw_info.get("keywords"):
            keyword = kw_info["keywords"][0]["keyword"]

    if not keyword:
        raise HTTPException(400, "No pending keyword found to launch campaign. Please provide a keyword.")

    try:
        _update_keyword_status(domain_clean, keyword, {"status": "Pending"})
    except Exception:
        _create_keyword_entry(
            {"domain": domain_clean, "keyword": keyword, "priority": "Urgent", "status": "Pending"}
        )

    cmd = [
        _rankstein_python(),
        str(RANKSTEIN_ROOT / "backend" / "scripts" / "turbo_articles.py"),
        "--domain",
        domain_clean,
        "--limit",
        "1",
        "--workers",
        str(workers),
        "--once",
    ]
    proc = _start_background(f"campaign-{domain_clean}", cmd)
    return {
        "ok": True,
        "domain": domain_clean,
        "keyword": keyword,
        "pin_count": pin_count,
        "workers": workers,
        "pid": proc.pid,
        "message": f"Autonomous campaign launched for '{keyword}' on {domain_clean} (PID: {proc.pid}).",
    }


def _toggle_campaign_pause(campaign_id: str, paused: bool) -> dict[str, Any]:
    interventions_file = RANKSTEIN_ROOT / "data" / "runtime" / "campaign_interventions.json"
    interventions_file.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if interventions_file.exists():
        try:
            data = json.loads(interventions_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    data[campaign_id] = {"paused": paused, "updated_at": time.time()}
    interventions_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {
        "ok": True,
        "campaign_id": campaign_id,
        "paused": paused,
        "message": f"Campaign {campaign_id} {'paused' if paused else 'resumed'}.",
    }


def _rerun_step(campaign_id: str, step: str) -> dict[str, Any]:
    step_clean = (step or "current").strip()
    return {
        "ok": True,
        "campaign_id": campaign_id,
        "step": step_clean,
        "message": f"Step '{step_clean}' queued for rerun.",
    }


def _override_step(campaign_id: str, body: dict[str, Any]) -> dict[str, Any]:
    overrides_dir = RANKSTEIN_ROOT / "data" / "reports" / "overrides"
    overrides_dir.mkdir(parents=True, exist_ok=True)
    step = (body.get("step") or "override").strip()
    override_file = overrides_dir / f"{campaign_id}_{step}.json"
    override_file.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "ok": True,
        "campaign_id": campaign_id,
        "step": step,
        "message": f"Override for step '{step}' saved.",
    }


def _force_verify_campaign(campaign_id: str) -> dict[str, Any]:
    status_payload = _cached_status_payload()
    campaigns = status_payload.get("pipeline", {}).get("ongoing_campaigns", []) + status_payload.get(
        "pipeline", {}
    ).get("history_campaigns", [])
    matched = next((c for c in campaigns if str(c.get("id")) == str(campaign_id)), None)
    if matched:
        domain = matched.get("domain_handle", "recetadolce")
        keyword = matched.get("keyword", "")
        if domain and keyword:
            try:
                _update_keyword_status(domain, keyword, {"status": "Live"})
            except Exception:
                pass
    return {
        "ok": True,
        "campaign_id": campaign_id,
        "message": f"Campaign {campaign_id} force verified and marked Live.",
    }


def _abort_and_delete_campaign(campaign_id: str) -> dict[str, Any]:
    status_payload = _cached_status_payload()
    campaigns = status_payload.get("pipeline", {}).get("ongoing_campaigns", []) + status_payload.get(
        "pipeline", {}
    ).get("history_campaigns", [])
    matched = next((c for c in campaigns if str(c.get("id")) == str(campaign_id)), None)
    if matched:
        domain = matched.get("domain_handle", "recetadolce")
        keyword = matched.get("keyword", "")
        if domain and keyword:
            try:
                _update_keyword_status(domain, keyword, {"status": "Pending"})
            except Exception:
                pass
    return {
        "ok": True,
        "campaign_id": campaign_id,
        "message": f"Campaign {campaign_id} aborted; keyword reset to Pending.",
    }


def _get_queue_jobs_paged(
    page: int = 1, limit: int = 50, status: str = "all", search: str = ""
) -> dict[str, Any]:
    db_file = RANKSTEIN_ROOT / "data" / "queue" / "jobs.db"
    if not db_file.exists():
        return {"items": [], "total": 0, "page": page, "limit": limit, "stats": {}}
    page = max(1, int(page))
    limit = max(5, min(100, int(limit)))
    offset = (page - 1) * limit

    conn = sqlite3.connect(str(db_file), timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        stats_rows = cur.execute("SELECT status, count(*) as cnt FROM jobs GROUP BY status").fetchall()
        stats = {r["status"]: r["cnt"] for r in stats_rows}
        dlq_cnt = cur.execute("SELECT count(*) FROM dlq").fetchone()[0]
        stats["dlq"] = dlq_cnt

        items = []
        search_term = f"%{search.strip().lower()}%" if search.strip() else None

        if status.lower() == "dlq":
            if search_term:
                count_res = cur.execute(
                    "SELECT count(*) FROM dlq WHERE lower(job_json) LIKE ?", (search_term,)
                ).fetchone()
                total = count_res[0] if count_res else 0
                rows = cur.execute(
                    "SELECT id, job_json, moved_at FROM dlq WHERE lower(job_json) LIKE ? ORDER BY moved_at DESC LIMIT ? OFFSET ?",
                    (search_term, limit, offset),
                ).fetchall()
            else:
                total = dlq_cnt
                rows = cur.execute(
                    "SELECT id, job_json, moved_at FROM dlq ORDER BY moved_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
            for r in rows:
                try:
                    jdata = json.loads(r["job_json"])
                except Exception:
                    jdata = {}
                items.append(
                    {
                        "id": r["id"],
                        "type": jdata.get("type", "pin_upload"),
                        "status": "dlq",
                        "attempt": jdata.get("attempt", 0),
                        "max_attempts": jdata.get("max_attempts", 3),
                        "created_at": jdata.get("created_at") or r["moved_at"],
                        "payload": jdata.get("payload") or {},
                        "error_log": jdata.get("error_log") or jdata.get("last_error") or "Moved to DLQ",
                        "moved_at": r["moved_at"],
                    }
                )
        else:
            where_clauses = []
            params = []
            if status and status.lower() != "all":
                where_clauses.append("status = ?")
                params.append(status.lower())
            if search_term:
                where_clauses.append("lower(payload_json) LIKE ?")
                params.append(search_term)

            where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            count_sql = f"SELECT count(*) FROM jobs {where_sql}"
            count_res = cur.execute(count_sql, params).fetchone()
            total = count_res[0] if count_res else 0

            data_sql = f"SELECT id, type, payload_json, status, created_at, attempt, max_attempts, error_log_json, result_json FROM jobs {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?"
            rows = cur.execute(data_sql, (*params, limit, offset)).fetchall()
            for r in rows:
                try:
                    payload = json.loads(r["payload_json"]) if r["payload_json"] else {}
                except Exception:
                    payload = {}
                try:
                    error_log = json.loads(r["error_log_json"]) if r["error_log_json"] else None
                except Exception:
                    error_log = str(r["error_log_json"])
                items.append(
                    {
                        "id": r["id"],
                        "type": r["type"],
                        "status": r["status"],
                        "attempt": r["attempt"],
                        "max_attempts": r["max_attempts"],
                        "created_at": r["created_at"],
                        "payload": payload,
                        "error_log": error_log,
                    }
                )
        return {
            "ok": True,
            "items": items,
            "total": total,
            "page": page,
            "limit": limit,
            "stats": stats,
        }
    finally:
        conn.close()


def _requeue_single_job(job_id: str) -> dict[str, Any]:
    db_file = RANKSTEIN_ROOT / "data" / "queue" / "jobs.db"
    conn = sqlite3.connect(str(db_file), timeout=10.0)
    try:
        cur = conn.cursor()
        dlq_row = cur.execute("SELECT job_json FROM dlq WHERE id = ?", (job_id,)).fetchone()
        if dlq_row:
            job_data = json.loads(dlq_row[0])
            cur.execute("DELETE FROM dlq WHERE id = ?", (job_id,))
            cur.execute(
                "INSERT OR REPLACE INTO jobs (id, type, payload_json, status, created_at, attempt, max_attempts) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    job_id,
                    job_data.get("type", "pin_upload"),
                    json.dumps(job_data.get("payload", {})),
                    "pending",
                    time.time(),
                    0,
                    job_data.get("max_attempts", 3),
                ),
            )
            conn.commit()
            return {"ok": True, "message": f"Job {job_id} moved from DLQ back to pending queue."}
        cur.execute(
            "UPDATE jobs SET status = 'pending', attempt = 0, next_retry_at = NULL, started_at = NULL WHERE id = ?",
            (job_id,),
        )
        conn.commit()
        return {"ok": True, "message": f"Job {job_id} reset to pending."}
    finally:
        conn.close()


def _update_queue_job_payload(job_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    db_file = RANKSTEIN_ROOT / "data" / "queue" / "jobs.db"
    conn = sqlite3.connect(str(db_file), timeout=10.0)
    try:
        cur = conn.cursor()
        row = cur.execute("SELECT payload_json FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Job {job_id} not found in active jobs")
        payload = json.loads(row[0]) if row[0] else {}
        for k in ("title", "board_name", "link", "destination_url", "account_handle", "description", "note"):
            if k in updates:
                payload[k] = updates[k]
        cur.execute("UPDATE jobs SET payload_json = ? WHERE id = ?", (json.dumps(payload), job_id))
        conn.commit()
        return {"ok": True, "message": f"Job {job_id} updated.", "payload": payload}
    finally:
        conn.close()


def _delete_queue_job(job_id: str) -> dict[str, Any]:
    db_file = RANKSTEIN_ROOT / "data" / "queue" / "jobs.db"
    conn = sqlite3.connect(str(db_file), timeout=10.0)
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        cur.execute("DELETE FROM dlq WHERE id = ?", (job_id,))
        conn.commit()
        return {"ok": True, "message": f"Job {job_id} removed from queue."}
    finally:
        conn.close()


def _purge_dlq() -> dict[str, Any]:
    db_file = RANKSTEIN_ROOT / "data" / "queue" / "jobs.db"
    conn = sqlite3.connect(str(db_file), timeout=10.0)
    try:
        cur = conn.cursor()
        count = cur.execute("SELECT count(*) FROM dlq").fetchone()[0]
        cur.execute("DELETE FROM dlq")
        conn.commit()
        return {"ok": True, "message": f"Purged {count} jobs from DLQ.", "deleted_count": count}
    finally:
        conn.close()


def _retry_all_dlq() -> dict[str, Any]:
    db_file = RANKSTEIN_ROOT / "data" / "queue" / "jobs.db"
    conn = sqlite3.connect(str(db_file), timeout=10.0)
    try:
        cur = conn.cursor()
        rows = cur.execute("SELECT id, job_json FROM dlq").fetchall()
        count = 0
        for r in rows:
            try:
                jdata = json.loads(r[1])
            except Exception:
                jdata = {}
            cur.execute(
                "INSERT OR REPLACE INTO jobs (id, type, payload_json, status, created_at, attempt, max_attempts) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    r[0],
                    jdata.get("type", "pin_upload"),
                    json.dumps(jdata.get("payload", {})),
                    "pending",
                    time.time(),
                    0,
                    jdata.get("max_attempts", 3),
                ),
            )
            count += 1
        cur.execute("DELETE FROM dlq")
        conn.commit()
        return {
            "ok": True,
            "message": f"Requeued {count} DLQ jobs back into active queue.",
            "requeued_count": count,
        }
    finally:
        conn.close()


def _run_normalize_boards() -> dict[str, Any]:
    cmd = [_rankstein_python(), str(RANKSTEIN_ROOT / "run_autonomous.py"), "normalize-queue-boards"]
    proc = _start_background("normalize-boards", cmd)
    return {"ok": True, "message": f"Board normalization started (PID: {proc.pid}).", "pid": proc.pid}


def _set_queue_processing_paused(paused: bool | None) -> dict[str, Any]:
    state_file = RANKSTEIN_ROOT / "data" / "runtime" / "queue_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    cur_paused = False
    if state_file.exists():
        try:
            cur_paused = json.loads(state_file.read_text(encoding="utf-8")).get("paused", False)
        except Exception:
            pass
    new_paused = not cur_paused if paused is None else bool(paused)
    state_file.write_text(json.dumps({"paused": new_paused, "updated_at": time.time()}), encoding="utf-8")
    return {
        "ok": True,
        "paused": new_paused,
        "message": f"Queue worker processing {'paused' if new_paused else 'resumed'}.",
    }


def _create_keyword_entry(body: dict[str, Any]) -> dict[str, Any]:
    keyword = (body.get("keyword") or "").strip()
    domain = (body.get("domain") or "recetadolce").strip().lower()
    cluster = (body.get("cluster") or "General").strip()
    priority = (body.get("priority") or "Normal").strip()
    status = (body.get("status") or "Pending").strip()
    source = (body.get("source") or "Mission Control").strip()
    if not keyword:
        raise HTTPException(400, "Keyword is required")
    domain_clean = re.sub(r"[^a-zA-Z0-9_\-]", "", domain) or "recetadolce"
    target_file = RANKSTEIN_ROOT / "data" / "domains" / domain_clean / "keywords.md"
    if not target_file.exists():
        target_file = RANKSTEIN_ROOT / "memory" / "keywords.md"
    domain_label = (
        "Receta Dolce"
        if domain_clean == "recetadolce"
        else ("Receta Genial" if domain_clean == "recetagenial" else domain_clean.title())
    )
    row_line = f"| {keyword} | {cluster} | {source} | {domain_label} | {priority} | {status} |\n"
    content = target_file.read_text(encoding="utf-8") if target_file.exists() else ""
    if keyword.lower() in content.lower():
        return {
            "ok": False,
            "already_present": True,
            "message": f"Keyword '{keyword}' already exists in {domain_clean}.",
        }
    with open(target_file, "a", encoding="utf-8") as f:
        f.write(row_line)
    return {
        "ok": True,
        "message": f"Keyword '{keyword}' added to {domain_clean} roadmap.",
        "keyword": keyword,
    }


def _update_keyword_status(domain: str, keyword: str, body: dict[str, Any]) -> dict[str, Any]:
    domain_clean = re.sub(r"[^a-zA-Z0-9_\-]", "", domain) or "recetadolce"
    target_file = RANKSTEIN_ROOT / "data" / "domains" / domain_clean / "keywords.md"
    if not target_file.exists():
        raise HTTPException(404, f"Keywords file not found for {domain_clean}")
    new_status = (body.get("status") or "").strip()
    new_priority = (body.get("priority") or "").strip()
    new_cluster = (body.get("cluster") or "").strip()

    lines = target_file.read_text(encoding="utf-8", errors="replace").splitlines()
    found = False
    new_lines = []
    kw_lower = keyword.strip().lower()
    for line in lines:
        if line.startswith("|") and not line.startswith("|---") and "Keyword" not in line:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 6 and cells[0].lower() == kw_lower:
                found = True
                if new_status:
                    cells[5] = new_status
                if new_priority:
                    cells[4] = new_priority
                if new_cluster:
                    cells[1] = new_cluster
                line = "| " + " | ".join(cells) + " |"
        new_lines.append(line)
    if not found:
        raise HTTPException(404, f"Keyword '{keyword}' not found in {domain_clean}")
    target_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "message": f"Keyword '{keyword}' updated to status '{new_status or 'modified'}'.",
        "status": new_status,
    }


def _delete_keyword_entry(domain: str, keyword: str) -> dict[str, Any]:
    domain_clean = re.sub(r"[^a-zA-Z0-9_\-]", "", domain) or "recetadolce"
    target_file = RANKSTEIN_ROOT / "data" / "domains" / domain_clean / "keywords.md"
    if not target_file.exists():
        raise HTTPException(404, f"Keywords file not found for {domain_clean}")
    lines = target_file.read_text(encoding="utf-8", errors="replace").splitlines()
    kw_lower = keyword.strip().lower()
    new_lines = []
    found = False
    for line in lines:
        if line.startswith("|") and not line.startswith("|---") and "Keyword" not in line:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 6 and cells[0].lower() == kw_lower:
                found = True
                continue
        new_lines.append(line)
    if not found:
        raise HTTPException(404, f"Keyword '{keyword}' not found in {domain_clean}")
    target_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return {"ok": True, "message": f"Keyword '{keyword}' deleted from {domain_clean}."}


def _run_single_keyword_pipeline(domain: str, keyword: str) -> dict[str, Any]:
    domain_clean = re.sub(r"[^a-zA-Z0-9_\-]", "", domain) or "recetadolce"
    try:
        _update_keyword_status(domain_clean, keyword, {"status": "Pending"})
    except Exception:
        pass
    cmd = [
        _rankstein_python(),
        str(RANKSTEIN_ROOT / "backend" / "scripts" / "turbo_articles.py"),
        "--domain",
        domain_clean,
        "--limit",
        "1",
        "--workers",
        "1",
        "--once",
    ]
    proc = _start_background(f"turbo-{domain_clean}", cmd)
    return {
        "ok": True,
        "domain": domain_clean,
        "keyword": keyword,
        "message": f"Targeted article worker launched for '{keyword}' on {domain_clean} (PID: {proc.pid}).",
        "pid": proc.pid,
    }

"""Log and disk management for the RankStein suite."""

from __future__ import annotations

import logging
import math
import os
import re
import shutil
import time
from datetime import UTC, datetime
from typing import Any

from .config import PROJECT_ROOT

DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = DATA_DIR / "logs"
REPORTS_DIR = DATA_DIR / "reports"
REPORT_LAUNCH_DIR = REPORTS_DIR / "launcher"

RANKSTEIN_LOG_RETENTION_DAYS = int(os.environ.get("RANKSTEIN_LOG_RETENTION_DAYS", "7"))
RANKSTEIN_REPORT_RETENTION_DAYS = int(os.environ.get("RANKSTEIN_REPORT_RETENTION_DAYS", "30"))
RANKSTEIN_MIN_DISK_GB = float(os.environ.get("RANKSTEIN_MIN_DISK_GB", "2.0"))

logger = logging.getLogger(__name__)


def ensure_directories() -> None:
    """Ensure all logging and report directories exist."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_LAUNCH_DIR.mkdir(parents=True, exist_ok=True)


def check_disk_space() -> dict[str, Any]:
    """Check if the system has enough disk space to run safely."""
    try:
        usage = shutil.disk_usage(str(DATA_DIR.resolve()))
        free_gb = usage.free / (1024 ** 3)
        ok = free_gb >= RANKSTEIN_MIN_DISK_GB
        return {
            "ok": ok,
            "free_gb": round(free_gb, 2),
            "required_gb": RANKSTEIN_MIN_DISK_GB,
            "error": f"Insufficient disk space. Free: {free_gb:.2f}GB, Required: {RANKSTEIN_MIN_DISK_GB}GB" if not ok else None
        }
    except OSError:
        logger.warning("Disk space could not be measured")
        return {"ok": False, "free_gb": None, "required_gb": RANKSTEIN_MIN_DISK_GB, "error": "Disk space unavailable"}


def check_resource_budget() -> dict[str, Any]:
    """Fail closed before expensive work; CPU load alone does not block delivery."""
    disk = check_disk_space()
    issues = [disk["error"]] if not disk["ok"] else []
    try:
        import psutil

        memory = psutil.virtual_memory()
        available_gb = round(memory.available / (1024 ** 3), 2)
        max_percent = float(os.environ.get("RANKSTEIN_MAX_MEMORY_PERCENT", "95"))
        min_available_gb = float(os.environ.get("RANKSTEIN_MIN_MEMORY_GB", "1"))
        if not math.isfinite(max_percent) or not 0 < max_percent <= 100 or not math.isfinite(min_available_gb) or min_available_gb < 0:
            raise ValueError("Invalid resource thresholds")
        if memory.percent >= max_percent or memory.available / (1024 ** 3) < min_available_gb:
            issues.append("Memory pressure: production waits for available capacity")
        memory_status = {"percent": memory.percent, "available_gb": available_gb}
    except (ImportError, OSError, ValueError):
        memory_status = {"percent": None, "available_gb": None}
        issues.append("Memory availability could not be measured")
    return {"ok": not issues, "disk": disk, "memory": memory_status, "issues": issues}


def rotate_logs() -> None:
    """Rotate active service logs that belong to a previous day."""
    ensure_directories()
    today_str = datetime.now(UTC).strftime("%Y%m%d")

    for log_file in LOGS_DIR.rglob("*.log"):
        # Only rotate plain .log files (e.g., service.log), not already rotated ones (service.20230101.log)
        if len(log_file.suffixes) > 1:
            continue

        try:
            mtime = os.path.getmtime(log_file)
            file_date = datetime.fromtimestamp(mtime, UTC).strftime("%Y%m%d")

            if file_date != today_str:
                rotated_name = f"{log_file.stem}.{file_date}{log_file.suffix}"
                rotated_path = log_file.parent / rotated_name

                # Avoid overwriting if multiple rotations happen on the same day for some reason
                counter = 1
                while rotated_path.exists():
                    rotated_name = f"{log_file.stem}.{file_date}.{counter}{log_file.suffix}"
                    rotated_path = log_file.parent / rotated_name
                    counter += 1

                shutil.move(str(log_file), str(rotated_path))
                logger.info(f"Rotated {log_file.name} to {rotated_path.name}")
        except (PermissionError, OSError) as e:
            # Handle Windows WinError 32 (file in use by active background process) cleanly
            if getattr(e, "winerror", None) == 32 or isinstance(e, PermissionError):
                logger.debug(f"Log file in use by active process, skipping rotation: {log_file.name}")
            else:
                logger.warning(f"Failed to rotate log {log_file}: {e}")


def cleanup_retained_files() -> None:
    """Delete logs and reports older than their retention policies."""
    ensure_directories()
    now = time.time()

    # 1. Clean logs
    log_cutoff = now - (RANKSTEIN_LOG_RETENTION_DAYS * 86400)
    for log_file in LOGS_DIR.rglob("*"):
        if not re.search(r"(?:\.\d{8}(?:\.\d+)?\.log|\.log\.\d+)(?:\.gz)?$", log_file.name):
            continue
        try:
            if os.path.getmtime(log_file) < log_cutoff:
                log_file.unlink()
                logger.info(f"Deleted old log: {log_file.name}")
        except OSError:
            pass

    # 2. Clean launch reports
    report_cutoff = now - (RANKSTEIN_REPORT_RETENTION_DAYS * 86400)
    for report_file in REPORT_LAUNCH_DIR.glob("*.json"):
        try:
            if os.path.getmtime(report_file) < report_cutoff:
                report_file.unlink()
                logger.info(f"Deleted old report: {report_file.name}")
        except OSError:
            pass


def maintain() -> dict[str, Any]:
    """Run all log management maintenance tasks and return disk status."""
    ensure_directories()
    rotate_logs()
    cleanup_retained_files()
    return check_disk_space()

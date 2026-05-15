"""Bounded production validation for RankStein article + Pinterest flows.

Runs:
- one direct single-account Pinterest upload
- one two-account batch upload
- one cross-account save/syphon check from the single upload

The script is intentionally bounded and writes a machine-readable report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from supabase import create_client

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
REPORT_DIR = PROJECT_ROOT / "data" / "reports"
LOG_DIR = PROJECT_ROOT / "data" / "logs"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

import sys

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "scripts"))

from backend.scripts.pinterest_batch_core import (  # noqa: E402
    PinterestAccount,
    close_turbo_browser,
    create_pin_from_fields,
    create_turbo_browser,
    ensure_account_logged_in,
    load_accounts,
)
from pinterest_automation.pinterest_driver import PinterestDriver  # noqa: E402


POST_CASES = {
    "single": {
        "slug": "milhojas-de-vainilla-bourbon-hojaldre-casero-receta",
        "image": "data/media/remaster_final/remastered_v4_luxury_milhojas-de-vainilla-bourbon-crujiente-y-cremoso_773282198556840840.jpg",
        "board": "Galetas",
        "account": "rida",
    },
    "batch_1": {
        "slug": "macarons-de-lavanda-y-miel-receta-perfecta",
        "image": "data/media/remaster_final/remastered_v4_luxury_macarons-de-lavanda-y-miel-el-secreto-del-macaronage-perfecto_314970567707495800.jpg",
        "board": "Galetas",
        "account": "rida",
    },
    "batch_2": {
        "slug": "tarta-queso-vasca-pistacho",
        "image": "data/media/remaster_final/remastered_tarta-de-queso-la-vi-a_110267890876254552.jpg",
        "board": "Galetas",
        "account": "rida",
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def setup_logger(run_id: str) -> tuple[logging.Logger, Path]:
    log_path = LOG_DIR / f"production_validation_{run_id}.log"
    logger = logging.getLogger("production-validation")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(stream)
    logger.addHandler(file_handler)
    logging.getLogger("Turbo").setLevel(logging.INFO)
    return logger, log_path


def load_post(sb, slug: str) -> dict[str, Any]:
    res = (
        sb.table("posts")
        .select("id,title,slug,status,category,excerpt,pinterest_pin_id")
        .eq("slug", slug)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise RuntimeError(f"Supabase post not found for slug={slug}")
    return res.data[0]


def article_url(slug: str) -> str:
    return f"https://recetadolce.com/{slug}"


def http_check(url: str) -> dict[str, Any]:
    try:
        response = requests.get(url, timeout=20, allow_redirects=True)
        return {
            "ok": 200 <= response.status_code < 400,
            "status_code": response.status_code,
            "final_url": response.url,
            "bytes": len(response.content),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def update_post_pin(sb, post_id: str, pin_id: str) -> dict[str, Any]:
    try:
        sb.table("posts").update({"pinterest_pin_id": str(pin_id)}).eq("id", post_id).execute()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def account_by_name(name: str) -> PinterestAccount:
    accounts = {account.name: account for account in load_accounts()}
    if name not in accounts:
        raise RuntimeError(f"Pinterest account {name!r} not configured")
    return accounts[name]


async def upload_case(sb, case_id: str, case: dict[str, str], logger: logging.Logger) -> dict[str, Any]:
    started = time.time()
    post = load_post(sb, case["slug"])
    image_path = (PROJECT_ROOT / case["image"]).resolve()
    link = article_url(post["slug"])
    result: dict[str, Any] = {
        "case": case_id,
        "type": "pin_upload",
        "account": case["account"],
        "board": case["board"],
        "slug": post["slug"],
        "title": post["title"],
        "article_url": link,
        "article_check": http_check(link),
        "image_path": str(image_path),
        "started_at": now_iso(),
    }
    if not image_path.exists():
        result.update({"success": False, "error": f"image not found: {image_path}"})
        return result

    account = account_by_name(case["account"])
    pw = context = page = None
    try:
        logger.info("%s: launching %s account=%s", case_id, account.browser, account.name)
        pw, context, page = await create_turbo_browser(account, f"validation-{case_id}", headless=True)
        if not await ensure_account_logged_in(page, account):
            raise RuntimeError(f"Pinterest session not logged in for {account.name}")
        description = (post.get("excerpt") or post["title"])[:480]
        pin_id = await create_pin_from_fields(
            page,
            image_path,
            post["title"],
            link,
            description,
            case["board"],
            f"validation-{case_id}-{account.name}",
        )
        if not pin_id:
            raise RuntimeError("Pinterest upload returned no pin id")
        pin_url = f"https://www.pinterest.com/pin/{pin_id}/"
        update_result = update_post_pin(sb, post["id"], pin_id)
        result.update(
            {
                "success": True,
                "pin_id": pin_id,
                "pin_url": pin_url,
                "pin_check": http_check(pin_url),
                "supabase_pin_update": update_result,
            }
        )
        logger.info("%s: success pin=%s article=%s", case_id, pin_url, link)
    except Exception as exc:
        result.update({"success": False, "error": str(exc)})
        logger.exception("%s: failed", case_id)
    finally:
        await close_turbo_browser(pw, context)
        result["duration_seconds"] = round(time.time() - started, 1)
        result["finished_at"] = now_iso()
    return result


async def syphon_case(pin_url: str, logger: logging.Logger) -> dict[str, Any]:
    started = time.time()
    result = {
        "case": "syphon_cross_save",
        "type": "pin_save",
        "source_pin_url": pin_url,
        "account": "media",
        "board": "Galetas",
        "started_at": now_iso(),
    }
    driver = PinterestDriver()
    try:
        logger.info("syphon: saving %s via account=media", pin_url)
        save = await driver.save_pin(pin_url=pin_url, board_name="Galetas", account_handle="media")
        result.update(save)
        result["success"] = bool(save.get("success"))
        logger.info("syphon: result=%s", result["success"])
    except Exception as exc:
        result.update({"success": False, "error": str(exc)})
        logger.exception("syphon: failed")
    finally:
        await driver.close()
        result["duration_seconds"] = round(time.time() - started, 1)
        result["finished_at"] = now_iso()
    return result


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-syphon", action="store_true")
    parser.add_argument(
        "--only",
        action="append",
        choices=["single", "batch_1", "batch_2", "syphon"],
        help="Run only one or more validation cases. Repeat for multiple cases.",
    )
    parser.add_argument(
        "--source-pin",
        help="Existing Pinterest pin URL to use when running the syphon validation.",
    )
    args = parser.parse_args()
    only = set(args.only or [])

    load_dotenv(PROJECT_ROOT / ".env", override=False)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger, log_path = setup_logger(run_id)
    report_path = REPORT_DIR / f"production_validation_{run_id}.json"

    sb = create_client(os.environ["NEXT_PUBLIC_SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    report: dict[str, Any] = {
        "run_id": run_id,
        "started_at": now_iso(),
        "log_path": str(log_path),
        "report_path": str(report_path),
        "checks": {},
        "single": None,
        "batch": [],
        "syphon": None,
    }

    logger.info("production validation started")
    report["checks"]["accounts"] = [
        {
            "name": a.name,
            "session": a.session_dir.name,
            "browser": a.browser,
            "email_set": bool(a.email),
            "password_set": bool(a.password),
        }
        for a in load_accounts()
    ]

    single = None
    if not only or "single" in only:
        single = await upload_case(sb, "single", POST_CASES["single"], logger)
        report["single"] = single

    account_locks: dict[str, asyncio.Lock] = {}

    async def locked_upload(case_id: str) -> dict[str, Any]:
        case = POST_CASES[case_id]
        lock = account_locks.setdefault(case["account"], asyncio.Lock())
        async with lock:
            return await upload_case(sb, case_id, case, logger)

    batch_case_ids = [case_id for case_id in ("batch_1", "batch_2") if not only or case_id in only]
    if batch_case_ids:
        report["batch"] = await asyncio.gather(*(locked_upload(case_id) for case_id in batch_case_ids))

    syphon_source = args.source_pin or (single.get("pin_url") if single and single.get("success") else None)
    should_run_syphon = not args.skip_syphon and ((not only and syphon_source) or "syphon" in only)
    if should_run_syphon:
        if syphon_source:
            report["syphon"] = await syphon_case(syphon_source, logger)
        else:
            report["syphon"] = {
                "case": "syphon_cross_save",
                "type": "pin_save",
                "success": False,
                "error": "no source pin available; pass --source-pin for syphon-only validation",
                "finished_at": now_iso(),
            }

    report["finished_at"] = now_iso()
    upload_results = [item for item in [report.get("single"), *report["batch"]] if item]
    report["summary"] = {
        "single_success": bool(report["single"] and report["single"].get("success")),
        "upload_successes": sum(1 for item in upload_results if item.get("success")),
        "upload_total": len(upload_results),
        "batch_successes": sum(1 for item in report["batch"] if item.get("success")),
        "batch_total": len(report["batch"]),
        "syphon_success": bool(report.get("syphon") and report["syphon"].get("success")),
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("production validation finished; report=%s", report_path)
    print(json.dumps(report["summary"], indent=2))
    print(str(report_path))
    uploads_ok = not upload_results or report["summary"]["upload_successes"] == report["summary"]["upload_total"]
    syphon_ok = report["syphon"] is None or bool(report["syphon"].get("success"))
    return 0 if uploads_ok and syphon_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

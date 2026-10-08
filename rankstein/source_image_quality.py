"""Bounded, local-only text gate for scraped remaster source images.

OCR output is ephemeral: only counts, an assessment reason, and a file hash
leave this module. A source is not considered safe when OCR is unavailable.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

SOURCE_QUALITY_POLICY = "text_free_pinterest_source"
SOURCE_QUALITY_VERSION = 1
OCR_TIMEOUT_SECONDS = 20.0
OCR_BACKEND = "windows-media-ocr"
_OCR_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/dev/read_source_image_text.ps1"
_MAX_OCR_CHARACTERS = 65536
_MAX_SOURCE_BYTES = 32 * 1024 * 1024
_WORDS = re.compile(r"[^\W\d_]+", re.UNICODE)
_BRAND_MARK = re.compile(r"(?:https?://|www\.|\.(?:com|net|org|es|io|co)\b|[@©®™])", re.IGNORECASE)
_SHORT_RECIPE_WORDS = {"pan", "sal", "pie", "mix", "egg", "cup", "oil", "g", "kg", "ml"}


def _read_windows_text(path: str, *, timeout: float) -> dict[str, Any]:
    """Capture local OCR in memory without logging its output or error text."""

    executable = shutil.which("powershell.exe") if sys.platform == "win32" else None
    if not executable or not _OCR_SCRIPT.is_file():
        return {"available": False, "reason": "ocr_unavailable"}
    try:
        completed = subprocess.run(
            [
                executable,
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(_OCR_SCRIPT),
                "-ImagePath",
                path,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return {"available": False, "reason": "ocr_timeout"}
    except OSError:
        return {"available": False, "reason": "ocr_unavailable"}
    if completed.returncode != 0 or len(completed.stdout) > _MAX_OCR_CHARACTERS * 2:
        return {"available": False, "reason": "ocr_unavailable"}
    try:
        payload = json.loads(completed.stdout.lstrip("\ufeff"))
    except (TypeError, ValueError):
        return {"available": False, "reason": "ocr_invalid_response"}
    if not isinstance(payload, dict) or payload.get("available") is not True:
        return {"available": False, "reason": "ocr_unavailable"}
    if not isinstance(payload.get("text"), str):
        return {"available": False, "reason": "ocr_invalid_response"}
    return payload


def _text_assessment(text: str) -> dict[str, Any]:
    """Allow only a small amount of short OCR noise, never recipe/brand copy."""

    words = _WORDS.findall(text)
    significant = [word for word in words if len(word) >= 4]
    character_count = sum(len(word) for word in words)
    has_brand = bool(_BRAND_MARK.search(text))
    has_recipe = any(word.casefold() in _SHORT_RECIPE_WORDS for word in words)
    meaningful = (
        bool(significant)
        or has_brand
        or has_recipe
        or len(words) > 2
        or character_count > 6
        or sum(character.isdigit() for character in text) > 4
        or len(text) > _MAX_OCR_CHARACTERS
    )
    return {
        "accepted": not meaningful,
        "reason": "embedded_text" if meaningful else "text_free_or_tiny_ocr_noise",
        "word_count": len(words),
        "significant_word_count": len(significant),
        "character_count": character_count,
    }


def _base_assessment(*, source_hash: str = "") -> dict[str, Any]:
    return {
        "accepted": False,
        "policy": SOURCE_QUALITY_POLICY,
        "version": SOURCE_QUALITY_VERSION,
        "backend": OCR_BACKEND,
        "reason": "ocr_unavailable",
        "word_count": 0,
        "significant_word_count": 0,
        "character_count": 0,
        "source_hash": source_hash,
    }


@lru_cache(maxsize=256)
def _assess_cached(path: str, modified_ns: int, size: int, timeout: float) -> dict[str, Any]:
    source = Path(path)
    try:
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        assessment = _base_assessment(source_hash=digest.hexdigest())
        payload = _read_windows_text(path, timeout=timeout)
        # Never retain raw OCR text in the cache, return value, or telemetry.
        if payload.get("available") is True and isinstance(payload.get("text"), str):
            assessment.update(_text_assessment(payload["text"]))
        else:
            reason = payload.get("reason")
            assessment["reason"] = (
                reason
                if reason in {"ocr_timeout", "ocr_unavailable", "ocr_invalid_response"}
                else "ocr_unavailable"
            )
        current = source.stat()
        if current.st_mtime_ns != modified_ns or current.st_size != size:
            assessment.update(accepted=False, reason="source_changed_during_assessment")
        return assessment
    except OSError:
        assessment = _base_assessment()
        assessment["reason"] = "source_unreadable"
        return assessment


def assess_source_image(path: str | Path, *, timeout: float = OCR_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Return sanitized quality evidence, cached by source path/mtime/size.

    The hard subprocess deadline is never greater than twenty seconds. A
    missing file, unreadable file, unsupported host, timeout, or OCR failure is
    a blocked source, not evidence that an image is text-free.
    """

    try:
        source = Path(path).resolve(strict=True)
        stat = source.stat()
        if not source.is_file() or stat.st_size <= 0:
            raise OSError("not an image file")
        if stat.st_size > _MAX_SOURCE_BYTES:
            assessment = _base_assessment()
            assessment["reason"] = "source_too_large"
            return assessment
        bounded_timeout = min(OCR_TIMEOUT_SECONDS, max(0.1, float(timeout)))
        return dict(_assess_cached(str(source), stat.st_mtime_ns, stat.st_size, bounded_timeout))
    except (OSError, TypeError, ValueError):
        assessment = _base_assessment()
        assessment["reason"] = "source_unreadable"
        return assessment

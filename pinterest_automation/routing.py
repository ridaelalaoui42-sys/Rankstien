"""Deterministic domain-to-account routing for bounded Pinterest fanout."""

from __future__ import annotations

import hashlib
import json
import os

from .config import get_config


def _positive_int_env(name: str, default: int = 0) -> int:
    try:
        return max(0, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def account_cohort(domain_handle: str, *, config=None) -> list[str]:
    config = config or get_config()
    configured = sorted(config.accounts)
    if not configured:
        return []

    raw = os.environ.get("PINTEREST_DOMAIN_ACCOUNT_MAP", "").strip()
    if raw:
        try:
            mapping = json.loads(raw)
        except (TypeError, ValueError):
            mapping = {}
        requested = mapping.get(domain_handle) if isinstance(mapping, dict) else None
        if isinstance(requested, list):
            cohort = [str(handle) for handle in requested if str(handle) in config.accounts]
            if cohort:
                return list(dict.fromkeys(cohort))
    return configured


def select_upload_account(domain_handle: str, asset_key: str, *, config=None) -> str | None:
    cohort = account_cohort(domain_handle, config=config)
    if not cohort:
        return None
    digest = hashlib.sha256(f"{domain_handle}:{asset_key}".encode()).digest()
    return cohort[int.from_bytes(digest[:4], "big") % len(cohort)]


def cross_save_targets(domain_handle: str, source_handle: str, *, config=None) -> list[str]:
    limit = _positive_int_env("PINTEREST_CROSS_SAVE_LIMIT", 0)
    if limit == 0:
        return []
    cohort = [handle for handle in account_cohort(domain_handle, config=config) if handle != source_handle]
    return cohort[:limit]

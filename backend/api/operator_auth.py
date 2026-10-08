"""Loopback-only operator access with same-origin and explicit mutation checks."""

from __future__ import annotations

import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

CSRF_TOKEN = secrets.token_urlsafe(32)


def require_local(request: Request) -> None:
    if not request.client or request.client.host not in {"127.0.0.1", "::1"}:
        raise HTTPException(403, "Operator access is local only")
    if request.url.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise HTTPException(403, "Invalid operator host")
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Cross-origin operator access denied")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site operator access denied")
    # Explicitly parse the Host header as well to reject DNS-rebinding requests.
    if urlsplit("http://" + request.headers.get("host", "")).hostname != request.url.hostname:
        raise HTTPException(403, "Invalid operator host")


def require_admin(request: Request) -> None:
    require_local(request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        token = request.headers.get("x-rankstein-csrf", "")
        if not secrets.compare_digest(token, CSRF_TOKEN):
            raise HTTPException(403, "Missing or expired operator session; reload the dashboard")

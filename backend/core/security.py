"""RankStein — Security Layer
API key validation, JWT tokens, rate limiting.
"""

from __future__ import annotations

import time

from fastapi import HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.core.config import get_settings

limiter = Limiter(key_func=get_remote_address)
api_key_header = APIKeyHeader(name="X-RankStein-Key", auto_error=False)


async def get_api_key(api_key: str = Security(api_key_header)) -> str:
    """Validate API key. Raises 401/403 if missing or invalid."""
    settings = get_settings()
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing X-RankStein-Key header")
    if api_key != settings.rankstein_secret:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key


async def get_api_key_optional(api_key: str = Security(api_key_header)) -> str | None:
    """Optional API key validation. Returns None if not provided."""
    if not api_key:
        return None
    try:
        return await get_api_key(api_key)
    except HTTPException:
        return None


def generate_jwt_token(payload: dict, expires_hours: int = 24) -> str:
    """Generate JWT token with expiry."""
    import jwt

    settings = get_settings()
    to_encode = payload.copy()
    now = int(time.time())
    to_encode.update({"iat": now, "exp": now + (expires_hours * 3600)})
    return jwt.encode(to_encode, settings.rankstein_secret, algorithm="HS256")


def decode_jwt_token(token: str) -> dict:
    """Decode and validate JWT token."""
    import jwt
    from jwt import ExpiredSignatureError, InvalidTokenError

    settings = get_settings()
    try:
        return jwt.decode(token, settings.rankstein_secret, algorithms=["HS256"])
    except ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

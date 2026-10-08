from __future__ import annotations

import pytest

from rankstein_mcp_server import _supabase_request_headers


@pytest.mark.unit
def test_supabase_opaque_secret_uses_apikey_header_only() -> None:
    headers = _supabase_request_headers(
        "sb_secret_test_value",
        **{"Content-Type": "application/json"},
    )

    assert headers == {
        "apikey": "sb_secret_test_value",
        "Content-Type": "application/json",
    }


@pytest.mark.unit
def test_supabase_legacy_jwt_keeps_bearer_authorization() -> None:
    key = "header.payload.signature"

    headers = _supabase_request_headers(key, Prefer="return=minimal")

    assert headers == {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Prefer": "return=minimal",
    }

from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests

import rankstein_mcp_server as mcp


class _Secret:
    def get_secret_value(self) -> str:
        return "test-service-key"


class _Response:
    def __init__(self, status_code: int, text: str = "", content: bytes = b"") -> None:
        self.status_code = status_code
        self.text = text
        self.content = content


class _Session:
    def __init__(self, post_results: list[object], get_results: list[object] | None = None) -> None:
        self.post_results = list(post_results)
        self.get_results = list(get_results or [])
        self.post_bodies: list[bytes] = []
        self.post_calls: list[dict] = []
        self.get_calls: list[dict] = []

    def post(self, url: str, **kwargs):
        self.post_calls.append({"url": url, **kwargs})
        self.post_bodies.append(kwargs["data"].read())
        result = self.post_results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def get(self, url: str, **kwargs):
        self.get_calls.append({"url": url, **kwargs})
        result = self.get_results.pop(0) if self.get_results else _Response(404)
        if isinstance(result, BaseException):
            raise result
        return result


@pytest.fixture
def upload_context(monkeypatch: pytest.MonkeyPatch, tmp_path):
    image_path = tmp_path / "hero.png"
    image_bytes = b"complete-image-body"
    image_path.write_bytes(image_bytes)
    domain = SimpleNamespace(
        handle="recetadolce",
        supabase_url="https://example.supabase.co",
        supabase_service_role_key=_Secret(),
    )
    registry = SimpleNamespace(get=lambda _handle: domain)
    monkeypatch.setattr(mcp, "get_registry", lambda: registry)
    monkeypatch.setattr(mcp, "BUCKET", "recipe-images")
    sleeps: list[float] = []
    monkeypatch.setattr(mcp.time, "sleep", sleeps.append)
    return image_path, image_bytes, sleeps


@pytest.mark.unit
def test_upload_reopens_body_after_ssl_eof_then_succeeds(
    monkeypatch: pytest.MonkeyPatch, upload_context
) -> None:
    image_path, image_bytes, sleeps = upload_context
    session = _Session(
        [requests.exceptions.SSLError("EOF occurred"), _Response(201)],
        [_Response(404)],
    )
    monkeypatch.setattr(mcp, "get_supabase_session", lambda: session)

    result = mcp.upload_image_to_supabase(str(image_path), "heroes/recipe.png", "recetadolce")

    assert result == {
        "success": True,
        "public_url": (
            "https://example.supabase.co/storage/v1/object/public/recipe-images/heroes/recipe.png"
        ),
        "attempts": 2,
    }
    assert session.post_bodies == [image_bytes, image_bytes]
    assert session.post_calls[0]["timeout"] == (10, 30)
    assert session.post_calls[1]["timeout"] == (10, 30)
    assert session.post_calls[0]["headers"]["x-upsert"] == "true"
    assert sleeps == [0.25]


@pytest.mark.unit
def test_upload_accepts_public_object_after_ambiguous_ssl_failure(
    monkeypatch: pytest.MonkeyPatch, upload_context
) -> None:
    image_path, image_bytes, sleeps = upload_context
    session = _Session(
        [requests.exceptions.SSLError("response lost after commit")],
        [_Response(200, content=image_bytes)],
    )
    monkeypatch.setattr(mcp, "get_supabase_session", lambda: session)

    result = mcp.upload_image_to_supabase(str(image_path), "heroes/recipe.png", "recetadolce")

    public_url = "https://example.supabase.co/storage/v1/object/public/recipe-images/heroes/recipe.png"
    assert result == {
        "success": True,
        "public_url": public_url,
        "attempts": 1,
        "verified_via": "public_url_content_match",
    }
    assert len(session.post_calls) == 1
    assert session.get_calls == [{"url": public_url, "timeout": (10, 30)}]
    assert sleeps == []


@pytest.mark.unit
def test_upload_retries_when_public_url_contains_stale_object(
    monkeypatch: pytest.MonkeyPatch, upload_context
) -> None:
    image_path, image_bytes, sleeps = upload_context
    session = _Session(
        [requests.exceptions.SSLError("response lost after commit"), _Response(201)],
        [_Response(200, content=b"stale-prior-image")],
    )
    monkeypatch.setattr(mcp, "get_supabase_session", lambda: session)

    result = mcp.upload_image_to_supabase(str(image_path), "heroes/recipe.png", "recetadolce")

    assert result["success"] is True
    assert result["attempts"] == 2
    assert session.post_bodies == [image_bytes, image_bytes]
    assert sleeps == [0.25]


@pytest.mark.unit
def test_upload_exhausts_three_ssl_attempts(monkeypatch: pytest.MonkeyPatch, upload_context) -> None:
    image_path, image_bytes, sleeps = upload_context
    session = _Session(
        [
            requests.exceptions.SSLError("EOF one"),
            requests.exceptions.SSLError("EOF two"),
            requests.exceptions.SSLError("EOF three"),
        ],
        [_Response(404), _Response(404), _Response(404)],
    )
    monkeypatch.setattr(mcp, "get_supabase_session", lambda: session)

    result = mcp.upload_image_to_supabase(str(image_path), "heroes/recipe.png", "recetadolce")

    assert result == {"success": False, "error": "EOF three", "attempts": 3}
    assert session.post_bodies == [image_bytes, image_bytes, image_bytes]
    assert len(session.get_calls) == 3
    assert sleeps == [0.25, 0.5]


@pytest.mark.unit
def test_upload_fails_immediately_on_forbidden(monkeypatch: pytest.MonkeyPatch, upload_context) -> None:
    image_path, _image_bytes, sleeps = upload_context
    session = _Session([_Response(403, "forbidden")])
    monkeypatch.setattr(mcp, "get_supabase_session", lambda: session)

    result = mcp.upload_image_to_supabase(str(image_path), "heroes/recipe.png", "recetadolce")

    assert result == {
        "success": False,
        "status": 403,
        "error": "forbidden",
        "attempts": 1,
    }
    assert len(session.post_calls) == 1
    assert session.get_calls == []
    assert sleeps == []

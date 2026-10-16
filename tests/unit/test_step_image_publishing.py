from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

import rankstein_mcp_server as mcp

pytestmark = pytest.mark.unit

STEP_IMAGES = [
    {
        "step_number": 1,
        "image_url": "https://example.supabase.co/storage/v1/object/public/images/paella-step-1.jpg",
        "text": "Dorar el pollo",
        "source_url": "https://example.com/paella",
    },
    {
        "step_number": 2,
        "image_url": "https://example.supabase.co/storage/v1/object/public/images/paella-step-2.jpg",
        "text": "Añadir las verduras",
    },
]


class _Response:
    def __init__(self, status_code: int = 204, data: object = None, text: str = "") -> None:
        self.status_code = status_code
        self.data = data
        self.text = text

    def json(self):
        return self.data


def _missing_column(column: str) -> _Response:
    return _Response(
        400,
        text=json.dumps(
            {
                "code": "PGRST204",
                "message": f"Could not find the '{column}' column of 'posts' in the schema cache",
            }
        ),
    )


class _Session:
    def __init__(self, exists: bool, responses: list[_Response] | None = None) -> None:
        self.exists = exists
        self.responses = list(responses or [_Response()])
        self.get_calls: list[str] = []
        self.writes: list[dict] = []

    def get(self, url: str, **kwargs) -> _Response:
        self.get_calls.append(url)
        return _Response(200, [{"slug": "paella-de-pollo"}] if self.exists else [])

    def _write(self, method: str, url: str, kwargs: dict) -> _Response:
        self.writes.append({"method": method, "url": url, "payload": deepcopy(kwargs["json"])})
        return self.responses.pop(0)

    def post(self, url: str, **kwargs) -> _Response:
        return self._write("POST", url, kwargs)

    def patch(self, url: str, **kwargs) -> _Response:
        return self._write("PATCH", url, kwargs)


@pytest.fixture
def publish_context(monkeypatch: pytest.MonkeyPatch) -> dict:
    domain = SimpleNamespace(
        handle="recetadolce",
        domain="example.com",
        display_name="RecetaDolce",
        categories=["Arroces"],
        supabase_url="https://example.supabase.co",
        supabase_service_role_key=SecretStr("test-service-key"),
    )
    monkeypatch.setattr(mcp, "get_registry", lambda: SimpleNamespace(get=lambda _handle: domain))
    monkeypatch.setattr(
        mcp,
        "assign_article_category",
        lambda **_kwargs: SimpleNamespace(category="Arroces", category_id="category-arroces"),
    )
    return {
        "title": "Paella de pollo con verduras",
        "slug": "paella-de-pollo",
        "content": "Dora el pollo y añade las verduras antes de incorporar el arroz.",
        "excerpt": "Una paella de pollo casera con verduras y arroz cocido en caldo.",
        "category": "Arroces",
        "featured_image_url": "https://example.supabase.co/storage/v1/object/public/images/paella.jpg",
        "domain_handle": "recetadolce",
        "auto_create_pinterest_campaign": False,
    }


@pytest.mark.parametrize("exists", [False, True], ids=["insert", "update"])
@pytest.mark.parametrize("serialized", [False, True], ids=["array", "json"])
def test_publish_persists_step_images_as_jsonb_array(
    monkeypatch: pytest.MonkeyPatch, publish_context: dict, exists: bool, serialized: bool
) -> None:
    session = _Session(exists)
    monkeypatch.setattr(mcp, "get_supabase_session", lambda: session)
    steps = json.dumps(STEP_IMAGES, ensure_ascii=False) if serialized else deepcopy(STEP_IMAGES)

    result = mcp.publish_article_to_supabase(**publish_context, step_images=steps)

    assert result["success"] is True
    assert result["action"] == ("updated" if exists else "created")
    assert session.writes[0]["method"] == ("PATCH" if exists else "POST")
    assert session.writes[0]["payload"]["step_images"] == STEP_IMAGES
    assert isinstance(session.writes[0]["payload"]["step_images"], list)
    assert steps == (json.dumps(STEP_IMAGES, ensure_ascii=False) if serialized else STEP_IMAGES)


@pytest.mark.parametrize("explicit_none", [False, True], ids=["omitted", "none"])
def test_update_preserves_images_when_step_images_not_supplied(
    monkeypatch: pytest.MonkeyPatch, publish_context: dict, explicit_none: bool
) -> None:
    session = _Session(exists=True)
    monkeypatch.setattr(mcp, "get_supabase_session", lambda: session)
    extra = {"step_images": None} if explicit_none else {}

    result = mcp.publish_article_to_supabase(**publish_context, **extra)

    assert result["success"] is True
    assert "step_images" not in session.writes[0]["payload"]


@pytest.mark.parametrize("steps", [[], "[]"], ids=["array", "json"])
def test_update_explicit_empty_array_clears_images(
    monkeypatch: pytest.MonkeyPatch, publish_context: dict, steps
) -> None:
    session = _Session(exists=True)
    monkeypatch.setattr(mcp, "get_supabase_session", lambda: session)

    result = mcp.publish_article_to_supabase(**publish_context, step_images=steps)

    assert result["success"] is True
    assert session.writes[0]["payload"]["step_images"] == []


@pytest.mark.parametrize(
    "steps",
    [
        "not JSON",
        "{}",
        "null",
        {},
        1,
        "[1]",
        ["https://example.com/step.jpg"],
        [{}],
        [{"image_url": "   "}],
        [{"image_url": None}],
        [{"image_url": "https://example.com/step.jpg", "step_number": 0}],
        [{"image_url": "https://example.com/step.jpg", "step_number": True}],
        [{"image_url": "https://example.com/step.jpg", "step_number": "1"}],
    ],
)
def test_malformed_step_images_are_rejected_before_supabase_requests(
    monkeypatch: pytest.MonkeyPatch, publish_context: dict, steps
) -> None:
    session = _Session(exists=True)
    monkeypatch.setattr(mcp, "get_supabase_session", lambda: session)

    result = mcp.publish_article_to_supabase(**publish_context, step_images=steps)

    assert result["success"] is False
    assert "Invalid step_images" in result["error"]
    assert session.get_calls == []
    assert session.writes == []


@pytest.mark.parametrize("exists", [False, True], ids=["insert", "update"])
def test_step_images_survive_retries_for_unrelated_legacy_columns(
    monkeypatch: pytest.MonkeyPatch, publish_context: dict, exists: bool
) -> None:
    session = _Session(exists, [_missing_column("hero_image"), _missing_column("cooking_time"), _Response()])
    monkeypatch.setattr(mcp, "get_supabase_session", lambda: session)

    result = mcp.publish_article_to_supabase(**publish_context, step_images=STEP_IMAGES)

    assert result["success"] is True
    assert result["omitted_columns"] == ["hero_image", "cooking_time"]
    assert len(session.writes) == 3
    assert all(write["payload"]["step_images"] == STEP_IMAGES for write in session.writes)
    assert all(write["method"] == ("PATCH" if exists else "POST") for write in session.writes)
    assert "hero_image" not in session.writes[-1]["payload"]
    assert "cooking_time" not in session.writes[-1]["payload"]


@pytest.mark.parametrize("exists", [False, True], ids=["insert", "update"])
def test_missing_step_images_column_fails_without_dropping_supplied_images(
    monkeypatch: pytest.MonkeyPatch, publish_context: dict, exists: bool
) -> None:
    session = _Session(exists, [_missing_column("step_images")])
    monkeypatch.setattr(mcp, "get_supabase_session", lambda: session)

    result = mcp.publish_article_to_supabase(**publish_context, step_images=STEP_IMAGES)

    assert result["success"] is False
    assert "posts.step_images JSONB is required" in result["error"]
    assert "step_images" in result["payload_sent"]
    assert len(session.writes) == 1
    assert session.writes[0]["payload"]["step_images"] == STEP_IMAGES


def test_empty_images_preserve_compatibility_with_legacy_schema(
    monkeypatch: pytest.MonkeyPatch, publish_context: dict
) -> None:
    session = _Session(False, [_missing_column("step_images"), _Response()])
    monkeypatch.setattr(mcp, "get_supabase_session", lambda: session)

    result = mcp.publish_article_to_supabase(**publish_context, step_images=[])

    assert result["success"] is True
    assert result["omitted_columns"] == ["step_images"]
    assert "step_images" not in session.writes[-1]["payload"]


@pytest.mark.parametrize("serialized", [False, True], ids=["array", "json"])
def test_publish_from_payload_forwards_step_images(monkeypatch: pytest.MonkeyPatch, serialized: bool) -> None:
    captured: dict = {}

    def publish(**kwargs):
        captured.update(kwargs)
        return {"success": True}

    monkeypatch.setattr(mcp, "publish_article_to_supabase", publish)
    steps = json.dumps(STEP_IMAGES) if serialized else STEP_IMAGES

    result = mcp.publish_from_payload(json.dumps({"step_images": steps}))

    assert result["success"] is True
    assert captured["step_images"] == steps


@pytest.mark.parametrize("payload", [{}, {"step_images": None}, {"step_images": []}])
def test_publish_from_payload_preserves_absent_and_explicit_empty_semantics(
    monkeypatch: pytest.MonkeyPatch, payload: dict
) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        mcp, "publish_article_to_supabase", lambda **kwargs: captured.update(kwargs) or {"success": True}
    )

    assert mcp.publish_from_payload(json.dumps(payload))["success"] is True
    assert captured["step_images"] == payload.get("step_images")

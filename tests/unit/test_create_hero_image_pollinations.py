"""Tests for create_hero_image_pollinations — the keyless Pollinations.ai
fallback used when Antigravity's native image generation is unavailable.

Real HTTP is mocked; we only verify request shape, persistence, and the same
dimension/byte gates the other ingestion tools enforce.
"""

from __future__ import annotations

import importlib.util as _u
import io
import sys
from pathlib import Path

import pytest
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

_spec = _u.spec_from_file_location("rms", PROJECT_ROOT / "rankstein_mcp_server.py")
rms = _u.module_from_spec(_spec)
_spec.loader.exec_module(rms)


def _make_jpeg(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(220, 90, 30)).save(buf, "JPEG", quality=90)
    return buf.getvalue()


class _StubResponse:
    def __init__(self, content: bytes, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"{self.status_code}")


@pytest.fixture(autouse=True)
def _redirect_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(rms, "OUTPUT_DIR", out)


@pytest.mark.unit
class TestPollinationsFallback:
    def test_happy_path_persists_jpeg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        def fake_get(url, params=None, timeout=None, allow_redirects=None):
            captured["url"] = url
            captured["params"] = params
            return _StubResponse(_make_jpeg(1920, 1280))

        monkeypatch.setattr(rms.requests, "get", fake_get)

        result = rms.create_hero_image_pollinations(
            "editorial paella with saffron",
            "paella-marinera",
        )
        assert result["success"] is True
        assert result["format"] == "jpg"
        assert result["width"] == 1920 and result["height"] == 1280
        assert result["output_path"].endswith("paella-marinera-hero.jpg")
        assert Path(result["output_path"]).exists()
        # Prompt was URL-encoded into the path
        assert captured["url"].startswith("https://image.pollinations.ai/prompt/")
        assert "paella" in captured["url"]
        assert captured["params"]["width"] == 1920
        assert captured["params"]["height"] == 1280
        assert captured["params"]["nologo"] == "true"
        assert captured["params"]["model"] == "flux"
        assert captured["params"]["enhance"] == "true"

    def test_empty_prompt_rejected(self) -> None:
        result = rms.create_hero_image_pollinations("   ", "x")
        assert result["success"] is False
        assert "empty" in result["error"].lower()

    def test_http_error_returned_cleanly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import requests as _r

        def fake_get(*a, **kw):
            raise _r.ConnectionError("boom")

        monkeypatch.setattr(rms.requests, "get", fake_get)
        result = rms.create_hero_image_pollinations("x", "slug")
        assert result["success"] is False
        assert "Pollinations HTTP error" in result["error"]

    def test_too_small_payload_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            rms.requests,
            "get",
            lambda *a, **kw: _StubResponse(b"short"),
        )
        result = rms.create_hero_image_pollinations("x", "slug")
        assert result["success"] is False
        assert "small" in result["error"].lower()

    def test_truly_small_source_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # 400x300 noisy JPEG — below the 800x500 pre-upscale floor.
        # Use noise so JPEG compression doesn't shrink it below the byte floor.
        import os as _os

        buf = io.BytesIO()
        noise = Image.frombytes("RGB", (400, 300), _os.urandom(400 * 300 * 3))
        noise.save(buf, "JPEG", quality=85)
        payload = buf.getvalue()
        assert len(payload) >= 5000  # sanity for the test premise

        monkeypatch.setattr(
            rms.requests,
            "get",
            lambda *a, **kw: _StubResponse(payload),
        )
        result = rms.create_hero_image_pollinations("x", "slug", width=400, height=300)
        assert result["success"] is False
        assert "too small" in result["error"].lower() or "source too small" in result["error"].lower()
        # File should be cleaned up so it cannot leak downstream
        assert list(rms.OUTPUT_DIR.glob("slug*")) == []

    def test_pollinations_subsize_is_lanczos_upscaled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Simulate Pollinations free cap: returns 940x627 even though we asked for 1920x1280
        payload = _make_jpeg(940, 627)
        monkeypatch.setattr(
            rms.requests,
            "get",
            lambda *a, **kw: _StubResponse(payload),
        )
        result = rms.create_hero_image_pollinations(
            "high quality food photo",
            "upscaled-paella",
            "hero",
            width=1920,
            height=1280,
        )
        assert result["success"] is True, result.get("error")
        assert result["upscaled"] is True
        assert result["raw_width"] == 940 and result["raw_height"] == 627
        assert result["width"] == 1920 and result["height"] == 1280
        assert result["format"] == "jpg"

    def test_upscale_disabled_passes_native_when_above_floor(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 1280x800 native — exactly at floor, should pass without upscale
        payload = _make_jpeg(1280, 800)
        monkeypatch.setattr(
            rms.requests,
            "get",
            lambda *a, **kw: _StubResponse(payload),
        )
        result = rms.create_hero_image_pollinations(
            "x",
            "native-floor",
            "hero",
            width=1280,
            height=800,
            upscale_if_smaller=False,
        )
        assert result["success"] is True
        assert result["upscaled"] is False
        assert result["width"] == 1280 and result["height"] == 800

"""Tests for save_image_from_base64 — the entry point Antigravity (and any
other agent that generates images natively) uses to persist hero images.

Coverage:
  - Raw base64 string (most common — Antigravity returns this)
  - Data URL ("data:image/png;base64,...")
  - Whitespace / newlines stripped
  - Format auto-detection from magic bytes (PNG saved as .png, JPEG as .jpg, etc.)
  - Empty / malformed inputs return success=False, no crash
  - Dimension gate (rejects images smaller than 800x600)
  - Configurable min_bytes floor

Tests pass ``min_bytes=50`` so the tiny fixtures used here clear the
production-default 5KB floor; production callers still get the default 5KB gate.
"""

from __future__ import annotations

import base64
import importlib.util as _u
import io
import sys
from pathlib import Path

import pytest
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

# rankstein_mcp_server is a flat .py file, not a package — load via spec
_spec = _u.spec_from_file_location("rms", PROJECT_ROOT / "rankstein_mcp_server.py")
rms = _u.module_from_spec(_spec)
_spec.loader.exec_module(rms)


def _make_png(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def _make_jpeg(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(30, 150, 30)).save(buf, "JPEG", quality=90)
    return buf.getvalue()


# Real-dimension fixtures (≥1280x800, the production gate).
HERO_PNG_BYTES = _make_png(1280, 800)
HERO_JPEG_BYTES = _make_jpeg(1600, 1066)
# Tiny fixtures used to exercise non-dimension code paths.
TINY_PNG_BYTES = _make_png(8, 8)
TINY_JPEG_BYTES = _make_jpeg(8, 8)


@pytest.fixture(autouse=True)
def _redirect_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Send saved images into tmp_path instead of nanobanana-output/."""
    monkeypatch.setattr(rms, "OUTPUT_DIR", tmp_path)


@pytest.mark.unit
class TestRawBase64:
    def test_png_is_saved_with_png_extension(self) -> None:
        b64 = base64.b64encode(HERO_PNG_BYTES).decode()
        result = rms.save_image_from_base64(b64, "test-slug", "hero", min_bytes=50)
        assert result["success"] is True
        assert result["format"] == "png"
        assert result["output_path"].endswith("test-slug-hero.png")
        assert Path(result["output_path"]).exists()
        assert result["width"] == 1280 and result["height"] == 800

    def test_jpeg_is_saved_with_jpg_extension(self) -> None:
        b64 = base64.b64encode(HERO_JPEG_BYTES).decode()
        result = rms.save_image_from_base64(b64, "paella", "hero", min_bytes=50)
        assert result["success"] is True
        assert result["format"] == "jpg"
        assert result["output_path"].endswith("paella-hero.jpg")

    def test_size_bytes_returned(self) -> None:
        b64 = base64.b64encode(HERO_PNG_BYTES).decode()
        result = rms.save_image_from_base64(b64, "x", min_bytes=50)
        assert result["size_bytes"] == len(HERO_PNG_BYTES)


@pytest.mark.unit
class TestDataUrl:
    def test_data_url_with_png_mime(self) -> None:
        b64 = base64.b64encode(HERO_PNG_BYTES).decode()
        data_url = f"data:image/png;base64,{b64}"
        result = rms.save_image_from_base64(data_url, "data-url-test", min_bytes=50)
        assert result["success"] is True
        assert result["format"] == "png"

    def test_data_url_with_jpeg_mime(self) -> None:
        b64 = base64.b64encode(HERO_JPEG_BYTES).decode()
        data_url = f"data:image/jpeg;base64,{b64}"
        result = rms.save_image_from_base64(data_url, "data-url-jpeg", min_bytes=50)
        assert result["success"] is True
        assert result["format"] == "jpg"


@pytest.mark.unit
class TestWhitespace:
    def test_newlines_stripped(self) -> None:
        b64 = base64.b64encode(HERO_PNG_BYTES).decode()
        wrapped = "\n".join(b64[i : i + 64] for i in range(0, len(b64), 64))
        result = rms.save_image_from_base64(wrapped, "wrapped", min_bytes=50)
        assert result["success"] is True

    def test_leading_trailing_whitespace_stripped(self) -> None:
        b64 = base64.b64encode(HERO_PNG_BYTES).decode()
        result = rms.save_image_from_base64(f"  \n  {b64}  \n  ", "padded", min_bytes=50)
        assert result["success"] is True


@pytest.mark.unit
class TestFailureModes:
    def test_empty_string_returns_failure(self) -> None:
        result = rms.save_image_from_base64("", "x")
        assert result["success"] is False
        assert "empty" in result["error"].lower()

    def test_none_returns_failure(self) -> None:
        result = rms.save_image_from_base64(None, "x")  # type: ignore[arg-type]
        assert result["success"] is False

    def test_malformed_data_url_no_comma(self) -> None:
        result = rms.save_image_from_base64("data:image/png;base64", "x")
        assert result["success"] is False
        assert "data URL" in result["error"] or "no comma" in result["error"].lower()

    def test_invalid_base64_returns_failure(self) -> None:
        result = rms.save_image_from_base64("!!!not-base64!!!", "x")
        assert result["success"] is False

    def test_too_small_payload_rejected(self) -> None:
        b64 = base64.b64encode(b"hello").decode()
        result = rms.save_image_from_base64(b64, "tiny")
        assert result["success"] is False
        assert "small" in result["error"].lower()

    def test_default_min_bytes_rejects_85b_stub(self) -> None:
        # The 8x8 PNG fixture is ~85 B — production default (5KB) must reject it
        b64 = base64.b64encode(TINY_PNG_BYTES).decode()
        result = rms.save_image_from_base64(b64, "stub-attack")
        assert result["success"] is False
        assert "small" in result["error"].lower()


@pytest.mark.unit
class TestDimensionGate:
    def test_8x8_jpeg_rejected_even_with_low_min_bytes(self, tmp_path: Path) -> None:
        # Bypass the byte-count floor; the dimension gate is the second guard.
        b64 = base64.b64encode(TINY_JPEG_BYTES).decode()
        result = rms.save_image_from_base64(b64, "shrimp", min_bytes=50)
        assert result["success"] is False
        assert "too small" in result["error"].lower()
        # File should be deleted so it cannot leak downstream
        leaked = list(tmp_path.glob("shrimp*"))
        assert leaked == [], f"orphan file(s) left behind: {leaked}"

    def test_at_floor_png_passes_dimension_gate(self) -> None:
        b64 = base64.b64encode(HERO_PNG_BYTES).decode()
        result = rms.save_image_from_base64(b64, "ok", min_bytes=50)
        assert result["success"] is True
        assert result["width"] >= 1280 and result["height"] >= 800


@pytest.mark.unit
class TestFormatDetection:
    def test_detect_image_extension_helper(self) -> None:
        assert rms._detect_image_extension(HERO_PNG_BYTES) == "png"
        assert rms._detect_image_extension(HERO_JPEG_BYTES) == "jpg"
        assert rms._detect_image_extension(b"GIF89a" + b"x" * 100) == "gif"
        assert rms._detect_image_extension(b"\x00\x01\x02") == "jpg"  # default

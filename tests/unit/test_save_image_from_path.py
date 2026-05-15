"""Tests for save_image_from_path — the path-ingestion entry point used when
Antigravity's native image tool returns a file path instead of inline base64.

Coverage:
  - PNG-on-disk → JPEG conversion path (default convert_to_jpeg=True)
  - JPEG passthrough (no conversion)
  - convert_to_jpeg=False keeps PNG as PNG
  - Missing source path returns success=False
  - Dimension gate (rejects images smaller than 800x600)
  - Source file is left in place (not deleted)
"""

from __future__ import annotations

import importlib.util as _u
import sys
from pathlib import Path

import pytest
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

_spec = _u.spec_from_file_location("rms", PROJECT_ROOT / "rankstein_mcp_server.py")
rms = _u.module_from_spec(_spec)
_spec.loader.exec_module(rms)


def _write_png(path: Path, width: int, height: int) -> None:
    Image.new("RGBA", (width, height), color=(200, 30, 30, 255)).save(path, "PNG")


def _write_jpeg(path: Path, width: int, height: int) -> None:
    Image.new("RGB", (width, height), color=(30, 150, 30)).save(path, "JPEG", quality=90)


@pytest.fixture(autouse=True)
def _redirect_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(rms, "OUTPUT_DIR", out)


@pytest.mark.unit
class TestPngToJpegConversion:
    def test_png_is_converted_to_jpeg_by_default(self, tmp_path: Path) -> None:
        src = tmp_path / "native_gen.png"
        _write_png(src, 1920, 1280)
        result = rms.save_image_from_path(str(src), "paella", "hero", min_bytes=50)
        assert result["success"] is True
        assert result["format"] == "jpg"
        assert result["output_path"].endswith("paella-hero.jpg")
        assert Path(result["output_path"]).exists()
        assert result["width"] == 1920 and result["height"] == 1280
        # Source file must remain in place
        assert src.exists()

    def test_jpeg_passthrough(self, tmp_path: Path) -> None:
        src = tmp_path / "native_gen.jpg"
        _write_jpeg(src, 1600, 1066)
        result = rms.save_image_from_path(str(src), "tortilla", "hero", min_bytes=50)
        assert result["success"] is True
        assert result["format"] == "jpg"
        assert result["output_path"].endswith("tortilla-hero.jpg")
        # Source file must remain in place
        assert src.exists()

    def test_convert_to_jpeg_false_keeps_png(self, tmp_path: Path) -> None:
        src = tmp_path / "native_gen.png"
        _write_png(src, 1920, 1280)
        result = rms.save_image_from_path(
            str(src),
            "preserved",
            "hero",
            convert_to_jpeg=False,
            min_bytes=50,
        )
        assert result["success"] is True
        assert result["format"] == "png"
        assert result["output_path"].endswith("preserved-hero.png")


@pytest.mark.unit
class TestFailureModes:
    def test_missing_source_returns_failure(self) -> None:
        result = rms.save_image_from_path("C:/no/such/file.png", "x", "hero")
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_directory_not_file(self, tmp_path: Path) -> None:
        result = rms.save_image_from_path(str(tmp_path), "x", "hero")
        assert result["success"] is False
        assert "not a file" in result["error"].lower()

    def test_too_small_byte_count_rejected(self, tmp_path: Path) -> None:
        src = tmp_path / "stub.png"
        src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)  # not a real image
        result = rms.save_image_from_path(str(src), "stub", "hero", min_bytes=5000)
        assert result["success"] is False
        assert "small" in result["error"].lower()


@pytest.mark.unit
class TestDimensionGate:
    def test_300x200_png_rejected(self, tmp_path: Path) -> None:
        src = tmp_path / "tiny.png"
        _write_png(src, 300, 200)
        result = rms.save_image_from_path(str(src), "tiny", "hero", min_bytes=50)
        assert result["success"] is False
        assert "too small" in result["error"].lower()
        # No output should have been kept
        out_dir = rms.OUTPUT_DIR
        assert list(out_dir.glob("tiny*")) == []

    def test_at_floor_png_passes(self, tmp_path: Path) -> None:
        src = tmp_path / "ok.png"
        _write_png(src, 1280, 800)
        result = rms.save_image_from_path(str(src), "ok", "hero", min_bytes=50)
        assert result["success"] is True
        assert result["width"] == 1280 and result["height"] == 800

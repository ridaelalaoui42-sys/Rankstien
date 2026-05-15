"""Tests for ``rankstein.branding``."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from rankstein import branding

# ───────────────────────────────────────────────────────────────────────────
# Palette lookup
# ───────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestPalette:
    def test_keto_lookup_returns_forest_gold(self) -> None:
        p = branding.palette_for("low-carb keto dinner recipes")
        assert p.primary == "#3D5A40"
        assert p.accent == "#D4AF37"

    def test_dessert_lookup_returns_pink_cream(self) -> None:
        p = branding.palette_for("postres y dulces tradicionales")
        assert p.primary == "#D67B7E"

    def test_seafood_lookup(self) -> None:
        assert branding.palette_for("japanese sushi cooking").primary == "#A22B22"  # asian wins
        assert branding.palette_for("fresh ocean fish").primary == "#1F4E79"  # seafood

    def test_unknown_niche_falls_back_to_default(self) -> None:
        p = branding.palette_for("hyperdimensional widgets")
        assert p.primary == "#D4AF37"
        assert p.accent == "#1a1a1a"

    def test_empty_niche_returns_default(self) -> None:
        assert branding.palette_for("").primary == "#D4AF37"

    def test_case_insensitive_match(self) -> None:
        assert branding.palette_for("KETO DINNERS").primary == "#3D5A40"


# ───────────────────────────────────────────────────────────────────────────
# Logo generation (Pollinations mocked)
# ───────────────────────────────────────────────────────────────────────────


def _make_real_png_bytes(width: int = 1024, height: int = 1024) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(50, 90, 64)).save(buf, "PNG")
    return buf.getvalue()


class _StubResponse:
    def __init__(self, content: bytes, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(str(self.status_code))


@pytest.mark.unit
class TestGenerateLogo:
    def test_pollinations_happy_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            branding.requests,
            "get",
            lambda *a, **kw: _StubResponse(_make_real_png_bytes()),
        )
        out = branding.generate_logo(
            niche="keto dinners",
            display_name="Keto Dinners",
            branding_dir=tmp_path / "branding",
            primary="#3D5A40",
            accent="#D4AF37",
        )
        assert out.exists()
        assert out.name == "logo.png"
        assert out.stat().st_size >= 5000

    def test_pollinations_too_small_falls_back_to_pillow(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            branding.requests,
            "get",
            lambda *a, **kw: _StubResponse(b"too short"),
        )
        out = branding.generate_logo(
            niche="anything",
            display_name="Acme Test",
            branding_dir=tmp_path / "branding",
            primary="#3D5A40",
            accent="#D4AF37",
        )
        assert out.exists()
        # Pillow fallback produces a real PNG bigger than the rejected payload
        assert out.stat().st_size > 1000

    def test_pollinations_http_error_falls_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import requests as _r

        def _raise(*a, **kw):
            raise _r.ConnectionError("network down")

        monkeypatch.setattr(branding.requests, "get", _raise)
        out = branding.generate_logo(
            niche="keto",
            display_name="K D",
            branding_dir=tmp_path / "branding",
            primary="#000000",
            accent="#FFFFFF",
        )
        assert out.exists()


# ───────────────────────────────────────────────────────────────────────────
# theme.json
# ───────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestThemeJson:
    def test_writes_expected_keys(self, tmp_path: Path) -> None:
        p = branding.write_theme_json(
            tmp_path / "branding",
            branding.Palette(primary="#111111", accent="#222222"),
            logo_filename="my-logo.png",
        )
        assert p.exists()
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["primary"] == "#111111"
        assert data["accent"] == "#222222"
        assert data["logo_path"] == "my-logo.png"
        assert "font_heading" in data and "font_body" in data


# ───────────────────────────────────────────────────────────────────────────
# provision_branding (the convenience entry point)
# ───────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestProvisionBranding:
    def test_full_flow(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            branding.requests,
            "get",
            lambda *a, **kw: _StubResponse(_make_real_png_bytes()),
        )
        result = branding.provision_branding(
            handle="keto-dinners",
            niche="low-carb keto dinners",
            display_name="Keto Dinners",
            branding_dir=tmp_path / "branding",
        )
        assert result["handle"] == "keto-dinners"
        assert result["primary_color"] == "#3D5A40"
        assert Path(result["logo_path"]).exists()
        assert Path(result["theme_path"]).exists()

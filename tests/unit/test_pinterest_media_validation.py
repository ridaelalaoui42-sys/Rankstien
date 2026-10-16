from __future__ import annotations

import json

import pytest
from PIL import Image

from pinterest_automation import media_validation as media


def _image(tmp_path, *, name="pin.jpg", kind="JPEG", size=(1000, 1500)):
    path = tmp_path / name
    Image.new("RGB", size, (44, 112, 72)).save(path, format=kind)
    return path


@pytest.mark.parametrize(
    "name,kind,mime",
    [
        ("pin.jpg", "JPEG", "image/jpeg"),
        ("pin.jpeg", "JPEG", "image/jpeg"),
        ("pin.JPG", "JPEG", "image/jpeg"),
        ("pin.png", "PNG", "image/png"),
    ],
)
def test_real_1000x1500_jpeg_and_png_pass_without_file_changes(tmp_path, name, kind, mime):
    path = _image(tmp_path, name=name, kind=kind)
    before, modified = path.read_bytes(), path.stat().st_mtime_ns
    result = media.validate_pin_upload_image(path)
    assert result == {
        "ok": True,
        "reason": "valid",
        "actual_format": kind,
        "width": 1000,
        "height": 1500,
        "file_bytes": len(before),
        "mime_type": mime,
        "min_width": 500,
        "min_height": 700,
    }
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == modified


def test_150px_jpeg_thumbnail_fails_existing_source_quality_contract(tmp_path):
    path = _image(tmp_path, size=(150, 150))
    result = media.validate_pin_upload_image(path)
    assert result["reason"] == "below_minimum_dimensions"
    assert not result["ok"]
    assert (result["actual_format"], result["width"], result["height"]) == ("JPEG", 150, 150)


def test_mislabeled_webp_thumbnail_rejected_by_actual_bytes(tmp_path):
    path = _image(tmp_path, kind="WEBP", size=(150, 150))
    before = path.read_bytes()
    result = media.validate_pin_upload_image(path)
    assert not result["ok"] and result["reason"] == "unsupported_format"
    assert (result["actual_format"], result["width"], result["height"]) == ("WEBP", 150, 150)
    assert result["mime_type"] == "image/webp"
    assert path.read_bytes() == before


@pytest.mark.parametrize("name,kind", [("pin.jpg", "PNG"), ("pin.png", "JPEG")])
def test_supported_image_with_wrong_extension_rejected(tmp_path, name, kind):
    result = media.validate_pin_upload_image(_image(tmp_path, name=name, kind=kind))
    assert not result["ok"] and result["reason"] == "extension_format_mismatch"
    assert result["actual_format"] == kind


def test_unknown_extension_is_not_silently_accepted(tmp_path):
    result = media.validate_pin_upload_image(_image(tmp_path, name="pin.bin"))
    assert result["reason"] == "unsupported_extension"


@pytest.mark.parametrize("contents", [b"", b"this is not an image", b"\x89PNG\r\n\x1a\ninvalid"])
def test_corrupt_image_fails_with_safe_reason_without_path_or_raw_error(tmp_path, contents):
    path = tmp_path / "private-source-name.jpg"
    path.write_bytes(contents)
    result = media.validate_pin_upload_image(path)
    assert not result["ok"] and result["reason"] == "corrupt_image"
    assert "private-source-name" not in json.dumps(result)


def test_truncated_jpeg_scan_data_fails_full_decode(tmp_path):
    path = _image(tmp_path)
    path.write_bytes(path.read_bytes()[:-50])
    result = media.validate_pin_upload_image(path)
    assert not result["ok"] and result["reason"] == "corrupt_image"


def test_oversized_file_rejected_before_pillow_or_payload_read(tmp_path, monkeypatch):
    path = tmp_path / "oversized.jpg"
    with path.open("wb") as stream:
        stream.truncate(media.MAX_IMAGE_BYTES + 1)

    def never_decode(*args):
        pytest.fail("Oversized source was handed to Pillow")

    monkeypatch.setattr(media.Image, "open", never_decode)
    result = media.validate_pin_upload_image(path)
    assert result["reason"] == "file_too_large"
    assert result["file_bytes"] == media.MAX_IMAGE_BYTES + 1


def test_excessive_dimension_rejected_from_actual_png_header(tmp_path):
    path = _image(tmp_path, name="too-wide.png", kind="PNG", size=(media.MAX_IMAGE_SIDE + 1, 1))
    result = media.validate_pin_upload_image(path)
    assert result["reason"] == "dimensions_exceed_safety_bound"
    assert result["width"] == media.MAX_IMAGE_SIDE + 1


def test_pixel_resource_bound_rejected_before_verify_or_decode(tmp_path, monkeypatch):
    path = tmp_path / "large-header.jpg"
    path.write_bytes(b"bounded header fixture")

    class Header:
        format = "JPEG"
        size = (10000, 5000)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def verify(self):
            pytest.fail("Excessive pixel count reached verification/decode")

    monkeypatch.setattr(media.Image, "open", lambda *_: Header())
    result = media.validate_pin_upload_image(path)
    assert result["reason"] == "dimensions_exceed_safety_bound"


def test_minimum_environment_override_and_explicit_values_are_respected(tmp_path, monkeypatch):
    path = _image(tmp_path, size=(150, 150))
    monkeypatch.setenv("RANKSTEIN_REMASTER_MIN_IMAGE_WIDTH", "100")
    monkeypatch.setenv("RANKSTEIN_REMASTER_MIN_IMAGE_HEIGHT", "125")
    assert media.validate_pin_upload_image(path)["ok"]
    result = media.validate_pin_upload_image(path, min_width=200, min_height=200)
    assert result["reason"] == "below_minimum_dimensions"
    assert (result["min_width"], result["min_height"]) == (200, 200)


@pytest.mark.parametrize("invalid", ["invalid", "500.5", "0", -1, True, 1.5, 10001])
def test_invalid_quality_configuration_is_distinct_from_bad_content(tmp_path, invalid):
    result = media.validate_pin_upload_image(tmp_path / "does-not-exist.jpg", min_width=invalid)
    assert result["reason"] == "invalid_quality_configuration"


def test_missing_and_nonregular_sources_fail_closed(tmp_path):
    assert media.validate_pin_upload_image(tmp_path / "missing.jpg")["reason"] == "missing_file"
    assert media.validate_pin_upload_image(tmp_path)["reason"] == "not_a_file"
    assert media.validate_pin_upload_image(None)["reason"] == "invalid_path"


def test_exact_quality_boundary_is_allowed(tmp_path):
    path = _image(tmp_path, size=(500, 700))
    assert media.validate_pin_upload_image(path)["ok"]

"""Read-only preflight for actual Pinterest upload image bytes.

Minimum dimensions follow the existing RankStein remaster source-quality
contract (500x700 unless configured). They are our intake policy, not a claim
about Pinterest's legal or platform-wide minimum dimensions. The upper bounds
limit local file/decode resources. This module never edits or upscales images.
"""

from __future__ import annotations

import io
import os
import stat
import warnings
from pathlib import Path

from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_SIDE = 10000
MAX_IMAGE_PIXELS = 40000000
_EXTENSION_FORMAT = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG"}
_FORMAT_MIME = {"JPEG": "image/jpeg", "PNG": "image/png"}


def _minimum(value, environment: str, default: int) -> int:
    value = os.environ.get(environment, str(default)) if value is None else value
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("Minimum dimensions must be positive integers")
    value = int(value)
    if not 1 <= value <= MAX_IMAGE_SIDE:
        raise ValueError("Minimum dimensions exceed the supported resource bounds")
    return value


def validate_pin_upload_image(image_path, *, min_width=None, min_height=None) -> dict:
    """Inspect bounded bytes and pixels, returning stable, nonsecret reason codes.

    ``invalid_quality_configuration`` describes operator configuration rather
    than defective content. Other failed results identify this one source file.
    The caller retains the original file and decides queue disposition.
    """
    result = {
        "ok": False,
        "reason": "invalid_path",
        "actual_format": None,
        "width": None,
        "height": None,
        "file_bytes": None,
        "mime_type": None,
        "min_width": None,
        "min_height": None,
    }
    try:
        result["min_width"] = _minimum(min_width, "RANKSTEIN_REMASTER_MIN_IMAGE_WIDTH", 500)
        result["min_height"] = _minimum(min_height, "RANKSTEIN_REMASTER_MIN_IMAGE_HEIGHT", 700)
    except (TypeError, ValueError):
        result["reason"] = "invalid_quality_configuration"
        return result
    try:
        path = Path(image_path)
        info = path.stat()
        result["file_bytes"] = info.st_size
        if not stat.S_ISREG(info.st_mode):
            result["reason"] = "not_a_file"
            return result
        if info.st_size > MAX_IMAGE_BYTES:
            result["reason"] = "file_too_large"
            return result
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode):
                result["reason"] = "not_a_file"
                return result
            if opened.st_size > MAX_IMAGE_BYTES:
                result.update(reason="file_too_large", file_bytes=opened.st_size)
                return result
            # Bound the read even if the source changes after stat/open.
            raw = stream.read(MAX_IMAGE_BYTES + 1)
        result["file_bytes"] = len(raw)
        if len(raw) > MAX_IMAGE_BYTES:
            result["reason"] = "file_too_large"
            return result
    except FileNotFoundError:
        result["reason"] = "missing_file"
        return result
    except (TypeError, ValueError):
        result["reason"] = "invalid_path"
        return result
    except OSError:
        result["reason"] = "image_unreadable"
        return result

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                kind = image.format
                width, height = image.size
                result.update(
                    actual_format=kind,
                    width=width,
                    height=height,
                    mime_type=Image.MIME.get(kind) or _FORMAT_MIME.get(kind),
                )
                if kind not in _FORMAT_MIME:
                    result["reason"] = "unsupported_format"
                    return result
                expected = _EXTENSION_FORMAT.get(path.suffix.casefold())
                if expected is None:
                    result["reason"] = "unsupported_extension"
                    return result
                if expected != kind:
                    result["reason"] = "extension_format_mismatch"
                    return result
                if width > MAX_IMAGE_SIDE or height > MAX_IMAGE_SIDE or width * height > MAX_IMAGE_PIXELS:
                    result["reason"] = "dimensions_exceed_safety_bound"
                    return result
                if width < result["min_width"] or height < result["min_height"]:
                    result["reason"] = "below_minimum_dimensions"
                    return result
                image.verify()
            # JPEG verify() alone does not fully decode truncated scan data.
            with Image.open(io.BytesIO(raw)) as image:
                image.load()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        result["reason"] = "dimensions_exceed_safety_bound"
        return result
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        result["reason"] = "corrupt_image"
        return result
    result.update(ok=True, reason="valid")
    return result

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from rankstein import source_image_quality as quality


@pytest.fixture(autouse=True)
def isolated_quality_cache():
    quality._assess_cached.cache_clear()
    yield
    quality._assess_cached.cache_clear()


@pytest.mark.unit
@pytest.mark.parametrize("text", ["", "x", "II 0", "ab cd", "? 42"])
def test_only_text_free_images_or_tiny_ocr_noise_are_accepted(monkeypatch, tmp_path, text):
    source = tmp_path / "source.jpg"
    source.write_bytes(b"isolated source file")
    monkeypatch.setattr(
        quality, "_read_windows_text", lambda *_args, **_kwargs: {"available": True, "text": text}
    )

    assessment = quality.assess_source_image(source)

    assert assessment["accepted"] is True
    assert assessment["policy"] == quality.SOURCE_QUALITY_POLICY
    assert assessment["version"] == quality.SOURCE_QUALITY_VERSION
    assert assessment["source_hash"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert "text" not in assessment


@pytest.mark.unit
@pytest.mark.parametrize(
    "text",
    [
        "Ingredientes: 200 g farinha, 3 ovos. Asse no forno por 30 minutos.",
        "RECETA DE PASTEL AL HORNO",
        "RecetaDolce.com",
        "@otherbrand",
        "© Recipe brand",
        "Chocolate",
        "pan",
        "abc def ghi",
        "12345",
    ],
)
def test_embedded_foreign_recipe_brand_and_title_text_are_rejected(monkeypatch, tmp_path, text):
    source = tmp_path / "source.jpg"
    source.write_bytes(b"isolated source file")
    monkeypatch.setattr(
        quality, "_read_windows_text", lambda *_args, **_kwargs: {"available": True, "text": text}
    )

    assessment = quality.assess_source_image(source)

    assert assessment["accepted"] is False
    assert assessment["reason"] == "embedded_text"
    assert "text" not in assessment
    assert text not in json.dumps(assessment)


@pytest.mark.unit
@pytest.mark.parametrize("reason", ["ocr_unavailable", "ocr_timeout", "ocr_invalid_response"])
def test_ocr_failures_block_the_source_instead_of_assuming_text_free(monkeypatch, tmp_path, reason):
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    monkeypatch.setattr(
        quality, "_read_windows_text", lambda *_args, **_kwargs: {"available": False, "reason": reason}
    )

    assessment = quality.assess_source_image(source)

    assert assessment["accepted"] is False
    assert assessment["reason"] == reason


@pytest.mark.unit
def test_cache_is_file_identity_scoped_and_returns_independent_metadata(monkeypatch, tmp_path):
    source = tmp_path / "source.jpg"
    source.write_bytes(b"first source")
    calls = []

    def reader(path, *, timeout):
        calls.append((path, timeout))
        return {"available": True, "text": ""}

    monkeypatch.setattr(quality, "_read_windows_text", reader)
    first = quality.assess_source_image(source)
    first["accepted"] = False
    cached = quality.assess_source_image(source)
    assert cached["accepted"] is True
    assert len(calls) == 1

    source.write_bytes(b"replacement source with a different size")
    replaced = quality.assess_source_image(source)
    assert len(calls) == 2
    assert replaced["source_hash"] != cached["source_hash"]


@pytest.mark.unit
def test_file_replacement_during_ocr_is_rejected(monkeypatch, tmp_path):
    source = tmp_path / "source.jpg"
    source.write_bytes(b"first source")

    def replace_during_scan(*_args, **_kwargs):
        source.write_bytes(b"another source with different size")
        return {"available": True, "text": ""}

    monkeypatch.setattr(quality, "_read_windows_text", replace_during_scan)
    assessment = quality.assess_source_image(source)
    assert assessment["accepted"] is False
    assert assessment["reason"] == "source_changed_during_assessment"


@pytest.mark.unit
def test_missing_file_is_rejected_without_starting_ocr(monkeypatch, tmp_path):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("missing files must not start OCR")

    monkeypatch.setattr(quality, "_read_windows_text", forbidden)
    assessment = quality.assess_source_image(tmp_path / "missing.jpg")
    assert assessment["accepted"] is False
    assert assessment["reason"] == "source_unreadable"


@pytest.mark.unit
def test_oversized_file_is_rejected_before_hashing_or_ocr(monkeypatch, tmp_path):
    source = tmp_path / "source.jpg"
    source.write_bytes(b"oversized source")
    monkeypatch.setattr(quality, "_MAX_SOURCE_BYTES", 8)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("oversized files must not start OCR")

    monkeypatch.setattr(quality, "_read_windows_text", forbidden)
    assessment = quality.assess_source_image(source)
    assert assessment["accepted"] is False
    assert assessment["reason"] == "source_too_large"


@pytest.mark.unit
def test_windows_subprocess_is_hidden_and_bounded_without_shell(monkeypatch, tmp_path):
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    monkeypatch.setattr(quality.sys, "platform", "win32")
    monkeypatch.setattr(quality.shutil, "which", lambda _name: "powershell.exe")
    monkeypatch.setattr(quality.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    captured = {}

    def run(command, **kwargs):
        captured.update(command=command, **kwargs)
        return SimpleNamespace(returncode=0, stdout='{"available":true,"text":""}')

    monkeypatch.setattr(quality.subprocess, "run", run)
    assessment = quality.assess_source_image(source, timeout=200)
    assert assessment["accepted"] is True
    assert captured["timeout"] == 20
    assert captured["creationflags"] == 0x08000000
    assert captured["capture_output"] is True
    assert captured.get("shell", False) is False
    assert "-ExecutionPolicy" not in captured["command"]
    assert captured["command"][-1] == str(source.resolve())


@pytest.mark.unit
def test_timeout_output_is_not_exposed(monkeypatch, tmp_path):
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    monkeypatch.setattr(quality.sys, "platform", "win32")
    monkeypatch.setattr(quality.shutil, "which", lambda _name: "powershell.exe")

    def timed_out(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("powershell.exe", 20, output="private recipe text")

    monkeypatch.setattr(quality.subprocess, "run", timed_out)
    assessment = quality.assess_source_image(source)
    assert assessment["accepted"] is False
    assert assessment["reason"] == "ocr_timeout"
    assert "private recipe" not in json.dumps(assessment)


@pytest.mark.unit
@pytest.mark.parametrize("stdout", ["not-json", "[]", '{"available":true}', '{"available":true,"text":0}'])
def test_malformed_ocr_response_is_rejected(monkeypatch, stdout):
    monkeypatch.setattr(quality.sys, "platform", "win32")
    monkeypatch.setattr(quality.shutil, "which", lambda _name: "powershell.exe")
    monkeypatch.setattr(
        quality.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=stdout)
    )
    payload = quality._read_windows_text(str(Path("source.jpg")), timeout=20)
    assert payload["available"] is False

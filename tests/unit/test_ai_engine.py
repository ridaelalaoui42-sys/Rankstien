from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.core import engine
from backend.core.config import get_settings


@pytest.fixture(autouse=True)
def _reset_backend_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.unit
def test_backend_defaults_to_gemini_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cli = tmp_path / "gemini.cmd"
    cli.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setenv("RANKSTEIN_SECRET", "x" * 32)
    monkeypatch.setenv("GEMINI_CLI_PATH", str(cli))
    monkeypatch.delenv("RANKSTEIN_AI_ENGINE", raising=False)
    monkeypatch.delenv("ADK_MODEL", raising=False)

    client = engine.get_genai_client()

    assert client.engine == "gemini_cli"
    assert client.cli_path == str(cli)
    assert get_settings().adk_model == "gemini-3.1-flash-lite-preview"


@pytest.mark.unit
def test_gemini_cli_generation_uses_subscription_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        assert kwargs["timeout"] == 12
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(engine.subprocess, "run", fake_run)
    client = engine.AIClient(
        engine="gemini_cli",
        cli_path="C:\\Tools\\gemini.cmd",
        fallback_model="gemini-3.1-pro-preview",
        timeout_seconds=12,
        yolo=True,
    )

    data = engine.generate_structured(client, "auto", "Return JSON")

    assert data == {"ok": True}
    assert calls == [["C:\\Tools\\gemini.cmd", "-p", "Return JSON", "--yolo"]]


@pytest.mark.unit
def test_gemini_cli_falls_back_to_secondary_model(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_run(cmd, **kwargs):
        model = cmd[cmd.index("--model") + 1] if "--model" in cmd else "auto"
        calls.append(model)
        if model == "auto":
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="quota")
        return subprocess.CompletedProcess(cmd, 0, stdout='{"fallback": true}', stderr="")

    monkeypatch.setattr(engine.subprocess, "run", fake_run)
    client = engine.AIClient(
        engine="gemini_cli",
        cli_path="gemini.cmd",
        fallback_model="gemini-3.1-pro-preview",
        timeout_seconds=12,
        yolo=False,
    )

    data = engine.generate_structured(client, "auto", "Return JSON")

    assert data == {"fallback": True}
    assert calls == ["auto", "gemini-3.1-pro-preview"]


@pytest.mark.unit
def test_google_api_mode_requires_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RANKSTEIN_SECRET", "x" * 32)
    monkeypatch.setenv("RANKSTEIN_AI_ENGINE", "google_api")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")

    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        engine.get_genai_client()

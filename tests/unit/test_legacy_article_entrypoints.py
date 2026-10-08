from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.api import routes
from backend.scripts import daily_engine, fix_post


def test_legacy_api_article_pipeline_returns_gone() -> None:
    request = routes.PipelineRequest(
        keyword="tarta de limón",
        domain="recetadolce.com",
        niche="recetas",
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(routes.orchestrate_pipeline(request))

    assert exc_info.value.status_code == 410
    assert exc_info.value.detail["code"] == "legacy_article_pipeline_retired"
    assert "Codex-only" in exc_info.value.detail["message"]


@pytest.mark.parametrize(
    ("call", "args"),
    [
        (daily_engine.generate_article_content, ("tarta de limón",)),
        (daily_engine.generate_ai_hero_image, ("tarta de limón", "tarta-de-limon")),
        (daily_engine.daily_growth_loop, ()),
        (daily_engine.run_forever, ()),
    ],
)
def test_retired_daily_engine_programmatic_paths_fail_closed(call, args) -> None:
    with pytest.raises(daily_engine.LegacyDailyEngineDisabled, match="Codex-only"):
        asyncio.run(call(*args))


def test_daily_engine_cli_delegates_with_codex_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def fake_call(command, *, cwd, env):
        captured.update(command=command, cwd=cwd, env=env)
        return 17

    monkeypatch.setenv("RANKSTEIN_ARTICLE_PROVIDER", "unapproved-provider")
    monkeypatch.setattr(daily_engine.subprocess, "call", fake_call)

    result = daily_engine.main(["--run-once"])

    assert result == 17
    assert captured["cwd"] == daily_engine.PROJECT_ROOT
    assert captured["command"] == [
        daily_engine.sys.executable,
        str(daily_engine.PROJECT_ROOT / "rankstein.py"),
        "run",
        "--all",
        "--no-launch",
    ]
    assert captured["env"]["RANKSTEIN_ARTICLE_PROVIDER"] == "hermes-codex-only"


def test_retired_post_fixer_fails_before_any_rewrite() -> None:
    with pytest.raises(fix_post.LegacyPostFixerDisabled, match="will not rewrite or publish"):
        fix_post.fix_post("tarta-de-limon", "recetadolce")


def test_owned_legacy_scripts_do_not_contain_provider_process_calls() -> None:
    for module_path in (
        Path(daily_engine.__file__),
        Path(fix_post.__file__),
    ):
        source = module_path.read_text(encoding="utf-8").casefold()
        assert "popen(" not in source
        assert "generate_structured(" not in source
        assert "google.generativeai" not in source


def test_legacy_api_does_not_import_or_instantiate_article_agents() -> None:
    source = Path(routes.__file__).read_text(encoding="utf-8").casefold()
    assert "pipelineorchestrator" not in source
    assert "backend.agents" not in source

from __future__ import annotations

import asyncio
import subprocess
from types import SimpleNamespace

import pytest

import rankstein.domain
import rankstein.prompts
import rankstein.runtime_env
import rankstein_mcp_server


@pytest.mark.unit
def test_mcp_relogin_uses_the_same_domain_remaster_profile(monkeypatch, tmp_path) -> None:
    domain = SimpleNamespace(
        handle="recetagenial",
        sessions_dir=tmp_path / "uploader_recetagenial",
    )
    monkeypatch.setattr(rankstein_mcp_server, "PROJECT_ROOT", tmp_path)

    session_dir = rankstein_mcp_server._pinterest_session_dir("remasterer", domain)

    assert session_dir == tmp_path / "data" / "sessions" / "remasterer_recetagenial"


@pytest.mark.unit
def test_mcp_relogin_rejects_unknown_session_type(monkeypatch, tmp_path) -> None:
    domain = SimpleNamespace(handle="recetagenial", sessions_dir=tmp_path / "uploader")
    monkeypatch.setattr(rankstein_mcp_server, "PROJECT_ROOT", tmp_path)

    with pytest.raises(ValueError, match="Unsupported Pinterest session type"):
        rankstein_mcp_server._pinterest_session_dir("unknown", domain)


@pytest.mark.unit
def test_mcp_remaster_login_uses_routed_account_credentials(monkeypatch) -> None:
    routed_credentials = SimpleNamespace(
        email="media@example.test",
        password="configured-password",
        valid=True,
    )
    config = SimpleNamespace(accounts={"media": routed_credentials})
    domain = SimpleNamespace(handle="recetagenial")

    monkeypatch.setattr("pinterest_automation.config.get_config", lambda: config)
    monkeypatch.setattr(
        "pinterest_automation.routing.account_cohort",
        lambda domain_handle, **_kwargs: ["media"] if domain_handle == "recetagenial" else [],
    )

    email, password, account_handle = rankstein_mcp_server._pinterest_login_identity(
        "remasterer", domain
    )

    assert (email, password, account_handle) == (
        "media@example.test",
        "configured-password",
        "media",
    )


@pytest.mark.unit
def test_pinterest_auth_proof_requires_canonical_links_without_login_wall() -> None:
    class FakeLocator:
        def __init__(self, *, text: str = "", count: int = 0) -> None:
            self.text = text
            self.value_count = count

        async def inner_text(self, **_kwargs) -> str:
            return self.text

        async def count(self) -> int:
            return self.value_count

    class FakePage:
        def __init__(self, *, body: str, pin_links: int) -> None:
            self.body = body
            self.pin_links = pin_links

        async def goto(self, *_args, **_kwargs) -> None:
            return None

        async def wait_for_timeout(self, *_args, **_kwargs) -> None:
            return None

        def locator(self, selector: str) -> FakeLocator:
            if selector == "body":
                return FakeLocator(text=self.body)
            return FakeLocator(count=self.pin_links)

    assert (
        asyncio.run(
            rankstein_mcp_server._pinterest_search_session_authenticated(
                FakePage(body="Has cerrado sesión", pin_links=19)
            )
        )
        is False
    )
    assert (
        asyncio.run(
            rankstein_mcp_server._pinterest_search_session_authenticated(
                FakePage(body="Ideas para ti", pin_links=19)
            )
        )
        is True
    )
    assert (
        asyncio.run(
            rankstein_mcp_server._pinterest_search_session_authenticated(
                FakePage(body="Ideas para ti", pin_links=0)
            )
        )
        is False
    )


@pytest.mark.unit
def test_mcp_remaster_campaign_loads_real_recipe_context(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    domain = SimpleNamespace(handle="recetadolce", domain="recetadolce.com")
    registry = SimpleNamespace(default=domain, get=lambda _handle: domain)
    launched: dict = {}

    monkeypatch.setattr(rankstein.domain, "get_registry", lambda: registry)
    monkeypatch.setattr(
        rankstein.prompts,
        "build_recipe_image_scrape_brief",
        lambda value, **_kwargs: {
            "search_query": value,
            "search_queries": [value, f"receta {value}"],
            "core_terms": ["chocolate"],
            "min_core_matches": 1,
            "expected_terms": ["tarta", "chocolate"],
            "blocked_terms": ["outfit"],
        },
    )
    monkeypatch.setattr(rankstein.runtime_env, "clean_python_env", lambda: {})
    monkeypatch.setattr(
        rankstein_mcp_server,
        "get_article_data_from_supabase_by_slug",
        lambda *_args: {
            "success": True,
            "title": "Tarta cremosa de chocolate",
            "category": "Postres",
            "chef_tip": "Deja enfriar antes de cortar.",
            "recipe_schema": {
                "recipeIngredient": ["200 g de chocolate", "3 huevos"],
                "recipeInstructions": [
                    {"@type": "HowToStep", "text": "Funde el chocolate."},
                    {"@type": "HowToStep", "text": "Hornea 25 minutos."},
                ],
            },
        },
    )
    monkeypatch.setattr(rankstein_mcp_server, "PROJECT_ROOT", tmp_path)

    def fake_popen(command, **kwargs):
        launched["command"] = command
        launched["kwargs"] = kwargs
        kwargs["stdout"].close()
        kwargs["stderr"].close()
        return SimpleNamespace(pid=4321)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    result = rankstein_mcp_server.run_article_remaster_campaign(
        keyword="postres con chocolate",
        title="Título de roadmap",
        slug="tarta-cremosa-de-chocolate",
        domain_handle="recetadolce",
        pins_per_keyword=10,
    )

    command = launched["command"]
    assert result["success"] is True
    assert result["pins_per_keyword"] == 30
    assert result["source_target"] == 15
    assert result["variants"] == ["viral_visual", "recipe_card"]
    assert command[2:4] == [
        "Tarta cremosa de chocolate",
        "Tarta cremosa de chocolate",
    ]
    assert command[command.index("--recipe-ingredients-json") + 1].startswith("[")
    assert "Funde el chocolate." in command[command.index("--recipe-steps-json") + 1]
    assert command[command.index("--tip-text") + 1] == "Deja enfriar antes de cortar."

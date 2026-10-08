from __future__ import annotations

import asyncio

import pytest

from backend.scripts import hero_image_pipeline
from backend.services import remasterer
from rankstein import prompts


@pytest.mark.unit
def test_native_fallback_retries_until_all_fifteen_sources_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []
    failed_attempts = {1, 2, 5}

    def fake_get_hero_image(*, keyword: str, slug: str, image_prompt: str) -> dict:
        del keyword, image_prompt
        attempts.append(slug)
        if len(attempts) in failed_attempts:
            return {"success": False, "error": "temporary Codex transport failure"}
        return {
            "success": True,
            "output_path": f"C:/generated/{slug}-hero.jpg",
            "source": "codex",
        }

    monkeypatch.delenv("RANKSTEIN_NATIVE_SOURCE_MAX_ATTEMPTS", raising=False)
    monkeypatch.setattr(hero_image_pipeline, "get_hero_image", fake_get_hero_image)
    monkeypatch.setattr(prompts, "build_recipe_image_prompt", lambda *args, **kwargs: "prompt")

    sources = remasterer._generate_native_fallback_sources("tarta de limon", 15)

    assert len(sources) == 15
    assert len(attempts) == 18
    assert [source["pin_id"] for source in sources] == [f"native-{index:02d}" for index in range(1, 16)]
    assert len({source["raw_path"] for source in sources}) == 15
    assert all(source["provider"] == "codex" for source in sources)


@pytest.mark.unit
def test_native_fallback_stops_at_bounded_retry_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def always_fail(**kwargs) -> dict:
        nonlocal calls
        del kwargs
        calls += 1
        return {"success": False, "error": "Codex unavailable"}

    monkeypatch.setenv("RANKSTEIN_NATIVE_SOURCE_MAX_ATTEMPTS", "7")
    monkeypatch.setattr(hero_image_pipeline, "get_hero_image", always_fail)
    monkeypatch.setattr(prompts, "build_recipe_image_prompt", lambda *args, **kwargs: "prompt")

    assert remasterer._generate_native_fallback_sources("flan casero", 3) == []
    assert calls == 7


@pytest.mark.unit
def test_native_retry_budget_cannot_reintroduce_a_source_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RANKSTEIN_NATIVE_SOURCE_MAX_ATTEMPTS", "6")
    assert remasterer._native_source_attempt_budget(15) == 15

    monkeypatch.setenv("RANKSTEIN_NATIVE_SOURCE_MAX_ATTEMPTS", "9999")
    assert remasterer._native_source_attempt_budget(15) == 75


@pytest.mark.unit
def test_hero_image_fallback_order_scraped_before_pollinations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rankstein_mcp_server

    calls: list[str] = []

    def mock_codex(**kwargs) -> dict:
        calls.append("codex")
        return {"success": False, "error": "Codex unavailable"}

    def mock_scrape(keyword: str, slug: str) -> dict:
        calls.append("scraped")
        return {
            "success": True,
            "output_path": "C:/tmp/scraped-hero.jpg",
            "format": "jpg",
            "size_bytes": 50000,
            "width": 1200,
            "height": 800,
        }

    def forbidden_pollinations(*args, **kwargs) -> dict:
        calls.append("pollinations")
        raise AssertionError("Pollinations must not be called when scraped succeeds")

    monkeypatch.setattr(rankstein_mcp_server, "create_hero_image_codex", mock_codex)
    monkeypatch.setattr(hero_image_pipeline, "scrape_hero_from_news", mock_scrape)
    monkeypatch.setattr(hero_image_pipeline, "create_hero_image_pollinations", forbidden_pollinations)

    result = hero_image_pipeline.get_hero_image(
        keyword="tarta de limón",
        slug="tarta-de-limon",
        domain_handle="recetadolce",
        image_prompt="Pastel de limón terminado, fotografía editorial.",
    )

    assert result["success"] is True
    assert result["source"] == "scraped"
    assert calls == ["codex", "scraped"]


@pytest.mark.unit
def test_hero_image_fallback_to_pollinations_when_scraped_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rankstein_mcp_server

    calls: list[str] = []

    def mock_codex(**kwargs) -> dict:
        calls.append("codex")
        return {"success": False, "error": "Codex unavailable"}

    def mock_scrape(keyword: str, slug: str) -> dict:
        calls.append("scraped")
        return {"success": False, "error": "no scraped sources"}

    def mock_pollinations(*args, **kwargs) -> dict:
        calls.append("pollinations")
        return {
            "success": True,
            "output_path": "C:/tmp/pollinations-hero.jpg",
            "format": "jpg",
            "size_bytes": 60000,
            "width": 1920,
            "height": 1080,
        }

    monkeypatch.setattr(rankstein_mcp_server, "create_hero_image_codex", mock_codex)
    monkeypatch.setattr(hero_image_pipeline, "scrape_hero_from_news", mock_scrape)
    monkeypatch.setattr(hero_image_pipeline, "create_hero_image_pollinations", mock_pollinations)

    result = hero_image_pipeline.get_hero_image(
        keyword="tarta de limón",
        slug="tarta-de-limon",
        domain_handle="recetadolce",
        image_prompt="Pastel de limón terminado, fotografía editorial.",
    )

    assert result["success"] is True
    assert result["source"] == "pollinations"
    assert calls == ["codex", "scraped", "pollinations"]


@pytest.mark.unit
def test_default_browser_sessions_are_isolated_by_domain() -> None:
    dolce = remasterer._resolve_session_name(domain_handle="recetadolce")
    genial = remasterer._resolve_session_name(domain_handle="recetagenial")

    assert dolce == "remasterer_recetadolce"
    assert genial == "remasterer_recetagenial"
    assert dolce != genial


@pytest.mark.unit
def test_unnamed_browser_sessions_are_unique_and_explicit_names_are_safe() -> None:
    first = remasterer._resolve_session_name()
    second = remasterer._resolve_session_name()

    assert first != second
    assert first.startswith("remasterer_")
    assert second.startswith("remasterer_")
    assert remasterer._resolve_session_name("../Receta Genial") == "Receta-Genial"


@pytest.mark.unit
def test_partial_scrape_does_not_generate_native_fill_or_any_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePinRemasterer:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

        async def collect_and_download(self, *args, **kwargs) -> list[dict]:
            del args, kwargs
            return [
                {
                    "pin_id": "123456789012345678",
                    "raw_path": "C:/scraped/turron.jpg",
                    "source": "pinterest",
                    "relevance_score": 10,
                }
            ]

    def forbidden(*args, **kwargs):
        del args, kwargs
        raise AssertionError("partial Pinterest intake must not create native sources or variants")

    monkeypatch.setattr(remasterer, "PinRemasterer", FakePinRemasterer)
    monkeypatch.setattr(
        remasterer,
        "_generate_native_fallback_sources",
        forbidden,
    )
    monkeypatch.setattr(remasterer, "create_viral_visual_pin", forbidden)
    monkeypatch.setattr(remasterer, "create_recipe_card_pin", forbidden)

    assets = asyncio.run(
        remasterer.run_remasterer(
            "tarta de limon",
            "Tarta de limon cremosa",
            domain_handle="recetadolce",
            pins_per_keyword=30,
            recipe_ingredients=["200 g de harina", "3 huevos", "2 limones"],
            recipe_steps=["Mezcla los ingredientes.", "Hornea durante 30 minutos."],
        )
    )

    assert assets == []


@pytest.mark.unit
def test_pinterest_search_timeouts_retry_each_query_and_report_diagnostics() -> None:
    class TimedOutPage:
        def __init__(self) -> None:
            self.urls: list[str] = []

        async def goto(self, url: str, **kwargs) -> None:
            del kwargs
            self.urls.append(url)
            raise TimeoutError("Pinterest search timed out")

        def is_closed(self) -> bool:
            return False

    studio = remasterer.PinRemasterer(
        headless=True,
        session_name="remasterer_timeout_test",
    )
    page = TimedOutPage()
    studio.page = page

    collected = asyncio.run(
        studio.collect_and_download(
            "tarta de turron",
            count=15,
            search_queries=["tarta turron", "postre turron"],
        )
    )

    assert collected == []
    assert len(page.urls) == 6
    assert studio.last_collection_diagnostics == {
        "queries_planned": 3,
        "query_attempts": 6,
        "queries_succeeded": 0,
        "query_failures": 6,
        "login_wall_detected": 0,
        "blocked_reason": "",
        "result_cards_seen": 0,
        "pin_images_seen": 0,
        "pin_links_seen": 0,
        "pins_examined": 0,
        "duplicates_skipped": 0,
        "relevance_rejected": 0,
        "download_failed": 0,
        "undersized_rejected": 0,
        "invalid_image_rejected": 0,
        "accepted": 0,
    }


@pytest.mark.unit
def test_pinterest_login_wall_detection_is_explicit() -> None:
    assert remasterer._is_pinterest_login_wall_text("Has cerrado sesión") is True
    assert remasterer._is_pinterest_login_wall_text("You've been logged out") is True
    assert remasterer._is_pinterest_login_wall_text("Explora ideas para cocinar") is False


@pytest.mark.unit
def test_pinterest_grid_cards_are_included_in_current_selector() -> None:
    assert '[data-test-id="pin"]' in remasterer.PINTEREST_PIN_CARD_SELECTOR
    assert '[data-grid-item="true"]' in remasterer.PINTEREST_PIN_CARD_SELECTOR

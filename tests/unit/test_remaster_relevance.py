from __future__ import annotations

import pytest
from PIL import Image

from backend.services.remasterer import (
    _augment_native_sources,
    is_relevant_recipe_pin,
    score_pin_relevance,
)
from rankstein.prompts import build_recipe_image_scrape_brief


@pytest.mark.unit
def test_relevance_uses_generated_expected_terms() -> None:
    assert is_relevant_recipe_pin(
        "ensalada de garbanzos",
        alt_text="Ensalada mediterranea con garbanzos y tomate",
        href="/pin/123456789012345678/",
        expected_terms=["ensalada", "garbanzos", "mediterranea"],
    )


@pytest.mark.unit
def test_relevance_rejects_blocked_off_topic_terms() -> None:
    score = score_pin_relevance(
        "ensalada de garbanzos",
        alt_text="outfit de verano moda nails",
        href="/pin/123456789012345678/",
        expected_terms=["ensalada", "garbanzos"],
        blocked_terms=["outfit", "moda", "nails"],
    )

    assert score < 2


@pytest.mark.unit
def test_relevance_requires_actual_keyword_match_not_only_context_terms() -> None:
    assert not is_relevant_recipe_pin(
        "ensalada de garbanzos",
        alt_text="Receta mediterranea saludable con verduras frescas",
        href="/pin/123456789012345678/",
        expected_terms=["receta", "mediterranea", "saludable"],
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "title", ["Pastel de zanahoria sin horno", "Tarta de limón SIN HORNO cremosa y fácil"]
)
def test_generated_campaign_queries_retain_required_no_oven_modifier(title: str) -> None:
    brief = build_recipe_image_scrape_brief(title)
    assert "sin horno" in brief["search_query"]
    assert all("sin horno" in query for query in brief["search_queries"])
    assert "horno" not in brief["core_terms"]


@pytest.mark.unit
def test_relevance_rejects_generic_recipe_with_wrong_core_ingredient() -> None:
    assert not is_relevant_recipe_pin(
        "ensalada de garbanzos",
        alt_text="Ensalada Cesar facil con pollo",
        description="Receta saludable para cenar",
        href="/pin/123456789012345678/",
        core_terms=["garbanzos"],
        expected_terms=["ensalada", "garbanzos", "saludable"],
    )


@pytest.mark.unit
def test_relevance_uses_title_description_and_board_metadata() -> None:
    score = score_pin_relevance(
        "aperitivos de calabacin en freidora de aire",
        alt_text="Idea crujiente",
        href="/pin/123456789012345678/",
        title="Calabacin crujiente en air fryer",
        description="Aperitivo facil preparado en freidora de aire",
        board_name="Aperitivos y Tapas",
        core_terms=["calabacin"],
        expected_terms=["aperitivos", "calabacin", "freidora"],
    )

    assert score >= 8


@pytest.mark.unit
def test_relevance_rejects_wrong_ingredient_with_same_cooking_method() -> None:
    assert not is_relevant_recipe_pin(
        "aperitivos de calabacin en freidora de aire",
        alt_text="Pollo crujiente en freidora de aire",
        description="Receta facil para air fryer",
        core_terms=["calabacin"],
        expected_terms=["aperitivos", "calabacin", "freidora", "aire"],
    )


@pytest.mark.unit
def test_long_turron_title_accepts_dish_match_and_rejects_occasion_only_pin() -> None:
    title = "Tarta cremosa de turrón para fin de año"
    brief = build_recipe_image_scrape_brief(title, category="Postres de Navidad")

    assert is_relevant_recipe_pin(
        title,
        alt_text="Tarta de turrón blando con almendras",
        description="Receta de postre navideño",
        href="/pin/123456789012345678/",
        core_terms=brief["core_terms"],
        min_core_matches=brief["min_core_matches"],
        expected_terms=brief["expected_terms"],
        blocked_terms=brief["blocked_terms"],
    )
    assert not is_relevant_recipe_pin(
        title,
        alt_text="Mesa elegante para fin de año",
        description="Ideas cremosas para Navidad",
        href="/pin/123456789012345679/",
        core_terms=brief["core_terms"],
        min_core_matches=brief["min_core_matches"],
        expected_terms=brief["expected_terms"],
        blocked_terms=brief["blocked_terms"],
    )


@pytest.mark.unit
def test_native_sources_are_augmented_to_campaign_target(tmp_path) -> None:
    source = tmp_path / "native-01-hero.jpg"
    Image.new("RGB", (800, 1200), (220, 80, 60)).save(source)
    sources = [
        {
            "pin_id": "native-01",
            "raw_path": str(source),
            "provider": "test-image-provider",
        }
    ]

    result = _augment_native_sources("pastel de limon", sources, 5)

    assert len(result) == 5
    assert len({item["raw_path"] for item in result}) == 5
    assert all(Image.open(item["raw_path"]).size == (800, 1200) for item in result)
    assert result[-1]["source"] == "native_augmented"

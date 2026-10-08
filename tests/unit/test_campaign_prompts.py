from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import SecretStr

from rankstein.domain import Domain
from rankstein.prompts import (
    build_recipe_image_scrape_brief,
    build_recipe_visual_brief,
    is_recipe_aware_keyword,
)


def _domain() -> Domain:
    return Domain(
        handle="recetatest",
        domain="recetatest.example",
        display_name="Receta Test",
        language="es",
        niche="recetas mediterraneas saludables",
        root=Path("."),
        keywords_file=Path("keywords.md"),
        sessions_dir=Path("sessions"),
        output_dir=Path("output"),
        branding_dir=Path("branding"),
        pinterest_email="user@example.com",
        pinterest_password=SecretStr("secret"),
        supabase_url="https://supabase.example",
        supabase_service_role_key=SecretStr("service-role"),
        categories=("Ensaladas", "Pescados"),
    )


@pytest.mark.unit
def test_scrape_brief_keeps_queries_short_without_domain_niche_suffix() -> None:
    brief = build_recipe_image_scrape_brief("ensalada de garbanzos", domain=_domain(), category="Ensaladas")

    assert brief["search_query"] == "ensalada de garbanzos"
    assert "ensalada" in brief["expected_terms"]
    assert "mediterraneas" not in brief["expected_terms"]
    assert all("recetas mediterraneas saludables" not in query for query in brief["search_queries"])
    assert brief["core_terms"] == ["garbanzos"]
    assert brief["min_core_matches"] == 1
    assert brief["search_queries"][0] == "ensalada de garbanzos"
    assert "receta ensalada de garbanzos" in brief["search_queries"]
    assert "outfit" in brief["blocked_terms"]
    assert brief["domain_handle"] == "recetatest"


@pytest.mark.unit
def test_scrape_brief_normalizes_accented_terms_for_workers() -> None:
    domain = replace(_domain(), niche="recetas españolas tradicionales")
    brief = build_recipe_image_scrape_brief("tortilla española", domain=domain, category="Recetas Españolas")

    assert brief["search_query"] == "tortilla espanola"
    assert "espanola" in brief["expected_terms"]
    assert "espanolas" in brief["expected_terms"]


@pytest.mark.unit
def test_scrape_brief_repairs_legacy_mojibake_terms() -> None:
    mojibake_niche = "recetas espa\u00f1olas tradicionales".encode().decode("latin1")
    domain = replace(_domain(), niche=mojibake_niche)
    brief = build_recipe_image_scrape_brief("carne estofada", domain=domain, category="Carnes")

    assert brief["search_query"] == "carne estofada"
    assert all("espanolas tradicionales" not in query for query in brief["search_queries"])


@pytest.mark.unit
def test_scrape_brief_excludes_cooking_method_from_core_identity() -> None:
    brief = build_recipe_image_scrape_brief(
        "aperitivos de calabacin en freidora de aire",
        domain=_domain(),
        category="Aperitivos",
    )

    assert brief["core_terms"] == ["calabacin"]
    assert brief["min_core_matches"] == 1


@pytest.mark.unit
def test_scrape_brief_reduces_long_occasion_title_to_dish_and_ingredient() -> None:
    brief = build_recipe_image_scrape_brief(
        "Tarta cremosa de turrón para fin de año",
        domain=_domain(),
        category="Postres de Navidad",
    )

    assert brief["search_query"] == "tarta de turron"
    assert brief["core_terms"] == ["turron"]
    assert brief["min_core_matches"] == 1
    assert brief["search_queries"][0] == "tarta de turron"
    assert "receta tarta de turron" in brief["search_queries"]
    assert not ({"cremosa", "fin", "ano", "navidad"} & set(brief["core_terms"]))


@pytest.mark.unit
def test_visual_brief_contains_recipe_image_contract_basics() -> None:
    brief = build_recipe_visual_brief("pollo al ajillo", domain=_domain(), asset_type="pinterest_pin")

    assert brief["aspect_ratio"] == "2:3"
    assert "finished dish" in brief["prompt"]
    assert "No embedded text" in brief["prompt"]
    assert brief["negative_prompt"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "keyword",
    [
        "pastel de limon y mascarpone",
        "ensalada de garbanzos crujientes",
        "paella de marisco paso a paso",
        "tostas de pimiento asado y queso",
    ],
)
def test_recipe_keyword_gate_accepts_real_dishes(keyword: str) -> None:
    assert is_recipe_aware_keyword(keyword, domain=_domain()) is True


@pytest.mark.unit
@pytest.mark.parametrize(
    "keyword",
    [
        "decorated in pastel colors",
        "pastel aesthetic wallpaper",
        "wedding decor ideas",
        "a chocolate cake with strawberries on top",
        "De chocolate",
    ],
)
def test_recipe_keyword_gate_rejects_design_and_ui_phrases(keyword: str) -> None:
    assert is_recipe_aware_keyword(keyword, domain=_domain()) is False

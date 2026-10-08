from __future__ import annotations

import json
from pathlib import Path

import pytest

from rankstein.category_policy import CategoryPolicyError, assign_article_category

ROOT = Path(__file__).resolve().parents[2]
DOLCE_CATEGORIES = (
    "fresas-y-nata",
    "tartas-y-pasteles",
    "chocolates",
    "dulces-saludables",
)
GENIAL_CATEGORIES = (
    "Aperitivos",
    "Arroces",
    "Postres",
    "Carnes",
    "Pescados",
    "Ensaladas",
)


@pytest.mark.unit
def test_dolce_chocolate_title_overrides_legacy_llm_label() -> None:
    assignment = assign_article_category(
        domain_handle="recetadolce",
        categories=DOLCE_CATEGORIES,
        requested="Pasteles",
        context="Bizcocho de chocolate para cumpleanos",
    )

    assert assignment.category == "chocolates"
    assert assignment.category_id == "75af6eb9-24e7-4dc8-823d-c0aa73b2f878"


@pytest.mark.unit
def test_dolce_healthy_dessert_uses_healthy_collection() -> None:
    assignment = assign_article_category(
        domain_handle="recetadolce",
        categories=DOLCE_CATEGORIES,
        requested="Galletas",
        context="Galletas de avena saludables sin azucar",
    )

    assert assignment.category == "dulces-saludables"


@pytest.mark.unit
@pytest.mark.parametrize(
    "title",
    [
        "Croquetas caseras de jamon",
        "Pasteles salados de hojaldre con espinacas",
        "Recetas rapidas para cada dia",
    ],
)
def test_dolce_rejects_savory_or_uncategorized_content(title: str) -> None:
    with pytest.raises(CategoryPolicyError):
        assign_article_category(
            domain_handle="recetadolce",
            categories=DOLCE_CATEGORIES,
            requested="Pasteles",
            context=title,
        )


@pytest.mark.unit
def test_genial_semantic_category_overrides_requested_label() -> None:
    assignment = assign_article_category(
        domain_handle="recetagenial",
        categories=GENIAL_CATEGORIES,
        requested="Aperitivos",
        context="Arroz negro con sepia y alioli",
    )

    assert assignment.category == "Arroces"


@pytest.mark.unit
def test_production_manifests_match_public_taxonomies() -> None:
    dolce = json.loads((ROOT / "data/domains/recetadolce/domain.json").read_text(encoding="utf-8"))
    genial = json.loads((ROOT / "data/domains/recetagenial/domain.json").read_text(encoding="utf-8"))

    assert tuple(dolce["categories"]) == DOLCE_CATEGORIES
    assert tuple(genial["categories"]) == GENIAL_CATEGORIES

import asyncio
from types import SimpleNamespace

from backend.scripts.turbo_articles import _deterministic_publication
from backend.services.news_scraper import validate_article


def _long_content(extra: str = "") -> str:
    paragraph = (
        "En mi cocina he probado esta receta con calma para ajustar textura, punto de sal "
        "y seguridad alimentaria según AESAN y EFSA. Recomiendo preparar todos los ingredientes, "
        "cocinar sin prisa y probar en varios momentos para lograr un resultado estable. "
    )
    return "## Introducción\n" + (paragraph * 25) + extra


def _base_article(content: str, *, ingredients=None, instructions=None) -> dict:
    ingredients = ingredients or [
        "500 g de tomates maduros",
        "2 dientes de ajo",
        "3 cucharadas de aceite de oliva virgen extra",
        "1 cebolla mediana",
        "Sal fina y pimienta negra",
    ]
    instructions = instructions or [
        {"@type": "HowToStep", "text": "Lava y corta los tomates."},
        {"@type": "HowToStep", "text": "Sofríe la cebolla con aceite."},
        {"@type": "HowToStep", "text": "Añade el ajo y remueve sin quemarlo."},
        {"@type": "HowToStep", "text": "Incorpora el tomate y cocina a fuego medio."},
        {"@type": "HowToStep", "text": "Ajusta sal, reposa y sirve."},
    ]
    return {
        "content": content,
        "excerpt": "Receta clara con ingredientes medibles, pasos útiles y consejos seguros.",
        "category": "Aperitivos",
        "recipe_schema": {
            "@context": "https://schema.org",
            "@type": "Recipe",
            "name": "Tomates guisados",
            "description": "Receta paso a paso con ingredientes medibles.",
            "image": ["https://example.com/hero.jpg"],
            "author": {"@type": "Person", "name": "Chef Receta Genial"},
            "prepTime": "PT15M",
            "cookTime": "PT30M",
            "totalTime": "PT45M",
            "recipeYield": "4 raciones",
            "recipeCategory": "Aperitivos",
            "recipeCuisine": "Española",
            "recipeIngredient": ingredients,
            "recipeInstructions": instructions,
        },
        "faq_schema": [
            {"question": "¿Puedo prepararla antes?", "answer": "Sí, conserva la base en frío."},
            {"question": "¿Cómo ajusto la textura?", "answer": "Reduce más tiempo o añade caldo."},
            {"question": "¿Cómo la guardo?", "answer": "En recipiente hermético refrigerado."},
        ],
    }


def test_deterministic_publication_is_disabled():
    domain = SimpleNamespace(handle="recetagenial")

    result = asyncio.run(_deterministic_publication("tomates guisados", "Aperitivos", domain))

    assert result == "Failed"


def test_quality_gate_rejects_non_pinterest_source_blockquotes():
    article = _base_article(_long_content("<blockquote>Texto largo copiado de una fuente.</blockquote>"))

    result = validate_article(article)

    assert result["passed"] is False
    assert any("blockquote" in issue for issue in result["issues"])


def test_quality_gate_rejects_generic_recipe_placeholders():
    article = _base_article(
        _long_content(),
        ingredients=[
            "250 g de ingrediente principal de calidad",
            "120 g de base cremosa o caldo suave",
            "60 g de toque aromático",
            "1 pizca de sal fina",
            "Aceite de oliva virgen extra o mantequilla, al gusto",
        ],
        instructions=[
            {"@type": "HowToStep", "text": "Cocina la base a fuego medio."},
            {"@type": "HowToStep", "text": "Integra el ingrediente principal poco a poco."},
            {"@type": "HowToStep", "text": "Ajusta sal y temperatura."},
            {"@type": "HowToStep", "text": "Deja reposar."},
            {"@type": "HowToStep", "text": "Sirve al final."},
        ],
    )

    result = validate_article(article)

    assert result["passed"] is False
    assert any("placeholder" in issue for issue in result["issues"])

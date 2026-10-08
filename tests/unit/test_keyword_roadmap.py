from __future__ import annotations

from pathlib import Path

import pytest

from backend.scripts.turbo_articles import (
    _OPENCODE_FALLBACK_MODELS,
    _OPENROUTER_FALLBACK_MODELS,
    _is_retryable_model_error,
    _openrouter_article_quality_check,
    _parse_llm_json_response,
    _status_from_completion_output,
    _strip_gemini_cli_noise,
)
from rankstein.keyword_roadmap import (
    KeywordRow,
    append_keyword_rows,
    clean_keyword_roadmap,
    mark_keyword_status,
    read_keyword_rows,
    reserve_pending_keywords,
    write_keyword_rows,
)


@pytest.mark.unit
def test_clean_keyword_roadmap_dedupes_resets_and_marks_db_live(tmp_path: Path) -> None:
    path = tmp_path / "keywords.md"
    write_keyword_rows(
        path,
        "Test Roadmap",
        [
            KeywordRow("Tarta Opera", "Postres", status="In Progress"),
            KeywordRow("tarta opera", "Postres", status="Pending"),
            KeywordRow("Gazpacho", "Ensaladas", status="Pending"),
        ],
    )

    report = clean_keyword_roadmap(path, "Test Roadmap", {"Gazpacho"})
    rows = read_keyword_rows(path)

    assert report["duplicates_removed"] == 1
    assert report["reset_in_progress"] == 1
    assert report["marked_live_from_db"] == 1
    assert [(row.keyword, row.status) for row in rows] == [
        ("Tarta Opera", "Pending"),
        ("Gazpacho", "Live"),
    ]


@pytest.mark.unit
def test_reserve_pending_keywords_marks_selected_rows_in_progress(tmp_path: Path) -> None:
    path = tmp_path / "keywords.md"
    write_keyword_rows(
        path,
        "Test Roadmap",
        [
            KeywordRow("One", status="Pending"),
            KeywordRow("Two", status="Pending"),
            KeywordRow("Three", status="Pending"),
        ],
    )

    selected = reserve_pending_keywords(path, "Test Roadmap", 2)
    rows = read_keyword_rows(path)

    assert [row.keyword for row in selected] == ["One", "Two"]
    assert [row.status for row in rows] == ["In Progress", "In Progress", "Pending"]


@pytest.mark.unit
def test_reserve_pending_keywords_can_require_research_eligibility(tmp_path: Path) -> None:
    path = tmp_path / "keywords.md"
    write_keyword_rows(
        path,
        "Test Roadmap",
        [
            KeywordRow("vague old keyword", status="Pending"),
            KeywordRow("Tarta de queso pistacho", status="Pending"),
            KeywordRow("Galletas de limon crujientes", status="Pending"),
        ],
    )

    selected = reserve_pending_keywords(
        path,
        "Test Roadmap",
        2,
        eligible_keywords={"tarta de queso pistacho"},
    )
    rows = read_keyword_rows(path)

    assert [row.keyword for row in selected] == ["Tarta de queso pistacho"]
    assert [row.status for row in rows] == ["Pending", "In Progress", "Pending"]


@pytest.mark.unit
def test_mark_keyword_status_updates_one_row(tmp_path: Path) -> None:
    path = tmp_path / "keywords.md"
    write_keyword_rows(path, "Test Roadmap", [KeywordRow("One", status="Pending")])

    assert mark_keyword_status(path, "Test Roadmap", "one", "Live") is True
    assert read_keyword_rows(path)[0].status == "Live"
    assert mark_keyword_status(path, "Test Roadmap", "missing", "Live") is False


@pytest.mark.unit
def test_append_keyword_rows_only_adds_unique_keywords(tmp_path: Path) -> None:
    path = tmp_path / "keywords.md"
    write_keyword_rows(path, "Test Roadmap", [KeywordRow("Tarta Opera", status="Pending")])

    added = append_keyword_rows(
        path,
        "Test Roadmap",
        [
            KeywordRow("tarta opera", status="Pending"),
            KeywordRow("Gazpacho facil", cluster="Aperitivos", status="Pending"),
        ],
    )

    rows = read_keyword_rows(path)
    assert added == 1
    assert [row.keyword for row in rows] == ["Tarta Opera", "Gazpacho facil"]


@pytest.mark.unit
def test_append_keyword_rows_refreshes_pending_research_metadata(tmp_path: Path) -> None:
    path = tmp_path / "keywords.md"
    write_keyword_rows(
        path,
        "Test Roadmap",
        [KeywordRow("Tarta de queso pistacho", source="Startup", priority="Medium")],
    )

    added = append_keyword_rows(
        path,
        "Test Roadmap",
        [
            KeywordRow(
                "Tarta de queso pistacho",
                cluster="Postres",
                source="Pinterest Trends + Google Autocomplete Demand",
                target_blog="Receta Dolce",
                priority="High",
            )
        ],
    )
    row = read_keyword_rows(path)[0]

    assert added == 0
    assert row.cluster == "Postres"
    assert row.source == "Pinterest Trends + Google Autocomplete Demand"
    assert row.target_blog == "Receta Dolce"
    assert row.priority == "High"


@pytest.mark.unit
@pytest.mark.parametrize("status", ["Failed", "Needs Verification", "Staged", "In Progress", "Live"])
def test_append_keyword_rows_preserves_existing_terminal_and_published_states(
    tmp_path: Path, status: str
) -> None:
    path = tmp_path / "keywords.md"
    write_keyword_rows(
        path,
        "Test Roadmap",
        [
            KeywordRow("Tarta Opera", cluster="Old", source="Old", priority="Low", status=status),
            KeywordRow("Gazpacho", status="Live"),
        ],
    )

    changed = append_keyword_rows(
        path,
        "Test Roadmap",
        [
            KeywordRow(
                "tarta opera",
                cluster="Postres",
                source="Pinterest Trends + Google News",
                target_blog="Receta Dolce",
                priority="High",
                status="Pending",
            ),
            KeywordRow("Gazpacho", status="Pending"),
        ],
    )

    rows = read_keyword_rows(path)
    assert changed == 0
    assert [(row.keyword, row.cluster, row.source, row.priority, row.status) for row in rows] == [
        ("Tarta Opera", "Old", "Old", "Low", status),
        ("Gazpacho", "General", "Startup", "Medium", "Live"),
    ]


@pytest.mark.unit
def test_completion_output_requires_full_publication_proof() -> None:
    assert (
        _status_from_completion_output(
            '{"supabase_published": true, "pinterest_uploaded": true, "pin_linked": true}'
        )
        == "Live"
    )
    assert (
        _status_from_completion_output(
            '{"supabase_published": true, "pinterest_uploaded": false, "pin_linked": true}'
        )
        == "Needs Verification"
    )
    assert _status_from_completion_output("gemini completed without proof") == "Needs Verification"


@pytest.mark.unit
def test_model_capacity_errors_are_retryable() -> None:
    assert _is_retryable_model_error("MODEL_CAPACITY_EXHAUSTED")
    assert _is_retryable_model_error("No capacity available for model gemini-2.5-flash")
    assert _is_retryable_model_error("Warning: True color (24-bit) support not detected.\nQUOTA_EXHAUSTED")
    assert not _is_retryable_model_error("invalid argument")


@pytest.mark.unit
def test_gemini_cli_terminal_warning_is_cosmetic_noise() -> None:
    warning = (
        "Warning: True color (24-bit) support not detected. "
        "Using a terminal with true color enabled will result in a better visual experience."
    )
    assert _strip_gemini_cli_noise(warning) == ""
    assert _strip_gemini_cli_noise(f"{warning}\nreal failure") == "real failure"


# ——————————————————————— OpenRouter fallback tests ———————————————————————


@pytest.mark.unit
def test_openrouter_article_fallback_models_are_disabled() -> None:
    assert _OPENROUTER_FALLBACK_MODELS == []


@pytest.mark.unit
def test_openrouter_article_quality_check_passes_good_article() -> None:
    article = {
        "title": "Receta Tradicional",
        "slug": "receta-tradicional",
        "content": (
            "## Ingredientes\nAquí tienes los ingredientes para esta receta tradicional. "
            "Preparación paso a paso con los mejores consejos de cocina.\n\n"
            "* 200 g de harina de trigo\n"
            "* 3 huevos frescos\n"
            "* 100 ml de leche entera\n"
            "* Sal y pimienta al gusto\n\n"
            "## Preparación\nPaso 1: Mezcla todos los ingredientes en un bol. "
            "Paso 2: Cocina a fuego medio durante 15 minutos. "
            "Paso 3: Deja reposar antes de servir. "
            "Este plato es perfecto para cualquier ocasión."
        ),
        "excerpt": "Una receta tradicional deliciosa y fácil.",
        "category": "Postres",
        "recipe_schema": {
            "recipeIngredient": [
                "200 g de harina de trigo",
                "3 huevos frescos",
                "100 ml de leche entera",
            ],
            "recipeInstructions": [
                {"@type": "HowToStep", "text": "Mezcla los ingredientes secos."},
                {"@type": "HowToStep", "text": "Añade los líquidos y bate."},
                {"@type": "HowToStep", "text": "Cocina hasta que esté dorado."},
            ],
        },
    }
    article["content"] += (
        " Serve each portion warm, store leftovers safely, and reheat them gently. "
        "The finished dish should be golden outside and tender inside."
    )
    assert _openrouter_article_quality_check(article) is True


@pytest.mark.unit
def test_openrouter_article_quality_check_rejects_placeholder_content() -> None:
    article = {
        "content": ("Esta receta usa ingrediente principal como base. Cocina la base a fuego medio. "),
        "recipe_schema": {
            "recipeIngredient": ["ingrediente principal"],
            "recipeInstructions": [
                {"@type": "HowToStep", "text": "Cocina la base."},
            ],
        },
    }
    assert _openrouter_article_quality_check(article) is False


@pytest.mark.unit
def test_openrouter_article_quality_check_rejects_too_short_content() -> None:
    article = {
        "content": "Muy corto.",
        "recipe_schema": {
            "recipeIngredient": [],
            "recipeInstructions": [],
        },
    }
    assert _openrouter_article_quality_check(article) is False


# ——————————————————————— OpenCode / parsing tests ———————————————————————


@pytest.mark.unit
def test_opencode_article_fallback_models_are_disabled() -> None:
    assert _OPENCODE_FALLBACK_MODELS == []


@pytest.mark.unit
def test_parse_llm_json_response_good_json() -> None:
    long_content = "Receta tradicional paso a paso. " * 40  # ~1200 chars
    article = _parse_llm_json_response(
        '{"title": "Tarta de Manzana", "slug": "tarta-de-manzana", '
        f'"content": "{long_content}", "excerpt": "excerpt", '
        '"category": "Postres", "recipe_schema": {"name": "test"}}'
    )
    assert article is not None
    assert article["title"] == "Tarta de Manzana"


@pytest.mark.unit
def test_parse_llm_json_response_with_markdown_fences() -> None:
    long_content = "Flan casero tradicional. " * 40
    article = _parse_llm_json_response(
        "```json\n"
        '{"title": "Flan", "slug": "flan", '
        f'"content": "{long_content}", "excerpt": "excerpt", '
        '"category": "Postres", "recipe_schema": {}}\n'
        "```"
    )
    assert article is not None
    assert article["title"] == "Flan"


@pytest.mark.unit
def test_parse_llm_json_response_too_short() -> None:
    assert _parse_llm_json_response('{"title": "x"}') is None


@pytest.mark.unit
def test_parse_llm_json_response_invalid_json() -> None:
    assert _parse_llm_json_response("not json") is None


@pytest.mark.unit
def test_parse_llm_json_response_missing_keys() -> None:
    """Missing required keys like 'recipe_schema' should return None."""
    long_content = "Contenido suficiente pero sin schema. " * 30
    assert (
        _parse_llm_json_response(
            '{"title": "Tarta", "slug": "tarta", '
            f'"content": "{long_content}", "excerpt": "excerpt", '
            '"category": "Postres"}'
        )
        is None
    )

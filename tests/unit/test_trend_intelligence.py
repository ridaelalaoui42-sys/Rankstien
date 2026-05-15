from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from rankstein.domain import Domain
from rankstein.keyword_roadmap import KeywordRow, read_keyword_rows, write_keyword_rows
from rankstein.trend_intelligence import (
    NewsSignal,
    _pinterest_seed_queries,
    refresh_domain_trend_lists,
)


def _domain(tmp_path: Path) -> Domain:
    root = tmp_path / "recetadolce"
    keywords_file = root / "keywords.md"
    write_keyword_rows(keywords_file, "Receta Dolce Keyword Roadmap", [KeywordRow("tarta opera")])
    return Domain(
        handle="recetadolce",
        domain="recetadolce.com",
        display_name="Receta Dolce",
        language="es",
        niche="pasteleria gourmet espanola",
        root=root,
        keywords_file=keywords_file,
        sessions_dir=root / "sessions",
        output_dir=root / "output",
        branding_dir=root / "branding",
        pinterest_email="user@example.com",
        pinterest_password=SecretStr("secret"),
        supabase_url="https://supabase.example",
        supabase_service_role_key=SecretStr("service-role"),
        categories=("Postres", "Pasteles", "Galletas"),
    )


@pytest.mark.unit
def test_refresh_domain_trend_lists_writes_daily_best_and_appends_unique_rows(tmp_path: Path) -> None:
    domain = _domain(tmp_path)

    def fake_news(keyword: str, language: str, region: str, limit: int) -> list[NewsSignal]:
        return [NewsSignal(title=f"{keyword} noticia {idx}") for idx in range(2)]

    report = refresh_domain_trend_lists(
        [domain],
        limit_per_domain=3,
        append_to_roadmap=True,
        pinterest_terms=["tarta opera", "tarta de queso", "galletas caseras", "ideas de jardin"],
        google_news_provider=fake_news,
        use_playwright=False,
    )

    rows = read_keyword_rows(domain.keywords_file)
    assert report["domains"]["recetadolce"]["roadmap_added"] == 2
    assert (domain.root / "daily_best_keywords.json").exists()
    assert (domain.root / "daily_best_keywords.md").exists()
    assert {row.keyword for row in rows} == {"tarta opera", "tarta de queso", "galletas caseras"}


@pytest.mark.unit
def test_pinterest_seed_queries_include_domain_categories_and_niche(tmp_path: Path) -> None:
    seeds = {seed.casefold() for seed in _pinterest_seed_queries(_domain(tmp_path))}

    assert "postres recetas" in seeds
    assert "pasteles ideas" in seeds
    assert "postres gourmet" in seeds

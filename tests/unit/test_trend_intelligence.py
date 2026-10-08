from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from io import BytesIO, TextIOWrapper
from pathlib import Path

import pytest
from pydantic import SecretStr

import rankstein.trend_intelligence as trend_intelligence
from rankstein.domain import Domain
from rankstein.keyword_roadmap import KeywordRow, read_keyword_rows, write_keyword_rows
from rankstein.trend_intelligence import (
    NewsSignal,
    _compose_pinterest_suggestion,
    _keyword_specificity_score,
    _pinterest_candidates_from_visible_items,
    _pinterest_seed_queries,
    _round_robin_pinterest_batches,
    _trend_browser_profile,
    load_qualified_keyword_keys,
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
        search_volume_provider=lambda *args: 8.0,
        google_news_discovery_provider=lambda *args: [],
        google_trends_provider=lambda *args: [],
        google_suggest_provider=lambda *args: [],
        use_playwright=False,
    )

    rows = read_keyword_rows(domain.keywords_file)
    assert report["domains"]["recetadolce"]["roadmap_added"] == 2
    assert (domain.root / "daily_best_keywords.json").exists()
    assert (domain.root / "daily_best_keywords.md").exists()
    assert {row.keyword for row in rows} == {"tarta opera", "tarta de queso", "galletas caseras"}


@pytest.mark.unit
def test_refresh_accepts_independent_google_candidates_when_pinterest_is_empty(
    tmp_path: Path,
) -> None:
    domain = _domain(tmp_path)
    write_keyword_rows(domain.keywords_file, "Receta Dolce Keyword Roadmap", [])

    def no_news_validation(keyword: str, language: str, region: str, limit: int) -> list[NewsSignal]:
        return []

    report = refresh_domain_trend_lists(
        [domain],
        limit_per_domain=3,
        append_to_roadmap=True,
        pinterest_terms=[],
        google_news_provider=no_news_validation,
        search_volume_provider=lambda *args: 8.0,
        google_news_discovery_provider=lambda *args: ["galletas de limon crujientes"],
        google_trends_provider=lambda *args: ["helado de melocoton casero"],
        google_suggest_provider=lambda *args: ["tarta de pistacho y frambuesa"],
        use_playwright=False,
    )

    rows = read_keyword_rows(domain.keywords_file)
    pending = {row.keyword: row.source for row in rows if row.status == "Pending"}
    domain_report = report["domains"]["recetadolce"]
    assert domain_report["roadmap_added"] == 3
    assert domain_report["research_status"] == "qualified"
    assert {item["keyword"] for item in domain_report["daily_best"]} == {
        "galletas de limon crujientes",
        "helado de melocoton casero",
        "tarta de pistacho y frambuesa",
    }
    assert all(item["pinterest_origin"] is False for item in domain_report["daily_best"])
    assert "Google News" in pending["galletas de limon crujientes"]
    assert "Google Trends" in pending["helado de melocoton casero"]
    assert "Google Suggestions" in pending["tarta de pistacho y frambuesa"]

    eligible, reason = load_qualified_keyword_keys(domain)
    assert eligible == {
        "galletas de limon crujientes",
        "helado de melocoton casero",
        "tarta de pistacho y frambuesa",
    }
    assert reason == "ok"


@pytest.mark.unit
def test_pinterest_required_policy_rejects_google_only_candidates(tmp_path: Path) -> None:
    domain = _domain(tmp_path)
    write_keyword_rows(domain.keywords_file, "Receta Dolce Keyword Roadmap", [])

    report = refresh_domain_trend_lists(
        [domain],
        limit_per_domain=3,
        append_to_roadmap=True,
        pinterest_terms=[],
        google_news_provider=lambda *args: [],
        search_volume_provider=lambda *args: 8.0,
        google_news_discovery_provider=lambda *args: ["galletas de limon crujientes"],
        google_trends_provider=lambda *args: ["helado de melocoton casero"],
        google_suggest_provider=lambda *args: ["tarta de pistacho y frambuesa"],
        candidate_origin_policy="pinterest_required",
        use_playwright=False,
    )

    domain_report = report["domains"]["recetadolce"]
    assert domain_report["roadmap_added"] == 0
    assert domain_report["research_status"] == "blocked_no_pinterest_terms"
    assert domain_report["daily_best"] == []
    assert read_keyword_rows(domain.keywords_file) == []


@pytest.mark.unit
def test_pinterest_required_policy_allows_only_exact_google_corroboration(
    tmp_path: Path,
) -> None:
    domain = _domain(tmp_path)
    write_keyword_rows(domain.keywords_file, "Receta Dolce Keyword Roadmap", [])

    report = refresh_domain_trend_lists(
        [domain],
        limit_per_domain=3,
        append_to_roadmap=False,
        pinterest_terms=["tarta de queso pistacho"],
        google_news_provider=lambda *args: [],
        search_volume_provider=lambda *args: 8.0,
        google_news_discovery_provider=lambda *args: [
            "tarta de queso pistacho",
            "galletas de limon crujientes",
        ],
        google_trends_provider=lambda *args: ["helado de melocoton casero"],
        google_suggest_provider=lambda *args: ["bizcocho de naranja esponjoso"],
        candidate_origin_policy="pinterest_required",
        use_playwright=False,
    )

    domain_report = report["domains"]["recetadolce"]
    assert [item["keyword"] for item in domain_report["daily_best"]] == ["tarta de queso pistacho"]
    assert domain_report["candidate_origin_policy"] == "pinterest_required"
    assert "Pinterest Trends" in domain_report["daily_best"][0]["source"]
    assert "Google News" in domain_report["daily_best"][0]["source"]

    payload = json.loads(Path(domain_report["output_json"]).read_text(encoding="utf-8"))
    assert payload["methodology"]["candidate_origin"] == "Pinterest Trends/Search only"


@pytest.mark.unit
def test_refresh_merges_independent_candidates_and_tracks_corroborated_provenance(
    tmp_path: Path,
) -> None:
    domain = _domain(tmp_path)
    write_keyword_rows(domain.keywords_file, "Receta Dolce Keyword Roadmap", [])
    demand_calls: list[str] = []

    def fake_demand(keyword: str, language: str, region: str) -> float:
        demand_calls.append(keyword)
        return {"tarta de queso pistacho": 8.0, "galletas de limon crujientes": 0.0}.get(
            keyword,
            8.0,
        )

    report = refresh_domain_trend_lists(
        [domain],
        limit_per_domain=5,
        append_to_roadmap=True,
        pinterest_terms=[
            "postres faciles y rapidos",
            "tarta de queso pistacho",
            "galletas de limon crujientes",
        ],
        google_news_provider=lambda *args: [],
        search_volume_provider=fake_demand,
        google_news_discovery_provider=lambda *args: [
            "helado de melocoton casero",
            "tarta de queso pistacho",
        ],
        google_trends_provider=lambda *args: ["flan de cafe cremoso"],
        google_suggest_provider=lambda *args: ["bizcocho de naranja esponjoso"],
        use_playwright=False,
    )

    daily_best = report["domains"]["recetadolce"]["daily_best"]
    rows = read_keyword_rows(domain.keywords_file)

    by_keyword = {item["keyword"]: item for item in daily_best}
    assert set(by_keyword) == {
        "tarta de queso pistacho",
        "helado de melocoton casero",
        "flan de cafe cremoso",
        "bizcocho de naranja esponjoso",
    }
    assert by_keyword["tarta de queso pistacho"]["pinterest_origin"] is True
    assert by_keyword["tarta de queso pistacho"]["qualified"] is True
    assert by_keyword["tarta de queso pistacho"]["search_demand_score"] == 8.0
    assert "Pinterest Trends" in by_keyword["tarta de queso pistacho"]["source"]
    assert "Google News" in by_keyword["tarta de queso pistacho"]["source"]
    assert by_keyword["helado de melocoton casero"]["pinterest_origin"] is False
    assert "Google News" in by_keyword["helado de melocoton casero"]["source"]
    assert "Google Trends" in by_keyword["flan de cafe cremoso"]["source"]
    assert "Google Suggestions" in by_keyword["bizcocho de naranja esponjoso"]["source"]
    assert "galletas de limon crujientes" not in {row.keyword for row in rows}
    assert set(demand_calls) == {
        "tarta de queso pistacho",
        "galletas de limon crujientes",
        "helado de melocoton casero",
        "flan de cafe cremoso",
        "bizcocho de naranja esponjoso",
    }


@pytest.mark.unit
def test_refresh_is_resilient_when_individual_discovery_sources_fail(tmp_path: Path) -> None:
    domain = _domain(tmp_path)
    write_keyword_rows(domain.keywords_file, "Receta Dolce Keyword Roadmap", [])

    def broken_provider(*args: object) -> list[str]:
        raise RuntimeError("source unavailable")

    report = refresh_domain_trend_lists(
        [domain],
        limit_per_domain=5,
        append_to_roadmap=True,
        pinterest_terms=["tarta de queso pistacho"],
        google_news_provider=lambda *args: [],
        search_volume_provider=lambda *args: 8.0,
        google_news_discovery_provider=broken_provider,
        google_trends_provider=lambda *args: ["flan de cafe cremoso"],
        google_suggest_provider=broken_provider,
        use_playwright=False,
    )

    domain_report = report["domains"]["recetadolce"]
    assert {item["keyword"] for item in domain_report["daily_best"]} == {
        "tarta de queso pistacho",
        "flan de cafe cremoso",
    }
    assert domain_report["sources"] == {
        "Pinterest Trends": 1,
        "Google News": 0,
        "Google Trends": 1,
        "Google Suggestions": 0,
    }
    assert domain_report["research_status"] == "qualified"


@pytest.mark.unit
def test_refresh_uses_all_discovery_providers_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    domain = _domain(tmp_path)
    write_keyword_rows(domain.keywords_file, "Receta Dolce Keyword Roadmap", [])
    calls: list[tuple[str, str]] = []

    def fake_discovery(source: str, keyword: str):
        def discover(target: Domain, language: str, region: str, limit: int) -> list[str]:
            assert target is domain
            assert language == "es"
            assert region == "ES"
            assert limit == 12
            calls.append((source, target.handle))
            return [keyword]

        return discover

    monkeypatch.setattr(
        trend_intelligence,
        "fetch_google_news_discovery_terms",
        fake_discovery("Google News", "galletas de limon crujientes"),
    )
    monkeypatch.setattr(
        trend_intelligence,
        "fetch_google_trending_terms",
        fake_discovery("Google Trends", "helado de melocoton casero"),
    )
    monkeypatch.setattr(
        trend_intelligence,
        "fetch_google_autocomplete_terms",
        fake_discovery("Google Suggestions", "tarta de pistacho y frambuesa"),
    )

    report = refresh_domain_trend_lists(
        [domain],
        limit_per_domain=3,
        append_to_roadmap=False,
        pinterest_terms=[],
        google_news_provider=lambda *args: [],
        search_volume_provider=lambda *args: 8.0,
        use_playwright=False,
    )

    assert set(calls) == {
        ("Google News", "recetadolce"),
        ("Google Trends", "recetadolce"),
        ("Google Suggestions", "recetadolce"),
    }
    assert len(report["domains"]["recetadolce"]["daily_best"]) == 3


@pytest.mark.unit
def test_demand_provider_failure_rejects_only_the_affected_candidate(tmp_path: Path) -> None:
    domain = _domain(tmp_path)
    write_keyword_rows(domain.keywords_file, "Receta Dolce Keyword Roadmap", [])

    def partial_demand(keyword: str, language: str, region: str) -> float:
        if keyword == "galletas de limon crujientes":
            raise RuntimeError("provider unavailable for one candidate")
        return 8.0

    report = refresh_domain_trend_lists(
        [domain],
        limit_per_domain=5,
        append_to_roadmap=True,
        pinterest_terms=["tarta de queso pistacho", "galletas de limon crujientes"],
        google_news_provider=lambda *args: [],
        search_volume_provider=partial_demand,
        google_news_discovery_provider=lambda *args: [],
        google_trends_provider=lambda *args: [],
        google_suggest_provider=lambda *args: [],
        use_playwright=False,
    )

    assert [item["keyword"] for item in report["domains"]["recetadolce"]["daily_best"]] == [
        "tarta de queso pistacho"
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    "keyword",
    [
        "postres faciles y rapidos",
        "ideas de comida",
        "pollo facil",
        "pasteles para mujer",
        "recetas para invitados",
    ],
)
def test_specificity_gate_rejects_vague_keywords(keyword: str) -> None:
    assert _keyword_specificity_score(keyword) == 0.0


@pytest.mark.unit
def test_daily_evidence_authorizes_only_fresh_qualified_keywords(tmp_path: Path) -> None:
    domain = _domain(tmp_path)
    write_keyword_rows(domain.keywords_file, "Receta Dolce Keyword Roadmap", [])
    refresh_domain_trend_lists(
        [domain],
        limit_per_domain=2,
        append_to_roadmap=True,
        pinterest_terms=["tarta de queso pistacho"],
        google_news_provider=lambda *args: [],
        search_volume_provider=lambda *args: 6.0,
        google_news_discovery_provider=lambda *args: [],
        google_trends_provider=lambda *args: [],
        google_suggest_provider=lambda *args: [],
        use_playwright=False,
    )

    eligible, reason = load_qualified_keyword_keys(domain)
    assert eligible == {"tarta de queso pistacho"}
    assert reason == "ok"

    report_path = domain.root / "daily_best_keywords.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["generated_at"] = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    eligible, reason = load_qualified_keyword_keys(domain, max_age_hours=24)
    assert eligible == set()
    assert reason == "stale_keyword_research"


@pytest.mark.unit
def test_refresh_excludes_terminal_duplicates_before_shortlist_limit(tmp_path: Path) -> None:
    domain = _domain(tmp_path)
    write_keyword_rows(
        domain.keywords_file,
        "Receta Dolce Keyword Roadmap",
        [KeywordRow("tarta de queso", status="Live")],
    )

    report = refresh_domain_trend_lists(
        [domain],
        limit_per_domain=1,
        append_to_roadmap=True,
        pinterest_terms=["tarta de queso", "galletas de almendra caseras"],
        google_news_provider=lambda *args: [],
        search_volume_provider=lambda *args: 8.0,
        google_news_discovery_provider=lambda *args: [],
        google_trends_provider=lambda *args: [],
        google_suggest_provider=lambda *args: [],
        use_playwright=False,
    )

    rows = read_keyword_rows(domain.keywords_file)
    assert report["domains"]["recetadolce"]["roadmap_added"] == 1
    assert [(row.keyword, row.status) for row in rows] == [
        ("tarta de queso", "Live"),
        ("galletas de almendra caseras", "Pending"),
    ]


@pytest.mark.unit
def test_pinterest_seed_queries_include_domain_categories_and_niche(tmp_path: Path) -> None:
    seeds = [seed.casefold() for seed in _pinterest_seed_queries(_domain(tmp_path))]

    assert "postres" in seeds
    assert "postres gourmet" in seeds
    assert "tarta de queso" in seeds
    assert all(_keyword_specificity_score(seed) > 0 for seed in seeds[:6])


@pytest.mark.unit
@pytest.mark.parametrize(
    ("query", "suggestion", "expected"),
    [
        ("tarta de queso", "De pistacho", "tarta de queso de pistacho"),
        ("tarta de queso", "tarta de queso vasca", "tarta de queso vasca"),
        ("pollo al horno", "con patatas", "pollo al horno con patatas"),
        ("tarta de queso", "Horno", "tarta de queso al horno"),
        ("tarta de queso", "Vasca receta", "tarta de queso vasca"),
        ("tarta de queso", "Air fryer", "tarta de queso en air fryer"),
    ],
)
def test_compose_pinterest_suggestion_reconstructs_complete_search_phrase(
    query: str,
    suggestion: str,
    expected: str,
) -> None:
    assert _compose_pinterest_suggestion(query, suggestion) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "suggestion",
    [
        "Iniciar sesión",
        "Mostrar filtros",
        "Menos IA",
        "Recetas de",
        "Eliminar texto de la búsqueda",
        "Como hacer",
        "Recipe",
        "Receta",
        "Para perro",
        "Para perros",
    ],
)
def test_compose_pinterest_suggestion_rejects_navigation_and_incomplete_ui(
    suggestion: str,
) -> None:
    assert _compose_pinterest_suggestion("tarta de queso", suggestion) == ""


@pytest.mark.unit
def test_pinterest_visible_items_use_only_targeted_search_evidence() -> None:
    items = [
        {"kind": "ui", "text": "Explorar Iniciar sesión Registrarse", "href": ""},
        {"kind": "guide", "text": "De pistacho", "href": ""},
        {"kind": "guide", "text": "Vasca", "href": ""},
        {
            "kind": "suggestion",
            "text": "tarta de queso philadelphia",
            "href": "/search/pins/?q=tarta%20de%20queso%20philadelphia",
        },
        {
            "kind": "pin",
            "text": "Tarta de queso Lotus cremosa | Receta paso a paso",
            "href": "/pin/123456789/",
        },
    ]

    candidates = _pinterest_candidates_from_visible_items("tarta de queso", items)

    assert {candidate.casefold() for candidate in candidates} == {
        "tarta de queso de pistacho",
        "tarta de queso vasca",
        "tarta de queso philadelphia",
        "tarta de queso lotus cremosa",
    }


@pytest.mark.unit
def test_pinterest_batches_are_interleaved_for_domain_variety() -> None:
    batches = [
        ["tarta de queso vasca", "tarta de queso lotus"],
        ["croquetas de jamon", "croquetas de pollo"],
        ["paella de marisco", "paella valenciana"],
    ]

    assert _round_robin_pinterest_batches(batches, limit=6) == [
        "tarta de queso vasca",
        "croquetas de jamon",
        "paella de marisco",
        "tarta de queso lotus",
        "croquetas de pollo",
        "paella valenciana",
    ]


@pytest.mark.unit
def test_reconstructed_pinterest_guides_can_produce_non_empty_qualified_results(
    tmp_path: Path,
) -> None:
    domain = _domain(tmp_path)
    items = [
        {"kind": "guide", "text": "De pistacho", "href": ""},
        {"kind": "guide", "text": "Vasca", "href": ""},
        {"kind": "guide", "text": "Lotus", "href": ""},
    ]
    pinterest_terms = _pinterest_candidates_from_visible_items("tarta de queso", items)

    report = refresh_domain_trend_lists(
        [domain],
        limit_per_domain=3,
        append_to_roadmap=False,
        pinterest_terms=pinterest_terms,
        google_news_provider=lambda *args: [],
        search_volume_provider=lambda *args: 8.0,
        google_news_discovery_provider=lambda *args: [],
        google_trends_provider=lambda *args: [],
        google_suggest_provider=lambda *args: [],
        use_playwright=False,
    )

    assert len(report["domains"]["recetadolce"]["daily_best"]) == 3


@pytest.mark.unit
def test_trend_collector_defaults_to_isolated_chromium_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    domain = _domain(tmp_path)
    monkeypatch.delenv("RANKSTEIN_TRENDS_BROWSER", raising=False)

    browser_type, profile_dir = _trend_browser_profile(domain)

    assert browser_type == "chromium"
    assert profile_dir == domain.sessions_dir / "trend-profiles" / "chromium"


@pytest.mark.unit
def test_trend_collector_allows_explicit_firefox_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    domain = _domain(tmp_path)
    monkeypatch.setenv("RANKSTEIN_TRENDS_BROWSER", "firefox")

    browser_type, profile_dir = _trend_browser_profile(domain)

    assert browser_type == "firefox"
    assert profile_dir == domain.sessions_dir / "trend-profiles" / "firefox"


@pytest.mark.unit
def test_trends_cli_defaults_to_pinterest_required_policy() -> None:
    from rankstein.cli import build_parser

    args = build_parser().parse_args(["trends", "--no-roadmap"])

    assert args.candidate_origin_policy == "pinterest_required"


@pytest.mark.unit
def test_cli_reconfigures_windows_streams_for_unicode_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rankstein.cli import _configure_utf8_stdio

    stdout_bytes = BytesIO()
    stderr_bytes = BytesIO()
    stdout = TextIOWrapper(stdout_bytes, encoding="cp1252")
    stderr = TextIOWrapper(stderr_bytes, encoding="cp1252")
    monkeypatch.setattr("sys.stdout", stdout)
    monkeypatch.setattr("sys.stderr", stderr)

    _configure_utf8_stdio()
    print("Google News 🤔")
    stdout.flush()

    assert stdout.encoding.casefold() == "utf-8"
    assert "🤔" in stdout_bytes.getvalue().decode("utf-8")

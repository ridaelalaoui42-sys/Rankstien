from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import SecretStr

import backend.scripts.turbo_articles as turbo
import rankstein.trend_intelligence as trend_intelligence
from backend.scripts.turbo_articles import _ensure_recipe_schema, _normalize_category, _source_relevant_enough
from rankstein.domain import Domain


def _domain(categories: tuple[str, ...]) -> Domain:
    return Domain(
        handle="test",
        domain="test.example",
        display_name="Test",
        language="es",
        niche="recipes",
        root=Path("."),
        keywords_file=Path("keywords.md"),
        sessions_dir=Path("sessions"),
        output_dir=Path("output"),
        branding_dir=Path("branding"),
        pinterest_email="user@example.com",
        pinterest_password=SecretStr("secret"),
        supabase_url="https://supabase.example",
        supabase_service_role_key=SecretStr("service-role"),
        categories=categories,
    )


@pytest.mark.unit
def test_normalize_category_maps_main_dishes_to_domain_category() -> None:
    domain = _domain(("Aperitivos", "Postres", "Carnes", "Pescados", "Ensaladas"))

    assert _normalize_category("Platos Principales", "Trending", domain) == "Carnes"


@pytest.mark.unit
def test_normalize_category_respects_dessert_domain_categories() -> None:
    domain = _domain(("Pasteles", "Galletas", "Chocolates", "Reposteria", "Helados", "Postres"))

    assert _normalize_category("Platos Principales", "Trending", domain) == "Postres"
    assert _normalize_category("Chocolate", "Trending", domain) == "Chocolates"


@pytest.mark.unit
def test_normalize_category_uses_live_dolce_policy() -> None:
    domain = replace(
        _domain(("fresas-y-nata", "tartas-y-pasteles", "chocolates", "dulces-saludables")),
        handle="recetadolce",
    )

    assert (
        _normalize_category(
            "Pasteles",
            "Pasteles",
            domain,
            context="Bolo mousse de chocolate casero",
        )
        == "chocolates"
    )


@pytest.mark.unit
def test_recipe_schema_category_is_normalized_before_publish() -> None:
    domain = _domain(("Aperitivos", "Postres", "Carnes", "Pescados", "Ensaladas"))
    article = {
        "title": "Pollo al ajillo",
        "category": "Platos Principales",
        "recipe_schema": {"recipeCategory": "Platos Principales"},
    }

    schema = _ensure_recipe_schema(
        article,
        keyword="pollo al ajillo",
        cluster="Trending",
        domain=domain,
        hero_url="https://example.test/hero.jpg",
    )

    assert article["category"] == "Carnes"
    assert schema["recipeCategory"] == "Carnes"


@pytest.mark.unit
def test_source_relevance_rejects_generic_keyword_drift() -> None:
    assert not _source_relevant_enough(
        "ideas de mesa de postre",
        "Ideas: concepto y significado",
        "Definicion general de ideas creativas",
        "https://humanidades.com/ideas/",
    )
    assert _source_relevant_enough(
        "ideas de mesa de postre",
        "Mesa de postres: recetas faciles para fiestas",
        "Postres, dulces e ingredientes para montar una mesa bonita",
        "https://example.test/mesa-postres-recetas",
    )


@pytest.mark.unit
def test_empty_queue_refresh_requires_pinterest_origin_candidates(monkeypatch) -> None:
    calls = []

    async def collect(domain, region, limit):
        assert limit == 240
        return ["tarta de coco"]

    def fake_refresh(domains, **kwargs):
        calls.append(kwargs)
        return {"domains": {domains[0].handle: {"roadmap_added": 2}}}

    monkeypatch.setattr(trend_intelligence, "refresh_domain_trend_lists", fake_refresh)
    monkeypatch.setattr(trend_intelligence, "_fetch_pinterest_niche_trending_terms_async", collect)

    added = asyncio.run(turbo._auto_refresh_keywords(_domain(("Postres",))))

    assert added == 2
    assert calls[0]["candidate_origin_policy"] == "pinterest_required"
    assert calls[0]["pinterest_terms"] == ["tarta de coco"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_refresh_ranks_new_longtails_after_excluding_attempted_and_published_phrases(
    tmp_path, monkeypatch
) -> None:
    from rankstein.keyword_roadmap import KeywordRow, read_keyword_rows, write_keyword_rows

    domain = replace(_domain(("Postres",)), root=tmp_path, keywords_file=tmp_path / "keywords.md")
    old_terms = [f"tarta de coco numero {index}" for index in range(15)]
    write_keyword_rows(
        domain.keywords_file,
        "Test",
        [KeywordRow(term, status="Pending") for term in old_terms]
        + [
            KeywordRow("tarta de coco publicada", status="Needs Verification"),
            KeywordRow("tarta de coco fallida", status="Failed"),
        ],
    )
    fresh_phrase = "galletas de almendra crujientes"

    async def collect(_domain, region, limit):
        assert _domain is domain and limit == 240
        return old_terms + ["tarta de coco publicada", "tarta de coco fallida", fresh_phrase]

    async def google_only(*args):
        raise AssertionError("Google discovery must not supply production candidates")

    monkeypatch.setattr(trend_intelligence, "_fetch_pinterest_niche_trending_terms_async", collect)
    monkeypatch.setattr(trend_intelligence, "_search_volume_proxy", lambda *args: 8.0)
    monkeypatch.setattr(trend_intelligence, "fetch_google_news_signals", lambda *args: [])
    monkeypatch.setattr(trend_intelligence, "fetch_google_autocomplete_terms", google_only)
    monkeypatch.setattr(trend_intelligence, "fetch_google_news_discovery_terms", google_only)
    monkeypatch.setattr(trend_intelligence, "fetch_google_trending_terms", google_only)

    added = await turbo._auto_refresh_keywords(domain, excluded_keywords=set(old_terms))

    assert added == 1
    report = json.loads((tmp_path / "daily_best_keywords.json").read_text(encoding="utf-8"))
    assert [(row["keyword"], row["pinterest_origin"]) for row in report["items"]] == [(fresh_phrase, True)]
    rows = {row.keyword: row.status for row in read_keyword_rows(domain.keywords_file)}
    assert rows["tarta de coco publicada"] == "Needs Verification"
    assert rows["tarta de coco fallida"] == "Failed"
    assert rows[fresh_phrase] == "Pending"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_production_refresh_exclusions_are_domain_local(tmp_path, monkeypatch) -> None:
    from rankstein.keyword_roadmap import KeywordRow, write_keyword_rows

    first = replace(_domain(("Postres",)), handle="first", root=tmp_path / "first")
    second = replace(_domain(("Postres",)), handle="second", root=tmp_path / "second")
    first.root.mkdir()
    second.root.mkdir()
    first = replace(first, keywords_file=first.root / "keywords.md")
    second = replace(second, keywords_file=second.root / "keywords.md")
    write_keyword_rows(first.keywords_file, "First", [KeywordRow("tarta de coco", status="Failed")])
    write_keyword_rows(second.keywords_file, "Second", [])
    calls = {}

    async def collect(*args):
        return ["tarta de coco"]

    def refresh(domains, **kwargs):
        calls[domains[0].handle] = kwargs["pinterest_terms"]
        return {"domains": {domains[0].handle: {"roadmap_added": 0}}}

    monkeypatch.setattr(trend_intelligence, "_fetch_pinterest_niche_trending_terms_async", collect)
    monkeypatch.setattr(trend_intelligence, "refresh_domain_trend_lists", refresh)
    await asyncio.gather(turbo._auto_refresh_keywords(first), turbo._auto_refresh_keywords(second))
    assert calls == {"first": [], "second": ["tarta de coco"]}


@pytest.mark.unit
@pytest.mark.parametrize(
    "keyword",
    ["croquetas caseras para gato", "mousse de chocolate saudável", "mousse de chocolate para recheio de bolo"],
)
def test_production_discovery_rejects_pet_and_foreign_language_noise(keyword) -> None:
    assert not turbo._production_discovery_keyword_allowed(keyword, _domain(("Postres",)))


@pytest.mark.unit
def test_production_discovery_respects_dolce_dessert_categories() -> None:
    domain = replace(
        _domain(("fresas-y-nata", "tartas-y-pasteles", "chocolates", "dulces-saludables")),
        handle="recetadolce",
    )
    assert not turbo._production_discovery_keyword_allowed("croquetas caseras de jamon", domain)
    assert turbo._production_discovery_keyword_allowed("tarta de queso con pistacho", domain)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_production_refresh_deadline_cancels_and_cleans_up_collector(monkeypatch) -> None:
    cleaned_up = []
    real_wait_for = asyncio.wait_for

    async def collect(*args):
        try:
            await asyncio.sleep(10)
        finally:
            cleaned_up.append(True)

    async def short_deadline(task, *, timeout):
        assert timeout == 300
        return await real_wait_for(task, timeout=0.001)

    def forbidden_refresh(*args, **kwargs):
        raise AssertionError("timed-out Pinterest evidence cannot authorize keywords")

    monkeypatch.setattr(trend_intelligence, "_fetch_pinterest_niche_trending_terms_async", collect)
    monkeypatch.setattr(trend_intelligence, "refresh_domain_trend_lists", forbidden_refresh)
    monkeypatch.setattr(turbo.asyncio, "wait_for", short_deadline)
    assert await turbo._auto_refresh_keywords(_domain(("Postres",))) == 0
    assert cleaned_up == [True]


@pytest.mark.unit
def test_production_keyword_keys_exclude_google_only_candidates(tmp_path, monkeypatch) -> None:
    domain = replace(_domain(("Postres",)), root=tmp_path)
    rows = [
        {
            "keyword": "tarta de coco",
            "qualified": True,
            "pinterest_origin": True,
            "source": "Pinterest Trends + Google News",
        },
        {
            "keyword": "tarta de pera",
            "qualified": True,
            "pinterest_origin": False,
            "source": "Google Suggestions",
        },
    ]
    (tmp_path / "daily_best_keywords.json").write_text(json.dumps({"items": rows}), encoding="utf-8")
    monkeypatch.setattr(
        turbo, "load_qualified_keyword_keys", lambda _: ({"tarta de coco", "tarta de pera"}, "ok")
    )
    assert turbo._load_pinterest_qualified_keyword_keys(domain) == ({"tarta de coco"}, "ok")


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin,source", [(False, "Google Suggestions"), (None, "Pinterest Trends"), (True, "Google News")]
)
async def test_article_pipeline_requires_explicit_pinterest_origin(monkeypatch, origin, source) -> None:
    monkeypatch.setattr(
        turbo,
        "has_qualified_keyword_evidence",
        lambda *a, **k: (
            True,
            "ok",
            {"qualified": True, "pinterest_origin": origin, "source": source},
        ),
    )

    async def forbidden_scrape(*args, **kwargs):
        raise AssertionError("source research started for an unproven Pinterest candidate")

    monkeypatch.setattr(turbo, "_scrape_source_brief", forbidden_scrape)
    assert await turbo.process_keyword("tarta de pera", "Postres", _domain(("Postres",))) == "Failed"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_worker_waits_instead_of_retrying_a_failed_keyword_after_refresh(tmp_path, monkeypatch) -> None:
    from rankstein.keyword_roadmap import EXPECTED_HEADER, mark_keyword_status

    domain = replace(_domain(("Postres",)), root=tmp_path, keywords_file=tmp_path / "keywords.md")
    domain.keywords_file.write_text(
        f"# Test\n\n{EXPECTED_HEADER}\n|---|---|---|---|---|---|\n"
        "| tarta de coco | Postres | Pinterest Trends | test | High | Pending |\n",
        encoding="utf-8",
    )
    attempts = []
    monkeypatch.setattr(turbo, "_PRODUCTION_BATCH_TRACKER", None)
    monkeypatch.setattr(turbo, "_load_pinterest_qualified_keyword_keys", lambda _: ({"tarta de coco"}, "ok"))

    async def failed_article(keyword, *args, **kwargs):
        attempts.append(keyword)
        assert len(attempts) == 1, "same failed keyword was attempted again in this batch"
        return "Failed"

    async def refresh(_, **kwargs):
        mark_keyword_status(domain.keywords_file, "Test", "tarta de coco", "Pending")
        return 1

    async def sleep(seconds):
        if seconds == 300:
            raise RuntimeError("worker is waiting for new Pinterest candidates")

    monkeypatch.setattr(turbo, "process_keyword", failed_article)
    monkeypatch.setattr(turbo, "_auto_refresh_keywords", refresh)
    monkeypatch.setattr(turbo.asyncio, "sleep", sleep)
    with pytest.raises(RuntimeError, match="waiting for new Pinterest candidates"):
        await turbo._run_domain(domain, workers=1, limit=1, once=False, success_target=10)
    assert attempts == ["tarta de coco"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_published_target_waits_for_pins_without_creating_extra_articles(monkeypatch) -> None:
    reasons = []

    class Tracker:
        def __init__(self):
            self.data = {"domains": {"test": {"articles": []}}}

        def verified(self, handle):
            return 0

        def published_count(self, handle):
            return 10

        def attempted_keyword_keys(self, handle):
            return set()

        def mark_domain_waiting(self, handle, reason):
            reasons.append(reason)

    async def reconcile(_):
        pass

    async def sleep(seconds):
        assert seconds == 300
        raise RuntimeError("waiting for Pinterest")

    def forbidden_reservation(*args):
        raise AssertionError("more articles were created while ten publications awaited proof")

    monkeypatch.setattr(turbo, "_PRODUCTION_BATCH_TRACKER", Tracker())
    monkeypatch.setattr(turbo, "_reconcile_awaiting_articles", reconcile)
    monkeypatch.setattr(turbo, "_load_pinterest_qualified_keyword_keys", forbidden_reservation)
    monkeypatch.setattr(turbo.asyncio, "sleep", sleep)
    with pytest.raises(RuntimeError, match="waiting for Pinterest"):
        await turbo._run_domain(_domain(("Postres",)), workers=1, limit=10, once=False, success_target=10)
    assert "Published article target reached" in reasons[0]


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("authorize,fresh", [(True, True), (False, True), (True, False)])
async def test_worker_retries_failed_run_only_with_explicit_permission_and_fresh_evidence(
    tmp_path, monkeypatch, authorize, fresh
) -> None:
    from rankstein.keyword_roadmap import EXPECTED_HEADER
    from rankstein.production_batch import ProductionBatchTracker

    domain = replace(_domain(("Postres",)), root=tmp_path, keywords_file=tmp_path / "keywords.md")
    domain.keywords_file.write_text(
        f"# Test\n\n{EXPECTED_HEADER}\n|---|---|---|---|---|---|\n"
        "| tarta de coco | Postres | Pinterest Trends | test | High | Pending |\n",
        encoding="utf-8",
    )
    tracker = ProductionBatchTracker(
        project_root=tmp_path,
        batch_id="production-worker-retry",
        domain_handles=[domain.handle],
        target_per_domain=10,
    )
    tracker.start_keyword(domain.handle, "tarta de coco", "Postres", "Pinterest Trends")
    tracker.attach_run(domain.handle, "tarta de coco", "failed-run-1")
    tracker.complete_keyword(domain.handle, "tarta de coco", "Failed")
    if authorize:
        assert tracker.authorize_failed_retry(
            domain.handle, "tarta de coco", "Codex quota recovered", pipeline_run_id="failed-run-1"
        )
    attempts = []

    async def article(keyword, *args, **kwargs):
        attempts.append(keyword)
        return "Failed"

    async def refresh(_, **kwargs):
        return 0

    monkeypatch.setattr(turbo, "_PRODUCTION_BATCH_TRACKER", tracker)
    monkeypatch.setattr(
        turbo,
        "_load_pinterest_qualified_keyword_keys",
        lambda _: ({"tarta de coco"} if fresh else set(), "ok"),
    )
    monkeypatch.setattr(turbo, "process_keyword", article)
    monkeypatch.setattr(turbo, "_auto_refresh_keywords", refresh)
    await turbo._run_domain(domain, workers=1, limit=1, once=True)
    assert attempts == (["tarta de coco"] if authorize and fresh else [])
    if attempts:
        assert len(tracker.data["domains"][domain.handle]["articles"]) == 2
        assert "tarta de coco" in tracker.attempted_keyword_keys(domain.handle)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_late_primary_pin_is_reconciled_with_the_shared_live_tracker(tmp_path, monkeypatch) -> None:
    import pinterest_automation
    import rankstein.pipeline_events as events
    import rankstein.production_reconcile as reconcile
    from rankstein.production_batch import ProductionBatchTracker

    domain = replace(_domain(("Postres",)), root=tmp_path)
    db = tmp_path / "events.db"
    run_id = events.start_pipeline_run(domain_handle=domain.handle, keyword="tarta de coco", db_path=db)
    events.record_pipeline_stage(
        run_id, "primary_pin_publish", "warning", "Queued", details={"job_id": "primary-exact"}, db_path=db
    )
    tracker = ProductionBatchTracker(
        project_root=tmp_path,
        batch_id="production-live",
        domain_handles=[domain.handle],
        target_per_domain=10,
    )
    tracker.start_keyword(domain.handle, "tarta de coco", "Postres", "Pinterest Trends")
    tracker.attach_run(domain.handle, "tarta de coco", run_id)
    tracker.complete_keyword(domain.handle, "tarta de coco", "Needs Verification")
    calls = []

    class Queue:
        async def get_job_outcome_async(self, job_id):
            assert job_id == "primary-exact"
            return {"state": "completed", "result": {"pin_id": "1148488342515527632"}}

    async def finish(**kwargs):
        calls.append(kwargs)
        return {"success": True}

    monkeypatch.setattr(events, "PIPELINE_DB", db)
    monkeypatch.setattr(turbo, "_PRODUCTION_BATCH_TRACKER", tracker)
    monkeypatch.setattr(pinterest_automation, "get_job_queue", lambda **kwargs: Queue())
    monkeypatch.setattr(reconcile, "reconcile_production_article", finish)
    await turbo._reconcile_awaiting_articles(domain)
    assert calls[0]["batch_tracker"] is tracker
    assert calls[0]["primary_job_id"] == "primary-exact"
    assert calls[0]["pipeline_run_id"] == run_id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_published_article_without_verified_pin_needs_verification(monkeypatch) -> None:
    domain = _domain(("Aperitivos", "Ensaladas"))
    article = {
        "title": "Ensalada de verano",
        "slug": "ensalada-de-verano",
        "category": "Ensaladas",
        "excerpt": "Una ensalada fresca.",
        "content": "Contenido completo.",
        "recipe_schema": {
            "recipeIngredient": ["200 g de garbanzos"],
            "recipeInstructions": [{"text": "Mezcla todos los ingredientes."}],
        },
    }

    import rankstein_mcp_server as mcp

    publish_kwargs = {}

    monkeypatch.setattr(
        turbo,
        "get_hero_image",
        lambda **kwargs: {"success": True, "output_path": "hero.jpg", "source": "codex"},
    )
    monkeypatch.setattr(turbo, "_ensure_recipe_schema", lambda *args, **kwargs: article["recipe_schema"])
    monkeypatch.setattr(
        mcp,
        "upload_image_to_supabase",
        lambda *args: {"success": True, "public_url": "https://img.test/hero.jpg"},
    )
    monkeypatch.setattr(mcp, "validate_article_quality", lambda *args: {"success": True, "score": 100})
    monkeypatch.setattr(
        mcp,
        "build_supabase_content",
        lambda *args: {"success": True, "payload": __import__("json").dumps(article)},
    )

    def publish_without_duplicate_campaign(**kwargs):
        publish_kwargs.update(kwargs)
        return {"success": True, "url": "https://test.example/ensalada-de-verano"}

    monkeypatch.setattr(mcp, "publish_article_to_supabase", publish_without_duplicate_campaign)
    monkeypatch.setattr(mcp, "create_article_pin", lambda **kwargs: {"success": False, "error": "no pin"})

    status = await turbo._publish_openrouter_article(
        article,
        "ensalada de verano",
        "Ensaladas",
        domain,
    )

    assert status == "Needs Verification"
    assert publish_kwargs["auto_create_pinterest_campaign"] is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failed_pin_upload_receives_domain_and_needs_verification(monkeypatch) -> None:
    domain = _domain(("Aperitivos",))
    article = {
        "title": "Aperitivo de calabacin",
        "slug": "aperitivo-de-calabacin",
        "category": "Aperitivos",
        "excerpt": "Un aperitivo sencillo.",
        "content": "Contenido completo.",
        "recipe_schema": {
            "recipeIngredient": ["1 calabacin"],
            "recipeInstructions": [{"text": "Cocina el calabacin."}],
        },
    }
    captured = {}

    import rankstein_mcp_server as mcp

    monkeypatch.setattr(
        turbo,
        "get_hero_image",
        lambda **kwargs: {"success": True, "output_path": "hero.jpg", "source": "codex"},
    )
    monkeypatch.setattr(turbo, "_ensure_recipe_schema", lambda *args, **kwargs: article["recipe_schema"])
    monkeypatch.setattr(
        mcp,
        "upload_image_to_supabase",
        lambda *args: {"success": True, "public_url": "https://img.test/hero.jpg"},
    )
    monkeypatch.setattr(mcp, "validate_article_quality", lambda *args: {"success": True, "score": 100})
    monkeypatch.setattr(
        mcp,
        "build_supabase_content",
        lambda *args: {"success": True, "payload": __import__("json").dumps(article)},
    )
    monkeypatch.setattr(
        mcp,
        "publish_article_to_supabase",
        lambda **kwargs: {"success": True, "url": "https://test.example/aperitivo-de-calabacin"},
    )
    monkeypatch.setattr(
        mcp, "create_article_pin", lambda **kwargs: {"success": True, "output_path": "pin.jpg"}
    )

    async def fail_upload(**kwargs):
        captured.update(kwargs)
        return {"success": False, "error": "blocked"}

    monkeypatch.setattr(mcp, "automation_upload_pin_direct", fail_upload)

    status = await turbo._publish_openrouter_article(
        article,
        "aperitivo de calabacin",
        "Aperitivos",
        domain,
    )

    assert status == "Needs Verification"
    assert captured["domain_handle"] == "test"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pin_upload_success_without_pin_identity_needs_verification(monkeypatch) -> None:
    domain = _domain(("Aperitivos",))
    article = {
        "title": "Aperitivo de calabacin",
        "slug": "aperitivo-de-calabacin",
        "category": "Aperitivos",
        "excerpt": "Un aperitivo sencillo.",
        "content": "Contenido completo.",
        "recipe_schema": {
            "recipeIngredient": ["1 calabacin"],
            "recipeInstructions": [{"text": "Cocina el calabacin."}],
        },
    }

    import rankstein_mcp_server as mcp

    monkeypatch.setattr(
        turbo,
        "get_hero_image",
        lambda **kwargs: {"success": True, "output_path": "hero.jpg", "source": "codex"},
    )
    monkeypatch.setattr(turbo, "_ensure_recipe_schema", lambda *args, **kwargs: article["recipe_schema"])
    monkeypatch.setattr(
        mcp,
        "upload_image_to_supabase",
        lambda *args: {"success": True, "public_url": "https://img.test/hero.jpg"},
    )
    monkeypatch.setattr(mcp, "validate_article_quality", lambda *args: {"success": True, "score": 100})
    monkeypatch.setattr(
        mcp,
        "build_supabase_content",
        lambda *args: {"success": True, "payload": __import__("json").dumps(article)},
    )
    monkeypatch.setattr(
        mcp,
        "publish_article_to_supabase",
        lambda **kwargs: {"success": True, "url": "https://test.example/aperitivo-de-calabacin"},
    )
    monkeypatch.setattr(
        mcp, "create_article_pin", lambda **kwargs: {"success": True, "output_path": "pin.jpg"}
    )

    async def upload_without_proof(**kwargs):
        return {"success": True, "pin_id": "", "pin_url": ""}

    async def forbidden_remaster(**kwargs):
        raise AssertionError("remastering must not run without primary pin proof")

    monkeypatch.setattr(mcp, "automation_upload_pin_direct", upload_without_proof)
    monkeypatch.setattr(turbo, "_launch_article_remaster_campaign", forbidden_remaster)

    status = await turbo._publish_generated_article(
        article,
        "aperitivo de calabacin",
        "Aperitivos",
        domain,
    )

    assert status == "Needs Verification"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_codex_hero_failure_fails_closed_before_publish(monkeypatch) -> None:
    domain = _domain(("Postres",))
    article = {
        "title": "Tarta de chocolate",
        "slug": "tarta-de-chocolate",
        "category": "Postres",
        "content": "Contenido culinario completo.",
        "recipe_schema": {
            "recipeIngredient": ["200 g de chocolate"],
            "recipeInstructions": [{"text": "Mezcla y hornea."}],
        },
    }
    events: list[tuple[str, str, dict]] = []

    import rankstein_mcp_server as mcp

    def forbidden_publish(*args, **kwargs):
        raise AssertionError("publishing must stop when the Codex hero fails")

    monkeypatch.setattr(
        turbo,
        "get_hero_image",
        lambda **kwargs: {"success": False, "error": "Codex image unavailable"},
    )
    monkeypatch.setattr(mcp, "upload_image_to_supabase", forbidden_publish)
    monkeypatch.setattr(mcp, "publish_article_to_supabase", forbidden_publish)
    monkeypatch.setattr(
        turbo,
        "_pipeline_event",
        lambda _run, stage, state, _message, **details: events.append((stage, state, details)),
    )
    monkeypatch.setattr(turbo, "_pipeline_status", lambda *args, **kwargs: None)

    status = await turbo._publish_generated_article(
        article,
        "tarta de chocolate",
        "Postres",
        domain,
        pipeline_run_id="run-hero-failure",
    )

    assert status == "Failed"
    assert any(
        stage == "hero_image" and state == "failed" and details["fallback_allowed"] is False
        for stage, state, details in events
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_non_codex_hero_source_is_rejected_before_upload(monkeypatch) -> None:
    domain = _domain(("Postres",))
    article = {
        "title": "Tarta de chocolate",
        "slug": "tarta-de-chocolate",
        "category": "Postres",
        "content": "Contenido culinario completo.",
        "recipe_schema": {
            "recipeIngredient": ["200 g de chocolate"],
            "recipeInstructions": [{"text": "Mezcla y hornea."}],
        },
    }

    import rankstein_mcp_server as mcp

    def forbidden_upload(*args, **kwargs):
        raise AssertionError("unattested hero sources must not be uploaded")

    monkeypatch.setattr(
        turbo,
        "get_hero_image",
        lambda **kwargs: {
            "success": True,
            "output_path": "unapproved-hero.jpg",
            "source": "pollinations",
        },
    )
    monkeypatch.setattr(mcp, "upload_image_to_supabase", forbidden_upload)
    monkeypatch.setattr(turbo, "_pipeline_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(turbo, "_pipeline_status", lambda *args, **kwargs: None)

    status = await turbo._publish_generated_article(
        article,
        "tarta de chocolate",
        "Postres",
        domain,
        pipeline_run_id="run-unapproved-hero",
    )

    assert status == "Failed"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_article_generation_fails_closed_without_non_codex_fallbacks(monkeypatch) -> None:
    domain = _domain(("Postres",))
    fallback_calls: list[str] = []

    monkeypatch.setattr(turbo, "_start_pipeline_telemetry", lambda *args, **kwargs: "run-test")
    monkeypatch.setattr(turbo, "_pipeline_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(turbo, "_pipeline_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        turbo,
        "has_qualified_keyword_evidence",
        lambda *args, **kwargs: (
            True,
            "ok",
            {"qualified": True, "pinterest_origin": True, "source": "Pinterest Trends"},
        ),
    )

    async def source_brief(*args, **kwargs):
        return "Fuentes compactas."

    async def codex_failure(*args, **kwargs):
        return turbo._HermesArticleResult(
            None,
            "availability_failure",
            "Codex unavailable",
            503,
        )

    async def forbidden_fallback(*args, **kwargs):
        fallback_calls.append("called")
        raise AssertionError("A non-Codex fallback was invoked")

    monkeypatch.setattr(turbo, "_scrape_source_brief", source_brief)
    monkeypatch.setenv("RANKSTEIN_ARTICLE_PROVIDER", "hermes-codex-only")
    monkeypatch.setenv("RANKSTEIN_ALLOW_ARTICLE_FALLBACKS", "1")
    monkeypatch.setattr(turbo, "_call_hermes_codex_for_article_result", codex_failure)
    monkeypatch.setattr(turbo, "_call_codex_cli_for_article", codex_failure)
    monkeypatch.setattr(turbo, "_call_opencode_for_article", forbidden_fallback)
    monkeypatch.setattr(turbo, "_call_openrouter_for_article", forbidden_fallback)

    status = await turbo.process_keyword(
        "tarta de chocolate",
        "Postres",
        domain,
        source="test",
    )

    assert status == "Failed"
    assert fallback_calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_keyword_uses_free_hermes_writer_only_when_codex_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    domain = _domain(("Postres",))
    article = {
        "title": "Tarta de chocolate",
        "slug": "tarta-de-chocolate",
        "content": "Contenido culinario completo. " * 30,
        "excerpt": "Una tarta de chocolate.",
        "category": "Postres",
        "recipe_schema": {
            "recipeIngredient": ["200 g de chocolate"],
            "recipeInstructions": [{"text": "Mezcla y hornea."}],
        },
    }
    calls: list[str] = []

    async def source_brief(*args, **kwargs):
        return "Fuentes compactas."

    async def codex_unavailable(*args, **kwargs):
        return turbo._HermesArticleResult(None, "availability_failure", "HTTP 503", 503)

    async def free_writer(*args, **kwargs):
        calls.append("free")
        return article

    async def publish(*args, **kwargs):
        calls.append("publish")
        return "Needs Verification"

    async def forbidden_legacy(*args, **kwargs):
        raise AssertionError("retired direct provider fallback was invoked")

    monkeypatch.setenv("RANKSTEIN_ARTICLE_PROVIDER", "hermes-codex")
    monkeypatch.setattr(turbo, "_start_pipeline_telemetry", lambda *args, **kwargs: "run-test")
    monkeypatch.setattr(turbo, "_pipeline_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(turbo, "_pipeline_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        turbo,
        "has_qualified_keyword_evidence",
        lambda *args, **kwargs: (
            True,
            "ok",
            {"qualified": True, "pinterest_origin": True, "source": "Pinterest Trends"},
        ),
    )
    monkeypatch.setattr(turbo, "_scrape_source_brief", source_brief)
    monkeypatch.setattr(turbo, "_call_hermes_codex_for_article_result", codex_unavailable)
    monkeypatch.setattr(turbo, "_call_hermes_free_for_article", free_writer)
    monkeypatch.setattr(turbo, "_openrouter_article_quality_check", lambda value: value is article)
    monkeypatch.setattr(turbo, "_publish_generated_article", publish)
    monkeypatch.setattr(turbo, "_call_nvidia_nemotron_for_article", forbidden_legacy)
    monkeypatch.setattr(turbo, "_call_opencode_for_article", forbidden_legacy)
    monkeypatch.setattr(turbo, "_call_openrouter_for_article", forbidden_legacy)

    status = await turbo.process_keyword("tarta de chocolate", "Postres", domain, source="test")

    assert status == "Needs Verification"
    assert calls == ["free", "publish"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_keyword_fails_closed_when_codex_and_hermes_free_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    domain = _domain(("Postres",))
    calls: list[str] = []

    async def source_brief(*args, **kwargs):
        return "Fuentes compactas."

    async def codex_unavailable(*args, **kwargs):
        return turbo._HermesArticleResult(None, "availability_failure", "HTTP 503", 503)

    async def unavailable_free_writer(*args, **kwargs):
        calls.append("hermes-free")
        return None

    async def forbidden_non_hermes_provider(*args, **kwargs):
        calls.append("non-hermes-provider")
        raise AssertionError("article generation must stop after Hermes providers fail")

    monkeypatch.setenv("RANKSTEIN_ARTICLE_PROVIDER", "hermes-codex")
    monkeypatch.setattr(turbo, "_start_pipeline_telemetry", lambda *args, **kwargs: "run-test")
    monkeypatch.setattr(turbo, "_pipeline_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(turbo, "_pipeline_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        turbo,
        "has_qualified_keyword_evidence",
        lambda *args, **kwargs: (
            True,
            "ok",
            {"qualified": True, "pinterest_origin": True, "source": "Pinterest Trends"},
        ),
    )
    monkeypatch.setattr(turbo, "_scrape_source_brief", source_brief)
    monkeypatch.setattr(turbo, "_call_hermes_codex_for_article_result", codex_unavailable)
    monkeypatch.setattr(
        turbo, "_hermes_free_article_target", lambda *args: (True, ("openrouter", "model:free"))
    )
    monkeypatch.setattr(turbo, "_call_hermes_free_for_article", unavailable_free_writer)
    monkeypatch.setattr(turbo, "_call_gemini_api_for_article", forbidden_non_hermes_provider)
    monkeypatch.setattr(turbo, "_call_opencode_for_article", forbidden_non_hermes_provider)
    monkeypatch.setattr(turbo, "_call_openrouter_for_article", forbidden_non_hermes_provider)

    status = await turbo.process_keyword("tarta de chocolate", "Postres", domain, source="test")

    assert status == "Failed"
    assert calls == ["hermes-free"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_keyword_does_not_use_free_model_for_rejected_codex_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    domain = _domain(("Postres",))

    async def source_brief(*args, **kwargs):
        return "Fuentes compactas."

    async def rejected_content(*args, **kwargs):
        return turbo._HermesArticleResult(
            None,
            "content_rejected",
            "malformed HTTP 200 response",
            200,
        )

    async def forbidden_free(*args, **kwargs):
        raise AssertionError("free fallback must not run for rejected HTTP-200 content")

    monkeypatch.setenv("RANKSTEIN_ARTICLE_PROVIDER", "hermes-codex")
    monkeypatch.setattr(turbo, "_start_pipeline_telemetry", lambda *args, **kwargs: "run-test")
    monkeypatch.setattr(turbo, "_pipeline_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(turbo, "_pipeline_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        turbo,
        "has_qualified_keyword_evidence",
        lambda *args, **kwargs: (
            True,
            "ok",
            {"qualified": True, "pinterest_origin": True, "source": "Pinterest Trends"},
        ),
    )
    monkeypatch.setattr(turbo, "_scrape_source_brief", source_brief)
    monkeypatch.setattr(turbo, "_call_hermes_codex_for_article_result", rejected_content)
    monkeypatch.setattr(turbo, "_call_hermes_free_for_article", forbidden_free)

    status = await turbo.process_keyword("tarta de chocolate", "Postres", domain, source="test")

    assert status == "Failed"


@pytest.mark.unit
def test_hermes_attestation_accepts_exact_openai_codex_model_block(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        """model:
  api_mode: codex_responses
  base_url: https://chatgpt.com/backend-api/codex
  default: gpt-5.5
  provider: openai-codex
providers:
  misleading:
    provider: gemini
""",
        encoding="utf-8",
    )

    assert turbo._hermes_openai_codex_attestation(config) == (True, "gpt-5.5")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("configured", "expected_ok"),
    [
        ("openrouter:nvidia/nemotron-3-super-120b-a12b:free", True),
        ("opencode-zen:future-model-free", True),
        ("openrouter:nvidia/nemotron-3-super-120b-a12b", False),
        ("gemini:gemini-flash:free", False),
        ("openrouter:", False),
    ],
)
def test_hermes_free_article_target_accepts_only_approved_free_models(
    configured: str,
    expected_ok: bool,
) -> None:
    ok, _detail = turbo._hermes_free_article_target(configured)

    assert ok is expected_ok


@pytest.mark.unit
@pytest.mark.asyncio
async def test_hermes_free_writer_uses_one_bounded_hermes_cli_invocation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    article = {
        "title": "Tarta de prueba",
        "slug": "tarta-de-prueba",
        "content": "Contenido culinario completo. " * 30,
        "excerpt": "Una tarta de prueba.",
        "category": "Postres",
        "recipe_schema": {
            "recipeIngredient": ["200 g de harina"],
            "recipeInstructions": [{"text": "Mezcla y hornea."}],
        },
    }
    captured: dict = {}

    class Process:
        returncode = 0
        pid = 12345

        async def communicate(self):
            return json.dumps(article).encode(), b""

    async def fake_subprocess(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("RANKSTEIN_HERMES_CLI_PATH", "hermes-test.exe")
    monkeypatch.setenv(
        "RANKSTEIN_HERMES_FREE_ARTICLE_MODEL",
        "openrouter:nvidia/nemotron-3-super-120b-a12b:free",
    )
    monkeypatch.setenv("RANKSTEIN_HERMES_FREE_ARTICLE_TIMEOUT", "77")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
    monkeypatch.setattr(turbo, "_openrouter_article_quality_check", lambda _article: True)

    generated = await turbo._call_hermes_free_for_article(
        "tarta de prueba",
        _domain(("Postres",)),
    )

    assert generated == article
    args = captured["args"]
    assert args[:7] == (
        "hermes-test.exe",
        "--ignore-user-config",
        "--ignore-rules",
        "--provider",
        "openrouter",
        "--model",
        "nvidia/nemotron-3-super-120b-a12b:free",
    )
    assert args[7] == "-z"
    assert captured["kwargs"]["env"]["HERMES_HOME"] == str(tmp_path)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_hermes_codex_first_free_makes_one_gateway_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "config.yaml").write_text(
        """model:
  api_mode: codex_responses
  base_url: https://chatgpt.com/backend-api/codex
  default: gpt-5.5
  provider: openai-codex
fallback_providers:
  - provider: opencode-zen
    model: qwen3-coder-free
    base_url: https://opencode.ai/zen/v1
    key_env: OPENCODE_API_KEY
  - provider: openrouter
    model: meta-llama/llama-3.3-70b-instruct:free
    base_url: https://openrouter.ai/api/v1
    key_env: OPENROUTER_API_KEY
""",
        encoding="utf-8",
    )
    article = {
        "title": "Tarta de prueba",
        "slug": "tarta-de-prueba",
        "content": "Contenido culinario completo. " * 30,
        "excerpt": "Una tarta de prueba.",
        "category": "Postres",
        "recipe_schema": {
            "recipeIngredient": ["200 g de harina"],
            "recipeInstructions": [{"text": "Mezcla y hornea."}],
        },
    }

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": json.dumps(article)}}]}

    class Session:
        def __init__(self) -> None:
            self.requests: list[dict] = []

        def post(self, url, **kwargs):
            self.requests.append({"url": url, **kwargs})
            return Response()

    session = Session()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("RANKSTEIN_ARTICLE_PROVIDER", "hermes-codex")
    monkeypatch.setenv("RANKSTEIN_HERMES_CODEX_API_KEY", "test-api-key")
    monkeypatch.setattr(turbo, "_get_session", lambda: session)

    generated = await turbo._call_hermes_codex_for_article(
        "tarta de prueba",
        _domain(("Postres",)),
    )

    assert generated == article
    assert len(session.requests) == 1
    assert "fallback_providers" not in session.requests[0]["json"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_malformed_hermes_success_fails_closed_after_one_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "config.yaml").write_text(
        """model:
  api_mode: codex_responses
  base_url: https://chatgpt.com/backend-api/codex
  default: gpt-5.5
  provider: openai-codex
fallback_providers:
  - provider: openrouter
    model: meta-llama/llama-3.3-70b-instruct:free
    base_url: https://openrouter.ai/api/v1
    key_env: OPENROUTER_API_KEY
""",
        encoding="utf-8",
    )

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"choices": []}

    class Session:
        calls = 0

        def post(self, *args, **kwargs):
            self.calls += 1
            return Response()

    session = Session()
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("RANKSTEIN_ARTICLE_PROVIDER", "hermes-codex")
    monkeypatch.setenv("RANKSTEIN_HERMES_CODEX_API_KEY", "test-api-key")
    monkeypatch.setattr(turbo, "_get_session", lambda: session)

    assert (
        await turbo._call_hermes_codex_for_article(
            "tarta de prueba",
            _domain(("Postres",)),
        )
        is None
    )
    assert session.calls == 1


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider", "gemini"),
        ("api_mode", "chat_completions"),
        ("base_url", "https://example.invalid/codex"),
        ("default", "gemini-3-pro"),
    ],
)
def test_hermes_attestation_rejects_every_non_codex_setting(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    settings = {
        "provider": "openai-codex",
        "api_mode": "codex_responses",
        "base_url": "https://chatgpt.com/backend-api/codex",
        "default": "gpt-5.5",
    }
    settings[field] = value
    config = tmp_path / "config.yaml"
    config.write_text(
        "model:\n" + "".join(f"  {key}: {item}\n" for key, item in settings.items()),
        encoding="utf-8",
    )

    attested, diagnostic = turbo._hermes_openai_codex_attestation(config)

    assert attested is False
    assert field in diagnostic or (field == "default" and "model" in diagnostic)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_hermes_request_is_blocked_before_network_when_attestation_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    (tmp_path / "config.yaml").write_text(
        """model:
  provider: gemini
  api_mode: codex_responses
  base_url: https://chatgpt.com/backend-api/codex
  default: gpt-5.5
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("RANKSTEIN_HERMES_CODEX_API_KEY", "test-key")

    def forbidden_network():
        raise AssertionError("Hermes network request must not be prepared")

    monkeypatch.setattr(turbo, "_get_session", forbidden_network)

    assert await turbo._call_hermes_codex_for_article("tarta", _domain(("Postres",))) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retired_article_provider_helpers_are_disabled_even_with_credentials(
    monkeypatch,
) -> None:
    domain = _domain(("Postres",))
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "test-key")

    assert await turbo._call_openrouter_for_article("prompt", "tarta", domain) is None
    assert await turbo._call_opencode_for_article("tarta", domain) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_keyword_stops_before_scraping_without_qualified_trend_evidence(
    monkeypatch,
) -> None:
    async def forbidden_scrape(*args, **kwargs):
        raise AssertionError("source scraping must not run before keyword qualification")

    monkeypatch.setattr(turbo, "_start_pipeline_telemetry", lambda *args, **kwargs: "")
    monkeypatch.setattr(
        turbo,
        "has_qualified_keyword_evidence",
        lambda *args, **kwargs: (False, "missing_keyword_research", None),
        raising=False,
    )
    monkeypatch.setattr(turbo, "_scrape_source_brief", forbidden_scrape)

    status = await turbo.process_keyword(
        "tarta de queso pistacho",
        "Postres",
        _domain(("Postres",)),
        source="Startup",
    )

    assert status == "Failed"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_keyword_stops_before_writing_when_source_research_is_incomplete(
    monkeypatch,
) -> None:
    async def no_sources(*args, **kwargs):
        return ""

    async def forbidden_writer(*args, **kwargs):
        raise AssertionError("article writing must not run without extracted source research")

    monkeypatch.setattr(turbo, "_start_pipeline_telemetry", lambda *args, **kwargs: "")
    monkeypatch.setattr(
        turbo,
        "has_qualified_keyword_evidence",
        lambda *args, **kwargs: (
            True,
            "ok",
            {"qualified": True, "pinterest_origin": True, "source": "Pinterest Trends"},
        ),
        raising=False,
    )
    monkeypatch.setattr(turbo, "_scrape_source_brief", no_sources)
    monkeypatch.setattr(turbo, "_call_hermes_codex_for_article", forbidden_writer)

    status = await turbo.process_keyword(
        "tarta de queso pistacho",
        "Postres",
        _domain(("Postres",)),
        source="Pinterest Trends + Google Autocomplete Demand",
    )

    assert status == "Failed"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_source_brief_requires_two_independent_relevant_articles(monkeypatch) -> None:
    import rankstein_mcp_server as mcp

    search_calls = 0

    def one_source(*args, **kwargs):
        nonlocal search_calls
        search_calls += 1
        return {
            "success": True,
            "articles": [
                {
                    "title": "Tarta de queso y pistacho: receta cremosa",
                    "snippet": "Ingredientes y preparacion de la tarta de queso con pistacho",
                    "url": "https://example.test/tarta-queso-pistacho-1",
                }
            ],
        }

    async def forbidden_sleep(delay_seconds: float) -> None:
        raise AssertionError(
            f"candidate extraction inadequacy must not trigger a search retry: {delay_seconds}"
        )

    monkeypatch.setattr(
        mcp,
        "scrape_news_sources",
        one_source,
    )
    monkeypatch.setattr(turbo, "_sleep_before_source_search_retry", forbidden_sleep)
    monkeypatch.setattr(
        mcp,
        "extract_article_content",
        lambda url: {
            "success": True,
            "title": "Receta de tarta de queso y pistacho",
            "content": (
                "Receta con ingredientes de queso y pistacho. Preparacion paso a paso de la tarta. " * 12
            ),
            "word_count": 240,
        },
    )

    brief = await turbo._scrape_source_brief(
        "tarta de queso pistacho",
        _domain(("Postres",)),
        min_sources=2,
    )

    assert brief == ""
    assert search_calls == 1


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "first_result",
    [
        {"success": True, "articles": []},
        {"success": False, "error": "Temporary failure in name resolution"},
    ],
    ids=("empty-provider-chain", "dns-failure"),
)
async def test_source_brief_retries_transient_search_then_recovers(monkeypatch, first_result) -> None:
    import rankstein_mcp_server as mcp

    articles = [
        {
            "title": f"Tarta de queso y pistacho: receta cremosa {index}",
            "snippet": "Ingredientes y preparacion de la tarta de queso con pistacho",
            "url": f"https://example.test/tarta-queso-pistacho-{index}",
        }
        for index in (1, 2)
    ]
    search_results = iter(
        [
            first_result,
            {"success": True, "articles": articles},
        ]
    )
    search_calls = 0
    slept: list[float] = []

    def transient_then_success(*args, **kwargs):
        nonlocal search_calls
        search_calls += 1
        return next(search_results)

    async def record_sleep(delay_seconds: float) -> None:
        slept.append(delay_seconds)

    monkeypatch.setattr(mcp, "scrape_news_sources", transient_then_success)
    monkeypatch.setattr(turbo, "_sleep_before_source_search_retry", record_sleep)
    monkeypatch.setattr(
        mcp,
        "extract_article_content",
        lambda url: {
            "success": True,
            "title": "Receta de tarta de queso y pistacho",
            "content": (
                "Receta con ingredientes de queso y pistacho. Preparacion paso a paso de la tarta. " * 12
            ),
            "word_count": 240,
        },
    )

    brief = await turbo._scrape_source_brief(
        "tarta de queso pistacho",
        _domain(("Postres",)),
        min_sources=2,
    )

    assert "SOURCE 1" in brief
    assert "SOURCE 2" in brief
    assert search_calls == 2
    assert slept == [5.0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_source_brief_stops_after_bounded_empty_search_retries(monkeypatch) -> None:
    import rankstein_mcp_server as mcp

    search_calls = 0
    slept: list[float] = []

    def empty_search(*args, **kwargs):
        nonlocal search_calls
        search_calls += 1
        return {"success": True, "articles": []}

    async def record_sleep(delay_seconds: float) -> None:
        slept.append(delay_seconds)

    def forbidden_extract(url: str):
        raise AssertionError(f"empty search must not attempt extraction: {url}")

    monkeypatch.setattr(mcp, "scrape_news_sources", empty_search)
    monkeypatch.setattr(mcp, "extract_article_content", forbidden_extract)
    monkeypatch.setattr(turbo, "_sleep_before_source_search_retry", record_sleep)

    brief = await turbo._scrape_source_brief(
        "tarta de queso pistacho",
        _domain(("Postres",)),
        min_sources=2,
    )

    assert brief == ""
    assert search_calls == 3
    assert slept == [5.0, 15.0]


def _complete_remaster_report() -> dict:
    assets = []
    details = []
    for source_index in range(1, 16):
        pair_id = f"source-{source_index:02d}"
        for variant in ("viral_visual", "recipe_card"):
            assets.append(
                {
                    "pair_id": pair_id,
                    "variant": variant,
                    "source": "pinterest",
                    "original_pin_id": f"pin-{source_index:02d}",
                }
            )
            details.append({"job_id": f"job-{source_index:02d}-{variant}"})
    return {
        "success": True,
        "domain_handle": "recetagenial",
        "slug": "tarta-de-prueba",
        "pipeline_run_id": "recetagenial-run-1",
        "target_count": 30,
        "source_target": 15,
        "accepted_source_count": 15,
        "pair_count": 15,
        "generated_count": 30,
        "missing_count": 0,
        "source_counts": {"pinterest": 15, "native": 0},
        "variant_contract": {
            "variants_per_source": 2,
            "variants": ["viral_visual", "recipe_card"],
        },
        "assets": assets,
        "enqueue": {
            "success": True,
            "images_enqueued": 30,
            "jobs_enqueued": 30,
            "details": details,
        },
    }


@pytest.mark.unit
def test_complete_remaster_report_proves_15_pairs_and_30_queue_jobs() -> None:
    assert turbo._validate_article_remaster_report(_complete_remaster_report()) == (True, "")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "actual", "expected"),
    [
        ("domain_handle", "recetadolce", "recetagenial"),
        ("slug", "same-slug-other-domain", "tarta-de-prueba"),
        ("pipeline_run_id", "recetagenial-run-2", "recetagenial-run-1"),
    ],
)
def test_remaster_report_identity_cannot_cross_article_runs(
    field: str,
    actual: str,
    expected: str,
) -> None:
    report = _complete_remaster_report()
    report[field] = actual

    valid, reason = turbo._validate_article_remaster_report(
        report,
        expected_domain_handle="recetagenial",
        expected_slug="tarta-de-prueba",
        expected_pipeline_run_id="recetagenial-run-1",
    )

    assert valid is False
    assert field in reason
    assert expected in reason


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("generated_count",), 28, "generated_count=28"),
        (("pair_count",), 14, "pair_count=14"),
        (("enqueue", "jobs_enqueued"), 29, "jobs_enqueued=29"),
        (("success",), False, "marked incomplete"),
    ],
)
def test_incomplete_remaster_report_cannot_mark_article_live(
    path: tuple[str, ...],
    value,
    message: str,
) -> None:
    report = _complete_remaster_report()
    target = report
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    valid, reason = turbo._validate_article_remaster_report(report)

    assert valid is False
    assert message in reason


@pytest.mark.unit
def test_native_filled_remaster_report_cannot_mark_article_live() -> None:
    report = _complete_remaster_report()
    report["source_counts"] = {"pinterest": 1, "native": 14}

    valid, reason = turbo._validate_article_remaster_report(report)

    assert valid is False
    assert "15 unique scraped Pinterest sources" in reason


@pytest.mark.unit
def test_duplicate_pinterest_sources_cannot_fill_multiple_pairs() -> None:
    report = _complete_remaster_report()
    for asset in report["assets"][-2:]:
        asset["original_pin_id"] = "pin-01"

    valid, reason = turbo._validate_article_remaster_report(report)

    assert valid is False
    assert "15 unique Pinterest sources" in reason


@pytest.mark.unit
@pytest.mark.asyncio
async def test_remaster_launcher_reuses_valid_existing_run_report_without_requeue(
    tmp_path: Path, monkeypatch
) -> None:
    from dataclasses import replace

    domain = replace(
        _domain(("Postres",)),
        handle="recetagenial",
        domain="recetagenial.com",
    )
    report_dir = tmp_path / "data" / "reports" / "campaigns"
    report_dir.mkdir(parents=True)
    report_path = report_dir / "tarta-de-prueba_remaster_existing.json"
    report_path.write_text(
        __import__("json").dumps(_complete_remaster_report()),
        encoding="utf-8",
    )
    monkeypatch.setattr(turbo, "PROJECT_ROOT", tmp_path)

    async def forbidden_subprocess(*args, **kwargs):
        raise AssertionError("a valid existing report must prevent another campaign enqueue")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden_subprocess)

    result = await turbo._launch_article_remaster_campaign(
        keyword="tarta de prueba",
        title="Tarta de prueba",
        slug="tarta-de-prueba",
        category="Postres",
        domain=domain,
        pipeline_run_id="recetagenial-run-1",
        recipe_ingredients=["200 g de chocolate"],
        recipe_steps=["Mezcla y hornea."],
    )

    assert result["success"] is True
    assert result["reused_existing_report"] is True
    assert Path(result["report_path"]) == report_path


@pytest.mark.unit
def test_duplicate_queue_job_ids_cannot_prove_complete_enqueue() -> None:
    report = _complete_remaster_report()
    report["enqueue"]["details"][-1]["job_id"] = report["enqueue"]["details"][0]["job_id"]

    valid, reason = turbo._validate_article_remaster_report(report)

    assert valid is False
    assert "duplicate queue job IDs" in reason

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


def _inline_trend_validation(monkeypatch) -> None:
    """Exercise the unchanged strict service with isolated mocked providers."""

    async def validate(domain, pinterest_terms, **kwargs):
        return trend_intelligence.refresh_domain_trend_lists(
            [domain],
            limit_per_domain=15,
            append_to_roadmap=True,
            pinterest_terms=pinterest_terms,
            region=kwargs["region"],
            use_playwright=True,
            candidate_origin_policy="pinterest_required",
        )

    monkeypatch.setattr(turbo, "_run_bounded_trend_validation", validate)


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
    _inline_trend_validation(monkeypatch)

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
        return [*old_terms, "tarta de coco publicada", "tarta de coco fallida", fresh_phrase]

    def google_only(*args):
        raise AssertionError("Google discovery must not supply production candidates")

    monkeypatch.setattr(trend_intelligence, "_fetch_pinterest_niche_trending_terms_async", collect)
    monkeypatch.setattr(trend_intelligence, "_search_volume_proxy", lambda *args: 8.0)
    monkeypatch.setattr(trend_intelligence, "fetch_google_news_signals", lambda *args: [])
    monkeypatch.setattr(trend_intelligence, "fetch_google_autocomplete_terms", google_only)
    monkeypatch.setattr(trend_intelligence, "fetch_google_news_discovery_terms", google_only)
    monkeypatch.setattr(trend_intelligence, "fetch_google_trending_terms", google_only)
    _inline_trend_validation(monkeypatch)

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
    _inline_trend_validation(monkeypatch)
    await asyncio.gather(turbo._auto_refresh_keywords(first), turbo._auto_refresh_keywords(second))
    assert calls == {"first": [], "second": ["tarta de coco"]}


@pytest.mark.unit
@pytest.mark.parametrize(
    "keyword",
    [
        "croquetas caseras para gato",
        "mousse de chocolate saudável",
        "mousse de chocolate para recheio de bolo",
        "mousse de chocolate como fazer",
        "croquetas caseras recetas para hacer",
    ],
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
async def test_worker_does_not_reserve_old_pending_foreign_generic_or_off_domain_phrases(
    tmp_path, monkeypatch
) -> None:
    from rankstein.keyword_roadmap import EXPECTED_HEADER, read_keyword_rows

    domain = replace(_domain(("Postres",)), root=tmp_path, keywords_file=tmp_path / "keywords.md")
    rejected = [
        "mousse de chocolate como fazer",
        "croquetas caseras recetas para hacer",
        "croquetas caseras para gato",
    ]
    domain.keywords_file.write_text(
        f"# Test\n\n{EXPECTED_HEADER}\n|---|---|---|---|---|---|\n"
        + "".join(
            f"| {phrase} | Postres | Pinterest Trends | test | High | Pending |\n" for phrase in rejected
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(turbo, "_PRODUCTION_BATCH_TRACKER", None)
    monkeypatch.setattr(turbo, "_load_pinterest_qualified_keyword_keys", lambda _: (set(rejected), "ok"))
    refreshes = []

    async def refresh(*args, **kwargs):
        refreshes.append(kwargs)
        return 0

    async def forbidden_article(*args, **kwargs):
        raise AssertionError("existing noisy Pending phrase reached a writer")

    monkeypatch.setattr(turbo, "_auto_refresh_keywords", refresh)
    monkeypatch.setattr(turbo, "process_keyword", forbidden_article)
    await turbo._run_domain(domain, workers=2, limit=2, once=True)

    assert len(refreshes) == 1
    assert all(row.status == "Pending" for row in read_keyword_rows(domain.keywords_file))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_production_refresh_deadline_cancels_and_cleans_up_collector(monkeypatch, caplog) -> None:
    cleaned_up = []
    real_wait_for = asyncio.wait_for

    async def collect(*args):
        try:
            await asyncio.sleep(10)
        finally:
            cleaned_up.append(True)

    async def short_deadline(task, *, timeout):  # noqa: ASYNC109
        assert timeout == 300
        return await real_wait_for(task, timeout=0.001)

    def forbidden_refresh(*args, **kwargs):
        raise AssertionError("timed-out Pinterest evidence cannot authorize keywords")

    monkeypatch.setattr(trend_intelligence, "_fetch_pinterest_niche_trending_terms_async", collect)
    monkeypatch.setattr(trend_intelligence, "refresh_domain_trend_lists", forbidden_refresh)
    monkeypatch.setattr(turbo.asyncio, "wait_for", short_deadline)
    assert await turbo._auto_refresh_keywords(_domain(("Postres",))) == 0
    assert cleaned_up == [True]
    assert "TimeoutError during pinterest_collection (deadline=300s" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "error", "cancel", "success"])
async def test_research_reason_tracks_real_stage_deadline_and_terminal_state(monkeypatch, failure) -> None:
    reasons = []

    class Tracker:
        def mark_domain_waiting(self, handle, reason):
            reasons.append((handle, reason))

    async def collect(*args):
        return ["tarta de coco"]

    async def validate(*args, **kwargs):
        assert reasons[-1][1].startswith("research_in_progress stage=exact_validation")
        assert "deadline_seconds=600" in reasons[-1][1]
        if failure == "timeout":
            raise TimeoutError
        if failure == "error":
            raise ValueError("isolated validation error")
        if failure == "cancel":
            raise asyncio.CancelledError
        return {"domains": {"test": {"roadmap_added": 2}}}

    monkeypatch.setattr(turbo, "_PRODUCTION_BATCH_TRACKER", Tracker())
    monkeypatch.setattr(trend_intelligence, "_fetch_pinterest_niche_trending_terms_async", collect)
    monkeypatch.setattr(turbo, "_run_bounded_trend_validation", validate)
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await turbo._auto_refresh_keywords(_domain(("Postres",)))
    else:
        assert await turbo._auto_refresh_keywords(_domain(("Postres",))) == (2 if failure == "success" else 0)

    assert reasons[0][1].startswith("research_in_progress stage=pinterest_collection")
    assert "deadline_seconds=300" in reasons[0][1]
    assert "deadline_at=" in reasons[0][1]
    expected = {
        "timeout": "research_timeout",
        "error": "research_failed",
        "cancel": "research_cancelled",
        "success": "research_complete",
    }[failure]
    assert reasons[-1][1].startswith(f"{expected} stage=exact_validation")
    if failure != "success":
        assert "error_type=" in reasons[-1][1]
    else:
        assert "new_pending_count=2" in reasons[-1][1]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_trend_validation_child_receives_exact_phrases_and_no_credentials(monkeypatch) -> None:
    captured = {}

    class Process:
        returncode = None
        pid = 42001

        async def communicate(self, request):
            captured["request"] = json.loads(request)
            self.returncode = 0
            return b'{"report":{"domains":{"test":{"roadmap_added":1}}}}', b""

    async def spawn(*args, **kwargs):
        captured["args"] = args
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    report = await turbo._run_bounded_trend_validation(
        _domain(("Postres",)), ["tarta de coco"], region="ES", timeout=5
    )

    assert report["domains"]["test"]["roadmap_added"] == 1
    request = captured["request"]
    assert request["pinterest_terms"] == ["tarta de coco"]
    assert request["domain"]["handle"] == "test"
    assert request["domain"]["domain"] == "test.example"
    assert not {"pinterest_email", "pinterest_password", "supabase_url", "supabase_service_role_key"} & set(
        request["domain"]
    )
    assert 'candidate_origin_policy="pinterest_required"' in captured["args"][-1]
    assert "tarta de coco" not in " ".join(captured["args"])


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "cancel", "exception"])
async def test_trend_validation_failure_reaps_child_and_prevents_late_roadmap_writes(
    monkeypatch, failure
) -> None:
    started = asyncio.Event()
    terminated = []
    late_writes = []

    class Process:
        returncode = None
        pid = 42002
        writing = None

        async def communicate(self, request):
            async def write_later():
                await asyncio.sleep(0.02)
                late_writes.append("unauthorized late roadmap write")

            self.writing = asyncio.create_task(write_later())
            started.set()
            if failure == "exception":
                raise OSError("isolated pipe failure")
            await asyncio.Future()

    process = Process()

    async def spawn(*args, **kwargs):
        return process

    async def terminate(owned):
        assert owned is process
        terminated.append(owned.pid)
        owned.writing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owned.writing
        owned.returncode = -9

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(turbo, "_terminate_process_tree", terminate)
    task = asyncio.create_task(
        turbo._run_bounded_trend_validation(
            _domain(("Postres",)), ["tarta de coco"], region="ES", timeout=0.001
        )
    )
    await started.wait()
    if failure == "cancel":
        task.cancel()
    error = {"timeout": TimeoutError, "cancel": asyncio.CancelledError, "exception": OSError}[failure]
    with pytest.raises(error):
        await task
    await asyncio.sleep(0.025)
    assert terminated == [process.pid]
    assert late_writes == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_real_cancelled_validation_process_cannot_write_roadmap_after_return(
    tmp_path, monkeypatch
) -> None:
    domain = replace(_domain(("Postres",)), root=tmp_path, keywords_file=tmp_path / "roadmap.md")
    children = []
    original_spawn = turbo._create_owned_subprocess
    worker = """
import json,sys,time
from pathlib import Path
request=json.loads(sys.stdin.buffer.read().decode('utf-8'))
roadmap=Path(request['domain']['keywords_file'])
roadmap.with_suffix('.started').write_text('started')
time.sleep(10)
roadmap.write_text('late write must never happen')
"""

    async def capture_spawn(*args, **kwargs):
        process = await original_spawn(*args, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(turbo, "_TREND_VALIDATION_WORKER", worker)
    monkeypatch.setattr(turbo, "_create_owned_subprocess", capture_spawn)
    try:
        with pytest.raises(TimeoutError):
            await turbo._run_bounded_trend_validation(domain, ["tarta de coco"], region="ES", timeout=5)
        assert domain.keywords_file.with_suffix(".started").exists()
        assert len(children) == 1 and children[0].returncode is not None
        assert not domain.keywords_file.exists()
    finally:
        for process in children:
            await turbo._cleanup_owned_process(process)


@pytest.mark.unit
@pytest.mark.parametrize("configured,expected", [("900", 300), ("nan", 300), ("-1", 300), ("12", 12)])
def test_trend_deadlines_are_bounded(configured, expected, monkeypatch) -> None:
    monkeypatch.setenv("TEST_TREND_DEADLINE", configured)
    assert turbo._trend_research_deadline("TEST_TREND_DEADLINE", 300) == expected


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

    async def reconcile(_, **kwargs):
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

    def shared_queue():
        # The production upload bridge writes primary jobs into the shared queue.
        # An accidental domain_handle argument must fail this regression test.
        return Queue()

    monkeypatch.setattr(pinterest_automation, "get_job_queue", shared_queue)
    monkeypatch.setattr(reconcile, "reconcile_production_article", finish)
    await turbo._reconcile_awaiting_articles(domain)
    assert calls[0]["batch_tracker"] is tracker
    assert calls[0]["primary_job_id"] == "primary-exact"
    assert calls[0]["pipeline_run_id"] == run_id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_article_worker_generates_while_owned_campaign_repair_is_running(tmp_path, monkeypatch) -> None:
    import rankstein.production_safety as safety
    from rankstein.keyword_roadmap import EXPECTED_HEADER

    domain = replace(_domain(("Postres",)), root=tmp_path, keywords_file=tmp_path / "keywords.md")
    domain.keywords_file.write_text(
        f"# Test\n\n{EXPECTED_HEADER}\n|---|---|---|---|---|---|\n"
        "| tarta de coco | Postres | Pinterest Trends | test | High | Pending |\n",
        encoding="utf-8",
    )
    repair_started = asyncio.Event()
    repair_cleaned = asyncio.Event()
    created = []

    class Tracker:
        def __init__(self):
            self.data = {"domains": {"test": {"articles": []}}}

        def attempted_keyword_keys(self, handle):
            return set()

        def verified(self, handle):
            return 0

        def published_count(self, handle):
            return len(created)

        def start_keyword(self, *args):
            pass

        def complete_keyword(self, *args):
            pass

    async def repair(_, **kwargs):
        assert kwargs["max_campaigns"] == 1
        repair_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            repair_cleaned.set()

    async def article(keyword, *args, **kwargs):
        await repair_started.wait()
        assert not repair_cleaned.is_set()
        created.append(keyword)
        return "Needs Verification"

    async def sleep(seconds):
        assert seconds == 2
        raise RuntimeError("test worker checkpoint")

    monkeypatch.setattr(safety, "campaign_admission", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(turbo, "_PRODUCTION_BATCH_TRACKER", Tracker())
    monkeypatch.setattr(turbo, "_reconcile_awaiting_articles", repair)
    monkeypatch.setattr(turbo, "_load_pinterest_qualified_keyword_keys", lambda _: ({"tarta de coco"}, "ok"))
    monkeypatch.setattr(turbo, "process_keyword", article)
    monkeypatch.setattr(turbo.asyncio, "sleep", sleep)
    with pytest.raises(RuntimeError, match="test worker checkpoint"):
        await turbo._run_domain(domain, workers=1, limit=1, once=False, success_target=10)
    assert created == ["tarta de coco"]
    assert repair_cleaned.is_set()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_campaign_repair_lane_singleflight_cooldown_and_cursor(monkeypatch) -> None:
    now = [100.0]
    calls = []

    async def repair(_, **kwargs):
        calls.append(kwargs)
        return kwargs["cursor"] + 1

    monkeypatch.setattr(turbo, "_reconcile_awaiting_articles", repair)
    monkeypatch.setattr(turbo.time, "monotonic", lambda: now[0])
    lane = turbo._DomainRepairLane(_domain(("Postres",)))
    lane.schedule()
    first = lane.task
    lane.schedule()
    assert lane.task is first
    await first
    lane.schedule()
    assert lane.task is None
    assert lane.cursor == 1
    now[0] += 61
    lane.schedule()
    await lane.task
    await lane.close()
    assert calls == [{"max_campaigns": 1, "cursor": 0}, {"max_campaigns": 1, "cursor": 1}]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_campaign_repair_close_waits_for_cleanup_despite_repeated_parent_cancel(monkeypatch) -> None:
    started = asyncio.Event()
    cleaning = asyncio.Event()
    release = asyncio.Event()

    async def repair(_, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()

    monkeypatch.setattr(turbo, "_reconcile_awaiting_articles", repair)
    lane = turbo._DomainRepairLane(_domain(("Postres",)))
    lane.schedule()
    await started.wait()
    closing = asyncio.create_task(lane.close())
    await cleaning.wait()
    closing.cancel()
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    await closing
    assert lane.task is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bounded_campaign_reconciliation_rotates_failed_reports(tmp_path, monkeypatch) -> None:
    import pinterest_automation
    import rankstein.pipeline_events as events
    import rankstein.production_reconcile as reconcile
    from rankstein.production_batch import ProductionBatchTracker

    domain = replace(_domain(("Postres",)), root=tmp_path)
    db = tmp_path / "events.db"
    tracker = ProductionBatchTracker(
        project_root=tmp_path,
        batch_id="production-fair-repair",
        domain_handles=[domain.handle],
        target_per_domain=10,
    )
    runs = []
    for keyword in ("tarta de coco", "tarta de pera"):
        run_id = events.start_pipeline_run(domain_handle=domain.handle, keyword=keyword, db_path=db)
        runs.append(run_id)
        events.record_pipeline_stage(
            run_id, "primary_pin_publish", "complete", details={"primary_job_id": run_id}, db_path=db
        )
        tracker.start_keyword(domain.handle, keyword, "Postres", "Pinterest Trends")
        tracker.attach_run(domain.handle, keyword, run_id)
        tracker.complete_keyword(domain.handle, keyword, "Needs Verification")

    class Queue:
        async def get_job_outcome_async(self, job_id):
            return {"state": "completed"}

    calls = []

    async def failed_campaign(**kwargs):
        calls.append(kwargs["pipeline_run_id"])
        raise reconcile.ReconciliationError("insufficient_clean_sources")

    monkeypatch.setattr(events, "PIPELINE_DB", db)
    monkeypatch.setattr(turbo, "_PRODUCTION_BATCH_TRACKER", tracker)
    monkeypatch.setattr(pinterest_automation, "get_job_queue", lambda: Queue())
    monkeypatch.setattr(reconcile, "reconcile_production_article", failed_campaign)
    cursor = await turbo._reconcile_awaiting_articles(domain, max_campaigns=1)
    await turbo._reconcile_awaiting_articles(domain, max_campaigns=1, cursor=cursor)
    assert calls == runs
    assert tracker.verified(domain.handle) == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_remaster_launches_share_domain_lock_and_recheck_after_wait(monkeypatch) -> None:
    first_started = asyncio.Event()
    release = asyncio.Event()
    proven = []

    async def launch(**kwargs):
        if proven:
            return {"success": True, "reused_existing_report": True}
        first_started.set()
        await release.wait()
        proven.append(kwargs["pipeline_run_id"])
        return {"success": True}

    monkeypatch.setattr(turbo, "_launch_article_remaster_campaign_unlocked", launch)
    args = dict(
        keyword="tarta", title="Tarta", slug="tarta", category="Postres", domain=_domain(("Postres",))
    )
    first = asyncio.create_task(turbo._launch_article_remaster_campaign(**args, pipeline_run_id="exact"))
    await first_started.wait()
    second = asyncio.create_task(turbo._launch_article_remaster_campaign(**args, pipeline_run_id="exact"))
    await asyncio.sleep(0)
    assert not second.done()
    release.set()
    results = await asyncio.gather(first, second)
    assert proven == ["exact"]
    assert results[1]["reused_existing_report"] is True


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
@pytest.mark.parametrize(
    "hero_result",
    [
        None,
        "invalid result",
        {},
        {"success": False, "error": "All hero providers unavailable"},
        {"success": True, "source": "scraped"},
        {"success": True, "source": "pollinations", "output_path": "   "},
    ],
)
async def test_failed_or_invalid_hero_result_fails_closed_before_publish(monkeypatch, hero_result) -> None:
    domain = _domain(("Postres",))
    article = {
        "title": "Tarta de chocolate",
        "slug": "tarta-de-chocolate",
        "category": "Postres",
        "excerpt": "Una deliciosa tarta de chocolate casera.",
        "content": "Contenido culinario completo.",
        "recipe_schema": {
            "recipeIngredient": ["200 g de chocolate"],
            "recipeInstructions": [{"text": "Mezcla y hornea."}],
        },
    }
    events: list[tuple[str, str, dict]] = []

    import rankstein_mcp_server as mcp

    def forbidden_publish(*args, **kwargs):
        raise AssertionError("publishing must stop when no usable approved hero exists")

    monkeypatch.setattr(
        turbo,
        "get_hero_image",
        lambda **kwargs: hero_result,
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
        stage == "hero_image" and state == "failed" and details["fallback_allowed"] is True
        for stage, state, details in events
    )


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["unapproved_vendor", "pillow"])
async def test_unapproved_hero_source_is_rejected_before_upload(monkeypatch, source) -> None:
    domain = _domain(("Postres",))
    article = {
        "title": "Tarta de chocolate",
        "slug": "tarta-de-chocolate",
        "category": "Postres",
        "excerpt": "Una deliciosa tarta de chocolate casera.",
        "content": "Contenido culinario completo.",
        "recipe_schema": {
            "recipeIngredient": ["200 g de chocolate"],
            "recipeInstructions": [{"text": "Mezcla y hornea."}],
        },
    }

    import rankstein_mcp_server as mcp

    def forbidden_upload(*args, **kwargs):
        raise AssertionError("unapproved hero sources must not be uploaded")

    monkeypatch.setattr(
        turbo,
        "get_hero_image",
        lambda **kwargs: {
            "success": True,
            "output_path": "unapproved-hero.jpg",
            "source": source,
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
async def test_scraped_hero_source_is_accepted_for_upload(monkeypatch) -> None:
    domain = _domain(("Postres",))
    article = {
        "title": "Tarta de chocolate",
        "slug": "tarta-de-chocolate",
        "category": "Postres",
        "excerpt": "Una deliciosa tarta de chocolate casera.",
        "content": "Contenido culinario completo.",
        "recipe_schema": {
            "recipeIngredient": ["200 g de chocolate"],
            "recipeInstructions": [{"text": "Mezcla y hornea."}],
        },
    }

    import rankstein_mcp_server as mcp

    uploaded = []
    published = []
    events = []

    monkeypatch.setattr(
        turbo,
        "get_hero_image",
        lambda **kwargs: {
            "success": True,
            "output_path": "scraped-hero.jpg",
            "source": "scraped",
            "provider": "scraped_source",
        },
    )
    monkeypatch.setattr(
        mcp,
        "upload_image_to_supabase",
        lambda path, storage, handle: uploaded.append(path)
        or {"success": True, "public_url": "https://img.test/hero.jpg"},
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
        lambda **kwargs: published.append(kwargs)
        or {"success": True, "url": "https://test.example/tarta-de-chocolate"},
    )
    monkeypatch.setattr(mcp, "create_article_pin", lambda **kwargs: {"success": False, "error": "no pin"})
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
        pipeline_run_id="run-scraped-hero",
    )

    assert uploaded == ["scraped-hero.jpg"]
    assert len(published) == 1
    assert published[0]["domain_handle"] == domain.handle
    assert any(
        stage == "hero_image" and state == "complete" and details.get("source") == "scraped"
        for stage, state, details in events
    )
    assert status == "Needs Verification"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pollinations_hero_source_is_accepted_for_upload(monkeypatch) -> None:
    domain = _domain(("Postres",))
    article = {
        "title": "Tarta de chocolate",
        "slug": "tarta-de-chocolate",
        "category": "Postres",
        "excerpt": "Una deliciosa tarta de chocolate casera.",
        "content": "Contenido culinario completo.",
        "recipe_schema": {
            "recipeIngredient": ["200 g de chocolate"],
            "recipeInstructions": [{"text": "Mezcla y hornea."}],
        },
    }

    import rankstein_mcp_server as mcp

    uploaded = []
    published = []
    events = []

    monkeypatch.setattr(
        turbo,
        "get_hero_image",
        lambda **kwargs: {
            "success": True,
            "output_path": "pollinations-hero.jpg",
            "source": "pollinations",
            "provider": "pollinations",
        },
    )
    monkeypatch.setattr(
        mcp,
        "upload_image_to_supabase",
        lambda path, storage, handle: uploaded.append(path)
        or {"success": True, "public_url": "https://img.test/hero.jpg"},
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
        lambda **kwargs: published.append(kwargs)
        or {"success": True, "url": "https://test.example/tarta-de-chocolate"},
    )
    monkeypatch.setattr(mcp, "create_article_pin", lambda **kwargs: {"success": False, "error": "no pin"})
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
        pipeline_run_id="run-pollinations-hero",
    )

    assert uploaded == ["pollinations-hero.jpg"]
    assert len(published) == 1
    assert published[0]["domain_handle"] == domain.handle
    assert any(
        stage == "hero_image" and state == "complete" and details.get("source") == "pollinations"
        for stage, state, details in events
    )
    assert status == "Needs Verification"


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

    requests = []

    async def http_request(url, **kwargs):
        requests.append({"url": url, **kwargs})
        return Response()

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("RANKSTEIN_ARTICLE_PROVIDER", "hermes-codex")
    monkeypatch.setenv("RANKSTEIN_HERMES_CODEX_API_KEY", "test-api-key")
    monkeypatch.setattr(turbo, "_bounded_hermes_article_http", http_request)

    generated = await turbo._call_hermes_codex_for_article(
        "tarta de prueba",
        _domain(("Postres",)),
    )

    assert generated == article
    assert len(requests) == 1
    assert "fallback_providers" not in requests[0]["payload"]
    assert requests[0]["timeout"] == turbo._hermes_codex_article_timeout_seconds()


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

    calls = []

    async def http_request(*args, **kwargs):
        calls.append(kwargs)
        return Response()

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("RANKSTEIN_ARTICLE_PROVIDER", "hermes-codex")
    monkeypatch.setenv("RANKSTEIN_HERMES_CODEX_API_KEY", "test-api-key")
    monkeypatch.setattr(turbo, "_bounded_hermes_article_http", http_request)

    assert (
        await turbo._call_hermes_codex_for_article(
            "tarta de prueba",
            _domain(("Postres",)),
        )
        is None
    )
    assert len(calls) == 1


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

    async def forbidden_network(*args, **kwargs):
        raise AssertionError("Hermes network request must not be prepared")

    monkeypatch.setattr(turbo, "_bounded_hermes_article_http", forbidden_network)

    assert await turbo._call_hermes_codex_for_article("tarta", _domain(("Postres",))) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_hermes_http_worker_passes_secrets_only_on_stdin_and_preserves_response(monkeypatch) -> None:
    captured = {}

    class Process:
        returncode = None
        pid = 41001

        async def communicate(self, request):
            captured["request"] = json.loads(request)
            self.returncode = 0
            return json.dumps({"status_code": 429, "body": '{"error":"quota"}'}).encode(), b""

    async def spawn(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    response = await turbo._bounded_hermes_article_http(
        "http://127.0.0.1:1/v1/chat/completions",
        headers={"Authorization": "Bearer test-secret-not-on-command-line"},
        payload={"messages": [{"content": "private prompt"}]},
        timeout=77,
    )

    assert response.status_code == 429
    assert response.json() == {"error": "quota"}
    assert captured["args"][1:4] == ("-I", "-u", "-c")
    assert "test-secret-not-on-command-line" not in " ".join(captured["args"])
    assert "private prompt" not in " ".join(captured["args"])
    assert captured["request"]["headers"]["Authorization"].endswith("test-secret-not-on-command-line")
    assert captured["request"]["timeout"] == 77
    assert captured["kwargs"]["stdin"] == asyncio.subprocess.PIPE


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["deadline", "cancel", "exception"])
async def test_hermes_http_worker_reaps_owned_child_before_failure_returns(monkeypatch, failure) -> None:
    started = asyncio.Event()
    terminated = []

    class Process:
        returncode = None
        pid = 41002

        async def communicate(self, request):
            started.set()
            if failure == "exception":
                raise OSError("isolated pipe failure")
            await asyncio.Future()

    process = Process()

    async def spawn(*args, **kwargs):
        return process

    async def terminate(owned):
        assert owned is process
        terminated.append(owned.pid)
        owned.returncode = -9

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(turbo, "_terminate_process_tree", terminate)
    task = asyncio.create_task(
        turbo._bounded_hermes_article_http("http://unused", headers={}, payload={}, timeout=0.01)
    )
    await started.wait()
    if failure == "cancel":
        task.cancel()
    error = {
        "deadline": turbo.requests.exceptions.Timeout,
        "cancel": asyncio.CancelledError,
        "exception": OSError,
    }[failure]
    with pytest.raises(error):
        await task
    assert terminated == [process.pid]
    assert process.returncode == -9


@pytest.mark.unit
@pytest.mark.asyncio
async def test_hermes_http_total_timeout_remains_availability_only_fallback(monkeypatch) -> None:
    monkeypatch.setattr(turbo, "_hermes_openai_codex_attestation", lambda: (True, "gpt-test"))
    monkeypatch.setenv("RANKSTEIN_HERMES_CODEX_API_KEY", "test-key")
    monkeypatch.setenv("RANKSTEIN_ENABLE_HERMES_CODEX_ARTICLES", "1")

    async def deadline(*args, **kwargs):
        raise turbo.requests.exceptions.Timeout("total deadline")

    monkeypatch.setattr(turbo, "_bounded_hermes_article_http", deadline)
    result = await turbo._call_hermes_codex_for_article_result("tarta de coco", _domain(("Postres",)))

    assert result.article is None
    assert result.outcome == "availability_failure"
    assert result.permits_free_fallback


@pytest.mark.unit
@pytest.mark.asyncio
async def test_real_trickling_http_response_cannot_outlive_total_deadline(monkeypatch) -> None:
    # A disposable loopback server and child only; never contact Hermes or any
    # production provider. Bytes arrive well inside the socket inactivity limit.
    connected = asyncio.Event()
    stopped = asyncio.Event()
    children = []
    handlers = []
    original_spawn = turbo._create_owned_subprocess

    async def capture_spawn(*args, **kwargs):
        process = await original_spawn(*args, **kwargs)
        children.append(process)
        return process

    async def trickle(reader, writer):
        handlers.append(asyncio.current_task())
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 100000\r\nConnection: close\r\n\r\n")
            await writer.drain()
            connected.set()
            while not stopped.is_set():
                writer.write(b" ")
                await writer.drain()
                await asyncio.sleep(0.01)
        except (OSError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    monkeypatch.setattr(turbo, "_create_owned_subprocess", capture_spawn)
    server = await asyncio.start_server(trickle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        with pytest.raises(turbo.requests.exceptions.Timeout, match="total HTTP deadline"):
            await turbo._bounded_hermes_article_http(
                f"http://127.0.0.1:{port}/test",
                headers={},
                payload={"test": "isolated"},
                timeout=5,
            )
        assert connected.is_set(), "test must actually receive a trickling response"
        assert len(children) == 1
        assert children[0].returncode is not None, "timed-out HTTP child was not reaped"
    finally:
        stopped.set()
        server.close()
        await server.wait_closed()
        if handlers:
            await asyncio.gather(*handlers)
        for process in children:
            await turbo._cleanup_owned_process(process)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("writer", ["codex", "hermes_free"])
@pytest.mark.parametrize("failure", ["cancel", "timeout", "exception"])
async def test_article_cli_abnormal_exit_reaps_only_its_owned_process(monkeypatch, writer, failure) -> None:
    started = asyncio.Event()
    terminated = []

    class Process:
        returncode = None
        pid = 41003

        async def communicate(self):
            started.set()
            if failure == "timeout":
                raise TimeoutError
            if failure == "exception":
                raise OSError("isolated pipe failure")
            await asyncio.Future()

    process = Process()

    async def spawn(*args, **kwargs):
        return process

    async def terminate(owned):
        assert owned is process
        terminated.append(owned.pid)
        owned.returncode = -9

    monkeypatch.setenv("RANKSTEIN_ENABLE_CODEX_CLI_ARTICLES", "1")
    monkeypatch.setenv("RANKSTEIN_CODEX_CLI_MODEL", "gpt-test")
    monkeypatch.setattr(turbo, "_hermes_free_article_target", lambda: (True, ("openrouter", "test:free")))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(turbo, "_terminate_process_tree", terminate)
    call = turbo._call_codex_cli_for_article if writer == "codex" else turbo._call_hermes_free_for_article
    task = asyncio.create_task(call("tarta de coco", _domain(("Postres",))))
    await started.wait()
    if failure == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        assert await task is None
    assert terminated == [process.pid]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_owned_spawn_cancellation_does_not_lose_child_handle(monkeypatch) -> None:
    spawning = asyncio.Event()
    allow_spawn = asyncio.Event()
    terminated = []

    class Process:
        returncode = None
        pid = 41004

    process = Process()

    async def spawn(*args, **kwargs):
        spawning.set()
        await allow_spawn.wait()
        return process

    async def terminate(owned):
        terminated.append(owned.pid)
        owned.returncode = -9

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(turbo, "_terminate_process_tree", terminate)
    task = asyncio.create_task(turbo._create_owned_subprocess("unused"))
    await spawning.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    allow_spawn.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert terminated == [process.pid]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_owned_cleanup_survives_repeated_cancellation_until_reaped(monkeypatch) -> None:
    started = asyncio.Event()
    allow_cleanup = asyncio.Event()

    class Process:
        returncode = None
        pid = 41005

    process = Process()

    async def terminate(owned):
        started.set()
        await allow_cleanup.wait()
        owned.returncode = -9

    monkeypatch.setattr(turbo, "_terminate_process_tree", terminate)
    task = asyncio.create_task(turbo._cleanup_owned_process(process))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    allow_cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.returncode == -9


@pytest.mark.unit
@pytest.mark.asyncio
async def test_windows_tree_cleanup_targets_exact_pid_not_browser_names(monkeypatch) -> None:
    from types import SimpleNamespace

    commands = []

    class Process:
        returncode = None
        pid = 41006

        def kill(self):
            self.returncode = -9

        async def wait(self):
            return self.returncode

    class Killer:
        returncode = 0

        async def wait(self):
            return 0

    async def spawn(*args, **kwargs):
        commands.append(args)
        return Killer()

    monkeypatch.setattr(turbo, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    process = Process()
    await turbo._terminate_process_tree(process)
    assert commands == [("taskkill", "/PID", str(process.pid), "/T", "/F")]
    assert process.returncode == -9


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
                    "source_path": f"source-{source_index:02d}.jpg",
                    "source_hash": "a" * 64,
                    "source_quality": {
                        "accepted": True,
                        "policy": "text_free_pinterest_source",
                        "version": 1,
                        "source_hash": "a" * 64,
                    },
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
@pytest.mark.asyncio
async def test_outer_reconcile_deadline_reaps_remaster_tree_and_closes_logs(tmp_path, monkeypatch) -> None:
    captured = {}
    terminated = []

    class Process:
        returncode = None
        pid = 41007

        async def wait(self):
            await asyncio.Future()

    process = Process()

    async def spawn(*args, **kwargs):
        captured.update(kwargs)
        return process

    async def terminate(owned):
        assert owned is process
        terminated.append(owned.pid)
        owned.returncode = -9

    monkeypatch.setattr(turbo, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(turbo, "_find_valid_article_remaster_report", lambda **_: None)
    monkeypatch.setattr(turbo, "_pipeline_event", lambda *args, **kwargs: None)
    monkeypatch.setenv("RANKSTEIN_ENABLE_ARTICLE_REMASTERS", "1")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(turbo, "_terminate_process_tree", terminate)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            turbo._launch_article_remaster_campaign(
                keyword="tarta de coco",
                title="Tarta de coco",
                slug="tarta-de-coco",
                category="Postres",
                domain=_domain(("Postres",)),
                pipeline_run_id="test-isolated-cancel",
            ),
            timeout=0.01,
        )

    assert terminated == [process.pid]
    assert process.returncode == -9
    assert captured["stdout"].closed
    assert captured["stderr"].closed


@pytest.mark.unit
def test_duplicate_queue_job_ids_cannot_prove_complete_enqueue() -> None:
    report = _complete_remaster_report()
    report["enqueue"]["details"][-1]["job_id"] = report["enqueue"]["details"][0]["job_id"]

    valid, reason = turbo._validate_article_remaster_report(report)

    assert valid is False
    assert "duplicate queue job IDs" in reason

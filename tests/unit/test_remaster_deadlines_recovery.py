from __future__ import annotations

import asyncio
import builtins
import json
import sqlite3
import time
import warnings
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from backend.services import remasterer
from rankstein import pipeline_events


@pytest.fixture(autouse=True)
def isolated_artifacts(monkeypatch, tmp_path):
    monkeypatch.setattr(remasterer, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(remasterer, "DOWNLOAD_DIR", tmp_path / "raw")
    monkeypatch.setattr(remasterer, "REMASTER_DIR", tmp_path / "final")
    monkeypatch.setattr(remasterer, "SESSION_DIR", tmp_path / "profiles" / "default")
    monkeypatch.setattr(remasterer, "_pipeline_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(remasterer, "_pipeline_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(remasterer, "record_pipeline_stage", lambda *_args, **_kwargs: None)


class FakeStudio:
    def __init__(self, sources=None):
        self.sources = sources or []
        self.last_collection_diagnostics = {}
        self.started = False
        self.stopped = False
        self.arguments = {}

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def collect_and_download(self, *_args, **kwargs):
        self.arguments = kwargs
        return self.sources


def _intake(studio, tmp_path):
    return remasterer._collect_campaign_sources(
        studio,
        "pastel de zanahoria sin horno",
        source_target=15,
        domain_handle="recetadolce",
        pipeline_run_id="isolated-run",
        download_dir=tmp_path / "attempt",
        collection_kwargs={},
    )


@pytest.mark.unit
def test_public_collector_has_hard_deadline_and_progress_during_slow_ocr(monkeypatch, capsys):
    studio = remasterer.PinRemasterer(session_name="deadline-test")
    monkeypatch.setattr(remasterer, "COLLECTION_PROGRESS_INTERVAL_SECONDS", 0.01)

    async def slow_collection(*_args, **_kwargs):
        studio.last_collection_diagnostics = {"phase": "collecting", "ocr_in_progress": 1}
        await asyncio.Event().wait()

    monkeypatch.setattr(studio, "_collect_and_download", slow_collection)
    result = asyncio.run(studio.collect_and_download("pastel", count=15, timeout_seconds=0.05))
    assert result == []
    assert studio.last_collection_diagnostics["blocked_reason"] == "collection_timeout"
    assert studio.last_collection_diagnostics["deadline_exceeded"] == 1
    output = capsys.readouterr().out
    assert "SOURCE_COLLECTION_PROGRESS" in output
    assert "ocr_running=1" in output


@pytest.mark.unit
def test_start_timeout_stops_owned_studio_and_never_collects(monkeypatch, tmp_path):
    studio = FakeStudio()
    monkeypatch.setattr(remasterer, "_held_campaign_source_pin_ids", lambda *_args: set())
    monkeypatch.setattr(remasterer, "BROWSER_START_TIMEOUT_SECONDS", 0.02)

    async def hung_start():
        await asyncio.Event().wait()

    monkeypatch.setattr(studio, "start", hung_start)
    result = asyncio.run(_intake(studio, tmp_path))
    assert result == []
    assert studio.stopped is True
    assert studio.arguments == {}
    assert studio.last_collection_diagnostics["blocked_reason"] == "starting_browser_timeout"


@pytest.mark.unit
def test_total_budget_reserves_cleanup_without_creating_unawaited_coroutines(monkeypatch, tmp_path):
    studio = FakeStudio()
    monkeypatch.setenv("RANKSTEIN_REMASTER_INTAKE_TIMEOUT_SECONDS", "0.01")
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        result = asyncio.run(_intake(studio, tmp_path))
    assert result == []
    assert studio.started is False
    assert not any(issubclass(item.category, RuntimeWarning) for item in recorded)


@pytest.mark.unit
def test_stop_timeout_is_failed_intake_not_success(monkeypatch, tmp_path):
    studio = FakeStudio()
    monkeypatch.setattr(remasterer, "_held_campaign_source_pin_ids", lambda *_args: set())
    monkeypatch.setattr(remasterer, "BROWSER_STOP_TIMEOUT_SECONDS", 0.02)

    async def hung_stop():
        await asyncio.Event().wait()

    monkeypatch.setattr(studio, "stop", hung_stop)
    result = asyncio.run(_intake(studio, tmp_path))
    assert result == []
    assert studio.last_collection_diagnostics["blocked_reason"] == "browser_cleanup_failed"
    assert studio.last_collection_diagnostics["cleanup_error_type"] == "TimeoutError"


@pytest.mark.unit
def test_cancelled_intake_cleans_up_and_propagates_cancellation(monkeypatch, tmp_path):
    studio = FakeStudio()
    monkeypatch.setattr(remasterer, "_held_campaign_source_pin_ids", lambda *_args: set())

    async def exercise():
        entered = asyncio.Event()

        async def hung_collection(*_args, **_kwargs):
            entered.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(studio, "collect_and_download", hung_collection)
        task = asyncio.create_task(_intake(studio, tmp_path))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
    assert studio.stopped is True
    assert studio.last_collection_diagnostics["blocked_reason"] == "source_intake_cancelled"


@pytest.mark.unit
def test_collection_timeout_cannot_reach_variant_creation(monkeypatch):
    studio = FakeStudio()
    monkeypatch.setattr(remasterer, "_held_campaign_source_pin_ids", lambda *_args: set())
    monkeypatch.setattr(remasterer, "PinRemasterer", lambda **_kwargs: studio)
    monkeypatch.setattr(remasterer, "COLLECTION_TIMEOUT_SECONDS", 0.02)

    async def hung_collection(*_args, **_kwargs):
        await asyncio.Event().wait()

    def forbidden(**_kwargs):
        raise AssertionError("timed-out intake must not compose variants")

    monkeypatch.setattr(studio, "collect_and_download", hung_collection)
    monkeypatch.setattr(remasterer, "create_viral_visual_pin", forbidden)
    monkeypatch.setattr(remasterer, "create_recipe_card_pin", forbidden)
    result = asyncio.run(
        remasterer.run_remasterer(
            "pastel de zanahoria sin horno",
            "Pastel de zanahoria sin horno",
            domain_handle="recetadolce",
            pipeline_run_id="isolated-run",
            recipe_ingredients=["200 g de zanahoria", "150 g de queso crema"],
            recipe_steps=["Ralla la zanahoria.", "Enfría la mezcla durante 2 horas."],
        )
    )
    assert result == []
    assert studio.stopped is True


@pytest.mark.unit
def test_actual_held_source_exclusions_are_exact_read_only_domain_run_scoped(tmp_path):
    database = tmp_path / "jobs.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE jobs(type TEXT, payload_json TEXT, status TEXT)")
        rows = [
            ("1", "held", "recetadolce", "run-a", "article_remaster_pairs", "pin_upload"),
            ("2", "pending", "recetadolce", "run-a", "article_remaster_pairs", "pin_upload"),
            ("3", "held", "recetagenial", "run-a", "article_remaster_pairs", "pin_upload"),
            ("4", "held", "recetadolce", "run-b", "article_remaster_pairs", "pin_upload"),
            ("5", "held", "recetadolce", "run-a", "article_publish", "pin_upload"),
            ("6", "held", "recetadolce", "run-a", "article_remaster_pairs", "other_job"),
        ]
        for pin_id, state, domain, run_id, campaign_type, job_type in rows:
            payload = {
                "domain_handle": domain,
                "extra": {
                    "domain_handle": domain,
                    "pipeline_run_id": run_id,
                    "campaign_type": campaign_type,
                    "source_pin_id": pin_id,
                },
            }
            connection.execute("INSERT INTO jobs VALUES(?,?,?)", (job_type, json.dumps(payload), state))
    original = database.read_bytes()
    excluded = remasterer._held_campaign_source_pin_ids("recetadolce", "run-a", queue_paths=[database])
    assert excluded == {"1"}
    assert database.read_bytes() == original


@pytest.mark.unit
def test_preflight_resolves_configured_queue_without_cold_automation_import(monkeypatch, tmp_path):
    shared = tmp_path / "configured.db"
    monkeypatch.setenv("PINTEREST_QUEUE_DB_FILE", str(shared))
    domain_root = tmp_path / "data" / "domains" / "recetagenial"
    domain_root.mkdir(parents=True)
    (domain_root / "domain.json").write_text(
        json.dumps({"handle": "recetagenial", "domain": "recetagenial.com"}), encoding="utf-8"
    )
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith("pinterest_automation") or name == "rankstein.domain":
            raise AssertionError("held preflight must not cold-boot automation or domain providers")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    assert remasterer._configured_held_source_queue_paths("recetagenial") == [
        shared,
        domain_root / "jobs.db",
    ]
    assert remasterer._held_campaign_source_pin_ids("recetagenial", "isolated-run") == set()


@pytest.mark.unit
def test_preflight_queue_path_honors_dotenv_and_environment_precedence(monkeypatch, tmp_path):
    monkeypatch.delenv("PINTEREST_QUEUE_DB_FILE", raising=False)
    (tmp_path / ".env").write_text("PINTEREST_QUEUE_DB_FILE=configured-from-dotenv.db\n", encoding="utf-8")
    assert remasterer._configured_held_source_queue_paths("recetadolce") == [
        Path("configured-from-dotenv.db"),
        tmp_path / "jobs.db",
    ]
    monkeypatch.setenv("PINTEREST_QUEUE_DB_FILE", "")
    assert remasterer._configured_held_source_queue_paths("recetadolce")[0] == (
        tmp_path / "data" / "queue" / "jobs.db"
    )
    with pytest.raises(ValueError, match="unknown domain"):
        remasterer._configured_held_source_queue_paths("unknown")


@pytest.mark.unit
def test_preflight_has_bounded_cold_start_allowance_before_browser(monkeypatch, tmp_path):
    studio = FakeStudio()

    def delayed_read(*_args):
        time.sleep(0.05)
        return {"123"}

    monkeypatch.setattr(remasterer, "_held_campaign_source_pin_ids", delayed_read)
    assert remasterer.HELD_SOURCE_PREFLIGHT_TIMEOUT_SECONDS == 30.0
    assert asyncio.run(_intake(studio, tmp_path)) == []
    assert studio.started is True
    assert studio.arguments["excluded_pin_ids"] == {"123"}
    assert "blocked_reason" not in studio.last_collection_diagnostics


@pytest.mark.unit
def test_collector_heartbeat_reaches_dashboard_events_without_raw_ocr(monkeypatch, tmp_path):
    studio = FakeStudio()
    database = tmp_path / "telemetry.db"
    # Production already owns a keyword run before launching the child. Wait
    # for a committed progress event rather than assuming an 80ms write on a
    # loaded host: late writes after completion must intentionally be dropped.
    pipeline_events.record_pipeline_stage(
        "isolated-run",
        "keyword_selected",
        "complete",
        domain_handle="recetadolce",
        keyword="pastel de zanahoria sin horno",
        db_path=database,
    )
    progress_seen = asyncio.Event()
    loop_holder = []
    monkeypatch.setattr(remasterer, "_held_campaign_source_pin_ids", lambda *_args: set())
    monkeypatch.setattr(remasterer, "COLLECTION_PROGRESS_INTERVAL_SECONDS", 0.01)

    def isolated_record(*args, **kwargs):
        pipeline_events.record_pipeline_stage(*args, **kwargs, db_path=database)
        loop_holder[0].call_soon_threadsafe(progress_seen.set)

    monkeypatch.setattr(remasterer, "record_pipeline_stage", isolated_record)

    async def slow_collection(*_args, **kwargs):
        studio.arguments = kwargs
        studio.last_collection_diagnostics.update(
            accepted=3, pins_examined=12, ocr_in_progress=1, raw_ocr="PRIVATE SOURCE TEXT"
        )
        await asyncio.wait_for(progress_seen.wait(), timeout=3.0)
        return []

    monkeypatch.setattr(studio, "collect_and_download", slow_collection)

    async def exercise():
        loop_holder.append(asyncio.get_running_loop())
        return await _intake(studio, tmp_path)

    assert asyncio.run(exercise()) == []
    with sqlite3.connect(database) as connection:
        run = connection.execute("SELECT domain_handle,keyword FROM pipeline_runs").fetchone()
        events = connection.execute(
            "SELECT stage,state,message,details_json FROM pipeline_events WHERE stage='pinterest_siphon' ORDER BY id"
        ).fetchall()
    assert run == ("recetadolce", "pastel de zanahoria sin horno")
    assert events
    assert all(row[0:2] == ("pinterest_siphon", "running") for row in events)
    progress = next(row for row in events if json.loads(row[3])["accepted"] == 3)
    counters = json.loads(progress[3])
    assert counters["accepted"] == 3
    assert counters["examined"] == 12
    assert counters["target"] == 15
    assert counters["remaining_sources"] == 12
    assert counters["ocr_in_progress"] == 1
    assert counters["domain_handle"] == "recetadolce"
    assert "3/15 accepted" in progress[2]
    assert "12 examined" in progress[2]
    assert "12 remaining" in progress[2]
    assert "PRIVATE SOURCE TEXT" not in str(events)
    assert "raw_ocr" not in str(events)


@pytest.mark.unit
def test_failed_progress_writer_does_not_interrupt_source_collection(monkeypatch, tmp_path):
    studio = FakeStudio()
    writes = []
    monkeypatch.setattr(remasterer, "_held_campaign_source_pin_ids", lambda *_args: set())
    monkeypatch.setattr(remasterer, "COLLECTION_PROGRESS_INTERVAL_SECONDS", 0.01)

    def unavailable(*_args, **_kwargs):
        writes.append(True)
        raise sqlite3.OperationalError("isolated lock failure")

    monkeypatch.setattr(remasterer, "record_pipeline_stage", unavailable)

    async def slow_collection(*_args, **kwargs):
        studio.arguments = kwargs
        await asyncio.sleep(0.04)
        return [{"pin_id": "123", "raw_path": "unused"}]

    monkeypatch.setattr(studio, "collect_and_download", slow_collection)
    result = asyncio.run(_intake(studio, tmp_path))
    assert writes
    assert len(result) == 1
    assert studio.stopped is True
    assert "blocked_reason" not in studio.last_collection_diagnostics


@pytest.mark.unit
def test_held_exclusions_are_passed_and_legacy_collector_cannot_return_held_sources(monkeypatch, tmp_path):
    sources = [{"pin_id": str(index), "raw_path": "unused"} for index in range(15)]
    studio = FakeStudio(sources)
    monkeypatch.setattr(remasterer, "_held_campaign_source_pin_ids", lambda *_args: {"0"})
    result = asyncio.run(_intake(studio, tmp_path))
    assert studio.arguments["excluded_pin_ids"] == {"0"}
    assert [item["pin_id"] for item in result] == [str(index) for index in range(1, 15)]
    assert studio.stopped is True


@pytest.mark.unit
def test_exclusion_read_failure_does_not_start_browser(monkeypatch, tmp_path):
    studio = FakeStudio()

    def broken_read(*_args):
        raise sqlite3.OperationalError("unavailable test database")

    monkeypatch.setattr(remasterer, "_held_campaign_source_pin_ids", broken_read)
    result = asyncio.run(_intake(studio, tmp_path))
    assert result == []
    assert studio.started is False
    assert studio.last_collection_diagnostics["blocked_reason"] == "source_intake_failed"


@pytest.mark.unit
def test_fresh_attempt_paths_cannot_overwrite_held_paths(tmp_path):
    first_raw, first_final = remasterer._isolated_remaster_directories("recetadolce", "run-a")
    next_raw, next_final = remasterer._isolated_remaster_directories("recetadolce", "run-a")
    assert first_raw != next_raw
    assert first_final != next_final
    assert first_raw.parent == tmp_path / "raw" / "recetadolce" / "run-a"
    assert first_final.parent == tmp_path / "final" / "recetadolce" / "run-a"


@pytest.mark.unit
def test_remaster_directories_separated_by_blog_day_keyword(tmp_path):
    raw_dir, final_dir = remasterer._isolated_remaster_directories(
        "recetagenial",
        "run-123",
        keyword="Pollo al horno con patatas",
        date_str="2026-10-09",
    )
    assert final_dir == tmp_path / "final" / "recetagenial" / "2026-10-09" / "pollo-al-horno-con-patatas"
    assert raw_dir.parent == tmp_path / "raw" / "recetagenial" / "2026-10-09" / "pollo-al-horno-con-patatas"
    assert final_dir.is_dir()
    assert raw_dir.is_dir()


@pytest.mark.unit
def test_profile_lease_is_nonblocking_and_recoverable_without_deleting_lock(tmp_path):
    first = remasterer._ProfileLease(tmp_path / "shared")
    second = remasterer._ProfileLease(tmp_path / "shared")
    other = remasterer._ProfileLease(tmp_path / "other")
    try:
        assert first.acquire() is True
        assert second.acquire() is False
        assert other.acquire() is True
        first.release()
        assert second.acquire() is True
        assert first.path.is_file()
    finally:
        first.release()
        second.release()
        other.release()


@pytest.mark.unit
def test_busy_profile_cannot_start_or_cleanup_another_browser(monkeypatch):
    first = remasterer.PinRemasterer(session_name="shared")
    second = remasterer.PinRemasterer(session_name="shared")
    browser_starts = []

    async def fake_browser_start(studio):
        browser_starts.append(studio)

    monkeypatch.setattr(remasterer.PinRemasterer, "_start_browser", fake_browser_start)

    async def exercise():
        await first.start()
        try:
            with pytest.raises(RuntimeError, match="remaster_profile_busy"):
                await second.start()
            assert first._profile_lease is not None
            assert second._profile_lease is None
        finally:
            await first.stop()
            await second.stop()

    asyncio.run(exercise())
    assert browser_starts == [first]


@pytest.fixture
def collector_cards(monkeypatch):
    class Element:
        def __init__(self, attributes):
            self.attributes = attributes

        async def get_attribute(self, name):
            return self.attributes.get(name)

    class Card:
        def __init__(self, index):
            self.index = index

        async def query_selector(self, selector):
            if selector == "img":
                return Element({"src": f"https://images.test/{self.index}.jpg", "alt": "pastel"})
            if selector == 'a[href*="/pin/"]':
                return Element({"href": f"/pin/{self.index}/", "title": "pastel"})
            return None

        async def inner_text(self):
            return "pastel"

    class Page:
        async def goto(self, *_args, **_kwargs):
            return None

    image = BytesIO()
    Image.new("RGB", (800, 1200), "tan").save(image, format="JPEG")

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, *_args, **_kwargs):
            return SimpleNamespace(status_code=200, content=image.getvalue())

    async def no_sleep(*_args):
        return None

    async def no_wall(_page):
        return False

    async def cards(_page):
        return [Card(index) for index in (1, 2, 3)]

    monkeypatch.setattr(remasterer.httpx, "AsyncClient", Client)
    monkeypatch.setattr(remasterer.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(remasterer, "_page_has_pinterest_login_wall", no_wall)
    monkeypatch.setattr(remasterer, "_query_pinterest_pin_cards", cards)
    monkeypatch.setattr(remasterer, "score_pin_relevance", lambda *_args, **_kwargs: 10)
    studio = remasterer.PinRemasterer(session_name="card-test")
    studio.page = Page()
    return studio


@pytest.mark.unit
def test_candidate_cap_bounds_ocr_attempts(monkeypatch, collector_cards):
    checks = []

    def assess(path):
        checks.append(path)
        return {"accepted": False, "reason": "embedded_text"}

    monkeypatch.setattr(remasterer, "assess_source_image", assess)
    result = asyncio.run(collector_cards.collect_and_download("pastel", count=1, max_candidates=2))
    assert result == []
    assert len(checks) == 2
    assert collector_cards.last_collection_diagnostics["pins_examined"] == 2
    assert collector_cards.last_collection_diagnostics["blocked_reason"] == "candidate_limit"


@pytest.mark.unit
def test_excluded_held_pin_is_skipped_before_download_or_ocr(monkeypatch, collector_cards):
    checks = []

    def assess(path):
        checks.append(Path(path).stem)
        return {"accepted": True, "source_hash": "a" * 64}

    monkeypatch.setattr(remasterer, "assess_source_image", assess)
    result = asyncio.run(collector_cards.collect_and_download("pastel", count=1, excluded_pin_ids={"1"}))
    assert [item["pin_id"] for item in result] == ["2"]
    assert checks == ["2"]
    assert collector_cards.last_collection_diagnostics["held_sources_skipped"] == 1

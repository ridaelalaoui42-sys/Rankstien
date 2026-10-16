from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image

from backend.services import remasterer


@pytest.fixture(autouse=True)
def isolated_intake(monkeypatch, tmp_path):
    monkeypatch.setattr(remasterer, "DOWNLOAD_DIR", tmp_path / "raw")
    monkeypatch.setattr(remasterer, "REMASTER_DIR", tmp_path / "final")
    monkeypatch.setattr(remasterer, "SESSION_DIR", tmp_path / "profiles" / "default")
    monkeypatch.setattr(remasterer, "_pipeline_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(remasterer, "_pipeline_status", lambda *_args, **_kwargs: None)
    monkeypatch.delenv("RANKSTEIN_REMASTER_CANDIDATE_LIMIT", raising=False)


@pytest.fixture
def query_studio(monkeypatch):
    class Element:
        def __init__(self, attributes):
            self.attributes = attributes

        async def get_attribute(self, name):
            return self.attributes.get(name)

    class Card:
        def __init__(self, pin_id, text):
            self.pin_id = pin_id
            self.text = text

        async def query_selector(self, selector):
            if selector == "img":
                return Element({"src": f"https://images.test/{self.pin_id}.jpg", "alt": self.text})
            if selector == 'a[href*="/pin/"]':
                return Element({"href": f"/pin/{self.pin_id}/", "title": self.text})
            return None

        async def inner_text(self):
            return self.text

    class Page:
        def __init__(self):
            self.queries = []
            self.mouse = SimpleNamespace(wheel=self.wheel)

        async def wheel(self, *_args):
            return None

        async def goto(self, url, **_kwargs):
            self.queries.append(parse_qs(urlparse(url).query)["q"][0])

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

    async def cards(page):
        if page.queries[-1] == "helado de pistacho":
            return [Card(str(index), "decoracion para el hogar") for index in range(1, 101)]
        return [Card(str(index), "helado de pistacho cremoso") for index in range(1001, 1017)]

    monkeypatch.setattr(remasterer.httpx, "AsyncClient", Client)
    monkeypatch.setattr(remasterer.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(remasterer, "_page_has_pinterest_login_wall", no_wall)
    monkeypatch.setattr(remasterer, "_query_pinterest_pin_cards", cards)
    monkeypatch.setattr(
        remasterer,
        "assess_source_image",
        lambda path: {"accepted": True, "source_hash": f"checked-{Path(path).stem}"},
    )
    studio = remasterer.PinRemasterer(session_name="query-budget-test")
    studio.page = Page()
    return studio


@pytest.mark.unit
def test_later_generated_query_gets_budget_after_ninety_irrelevant_candidates(query_studio):
    sources = asyncio.run(
        query_studio.collect_and_download(
            "helado de pistacho",
            count=15,
            search_queries=["helado de pistacho", "helado pistacho cremoso"],
            core_terms=["helado", "pistacho"],
            min_core_matches=2,
            excluded_pin_ids={"1001"},
        )
    )
    assert query_studio.page.queries == ["helado de pistacho", "helado pistacho cremoso"]
    assert len(sources) == 15
    assert len({source["pin_id"] for source in sources}) == 15
    assert all(source["source"] == "pinterest" for source in sources)
    assert "1001" not in {source["pin_id"] for source in sources}
    diagnostics = query_studio.last_collection_diagnostics
    assert diagnostics["relevance_rejected"] == 90
    assert diagnostics["pins_examined"] == 105
    assert diagnostics["candidate_limit"] == 180
    assert diagnostics["held_sources_skipped"] == 1
    assert diagnostics["blocked_reason"] == ""


@pytest.mark.unit
def test_explicit_total_budget_is_shared_across_generated_queries(query_studio, monkeypatch):
    monkeypatch.setenv("RANKSTEIN_REMASTER_CANDIDATE_LIMIT", "4")
    monkeypatch.setattr(
        remasterer, "assess_source_image", lambda _path: {"accepted": False, "reason": "embedded_text"}
    )
    sources = asyncio.run(
        query_studio.collect_and_download(
            "helado de pistacho",
            count=15,
            search_queries=["helado de pistacho", "helado pistacho cremoso"],
            core_terms=["helado", "pistacho"],
            min_core_matches=2,
        )
    )
    assert sources == []
    assert len(query_studio.page.queries) == 2
    diagnostics = query_studio.last_collection_diagnostics
    assert diagnostics["pins_examined"] == 4
    assert diagnostics["relevance_rejected"] == 2
    assert diagnostics["text_rejected"] == 2
    assert diagnostics["candidate_limit"] == 4
    assert diagnostics["blocked_reason"] == "candidate_limit"


@pytest.mark.unit
@pytest.mark.parametrize("query_count", [1, 6, 8, 1000])
def test_adaptive_candidate_budget_has_fixed_hard_cap(query_count):
    assert remasterer._candidate_limit(query_count=query_count) == min(90 * query_count, 600)
    assert remasterer._candidate_limit(9, query_count=query_count) == 9
    assert remasterer._candidate_limit(10_000, query_count=query_count) == 600


@pytest.mark.unit
@pytest.mark.parametrize("case", ["seven_clean", "duplicate_pin", "native_source"])
def test_incomplete_unique_pinterest_source_set_never_starts_composition(monkeypatch, case):
    sources = [
        {
            "pin_id": str(index),
            "source": "pinterest",
            "raw_path": f"isolated-{index}.jpg",
            "source_quality": {"accepted": True},
        }
        for index in range(15)
    ]
    if case == "seven_clean":
        sources = sources[:7]
    elif case == "duplicate_pin":
        sources[-1] = sources[0]
    else:
        sources[-1]["source"] = "native_fallback"

    studio = SimpleNamespace(last_collection_diagnostics={"candidate_limit": 90, "accepted": 15})

    async def collect(*_args, **_kwargs):
        return sources

    def forbidden(*_args, **_kwargs):
        raise AssertionError("incomplete fifteen-source intake must not create any variants")

    monkeypatch.setattr(remasterer, "PinRemasterer", lambda **_kwargs: studio)
    monkeypatch.setattr(remasterer, "_collect_campaign_sources", collect)
    monkeypatch.setattr(remasterer, "create_viral_visual_pin", forbidden)
    monkeypatch.setattr(remasterer, "create_recipe_card_pin", forbidden)
    monkeypatch.setattr(remasterer, "_generate_native_fallback_sources", forbidden)
    diagnostics = {}
    assets = asyncio.run(
        remasterer.run_remasterer(
            "helado de pistacho",
            "Helado de pistacho cremoso",
            domain_handle="recetadolce",
            recipe_ingredients=["100 g de pistachos", "250 ml de nata"],
            recipe_steps=["Tritura los pistachos.", "Congela la mezcla."],
            source_collection_diagnostics=diagnostics,
        )
    )
    assert assets == []
    assert diagnostics["source_target"] == 15
    assert diagnostics["accepted"] == (7 if case == "seven_clean" else 14)
    assert diagnostics["remaining_sources"] == (8 if case == "seven_clean" else 1)
    assert diagnostics["phase"] == "incomplete"
    assert diagnostics["failure_phase"] == "validating_source_count"
    assert diagnostics["blocked_reason"] == "insufficient_clean_sources"

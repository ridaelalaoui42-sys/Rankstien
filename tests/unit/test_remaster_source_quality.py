from __future__ import annotations

import asyncio
import hashlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from backend.services import remasterer
from rankstein.source_image_quality import SOURCE_QUALITY_POLICY, SOURCE_QUALITY_VERSION


def _assessment(path, *, accepted=True, reason="text_free_or_tiny_ocr_noise"):
    return {
        "accepted": accepted,
        "policy": SOURCE_QUALITY_POLICY,
        "version": SOURCE_QUALITY_VERSION,
        "backend": "mock-local-ocr",
        "reason": reason,
        "word_count": 0 if accepted else 40,
        "source_hash": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
    }


@pytest.fixture
def selected_sources(monkeypatch, tmp_path):
    sources = []
    for index in range(15):
        path = tmp_path / f"source-{index}.jpg"
        path.write_bytes(f"isolated-source-{index}".encode())
        sources.append(
            {
                "pin_id": str(100000000000000000 + index),
                "raw_path": str(path),
                "source": "pinterest",
                # A stale collector's claim must not bypass re-assessment.
                "source_quality": {"accepted": True},
            }
        )

    class FakeCollector:
        def __init__(self, **_kwargs):
            self.last_collection_diagnostics = {}

        async def start(self):
            return None

        async def stop(self):
            return None

        async def collect_and_download(self, *_args, **_kwargs):
            return sources

    monkeypatch.setattr(remasterer, "PinRemasterer", FakeCollector)
    monkeypatch.setattr(remasterer, "_held_campaign_source_pin_ids", lambda *_args, **_kwargs: set())
    monkeypatch.setattr(remasterer, "_pipeline_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(remasterer, "_pipeline_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(remasterer, "REMASTER_DIR", tmp_path)
    return sources


def _run():
    return asyncio.run(
        remasterer.run_remasterer(
            "pastel de zanahoria sin horno",
            "Pastel de zanahoria sin horno",
            domain_handle="recetadolce",
            recipe_ingredients=["200 g de zanahoria", "150 g de queso crema"],
            recipe_steps=["Ralla la zanahoria.", "Enfría la mezcla durante 2 horas."],
            pipeline_run_id="isolated-test-run",
        )
    )


@pytest.mark.unit
@pytest.mark.parametrize("reason", ["embedded_text", "ocr_timeout", "ocr_unavailable"])
def test_one_blocked_selected_source_prevents_every_variant(monkeypatch, selected_sources, reason):
    checks = []

    def assess(path):
        checks.append(path)
        return _assessment(path, accepted=path != selected_sources[0]["raw_path"], reason=reason)

    def forbidden(**_kwargs):
        raise AssertionError("no variants may be composed from a blocked source set")

    monkeypatch.setattr(remasterer, "assess_source_image", assess)
    monkeypatch.setattr(remasterer, "create_viral_visual_pin", forbidden)
    monkeypatch.setattr(remasterer, "create_recipe_card_pin", forbidden)

    assert _run() == []
    assert len(checks) == 15


@pytest.mark.unit
def test_each_generated_pair_preserves_exact_checked_source_evidence(monkeypatch, selected_sources, tmp_path):
    checks = []

    def assess(path):
        checks.append(path)
        return _assessment(path)

    def create(variant, **kwargs):
        path = Path(kwargs["output_dir"]) / f"{kwargs['pair_id']}-{variant}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(variant.encode())
        return {"success": True, "output_path": str(path), "variant": variant, "variant_label": variant}

    monkeypatch.setattr(remasterer, "assess_source_image", assess)
    monkeypatch.setattr(
        remasterer, "create_viral_visual_pin", lambda **kwargs: create("viral_visual", **kwargs)
    )
    monkeypatch.setattr(
        remasterer, "create_recipe_card_pin", lambda **kwargs: create("recipe_card", **kwargs)
    )

    held_image = tmp_path / "pastel-de-zanahoria-sin-horno-source-01-viral-visual.jpg"
    held_image.write_bytes(b"held image must remain unchanged")
    assets = _run()
    assert len(assets) == 30
    assert len(checks) == 15
    assert held_image.read_bytes() == b"held image must remain unchanged"
    assert all(Path(asset["remastered_path"]).parent != tmp_path for asset in assets)
    for index, source in enumerate(selected_sources):
        pair = assets[index * 2 : index * 2 + 2]
        assert {asset["variant"] for asset in pair} == {"viral_visual", "recipe_card"}
        assert all(asset["source_path"] == source["raw_path"] for asset in pair)
        assert all(asset["source_hash"] == source["source_quality"]["source_hash"] for asset in pair)
        assert all(asset["source_quality"]["accepted"] is True for asset in pair)
        assert all(asset["source_quality"]["policy"] == SOURCE_QUALITY_POLICY for asset in pair)


@pytest.mark.unit
def test_collector_skips_text_and_unavailable_sources_then_accepts_clean_photo(monkeypatch, tmp_path):
    class FakeElement:
        def __init__(self, attributes):
            self.attributes = attributes

        async def get_attribute(self, name):
            return self.attributes.get(name)

    class FakeCard:
        def __init__(self, index):
            self.index = index

        async def query_selector(self, selector):
            if selector == "img":
                return FakeElement({"src": f"https://images.test/{self.index}.jpg", "alt": "pastel"})
            if selector == 'a[href*="/pin/"]':
                return FakeElement({"href": f"/pin/{self.index}/", "title": "pastel"})
            return None

        async def inner_text(self):
            return "pastel"

    class FakePage:
        async def goto(self, *_args, **_kwargs):
            return None

    image = BytesIO()
    Image.new("RGB", (800, 1200), "tan").save(image, format="JPEG")

    class FakeClient:
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
        return [FakeCard(index) for index in (1, 2, 3)]

    def assess(path):
        pin_id = Path(path).stem
        return _assessment(
            path,
            accepted=pin_id == "3",
            reason="embedded_text" if pin_id == "1" else "ocr_unavailable",
        )

    monkeypatch.setattr(remasterer, "DOWNLOAD_DIR", tmp_path)
    monkeypatch.setattr(remasterer, "SESSION_DIR", tmp_path / "sessions" / "default")
    monkeypatch.setattr(remasterer, "assess_source_image", assess)
    monkeypatch.setattr(remasterer.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(remasterer.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(remasterer, "_page_has_pinterest_login_wall", no_wall)
    monkeypatch.setattr(remasterer, "_query_pinterest_pin_cards", cards)
    monkeypatch.setattr(remasterer, "score_pin_relevance", lambda *_args, **_kwargs: 10)
    studio = remasterer.PinRemasterer(session_name="isolated-quality-test")
    studio.page = FakePage()

    collected = asyncio.run(studio.collect_and_download("pastel", count=1))

    assert [item["pin_id"] for item in collected] == ["3"]
    assert studio.last_collection_diagnostics["text_rejected"] == 1
    assert studio.last_collection_diagnostics["text_unavailable"] == 1
    assert studio.last_collection_diagnostics["pins_examined"] == 3
    assert collected[0]["source_quality"]["accepted"] is True
    assert collected[0]["source_hash"] == collected[0]["source_quality"]["source_hash"]

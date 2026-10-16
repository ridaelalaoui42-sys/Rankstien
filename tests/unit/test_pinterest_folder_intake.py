"""Folder intake resolves immutable destination metadata before queue writes."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from pinterest_automation import campaign


@pytest.fixture
def intake(tmp_path, monkeypatch):
    from rankstein import domain as domain_module

    domains = [
        SimpleNamespace(
            handle="recetadolce", domain="dulce.example", boards_default={"_default": "Chocolate"}
        ),
        SimpleNamespace(
            handle="recetagenial", domain="salado.example", boards_default={"_default": "Aperitivos"}
        ),
    ]
    root = tmp_path / "data" / "media" / "remaster_final"
    root.mkdir(parents=True)
    jobs = []

    def enqueue(**payload):
        jobs.append(payload)
        return f"job-{len(jobs)}"

    monkeypatch.setattr(domain_module, "get_registry", lambda: SimpleNamespace(all=lambda: domains))
    monkeypatch.setattr(campaign, "REMASTER_DIR", root)
    monkeypatch.setattr(campaign, "get_job_queue", lambda: SimpleNamespace(enqueue_pin_upload=enqueue))
    config = SimpleNamespace(
        accounts={"sweet-a": object(), "sweet-b": object(), "savory": object()},
        boards={},
        default_board="Chocolate",
    )
    monkeypatch.setattr(campaign, "get_config", lambda: config)
    monkeypatch.setenv(
        "PINTEREST_DOMAIN_ACCOUNT_MAP",
        '{"recetadolce":["sweet-a","sweet-b"],"recetagenial":["savory"]}',
    )
    return SimpleNamespace(root=root, jobs=jobs, domains=domains, tmp_path=tmp_path)


def image(path: Path, size=8):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


@pytest.mark.parametrize(
    ("handle", "public_domain", "cohort", "board"),
    [
        ("recetadolce", "dulce.example", {"sweet-a", "sweet-b"}, "Chocolate"),
        ("recetagenial", "salado.example", {"savory"}, "Aperitivos"),
    ],
)
def test_article_folder_supplies_destination_and_preserves_source_variants(
    intake, handle, public_domain, cohort, board
):
    folder = intake.root / handle / "2026-10-15" / "tarta-de-queso"
    paths = [
        image(folder / "tarta-de-queso-source-01-viral-visual.jpg"),
        image(folder / "tarta-de-queso-source-01-recipe-card.jpg"),
        image(folder / "source-02-viral-visual.jpg"),
    ]

    result = campaign.enqueue_folder(folder)

    assert result["success"] and result["jobs_enqueued"] == 3
    assert result["unique_slugs"] == 1 and result["unique_assets"] == 3
    assert {job["image_path"] for job in intake.jobs} == {str(path) for path in paths}
    assert {job["link"] for job in intake.jobs} == {f"https://{public_domain}/tarta-de-queso"}
    for job in intake.jobs:
        assert job["title"] == "Tarta De Queso"
        assert job["extra"]["slug"] == "tarta-de-queso"
        assert job["extra"]["domain_handle"] == handle
        assert job["extra"]["account_handle"] in cohort
        assert job["board_name"] == board
    assert len({job["extra"]["asset_key"] for job in intake.jobs}) == 3


def test_mixed_root_routes_each_file_through_its_configured_domain(intake):
    for handle in ("recetadolce", "recetagenial"):
        image(intake.root / handle / "2026-10-15" / "tarta-de-queso" / "source-01-viral-visual.jpg")

    result = campaign.enqueue_folder()

    assert result["success"] and result["jobs_enqueued"] == 2
    assert result["domains"] == ["recetadolce", "recetagenial"]
    jobs = {job["extra"]["domain_handle"]: job for job in intake.jobs}
    assert jobs["recetadolce"]["link"] == "https://dulce.example/tarta-de-queso"
    assert jobs["recetagenial"]["link"] == "https://salado.example/tarta-de-queso"
    assert jobs["recetagenial"]["extra"]["account_handle"] == "savory"
    assert jobs["recetadolce"]["extra"]["account_handle"] in {"sweet-a", "sweet-b"}


def test_thirty_variant_assets_share_article_url_and_spread_across_domain_accounts(intake):
    folder = intake.root / "recetadolce" / "2026-10-15" / "tarta-de-queso"
    for source in range(1, 16):
        for variant in ("viral-visual", "recipe-card"):
            image(folder / f"tarta-de-queso-source-{source:02d}-{variant}.jpg")

    result = campaign.enqueue_folder(folder)

    assert result["success"] and result["jobs_enqueued"] == 30
    assert {job["link"] for job in intake.jobs} == {"https://dulce.example/tarta-de-queso"}
    assert {job["extra"]["account_handle"] for job in intake.jobs} == {"sweet-a", "sweet-b"}
    assert len({job["extra"]["asset_key"] for job in intake.jobs}) == 30


def test_same_article_asset_across_dates_keeps_largest_without_collapsing_variants(intake):
    older = intake.root / "recetadolce" / "2026-10-14" / "tarta-de-queso"
    newer = intake.root / "recetadolce" / "2026-10-15" / "tarta-de-queso"
    image(older / "source-01-viral-visual.jpg", size=4)
    chosen = image(newer / "source-01-viral-visual.jpg", size=12)
    other = image(newer / "source-01-recipe-card.jpg", size=8)

    result = campaign.enqueue_folder()

    assert result["jobs_enqueued"] == 2 and result["total_images"] == 3
    assert {job["image_path"] for job in intake.jobs} == {str(chosen), str(other)}


def test_explicit_same_domain_article_destination_is_preserved_exactly(intake):
    folder = intake.root / "recetadolce" / "2026-10-15" / "tarta-de-queso"
    image(folder / "source-01-recipe-card.jpg")
    link = "https://www.dulce.example/receta-canonica/?campaign=approved#recipe"

    result = campaign.enqueue_folder(
        folder, domain_handle="recetadolce", domain_url="dulce.example", article_link=link
    )

    assert result["success"] and intake.jobs[0]["link"] == link
    assert intake.jobs[0]["extra"]["domain_handle"] == "recetadolce"


@pytest.mark.parametrize(
    "overrides",
    [
        {"domain_handle": "recetadolce"},
        {"domain_url": "dulce.example"},
        {"article_link": "https://dulce.example/receta"},
    ],
)
def test_explicit_constraint_conflicting_with_later_domain_enqueues_nothing(intake, overrides):
    for handle in ("recetadolce", "recetagenial"):
        image(intake.root / handle / "2026-10-15" / "tarta-de-queso" / "source-01.jpg")

    result = campaign.enqueue_folder(**overrides)

    assert result["success"] is False and result["jobs_enqueued"] == 0
    assert "conflict" in result["error"].lower() and intake.jobs == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"domain_handle": "recetadolce", "domain_url": "salado.example"},
        {"domain_handle": "recetadolce", "article_link": "https://salado.example/receta"},
        {"domain_url": "unconfigured.example"},
        {"article_link": "dulce.example/receta"},
        {"domain_handle": "unknown"},
    ],
)
def test_invalid_explicit_target_fails_before_queue_access(intake, monkeypatch, overrides):
    image(intake.root / "recetadolce" / "2026-10-15" / "tarta-de-queso" / "source-01.jpg")
    monkeypatch.setattr(
        campaign, "get_job_queue", lambda: pytest.fail("Queue accessed before target validation")
    )

    result = campaign.enqueue_folder(**overrides)

    assert result["success"] is False and result["jobs_enqueued"] == 0


@pytest.mark.parametrize(
    "relative",
    [
        "unknown/2026-10-15/tarta-de-queso/source-01.jpg",
        "recetadolce/2026-99-99/tarta-de-queso/source-01.jpg",
        "recetadolce/2026-10-15/not_a_canonical_slug/source-01.jpg",
        "recetadolce/2026-10-15/source-01.jpg",
    ],
)
def test_unrecognized_managed_layout_never_invents_a_destination(intake, relative):
    image(intake.root / relative)

    result = campaign.enqueue_folder(domain_handle="recetadolce")

    assert result["success"] is False and result["jobs_enqueued"] == 0 and intake.jobs == []


def test_ordinary_legacy_folder_preserves_filename_deduplication_and_url_override(intake):
    folder = intake.tmp_path / "legacy"
    image(folder / "tarta-de-queso.jpg", size=4)
    chosen = image(folder / "tarta-de-queso-hero.jpg", size=12)
    image(folder / "helado-de-fresa.png", size=8)

    result = campaign.enqueue_folder(folder, domain_handle="recetadolce", domain_url="dulce.example")

    assert result["success"] and result["jobs_enqueued"] == 2
    assert {job["link"] for job in intake.jobs} == {
        "https://dulce.example/tarta-de-queso",
        "https://dulce.example/helado-de-fresa",
    }
    assert str(chosen) in {job["image_path"] for job in intake.jobs}
    assert all("asset_key" not in job["extra"] for job in intake.jobs)


def test_legacy_folder_requires_explicit_configured_domain(intake):
    folder = intake.tmp_path / "legacy"
    image(folder / "tarta-de-queso.jpg")

    result = campaign.enqueue_folder(folder)

    assert result["success"] is False and result["jobs_enqueued"] == 0 and intake.jobs == []


def test_short_canonical_article_slug_remains_publishable(intake):
    folder = intake.root / "recetadolce" / "2026-10-15" / "flan"
    image(folder / "source-01-viral-visual.jpg")

    result = campaign.enqueue_folder(folder)

    assert result["success"] and result["jobs_enqueued"] == 1
    assert intake.jobs[0]["title"] == "Flan"
    assert intake.jobs[0]["link"] == "https://dulce.example/flan"


def test_legacy_run_layout_can_use_explicit_article_link(intake):
    folder = intake.root / "recetagenial" / "run-123" / "attempt-456"
    image(folder / "tarta-de-queso.jpg")

    result = campaign.enqueue_folder(folder, article_link="https://salado.example/tarta-de-queso")

    assert result["success"] and result["jobs_enqueued"] == 1
    assert intake.jobs[0]["extra"]["domain_handle"] == "recetagenial"
    assert intake.jobs[0]["link"] == "https://salado.example/tarta-de-queso"

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from backend.services import remasterer
from rankstein import remaster_variants
from rankstein.remaster_variants import create_recipe_card_pin, create_viral_visual_pin
from rankstein_mcp_server import _normalise_codex_image


@pytest.fixture
def food_source(tmp_path: Path) -> Path:
    path = tmp_path / "food.jpg"
    image = Image.new("RGB", (900, 1350), (126, 72, 38))
    image.save(path, "JPEG", quality=92)
    return path


@pytest.mark.unit
def test_one_source_creates_exact_domain_aware_pair(food_source: Path, tmp_path: Path) -> None:
    common = {
        "source_path": str(food_source),
        "title": "Tarta de chocolate y almendra",
        "domain_handle": "recetadolce",
        "pair_id": "source-01",
        "output_dir": tmp_path,
    }
    visual = create_viral_visual_pin(**common)
    recipe = create_recipe_card_pin(
        **common,
        ingredients=["200 g de chocolate negro", "100 g de almendra molida", "3 huevos"],
        steps=["Funde el chocolate.", "Mezcla todos los ingredientes.", "Hornea durante 25 minutos."],
        tip_text="Deja enfriar antes de cortar.",
    )

    assert visual["success"] is True
    assert recipe["success"] is True
    assert {visual["variant"], recipe["variant"]} == {"viral_visual", "recipe_card"}
    assert Path(visual["output_path"]).name.endswith("source-01-viral-visual.jpg")
    assert Path(recipe["output_path"]).name.endswith("source-01-recipe-card.jpg")
    with Image.open(visual["output_path"]) as image:
        assert image.size == (1000, 1500)
    with Image.open(recipe["output_path"]) as image:
        assert image.size == (1000, 1500)


@pytest.mark.unit
def test_recipe_card_fails_closed_without_real_recipe_context(food_source: Path, tmp_path: Path) -> None:
    result = create_recipe_card_pin(
        source_path=str(food_source),
        title="Tarta de chocolate",
        ingredients=[],
        steps=[],
        tip_text="",
        domain_handle="recetadolce",
        pair_id="source-01",
        output_dir=tmp_path,
    )

    assert result["success"] is False
    assert "requires real recipe ingredients and steps" in result["error"]


@pytest.mark.unit
def test_recipe_card_rejects_generic_placeholder_context(food_source: Path, tmp_path: Path) -> None:
    result = create_recipe_card_pin(
        source_path=str(food_source),
        title="Tarta de chocolate",
        ingredients=["Ingrediente 1", "ingrediente principal"],
        steps=["Paso 1", "Mezclar y servir."],
        tip_text="",
        domain_handle="recetadolce",
        pair_id="source-01",
        output_dir=tmp_path,
    )

    assert result["success"] is False
    assert "requires real recipe ingredients and steps" in result["error"]


@pytest.mark.unit
def test_recipe_card_keeps_long_steps_complete_without_ellipsis(food_source: Path, tmp_path: Path) -> None:
    long_step = (
        "Incorpora la crema en tres tandas mientras remueves desde el centro hacia los bordes, "
        "mantén el fuego suave y espera a que la mezcla quede lisa antes de retirarla para "
        "conservar el acabado final completo."
    )
    result = create_recipe_card_pin(
        source_path=str(food_source),
        title="Tarta cremosa de turrón para fin de año",
        ingredients=[
            "250 g de turrón blando de almendra",
            "500 ml de nata para montar fría",
            "200 g de queso crema a temperatura ambiente",
        ],
        steps=["Tritura el turrón hasta obtener migas finas.", long_step],
        tip_text=("Sirve la tarta muy fría para mantener su textura. " * 40),
        domain_handle="recetagenial",
        pair_id="source-01",
        output_dir=tmp_path,
    )

    assert result["success"] is True
    assert result["rendered_steps"][1] == long_step
    assert "…" not in " ".join(result["rendered_steps"])
    assert "..." not in " ".join(result["rendered_steps"])
    assert result["tip_rendered"] is False


@pytest.mark.unit
def test_recipe_card_layout_keeps_every_required_line_inside_content_bounds() -> None:
    ingredients = [
        f"{100 + index * 25} g de ingrediente artesanal con una descripción completa y medible"
        for index in range(7)
    ]
    steps = [
        f"Paso completo {index}: mezcla los ingredientes lentamente, incorpora la crema en tres "
        "tandas y cocina hasta obtener una textura uniforme antes de continuar con el siguiente "
        "proceso."
        for index in range(1, 6)
    ]
    canvas = Image.new("RGBA", (1000, 1500), "white")
    draw = ImageDraw.Draw(canvas, "RGBA")

    layout = remaster_variants._recipe_card_layout(
        draw,
        ingredient_items=ingredients,
        step_items=steps,
        tip_text=("Consejo opcional demasiado largo. " * 80),
    )

    assert layout is not None
    assert [item.text for item in layout.ingredient_items] == ingredients
    assert [item.text for item in layout.step_items] == steps
    assert all("…" not in line and "..." not in line for item in layout.step_items for line in item.lines)
    assert all(
        remaster_variants._text_width(draw, line, layout.body_font)
        <= layout.content_right - (layout.content_left + 30)
        for item in layout.ingredient_items
        for line in item.lines
    )
    assert all(
        remaster_variants._text_width(draw, line, layout.body_font)
        <= layout.content_right - (layout.content_left + 57)
        for item in layout.step_items
        for line in item.lines
    )
    assert layout.step_items[-1].y + layout.step_items[-1].height <= layout.content_bottom
    assert layout.tip_y is None


@pytest.mark.unit
@pytest.mark.parametrize("requested", [1, 3, 29, 30, 200])
def test_pair_target_is_fixed_to_fifteen_source_pairs(requested: int) -> None:
    assert remasterer._paired_output_target(requested) == 30


@pytest.mark.unit
def test_pair_report_counts_sources_not_assets(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(remasterer, "CAMPAIGN_REPORT_DIR", tmp_path)
    assets = []
    for source_index, source in ((1, "pinterest"), (2, "native_fallback")):
        for variant in ("viral_visual", "recipe_card"):
            assets.append(
                {
                    "pair_id": f"source-{source_index:02d}",
                    "source": source,
                    "variant": variant,
                    "remastered_path": f"asset-{source_index}-{variant}.jpg",
                }
            )

    report = remasterer.write_article_remaster_report(
        keyword="tarta",
        title="Tarta de prueba",
        slug="tarta-de-prueba",
        domain_handle="recetadolce",
        domain_url="recetadolce.com",
        target_count=4,
        assets=assets,
    )

    assert report["success"] is False
    assert report["generated_count"] == 4
    assert report["target_count"] == 30
    assert report["source_target"] == 15
    assert report["missing_count"] == 26
    assert report["pair_count"] == 2
    assert report["source_counts"] == {"pinterest": 1, "native": 1}
    assert report["variant_contract"]["variants_per_source"] == 2


def _production_assets(tmp_path: Path, source_count: int = 15) -> list[dict]:
    assets = []
    for source_index in range(source_count):
        for variant in ("viral_visual", "recipe_card"):
            path = tmp_path / f"source-{source_index}-{variant}.jpg"
            Image.new("RGB", (10, 15), (126, 72, 38)).save(path)
            assets.append(
                {
                    "pair_id": f"source-{source_index}",
                    "source": "pinterest",
                    "original_pin_id": str(100000000000000000 + source_index),
                    "variant": variant,
                    "remastered_path": str(path),
                }
            )
    return assets


def _enqueue_proof(assets: list[dict]) -> dict:
    return {
        "success": True,
        "images_enqueued": len(assets),
        "jobs_enqueued": len(assets),
        "pipeline_run_id": "dolce-run-1",
        "details": [
            {
                "job_id": f"job-{index}",
                "image": item["remastered_path"],
                "pair_id": item["pair_id"],
                "variant": item["variant"],
                "original_pin_id": item["original_pin_id"],
            }
            for index, item in enumerate(assets)
        ],
    }


@pytest.mark.unit
@pytest.mark.parametrize("source_count", [1, 7, 14, 16])
def test_partial_or_excess_campaign_never_shrinks_target_or_mutates_queue(
    source_count: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assets = _production_assets(tmp_path, source_count)
    monkeypatch.setattr(remasterer, "CAMPAIGN_REPORT_DIR", tmp_path)
    calls = []
    enqueue_result = remasterer.enqueue_validated_production_assets(
        assets,
        target_count=30,
        enqueue_callable=lambda **kwargs: calls.append(kwargs),
    )
    report = remasterer.write_article_remaster_report(
        keyword="tarta",
        title="Tarta de prueba",
        slug="tarta-de-prueba",
        domain_handle="recetadolce",
        domain_url="recetadolce.com",
        target_count=30,
        assets=assets,
        enqueue_result=_enqueue_proof(assets),
        pipeline_run_id="dolce-run-1",
    )

    assert calls == []
    assert enqueue_result["success"] is False
    assert report["success"] is False
    assert report["target_count"] == report["production_validation"]["target_count"] == 30
    assert report["source_target"] == report["source_contract"]["required_pinterest_sources"] == 15
    assert report["missing_count"] == max(0, 30 - len(assets))


@pytest.mark.unit
def test_requested_partial_target_cannot_weaken_full_campaign(tmp_path: Path) -> None:
    assets = _production_assets(tmp_path)
    validation = remasterer.validate_production_asset_set(assets, target_count=28)
    assert validation["success"] is False
    assert validation["target_count"] == 30
    assert "exactly 30" in validation["error"]
    assert remasterer.validate_production_asset_set(assets)["success"] is True


@pytest.mark.unit
@pytest.mark.parametrize("duplicate", ["original_pin_id", "remastered_path"])
def test_production_assets_require_unique_sources_and_asset_files(tmp_path: Path, duplicate: str) -> None:
    assets = _production_assets(tmp_path)
    assets[2][duplicate] = assets[0][duplicate]
    if duplicate == "original_pin_id":
        assets[3][duplicate] = assets[0][duplicate]
    assert remasterer.validate_production_asset_set(assets, target_count=30)["success"] is False


@pytest.mark.unit
@pytest.mark.parametrize(
    "failure", ["missing", "counter", "duplicate_job", "partial_details", "wrong_asset", "wrong_run"]
)
def test_report_requires_thirty_unique_exact_current_run_queue_jobs(
    failure: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assets = _production_assets(tmp_path)
    enqueue = _enqueue_proof(assets)
    if failure == "missing":
        enqueue = None
    elif failure == "counter":
        enqueue["jobs_enqueued"] = 29
    elif failure == "duplicate_job":
        enqueue["details"][-1]["job_id"] = enqueue["details"][0]["job_id"]
    elif failure == "partial_details":
        enqueue["details"].pop()
    elif failure == "wrong_asset":
        enqueue["details"][-1]["image"] = str(tmp_path / "other-run.jpg")
    elif failure == "wrong_run":
        enqueue["pipeline_run_id"] = "another-run"
    monkeypatch.setattr(remasterer, "CAMPAIGN_REPORT_DIR", tmp_path)
    report = remasterer.write_article_remaster_report(
        keyword="tarta",
        title="Tarta de prueba",
        slug="tarta-de-prueba",
        domain_handle="recetadolce",
        domain_url="recetadolce.com",
        target_count=30,
        assets=assets,
        enqueue_result=enqueue,
        pipeline_run_id="dolce-run-1",
    )
    assert report["production_validation"]["success"] is True
    assert report["enqueue_validation"]["success"] is False
    assert report["success"] is False
    assert report["blocked_reason"] == "incomplete_queue_proof"
    assert "queue" in report["remaining_workflow_steps"]


@pytest.mark.unit
def test_complete_campaign_report_preserves_exact_target_and_queue_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assets = _production_assets(tmp_path)
    enqueue = _enqueue_proof(assets)
    calls = []

    def enqueue_assets(**kwargs):
        calls.append(kwargs)
        return enqueue

    queued = remasterer.enqueue_validated_production_assets(
        assets, target_count=30, enqueue_callable=enqueue_assets
    )
    assert queued["success"] is True
    assert len(calls) == 1
    assert calls[0]["limit"] == 30
    assert calls[0]["image_paths"] == [item["remastered_path"] for item in assets]
    monkeypatch.setattr(remasterer, "CAMPAIGN_REPORT_DIR", tmp_path)
    report = remasterer.write_article_remaster_report(
        keyword="tarta",
        title="Tarta de prueba",
        slug="tarta-de-prueba",
        domain_handle="recetadolce",
        domain_url="recetadolce.com",
        target_count=30,
        assets=assets,
        enqueue_result=queued,
        pipeline_run_id="dolce-run-1",
    )
    assert report["success"] is True
    assert report["generated_count"] == 30
    assert report["accepted_source_count"] == report["pair_count"] == 15
    assert report["source_counts"] == {"pinterest": 15, "native": 0}
    assert report["enqueue_validation"]["unique_job_id_count"] == 30
    assert "queue" not in report["remaining_workflow_steps"]


@pytest.mark.unit
def test_mixed_pinterest_and_native_set_is_not_production_enqueue_ready() -> None:
    assets = []
    for source_index in range(1, 16):
        source = "pinterest" if source_index == 1 else "native_fallback"
        original_pin_id = str(100000000000000000 + source_index)
        for variant in ("viral_visual", "recipe_card"):
            assets.append(
                {
                    "pair_id": f"source-{source_index:02d}",
                    "source": source,
                    "original_pin_id": original_pin_id,
                    "variant": variant,
                    "remastered_path": f"asset-{source_index}-{variant}.jpg",
                }
            )

    queue_writes = 0

    def forbidden_enqueue(**kwargs) -> dict:
        nonlocal queue_writes
        del kwargs
        queue_writes += 1
        return {"success": True}

    result = remasterer.enqueue_validated_production_assets(
        assets,
        target_count=30,
        enqueue_callable=forbidden_enqueue,
    )
    validation = result["validation"]

    assert result["success"] is False
    assert queue_writes == 0
    assert validation["pinterest_source_count"] == 1
    assert validation["native_source_count"] == 14
    assert "Pinterest" in validation["error"]


@pytest.mark.unit
def test_article_report_paths_are_domain_run_scoped_and_collision_resistant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(remasterer, "CAMPAIGN_REPORT_DIR", tmp_path)

    first = remasterer.write_article_remaster_report(
        keyword="tarta",
        title="Tarta compartida",
        slug="tarta-compartida",
        domain_handle="recetadolce",
        domain_url="recetadolce.com",
        target_count=2,
        assets=[],
        pipeline_run_id="dolce-run-1",
    )
    second = remasterer.write_article_remaster_report(
        keyword="tarta",
        title="Tarta compartida",
        slug="tarta-compartida",
        domain_handle="recetagenial",
        domain_url="recetagenial.com",
        target_count=2,
        assets=[],
        pipeline_run_id="genial-run-1",
    )

    first_path = Path(first["report_path"])
    second_path = Path(second["report_path"])
    assert first_path != second_path
    assert "recetadolce" in first_path.name
    assert "dolce-run-1" in first_path.name
    assert "recetagenial" in second_path.name
    assert "genial-run-1" in second_path.name
    assert first_path.exists()
    assert second_path.exists()


@pytest.mark.unit
def test_codex_portrait_response_is_normalized_to_landscape(tmp_path: Path) -> None:
    path = tmp_path / "codex.png"
    Image.new("RGB", (1024, 1536), (80, 120, 90)).save(path, "PNG")

    dimensions = _normalise_codex_image(path, "1536x1024")

    assert dimensions == (1536, 1024)
    with Image.open(path) as image:
        assert image.size == (1536, 1024)


@pytest.mark.unit
def test_recipe_card_pin_supports_bright_infographic_and_classic_styles(
    food_source: Path, tmp_path: Path
) -> None:
    common = {
        "source_path": str(food_source),
        "title": "Tarta de queso vasca",
        "domain_handle": "recetagenial",
        "pair_id": "source-01",
        "output_dir": tmp_path,
        "ingredients": ["600 g queso crema", "4 huevos", "200 g azúcar"],
        "steps": ["Bate el queso con azúcar.", "Añade huevos.", "Hornea a 210 °C."],
        "tip_text": "Dejar enfriar a temperatura ambiente.",
    }
    bright = create_recipe_card_pin(**common, card_style="bright_infographic")
    assert bright["success"] is True
    assert bright["variant"] == "recipe_card"
    assert bright["card_style"] == "bright_infographic"
    assert Path(bright["output_path"]).name.endswith("source-01-recipe-card.jpg")
    with Image.open(bright["output_path"]) as img:
        assert img.size == (1000, 1500)

    classic = create_recipe_card_pin(**common, card_style="classic")
    assert classic["success"] is True
    assert classic["variant"] == "recipe_card"
    assert Path(classic["output_path"]).name.endswith("source-01-recipe-card.jpg")
    with Image.open(classic["output_path"]) as img:
        assert img.size == (1000, 1500)

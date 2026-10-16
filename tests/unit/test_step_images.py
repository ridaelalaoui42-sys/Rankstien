from __future__ import annotations

import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from pydantic import SecretStr

import backend.scripts.turbo_articles as turbo
import rankstein_mcp_server as mcp
from backend.scripts.turbo_articles import (
    _embed_step_images_in_content,
    _ensure_recipe_schema,
)
from backend.services.news_scraper import _extract_step_images
from rankstein.domain import Domain


def test_extract_step_images_from_schema():
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Recipe",
          "name": "Paella Valenciana",
          "recipeInstructions": [
            {
              "@type": "HowToStep",
              "text": "Dorar el pollo y el conejo en aceite de oliva.",
              "image": "https://example.com/step1-dorar.jpg"
            },
            {
              "@type": "HowToStep",
              "text": "Añadir las verduras y sofreír.",
              "image": "https://example.com/step2-verduras.jpg"
            }
          ]
        }
        </script>
      </head>
      <body></body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")
    step_images = _extract_step_images(soup, "https://example.com/receta")
    assert len(step_images) == 2
    assert step_images[0]["step_number"] == 1
    assert step_images[0]["image_url"] == "https://example.com/step1-dorar.jpg"
    assert step_images[1]["step_number"] == 2
    assert step_images[1]["image_url"] == "https://example.com/step2-verduras.jpg"


def test_extract_step_images_from_img_patterns():
    html = """
    <html>
      <body>
        <div class="entry-content">
          <p>Comenzamos la preparación:</p>
          <img src="/wp-content/uploads/2026/03/paella-paso-1.jpg" alt="Paso 1: Dorar la carne" />
          <p>Continuamos con el sofrito:</p>
          <img src="https://cdn.example.com/images/paella-paso-2-1200x800.jpg" alt="Paso 2: Sofreír judías" />
        </div>
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")
    step_images = _extract_step_images(soup, "https://example.com/receta-paella")
    assert len(step_images) == 2
    assert step_images[0]["step_number"] == 1
    assert "paella-paso-1.jpg" in step_images[0]["image_url"]
    assert step_images[1]["step_number"] == 2
    assert "paella-paso-2-1200x800.jpg" in step_images[1]["image_url"]


def test_embed_step_images_in_content():
    content = (
        "## Introducción\n\n"
        "Una receta tradicional fantástica.\n\n"
        "## Guía Paso a Paso Detallada\n\n"
        "1. **Preparación de la carne**: Doramos la carne en aceite de oliva bien caliente hasta que coja color.\n\n"
        "2. **Añadir las verduras**: Incorporamos el tomate y las judías verdes y sofreímos despacio.\n\n"
        "3. **Cocción del arroz**: Añadimos el caldo y el arroz repartiéndolo de forma uniforme.\n\n"
        "## El Truco del Chef\n\n"
        "Dejar reposar 5 minutos."
    )
    step_images = [
        {"step_number": 1, "image_url": "https://storage.supabase.co/steps/step-1.jpg"},
        {"step_number": 2, "image_url": "https://storage.supabase.co/steps/step-2.jpg"},
        {"step_number": 3, "image_url": "https://storage.supabase.co/steps/step-3.jpg"},
    ]
    embedded = _embed_step_images_in_content(content, step_images, "Paella Tradicional")

    assert "https://storage.supabase.co/steps/step-1.jpg" in embedded
    assert "https://storage.supabase.co/steps/step-2.jpg" in embedded
    assert "https://storage.supabase.co/steps/step-3.jpg" in embedded
    assert "Paso 1 de la receta Paella Tradicional" in embedded
    assert "Paso 2 de la receta Paella Tradicional" in embedded
    assert "Paso 3 de la receta Paella Tradicional" in embedded

    # Idempotency test: embedding again should not duplicate
    double_embedded = _embed_step_images_in_content(embedded, step_images, "Paella Tradicional")
    assert double_embedded == embedded


def test_ensure_recipe_schema_attaches_step_images():
    domain = Domain(
        handle="recetagenial",
        domain="recetagenial.com",
        display_name="RecetaGenial",
        brand_name_short="RECETAGENIAL",
        niche="recetas caseras españolas",
        language="es",
        root=Path("."),
        keywords_file=Path("keywords.md"),
        sessions_dir=Path("sessions"),
        output_dir=Path("output"),
        branding_dir=Path("branding"),
        pinterest_email="user@example.com",
        pinterest_password=SecretStr("secret"),
        supabase_url="https://supabase.example",
        supabase_service_role_key=SecretStr("service-role"),
        categories=("Arroces", "Carnes"),
        boards_default={"_default": "Aperitivos", "Arroces": "Arroces"},
    )
    article = {
        "title": "Paella Valenciana Auténtica",
        "category": "Arroces",
        "content": "Contenido de receta",
        "recipe_schema": {
            "recipeIngredient": ["400g arroz bomba", "1 conejo troceado", "1 pollo troceado"],
            "recipeInstructions": [
                {"@type": "HowToStep", "name": "Paso 1", "text": "Dorar las carnes con aceite."},
                {"@type": "HowToStep", "name": "Paso 2", "text": "Sofreír las judías y el tomate."},
            ],
        },
        "step_images": [
            {"step_number": 1, "image_url": "https://storage.supabase.co/steps/paella-step-1.jpg"},
            {"step_number": 2, "image_url": "https://storage.supabase.co/steps/paella-step-2.jpg"},
        ],
    }

    schema = _ensure_recipe_schema(
        article,
        keyword="paella valenciana",
        cluster="Arroces",
        domain=domain,
        hero_url="https://storage.supabase.co/heroes/paella.jpg",
    )

    instructions = schema.get("recipeInstructions", [])
    assert len(instructions) == 2
    assert instructions[0]["image"] == "https://storage.supabase.co/steps/paella-step-1.jpg"
    assert instructions[1]["image"] == "https://storage.supabase.co/steps/paella-step-2.jpg"

    # Failed uploads can leave gaps; explicit step numbers must not fall back to array position.
    article["step_images"] = article["step_images"][1:]
    schema = _ensure_recipe_schema(
        article,
        keyword="paella valenciana",
        cluster="Arroces",
        domain=domain,
        hero_url="https://storage.supabase.co/heroes/paella.jpg",
    )
    assert "image" not in schema["recipeInstructions"][0]
    assert schema["recipeInstructions"][1]["image"] == article["step_images"][0]["image_url"]

    article["step_images"] = []
    schema = _ensure_recipe_schema(
        article,
        keyword="paella valenciana",
        cluster="Arroces",
        domain=domain,
        hero_url="https://storage.supabase.co/heroes/paella.jpg",
    )
    assert all("image" not in step for step in schema["recipeInstructions"])


@pytest.mark.asyncio
@pytest.mark.parametrize("handle", ["test", "other"])
@pytest.mark.parametrize("uploads_succeed", [True, False])
async def test_article_worker_forwards_uploaded_steps_through_content_build(
    monkeypatch, tmp_path, handle, uploads_succeed
):
    domain = Domain(
        handle=handle,
        domain=f"{handle}.example",
        display_name=handle,
        niche="recetas caseras",
        language="es",
        root=tmp_path,
        keywords_file=tmp_path / "keywords.md",
        sessions_dir=tmp_path / "sessions",
        output_dir=tmp_path / "output",
        branding_dir=tmp_path / "branding",
        pinterest_email="user@example.com",
        pinterest_password=SecretStr("secret"),
        supabase_url="https://supabase.example",
        supabase_service_role_key=SecretStr("service-role"),
        categories=("Ensaladas",),
    )
    scraped_steps = _extract_step_images(
        BeautifulSoup(
            '<article><img src="/ensalada-paso-1.jpg" alt="Paso 1: Corta el pepino">'
            '<img src="/ensalada-paso-2.jpg" alt="Paso 2: Mezcla las verduras"></article>',
            "html.parser",
        ),
        "https://recipes.example/ensalada",
    )
    uploaded_steps = (
        [
            {**step, "image_url": f"https://storage.example/{handle}/step-{step['step_number']}.jpg"}
            for step in scraped_steps
        ]
        if uploads_succeed
        else []
    )
    article = {
        "title": "Ensalada de pepino y tomate",
        "slug": "ensalada-pepino-tomate",
        "category": "Ensaladas",
        "excerpt": "Ensalada fresca con pepino, tomate y aceite de oliva.",
        "content": (
            "## Paso a paso\n\n"
            "1. Corta el pepino en rodajas y el tomate en dados.\n\n"
            "2. Mezcla las verduras con el aceite de oliva.\n"
        ),
        "recipe_schema": {
            "recipeIngredient": ["1 pepino", "2 tomates", "2 cucharadas de aceite de oliva"],
            "recipeInstructions": [
                {"@type": "HowToStep", "text": "Corta el pepino y los tomates."},
                {"@type": "HowToStep", "text": "Mezcla las verduras con el aceite."},
            ],
        },
        "step_images": scraped_steps,
    }
    captured = {}

    def upload_steps(steps, slug, target_domain):
        assert steps == scraped_steps
        assert slug == article["slug"]
        assert target_domain.handle == handle
        return uploaded_steps

    def publish(**kwargs):
        captured.update(kwargs)
        return {"success": True, "url": f"https://{domain.domain}/{article['slug']}"}

    monkeypatch.setattr(turbo, "_process_and_upload_step_images", upload_steps)
    monkeypatch.setattr(
        turbo,
        "get_hero_image",
        lambda **kwargs: {"success": True, "output_path": "hero.jpg", "source": "scraped"},
    )
    monkeypatch.setattr(
        mcp,
        "upload_image_to_supabase",
        lambda *args: {"success": True, "public_url": f"https://storage.example/{handle}/hero.jpg"},
    )
    monkeypatch.setattr(mcp, "publish_article_to_supabase", publish)
    monkeypatch.setattr(mcp, "create_article_pin", lambda **kwargs: {"success": False, "error": "no pin"})

    status = await turbo._publish_generated_article(
        article, "ensalada de pepino y tomate", "Ensaladas", domain, step_images=scraped_steps
    )

    assert status == "Needs Verification"
    assert captured["domain_handle"] == handle
    assert captured["step_images"] == uploaded_steps
    assert captured["auto_create_pinterest_campaign"] is False
    for step in uploaded_steps:
        assert step["image_url"] in captured["content"]
        assert step["image_url"] in captured["recipe_schema"]
    if not uploads_succeed:
        assert all(
            "image" not in step for step in json.loads(captured["recipe_schema"])["recipeInstructions"]
        )
    assert all(step["image_url"] not in captured["recipe_schema"] for step in scraped_steps)


def test_embed_step_images_in_content_unnumbered_paragraphs():
    content = (
        "## Introducción\n\n"
        "Una receta deliciosa para toda la familia.\n\n"
        "## Guía Paso a Paso Detallada\n\n"
        "Empieza limpiando bien los solomillos y retirando la grasa exterior.\n\n"
        "Calienta una cazuela amplia con aceite de oliva y dora la carne por ambos lados.\n\n"
        "Añade la cebolla picada y el vino blanco, reduciendo a fuego lento.\n\n"
        "## El Truco del Chef\n\n"
        "El reposo de la carne es fundamental antes de servir."
    )
    step_images = [
        {"step_number": 1, "image_url": "https://storage.supabase.co/steps/solomillo-1.jpg"},
        {"step_number": 2, "image_url": "https://storage.supabase.co/steps/solomillo-2.jpg"},
        {"step_number": 3, "image_url": "https://storage.supabase.co/steps/solomillo-3.jpg"},
    ]
    embedded = _embed_step_images_in_content(content, step_images, "Solomillo de cerdo")

    assert "https://storage.supabase.co/steps/solomillo-1.jpg" in embedded
    assert "https://storage.supabase.co/steps/solomillo-2.jpg" in embedded
    assert "https://storage.supabase.co/steps/solomillo-3.jpg" in embedded
    assert "Paso 1 de la receta Solomillo de cerdo" in embedded
    assert "Paso 2 de la receta Solomillo de cerdo" in embedded
    assert "Paso 3 de la receta Solomillo de cerdo" in embedded


def test_extract_step_images_builder_and_resilient_prep():
    html = """
    <html>
      <body>
        <div class="post-content">
          <p>Teaser related article</p>
        </div>
        <div class="et_builder_inner_content">
          <h2>Cómo hacer y preparar la tarta casera</h2>
          <p>Primer paso de elaboración:</p>
          <img data-lazy-src="https://example.com/wp-content/uploads/tarta-horno.jpg" alt="Tarta en el horno" />
          <p>Segundo paso:</p>
          <img data-src="https://example.com/wp-content/uploads/tarta-terminada.jpg" alt="Resultado de la tarta" />
        </div>
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")
    steps = _extract_step_images(soup, "https://example.com/receta-tarta")
    assert len(steps) == 2
    assert steps[0]["step_number"] == 1
    assert "tarta-horno.jpg" in steps[0]["image_url"]
    assert steps[1]["step_number"] == 2
    assert "tarta-terminada.jpg" in steps[1]["image_url"]

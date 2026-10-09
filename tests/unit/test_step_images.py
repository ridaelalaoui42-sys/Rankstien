from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup
from pydantic import SecretStr

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

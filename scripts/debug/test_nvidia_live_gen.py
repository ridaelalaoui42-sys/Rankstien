import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from backend.services.nvidia_client import generate_article_with_nvidia_nemotron

prompt = """
Escribe un artículo completo en formato JSON para la receta 'Tarta de Queso La Viña'.
El JSON DEBE incluir exactamente estas claves:
{
  "title": "Tarta de Queso La Viña Auténtica y Cremosa",
  "slug": "tarta-de-queso-la-vina-autentica",
  "meta_description": "Aprende a preparar la famosa tarta de queso La Viña...",
  "excerpt": "Descubre el secreto de la mejor tarta de queso al horno...",
  "category": "Postres",
  "content": "## Introducción\\n\\nLa tarta de queso La Viña es un ícono...",
  "recipe_schema": {
    "@context": "https://schema.org/",
    "@type": "Recipe",
    "name": "Tarta de Queso La Viña",
    "recipeIngredient": ["1 kg de queso crema", "7 huevos", "400 g de azúcar", "500 ml de nata montada", "1 cucharada de harina"],
    "recipeInstructions": [{"@type": "HowToStep", "text": "Precalentar el horno a 210°C."}, {"@type": "HowToStep", "text": "Mezclar todos los ingredientes con varilla."}],
    "prepTime": "PT15M",
    "cookTime": "PT50M",
    "totalTime": "PT65M",
    "recipeYield": "8 porciones"
  },
  "hero_image_prompt": "A close up cinematic shot of a glossy baked San Sebastian cheesecake on parchment paper",
  "pinterest_pin_prompt": "Vertical pin of a creamy slice of La Vina cheesecake",
  "image_negative_prompt": "blurry, low quality",
  "image_alt": "Tarta de queso La Viña horneada cremosa"
}
Responde UNICAMENTE con el objeto JSON.
"""

print("=== TESTING NVIDIA NEMOTRON LIVE GENERATION ===")
article = generate_article_with_nvidia_nemotron(prompt)
if article:
    print("\nSUCCESS!")
    print(f"Title: {article.get('title')}")
    print(f"Slug: {article.get('slug')}")
    print(f"Recipe Ingredients Count: {len(article.get('recipe_schema', {}).get('recipeIngredient', []))}")
else:
    print("\nFAILED")

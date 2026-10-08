import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from backend.services.nvidia_client import generate_article_with_nvidia_nemotron

def test():
    prompt = """Return ONLY a valid JSON object:
{
  "title": "Tarta de Manzana Casera",
  "slug": "tarta-de-manzana-casera",
  "content": "## Ingredientes\\n\\n- 3 manzanas\\n- 200g harina\\n- 100g azúcar\\n\\n[HERO_IMAGE]\\n\\nReceta clásica y fácil.",
  "excerpt": "Tarta de manzana jugosa y crujiente.",
  "category": "Postres",
  "prep_time": 20,
  "cook_time": 45,
  "recipe_schema": {"@type": "Recipe", "name": "Tarta de Manzana", "recipeIngredient": ["3 manzanas", "200g harina"]}
}
OUTPUT ONLY THE JSON.
"""
    result = generate_article_with_nvidia_nemotron(prompt, timeout=120)
    if result:
        print("[SUCCESS] Title:", result.get("title"))
        print("[SUCCESS] Category:", result.get("category"))
        print("[SUCCESS] Ingredients:", result.get("recipe_schema", {}).get("recipeIngredient"))
    else:
        print("[FAILED] Could not get valid article JSON")

if __name__ == "__main__":
    test()

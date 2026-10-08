import os
import sys
import json
import time
import openai

# Ensure project imports work
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from rankstein.domain import get_registry
from backend.scripts.turbo_articles import (
    _build_generation_prompt,
    _parse_llm_json_response,
)

def test_nemotron_article_generation():
    domain_reg = get_registry()
    domain = domain_reg.get("recetadolce")
    keyword = "bizcocho de limon esponjoso"

    print("=" * 60)
    print(f"TESTING FULL ARTICLE GENERATION VIA NVIDIA NEMOTRON 3.5 LIGHTNING")
    print(f"Target Keyword: '{keyword}' | Domain: {domain.display_name}")
    print("=" * 60)

    client = openai.OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key="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"
    )

    source_material = """
    Fuente 1: Bizcocho de limón esponjoso tradicional. Ingredientes: 250g harina de trigo, 200g azúcar, 3 huevos, 120ml aceite de oliva suave, 120ml yogur natural, ralladura y zumo de 1 limón, 1 sobre de levadura química (16g), pizca de sal. Hornear a 180°C durante 40 minutos.
    Fuente 2: Secreto del bizcocho de limón súper esponjoso. Batir bien los huevos con el azúcar hasta blanquear y montar ligeramente. Tamizar la harina junto con la levadura.
    """

    prompt = _build_generation_prompt(keyword, domain, source_material=source_material)

    start_time = time.time()
    try:
        completion = client.chat.completions.create(
            model="nvidia/nemotron-3.5-lightning-30b-a3b",
            messages=[
                {"role": "system", "content": "You are RankStein's recipe generator. Return ONLY valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=8192,
            extra_body={"chat_template_kwargs": {"enable_thinking": True}, "reasoning_budget": 4096}
        )
        duration = time.time() - start_time
        raw_output = completion.choices[0].message.content

        print(f"\n[API Success] Responded in {duration:.2f} seconds.")
        print(f"Raw output length: {len(raw_output)} characters.")

        article = _parse_llm_json_response(raw_output)

        if not article:
            print("\n❌ FAILED: Response could not be parsed into valid article JSON.")
            print("Preview of raw response:\n", raw_output[:1000])
            return False

        print("\n✅ SUCCESS: Parsed valid article JSON!")
        print("-" * 50)
        print(f"Title:        {article.get('title')}")
        print(f"Slug:         {article.get('slug')}")
        print(f"Category:     {article.get('category')}")
        print(f"Excerpt:      {article.get('excerpt')}")
        print(f"Content Length: {len(article.get('content', ''))} characters")
        print(f"Prep/Cook:    {article.get('prep_time')}m / {article.get('cook_time')}m")
        print(f"Hero Prompt:  {article.get('hero_image_prompt')[:100]}...")
        print(f"Pin Prompt:   {article.get('pinterest_pin_prompt')[:100]}...")
        
        recipe_schema = article.get("recipe_schema", {})
        ingredients = recipe_schema.get("recipeIngredient", [])
        instructions = recipe_schema.get("recipeInstructions", [])

        print(f"Schema Ingredients ({len(ingredients)}):", ingredients[:3])
        print(f"Schema Instructions ({len(instructions)}):", [i.get('text', '')[:40] for i in instructions[:2]])
        print("-" * 50)

        # Quality assertions
        assert len(article.get("content", "")) > 1000, "Content too short"
        assert len(ingredients) > 0, "Ingredients empty"
        assert len(instructions) > 0, "Instructions empty"
        print("✅ ALL QUALITY GATES PASSED PERFECTLY!")
        return True

    except Exception as exc:
        print("\n❌ API EXCEPTION:", exc)
        return False

if __name__ == "__main__":
    test_nemotron_article_generation()

import os
import sys
import json
import time
import openai

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from rankstein.domain import get_registry
from backend.scripts.turbo_articles import (
    _build_generation_prompt,
    _parse_llm_json_response,
)

def verify_nemotron():
    domain_reg = get_registry()
    domain = domain_reg.get("recetadolce")
    keyword = "bizcocho de limon esponjoso"

    client = openai.OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key="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"
    )

    prompt = _build_generation_prompt(
        keyword,
        domain,
        source_material="Bizcocho de limón suave. Ingredientes: 250g harina, 200g azúcar, 3 huevos, 120ml yogur, 120ml aceite, 1 sobre levadura, ralladura y zumo de 1 limón."
    )

    print(f"Calling NVIDIA Nemotron 3.5 for keyword '{keyword}'...")
    start_t = time.time()

    completion = client.chat.completions.create(
        model="nvidia/nemotron-3.5-lightning-30b-a3b",
        messages=[
            {"role": "system", "content": "You are RankStein's recipe generator. Return ONLY a valid JSON object matching the requested schema."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.6,
        max_tokens=8192,
        extra_body={"chat_template_kwargs": {"enable_thinking": True}, "reasoning_budget": 2048},
        stream=True
    )

    chunks = []
    for chunk in completion:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content is not None:
            chunks.append(delta.content)

    elapsed = time.time() - start_t
    raw_text = "".join(chunks)
    print(f"Response received in {elapsed:.2f}s! Total content length: {len(raw_text)} chars")

    article = _parse_llm_json_response(raw_text)

    if article:
        print("[SUCCESS] Parsed full RankStein article JSON!")
        print("Title:", article.get("title"))
        print("Slug:", article.get("slug"))
        print("Content length:", len(article.get("content", "")))
        print("Prep/Cook time:", article.get("prep_time"), "/", article.get("cook_time"))
        print("Hero image prompt:", article.get("hero_image_prompt"))
        print("Pinterest pin prompt:", article.get("pinterest_pin_prompt"))
        schema = article.get("recipe_schema", {})
        print("Recipe Schema Ingredients:", schema.get("recipeIngredient"))
        print("Recipe Schema Instructions:", [step.get("text") for step in schema.get("recipeInstructions", [])])
        return True
    else:
        print("[FAIL] Could not parse JSON. First 500 chars:\n", raw_text[:500])
        return False

if __name__ == "__main__":
    verify_nemotron()

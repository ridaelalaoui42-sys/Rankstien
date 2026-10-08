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

def test_streaming_article():
    domain_reg = get_registry()
    domain = domain_reg.get("recetadolce")
    keyword = "bizcocho de limon esponjoso"

    client = openai.OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key="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"
    )

    prompt = _build_generation_prompt(keyword, domain, source_material="Bizcocho de limón con harina, huevos, limón, azúcar, yogur y levadura.")

    print(f"Connecting to NVIDIA Nemotron for '{keyword}'...")
    start_t = time.time()
    
    completion = client.chat.completions.create(
        model="nvidia/nemotron-3.5-lightning-30b-a3b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=4096,
        extra_body={"chat_template_kwargs": {"enable_thinking": True}, "reasoning_budget": 1024},
        stream=True
    )

    full_response = []
    reasoning_tokens = 0
    content_tokens = 0

    for chunk in completion:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning:
            reasoning_tokens += len(reasoning)
        if delta.content is not None:
            full_response.append(delta.content)
            content_tokens += len(delta.content)

    elapsed = time.time() - start_t
    raw_json = "".join(full_response)
    print(f"Finished in {elapsed:.2f}s! Reasoning bytes: {reasoning_tokens}, Content bytes: {content_tokens}")

    article = _parse_llm_json_response(raw_json)
    if article:
        print("✅ VALID ARTICLE PARSED!")
        print("Title:", article.get("title"))
        print("Content len:", len(article.get("content", "")))
        print("Ingredients:", article.get("recipe_schema", {}).get("recipeIngredient"))
        return True
    else:
        print("❌ Could not parse JSON. Preview:\n", raw_json[:500])
        return False

if __name__ == "__main__":
    test_streaming_article()

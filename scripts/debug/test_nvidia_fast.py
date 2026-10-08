import time
import json
import openai

client = openai.OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key="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"
)

prompt = """You are a Spanish recipe writer. Return ONLY a valid JSON object:
{
  "title": "Bizcocho de Limón Esponjoso",
  "slug": "bizcocho-de-limon-esponjoso",
  "content": "## Ingredientes\\n\\n- 250g harina\\n- 3 huevos\\n- 120ml yogur\\n\\n[HERO_IMAGE]\\n\\nUn bizcocho de limón suave y clásico.",
  "excerpt": "Receta fácil de bizcocho de limón súper esponjoso.",
  "category": "Postres",
  "recipe_schema": {
    "@type": "Recipe",
    "name": "Bizcocho de Limón Esponjoso",
    "recipeIngredient": ["250g harina", "3 huevos", "120ml yogur"],
    "recipeInstructions": [{"@type": "HowToStep", "text": "Mezclar y hornear."}]
  }
}
OUTPUT ONLY THE JSON OBJECT.
"""

print("Testing NVIDIA Nemotron 3.5 Lightning (fast)...")
t0 = time.time()
res = client.chat.completions.create(
    model="nvidia/nemotron-3.5-lightning-30b-a3b",
    messages=[{"role": "user", "content": prompt}],
    temperature=0.6,
    max_tokens=1500,
    extra_body={"chat_template_kwargs": {"enable_thinking": True}, "reasoning_budget": 512}
)
dt = time.time() - t0
content = res.choices[0].message.content
print(f"DONE in {dt:.2f}s! Total chars: {len(content)}")
print("Response preview:\n", content[:400])

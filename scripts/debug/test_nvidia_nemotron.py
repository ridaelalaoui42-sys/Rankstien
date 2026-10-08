import os
import sys
import json
import openai

client = openai.OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key="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"
)

prompt = """You are an expert Spanish recipe content writer. Return ONLY a valid JSON object:
{
  "title": "Tarta de Queso Vasca Cremosa",
  "slug": "tarta-de-queso-vasca-cremosa",
  "content": "## Ingredientes\\n\\n- 600g queso crema\\n- 4 huevos\\n- 200ml nata\\n- 150g azúcar\\n\\n## Pasos\\n\\n1. Mezclar todo.\\n2. Hornear a 210C por 40 min.\\n\\n[HERO_IMAGE]\\n\\nEn mi cocina este postre siempre triunfa.",
  "excerpt": "Receta fácil y cremosa de tarta de queso vasca tradicional.",
  "category": "Postres",
  "keywords": ["tarta de queso", "tarta vasca", "postres faciles"],
  "difficulty": "Facil",
  "prep_time": 15,
  "cook_time": 40,
  "image_alt": "Tarta de queso vasca dorada por fuera y cremosa por dentro",
  "hero_image_prompt": "Golden Basque burnt cheesecake on a rustic wooden table",
  "pinterest_pin_prompt": "Vertical 2:3 photo of Basque cheesecake slice showing creamy texture",
  "image_negative_prompt": "text, watermark, logo, blurry",
  "chef_tip": "Deja enfriar a temperatura ambiente antes de desmoldar.",
  "recipe_schema": {
    "@type": "Recipe",
    "name": "Tarta de Queso Vasca Cremosa",
    "recipeIngredient": ["600g queso crema", "4 huevos", "200ml nata", "150g azúcar"],
    "recipeInstructions": [{"@type": "HowToStep", "text": "Mezclar ingredientes y hornear."}]
  },
  "faq_schema": [{"question": "¿Se puede congelar?", "answer": "Sí, en porciones."}]
}
OUTPUT ONLY THE JSON OBJECT. No preamble.
"""

try:
    print("Sending request to NVIDIA Nemotron 3.5 Lightning...")
    completion = client.chat.completions.create(
        model="nvidia/nemotron-3.5-lightning-30b-a3b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=4096,
        extra_body={"chat_template_kwargs": {"enable_thinking": True}, "reasoning_budget": 2048}
    )
    content = completion.choices[0].message.content
    print(f"Received {len(content)} characters!")
    print("First 300 chars:")
    print(content[:300])
except Exception as exc:
    print("NVIDIA API Error:", exc)

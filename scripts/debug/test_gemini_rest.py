import os, requests, json, sys
from pathlib import Path

sys.path.insert(0, ".")
from rankstein.domain import get_registry
from backend.scripts.turbo_articles import _build_generation_prompt, _parse_llm_json_response

api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}'

reg = get_registry()
domain = reg.get('recetadolce')
prompt = _build_generation_prompt('croquetas caseras de puchero', domain)

payload = {
    'system_instruction': {'parts': [{'text': 'You are a professional recipe article generator for RankStein. Output ONLY valid, complete JSON matching the requested schema.'}]},
    'contents': [{'parts': [{'text': prompt}]}],
    'generationConfig': {'responseMimeType': 'application/json', 'maxOutputTokens': 8192}
}

print("Sending request to Gemini 2.5 Flash REST API...")
resp = requests.post(url, json=payload, timeout=120)
print("STATUS CODE:", resp.status_code)

if resp.status_code == 200:
    data = resp.json()
    text = data['candidates'][0]['content']['parts'][0]['text']
    print("RESPONSE LENGTH:", len(text))
    print("FIRST 200 CHARS:\n", text[:200])
    print("LAST 200 CHARS:\n", text[-200:])
    article = _parse_llm_json_response(text)
    if article:
        print("PARSE SUCCESS! Article Title:", article.get("title"))
        print("Article Content Length:", len(article.get("content", "")))
    else:
        print("PARSE FAILED!")
        # Print why parsing failed
        try:
            d = json.loads(text)
            print("json.loads worked! Missing required keys:", set({"title", "slug", "content", "excerpt", "category", "recipe_schema"}) - set(d.keys()))
        except Exception as e:
            print("json.loads error:", e)
else:
    print("ERROR BODY:", resp.text[:500])

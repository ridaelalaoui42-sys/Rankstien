import os, requests, json, sys

try:
    import primp
except ImportError:
    primp = None

api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
print("=== AVAILABLE GEMINI REST API MODELS ===")
url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"

if primp:
    client = primp.Client(impersonate="random", timeout=15)
    resp = client.get(url)
else:
    resp = requests.get(url, timeout=15)

if resp.status_code == 200:
    models = resp.json().get("models", [])
    print(f"\nTotal models available: {len(models)}\n")
    for m in models:
        name = m.get("name", "").replace("models/", "")
        methods = m.get("supportedGenerationMethods", [])
        if "generateContent" in methods:
            desc = m.get("description", "")
            print(f"• {name:35} | {desc[:60]}")
else:
    print("Error listing Gemini models:", resp.status_code, resp.text[:300])

print("\n=== HERMES / OPENROUTER FREE MODELS ===")
openrouter_url = "https://openrouter.ai/api/v1/models"
try:
    if primp:
        r = primp.Client(impersonate="random", timeout=15).get(openrouter_url)
    else:
        r = requests.get(openrouter_url, timeout=15)
    if r.status_code == 200:
        data = r.json().get("data", [])
        free_models = [m for m in data if m.get("id", "").endswith(":free") or float(m.get("pricing", {}).get("prompt", "1") or "1") == 0]
        print(f"\nFound {len(free_models)} completely free OpenRouter models:")
        for fm in free_models[:15]:
            print(f"• {fm.get('id'):40} | context: {fm.get('context_length')}")
except Exception as e:
    print("Error listing OpenRouter free models:", e)

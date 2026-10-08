import os, json, sys

try:
    import primp
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "primp"], check=True)
    import primp

api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"

payload = {
    "system_instruction": {"parts": [{"text": "You are a JSON generator. Return ONLY valid JSON."}]},
    "contents": [{"parts": [{"text": "Say hello in JSON format with key message"}]}],
    "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 100}
}

client = primp.Client(impersonate="chrome_131", timeout=30)
r = client.post(url, json=payload)
print("PRIMP STATUS:", r.status_code)
print("PRIMP JSON:", r.json())

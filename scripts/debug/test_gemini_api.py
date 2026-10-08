import os, requests
from dotenv import load_dotenv
load_dotenv()

key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
print("Key length:", len(key) if key else 0)

url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}"
resp = requests.post(
    url,
    json={
        "contents": [{"parts": [{"text": "Generate a short JSON object with keys title and status."}]}],
        "generationConfig": {"responseMimeType": "application/json"}
    }
)

print("Status:", resp.status_code)
if resp.status_code == 200:
    print("Response:", resp.json()["candidates"][0]["content"]["parts"][0]["text"])
else:
    print("Error:", resp.text[:300])

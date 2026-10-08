import sys
sys.path.insert(0, ".")
import requests
from bs4 import BeautifulSoup
from rankstein.domain import get_registry
from supabase import create_client

reg = get_registry()
for handle in ["recetadolce", "recetagenial"]:
    dom = reg.get(handle)
    client = create_client(dom.supabase_url, dom.supabase_service_role_key.get_secret_value())
    res = client.from_("posts").select("slug, title, hero_image, featured_image").eq("is_published", True).limit(1).execute()
    if res.data:
        p = res.data[0]
        slug = p["slug"]
        url = f"https://{dom.domain}/{slug}"
        print(f"Testing {handle} article: {url}")
        r = requests.get(url, timeout=15)
        print(f"  Status: {r.status_code}")
        soup = BeautifulSoup(r.text, "html.parser")
        og = soup.find("meta", property="og:image")
        print(f"  og:image: {og.get('content') if og else 'None'}")
        imgs = [img.get("src") for img in soup.find_all("img") if img.get("src")]
        for s in imgs[:4]:
            full = s if s.startswith("http") else f"https://{dom.domain}{s}"
            resp = requests.get(full, timeout=10)
            print(f"    -> {full[:75]}... HTTP {resp.status_code} ({len(resp.content)} bytes)")

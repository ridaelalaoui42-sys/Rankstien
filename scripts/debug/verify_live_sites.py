import requests
from bs4 import BeautifulSoup

for domain in ["https://recetadolce.com", "https://recetagenial.com"]:
    print("=" * 45)
    print(f"Testing live site: {domain}")
    print("=" * 45)
    try:
        r = requests.get(domain, timeout=15)
        print(f"Homepage status: {r.status_code}")
        soup = BeautifulSoup(r.text, "html.parser")
        imgs = soup.find_all("img")
        print(f"Found {len(imgs)} <img> tags")
        
        # Check if any img has /_next/image
        next_imgs = [img.get("src") for img in imgs if img.get("src") and "_next/image" in img.get("src")]
        print(f"Number of /_next/image URLs (should be 0): {len(next_imgs)}")
        
        # Test 5 sample images
        tested = 0
        for img in imgs:
            src = img.get("src")
            if not src:
                continue
            full_src = src if src.startswith("http") else domain + src
            ir = requests.get(full_src, timeout=10)
            print(f"  [img {tested+1}] {full_src[:75]}... -> HTTP {ir.status_code} ({len(ir.content)} bytes)")
            tested += 1
            if tested >= 5:
                break
                
        # Find first article link to test slug page
        links = [a.get("href") for a in soup.find_all("a") if a.get("href") and not a.get("href").startswith(("/admin", "/about", "/contact", "/privacy", "/terms", "/categoria", "/cookies", "#", "http"))]
        if links:
            slug_url = domain + (links[0] if links[0].startswith("/") else "/" + links[0])
            print(f"Testing sample recipe page: {slug_url}")
            sr = requests.get(slug_url, timeout=15)
            print(f"  Recipe page status: {sr.status_code}")
            ssoup = BeautifulSoup(sr.text, "html.parser")
            og_img = ssoup.find("meta", property="og:image")
            print(f"  og:image content: {og_img.get('content') if og_img else 'None'}")
            recipe_imgs = ssoup.find_all("img")
            print(f"  Recipe page img tags count: {len(recipe_imgs)}")
            for r_img in recipe_imgs[:3]:
                r_src = r_img.get("src")
                if r_src:
                    full_r_src = r_src if r_src.startswith("http") else domain + r_src
                    r_res = requests.get(full_r_src, timeout=10)
                    print(f"    -> {full_r_src[:75]}... HTTP {r_res.status_code}")
    except Exception as e:
        print(f"Error testing {domain}: {e}")

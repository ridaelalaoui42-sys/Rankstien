"""Fix internal links with /recetas/ slug in Supabase posts for RecetaDolce and RecetaGenial."""

import os
import re
from dotenv import load_dotenv
from supabase import create_client

load_dotenv(override=True)

url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if not url or not key:
    raise RuntimeError("Missing Supabase URL or SERVICE_ROLE_KEY")

supabase = create_client(url, key)

print("Fetching posts from Supabase...")
res = supabase.table("posts").select("id, slug, content").execute()
posts = res.data or []
print(f"Total posts checked: {len(posts)}")

updated_count = 0

for post in posts:
    content = post.get("content") or ""
    if "/recetas/" not in content:
        continue

    # Only replace internal links pointing to /recetas/<slug>
    # Do NOT replace external URLs (like https://www.hogarmania.com/cocina/recetas/...)
    orig = content

    # 1. Full domain internal links: https://recetadolce.com/recetas/slug -> https://recetadolce.com/slug
    content = re.sub(
        r'(https?://(?:www\.)?recetadolce\.com)/recetas/([a-zA-Z0-9_-]+)',
        r'\1/\2',
        content,
    )
    # 2. Full domain internal links for recetagenial: https://recetagenial.com/recetas/slug -> https://recetagenial.com/slug
    content = re.sub(
        r'(https?://(?:www\.)?recetagenial\.com)/recetas/([a-zA-Z0-9_-]+)',
        r'\1/\2',
        content,
    )
    # 3. Markdown relative links: [Anchor](/recetas/slug) -> [Anchor](/slug)
    content = re.sub(r'\]\(/recetas/([a-zA-Z0-9_-]+)\)', r'](/\1)', content)

    # 4. HTML href relative links: href="/recetas/slug" -> href="/slug"
    content = re.sub(r'href=["\']/recetas/([^"\']+)["\']', r'href="/\1"', content)

    if content != orig:
        supabase.table("posts").update({"content": content}).eq("id", post["id"]).execute()
        updated_count += 1
        print(f"Fixed post [{post['slug']}]")

print(f"\nDone! Successfully updated {updated_count} posts in Supabase.")

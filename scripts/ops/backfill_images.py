"""
Backfill and synchronize hero_image and featured_image columns across both
Receta Dolce and Receta Genial Supabase databases.
"""

import sys
from pathlib import Path

# Add project root to sys.path
root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(root))

from rankstein.domain_registry import get_registry
from supabase import create_client


def is_valid_image(url: str | None) -> bool:
    if not url or not isinstance(url, str):
        return False
    val = url.strip()
    if not val or val == "PLACEHOLDER" or val.lower() in ("null", "undefined"):
        return False
    return (
        val.startswith("/")
        or val.startswith("data:image/")
        or val.startswith("http://")
        or val.startswith("https://")
    )


def backfill_domain(domain_handle: str):
    registry = get_registry()
    domain = registry.get(domain_handle)
    url = domain.supabase_url
    key = domain.supabase_service_role_key.get_secret_value()
    if not url or not key:
        print(f"[{domain_handle}] Missing Supabase URL or key, skipping")
        return

    client = create_client(url, key)
    print(f"[{domain_handle}] Fetching posts from {url}...")

    # Fetch posts in batches of 100
    offset = 0
    batch_size = 100
    total_scanned = 0
    total_updated = 0

    while True:
        res = (
            client.from_("posts")
            .select("id, slug, hero_image, featured_image, recipe_schema")
            .range(offset, offset + batch_size - 1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            break

        total_scanned += len(rows)
        for row in rows:
            post_id = row.get("id")
            hero = row.get("hero_image")
            featured = row.get("featured_image")
            schema = row.get("recipe_schema")

            target_image = None
            if is_valid_image(hero):
                target_image = hero.strip()
            elif is_valid_image(featured):
                target_image = featured.strip()
            elif schema and isinstance(schema, dict) and is_valid_image(schema.get("image")):
                target_image = schema.get("image").strip()
            elif schema and isinstance(schema, list) and len(schema) > 0 and is_valid_image(schema[0]):
                target_image = schema[0].strip()

            if not target_image:
                continue

            updates = {}
            if not is_valid_image(hero) or hero != target_image:
                updates["hero_image"] = target_image
            if not is_valid_image(featured) or featured != target_image:
                updates["featured_image"] = target_image

            if updates:
                try:
                    client.from_("posts").update(updates).eq("id", post_id).execute()
                    total_updated += 1
                except Exception as exc:
                    print(f"[{domain_handle}] Error updating post {row.get('slug')}: {exc}")

        if len(rows) < batch_size:
            break
        offset += batch_size

    print(
        f"[{domain_handle}] Done: scanned {total_scanned} posts, updated {total_updated} posts with synced images."
    )


def main():
    for handle in ["recetadolce", "recetagenial"]:
        try:
            backfill_domain(handle)
        except Exception as exc:
            print(f"Error backfilling {handle}: {exc}")


if __name__ == "__main__":
    main()

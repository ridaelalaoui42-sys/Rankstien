"""Fix the last remaining pollinations references in merluza post."""
import os, json, re, requests, sys
from dotenv import load_dotenv

load_dotenv()

url = "https://hokcljsrrnjxzgdhjice.supabase.co"
key = os.environ["RECETAGENIAL_SUPABASE_KEY"]
slug = "merluza-en-salsa-verde-con-almejas-y-esparragos"

headers = {
    "apikey": key,
    "Authorization": f"Bearer {key}",
    "Content-Type": "application/json",
}

# 1. Fetch the post
r = requests.get(
    f"{url}/rest/v1/posts?slug=eq.{slug}&select=id,slug,featured_image,content,recipe_schema",
    headers=headers,
)
r.raise_for_status()
data = r.json()
if not data:
    print("Post not found!")
    sys.exit(1)

post = data[0]
post_id = post["id"]
clean_image = post["featured_image"]
print(f"Post ID: {post_id}")
print(f"Clean featured_image: {clean_image}")

# 2. Fix content - replace pollinations <img> tags
content = post.get("content", "")
poll_pattern = r'<img[^>]*src=["\']([^"\']*pollinations[^"\']*)["\'][^>]*/?\s*>'
poll_matches = re.findall(poll_pattern, content)
print(f"\nPollinations <img> tags found in content: {len(poll_matches)}")
for m in poll_matches:
    print(f"  -> {m[:120]}")

# Replace pollinations <img> tags with clean image
new_content = re.sub(
    poll_pattern,
    f'<img src="{clean_image}" alt="Merluza en salsa verde con almejas y espárragos" loading="lazy" />',
    content,
)
content_changed = new_content != content

# 3. Fix recipe_schema.image
schema = post.get("recipe_schema")
schema_changed = False
if schema:
    if isinstance(schema, str):
        schema = json.loads(schema)
    old_img = schema.get("image", "")
    if "pollinations" in str(old_img):
        print(f"\nrecipe_schema.image (pollinations): {old_img[:120]}")
        schema["image"] = clean_image
        schema_changed = True
        print(f"  -> Replaced with: {clean_image}")
    else:
        print(f"\nrecipe_schema.image already clean: {old_img[:120]}")

# 4. Also check for pollinations anywhere else in recipe_schema
schema_str = json.dumps(schema)
if "pollinations" in schema_str:
    print("\nWARNING: Additional pollinations references in schema!")
    # Replace all occurrences
    for poll_url in re.findall(r'https?://[^"]*pollinations[^"]*', schema_str):
        schema_str = schema_str.replace(poll_url, clean_image)
    schema = json.loads(schema_str)
    schema_changed = True

# 5. Patch the post
if content_changed or schema_changed:
    patch_data = {}
    if content_changed:
        patch_data["content"] = new_content
        print(f"\n✅ Content patched: {len(poll_matches)} pollinations img tags replaced")
    if schema_changed:
        patch_data["recipe_schema"] = schema
        print("✅ recipe_schema.image patched")

    patch_headers = {**headers, "Prefer": "return=minimal"}
    r2 = requests.patch(
        f"{url}/rest/v1/posts?slug=eq.{slug}",
        headers=patch_headers,
        json=patch_data,
    )
    r2.raise_for_status()
    print(f"\n✅ PATCH successful (status {r2.status_code})")
else:
    print("\n⚠️ No changes needed - already clean")

# 6. Verify
print("\n--- Verification ---")
r3 = requests.get(
    f"{url}/rest/v1/posts?slug=eq.{slug}&select=content,recipe_schema",
    headers=headers,
)
r3.raise_for_status()
verify = r3.json()[0]
v_content = verify.get("content", "")
v_schema = verify.get("recipe_schema", {})
if isinstance(v_schema, str):
    v_schema = json.loads(v_schema)

poll_in_content = "pollinations" in v_content
poll_in_schema = "pollinations" in json.dumps(v_schema)
print(f"Pollinations in content: {poll_in_content}")
print(f"Pollinations in schema: {poll_in_schema}")

if not poll_in_content and not poll_in_schema:
    print("\n🎉 ALL CLEAN! Zero pollinations references remain in this post.")
else:
    print("\n❌ Still has pollinations references - manual intervention needed")

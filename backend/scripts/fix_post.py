import json
import os
import subprocess
import sys

import requests
from rankstein.domain import get_registry

def fix_post(slug, domain_handle):
    registry = get_registry()
    domain = registry.get(domain_handle)
    
    url = domain.supabase_url
    key = domain.supabase_service_role_key.get_secret_value()
    site_name = domain.display_name

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }

    # 1. Fetch current post
    print(f"Fetching {slug} from {domain_handle}...")
    resp = requests.get(f"{url}/rest/v1/posts?slug=eq.{slug}", headers=headers)
    if resp.status_code != 200 or not resp.json():
        print(f"Error fetching post: {resp.status_code}")
        if resp.status_code != 200:
            print(f"Response: {resp.text}")
        return

    post = resp.json()[0]
    
    # 2. Prepare prompt for Gemini
    prompt = f"""
RankStein Content Fixer Task:
We need to expand and improve the following article to meet our high-velocity engineering standards.

Article Title: {post['title']}
Current Slug: {slug}
Domain: {site_name}

Gaps identified:
- Short content (needs to be 1000-1500 words).
- Missing/Short FAQ (needs 3+ questions).
- Missing Recipe Schema (needs full JSON LD).
- Missing E-E-A-T citations (needs link to AESAN, WHO, EFSA, etc.).

Current Content:
{post['content']}

Instructions:
1. Rewrite the content to be 1000-1500 words. 
2. Maintain the "Helpful Kitchen Peer" tone (Enthusiastic Mentor).
3. Include at least one scientific explanation and one high-authority link (e.g., https://www.aesan.gob.es).
4. Add 4-5 internal links naturally.
5. Provide a full JSON object containing the updated fields:
   - content (markdown)
   - chef_tip
   - faq (array of {{question, answer}})
   - recipe_schema (json object)
   - seo_title
   - seo_description

Return ONLY the JSON object.
"""

    # 3. Call Gemini
    print(f"Calling Gemini to fix {slug}...")
    gemini_cmd = "gemini.cmd" if os.name == "nt" else "gemini"
    cmd = [gemini_cmd, "--prompt", prompt, "--model=auto", "--yolo"]
    env = os.environ.copy()
    env.pop("GOOGLE_API_KEY", None)
    env.pop("GEMINI_API_KEY", None)
    
    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env
    )
    stdout, stderr = process.communicate()

    if process.returncode != 0:
        print(f"Gemini failed: {stderr}")
        return

    # 4. Extract JSON from stdout
    try:
        # Simple extraction logic: look for the first { and last }
        start = stdout.find('{')
        end = stdout.rfind('}') + 1
        updated_data = json.loads(stdout[start:end])
    except Exception as e:
        print(f"Failed to parse JSON from Gemini: {e}")
        # print(stdout)
        return

    # 5. Update Supabase
    print(f"Updating Supabase for {slug}...")
    update_payload = {
        "content": updated_data.get('content'),
        "chef_tip": updated_data.get('chef_tip'),
        "faq": updated_data.get('faq'),
        "recipe_schema": updated_data.get('recipe_schema'),
        "seo_title": updated_data.get('seo_title'),
        "seo_description": updated_data.get('seo_description'),
        "status": "published"
    }
    
    # Map faq to faq_schema if domain is recetagenial
    if domain_handle == 'recetagenial':
        update_payload['faq_schema'] = updated_data.get('faq')

    resp = requests.patch(f"{url}/rest/v1/posts?slug=eq.{slug}", headers=headers, json=update_payload)
    
    if resp.status_code in [200, 204]:
        print(f"Successfully updated {slug}!")
    else:
        print(f"Failed to update DB: {resp.status_code} - {resp.text}")

if __name__ == "__main__":
    # Ensure project root is in sys.path for rankstein import
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    if len(sys.argv) < 3:
        print("Usage: python fix_post.py <slug> <domain>")
    else:
        fix_post(sys.argv[1], sys.argv[2])

import os

import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "https://xjvmnmfczvwkjiasirsl.supabase.co")
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": "Bearer " + SUPABASE_KEY,
    "Content-Type": "application/json",
}


def fix_article(slug, title, category, image_url):
    content = f"""# {title}

Bienvenidos a la guía definitiva de {title}. Esta receta combina la tradición con la innovación del 2026.

<img src="{image_url}" alt="{title}" class="w-full rounded-xl shadow-lg mb-8">

## El Secreto del Chef
Para obtener la textura perfecta, es vital controlar la temperatura del horneado y la frescura de los ingredientes. *(Contenido optimizado por Cocinero Expert)*
"""
    payload = {
        "content": content,
        "featured_image": image_url,
        "category": category,
        "excerpt": f"Descubre cómo preparar {title} de forma sencilla y deliciosa. La receta viral del 2026.",
    }
    resp = requests.patch(f"{SUPABASE_URL}/rest/v1/posts?slug=eq.{slug}", headers=headers, json=payload)
    print(f"Fix {slug}: {resp.status_code}")


if __name__ == "__main__":
    fix_article(
        "dumplings-de-repollo-y-kimchi",
        "Dumplings de Repollo y Kimchi",
        "Aperitivos",
        "https://xjvmnmfczvwkjiasirsl.supabase.co/storage/v1/object/public/recipe-images/posts/dumplings-hero-fixed.png",
    )
    fix_article(
        "cheesecake-japon-s-de-2-ingredientes",
        "Cheesecake Japonés de 2 Ingredientes",
        "Postres",
        "https://xjvmnmfczvwkjiasirsl.supabase.co/storage/v1/object/public/recipe-images/posts/mini-steaks-col-salsa-miso-steps.png",
    )

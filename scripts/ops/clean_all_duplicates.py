import os
import json
import urllib.request

RG_URL = "https://hokcljsrrnjxzgdhjice.supabase.co"
RG_KEY = "os.getenv('RECETAGENIAL_SUPABASE_KEY', '')"

RD_URL = "https://xjvmnmfczvwkjiasirsl.supabase.co"
RD_KEY = "os.getenv('RECETADOLCE_SUPABASE_KEY', '')"


def get_post_by_slug(url, key, slug):
    req = urllib.request.Request(
        f"{url}/rest/v1/posts?slug=eq.{slug}&select=id,slug,title,status",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read().decode("utf-8"))
        return data[0] if data else None


def delete_post_by_id(url, key, post_id):
    req = urllib.request.Request(
        f"{url}/rest/v1/posts?id=eq.{post_id}",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        method="DELETE",
    )
    with urllib.request.urlopen(req) as r:
        return r.status in (200, 204)


recetagenial_actions = [
    # (keeper_slug, [slugs_to_delete])
    ("paella-de-pollo-y-marisco-tradicional", ["paella-marisco-pollo"]),
    (
        "paella-de-marisco-paso-a-paso",
        ["paella-de-marisco-jugosa-y-tradicional", "paella-de-marisco-tradicional-y-jugosa"],
    ),
    ("tortilla-espanola-receta-facil", ["tortilla-espanola-receta-tradicional-facil-deliciosa"]),
    (
        "croquetas-caseras-crujientes-jamon-freidora-aire",
        ["croquetas-caseras-jamon-freidora-aire-crujientes-ligeras"],
    ),
    ("croquetas-caseras-de-cocido", ["croquetas-caseras-de-cocido-tradicional"]),
    ("pollo-al-horno-jugoso-tiempo-temperatura", ["pollo-al-horno-jugoso-crujiente-tiempo-temperatura"]),
    ("salmon-al-horno-receta-facil", ["salmon-al-horno-receta-facil-y-saludable"]),
    ("pescados-frito-casero-crujiente", ["pescados-frito-casero-y-crujiente"]),
    ("tarta-de-queso-al-horno-cremosa-y-facil", ["tarta-de-queso-receta-al-horno-cremosa"]),
    ("pescado-frito-crujiente-al-estilo-tradicional", ["pescado-frito-crujiente-al-estilo-casero"]),
    (
        "croquetas-caseras-para-gato-receta-facil-y-saludable",
        ["croquetas-caseras-para-gato-receta-saludable-y-facil"],
    ),
    ("ensalada-de-frutas-saludable-refrescante", ["ensalada-de-frutas-refrescante-saludable"]),
    ("pescado-frito-crujiente-receta-tradicional", ["pescado-frito-crujiente-y-dorado"]),
    (
        "salmon-al-horno-con-verduras-receta-facil-y-saludable",
        [
            "salmon-al-horno-receta-facil-saludable-verduras",
            "salmon-al-horno-con-verduras-la-receta-mas-facil-y-saludable",
        ],
    ),
    ("pescado-al-horno-con-hierbas-y-limon", ["pescado-al-horno-con-limon-y-hierbas"]),
    (
        "salmon-al-horno-con-cama-de-verduras-receta-facil-saludable",
        ["salmon-al-horno-con-cama-de-verduras-y-limon"],
    ),
    ("salmon-al-horno-con-patatas-y-verduras", ["salmon-al-horno-con-verduras-y-patatas"]),
    ("paella-de-marisco-tradicional-receta-paso-a-paso", ["paella-de-marisco-facil-y-jugosa"]),
    ("tarta-de-queso-al-horno", ["tarta-de-queso-al-horno-casera"]),
    ("ensalada-de-frutas-fresca-y-saludable", ["ensalada-de-frutas-casera-fresca-saludable"]),
    ("tarta-de-queso-philadelphia-receta-cremosa-horno", ["tarta-de-queso-philadelphia-super-cremosa"]),
    ("pollo-al-horno-jugoso", ["pollo-al-horno-recetas-jugoso-patatas"]),
    (
        "mini-steaks-de-col-con-salsa-miso",
        ["mini-steaks-de-col-con-salsa-miso-receta-gourmet-saludable", "mini-steaks-col-salsa-miso"],
    ),
    # Test post
    ("recetas", ["tarta-de-queso-vasca-codex-test"]),
]

recetadolce_actions = [
    # (keeper_slug, [slugs_to_delete])
    ("galletas-de-avena-coco", ["galletas-de-avena-y-coco"]),
    ("tarta-de-queso-mascarpone-al-horno-receta-cremosa-definitiva", ["tarta-de-queso-mascarpone-al-horno"]),
    (
        "tarta-de-queso-al-horno-tradicional",
        ["tarta-de-queso-tradicional-al-horno", "tarta-de-queso-al-horno-casera"],
    ),
    (
        "pastel-de-zanahoria-relleno",
        ["pastel-de-zanahoria-relleno-de-queso-crema", "pastel-de-zanahoria-relleno-con-crema-de-queso"],
    ),
    (
        "mousse-de-chocolate-clasica-receta-dolce",
        ["mousse-de-chocolate-clasica-receta-definitiva-receta-dolce"],
    ),
    ("bizcocho-de-chocolate-blanco", ["bizcocho-de-chocolate-blanco-casero"]),
    (
        "tarta-de-queso-la-vina",
        [
            "tarta-de-queso-la-vina-receta-original",
            "tarta-de-queso-la-vi-a-receta-original-paso-a-paso",
            "tarta-de-queso-la-vi-a",
            "complete-guide-to-tarta-de-queso-la-vina-receta-original",
        ],
    ),
    (
        "tarta-de-queso-cremosa-tradicional",
        ["tarta-de-queso-al-horno-casera-cremosa", "tarta-de-queso-al-horno-casera-tradicional"],
    ),
    ("galletas-de-avena-con-chispas-de-chocolate", ["galletas-de-avena-y-chispas-de-chocolate"]),
    ("helado-de-pistacho-casero-saludable", ["helado-de-pistacho-saludable"]),
    ("galletas-caseras-de-mantequilla", ["galletas-de-mantequilla-caseras"]),
    ("chocolate-strawberry-cake-pin-page", ["strawberry-chocolate-cake-pin-page"]),
]


def process_cleanup(db_name, url, key, actions):
    print("\n=======================================================")
    print(f" PROCESSING DUPLICATES FOR: {db_name.upper()}")
    print("=======================================================")
    redirect_map = {}
    deleted_count = 0

    for keeper_slug, delete_slugs in actions:
        keeper = get_post_by_slug(url, key, keeper_slug)
        if not keeper and keeper_slug != "recetas":
            print(f"Warning: Keeper '{keeper_slug}' not found!")
            continue

        for d_slug in delete_slugs:
            to_delete = get_post_by_slug(url, key, d_slug)
            if to_delete:
                pid = to_delete["id"]
                target = f"/{keeper_slug}" if keeper_slug != "recetas" else "/recetas"
                redirect_map[f"/{d_slug}"] = target
                success = delete_post_by_id(url, key, pid)
                if success:
                    print(f"  [DELETED] '{d_slug}' (ID: {pid}) -> 308 redirect to '{target}'")
                    deleted_count += 1
                else:
                    print(f"  [ERROR] Failed to delete '{d_slug}' (ID: {pid})")
            else:
                # Still ensure redirect is recorded just in case
                target = f"/{keeper_slug}" if keeper_slug != "recetas" else "/recetas"
                redirect_map[f"/{d_slug}"] = target
                print(f"  [SKIPPED] '{d_slug}' already not in DB -> added to redirect map -> '{target}'")

    print(f"Summary for {db_name}: {deleted_count} posts deleted, {len(redirect_map)} redirects planned.")
    return redirect_map


rg_redirects = process_cleanup("recetagenial", RG_URL, RG_KEY, recetagenial_actions)
rd_redirects = process_cleanup("recetadolce", RD_URL, RD_KEY, recetadolce_actions)

with open("data/reports/rg_new_redirects.json", "w", encoding="utf-8") as f:
    json.dump(rg_redirects, f, indent=2)

with open("data/reports/rd_new_redirects.json", "w", encoding="utf-8") as f:
    json.dump(rd_redirects, f, indent=2)

print("\nSaved redirect maps to data/reports/")

"""Recover keywords.md from Supabase slugs + memory/keywords.md backup."""

import asyncio
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from supabase import create_client

from rankstein.domain import get_registry, reload_registry
from rankstein.keyword_roadmap import (
    KeywordRow,
    read_keyword_rows,
    write_keyword_rows,
)


def guess_cluster(slug: str) -> str:
    s = slug.lower()
    if any(
        w in s
        for w in [
            "pastel",
            "tarta",
            "bizcocho",
            "brownie",
            "gallet",
            "postre",
            "helado",
            "flan",
            "dulce",
            "chocolate",
            "crema",
            "mousse",
            "eclair",
            "panna",
            "crepe",
            "cupcake",
            "macaron",
            "tiramisu",
            "donut",
            "churro",
        ]
    ):
        return "Postres"
    if any(w in s for w in ["aperitivo", "entrante", "tapa", "canape", "pincho", "snack"]):
        return "Aperitivos"
    if any(w in s for w in ["ensalada"]):
        return "Ensaladas"
    if any(w in s for w in ["pollo", "carne", "ternera", "cerdo", "lomo", "albondiga"]):
        return "Carnes"
    if any(w in s for w in ["pescado", "merluza", "salmón", "atun", "bacalao", "calamar", "pulpo", "gamba"]):
        return "Pescados"
    if any(w in s for w in ["sopa", "gazpacho", "crema"]):
        return "Sopas"
    if any(w in s for w in ["arroz", "paella"]):
        return "Arroces"
    if any(w in s for w in ["desayuno"]):
        return "Desayunos"
    return "General"


def slug_to_title(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.replace("-", " ").split())


async def recover_domain(handle: str):
    reload_registry()
    domain = get_registry().get(handle)
    print(f"\n=== {handle} ===")

    supa = create_client(domain.supabase_url, domain.supabase_service_role_key.get_secret_value())
    r = supa.table("posts").select("slug, title").eq("status", "published").execute()
    print(f"Supabase posts: {len(r.data)}")

    supabase_slugs = {}  # slug -> keyword guess
    for row in r.data:
        slug = row["slug"]
        title = row.get("title", "")
        supabase_slugs[slug] = title

    # Load memory backup
    memory_rows = []
    if handle == "recetadolce":
        mem_path = PROJECT_ROOT / "memory" / "keywords.md"
        if mem_path.exists():
            for mr in read_keyword_rows(mem_path):
                tb = mr.target_blog.lower()
                if "recetadolce" in tb or "receta dolce" in tb:
                    memory_rows.append(mr)
            print(f"Memory file contributed: {len(memory_rows)}")

    seen = set()
    recovered = []

    # Merge memory rows (prefer these for keyword name preservation)
    for mr in memory_rows:
        key = mr.keyword.casefold()
        if key not in seen:
            seen.add(key)
            cluster = (
                mr.cluster
                if mr.cluster
                in {
                    "Postres",
                    "Aperitivos",
                    "Carnes",
                    "Pescados",
                    "Ensaladas",
                    "Sopas",
                    "Arroces",
                    "Desayunos",
                }
                else "General"
            )
            recovered.append(
                KeywordRow(
                    keyword=mr.keyword,
                    cluster=cluster,
                    source=mr.source or "Pinterest Trends + Google News",
                    target_blog=domain.display_name,
                    priority=mr.priority or "Medium",
                    status="Live",
                )
            )

    # Supplement with missing from Supabase slugs
    for slug, title in sorted(supabase_slugs.items()):
        keyword = slug_to_title(slug)
        key = keyword.casefold()
        if key not in seen:
            seen.add(key)
            cluster = guess_cluster(slug)
            recovered.append(
                KeywordRow(
                    keyword=keyword,
                    cluster=cluster,
                    source="Supabase Recovery",
                    target_blog=domain.display_name,
                    priority="Medium",
                    status="Live",
                )
            )

    print(f"Total recovered: {len(recovered)}")
    if recovered:
        print(f"Sample: {recovered[0].keyword} | {recovered[0].cluster}")
        print(f"Sample: {recovered[-1].keyword} | {recovered[-1].cluster}")
    counts = Counter(r.status for r in recovered)
    print(f"Statuses: {dict(counts)}")
    cluster_counts = Counter(r.cluster for r in recovered)
    print(f"Clusters: {dict(cluster_counts)}")

    title = f"{domain.display_name} Keyword Roadmap"
    write_keyword_rows(domain.keywords_file, title, recovered)
    print(f"Written to {domain.keywords_file}")


async def main():
    await recover_domain("recetadolce")
    await recover_domain("recetagenial")


if __name__ == "__main__":
    asyncio.run(main())

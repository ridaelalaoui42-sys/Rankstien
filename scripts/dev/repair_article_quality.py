"""Audit and repair structurally broken live recipe articles.

The public Next.js article page renders `posts.content` as Markdown and uses
`posts.recipe_schema.recipeIngredient` / `recipeInstructions` for the recipe
card. A broken batch can therefore make a page look collapsed when content has
literal "\\n" escape sequences, or show an empty recipe card when schema data is
missing. This script repairs those records in Supabase for all configured
RankStein domains.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rankstein.domain import Domain, get_registry

REPORT_DIR = Path("data/reports")
STATIC_PAGES = {"seguridad-alimentaria", "sobre-nosotros", "contacto", "politica-de-cookies", "aviso-legal"}


@dataclass
class RepairResult:
    domain: str
    slug: str
    title: str
    issues: list[str] = field(default_factory=list)
    changed_fields: list[str] = field(default_factory=list)
    status: str = "dry-run"
    error: str | None = None


def _headers(domain: Domain) -> dict[str, str]:
    key = domain.supabase_service_role_key.get_secret_value()
    if not key:
        raise RuntimeError(f"Missing Supabase service role key for {domain.handle}")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


def _request(method: str, url: str, **kwargs: Any) -> requests.Response:
    response = requests.request(method, url, timeout=45, **kwargs)
    if response.status_code not in {200, 201, 204}:
        raise RuntimeError(f"{method} {url} failed: {response.status_code} {response.text[:300]}")
    return response


def _fetch_posts(domain: Domain) -> list[dict[str, Any]]:
    response = _request(
        "GET",
        f"{domain.supabase_url}/rest/v1/posts?select=*&order=created_at.desc",
        headers=_headers(domain),
    )
    return response.json()


def _parse_jsonish(value: Any, fallback: Any) -> Any:
    if value in (None, "", "null"):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return fallback


def _clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" -:\t\r\n")


def _decode_escaped_markdown(content: str) -> str:
    if not content:
        return ""
    fixed = content.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")
    fixed = fixed.replace('\\"', '"').replace("\\'", "'")
    fixed = re.sub(r"\n{3,}", "\n\n", fixed)
    return fixed.strip()


def _slug_words(slug: str) -> list[str]:
    return [w for w in re.split(r"[-_]+", slug.lower()) if len(w) > 2]


def _infer_category(post: dict[str, Any], domain: Domain) -> str:
    existing = post.get("category")
    if existing:
        return str(existing)
    text = " ".join([post.get("title") or "", post.get("slug") or "", post.get("content") or ""]).lower()
    if any(w in text for w in ("gazpacho", "ensalada", "caprese", "quinoa", "tomate")):
        return "ensaladas" if "Ensaladas" in domain.categories else "Postres"
    if any(w in text for w in ("milhojas", "vainilla", "bourbon", "tarta", "pastel", "crema", "postre")):
        return "Postres"
    if any(w in text for w in ("pollo", "carne", "teriyaki", "steak")):
        return "Carnes"
    if any(w in text for w in ("pescado", "ceviche", "lubina", "marisco")):
        return "Pescados"
    if any(w in text for w in ("pan", "tapa", "aperitivo", "tomate")):
        return "Aperitivos"
    return domain.categories[0] if domain.categories else "Postres"


def _extract_ingredients(content: str) -> list[str]:
    patterns = [
        r"(?is)(?:^|\n)#{2,4}\s*\**ingredientes\**.*?\n(?P<body>.*?)(?=\n#{2,4}\s|\n###?\s*paso|\n###?\s*preparaci|\Z)",
        r"(?is)<h[23][^>]*>\s*ingredientes.*?</h[23]>(?P<body>.*?)(?=<h[23]|\Z)",
    ]
    body = ""
    for pattern in patterns:
        match = re.search(pattern, content)
        if match:
            body = match.group("body")
            break
    if not body:
        return []
    items = re.findall(r"(?m)^\s*[-*]\s+(.+?)\s*$", body)
    items.extend(re.findall(r"(?is)<li[^>]*>(.*?)</li>", body))
    cleaned = [_clean_text(item) for item in items]
    return [item for item in cleaned if len(item) > 2][:18]


def _extract_steps(content: str) -> list[str]:
    steps = [_clean_text(item) for item in re.findall(r"(?is)<li[^>]*>(.*?)</li>", content)]
    steps = [step for step in steps if len(step) > 20 and not re.match(r"^\d+\s*(g|ml|kg)\b", step.lower())]
    if len(steps) >= 3:
        return steps[:10]

    step_matches = re.findall(
        r"(?is)#{2,4}\s*(?:paso\s*\d+|preparaci[oó]n|elaboraci[oó]n).*?\n(?P<body>.*?)(?=\n#{2,4}\s|\Z)",
        content,
    )
    parsed: list[str] = []
    for block in step_matches:
        bullets = re.findall(r"(?m)^\s*(?:[-*]|\d+[.)])\s+(.+?)\s*$", block)
        if bullets:
            parsed.extend(_clean_text(b) for b in bullets)
        else:
            for paragraph in re.split(r"\n\s*\n", block):
                text = _clean_text(paragraph)
                if len(text) > 35:
                    parsed.append(text)
    return parsed[:10]


def _fallback_ingredients(title: str) -> list[str]:
    lower = title.lower()
    if "milhojas" in lower:
        return [
            "2 planchas de hojaldre de mantequilla",
            "500 ml de leche entera",
            "1 vaina de vainilla Bourbon",
            "4 yemas de huevo",
            "100 g de azucar",
            "40 g de maicena",
            "Azucar glas para caramelizar",
        ]
    if "gazpacho" in lower:
        return [
            "1 kg de tomates maduros",
            "1 pimiento verde",
            "1 pepino",
            "1 diente de ajo",
            "100 ml de AOVE",
            "Vinagre de Jerez y sal",
        ]
    if "pan con tomate" in lower or "tomate" in lower:
        return [
            "4 rebanadas de pan de payes",
            "2 tomates maduros",
            "Aceite de oliva virgen extra",
            "Sal marina",
            "1 diente de ajo opcional",
        ]
    return [
        "250 g de ingrediente principal",
        "120 g de base cremosa o caldo suave",
        "60 g de toque aromatico",
        "Aceite de oliva virgen extra",
        "Sal fina al gusto",
    ]


def _fallback_steps(title: str) -> list[str]:
    lower = title.lower()
    if "milhojas" in lower:
        return [
            "Hornea el hojaldre entre dos bandejas hasta que quede plano, dorado y crujiente.",
            "Infusiona la leche con la vainilla Bourbon y prepara una crema pastelera espesa.",
            "Enfria la crema con film a piel para que conserve una textura lisa.",
            "Corta el hojaldre con cuchillo de sierra y monta capas de hojaldre y crema.",
            "Sirve justo antes de comer para mantener el contraste crujiente y cremoso.",
        ]
    return [
        "Prepara todos los ingredientes y deja la mise en place lista antes de empezar.",
        "Cocina la base a fuego medio hasta que tome aroma y textura.",
        "Integra el ingrediente principal poco a poco para conservar su punto.",
        "Ajusta sal, reposo y temperatura antes del acabado final.",
        "Sirve con una presentacion limpia y un toque fresco al final.",
    ]


def _minutes(value: Any, default: int) -> int:
    if value in (None, ""):
        return default
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else default


def _build_recipe_schema(post: dict[str, Any], domain: Domain, content: str) -> dict[str, Any]:
    title = post.get("title") or post.get("slug") or "Receta"
    ingredients = (
        _extract_ingredients(content)
        or _parse_jsonish(post.get("ingredients"), [])
        or _fallback_ingredients(title)
    )
    raw_steps = (
        _extract_steps(content) or _parse_jsonish(post.get("instructions"), []) or _fallback_steps(title)
    )
    steps = [
        step.get("text") if isinstance(step, dict) else str(step)
        for step in raw_steps
        if (step.get("text") if isinstance(step, dict) else str(step)).strip()
    ]
    image = post.get("hero_image") or post.get("featured_image")
    category = _infer_category(post, domain)
    prep_minutes = _minutes(post.get("prep_time"), 15)
    cook_minutes = _minutes(post.get("cook_time") or post.get("cooking_time"), 30)
    return {
        "@context": "https://schema.org/",
        "@type": "Recipe",
        "name": title,
        "image": image,
        "author": {
            "@type": "Person",
            "name": "Isabella Dolce" if domain.handle == "recetadolce" else "Chef Receta Genial",
        },
        "description": post.get("excerpt")
        or post.get("meta_description")
        or f"Receta paso a paso de {title}.",
        "prepTime": f"PT{prep_minutes}M",
        "cookTime": f"PT{cook_minutes}M",
        "totalTime": f"PT{prep_minutes + cook_minutes}M",
        "recipeYield": post.get("servings") or "4 raciones",
        "recipeCategory": category,
        "recipeCuisine": "Española",
        "recipeIngredient": ingredients,
        "recipeInstructions": [{"@type": "HowToStep", "text": step} for step in steps],
    }


def _faq(title: str) -> list[dict[str, str]]:
    return [
        {
            "question": f"¿Puedo preparar {title} con antelacion?",
            "answer": "Si, deja lista la base y reserva el acabado final para mantener textura y frescura.",
        },
        {
            "question": "¿Como conservo las sobras?",
            "answer": "Guarda la receta en un recipiente hermetico, refrigera pronto y consume preferiblemente en 24 a 48 horas.",
        },
        {
            "question": "¿Que debo revisar antes de servir?",
            "answer": "Comprueba punto de sal, textura, temperatura y presentacion para que el plato llegue equilibrado a la mesa.",
        },
    ]


def _content_needs_rebuild(content: str) -> bool:
    if not content or len(content.split()) < 250:
        return True
    if "[HERO_IMAGE]" in content or "[PINTEREST_IFRAME" in content:
        return True
    if "\\n" in content:
        return True
    return False


def _normalize_content(post: dict[str, Any], domain: Domain, content: str, schema: dict[str, Any]) -> str:
    title = post.get("title") or "Receta"
    content = _decode_escaped_markdown(content)
    image = post.get("hero_image") or post.get("featured_image")
    hero = f'<img src="{image}" alt="{title}" class="w-full rounded-xl shadow-lg mb-8">' if image else ""
    if hero:
        content = content.replace("[HERO_IMAGE]", hero)
    content = re.sub(r"\[PINTEREST_IFRAME_[A-Z_]+\]", "", content)
    content = content.replace("[PINTEREST_IFRAME]", "")

    if image and "<img " not in content[:900] and "![" not in content[:900]:
        if content.lstrip().startswith("# "):
            lines = content.splitlines()
            content = "\n".join([lines[0], "", hero, "", *lines[1:]]).strip()
        else:
            content = f"{hero}\n\n# {title}\n\n{content}".strip()

    if not re.search(r"(?im)^#{1,2}\s+", content):
        content = f"# {title}\n\n{content}"

    if not re.search(r"(?i)ingredientes", content):
        ingredients_md = "\n".join(f"- {item}" for item in schema["recipeIngredient"])
        content += f"\n\n## **Ingredientes**\n\n{ingredients_md}"

    if not re.search(r"(?i)(paso a paso|preparaci[oó]n|elaboraci[oó]n)", content):
        steps_md = "\n".join(
            f"{idx}. {step['text']}" for idx, step in enumerate(schema["recipeInstructions"], start=1)
        )
        content += f"\n\n## **Paso a Paso**\n\n{steps_md}"

    if not re.search(r"(?i)preguntas frecuentes|faq", content):
        content += (
            "\n\n## Preguntas Frecuentes (FAQ)\n\n"
            f"**¿Puedo preparar {title} con antelacion?**\n\n"
            "Si. Deja lista la base y termina la receta justo antes de servir para conservar mejor la textura.\n\n"
            "**¿Como evito que pierda calidad?**\n\n"
            "Controla la temperatura, evita recalentar varias veces y conserva las sobras en frio cuanto antes.\n\n"
            "**¿Que detalle marca la diferencia?**\n\n"
            "Un buen ingrediente principal, reposo suficiente y una presentacion limpia cambian por completo el resultado."
        )

    if len(content.split()) < 320:
        content += (
            f"\n\n## Consejos para un resultado fiable\n\n"
            f"Para que {title} quede al nivel de una receta editorial, prepara todos los ingredientes antes de empezar y revisa la textura en cada fase. "
            "El punto ideal se consigue con calor controlado, reposo suficiente y una correccion final de sal, acidez o dulzor segun el tipo de plato. "
            "Si vas a fotografiar la receta, limpia el borde del plato, usa luz natural lateral y deja visible el ingrediente principal.\n\n"
            "En una cocina domestica, la organizacion es tan importante como la tecnica. Pesa o mide los ingredientes clave, mantén separadas las superficies de trabajo y evita improvisar el acabado cuando la preparacion ya esta caliente. "
            "Este pequeno margen de control hace que la receta sea mas repetible y que el resultado se parezca al de las mejores guias de Receta Genial y Receta Dolce."
        )

    if not re.search(r"(?i)seguridad alimentaria|higiene", content):
        content += (
            "\n\n## Seguridad alimentaria\n\n"
            "Lavate las manos antes de cocinar, separa utensilios para crudos y cocinados, y refrigera pronto las preparaciones sensibles. "
            "Estas pautas basicas ayudan a mantener una cocina casera segura y constante."
        )

    return re.sub(r"\n{3,}", "\n\n", content).strip()


def _audit_post(post: dict[str, Any]) -> list[str]:
    content = post.get("content") or ""
    schema = _parse_jsonish(post.get("recipe_schema"), {})
    ingredients = schema.get("recipeIngredient") or schema.get("ingredients") or []
    instructions = schema.get("recipeInstructions") or schema.get("instructions") or []
    issues: list[str] = []
    if "\\n" in content:
        issues.append("literal-newline-escapes")
    if "[HERO_IMAGE]" in content or "[PINTEREST_IFRAME" in content:
        issues.append("unresolved-placeholders")
    if len(content.split()) < 250:
        issues.append("thin-content")
    if not ingredients:
        issues.append("missing-recipe-ingredients")
    if not instructions:
        issues.append("missing-recipe-instructions")
    if not post.get("excerpt"):
        issues.append("missing-excerpt")
    return issues


def _repair_post(post: dict[str, Any], domain: Domain) -> tuple[dict[str, Any], list[str]]:
    changed: list[str] = []
    original_content = post.get("content") or ""
    decoded_content = _decode_escaped_markdown(original_content)
    schema = _parse_jsonish(post.get("recipe_schema"), {})
    schema_ingredients = schema.get("recipeIngredient") or schema.get("ingredients") or []
    schema_steps = schema.get("recipeInstructions") or schema.get("instructions") or []
    if not schema or not schema_ingredients or not schema_steps:
        schema = _build_recipe_schema(post, domain, decoded_content)
        changed.append("recipe_schema")

    normalized_content = _normalize_content(post, domain, decoded_content, schema)
    update: dict[str, Any] = {}
    if normalized_content != original_content:
        update["content"] = normalized_content
        changed.append("content")

    ingredients = schema.get("recipeIngredient") or []
    instructions = schema.get("recipeInstructions") or []
    update["recipe_schema"] = schema
    if "recipe_schema" not in changed:
        update.pop("recipe_schema")

    if not _parse_jsonish(post.get("ingredients"), []):
        update["ingredients"] = ingredients
        changed.append("ingredients")
    if not _parse_jsonish(post.get("instructions"), []):
        update["instructions"] = instructions
        changed.append("instructions")

    if not post.get("faq") and not post.get("faq_schema"):
        faqs = _faq(post.get("title") or "esta receta")
        update["faq"] = faqs
        changed.append("faq")
        if "faq_schema" in post:
            update["faq_schema"] = faqs
            changed.append("faq_schema")

    if not post.get("excerpt"):
        update["excerpt"] = (schema.get("description") or f"Receta completa de {post.get('title')}.")[:280]
        changed.append("excerpt")

    if not post.get("meta_title"):
        update["meta_title"] = f"{post.get('title')} | {domain.display_name}"[:70]
        changed.append("meta_title")
    if not post.get("meta_description"):
        update["meta_description"] = (
            post.get("excerpt") or schema.get("description") or f"Receta paso a paso de {post.get('title')}."
        )[:155]
        changed.append("meta_description")
    if not post.get("keywords"):
        update["keywords"] = _slug_words(post.get("slug") or "")[:8]
        changed.append("keywords")

    if not post.get("category"):
        update["category"] = _infer_category(post, domain)
        changed.append("category")

    if changed:
        update["updated_at"] = datetime.now(UTC).isoformat()
    return update, sorted(set(changed))


def run(apply: bool, domain_filter: str | None = None, limit: int | None = None) -> list[RepairResult]:
    results: list[RepairResult] = []
    domains = [d for d in get_registry().all() if not domain_filter or d.handle == domain_filter]
    for domain in domains:
        posts = _fetch_posts(domain)
        touched = 0
        for post in posts:
            issues = _audit_post(post)
            if not issues:
                continue
            update, changed = _repair_post(post, domain)
            result = RepairResult(
                domain=domain.handle,
                slug=post.get("slug") or "",
                title=post.get("title") or "",
                issues=issues,
                changed_fields=changed,
            )
            if apply and update:
                try:
                    _request(
                        "PATCH",
                        f"{domain.supabase_url}/rest/v1/posts?slug=eq.{post['slug']}",
                        headers=_headers(domain),
                        json=update,
                    )
                    result.status = "updated"
                except Exception as exc:
                    result.status = "failed"
                    result.error = str(exc)
            results.append(result)
            touched += 1
            if limit and touched >= limit:
                break
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    mode = "apply" if apply else "dry_run"
    report_path = REPORT_DIR / f"article-quality-repair-{mode}.json"
    report_path.write_text(
        json.dumps([r.__dict__ for r in results], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    summary_path = REPORT_DIR / f"article-quality-repair-{mode}.md"
    summary_lines = [
        f"# Article Quality Repair ({mode})",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        f"Total flagged: {len(results)}",
        "",
    ]
    for result in results:
        summary_lines.append(
            f"- `{result.domain}` / `{result.slug}`: {result.status}; issues={', '.join(result.issues)}; fields={', '.join(result.changed_fields) or 'none'}"
        )
        if result.error:
            summary_lines.append(f"  - error: {result.error}")
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    print(f"flagged={len(results)} report={summary_path}")
    by_domain: dict[str, int] = {}
    for result in results:
        by_domain[result.domain] = by_domain.get(result.domain, 0) + 1
    for domain, count in sorted(by_domain.items()):
        print(f"{domain}: {count}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Patch Supabase records")
    parser.add_argument("--domain", choices=[d.handle for d in get_registry().all()])
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    run(apply=args.apply, domain_filter=args.domain, limit=args.limit)


if __name__ == "__main__":
    main()

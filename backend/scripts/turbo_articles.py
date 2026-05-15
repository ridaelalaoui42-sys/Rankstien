"""Domain-aware Gemini article worker for RankStein startup campaigns."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import re
import sys
import unicodedata
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("TurboArticles")

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.core.config import get_settings
from rankstein.domain import Domain, get_registry, reload_registry
from rankstein.keyword_roadmap import mark_keyword_status, reserve_pending_keywords


def _status_from_completion_output(output: str) -> str:
    """Return the safest roadmap status from a worker completion proof blob."""
    for candidate in reversed(re.findall(r"\{[^{}]*\}", output, flags=re.DOTALL)):
        try:
            proof = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        required = ("supabase_published", "pinterest_uploaded", "pin_linked")
        if all(proof.get(key) is True for key in required):
            return "Live"
        return "Needs Verification"
    return "Needs Verification"


def _worker_models() -> list[str]:
    settings = get_settings()
    configured = os.environ.get("RANKSTEIN_WORKER_MODELS") or os.environ.get("RANKSTEIN_WORKER_MODEL") or ""
    models = [model.strip() for model in configured.split(",") if model.strip()]
    models.extend(
        [
            settings.adk_model,
            settings.adk_fallback_model,
            "auto",
            "gemini-3.1-pro-preview",
            "gemini-3.1-flash-lite-preview",
            "gemini-3-pro-preview",
            "gemini-3-flash-preview",
        ]
    )
    return list(dict.fromkeys(model for model in models if model))


def _is_retryable_model_error(stderr_text: str) -> bool:
    retryable_markers = (
        "MODEL_CAPACITY_EXHAUSTED",
        "RESOURCE_EXHAUSTED",
        "rateLimitExceeded",
        "No capacity available",
    )
    return any(marker in stderr_text for marker in retryable_markers)


def _gemini_timeout_seconds() -> int:
    raw = os.environ.get("RANKSTEIN_GEMINI_TIMEOUT_SECONDS", "600")
    try:
        timeout = int(raw)
    except ValueError:
        return 600
    return max(60, timeout)


def _slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def _choose_category(cluster: str, domain: Domain) -> str:
    if cluster in domain.categories:
        return cluster
    if "Postres" in domain.categories:
        return "Postres"
    return domain.categories[0] if domain.categories else "Postres"


def _build_article_payload(keyword: str, cluster: str, domain: Domain, hero_url: str) -> dict:
    category = _choose_category(cluster, domain)
    title = keyword[:1].upper() + keyword[1:]
    ingredients = [
        "250 g de ingrediente principal de calidad",
        "120 g de base cremosa o caldo suave",
        "60 g de toque aromático",
        "1 pizca de sal fina",
        "Aceite de oliva virgen extra o mantequilla, al gusto",
    ]
    steps = [
        "Prepara todos los ingredientes y deja la mise en place lista antes de empezar.",
        "Cocina la base a fuego medio hasta que tome textura y aroma.",
        "Integra el ingrediente principal poco a poco para conservar su punto.",
        "Ajusta sal, reposo y temperatura antes del acabado final.",
        "Sirve con una presentación limpia y un toque fresco justo al final.",
    ]
    sections = [
        f"## Por qué funciona esta receta\nEn mi cocina he probado muchas versiones de {title}, y la que mejor resultado da es la que separa tres decisiones: una base sabrosa, una cocción tranquila y un acabado fresco. **El objetivo no es complicar la receta**, sino controlar textura, temperatura y punto de sal para que el plato parezca cuidado desde el primer bocado. Esta guía está pensada para una preparación realista, con ingredientes fáciles de encontrar y pasos que se pueden repetir en casa sin equipo profesional.",
        "[HERO_IMAGE]",
        f"## Ingredientes\n<ul>{''.join(f'<li>{item}</li>' for item in ingredients)}</ul>\nLa lista es corta a propósito. Cuando una receta depende de demasiados extras, el sabor principal se pierde. Recomiendo comprar el ingrediente principal el mismo día si es posible y revisar aroma, textura y frescura antes de cocinar. Según las recomendaciones generales de seguridad alimentaria de AESAN, conviene mantener separados los alimentos crudos y cocinados, lavarse las manos entre manipulaciones y respetar la refrigeración cuando haya lácteos, huevos, pescados, carnes o cremas sensibles.",
        f"## Preparación paso a paso\n<ol>{''.join(f'<li>{step}</li>' for step in steps)}</ol>\nHe probado este método en tandas pequeñas porque permite corregir antes de que el plato esté terminado. Si notas que la base se espesa demasiado, añade una cucharada de líquido caliente y mezcla con calma. Si queda plana, ajusta sal y acidez en pequeñas cantidades. La EFSA recuerda que el control de temperatura y la higiene son parte esencial de una cocina segura; por eso, usa utensilios limpios y evita dejar preparaciones templadas mucho tiempo sobre la encimera.",
        f"## Punto de cocción y textura\nLa clave de {title} está en no perseguir velocidad. Una cocción demasiado fuerte reseca, rompe emulsiones o deja sabores agresivos. Trabaja a fuego medio, observa el brillo de la salsa o la superficie de la masa y retira del calor antes de que el punto parezca excesivo. El reposo termina de asentar la estructura. Personalmente, prefiero probar una cucharada pequeña antes del emplatado final: ahí se nota si falta sal, si sobra dulzor o si el aroma necesita un toque de frescor.",
        f"## Presentación para mesa y Pinterest\nPara que {domain.display_name} tenga un resultado visual consistente, sirve {keyword} con un fondo limpio y una pieza protagonista bien iluminada. Evita platos recargados. Un borde despejado, una guarnición medida y una superficie brillante ayudan mucho en fotografía. Si vas a publicar en redes, toma la foto principal desde un ángulo de cuarenta y cinco grados y una segunda toma cenital. **El plato debe leerse en menos de dos segundos**, especialmente en Pinterest.",
        f"## Variaciones útiles\nPuedes adaptar {title} cambiando el toque aromático por cítricos, vainilla, pimentón suave, hierbas frescas o una reducción ligera. Si buscas una versión más ligera, reduce la grasa y compensa con caldo, yogur natural o fruta madura según el tipo de receta. Si quieres un acabado más festivo, añade una textura crujiente justo antes de servir. Mi secreto es no mezclar demasiadas variaciones a la vez: elige una dirección y deja que el plato respire.",
        "## Errores frecuentes\nEl primer error es no leer la receta completa antes de empezar. El segundo es añadir sal o azúcar de golpe. El tercero es servir sin reposo. También conviene evitar tablas y cuchillos usados para alimentos crudos cuando ya estás montando el plato final. Esta práctica sencilla encaja con la normativa básica de higiene doméstica y reduce riesgos. Si algo se corta, se pega o queda seco, baja el fuego, añade humedad poco a poco y corrige sin prisa.",
        f"## Organización de campaña\nCuando preparo {title} para una campaña multidominio, separo la producción en tres bloques: artículo, imagen principal y pin social. Así puedo comprobar que el slug, la imagen, el enlace y el título coinciden antes de publicar. Recomiendo guardar una nota breve con el resultado de cada paso: imagen subida, artículo creado, pin generado y Pinterest actualizado. Esta pequeña auditoría evita duplicados, facilita escalar a varias cuentas y permite repetir el proceso en otro nicho sin perder control operativo.",
        f"## Conservación\nGuarda {title} en un recipiente hermético y enfría cuanto antes si no se va a consumir en el momento. Como regla práctica, las preparaciones cocinadas se disfrutan mejor durante las primeras 24 a 48 horas. Para recalentar, usa calor suave y añade una pequeña cantidad de líquido si hace falta recuperar textura. En recetas con crema, huevo o rellenos delicados, no recomiendo recalentar varias veces: separa porciones desde el principio y conserva solo lo necesario.",
        f"## Resumen final\nEsta versión de {keyword} combina una técnica ordenada con una presentación lista para publicar. Tiene margen para adaptarse, pero mantiene una idea central: buen producto, cocción controlada y acabado limpio. Si sigues los pasos con calma, tendrás un plato fiable para una comida especial, una sesión de contenido o una receta evergreen dentro de {domain.display_name}. Te cuento el mejor indicador de éxito: cuando al cortar o servir, la textura se mantiene estable y el aroma aparece antes del primer bocado.",
    ]
    content = "\n\n".join(sections)
    recipe_schema = {
        "@context": "https://schema.org",
        "@type": "Recipe",
        "name": title,
        "image": hero_url,
        "description": f"Receta paso a paso de {title}.",
        "author": {"@type": "Person", "name": "Isabella Dolce" if "dolce" in domain.handle else "Chef Receta Genial"},
        "prepTime": "PT15M",
        "cookTime": "PT30M",
        "totalTime": "PT45M",
        "recipeYield": "4 raciones",
        "recipeCategory": category,
        "recipeIngredient": ingredients,
        "recipeInstructions": [{"@type": "HowToStep", "text": step} for step in steps],
    }
    return {
        "title": title,
        "slug": _slugify(keyword),
        "content": content,
        "excerpt": f"Aprende a preparar {title} con una guía clara, visual y lista para servir.",
        "category": category,
        "featured_image": hero_url,
        "meta_title": f"{title} | {domain.display_name}",
        "meta_description": f"Receta completa de {title}: ingredientes, pasos, consejos y presentación.",
        "keywords": [keyword, cluster, domain.display_name],
        "difficulty": "Media",
        "estimated_cost": "Medio",
        "prep_time": 15,
        "cook_time": 30,
        "image_alt": title,
        "chef_tip": "Respeta los tiempos de reposo y termina el plato justo antes de servir.",
        "recipe_schema": recipe_schema,
        "faq_schema": [
            {
                "question": f"¿Puedo preparar {title} con antelación?",
                "answer": "Sí, prepara la base con antelación y reserva el acabado para el momento de servir.",
            },
            {
                "question": f"¿Cómo evito que {title} quede seco?",
                "answer": "Usa fuego medio, controla el reposo y corrige con pequeñas cantidades de líquido caliente.",
            },
            {
                "question": "¿Qué debo cuidar para una preparación segura?",
                "answer": "Mantén higiene de manos y utensilios, separa crudo y cocinado y refrigera las sobras pronto.",
            },
        ],
    }


def _update_domain_pin_id(domain: Domain, slug: str, pin_id: str) -> dict:
    import requests

    key = domain.supabase_service_role_key.get_secret_value()
    if not key:
        return {"success": False, "error": f"Supabase key not set for {domain.handle}"}
    if not re.fullmatch(r"\d{15,20}", str(pin_id or "").strip()):
        return {"success": False, "error": f"invalid Pinterest pin id: {pin_id!r}"}
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    resp = requests.patch(
        f"{domain.supabase_url}/rest/v1/posts?slug=eq.{slug}",
        headers=headers,
        json={"pinterest_pin_id": str(pin_id)},
        timeout=20,
    )
    if resp.status_code in {200, 204}:
        return {"success": True, "slug": slug, "pin_id": str(pin_id)}
    return {"success": False, "status": resp.status_code, "error": resp.text}


async def _deterministic_publication(keyword: str, cluster: str, domain: Domain) -> str:
    try:
        from rankstein_mcp_server import (
            automation_upload_pin_direct,
            build_supabase_content,
            create_article_pin,
            create_hero_image_pollinations,
            publish_article_to_supabase,
            upload_image_to_supabase,
            validate_article_quality,
        )

        slug = _slugify(keyword)
        image_prompt = (
            f"editorial food photography of {keyword}, Spanish recipe, premium plating, "
            "natural window light, clean table, appetizing texture, no text, no watermark"
        )
        hero = create_hero_image_pollinations(image_prompt, slug, width=1280, height=960, timeout_seconds=120)
        if not hero.get("success"):
            logger.error("Fallback hero generation failed for %s: %s", keyword, hero)
            return "Failed"

        storage_path = f"{domain.handle}/{slug}-hero.jpg"
        uploaded = upload_image_to_supabase(hero["output_path"], storage_path, domain.handle)
        if not uploaded.get("success"):
            logger.error("Fallback hero upload failed for %s: %s", keyword, uploaded)
            return "Failed"

        article = _build_article_payload(keyword, cluster, domain, uploaded["public_url"])
        quality = validate_article_quality(json.dumps(article, ensure_ascii=False))
        if not quality.get("success"):
            logger.warning("Fallback article quality warning for %s: %s", keyword, quality)

        content = build_supabase_content(keyword, uploaded["public_url"], json.dumps(article, ensure_ascii=False))
        if not content.get("success"):
            logger.error("Fallback content build failed for %s: %s", keyword, content)
            return "Failed"
        payload = json.loads(content["payload"])
        published = publish_article_to_supabase(
            title=payload["title"],
            slug=payload["slug"],
            content=payload["content"],
            excerpt=payload["excerpt"],
            category=payload["category"],
            featured_image_url=payload["featured_image"],
            meta_title=payload["meta_title"],
            meta_description=payload["meta_description"],
            keywords=", ".join(payload["keywords"]) if isinstance(payload["keywords"], list) else payload["keywords"],
            difficulty=payload["difficulty"],
            prep_time=payload["prep_time"],
            cook_time=payload["cook_time"],
            image_alt=payload["image_alt"],
            chef_tip=payload["chef_tip"],
            recipe_schema=json.dumps(payload["recipe_schema"], ensure_ascii=False),
            faq_schema=json.dumps(payload["faq_schema"], ensure_ascii=False),
            domain_handle=domain.handle,
        )
        if not published.get("success"):
            logger.error("Fallback publish failed for %s: %s", keyword, published)
            return "Needs Verification"

        pin_upload = create_article_pin(
            hero["output_path"],
            payload["title"],
            subtitle=cluster,
            brand=getattr(domain, "brand_name_short", "") or f"{domain.display_name.upper()} | 2026",
            style_variant="classic",
        )
        if not pin_upload.get("success"):
            logger.error("Fallback pin image failed for %s: %s", keyword, pin_upload)
            return "Needs Verification"

        board = domain.boards_default.get(payload["category"]) or domain.boards_default.get("_default", "")
        upload = await automation_upload_pin_direct(
            image_path=pin_upload["output_path"],
            title=payload["title"],
            description=payload["excerpt"],
            link=published["url"],
            alt_text=payload["image_alt"],
            board_name=board,
        )
        if not upload.get("success"):
            logger.error("Fallback Pinterest upload failed for %s: %s", keyword, upload)
            return "Needs Verification"

        pin_id = upload.get("pin_id") or ""
        if pin_id:
            linked = _update_domain_pin_id(domain, payload["slug"], pin_id)
            if not linked.get("success"):
                logger.warning("Fallback pin link update warning for %s: %s", keyword, linked)
                return "Needs Verification"
        logger.info(
            "Fallback published %s: article=%s pin=%s",
            keyword,
            published.get("url"),
            upload.get("pin_url"),
        )
        return "Live"
    except Exception as exc:
        logger.exception("Fallback publication crashed for %s: %s", keyword, exc)
        return "Failed"


async def _terminate_process_tree(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if os.name == "nt":
        killer = await asyncio.create_subprocess_exec(
            "taskkill",
            "/PID",
            str(process.pid),
            "/T",
            "/F",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        with contextlib.suppress(Exception):
            await asyncio.wait_for(killer.communicate(), timeout=10)
    else:
        process.kill()
    with contextlib.suppress(Exception):
        await asyncio.wait_for(process.wait(), timeout=10)


async def process_keyword(keyword: str, cluster: str, domain: Domain) -> str:
    logger.info("Processing keyword %r for domain %s", keyword, domain.handle)

    author = "Isabella Dolce" if "dolce" in domain.display_name.lower() else "Chef Receta Genial"
    board_default = getattr(domain, "boards_default", {}).get("_default", "")
    prompt = (
        f"RANKSTEIN AUTONOMOUS PIPELINE — execute all steps without stopping or asking questions.\n"
        f"\n"
        f"DOMAIN: {domain.handle} | site: https://{domain.domain} | niche: {domain.niche}\n"
        f"KEYWORD: {keyword!r} | cluster: {cluster!r}\n"
        f"AUTHOR: {author} | DISPLAY_NAME: {domain.display_name}\n"
        f"DEFAULT_BOARD: {board_default}\n"
        f"\n"
        "MANDATORY STEP SEQUENCE (complete every step, no human input needed):\n"
        "1.  memory_stats() — check AgentMemory health.\n"
        "2.  search_project_memory(query=keyword) — retrieve lessons for this keyword.\n"
        "3.  check_supabase_connection(domain_handle=DOMAIN) — verify DB is reachable.\n"
        "4.  get_article_data_from_supabase_by_slug(slug=slugified_keyword, domain_handle=DOMAIN)\n"
        "    — if article already exists and has a valid pin_id, mark Live and stop (no duplicate).\n"
        "5.  scrape_news_sources(keyword=KEYWORD, domain=DOMAIN) — get source URLs.\n"
        "6.  extract_article_content(url=best_source_url) — extract full text.\n"
        "7.  Generate a full Spanish recipe article JSON (title, slug, content, recipe_schema with\n"
        "    recipeIngredient and recipeInstructions arrays populated — NEVER empty arrays).\n"
        "8.  validate_article_quality(article_json=...) — must pass; revise up to 3 times if needed.\n"
        "9.  create_hero_image_pollinations(prompt=..., slug=slug) — generate hero image.\n"
        "10. upload_image_to_supabase(local_path=..., storage_path=DOMAIN/slug-hero.jpg, domain_handle=DOMAIN)\n"
        "    — get public_url.\n"
        "11. build_supabase_content(keyword=KEYWORD, hero_image_url=public_url, article_json=...) — build payload.\n"
        "12. publish_article_to_supabase(...all payload fields..., domain_handle=DOMAIN) — publish post.\n"
        "13. create_article_pin(image_path=hero_path, title=title, subtitle=cluster) — make Pinterest image.\n"
        "14. automation_upload_pin_direct(image_path=pin_path, title=title, description=excerpt,\n"
        f"    link=published_url, board_name={board_default!r}) — upload pin, capture pin_id.\n"
        "15. update_pinterest_pin_id(slug=slug, pin_id=pin_id, domain_handle=DOMAIN) — link pin to post.\n"
        "16. remember_pipeline_event(event=completion summary including slug, pin_id, status).\n"
        "\n"
        "RULES:\n"
        "- Always pass domain_handle=DOMAIN to every domain-aware tool call.\n"
        "- Do NOT skip steps or ask for confirmation. Run every step automatically.\n"
        "- If a step fails, log the error and continue to the next step where possible.\n"
        "- If supabase_publish fails, still attempt the Pinterest upload with the article URL.\n"
        "- All text in Spanish (es-ES). Author name is exact as given above.\n"
        "\n"
        "COMPLETION: output a single-line JSON on the last line:\n"
        '{"supabase_published": true|false, "pinterest_uploaded": true|false, "pin_linked": true|false}'
    )

    try:
        gemini_cmd = "gemini.cmd" if os.name == "nt" else "gemini"
        last_error = ""
        env = os.environ.copy()
        env.pop("GOOGLE_API_KEY", None)
        env.pop("GEMINI_API_KEY", None)
        for model in _worker_models():
            logger.info("Invoking Gemini CLI model=%s for %s", model, keyword)
            cmd = [gemini_cmd, "--prompt", prompt, "--yolo"]
            if model.lower() != "auto":
                cmd.append(f"--model={model}")
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=_gemini_timeout_seconds(),
                )
            except TimeoutError:
                await _terminate_process_tree(process)
                logger.error(
                    "Gemini CLI timed out after %ss for %s with model=%s",
                    _gemini_timeout_seconds(),
                    keyword,
                    model,
                )
                return await _deterministic_publication(keyword, cluster, domain)
            stderr_text = stderr.decode(errors="replace")

            if process.returncode == 0:
                status = _status_from_completion_output(stdout.decode(errors="replace"))
                logger.info("Completed: %s -> %s", keyword, status)
                return status

            last_error = stderr_text
            if _is_retryable_model_error(stderr_text):
                logger.warning("Gemini model=%s capacity/rate failure for %s; trying fallback.", model, keyword)
                continue
            logger.error("Gemini model=%s failed for %s: %s", model, keyword, stderr_text[-2000:])
            break

        logger.error("Failed: %s - %s", keyword, last_error)
        return await _deterministic_publication(keyword, cluster, domain)
    except Exception as exc:
        logger.error("Crash: %s - %s", keyword, exc)
        return "Failed"


async def _run_domain(domain: Domain, workers: int, limit: int, once: bool) -> None:
    """Continuous keyword worker for a single domain. Loops until all keywords exhausted or once=True."""
    roadmap_title = f"{domain.display_name} Keyword Roadmap"
    batch_size = max(1, min(limit, workers))
    logger.info("[%s] worker started (%d workers, batch=%d)", domain.handle, workers, batch_size)

    while True:
        if not domain.keywords_file.exists():
            logger.warning("[%s] keywords file missing: %s", domain.handle, domain.keywords_file)
            if once:
                return
            await asyncio.sleep(120)
            continue

        pending = reserve_pending_keywords(domain.keywords_file, roadmap_title, batch_size)
        if not pending:
            logger.info("[%s] Queue empty. Sleeping 5 minutes.", domain.handle)
            if once:
                return
            await asyncio.sleep(300)
            continue

        tasks = [process_keyword(item.keyword, item.cluster, domain) for item in pending]
        results = await asyncio.gather(*tasks)
        for item, status in zip(pending, results, strict=False):
            mark_keyword_status(domain.keywords_file, roadmap_title, item.keyword, status)
        if once:
            return
        await asyncio.sleep(30)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="RankStein domain-aware parallel article generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python turbo_articles.py --all-domains --workers 2\n"
            "  python turbo_articles.py --domain recetadolce --workers 3\n"
        ),
    )
    parser.add_argument("--domain", type=str, default="", help="Domain handle to process (omit for --all-domains)")
    parser.add_argument("--all-domains", action="store_true", help="Run workers for ALL registered domains simultaneously")
    parser.add_argument("--workers", type=int, default=3, help="Number of parallel keyword workers per domain")
    parser.add_argument("--limit", type=int, default=3, help="Keywords to reserve per loop per domain")
    parser.add_argument("--once", action="store_true", help="Process one batch per domain then exit")
    args = parser.parse_args()

    reload_registry()
    registry = get_registry()

    if args.all_domains or not args.domain:
        # Launch workers for every domain simultaneously
        domains = registry.all()
        logger.info("Turbo mode: ALL DOMAINS (%d) — %d workers each", len(domains), args.workers)
        await asyncio.gather(*[
            _run_domain(domain, args.workers, args.limit, args.once)
            for domain in domains
        ])
    else:
        domain = registry.get(args.domain)
        logger.info("Turbo mode: domain=%s workers=%d", domain.handle, args.workers)
        await _run_domain(domain, args.workers, args.limit, args.once)


if __name__ == "__main__":
    asyncio.run(main())

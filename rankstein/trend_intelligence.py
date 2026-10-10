"""Daily multi-source keyword intelligence for RankStein domains.

Pinterest Trends/Search, Google News discovery, Google Trends RSS, and Google
autocomplete can independently contribute domain-aware candidates. Precise
recipe phrases are still validated against independent Google demand before a
keyword can enter a roadmap or authorize article production.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
import urllib.parse
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from defusedxml import ElementTree as ET

from rankstein.category_policy import CategoryPolicyError
from rankstein.domain import Domain
from rankstein.keyword_roadmap import (
    KeywordRow,
    append_keyword_rows,
    read_keyword_rows,
)
from rankstein.prompts import is_recipe_aware_keyword

logger = logging.getLogger("rankstein.trends")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_REGION = "ES"
DEFAULT_LANGUAGE = "es"
PINTEREST_TRENDS_URL = "https://trends.pinterest.com/"
DISCOVERY_SOURCES = frozenset(
    {
        "Pinterest Trends",
        "Google News",
        "Google Trends",
        "Google Suggestions",
    }
)

NOISE_TERMS = {
    "pinterest",
    "trends",
    "explore",
    "login",
    "sign up",
    "business",
    "privacy",
    "cookies",
    "home",
}

_PINTEREST_UI_NOISE = {
    "buscar",
    "eliminar texto de la busqueda",
    "explorar",
    "iniciar sesion",
    "registrarse",
    "mostrar filtros",
    "menos ia",
    "recetas de",
    "saltar al contenido",
    "configuracion",
    "tendencias",
    "pinterest trends",
}

_LOW_QUALITY_PINTEREST_GUIDES = {
    "aesthetic",
    "como hacer",
    "decoracion",
    "decorada",
    "decoradas",
    "dibujo",
    "facil",
    "mejor",
    "para perro",
    "para perros",
    "receta",
    "recipe",
}


@dataclass(frozen=True)
class NewsSignal:
    title: str
    source: str = ""
    published: str = ""


@dataclass(frozen=True)
class TrendCandidate:
    keyword: str
    domain: str
    cluster: str
    priority: str
    score: float
    pinterest_score: float
    google_news_hits: int
    google_news_titles: list[str]
    source: str
    specificity_score: float = 0.0
    # Legacy output field retained for existing report consumers. This is a
    # normalized demand proxy, not literal monthly search volume.
    search_volume_score: float = 0.0
    search_demand_score: float = 0.0
    search_demand_source: str = ""
    pinterest_origin: bool = True
    qualified: bool = True


# ───────────────────────────────────────────────────────────────────────────
# Keyword quality gate — dish noun + concrete qualifier required
# ───────────────────────────────────────────────────────────────────────────
# A precise recipe keyword names an actual dish plus a qualifier (ingredient,
# style, origin, occasion, technique). Vague category+modifier phrases such as
# "aperitivos faciles y rapidos" or "postres ideas para vender" fail this gate
# because scrapers cannot find real recipe sources for them.
_DISH_SUBSTRINGS = {
    "tarta",
    "pastel",
    "galleta",
    "bizcocho",
    "flan",
    "mousse",
    "brownie",
    "cupcake",
    "macaron",
    "croqueta",
    "tortilla",
    "paella",
    "ensalada",
    "sopa",
    "helado",
    "natillas",
    "torrijas",
    "churros",
    "empanada",
    "empanadilla",
    "lasaña",
    "canelones",
    "pizza",
    "magdalena",
    "milhojas",
    "tatin",
    "cheesecake",
    "coulant",
    "trufa",
    "tiramisu",
    "panna cotta",
    "arroz con leche",
    "tres leches",
    "gazpacho",
    "salmorejo",
    "fabada",
    "cocido",
    "callos",
    "pulpo",
    "calamares",
    "boquerones",
    "canape",
    "tosta",
    "pincho",
    "quiche",
    "risotto",
    "carbonara",
    "merengue",
    "pavlova",
    "eclair",
    "profiteroles",
    "clafoutis",
    "crumble",
    "cobbler",
    "fondant",
    "souffle",
    "crepes",
    "crepa",
    "gofres",
    "carpaccio",
    "pollo",
    "carne",
    "ternera",
    "cerdo",
    "cordero",
    "pescado",
    "salmon",
    "atun",
    "merluza",
    "bacalao",
    "lubina",
    "dorada",
    "gambas",
    "langostinos",
    "arroz",
    "pasta",
    "pan ",
    "brownies",
    "donut",
    "rosquilla",
    "berlina",
}

# Tokens that never make a keyword specific on their own.
# NOTE: "casera/casero" (homemade) IS a real qualifier ("galletas caseras"
# is a high-demand search) and is intentionally NOT in this set.
_GENERIC_MODIFIER_TOKENS = {
    "ideas",
    "idea",
    "virales",
    "viral",
    "faciles",
    "facil",
    "rapidas",
    "rapido",
    "irresistible",
    "irresistibles",
    "mejores",
    "mejor",
    "perfecta",
    "perfecto",
    "bonitos",
    "bonitas",
    "aesthetic",
    "deliciosas",
    "deliciosos",
    "deliciosa",
    "delicioso",
    "recetas",
    "receta",
    "sencillas",
    "sencillos",
    "economicas",
    "economicos",
    "economica",
    "economico",
    "originales",
    "original",
    "super",
    "muy",
    "mas",
    "san",
    "para",
    "con",
    "sin",
    "los",
    "las",
    "una",
    "unos",
    "unas",
    "del",
    "como",
    "hacer",
    "minutos",
    "casa",
    "hoy",
    "siempre",
    "mundo",
    "gente",
    "fiesta",
    "fiestas",
    "navidad",
    "navidenos",
    "navidenas",
    "vender",
}

# Category-only nouns — a keyword made ONLY of these + generic modifiers is vague.
_CATEGORY_ONLY_TOKENS = {
    "postres",
    "postre",
    "aperitivos",
    "aperitivo",
    "comida",
    "cena",
    "cenas",
    "cocina",
    "recetas",
    "receta",
    "pasteles",
    "galletas",
    "tartas",
    "dulces",
    "dulce",
    "salado",
    "salados",
    "bebidas",
    "desayunos",
    "meriendas",
    "tapas",
    "snacks",
}

# Multiword dish names that qualify on their own even though each token is common.
_MULTIWORD_DISHES = {
    "arroz con leche",
    "tres leches",
    "panna cotta",
    "crema catalana",
    "pan de muerto",
    "leche frita",
    "huevos rotos",
    "patatas bravas",
    "tortilla espanola",
    "pulpo a la gallega",
    "gambas al ajillo",
}

# Audience-only qualifiers do NOT make a keyword specific ("pasteles para mujer").
_AUDIENCE_TOKENS = {
    "mujer",
    "mujeres",
    "hombre",
    "hombres",
    "nino",
    "nina",
    "ninos",
    "ninas",
    "adultos",
    "invitados",
    "familia",
    "amigos",
    "pareja",
}


# Imported dish names are culinary vocabulary, not foreign-language noise.
_NAMED_IMPORTED_DISHES = {
    "panna cotta",
    "arroz con leche",
    "tres leches",
    "carrot cake",
    "red velvet",
    "new york cheesecake",
    "creme brulee",
    "crema catalana",
    "pasta carbonara",
}
_PET_TOKENS = {
    "gato",
    "gatos",
    "perro",
    "perros",
    "mascota",
    "mascotas",
    "cachorro",
    "cachorros",
    "felino",
    "felinos",
    "canino",
    "caninos",
    "cat",
    "cats",
    "dog",
    "dogs",
    "pet",
    "pets",
}
_FOREIGN_RECIPE_TOKENS = {
    "fazer",
    "receita",
    "receitas",
    "bolo",
    "bolos",
    "caseiro",
    "caseira",
    "caseiros",
    "caseiras",
    "saudavel",
    "saudaveis",
    "recheio",
    "frango",
    "morango",
    "forno",
    "gostoso",
    "gostosa",
    "recipe",
    "recipes",
    "how",
    "make",
    "homemade",
    "easy",
    "with",
    "without",
    "chicken",
    "creamy",
    "fluffy",
    "best",
    "recette",
    "recettes",
    "gateau",
    "avec",
    "pour",
    "facile",
    "ricetta",
    "ricette",
    "fatto",
}
_NON_RECIPE_TOKENS = {
    "decoracion",
    "decoraciones",
    "decorado",
    "decorada",
    "decorados",
    "decoradas",
    "dibujo",
    "dibujos",
    "imagen",
    "imagenes",
    "foto",
    "fotos",
    "plantilla",
    "plantillas",
    "invitacion",
    "invitaciones",
    "aesthetic",
    "disfraz",
    "tatuaje",
    "wallpaper",
}
# Only recognized culinary qualifiers count. Plurals of dish nouns and random
# guide fragments must not masquerade as ingredient/style evidence.
_CONCRETE_QUALIFIERS = set(
    "queso chocolate cacao cafe vainilla limon naranja mandarina manzana pera platano banana "
    "zanahoria coco almendra almendras avellana avellanas nuez nueces pistacho pistachos "
    "fresa fresas frambuesa frambuesas arandano arandanos mora moras cereza cerezas "
    "melocoton mango maracuya nata leche yogur yogurt mantequilla huevo huevos miel "
    "avena harina maiz trigo arroz garbanzo garbanzos lenteja lentejas patata patatas "
    "calabaza calabacin berenjena espinacas tomate tomates cebolla ajo ajillo puerro "
    "brocoli champinon champinones setas guisantes verduras pimiento pimientos jamon "
    "pollo ternera cerdo cordero atun salmon merluza bacalao gambas langostinos marisco "
    "sepia calamar calamares chorizo bacon tofu canela jengibre curry azafran romero "
    "albahaca pesto bechamel hojaldre masa fermentacion integral vegano vegana veganos "
    "veganas proteico proteica proteicos proteicas saludable saludables azucar gluten "
    "lactosa casero casera caseros caseras tradicional tradicionales clasico clasica "
    "clasicos clasicas vasco vasca vasco vasca valenciano valenciana asturiano asturiana "
    "gallega gallego andaluz andaluza catalana catalan italiana italiano mexicano mexicana "
    "horno vapor parrilla brasa frito frita fritos fritas asado asada asados asadas "
    "guisado guisada relleno rellena rellenos rellenas gratinado gratinada freidora "
    "air fryer frio fria frios frias cremosa cremoso cremosas cremosos crujiente crujientes "
    "esponjoso esponjosa esponjosos esponjosas philadelphia lotus nutella oreo opera "
    "navidad cumpleanos pascua navideno navidena navidenos navidenas pascua cuaresma".split()
)
_DISH_PATTERN = re.compile(
    r"\b(?:"
    + "|".join(
        re.escape(_folded) + (r"(?:s|es)?" if " " not in _folded else "")
        for dish in sorted(_DISH_SUBSTRINGS, key=len, reverse=True)
        if (
            _folded := __import__("unicodedata")
            .normalize("NFKD", dish.strip())
            .encode("ascii", "ignore")
            .decode("ascii")
        )
    )
    + r")\b"
)


def _fold(text: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKD", text or "")
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


def _has_spanish_human_recipe_intent(keyword: str) -> bool:
    folded = _fold(keyword).strip()
    if not folded or len(folded.split()) > 8 or _is_pinterest_ui_noise(keyword):
        return False
    if any(char.isalpha() and not _fold(char) for char in keyword):
        return False
    tokens = set(re.findall(r"[a-z]+", folded))
    if tokens & (_PET_TOKENS | _NON_RECIPE_TOKENS):
        return False
    if re.search(r"\bpara\s+(?:(?:un|una|el|la)\s+)?(?:hombres?|mujeres?)\b", folded):
        return False
    if re.search(r"\b(?:para hacer|paso a paso)$", folded):
        return False
    language_text = folded
    for dish in _NAMED_IMPORTED_DISHES:
        language_text = re.sub(r"\b" + re.escape(dish) + r"\b", "", language_text)
    return not (set(re.findall(r"[a-z]+", language_text)) & _FOREIGN_RECIPE_TOKENS)


def _keyword_specificity_score(keyword: str) -> float:
    """Score how precise a recipe keyword is. 0 = reject as vague.

    Requires:
      1. A concrete dish noun (tarta, galletas, croquetas, salmón, ...), and
      2. At least one concrete qualifier (ingredient/style/origin/occasion/
         technique) that is not a generic modifier, category noun, or
         audience-only word.

    Multiword dishes ("arroz con leche", "panna cotta") qualify on their own.
    Returns 2.0 + min(3, concrete_qualifiers) for accepted keywords, else 0.
    """
    folded = _fold(keyword).strip()
    if not _has_spanish_human_recipe_intent(keyword):
        return 0.0
    if any(
        re.search(r"\b" + re.escape(dish) + r"\b", folded)
        for dish in _MULTIWORD_DISHES | _NAMED_IMPORTED_DISHES
    ):
        return 3.0
    if not _DISH_PATTERN.search(folded):
        return 0.0
    dish = _DISH_PATTERN.search(folded)
    # Keep ingredient names after the first dish noun (croquetas de pollo),
    # but never count that noun itself (pollo facil, croquetas recetas).
    remaining = folded[: dish.start()] + " " + folded[dish.end() :]
    qualifiers = set(re.findall(r"[a-z]+", remaining)) & _CONCRETE_QUALIFIERS
    if not qualifiers:
        return 0.0
    return 2.0 + min(3.0, float(len(qualifiers)))


def qualify_recipe_keyword(domain: Domain, keyword: str) -> tuple[float, str]:
    """Apply today's recipe intent, specificity and category policy without I/O.

    An empty cluster means rejected. Stored ``qualified`` flags and specificity
    scores cannot bypass this gate at discovery, evidence loading or reservation.
    """
    specificity = _keyword_specificity_score(keyword)
    if specificity <= 0 or _is_generic_domain_seed(domain, keyword):
        return 0.0, ""
    try:
        cluster = _cluster_for_keyword(domain, keyword)
    except CategoryPolicyError:
        return 0.0, ""
    return specificity, cluster


def _search_volume_proxy(keyword: str, language: str, region: str) -> float:
    """Estimate relative search demand via Google autocomplete depth.

    This is intentionally reported as a demand score, never as monthly search
    volume. Google Trends values are normalized 0-100 relative interest, while
    true average monthly searches require Google Ads historical metrics:
    https://support.google.com/trends/answer/4365533
    https://developers.google.com/google-ads/api/docs/keyword-planning/generate-historical-metrics

    Score: 2 points per suggestion, capped at 20.
    """
    del region
    try:
        response = requests.get(
            "https://suggestqueries.google.com/complete/search",
            headers={"User-Agent": USER_AGENT},
            params={"client": "firefox", "hl": language, "q": keyword},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        suggestions = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
        return min(20.0, len(suggestions) * 2.0)
    except Exception as exc:
        logger.debug("Autocomplete volume proxy failed for %r: %s", keyword, exc)
        return 0.0


GoogleNewsProvider = Callable[[str, str, str, int], list[NewsSignal]]
KeywordDiscoveryProvider = Callable[[Domain, str, str, int], list[str]]
SearchVolumeProvider = Callable[[str, str, str], float]


def _minimum_search_demand_score() -> float:
    """Return the fail-closed minimum independent demand score."""

    try:
        configured = float(os.environ.get("RANKSTEIN_MIN_SEARCH_DEMAND_SCORE", "2"))
    except ValueError:
        configured = 2.0
    return max(0.1, configured)


def refresh_domain_trend_lists(
    domains: list[Domain],
    *,
    limit_per_domain: int = 10,
    region: str | None = None,
    language: str | None = None,
    append_to_roadmap: bool = True,
    pinterest_terms: list[str] | None = None,
    google_news_provider: GoogleNewsProvider | None = None,
    search_volume_provider: SearchVolumeProvider | None = None,
    google_news_discovery_provider: KeywordDiscoveryProvider | None = None,
    google_trends_provider: KeywordDiscoveryProvider | None = None,
    google_suggest_provider: KeywordDiscoveryProvider | None = None,
    use_playwright: bool = True,
    candidate_origin_policy: str = "multi_source",
) -> dict[str, object]:
    """Create fresh externally validated keyword shortlists for each domain.

    ``multi_source`` lets each discovery provider contribute candidates.
    ``pinterest_required`` admits only phrases observed on Pinterest; Google
    discovery may corroborate the exact phrase but cannot inject a candidate.
    Every admitted candidate must still pass specificity and demand gates.

    Returns a machine-readable report and writes:
    - ``data/domains/<handle>/daily_best_keywords.json``
    - ``data/domains/<handle>/daily_best_keywords.md``
    """

    region = (region or os.environ.get("RANKSTEIN_TRENDS_REGION") or DEFAULT_REGION).upper()
    language = (language or os.environ.get("RANKSTEIN_TRENDS_LANGUAGE") or DEFAULT_LANGUAGE).lower()
    limit_per_domain = max(1, limit_per_domain)
    candidate_origin_policy = candidate_origin_policy.strip().casefold()
    if candidate_origin_policy not in {"multi_source", "pinterest_required"}:
        raise ValueError("candidate_origin_policy must be 'multi_source' or 'pinterest_required'")
    google_news_provider = google_news_provider or fetch_google_news_signals
    search_volume_provider = search_volume_provider or _search_volume_proxy
    if candidate_origin_policy == "multi_source":
        google_news_discovery_provider = google_news_discovery_provider or fetch_google_news_discovery_terms
        google_trends_provider = google_trends_provider or fetch_google_trending_terms
        google_suggest_provider = google_suggest_provider or fetch_google_autocomplete_terms
    generated_at = datetime.now(UTC).isoformat()
    report: dict[str, object] = {
        "generated_at": generated_at,
        "region": region,
        "language": language,
        "collector": (
            "pinterest_first_keyword_research"
            if candidate_origin_policy == "pinterest_required"
            else "multi_source_keyword_research"
        ),
        "pinterest_collector": ("playwright_pinterest_trends" if use_playwright else "http_fallback"),
        "candidate_origin_policy": candidate_origin_policy,
        "domains": {},
    }

    for domain in domains:
        source_terms: dict[str, list[str]] = {}
        try:
            if pinterest_terms is not None:
                raw_terms = list(pinterest_terms)
            elif use_playwright:
                raw_terms = fetch_pinterest_niche_trending_terms(
                    domain,
                    region=region,
                    limit=limit_per_domain * (4 if candidate_origin_policy == "pinterest_required" else 8),
                )
            else:
                raw_terms = fetch_pinterest_trending_terms(
                    region,
                    limit=limit_per_domain * (4 if candidate_origin_policy == "pinterest_required" else 8),
                )
        except Exception as exc:
            logger.warning(
                "Pinterest keyword discovery failed for %s: %s",
                domain.handle,
                exc,
            )
            raw_terms = []
        source_terms["Pinterest Trends"] = raw_terms

        supplemental_providers = (
            ("Google News", google_news_discovery_provider),
            ("Google Trends", google_trends_provider),
            ("Google Suggestions", google_suggest_provider),
        )
        for source_name, provider in supplemental_providers:
            if provider is None:
                continue
            try:
                source_terms[source_name] = list(
                    provider(
                        domain,
                        language,
                        region,
                        limit_per_domain * 4,
                    )
                    or []
                )
            except Exception as exc:
                logger.warning(
                    "%s keyword discovery failed for %s: %s",
                    source_name,
                    domain.handle,
                    exc,
                )
                source_terms[source_name] = []

        if candidate_origin_policy == "pinterest_required":
            normalized_terms = _dedupe_terms(raw_terms)
            pinterest_keys = {term.casefold() for term in normalized_terms}
            term_sources: dict[str, set[str]] = {
                term.casefold(): {"Pinterest Trends"} for term in normalized_terms
            }
            for source_name, terms in source_terms.items():
                if source_name == "Pinterest Trends":
                    continue
                for term in _dedupe_terms(terms):
                    key = term.casefold()
                    if key in pinterest_keys:
                        term_sources[key].add(source_name)
        else:
            normalized_terms, term_sources = _merge_discovery_terms(source_terms)

        existing_rows = read_keyword_rows(domain.keywords_file)
        excluded_keywords = {
            row.keyword.casefold()
            for row in existing_rows
            if row.status.strip().casefold() in {"live", "in progress"}
        }
        candidates = rank_terms_for_domain(
            domain,
            normalized_terms,
            limit=limit_per_domain,
            region=region,
            language=language,
            google_news_provider=google_news_provider,
            search_volume_provider=search_volume_provider,
            term_sources=term_sources,
            excluded_keywords=excluded_keywords,
        )
        write_daily_best_list(
            domain,
            candidates,
            generated_at,
            candidate_origin_policy=candidate_origin_policy,
        )
        added = 0
        if append_to_roadmap:
            title = f"{domain.display_name} Keyword Roadmap"
            added = append_keyword_rows(
                domain.keywords_file,
                title,
                [
                    KeywordRow(
                        keyword=item.keyword,
                        cluster=item.cluster,
                        source=item.source,
                        target_blog=domain.display_name,
                        priority=item.priority,
                        status="Pending",
                    )
                    for item in candidates
                ],
            )
        report["domains"][domain.handle] = {
            "pinterest_terms_found": len(raw_terms),
            "discovery_terms_found": len(normalized_terms),
            "terms_considered": len(normalized_terms),
            "sources": {
                source_name: len(_dedupe_terms(terms)) for source_name, terms in source_terms.items()
            },
            "daily_best": [asdict(item) for item in candidates],
            "candidate_origin_policy": candidate_origin_policy,
            "research_status": (
                "qualified"
                if candidates
                else "blocked_no_pinterest_terms"
                if candidate_origin_policy == "pinterest_required" and not normalized_terms
                else "blocked_no_discovery_terms"
                if not normalized_terms
                else "blocked_no_qualified_keywords"
            ),
            "roadmap_added": added,
            "output_json": str(domain.root / "daily_best_keywords.json"),
            "output_md": str(domain.root / "daily_best_keywords.md"),
        }

    return report


def _merge_discovery_terms(
    source_terms: dict[str, list[str]],
) -> tuple[list[str], dict[str, set[str]]]:
    """Round-robin source results and retain provenance for every candidate."""

    normalized_by_source = {source: _dedupe_terms(terms) for source, terms in source_terms.items() if terms}
    merged: list[str] = []
    seen: set[str] = set()
    sources_by_keyword: dict[str, set[str]] = {}
    max_terms = max((len(terms) for terms in normalized_by_source.values()), default=0)
    for index in range(max_terms):
        for source, terms in normalized_by_source.items():
            if index >= len(terms):
                continue
            keyword = terms[index]
            key = keyword.casefold()
            sources_by_keyword.setdefault(key, set()).add(source)
            if key in seen:
                continue
            seen.add(key)
            merged.append(keyword)
    return merged, sources_by_keyword


def fetch_pinterest_niche_trending_terms(
    domain: Domain,
    *,
    region: str = DEFAULT_REGION,
    limit: int = 80,
) -> list[str]:
    """Use Playwright to open Pinterest Trends/Search for domain-specific niche queries."""

    try:
        return _run_playwright_collector(domain, region, limit)
    except Exception as exc:
        logger.warning("Playwright Pinterest trend collection failed for %s: %s", domain.handle, exc)
        return fetch_pinterest_trending_terms(region, limit=limit)


def _run_playwright_collector(domain: Domain, region: str, limit: int) -> list[str]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_fetch_pinterest_niche_trending_terms_async(domain, region, limit))

    result: list[str] = []
    error: Exception | None = None

    def runner() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(_fetch_pinterest_niche_trending_terms_async(domain, region, limit))
        except Exception as exc:  # pragma: no cover - defensive thread handoff
            error = exc

    thread = threading.Thread(target=runner, name="rankstein-pinterest-trends", daemon=True)
    thread.start()
    thread.join()
    if error is not None:
        raise error
    return result


def _trend_browser_profile(domain: Domain) -> tuple[str, Path]:
    """Resolve an isolated profile for unattended Pinterest trend collection."""

    browser_type = os.environ.get("RANKSTEIN_TRENDS_BROWSER", "chromium").strip().casefold()
    if browser_type not in {"chromium", "firefox"}:
        logger.warning(
            "Unsupported RANKSTEIN_TRENDS_BROWSER=%r; using chromium.",
            browser_type,
        )
        browser_type = "chromium"

    sessions_dir = domain.sessions_dir
    if not sessions_dir.is_absolute():
        sessions_dir = PROJECT_ROOT / sessions_dir
    return browser_type, sessions_dir / "trend-profiles" / browser_type


async def _fetch_pinterest_niche_trending_terms_async(
    domain: Domain,
    region: str,
    limit: int,
) -> list[str]:
    from playwright.async_api import async_playwright

    browser_type, profile_dir = _trend_browser_profile(domain)
    profile_dir.mkdir(parents=True, exist_ok=True)

    queries = _pinterest_seed_queries(domain)
    query_batches: list[list[str]] = []
    per_query_cap = max(4, min(10, (limit + 3) // 4))
    minimum_query_count = min(4, len(queries))

    async with async_playwright() as p:
        browser_engine = getattr(p, browser_type)
        launch_options: dict[str, object] = {
            "headless": True,
            "locale": "es-ES",
            "viewport": {"width": 1365, "height": 1000},
            "timeout": 60000,
        }
        if browser_type == "firefox":
            launch_options["args"] = ["--no-remote", "--allow-downgrade"]
        else:
            launch_options["user_agent"] = USER_AGENT

        browser = await browser_engine.launch_persistent_context(
            str(profile_dir),
            **launch_options,
        )
        try:
            page = browser.pages[0] if browser.pages else await browser.new_page()
            for query in queries:
                collected_count = sum(len(batch) for batch in query_batches)
                if collected_count >= limit and len(query_batches) >= minimum_query_count:
                    break
                trend_terms = await _collect_terms_from_pinterest_trends_page(page, query, region)
                batch = _qualified_pinterest_collector_terms(domain, trend_terms)
                if len(batch) < per_query_cap:
                    search_terms = await _collect_terms_from_pinterest_search_page(page, query)
                    batch.extend(_qualified_pinterest_collector_terms(domain, search_terms))
                query_batches.append(_dedupe_terms(batch)[:per_query_cap])
        finally:
            try:
                await browser.close()
            except Exception:
                pass

    return _round_robin_pinterest_batches(query_batches, limit=limit)


async def _collect_terms_from_pinterest_trends_page(page, query: str, region: str) -> list[str]:
    encoded_query = urllib.parse.quote(query)
    urls = [
        f"https://trends.pinterest.com/?country={urllib.parse.quote(region)}&q={encoded_query}",
        f"https://trends.pinterest.com/search/?q={encoded_query}&country={urllib.parse.quote(region)}",
    ]
    terms: list[str] = []
    for url in urls:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(4000)
            terms.extend(await _try_pinterest_trends_search_box(page, query))
            terms.extend(await _visible_keyword_terms(page, query))
        except Exception as exc:
            logger.debug("Pinterest Trends page failed for %r at %s: %s", query, url, exc)
    return terms


async def _try_pinterest_trends_search_box(page, query: str) -> list[str]:
    selectors = [
        'input[type="search"]',
        'input[placeholder*="Search" i]',
        'input[placeholder*="buscar" i]',
        'input[aria-label*="Search" i]',
        'input[aria-label*="buscar" i]',
    ]
    for selector in selectors:
        loc = page.locator(selector).first
        try:
            if await loc.count() > 0 and await loc.is_visible(timeout=1000):
                await loc.fill(query)
                await page.wait_for_timeout(1500)
                terms = await _visible_keyword_terms(page, query)
                await loc.press("Enter")
                await page.wait_for_timeout(4000)
                terms.extend(await _visible_keyword_terms(page, query))
                return _dedupe_terms(terms)
        except Exception as exc:
            logger.debug("Pinterest search box selector failed (%s): %s", selector, exc)
            continue
    return []


async def _collect_terms_from_pinterest_search_page(page, query: str) -> list[str]:
    try:
        await page.goto(
            f"https://www.pinterest.com/search/pins/?q={urllib.parse.quote(query)}",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        await page.wait_for_timeout(5000)
        return await _visible_keyword_terms(page, query)
    except Exception as exc:
        logger.debug("Pinterest search page failed for %r: %s", query, exc)
        return []


async def _visible_keyword_terms(page, query: str) -> list[str]:
    payload = await page.evaluate(
        """() => {
            const values = [];
            const targets = [
                ['guide', 'button[data-test-id="one-bar-pill"]'],
                ['suggestion', '[role="listbox"] [role="option"]'],
                ['suggestion', '[data-test-id*="typeahead" i] a'],
                ['suggestion', '[data-test-id*="suggestion" i] a'],
                ['suggestion', 'a[href*="/search/pins/"]'],
                ['trend', '[data-test-id*="trend" i] a'],
                ['trend', '[data-test-id*="trend" i][role="button"]'],
                ['pin', 'a[href*="/pin/"]']
            ];
            const seen = new Set();
            for (const [kind, selector] of targets) {
                for (const el of document.querySelectorAll(selector)) {
                    const rect = el.getBoundingClientRect();
                    const style = getComputedStyle(el);
                    if (rect.width <= 0 || rect.height <= 0 || style.display === 'none' || style.visibility === 'hidden') {
                        continue;
                    }
                    const text = (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim();
                    const href = el.getAttribute('href') || '';
                    if (text.length < 2 || text.length > 180) continue;
                    const key = `${kind}|${text}|${href}`;
                    if (seen.has(key)) continue;
                    seen.add(key);
                    values.push({kind, text, href});
                }
            }
            return values.slice(0, 300);
        }"""
    )
    return _pinterest_candidates_from_visible_items(query, payload)


def fetch_pinterest_trending_terms(region: str = DEFAULT_REGION, *, limit: int = 80) -> list[str]:
    """HTTP fallback for Pinterest Trends when Playwright is unavailable."""

    token = os.environ.get("PINTEREST_ACCESS_TOKEN", "").strip()
    if token:
        api_terms = _fetch_pinterest_api_terms(region, token, limit)
        if api_terms:
            return api_terms

    terms = _fetch_pinterest_public_page_terms(region, limit)
    if terms:
        return terms

    logger.warning("Pinterest Trends scrape returned no terms; using seed fallback.")
    return []


def _fetch_pinterest_api_terms(region: str, token: str, limit: int) -> list[str]:
    """Best-effort official API path for accounts with Pinterest API access."""
    url = f"https://api.pinterest.com/v5/trends/keywords/{region}/top/growing"
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT},
            params={"limit": min(limit, 50)},
            timeout=20,
        )
        if response.status_code >= 400:
            logger.warning("Pinterest Trends API returned HTTP %s", response.status_code)
            return []
        payload = response.json()
    except Exception as exc:
        logger.warning("Pinterest Trends API failed: %s", exc)
        return []

    terms = []
    for item in payload.get("items", payload if isinstance(payload, list) else []):
        if isinstance(item, str):
            terms.append(item)
        elif isinstance(item, dict):
            terms.append(str(item.get("keyword") or item.get("term") or item.get("name") or ""))
    return _dedupe_terms(terms)[:limit]


def _fetch_pinterest_public_page_terms(region: str, limit: int) -> list[str]:
    """Best-effort scrape of the public Pinterest Trends page."""
    url = f"{PINTEREST_TRENDS_URL}?country={urllib.parse.quote(region)}"
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=25)
        response.raise_for_status()
    except Exception as exc:
        logger.warning("Pinterest Trends page request failed: %s", exc)
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    text_blobs: list[str] = []
    for script in soup.find_all("script"):
        text = script.get_text(" ", strip=True)
        if any(marker in text.lower() for marker in ["trend", "keyword", "query"]):
            text_blobs.append(text)
    for tag in soup.find_all(["h1", "h2", "h3", "a", "button", "span", "div"]):
        text = tag.get_text(" ", strip=True)
        if 3 <= len(text) <= 80:
            text_blobs.append(text)

    terms: list[str] = []
    for blob in text_blobs:
        terms.extend(_extract_candidate_terms(blob))
    return _dedupe_terms(terms)[:limit]


def fetch_google_news_signals(
    keyword: str,
    language: str = DEFAULT_LANGUAGE,
    region: str = DEFAULT_REGION,
    limit: int = 5,
) -> list[NewsSignal]:
    query = urllib.parse.quote(f"{keyword} receta OR cocina OR food")
    url = f"https://news.google.com/rss/search?q={query}&hl={language}&gl={region}&ceid={region}:{language}"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": f"{language}-{region},{language};q=0.9,en;q=0.8",
    }
    for attempt in range(2):
        try:
            response = requests.get(url, headers=headers, timeout=12)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            break
        except Exception as exc:
            if attempt == 0:
                time.sleep(0.5)
                continue
            logger.debug("Google News RSS failed for %r: %s", keyword, exc)
            return []

    signals: list[NewsSignal] = []
    for item in root.findall(".//item"):
        title = _clean_news_title(item.findtext("title", ""))
        if not title:
            continue
        source_node = item.find("source")
        signals.append(
            NewsSignal(
                title=title,
                source=source_node.text if source_node is not None and source_node.text else "",
                published=item.findtext("pubDate", ""),
            )
        )
        if len(signals) >= limit:
            break
    return signals


def fetch_google_news_discovery_terms(
    domain: Domain,
    language: str = DEFAULT_LANGUAGE,
    region: str = DEFAULT_REGION,
    limit: int = 40,
) -> list[str]:
    """Discover current recipe topics directly from Google News titles."""

    queries = [f"{category} recetas" for category in domain.categories[:4]]
    queries.extend(["recetas de temporada", domain.niche])
    terms: list[str] = []
    with ThreadPoolExecutor(max_workers=min(4, len(queries))) as executor:
        futures = {
            executor.submit(fetch_google_news_signals, query, language, region, 6): query for query in queries
        }
        for future in as_completed(futures):
            try:
                signals = future.result()
            except Exception as exc:
                logger.debug("Google News discovery failed for %r: %s", futures[future], exc)
                continue
            for signal in signals:
                terms.extend(_candidate_terms_from_news_title(signal.title))
    return _dedupe_terms(terms)[:limit]


def fetch_google_trending_terms(
    domain: Domain,
    language: str = DEFAULT_LANGUAGE,
    region: str = DEFAULT_REGION,
    limit: int = 40,
) -> list[str]:
    """Read Google's current trending-search RSS feed for food topics."""

    del domain, language
    url = "https://trends.google.com/trending/rss"
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            params={"geo": region},
            timeout=20,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except Exception as exc:
        logger.warning("Google Trends RSS failed: %s", exc)
        return []

    terms = []
    for node in root.iter():
        if str(node.tag).rsplit("}", 1)[-1] not in {"title", "news_item_title"}:
            continue
        text = _clean_news_title(node.text or "")
        if text:
            terms.extend(_candidate_terms_from_news_title(text))
    return _dedupe_terms(terms)[:limit]


def fetch_google_autocomplete_terms(
    domain: Domain,
    language: str = DEFAULT_LANGUAGE,
    region: str = DEFAULT_REGION,
    limit: int = 40,
) -> list[str]:
    """Expand domain seeds into current long-tail Google search suggestions."""

    del region
    seeds = _pinterest_seed_queries(domain)[:8]

    def fetch(seed: str) -> list[str]:
        try:
            response = requests.get(
                "https://suggestqueries.google.com/complete/search",
                headers={"User-Agent": USER_AGENT},
                params={"client": "firefox", "hl": language, "q": seed},
                timeout=12,
            )
            response.raise_for_status()
            payload = response.json()
            return payload[1] if isinstance(payload, list) and len(payload) > 1 else []
        except Exception as exc:
            logger.debug("Google Suggestions failed for %r: %s", seed, exc)
            return []

    terms: list[str] = []
    with ThreadPoolExecutor(max_workers=min(6, len(seeds))) as executor:
        futures = [executor.submit(fetch, seed) for seed in seeds]
        for future in as_completed(futures):
            terms.extend(future.result())
    return _dedupe_terms(terms)[:limit]


def _candidate_terms_from_news_title(title: str) -> list[str]:
    """Extract a compact recipe phrase from a headline without copying the article."""

    text = _clean_news_title(title)
    text = re.split(r"\s+[|\u2013\u2014]\s+|:\s+", text, maxsplit=1)[0]
    text = re.sub(
        r"^(?:c[o\u00f3]mo (?:hacer|preparar)|la receta (?:f[a\u00e1]cil )?de|"
        r"receta (?:f[a\u00e1]cil )?de|el secreto (?:para|de))\s+",
        "",
        text,
        flags=re.I,
    )
    words = text.split()
    if not 2 <= len(words) <= 12:
        return []
    return [text]


def rank_terms_for_domain(
    domain: Domain,
    terms: list[str],
    *,
    limit: int,
    region: str,
    language: str,
    google_news_provider: GoogleNewsProvider,
    search_volume_provider: SearchVolumeProvider | None = None,
    term_sources: dict[str, set[str]] | None = None,
    excluded_keywords: set[str] | None = None,
    deep_validate_top: int = 40,
) -> list[TrendCandidate]:
    """Rank trend candidates in two passes:

    Pass 1 (cheap): normalize → food relevance → specificity quality gate.
    Vague keywords (no dish noun + concrete qualifier) are rejected here.

    Pass 2 (expensive): the top ``deep_validate_top`` survivors are validated
    for search demand (Google autocomplete depth) and freshness (Google News).
    Only then are they scored, sorted, and trimmed to ``limit``.
    """
    domain_tokens = _domain_tokens(domain)
    demand_provider = search_volume_provider or _search_volume_proxy
    demand_source = (
        "Google Autocomplete Demand"
        if demand_provider is _search_volume_proxy
        else "Configured Search Demand Provider"
    )
    minimum_demand = _minimum_search_demand_score()
    if term_sources is None:
        # Direct callers predating multi-source discovery supplied a Pinterest
        # term list without an explicit provenance map.
        term_sources = {
            normalized.casefold(): {"Pinterest Trends"}
            for term in terms
            if (normalized := _normalize_keyword(term))
        }
    excluded_keywords = excluded_keywords or set()

    # ── Pass 1: cheap quality gate ──
    survivors: list[tuple[int, str, float, float, set[str]]] = []
    # (index, keyword, pinterest_score, specificity, discovery_sources)
    rejected_vague = 0
    for index, term in enumerate(terms):
        keyword = _normalize_keyword(term)
        if not keyword or len(keyword) < 4:
            continue
        if keyword.casefold() in excluded_keywords:
            continue
        if _is_generic_domain_seed(domain, keyword):
            continue
        if not _looks_food_relevant(keyword, domain_tokens):
            continue
        specificity = _keyword_specificity_score(keyword)
        if specificity <= 0:
            rejected_vague += 1
            logger.debug("Rejected vague keyword for %s: %r", domain.handle, keyword)
            continue
        discovery_sources = set(term_sources.get(keyword.casefold(), set())) & DISCOVERY_SOURCES
        if not discovery_sources:
            logger.warning(
                "[%s] Rejected candidate without discovery provenance: %r",
                domain.handle,
                keyword,
            )
            continue
        pinterest_origin = "Pinterest Trends" in discovery_sources
        pinterest_score = max(1.0, 100.0 - index) if pinterest_origin else 0.0
        survivors.append((index, keyword, pinterest_score, specificity, discovery_sources))

    if rejected_vague:
        logger.info(
            "[%s] Specificity gate rejected %d vague keywords (%d survivors)",
            domain.handle,
            rejected_vague,
            len(survivors),
        )

    # Pre-rank survivors cheaply so deep validation only touches the best ones.
    survivors.sort(key=lambda item: (item[2] + item[3] * 6), reverse=True)
    deep_pool = survivors[: max(limit, deep_validate_top)]

    # ── Pass 2: deep volume + freshness validation ──
    def validate_survivor(
        survivor: tuple[int, str, float, float, set[str]],
    ) -> TrendCandidate | None:
        _index, keyword, pinterest_score, specificity, discovery_sources = survivor
        try:
            volume = max(0.0, float(demand_provider(keyword, language, region)))
        except Exception as exc:
            logger.warning(
                "[%s] Search demand validation failed for %r: %s",
                domain.handle,
                keyword,
                exc,
            )
            return None
        if volume < minimum_demand:
            logger.info(
                "[%s] Rejected keyword without sufficient external demand (%.2f < %.2f): %r",
                domain.handle,
                volume,
                minimum_demand,
                keyword,
            )
            return None
        try:
            news = google_news_provider(keyword, language, region, 5)
        except Exception as exc:
            logger.warning(
                "[%s] Google News freshness validation failed for %r: %s",
                domain.handle,
                keyword,
                exc,
            )
            news = []
        cluster = _cluster_for_keyword(domain, keyword)
        relevance = _relevance_score(keyword, domain_tokens)
        news_score = min(25, len(news) * 5)
        score = pinterest_score + relevance + news_score + volume + specificity * 6
        sources = set(discovery_sources)
        if news:
            sources.add("Google News")
        sources.add(demand_source)
        return TrendCandidate(
            keyword=keyword,
            domain=domain.handle,
            cluster=cluster,
            priority=_priority(score),
            score=round(score, 2),
            pinterest_score=round(pinterest_score, 2),
            google_news_hits=len(news),
            google_news_titles=[item.title for item in news],
            source=" + ".join(sorted(sources)),
            specificity_score=round(specificity, 2),
            search_volume_score=round(volume, 2),
            search_demand_score=round(volume, 2),
            search_demand_source=demand_source,
            pinterest_origin="Pinterest Trends" in discovery_sources,
            qualified=True,
        )

    scored: list[TrendCandidate] = []
    if deep_pool:
        try:
            configured_workers = int(os.environ.get("RANKSTEIN_KEYWORD_VALIDATION_WORKERS", "6"))
        except ValueError:
            configured_workers = 6
        validation_workers = max(1, min(configured_workers, 8, len(deep_pool)))
        with ThreadPoolExecutor(max_workers=validation_workers) as executor:
            futures = [executor.submit(validate_survivor, survivor) for survivor in deep_pool]
            for future in as_completed(futures):
                candidate = future.result()
                if candidate is not None:
                    scored.append(candidate)

    scored.sort(key=lambda item: item.score, reverse=True)
    return scored[:limit]


def write_daily_best_list(
    domain: Domain,
    candidates: list[TrendCandidate],
    generated_at: str,
    *,
    candidate_origin_policy: str = "multi_source",
) -> None:
    domain.root.mkdir(parents=True, exist_ok=True)
    json_path = domain.root / "daily_best_keywords.json"
    md_path = domain.root / "daily_best_keywords.md"
    payload = {
        "generated_at": generated_at,
        "domain": domain.handle,
        "methodology": {
            "candidate_origin": (
                "Pinterest Trends/Search only"
                if candidate_origin_policy == "pinterest_required"
                else (
                    "Pinterest Trends/Search plus Google News discovery, "
                    "Google Trends RSS, and Google autocomplete"
                )
            ),
            "candidate_origin_policy": candidate_origin_policy,
            "specificity_gate": "dish plus concrete qualifier",
            "external_validation": "Google search demand plus optional Google News freshness",
            "fail_closed": True,
        },
        "items": [asdict(item) for item in candidates],
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        f"# Daily Best Keywords - {domain.display_name}",
        "",
        f"Generated: {generated_at}",
        "",
        "| Keyword | Cluster | Priority | Score | Specificity | Demand | News Hits |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for item in candidates:
        lines.append(
            f"| {item.keyword} | {item.cluster} | {item.priority} | "
            f"{item.score:.2f} | {item.specificity_score:.1f} | "
            f"{item.search_volume_score:.1f} | {item.google_news_hits} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_qualified_keyword_keys(
    domain: Domain,
    *,
    max_age_hours: float | None = None,
    now: datetime | None = None,
) -> tuple[set[str], str]:
    """Load fresh keyword evidence that is allowed to reach article research.

    The daily JSON report is an authorization record, not just an operator
    display. Missing, stale, malformed, unprovenanced, vague, or zero-demand
    rows fail closed.
    """

    report_path = domain.root / "daily_best_keywords.json"
    if not report_path.exists():
        return set(), "missing_keyword_research"
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        generated_at = datetime.fromisoformat(str(payload["generated_at"]).replace("Z", "+00:00"))
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return set(), "invalid_keyword_research"

    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=UTC)
    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    if max_age_hours is None:
        try:
            max_age_hours = float(os.environ.get("RANKSTEIN_KEYWORD_EVIDENCE_MAX_AGE_HOURS", "36"))
        except ValueError:
            max_age_hours = 36.0
    if current_time - generated_at > timedelta(hours=max(1.0, max_age_hours)):
        return set(), "stale_keyword_research"

    eligible: set[str] = set()
    for item in payload.get("items", []):
        if not isinstance(item, dict):
            continue
        keyword = str(item.get("keyword") or "").strip()
        try:
            demand = float(item.get("search_demand_score") or item.get("search_volume_score") or 0.0)
            specificity = float(item.get("specificity_score") or 0.0)
        except (TypeError, ValueError):
            continue
        source = str(item.get("source") or "")
        pinterest_origin = item.get("pinterest_origin")
        has_valid_origin = (pinterest_origin is True and "Pinterest Trends" in source) or (
            pinterest_origin is False
            and any(
                discovery_source in source for discovery_source in DISCOVERY_SOURCES - {"Pinterest Trends"}
            )
        )
        if (
            keyword
            and item.get("qualified") is True
            and has_valid_origin
            and specificity > 0
            and demand >= _minimum_search_demand_score()
        ):
            eligible.add(keyword.casefold())
    if not eligible:
        return set(), "no_qualified_keywords"
    return eligible, "ok"


def has_qualified_keyword_evidence(
    domain: Domain,
    keyword: str,
    *,
    max_age_hours: float | None = None,
) -> tuple[bool, str, dict[str, object] | None]:
    """Return the fresh evidence row for one keyword, if authorized."""

    eligible, reason = load_qualified_keyword_keys(domain, max_age_hours=max_age_hours)
    key = keyword.strip().casefold()
    if key not in eligible:
        return False, reason if not eligible else "keyword_not_qualified", None
    try:
        payload = json.loads((domain.root / "daily_best_keywords.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False, "invalid_keyword_research", None
    for item in payload.get("items", []):
        if isinstance(item, dict) and str(item.get("keyword") or "").strip().casefold() == key:
            return True, "ok", item
    return False, "keyword_not_qualified", None


def fallback_seed_terms() -> list[str]:
    """Retired: static seeds must never authorize autonomous article work."""

    raise RuntimeError("Live trend discovery is required; static keyword fallback is disabled")
    return [
        "postres faciles",
        "tarta de queso",
        "recetas saludables",
        "aperitivos faciles",
        "cenas rapidas",
        "pasteles de chocolate",
        "ensaladas frescas",
        "recetas con freidora de aire",
        "galletas caseras",
        "helados artesanales",
        "comida española",
        "recetas para invitados",
    ]


def _pinterest_seed_queries(domain: Domain) -> list[str]:
    """Build precise searches that Pinterest can expand into live query guides.

    Pinterest's search result page returns useful guide fragments such as
    ``De pistacho`` or ``Vasca``. Precise dish queries must come first so those
    fragments reconstruct into precise recipe phrases instead of vague category
    phrases. Category searches remain as a later breadth fallback.
    """

    niche = domain.niche.casefold()
    queries: list[str] = []

    if any(marker in niche for marker in ["pasteler", "postre", "reposter", "dulce"]):
        queries.extend(
            [
                "tarta de queso",
                "bizcocho de chocolate",
                "galletas de avena",
                "pastel de zanahoria",
                "helado de pistacho",
                "mousse de chocolate",
                "postres gourmet",
            ]
        )
    if any(marker in niche for marker in ["saludable", "espanol", "español", "tradicional", "receta"]):
        queries.extend(
            [
                "tarta de queso",
                "croquetas caseras",
                "tortilla española",
                "paella de marisco",
                "ensalada de garbanzos",
                "pollo al horno",
                "salmón al horno",
                "arroz con leche",
            ]
        )

    if not queries:
        queries.extend(
            [
                "tarta de queso",
                "pollo al horno",
                "ensalada de garbanzos",
                "galletas de avena",
                "arroz con leche",
                "salmón al horno",
            ]
        )

    queries.extend(category for category in domain.categories)
    queries.extend(["postres gourmet", "aperitivos fríos"])
    try:
        query_limit = int(os.environ.get("RANKSTEIN_PINTEREST_SEED_QUERY_LIMIT", "16"))
    except ValueError:
        query_limit = 16
    return _dedupe_terms(queries)[: max(6, min(query_limit, 24))]


def _is_pinterest_ui_noise(text: str) -> bool:
    folded = _fold(text).strip()
    return (
        not folded
        or folded in _PINTEREST_UI_NOISE
        or folded in _LOW_QUALITY_PINTEREST_GUIDES
        or folded.startswith(("continuar con ", "has cerrado sesion", "si continuas"))
        or folded.endswith((" para", " con", " de"))
    )


def _compose_pinterest_suggestion(query: str, suggestion: str) -> str:
    """Join a Pinterest search-guide fragment to the query that produced it."""

    base = _normalize_keyword(query)
    fragment = _normalize_keyword(suggestion)
    if not base or not fragment or _is_pinterest_ui_noise(fragment):
        return ""

    canonical_fragments = {
        "air fryer": "en air fryer",
        "fria": "fría",
        "horno": "al horno",
        "la vina receta original": "la viña original",
        "vasca receta": "vasca",
    }
    fragment = canonical_fragments.get(_fold(fragment), fragment)
    fragment = fragment[:1].lower() + fragment[1:]

    base_folded = _fold(base)
    fragment_folded = _fold(fragment)
    if fragment_folded == base_folded or base_folded in fragment_folded:
        return fragment

    base_words = base_folded.split()
    fragment_words = fragment_folded.split()
    overlap = 0
    for size in range(min(len(base_words), len(fragment_words)), 0, -1):
        if base_words[-size:] == fragment_words[:size]:
            overlap = size
            break
    suffix = " ".join(fragment.split()[overlap:])
    return _normalize_keyword(f"{base} {suffix}")


def _round_robin_pinterest_batches(
    batches: list[list[str]],
    *,
    limit: int,
) -> list[str]:
    """Interleave Pinterest query families so one dish cannot monopolize a shortlist."""

    interleaved: list[str] = []
    max_batch_size = max((len(batch) for batch in batches), default=0)
    for index in range(max_batch_size):
        for batch in batches:
            if index < len(batch):
                interleaved.append(batch[index])
    return _dedupe_terms(interleaved)[: max(0, limit)]


def _pinterest_search_query_from_href(href: str) -> str:
    if "/search/" not in href:
        return ""
    try:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("q", [""])[0]
    except (TypeError, ValueError):
        return ""
    return _normalize_keyword(query)


def _pinterest_pin_phrase(text: str) -> str:
    phrase = re.split(r"\s+[|\u2013\u2014]\s+|[.!?](?:\s|$)", text.strip(), maxsplit=1)[0]
    phrase = re.sub(
        r"^(?:c[oó]mo (?:hacer|preparar)|receta (?:f[aá]cil )?de|la receta de)\s+",
        "",
        phrase,
        flags=re.I,
    )
    return _normalize_keyword(phrase)


def _pinterest_candidates_from_visible_items(
    query: str,
    items: list[Mapping[str, object]],
) -> list[str]:
    """Convert targeted Pinterest DOM evidence into complete search phrases."""

    terms: list[str] = []
    for item in items:
        kind = str(item.get("kind") or "").strip().casefold()
        text = str(item.get("text") or "").strip()
        href = str(item.get("href") or "").strip()
        if kind not in {"guide", "suggestion", "trend", "pin"} or not text:
            continue

        href_query = _pinterest_search_query_from_href(href)
        if href_query and not _is_pinterest_ui_noise(href_query):
            terms.append(href_query)
            continue
        if kind in {"guide", "suggestion"}:
            composed = _compose_pinterest_suggestion(query, text)
            if composed:
                terms.append(composed)
            continue

        phrase = _pinterest_pin_phrase(text)
        if phrase and not _is_pinterest_ui_noise(phrase):
            terms.append(phrase)
    return _dedupe_terms(terms)


def _qualified_pinterest_collector_terms(domain: Domain, terms: list[str]) -> list[str]:
    """Keep the browser collection budget focused on precise recipe phrases."""

    domain_tokens = _domain_tokens(domain)
    return [
        keyword
        for keyword in _dedupe_terms(terms)
        if _looks_food_relevant(keyword, domain_tokens) and _keyword_specificity_score(keyword) > 0
    ]


def _extract_candidate_terms(text: str) -> list[str]:
    terms = re.findall(r'"(?:keyword|term|query|name|label)"\s*:\s*"([^"]{3,80})"', text, re.I)
    terms.extend(re.findall(r"\b[a-záéíóúñü][a-záéíóúñü ]{3,58}\b", text, re.I))
    return terms


def _dedupe_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        keyword = _normalize_keyword(term)
        if not keyword or keyword.casefold() in seen or keyword.casefold() in NOISE_TERMS:
            continue
        seen.add(keyword.casefold())
        result.append(keyword)
    return result


def _normalize_keyword(term: str) -> str:
    term = BeautifulSoup(term or "", "html.parser").get_text(" ", strip=True)
    term = urllib.parse.unquote(term)
    term = re.sub(r"\s+", " ", term).strip(" -_.,:;|")
    if len(term.split()) > 8:
        return ""
    return term


def _clean_news_title(title: str) -> str:
    title = BeautifulSoup(title or "", "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+-\s+[^-]+$", "", title).strip()


def _domain_tokens(domain: Domain) -> set[str]:
    text = " ".join([domain.niche, domain.display_name, *domain.categories]).casefold()
    return {token for token in re.findall(r"[a-záéíóúñü]{4,}", text) if token}


def _looks_food_relevant(keyword: str, domain_tokens: set[str]) -> bool:
    food_markers = {
        "receta",
        "recetas",
        "cocina",
        "postre",
        "postres",
        "tarta",
        "pastel",
        "galleta",
        "chocolate",
        "helado",
        "aperitivo",
        "ensalada",
        "carne",
        "pescado",
        "saludable",
        "cena",
        "comida",
    }
    tokens = set(re.findall(r"[a-záéíóúñü]{4,}", keyword.casefold()))
    folded = _fold(keyword)
    has_known_dish = any(dish in folded for dish in _DISH_SUBSTRINGS)
    return bool(tokens & (food_markers | domain_tokens) or has_known_dish) and (
        is_recipe_aware_keyword(keyword) or has_known_dish
    )


def _is_generic_domain_seed(domain: Domain, keyword: str) -> bool:
    lower = keyword.casefold().strip()
    generic = {domain.display_name.casefold(), domain.handle.casefold()}
    generic.update(category.casefold() for category in domain.categories)
    return lower in generic


def _cluster_for_keyword(domain: Domain, keyword: str) -> str:
    lower = keyword.casefold()
    for category in domain.categories:
        if category.casefold() in lower:
            return category
    category_aliases = {
        "Postres": ["postre", "tarta", "dulce", "crema"],
        "Pasteles": ["pastel", "bizcocho", "cake"],
        "Galletas": ["galleta", "cookie"],
        "Chocolates": ["chocolate", "cacao"],
        "Helados": ["helado", "sorbete"],
        "Aperitivos": ["aperitivo", "tapa", "canape", "entrante"],
        "Ensaladas": ["ensalada"],
        "Carnes": ["carne", "pollo", "ternera"],
        "Pescados": ["pescado", "atun", "salmon", "merluza"],
    }
    for category in domain.categories:
        if any(alias in lower for alias in category_aliases.get(category, [])):
            return category
    return domain.categories[0] if domain.categories else "General"


def _relevance_score(keyword: str, domain_tokens: set[str]) -> float:
    tokens = set(re.findall(r"[a-záéíóúñü]{4,}", keyword.casefold()))
    return float(len(tokens & domain_tokens) * 12)


def _priority(score: float) -> str:
    if score >= 120:
        return "High"
    if score >= 90:
        return "Medium"
    return "Low"

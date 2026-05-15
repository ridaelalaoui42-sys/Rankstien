"""Domain-name → niche / categories / keywords / brand voice via Gemini CLI.

Used by the ``add-domain`` provisioner to populate everything that can be
inferred from the domain name alone, with no further user input. Each
public function shells out to ``gemini -p ... --yolo`` in OAuth/subscription mode.
The model is left on ``auto`` by default so Gemini CLI can route to the best
available model; fallback calls may use Gemini 3/3.1 variants.

The four generators are independent: a failure in one (e.g. quota cap)
falls back to a sensible default so the wizard still completes. The
``add-domain`` orchestrator surfaces which step fell back so the user can
re-run a single step later (``rankstein regenerate <handle> --step categories``).

Public API
----------
- ``detect_niche(domain) -> NicheInfo``
- ``generate_categories(niche, language, count=6) -> list[str]``
- ``generate_keywords(niche, categories, language, count=30) -> list[Keyword]``
- ``generate_brand_voice(niche, language, display_name) -> str``
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("rankstein.niche_detector")


# ───────────────────────────────────────────────────────────────────────────
# Models
# ───────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class NicheInfo:
    """Output of niche detection from a domain name."""

    niche: str  # e.g. "low-carb dinner recipes"
    language: str  # ISO 639-1, e.g. "en"
    vertical: str  # e.g. "recipe blog"
    display_name: str  # e.g. "Keto Dinners"


@dataclass(frozen=True)
class Keyword:
    """One row of the keyword roadmap."""

    keyword: str
    category: str
    priority: str  # "High" | "Medium" | "Low"


# ───────────────────────────────────────────────────────────────────────────
# Gemini CLI wrapper
# ───────────────────────────────────────────────────────────────────────────


_DEFAULT_MODEL = "auto"
_GEMINI_TIMEOUT_SECONDS = 180  # bumped — 2.5-flash on free tier can take 90s+


_ISOLATED_CONFIG_DIR: Path | None = None


def _isolated_gemini_config_dir() -> Path | None:
    """Build (once per process) a stripped-down ``GEMINI_CONFIG_DIR`` that
    has the user's OAuth creds but NONE of their project context.

    The default user config at ``~/.gemini/`` includes ``GEMINI.md`` (system
    instructions describing the user's RankStein workspace), installed
    extensions, custom commands, and a per-project context cache. Loading
    that persona makes the model answer "categories for a blog" with the
    user's known projects (RankStein, RecetaDolce, etc.).

    By copying ONLY ``oauth_creds.json`` into a fresh tmpdir and pointing
    ``GEMINI_CONFIG_DIR`` at it, gemini boots authenticated but stateless.
    The dir is created lazily and cleaned up at process exit.

    Returns ``None`` if the user's gemini config can't be located — the
    caller falls back to using the user's full config (drift risk noted).
    """
    global _ISOLATED_CONFIG_DIR
    if _ISOLATED_CONFIG_DIR is not None and _ISOLATED_CONFIG_DIR.is_dir():
        return _ISOLATED_CONFIG_DIR

    user_config = Path(os.path.expanduser("~/.gemini"))
    creds = user_config / "oauth_creds.json"
    if not creds.is_file():
        # No OAuth creds detected — caller should fall back gracefully.
        return None

    isolated = Path(tempfile.mkdtemp(prefix="rankstein-gemini-cfg-"))
    try:
        shutil.copy2(creds, isolated / "oauth_creds.json")
        # Some gemini-cli versions also need ``settings.json`` to skip the
        # first-run wizard. Copy it if present (does not contain credentials).
        settings = user_config / "settings.json"
        if settings.is_file():
            shutil.copy2(settings, isolated / "settings.json")
    except OSError as e:
        logger.warning("Could not seed isolated gemini config: %s", e)
        return None

    atexit.register(lambda: shutil.rmtree(isolated, ignore_errors=True))
    _ISOLATED_CONFIG_DIR = isolated
    return isolated


def _resolve_gemini_binary() -> str:
    """Return the resolved path to the gemini CLI.

    Honors ``GEMINI_CLI`` env override. On Windows, ``shutil.which`` traverses
    PATHEXT so ``gemini.cmd`` / ``gemini.bat`` resolve correctly — Python's
    raw ``subprocess.run([...])`` does NOT do this automatically (it calls
    CreateProcess which only matches the literal name).
    """
    override = os.environ.get("GEMINI_CLI")
    if override:
        return override
    resolved = shutil.which("gemini")
    if resolved:
        return resolved
    # Last-ditch fallback: let subprocess fail with FileNotFoundError so the
    # caller's existing error path triggers.
    return "gemini"


def _run_gemini(prompt: str, *, model: str = _DEFAULT_MODEL) -> str:
    """Invoke ``gemini -p <prompt> [--model <model>] --yolo`` and return stdout.

    Run from a stateless temp cwd so project-local ``GEMINI.md`` files don't
    auto-load — when they do, the model takes on the RankStein agent persona
    and adds chatty preamble instead of returning bare JSON.

    Raises ``RuntimeError`` on non-zero exit OR empty output. The caller is
    responsible for parsing the response and applying any fallback.
    """
    cmd = [
        _resolve_gemini_binary(),
        "-p",
        prompt,
        "--yolo",
        # Disable all extensions so installed skills (rankstein-content-chef,
        # youtube-shorts, etc.) cannot leak into the response context. The
        # ``-e`` flag with an unmatched name selects zero extensions.
        "-e",
        "__none__",
    ]
    if model.lower() != "auto":
        cmd[3:3] = ["--model", model]
    # Stateless cwd + isolated config dir: tmp cwd has no GEMINI.md so the
    # agent doesn't take on the project's persona, AND we override
    # GEMINI_CONFIG_DIR to a stripped config that has only OAuth creds —
    # no GEMINI.md, no extensions, no commands. Without this, gemini loads
    # ~/.gemini/GEMINI.md as system instructions and answers questions
    # using the user's known projects (RankStein/RecetaDolce) instead of the actual prompt.
    env = dict(os.environ)
    env.pop("GOOGLE_API_KEY", None)
    env.pop("GEMINI_API_KEY", None)
    isolated = _isolated_gemini_config_dir()
    if isolated is not None:
        env["GEMINI_CONFIG_DIR"] = str(isolated)
    with tempfile.TemporaryDirectory(prefix="rankstein-gemini-") as tmpcwd:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_GEMINI_TIMEOUT_SECONDS,
                encoding="utf-8",
                errors="replace",
                cwd=tmpcwd,
                env=env,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"gemini CLI timed out after {_GEMINI_TIMEOUT_SECONDS}s") from e
        except FileNotFoundError as e:
            raise RuntimeError(
                "gemini CLI not found on PATH. Install via "
                "'npm i -g @google/gemini-cli' and authenticate with 'gemini'."
            ) from e

    if result.returncode != 0:
        raise RuntimeError(f"gemini CLI exited {result.returncode}: {result.stderr.strip()[:300]}")
    text = (result.stdout or "").strip()
    if not text:
        raise RuntimeError("gemini CLI returned empty output")
    return text


def _extract_json(text: str) -> object:
    """Pull the first JSON value (object or array) out of a CLI response.

    Robustness order:
      1. Strip ```json``` / ``` fences.
      2. Find the first ``{`` or ``[`` and try increasingly-shortened suffixes
         until ``json.loads`` accepts one (handles trailing prose).
      3. As a last resort, if the body looks like a markdown numbered list
         of bolded items, parse it into a list of strings.
    Raises ``ValueError`` if nothing usable is found.
    """
    # Strip code fences if present
    fenced = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text

    start = next((i for i, c in enumerate(candidate) if c in "{["), -1)
    if start != -1:
        body = candidate[start:]
        for end in range(len(body), 0, -1):
            try:
                return json.loads(body[:end])
            except json.JSONDecodeError:
                continue

    # Markdown-list fallback: lines like "1. **Quick & Easy Desserts**" or "1. Sheet Pan".
    # The dash class matches em-dash, en-dash, and ASCII hyphen — all three appear
    # in real Gemini markdown output, so the multi-codepoint class is intentional.
    md_items = re.findall(
        r"(?m)^\s*\d+\.\s+\**([^\n*]+?)\**\s*(?:[—–-]\s*[^\n]*)?$",  # noqa: RUF001
        candidate,
    )
    cleaned = [s.strip(" *.") for s in md_items if s.strip()]
    if cleaned:
        return cleaned

    raise ValueError(f"No JSON value found in response: {text[:200]!r}")


# ───────────────────────────────────────────────────────────────────────────
# Step 1 — niche detection from domain
# ───────────────────────────────────────────────────────────────────────────


def detect_niche(domain: str) -> NicheInfo:
    """Infer niche, language, vertical, and display name from a domain.

    On Gemini failure, falls back to a heuristic that strips the TLD and
    title-cases the second-level domain — better than nothing.
    """
    prompt = (
        "You are a JSON API. Output ONLY a single JSON object. "
        "Do NOT output any markdown, headings, prose, code fences, or commentary. "
        "Your entire response MUST start with { and end with }.\n\n"
        f"Task: classify the domain {domain!r}.\n"
        'Schema: {"niche": string (5-10 words), "language": string (ISO 639-1, '
        'e.g. en/es/fr/it/de), "vertical": one of ["recipe blog", "lifestyle", '
        '"tech", "fitness", "finance", "travel", "general"], '
        '"display_name": string (1-3 words, title-cased brand name)}\n\n'
        "Treat domain language hints (recetas/dolce → es/it; keto → en; etc.) "
        "as strong signals.\n\n"
        f"Output the JSON object now for {domain!r}:"
    )

    try:
        raw = _run_gemini(prompt)
        data = _extract_json(raw)
        if isinstance(data, dict):
            return NicheInfo(
                niche=str(data.get("niche", "")).strip() or _fallback_niche(domain),
                language=str(data.get("language", "en")).strip().lower()[:2] or "en",
                vertical=str(data.get("vertical", "general")).strip() or "general",
                display_name=str(data.get("display_name", "")).strip() or _fallback_display_name(domain),
            )
    except Exception as e:
        logger.warning("Niche detection failed (%s); using heuristic fallback", e)

    return NicheInfo(
        niche=_fallback_niche(domain),
        language="en",
        vertical="general",
        display_name=_fallback_display_name(domain),
    )


def _fallback_display_name(domain: str) -> str:
    stem = domain.split(".")[0]
    return " ".join(p.title() for p in re.split(r"[-_]+", stem) if p)


def _fallback_niche(domain: str) -> str:
    return _fallback_display_name(domain).lower() + " content"


# ───────────────────────────────────────────────────────────────────────────
# Step 2 — category tree
# ───────────────────────────────────────────────────────────────────────────


def generate_categories(niche: str, language: str, count: int = 6) -> list[str]:
    """Generate ``count`` Pinterest-friendly categories for the niche."""
    prompt = (
        "You are a JSON API. Output ONLY a single JSON array of strings. "
        "Do NOT output any markdown, headings, prose, code fences, or commentary. "
        "Your entire response MUST start with [ and end with ].\n\n"
        f"Task: generate exactly {count} Pinterest-friendly category names "
        f'for a blog about "{niche}" in {language}.\n'
        "Each name: 1-3 words, title-cased, written in the target language, "
        "able to anchor 5-20 articles.\n\n"
        f"Output the JSON array of {count} strings now:"
    )

    try:
        raw = _run_gemini(prompt)
        data = _extract_json(raw)
        if isinstance(data, list) and all(isinstance(x, str) for x in data):
            cats = [c.strip() for c in data if c.strip()]
            if cats:
                return cats[:count]
    except Exception as e:
        logger.warning("Category generation failed (%s); using niche-derived fallback", e)

    # Fallback: synthesize from niche words
    return _fallback_categories(niche, count)


def _fallback_categories(niche: str, count: int) -> list[str]:
    base = ["Recipes", "Quick & Easy", "Healthy", "Comfort Food", "Holiday", "Tips"]
    if "fitness" in niche.lower() or "workout" in niche.lower():
        base = ["Workouts", "Nutrition", "Recovery", "Equipment", "Mindset", "Programs"]
    elif "travel" in niche.lower():
        base = ["Destinations", "Tips", "Budget", "Solo", "Family", "Adventure"]
    return base[:count]


# ───────────────────────────────────────────────────────────────────────────
# Step 3 — keyword roadmap
# ───────────────────────────────────────────────────────────────────────────


def generate_keywords(
    niche: str,
    categories: list[str],
    language: str,
    count: int = 30,
) -> list[Keyword]:
    """Generate a starter keyword roadmap mapped to categories."""
    cats_csv = ", ".join(categories)
    prompt = (
        "You are a JSON API. Output ONLY a single JSON array of objects. "
        "Do NOT output any markdown, headings, prose, code fences, or commentary. "
        "Your entire response MUST start with [ and end with ].\n\n"
        f"Task: generate exactly {count} SEO-targetable keywords for a blog "
        f'about "{niche}" in {language}.\n'
        f"Distribute across categories: {cats_csv}\n"
        "Each keyword: 2-6 words in the target language, real search intent, "
        "mix of high-volume and long-tail.\n"
        'Each object schema: {"keyword": string, "category": string '
        '(must be one of the listed categories), "priority": "High" or "Medium"}\n\n'
        f"Output the JSON array of {count} objects now:"
    )

    try:
        raw = _run_gemini(prompt)
        data = _extract_json(raw)
        if isinstance(data, list):
            out: list[Keyword] = []
            valid_cats = set(categories)
            for entry in data:
                if not isinstance(entry, dict):
                    continue
                kw = str(entry.get("keyword", "")).strip()
                cat = str(entry.get("category", "")).strip()
                pri = str(entry.get("priority", "Medium")).strip().title()
                if not kw or pri not in {"High", "Medium", "Low"}:
                    continue
                # Snap unknown categories to the first valid one
                if cat not in valid_cats:
                    cat = categories[0] if categories else cat or "Uncategorized"
                out.append(Keyword(keyword=kw, category=cat, priority=pri))
            if out:
                return out[:count]
    except Exception as e:
        logger.warning("Keyword generation failed (%s); using minimal fallback", e)

    return _fallback_keywords(niche, categories, count)


def _fallback_keywords(niche: str, categories: list[str], count: int) -> list[Keyword]:
    """Minimal seed roadmap so add-domain still produces something usable."""
    if not categories:
        categories = ["Uncategorized"]
    out: list[Keyword] = []
    base = niche.lower().split()[0] if niche else "content"
    for i in range(count):
        cat = categories[i % len(categories)]
        out.append(
            Keyword(
                keyword=f"{base} {cat.lower()} guide".strip(),
                category=cat,
                priority="Medium",
            )
        )
    return out


# ───────────────────────────────────────────────────────────────────────────
# Step 4 — brand voice document
# ───────────────────────────────────────────────────────────────────────────


def generate_brand_voice(niche: str, language: str, display_name: str) -> str:
    """Produce a markdown brand voice guide. Falls back to a generic template."""
    prompt = f"""Write a brand voice guide for a blog called "{display_name}" about "{niche}" in {language}.

Output a markdown document with these sections:
1. ## Tone — 3-4 adjectives describing the voice
2. ## First-Person Markers — 3 sample phrases the author would say in {language}
3. ## Authority Sources — which authoritative bodies the blog cites (e.g. AESAN/EFSA for Spanish food, USDA/Mayo Clinic for US health, WHO for global health)
4. ## Style Pillars — 5 numbered pillars matching a "Helpful Knowledgeable Friend" persona, each with a one-sentence description

Write directly in {language} where appropriate (sample phrases, pillar names if natural). Keep the document under 500 words. No introduction prose; start at the first ## heading."""

    try:
        raw = _run_gemini(prompt)
        if "##" in raw:
            return raw.strip()
    except Exception as e:
        logger.warning("Brand voice generation failed (%s); using template fallback", e)

    return _fallback_brand_voice(niche, language, display_name)


def _fallback_brand_voice(niche: str, language: str, display_name: str) -> str:
    return f"""## Tone
Helpful, knowledgeable, warm, direct.

## First-Person Markers
- "In my experience..."
- "After years of trying..."
- "Here's a tip I learned..."

## Authority Sources
General: peer-reviewed sources, recognized industry bodies. Update this section
with niche-specific authorities once the domain has shipped its first 5 articles.

## Style Pillars
1. **The Lead** — Open every article with why this specific topic matters now.
2. **Direct & Clear** — Plain language, no fluff. A friend giving real advice.
3. **One Concise Tip** — Every article includes one actionable expert tip.
4. **Action Headers** — Group steps under bold action-oriented headers.
5. **Authentic Voice** — First-person markers used sparingly but naturally.

(Generated from fallback template for {display_name} / niche: {niche} / language: {language}.
Re-run `rankstein regenerate <handle> --step brand-voice` to replace with a niche-specific guide.)
"""

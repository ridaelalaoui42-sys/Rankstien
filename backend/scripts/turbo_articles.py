"""Domain-aware Codex-first article worker for RankStein startup campaigns."""

from __future__ import annotations

import os
import sys

# Re-exec before importing modules like re/json when PYTHONHOME points at a
# different Python stdlib than the interpreter on PATH.
_clean_env = dict(os.environ)
_reexec_needed = False
for _name in ("PYTHONHOME",):
    if _clean_env.pop(_name, None):
        _reexec_needed = True
_clean_env.pop("UV_INTERNAL__PYTHONHOME", None)
if _reexec_needed:
    _exe = sys.executable.replace("\\", "/")
    os.execve(_exe, [_exe, *sys.argv], _clean_env)  # noqa: S606

import argparse
import asyncio
import contextlib
import json
import logging
import re
import shutil
import subprocess
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    import primp
except ImportError:
    primp = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("TurboArticles")

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.scripts.gemini_token_rotator import (
    current_account_label,
    ensure_account_1,
    is_quota_exhausted,
    rotate_account,
)
from backend.scripts.hero_image_pipeline import get_hero_image
from rankstein.category_policy import CategoryPolicyError, assign_article_category
from rankstein.domain import Domain, get_registry, reload_registry
from rankstein.keyword_roadmap import (
    clean_keyword_roadmap,
    mark_keyword_status,
    read_keyword_rows,
    reserve_pending_keywords,
)
from rankstein.pipeline_events import (
    record_pipeline_stage,
    set_pipeline_run_status,
    start_pipeline_run,
)
from rankstein.production_batch import ProductionBatchTracker
from rankstein.prompts import (
    IMAGE_NEGATIVE_PROMPT,
    build_recipe_image_prompt,
    build_recipe_image_scrape_brief,
    is_recipe_aware_keyword,
    recipe_alt_text,
    recipe_generation_visual_requirements,
)
from rankstein.runtime_env import clean_python_env
from rankstein.trend_intelligence import (
    _keyword_specificity_score,
    has_qualified_keyword_evidence,
    load_qualified_keyword_keys,
)

_PRODUCTION_BATCH_TRACKER: ProductionBatchTracker | None = None


def _start_pipeline_telemetry(
    keyword: str,
    cluster: str,
    domain: Domain,
    source: str,
) -> str:
    """Start telemetry without ever making observability a production blocker."""

    try:
        return start_pipeline_run(
            domain_handle=domain.handle,
            keyword=keyword,
            cluster=cluster,
            source=source,
        )
    except Exception as exc:
        logger.warning("Pipeline telemetry start failed for %s: %s", keyword, exc)
        return ""


def _pipeline_event(
    run_id: str,
    stage: str,
    state: str,
    message: str,
    **details,
) -> None:
    if not run_id:
        return
    try:
        record_pipeline_stage(
            run_id,
            stage,
            state,
            message,
            details=details,
            slug=str(details.get("slug") or ""),
        )
    except Exception as exc:
        logger.warning("Pipeline telemetry write failed for %s/%s: %s", run_id, stage, exc)


def _pipeline_status(run_id: str, status: str) -> None:
    if not run_id:
        return
    try:
        set_pipeline_run_status(run_id, status)
    except Exception as exc:
        logger.warning("Pipeline telemetry status failed for %s: %s", run_id, exc)


def _status_from_completion_output(output: str) -> str:
    """Return roadmap status from a worker completion proof blob.

    If the proof JSON shows all 3 flags True → Live.
    If at least supabase_published is True → Needs Verification until Pinterest
    proof is linked. If no proof JSON exists but the CLI exited 0, keep the
    keyword in Needs Verification for manual/runtime proof.
    Only return Failed if we see explicit failure evidence.
    """
    for candidate in reversed(re.findall(r"\{[^{}]*\}", output, flags=re.DOTALL)):
        try:
            proof = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        required = ("supabase_published", "pinterest_uploaded", "pin_linked")
        if all(proof.get(key) is True for key in required):
            return "Live"
        # Supabase published but pin missing → article-only success needs verification.
        if proof.get("supabase_published") is True:
            return "Needs Verification"
        # Explicit failure in proof
        if proof.get("supabase_published") is False:
            return "Failed"
        return "Needs Verification"
    # No proof JSON found but CLI exited 0 → keep out of Live until verified.
    return "Needs Verification"


def _worker_models() -> list[str]:
    """Return fallback model names for Gemini/Odysseus fallback paths."""
    return ["gemini-3.1-flash-lite", "gemini-3.1-flash-lite-preview", "gemini-3.1-pro-preview"]


# ——————————————————————— OpenRouter LLM fallback ———————————————————————

_OPENROUTER_FALLBACK_MODELS: list[str] = []

# ——————————————————————— OpenCode LLM fallback ———————————————————————

_OPENCODE_FALLBACK_MODELS: list[str] = []
_OPENCODE_BASE_URL = "https://opencode.ai/zen/v1"

_HERMES_CODEX_PROVIDER = "openai-codex"
_HERMES_CODEX_API_MODE = "codex_responses"
_HERMES_CODEX_UPSTREAM = "https://chatgpt.com/backend-api/codex"
_HERMES_FREE_DEFAULT_PROVIDER = "gemini"
_HERMES_FREE_DEFAULT_MODEL = "gemini-2.5-flash-lite"
_HERMES_FREE_ALLOWED_SUFFIXES = {
    "openrouter": (":free",),
    "opencode-zen": ("-free",),
    "gemini": ("-flash", "-lite", "-flash-lite", "-preview"),
}


def _read_hermes_api_key(env_var: str) -> str | None:
    """Read an API key from the process env or the Hermes .env file."""
    val = os.environ.get(env_var)
    if val:
        return val
    # Fallback: read from Hermes .env
    hermes_env = Path(os.environ.get("HERMES_HOME", "C:/ProgramData/hermes")) / ".env"
    if not hermes_env.exists():
        return None
    try:
        for line in hermes_env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{env_var}="):
                return line[len(env_var) + 1 :].strip("\"'")
    except OSError:
        pass
    return None


def _read_hermes_config_value(key: str) -> str | None:
    """Read a top-level scalar from Hermes config.yaml without adding YAML deps."""
    hermes_config = Path(os.environ.get("HERMES_HOME", "C:/ProgramData/hermes")) / "config.yaml"
    if not hermes_config.exists():
        return None
    try:
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*:\s*(.+?)\s*$")
        for line in hermes_config.read_text(encoding="utf-8").splitlines():
            match = pattern.match(line)
            if match:
                return match.group(1).strip().strip("\"'")
    except OSError:
        return None
    return None


def _is_openai_codex_model(model: str) -> bool:
    """Return whether a configured model is an OpenAI GPT/Codex model name."""
    return model.strip().lower().startswith("gpt-")


def _read_hermes_top_level_model_block(config_path: Path) -> dict[str, str]:
    """Read only the immediate children of Hermes' top-level ``model`` block.

    This deliberately small parser avoids trusting similarly named nested provider
    blocks. Unsupported/ambiguous YAML fails closed in the attestation below.
    """
    text = config_path.read_text(encoding="utf-8")
    values: dict[str, str] = {}
    in_model = False
    child_indent: int | None = None
    model_blocks = 0

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or stripped == "---":
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        if indent == 0:
            if re.fullmatch(r"model\s*:\s*(?:#.*)?", stripped):
                model_blocks += 1
                if model_blocks > 1:
                    raise ValueError("multiple top-level model blocks")
                in_model = True
                child_indent = None
                continue
            if in_model:
                break
            continue

        if not in_model:
            continue
        if "\t" in raw_line[: len(raw_line) - len(raw_line.lstrip())]:
            raise ValueError("tabs are not supported in the model block")

        match = re.match(r"^\s+([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*?)\s*$", raw_line)
        if not match:
            continue
        if child_indent is None:
            child_indent = indent
        if indent != child_indent:
            continue

        key, raw_value = match.groups()
        if key in values:
            raise ValueError(f"duplicate model key: {key}")
        value = raw_value.split(" #", 1)[0].strip().strip("\"'")
        values[key] = value

    if model_blocks != 1:
        raise ValueError("missing top-level model block")
    return values


def _hermes_openai_codex_attestation(config_path: Path | None = None) -> tuple[bool, str]:
    """Attest that the local Hermes gateway is backed by OpenAI Codex only.

    The second tuple item is the attested model on success and a safe diagnostic
    on failure. No request is sent to Hermes unless this check succeeds.
    """
    path = config_path or Path(os.environ.get("HERMES_HOME", "C:/ProgramData/hermes")) / "config.yaml"
    try:
        model_config = _read_hermes_top_level_model_block(path)
    except (OSError, UnicodeError, ValueError) as exc:
        return False, f"cannot attest {path}: {exc}"

    provider = model_config.get("provider", "").strip().lower()
    api_mode = model_config.get("api_mode", "").strip().lower()
    base_url = model_config.get("base_url", "").strip()
    default_model = model_config.get("default", "").strip()

    if provider != _HERMES_CODEX_PROVIDER:
        return False, f"provider must be {_HERMES_CODEX_PROVIDER!r}, got {provider or '<missing>'!r}"
    if api_mode != _HERMES_CODEX_API_MODE:
        return False, f"api_mode must be {_HERMES_CODEX_API_MODE!r}, got {api_mode or '<missing>'!r}"
    if base_url != _HERMES_CODEX_UPSTREAM:
        return False, f"base_url must be {_HERMES_CODEX_UPSTREAM!r}, got {base_url or '<missing>'!r}"
    if not _is_openai_codex_model(default_model):
        return False, f"default model must start with 'gpt-', got {default_model or '<missing>'!r}"
    return True, default_model


@dataclass(frozen=True)
class _HermesArticleResult:
    article: dict | None
    outcome: str
    detail: str = ""
    status_code: int | None = None

    @property
    def permits_free_fallback(self) -> bool:
        return self.outcome == "availability_failure"


def _hermes_free_article_target(value: str | None = None) -> tuple[bool, tuple[str, str] | str]:
    """Attest one free Hermes CLI provider/model target from a singular env value."""

    configured = (
        value
        if value is not None
        else os.environ.get(
            "RANKSTEIN_HERMES_FREE_ARTICLE_MODEL",
            f"{_HERMES_FREE_DEFAULT_PROVIDER}:{_HERMES_FREE_DEFAULT_MODEL}",
        )
    ).strip()
    provider, separator, model = configured.partition(":")
    provider = provider.strip()
    model = model.strip()
    if not separator or not provider or not model:
        return False, "free article model must use provider:model"
    suffixes = _HERMES_FREE_ALLOWED_SUFFIXES.get(provider)
    if suffixes is None:
        return False, f"free article provider is not approved: {provider!r}"
    if isinstance(suffixes, str):
        suffixes = (suffixes,)
    if not any(model.endswith(sfx) for sfx in suffixes):
        return (
            False,
            f"free article model for {provider} must end with an approved suffix ({', '.join(suffixes)})",
        )
    if not re.fullmatch(r"[A-Za-z0-9._/:-]+", model):
        return False, "free article model contains unsupported characters"
    return True, (provider, model)


def _hermes_free_article_timeout_seconds() -> int:
    """Return the free-writer timeout, constrained to a hard 900-second cap."""

    try:
        configured = int(os.environ.get("RANKSTEIN_HERMES_FREE_ARTICLE_TIMEOUT", "600"))
    except ValueError:
        configured = 600
    return max(1, min(configured, 900))


def _hermes_codex_article_timeout_seconds() -> int:
    """Return the total Codex HTTP deadline, constrained to 30–900 seconds."""

    try:
        configured = int(os.environ.get("RANKSTEIN_HERMES_CODEX_TIMEOUT", "600"))
    except ValueError:
        configured = 600
    return max(30, min(configured, 900))


_HERMES_ARTICLE_HTTP_WORKER = """
import json
import sys
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
try:
    post = Request(
        request["url"],
        data=json.dumps(request["payload"], ensure_ascii=False).encode("utf-8"),
        headers=request["headers"],
        method="POST",
    )
    try:
        response = urlopen(post, timeout=request["timeout"])
    except HTTPError as error:
        response = error
    with response:
        body = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        result = {"status_code": response.status, "body": body}
except TimeoutError:
    result = {"error": "timeout"}
except URLError as error:
    result = {"error": "timeout" if isinstance(error.reason, TimeoutError) else "connection"}
except (HTTPException, OSError):
    result = {"error": "transport"}
sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
"""


@dataclass(frozen=True)
class _HermesHttpResponse:
    status_code: int
    text: str

    def json(self) -> dict:
        return json.loads(self.text)


async def _bounded_hermes_article_http(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict,
    timeout: float,
) -> _HermesHttpResponse:
    """One POST in an owned process: trickling bytes cannot extend its deadline.

    Credentials and prompts travel over stdin, never command-line arguments.
    Cleanup is completed before propagating cancellation or a deadline failure;
    no executor thread remains blocked in network I/O after the coroutine exits.
    """

    process = None
    started_at = asyncio.get_running_loop().time()
    request = json.dumps(
        {"url": url, "headers": headers, "payload": payload, "timeout": timeout},
        ensure_ascii=False,
    ).encode("utf-8")
    try:
        process = await _create_owned_subprocess(
            sys.executable,
            "-I",
            "-u",
            "-c",
            _HERMES_ARTICLE_HTTP_WORKER,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=clean_python_env(),
        )
        remaining = max(0.001, timeout - (asyncio.get_running_loop().time() - started_at))
        try:
            stdout, _stderr = await asyncio.wait_for(process.communicate(request), timeout=remaining)
        except TimeoutError as exc:
            raise requests.exceptions.Timeout("Hermes article total HTTP deadline exceeded") from exc
        if process.returncode != 0:
            raise RuntimeError("Hermes article HTTP worker failed")
        result = json.loads(stdout)
        error = result.get("error")
        if error == "timeout":
            raise requests.exceptions.Timeout("Hermes article HTTP socket timed out")
        if error == "connection":
            raise requests.exceptions.ConnectionError("Hermes article HTTP connection failed")
        if error == "transport":
            raise requests.exceptions.RequestException("Hermes article HTTP transport failed")
        return _HermesHttpResponse(int(result["status_code"]), result["body"])
    finally:
        await _cleanup_owned_process(process)


def _hermes_status_is_availability_failure(status_code: int) -> bool:
    return status_code in {401, 402, 403, 404, 408, 425, 429} or status_code >= 500


def _build_generation_prompt(keyword: str, domain: Domain, source_material: str = "") -> str:
    """Build the LLM prompt for generating a Spanish recipe article JSON."""
    author = (
        "Atelier editorial de RecetaDolce" if "dolce" in domain.handle else "Equipo editorial de RecetaGenial"
    )
    source_instruction = (
        "\n\nCRITICAL SOURCE RULES:\n"
        "You have been given real scraped recipe articles above. You MUST:\n"
        "1. COMBINE the best elements from all sources into ONE unified recipe.\n"
        "2. Use the real ingredients and quantities found in the sources.\n"
        "3. Use the real cooking steps and techniques found in the sources.\n"
        "4. REPHRASE everything in your own words — never copy a sentence verbatim.\n"
        "5. The result must be a single cohesive article, not a list of sources.\n"
        if source_material
        else ""
    )
    return (
        "You are an expert Spanish recipe content writer for food blogs. "
        "Write ONLY valid JSON — no markdown fences, no explanation.\n\n"
        "Produce a JSON object with EXACTLY these keys (all required):\n"
        "  title (str): Spanish recipe title, capitalize first letter\n"
        "  slug (str): URL-safe version of the title\n"
        "  excerpt (str): One-sentence concise summary, strictly under 150 characters\n"
        f"  category (str): One of: {', '.join(domain.categories or ('Postres', 'Aperitivos'))}\n"
        "  keywords (list[str]): 3-5 relevant Spanish keywords\n"
        "  difficulty (str): Facil | Media | Dificil\n"
        "  prep_time (int): Minutes\n"
        "  cook_time (int): Minutes\n"
        "  image_alt (str): Descriptive Spanish alt text for the hero image\n"
        "  hero_image_prompt (str): Production image prompt for the actual finished dish hero image\n"
        "  pinterest_pin_prompt (str): Production vertical 2:3 image prompt for the same dish and destination pin\n"
        "  image_negative_prompt (str): Negative prompt forbidding text, logos, watermarks, fake URLs, distorted food\n"
        "  chef_tip (str): Practical cooking tip in Spanish\n"
        "  recipe_schema (dict): Full Schema.org Recipe with real "
        "recipeIngredient (at least 6 detailed strings with quantities), recipeInstructions "
        "(at least 6 HowToStep objects with @type and text), prepTime/cookTime/totalTime "
        "in ISO 8601 (e.g. PT20M, PT40M, PT60M), recipeYield (e.g. '8 raciones'), recipeCuisine='Española', "
        f"recipeCategory, name, description, author ({author})\n"
        "  content (str): Comprehensive, highly engaging article markdown in Spanish (es-ES). "
        "CRITICAL REQUIREMENT: Content MUST be between 1000 and 1500 words (strictly minimum 950 words). "
        "Organize with clear Markdown headings: ## Origen y Por Qué Funciona Esta Receta, ## Ingredientes Clave y Sustituciones, "
        "## Guía Paso a Paso Detallada, ## El Truco del Chef para un Resultado Perfecto, ## Conservación y Congelación, and ## Preguntas Frecuentes. "
        "Use bold text (**ingrediente**) for key terms. Insert [HERO_IMAGE] where the hero photo belongs. "
        "Include first-person culinary reflections (e.g., 'en mi cocina...', 'en mi experiencia...') and "
        "cite standard Spanish food safety guidelines (e.g. 'según las recomendaciones de AESAN sobre higiene y temperaturas...').\n"
        "  faq_schema (list[dict]): AT LEAST 3 to 4 detailed entries, each with 'question' and 'answer' in Spanish\n\n"
        f"BRAND VOICE: The article is for {domain.display_name} (niche: {domain.niche}).\n"
        f"{recipe_generation_visual_requirements(keyword, domain)}\n"
        f"{source_material}\n"
        f"{source_instruction}"
        f"Write naturally in Spanish (es-ES), not English.\n"
        f"AUTHOR NAME: {author}\n\n"
        f'KEYWORD: "{keyword}"\n\n'
        "OUTPUT ONLY THE JSON OBJECT. No markdown fences. No preamble.\n"
    )


def _repair_truncated_json(s: str) -> str:
    """Attempt to repair truncated JSON strings by balancing unclosed quotes, brackets, and braces."""
    s = s.strip()
    s = re.sub(r",\s*$", "", s)
    in_str = False
    esc = False
    for char in s:
        if esc:
            esc = False
        elif char == "\\":
            esc = True
        elif char == '"':
            in_str = not in_str
    if in_str:
        s += '"'
    open_braces = 0
    open_brackets = 0
    in_s = False
    e = False
    for char in s:
        if e:
            e = False
        elif char == "\\":
            e = True
        elif char == '"':
            in_s = not in_s
        elif not in_s:
            if char == "{":
                open_braces += 1
            elif char == "}":
                open_braces -= 1
            elif char == "[":
                open_brackets += 1
            elif char == "]":
                open_brackets -= 1
    s = re.sub(r",\s*$", "", s)
    s += "]" * max(0, open_brackets)
    s += "}" * max(0, open_braces)
    return s


def _parse_llm_json_response(content: str) -> dict | None:
    """Parse JSON from an LLM response, stripping markdown fences and thinking blocks."""
    if not content or len(content) < 300:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    # Strip <think> blocks common in reasoning models (deepseek, minimax)
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL)
    cleaned = cleaned.strip()
    required = {"title", "slug", "content", "excerpt", "category", "recipe_schema"}

    # Try direct parse first
    for candidate in (cleaned, _repair_truncated_json(cleaned)):
        try:
            article = json.loads(candidate, strict=False)
            if required.issubset(article.keys()) and len(article.get("content", "")) > 500:
                return article
        except json.JSONDecodeError:
            pass

    # Fallback: find outer JSON object via greedy regex
    match = re.search(r"(\{[\s\S]*\})", cleaned)
    if match:
        for candidate in (match.group(1), _repair_truncated_json(match.group(1))):
            try:
                article = json.loads(candidate, strict=False)
                if required.issubset(article.keys()) and len(article.get("content", "")) > 500:
                    return article
            except json.JSONDecodeError:
                pass
    return None


async def _call_codex_cli_for_article(keyword: str, domain: Domain, source_material: str = "") -> dict | None:
    """Generate article JSON through OpenAI Codex CLI with ChatGPT subscription.

    Uses the local Codex CLI (gpt-5.5) for cost-effective article generation.
    No API key required — uses ChatGPT OAuth subscription.
    """
    if os.environ.get("RANKSTEIN_ENABLE_CODEX_CLI_ARTICLES", "1").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        logger.info("Codex CLI article generation disabled by env")
        return None

    codex_bin = os.environ.get(
        "RANKSTEIN_CODEX_CLI_PATH",
        str(Path.home() / "AppData" / "Local" / "OpenAI" / "Codex" / "bin" / "codex.exe"),
    )
    model = os.environ.get("RANKSTEIN_CODEX_CLI_MODEL", "gpt-5.5")
    if not _is_openai_codex_model(model):
        logger.error(
            "Codex CLI article generation blocked: model %r is not an attested gpt-* model",
            model,
        )
        return None

    generation_prompt = _build_generation_prompt(keyword, domain, source_material=source_material)
    system_prompt = (
        "You are RankStein's article generator. Return only the requested JSON object. "
        "Do not browse, call tools, or include markdown fences."
    )

    cmd = [
        codex_bin,
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--model",
        model,
        "--config",
        f"system_prompt={json.dumps(system_prompt)}",
        generation_prompt,
    ]

    env = os.environ.copy()
    env.pop("GOOGLE_API_KEY", None)
    env.pop("GEMINI_API_KEY", None)
    env.pop("MCP_GEMINI_API_KEY", None)
    env.pop("MCP_GOOGLE_API_KEY", None)

    process = None
    try:
        logger.info("Invoking Codex CLI model=%s for %s", model, keyword)
        process = await _create_owned_subprocess(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=int(os.environ.get("RANKSTEIN_CODEX_CLI_TIMEOUT", "300")),
        )
        output = stdout.decode(errors="replace")
        stderr_text = stderr.decode(errors="replace")

        if process.returncode != 0:
            logger.warning("Codex CLI failed for %s: %s", keyword, stderr_text[-500:])
            return None

        # Extract the article JSON from the output
        article = _parse_llm_json_response(output)
        if article:
            logger.info(
                "Codex CLI model=%s succeeded for %s (%d chars content)",
                model,
                keyword,
                len(article.get("content", "")),
            )
            return article
        logger.warning("Codex CLI returned incomplete JSON for %s", keyword)
        return None
    except TimeoutError:
        logger.warning("Codex CLI timed out for %s", keyword)
        return None
    except Exception as exc:
        logger.warning("Codex CLI exception for %s: %s", keyword, exc)
        return None
    finally:
        await _cleanup_owned_process(process)


async def _call_hermes_codex_for_article_result(
    keyword: str,
    domain: Domain,
    source_material: str = "",
) -> _HermesArticleResult:
    """Make one attested Codex-gateway request and classify any failure."""

    if os.environ.get("RANKSTEIN_ENABLE_HERMES_CODEX_ARTICLES", "1").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return _HermesArticleResult(None, "policy_failure", "Hermes Codex disabled")

    attested, attestation_detail = _hermes_openai_codex_attestation()
    if not attested:
        logger.error("Hermes Codex article generation blocked: %s", attestation_detail)
        return _HermesArticleResult(None, "policy_failure", attestation_detail)
    attested_model = attestation_detail

    base_url = os.environ.get("RANKSTEIN_HERMES_CODEX_URL", "http://127.0.0.1:8642/v1").rstrip("/")
    api_model_alias = (
        os.environ.get("RANKSTEIN_HERMES_CODEX_MODEL")
        or _read_hermes_config_value("API_SERVER_MODEL_NAME")
        or "Hermes Agent"
    )
    api_key = (
        os.environ.get("RANKSTEIN_HERMES_CODEX_API_KEY")
        or os.environ.get("API_SERVER_KEY")
        or _read_hermes_api_key("API_SERVER_KEY")
        or _read_hermes_config_value("API_SERVER_KEY")
    )
    if not api_key:
        logger.warning("Hermes Codex article generation skipped: missing API_SERVER_KEY")
        return _HermesArticleResult(None, "policy_failure", "missing API_SERVER_KEY")

    generation_prompt = _build_generation_prompt(keyword, domain, source_material=source_material)
    system_prompt = (
        "You are RankStein's article generator. Return only the requested JSON object. "
        "Do not browse, call tools, mention Hermes, or include markdown fences."
    )
    try:
        logger.info(
            "Invoking attested Hermes OpenAI Codex primary_model=%s api_alias=%s for %s",
            attested_model,
            api_model_alias,
            keyword,
        )
        resp = await _bounded_hermes_article_http(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            payload={
                "model": api_model_alias,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": generation_prompt},
                ],
                "temperature": 0.65,
                "max_tokens": 16384,
                "stream": False,
                "tools": [],
                "tool_choice": "none",
            },
            timeout=_hermes_codex_article_timeout_seconds(),
        )
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
        logger.warning("Hermes Codex gateway unavailable for %s: %s", keyword, type(exc).__name__)
        return _HermesArticleResult(None, "availability_failure", type(exc).__name__)
    except requests.exceptions.RequestException as exc:
        logger.warning("Hermes Codex transport failed for %s: %s", keyword, type(exc).__name__)
        return _HermesArticleResult(None, "availability_failure", type(exc).__name__)
    except Exception as exc:
        logger.warning("Hermes Codex article provider exception for %s: %s", keyword, exc)
        return _HermesArticleResult(None, "internal_failure", type(exc).__name__)

    if resp.status_code != 200:
        availability_failure = _hermes_status_is_availability_failure(resp.status_code)
        logger.warning("Hermes Codex article provider status=%s for %s", resp.status_code, keyword)
        return _HermesArticleResult(
            None,
            "availability_failure" if availability_failure else "request_rejected",
            f"HTTP {resp.status_code}",
            status_code=resp.status_code,
        )

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        logger.warning("Hermes Codex returned malformed response for %s: %s", keyword, exc)
        return _HermesArticleResult(None, "content_rejected", "malformed HTTP 200 response", 200)

    article = _parse_llm_json_response(content)
    if not article:
        content_lower = (content or "").lower()
        if any(
            marker in content_lower for marker in ("429", "usage limit", "rate limit", "capacity", "quota")
        ):
            logger.warning(
                "Hermes Codex gateway returned rate limit payload for %s: %r", keyword, (content or "")[:150]
            )
            return _HermesArticleResult(None, "availability_failure", "rate limit payload", 429)
        logger.warning(
            "Hermes Codex returned incomplete article JSON for %s (len=%d, start=%r, end=%r)",
            keyword,
            len(content or ""),
            (content or "")[:200],
            (content or "")[-200:],
        )
        return _HermesArticleResult(None, "content_rejected", "incomplete article JSON", 200)
    if not _openrouter_article_quality_check(article):
        logger.warning("Hermes Codex article failed the quality gate for %s", keyword)
        return _HermesArticleResult(None, "content_rejected", "article quality gate failed", 200)

    logger.info(
        "Hermes Codex returned complete article JSON for %s (%d chars content)",
        keyword,
        len(article.get("content", "")),
    )
    return _HermesArticleResult(article, "success", status_code=200)


async def _call_hermes_codex_for_article(
    keyword: str,
    domain: Domain,
    source_material: str = "",
) -> dict | None:
    """Compatibility wrapper returning only the attested Codex article."""

    result = await _call_hermes_codex_for_article_result(keyword, domain, source_material)
    return result.article


async def _call_hermes_free_for_article(
    keyword: str,
    domain: Domain,
    source_material: str = "",
) -> dict | None:
    """Invoke one attested free model through the maintained Hermes CLI."""

    target_attested, target_detail = _hermes_free_article_target()
    if not target_attested:
        logger.error("Hermes free article fallback blocked: %s", target_detail)
        return None
    provider, model = target_detail
    hermes_home = Path(os.environ.get("HERMES_HOME", "C:/ProgramData/hermes"))
    hermes_cli = os.environ.get(
        "RANKSTEIN_HERMES_CLI_PATH",
        str(hermes_home / "hermes-agent" / "venv" / "Scripts" / "hermes.exe"),
    )
    system_prompt = (
        "You are RankStein's article generator. Return only the requested JSON object. "
        "Do not browse, call tools, mention Hermes, or include markdown fences."
    )
    generation_prompt = _build_generation_prompt(keyword, domain, source_material=source_material)
    strict_prompt = f"{system_prompt}\n\n{generation_prompt}"
    # Tier A: Direct in-process Hermes agent invocation (avoids Windows CLI pipe truncation)
    try:
        hermes_agent_dir = str(hermes_home / "hermes-agent")
        if os.path.isdir(hermes_agent_dir) and hermes_agent_dir not in sys.path:
            sys.path.insert(0, hermes_agent_dir)

        from hermes_cli.runtime_provider import resolve_runtime_provider
        from run_agent import AIAgent

        runtime = resolve_runtime_provider(requested=provider, target_model=model)
        if runtime.get("api_key") or runtime.get("base_url"):
            logger.info(
                "Hermes Codex first with free-provider fallback is invoking in-process %s/%s for %s",
                provider,
                model,
                keyword,
            )
            agent = AIAgent(
                api_key=runtime.get("api_key"),
                base_url=runtime.get("base_url"),
                provider=runtime.get("provider"),
                api_mode=runtime.get("api_mode"),
                model=model,
                quiet_mode=True,
                platform="cli",
            )
            agent.suppress_status_output = True
            loop_res = await asyncio.to_thread(agent.run_conversation, strict_prompt)
            raw_output = loop_res.get("final_response") or ""
            if raw_output:
                article = _parse_llm_json_response(raw_output)
                if article and _openrouter_article_quality_check(article):
                    logger.info(
                        "Hermes free article writer in-process %s/%s succeeded for %s (%d chars content)",
                        provider,
                        model,
                        keyword,
                        len(article.get("content", "")),
                    )
                    return article
                logger.warning(
                    "Hermes in-process generation produced unparseable response (len=%d), falling back to CLI subprocess",
                    len(raw_output),
                )
    except Exception as exc:
        logger.warning(
            "Hermes in-process conversation attempt raised (%s); proceeding to CLI subprocess", exc
        )

    command = [
        hermes_cli,
        "--ignore-user-config",
        "--ignore-rules",
        "--provider",
        provider,
        "--model",
        model,
        "-z",
        strict_prompt,
    ]
    subprocess_env = os.environ.copy()
    subprocess_env["HERMES_HOME"] = str(hermes_home)
    subprocess_env["PYTHONIOENCODING"] = "utf-8"
    subprocess_env["PYTHONUTF8"] = "1"

    process = None
    try:
        logger.info(
            "Hermes Codex first with free-provider fallback is invoking %s/%s for %s",
            provider,
            model,
            keyword,
        )
        process = await _create_owned_subprocess(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=subprocess_env,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=_hermes_free_article_timeout_seconds(),
        )
    except TimeoutError:
        logger.warning("Hermes free article writer timed out for %s", keyword)
        return None
    except Exception as exc:
        logger.warning("Hermes free article writer failed for %s: %s", keyword, exc)
        return None
    finally:
        await _cleanup_owned_process(process)

    if process.returncode != 0:
        stderr_text = stderr.decode(errors="replace")
        logger.warning(
            "Hermes free article writer exited %s for %s: %s",
            process.returncode,
            keyword,
            stderr_text[-500:],
        )
        return None

    try:
        raw_stdout = stdout.decode("utf-8")
    except UnicodeDecodeError:
        try:
            raw_stdout = stdout.decode("cp1252")
        except Exception:
            raw_stdout = stdout.decode(errors="replace")
    article = _parse_llm_json_response(raw_stdout)
    if not article:
        logger.warning(
            "Hermes free article writer JSON parse failed for %s (stdout len=%d, preview: %r)",
            keyword,
            len(raw_stdout),
            raw_stdout[:300],
        )
        return None
    if not _openrouter_article_quality_check(article):
        logger.warning("Hermes free article writer quality check failed for %s", keyword)
        return None
    logger.info(
        "Hermes free article writer %s/%s succeeded for %s (%d chars content)",
        provider,
        model,
        keyword,
        len(article.get("content", "")),
    )
    return article


async def _call_omniroute_for_article(
    keyword: str,
    domain: Domain,
    source_material: str = "",
) -> dict | None:
    """Generate article JSON via local OmniRoute AI gateway."""
    if os.environ.get("RANKSTEIN_ENABLE_OMNIROUTE_FALLBACK", "1").strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        return None

    base_url = os.environ.get("RANKSTEIN_OMNIROUTE_URL", "http://127.0.0.1:20128/v1").rstrip("/")
    api_key = os.environ.get("RANKSTEIN_OMNIROUTE_API_KEY", "").strip()
    model = os.environ.get("RANKSTEIN_OMNIROUTE_MODEL", "freee").strip()

    if not api_key:
        logger.warning("OmniRoute article fallback skipped: missing RANKSTEIN_OMNIROUTE_API_KEY")
        return None

    generation_prompt = _build_generation_prompt(keyword, domain, source_material=source_material)
    system_prompt = (
        "You are RankStein's article generator. Return only the requested JSON object. "
        "Do not browse, call tools, mention OmniRoute, or include markdown fences."
    )

    try:
        timeout = int(os.environ.get("RANKSTEIN_OMNIROUTE_TIMEOUT", "300"))
    except ValueError:
        timeout = 300

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": generation_prompt},
        ],
        "temperature": 0.65,
        "max_tokens": 16384,
    }

    try:
        logger.info(
            "Invoking OmniRoute model=%s at %s for %s",
            model,
            base_url,
            keyword,
        )
        resp = await _bounded_hermes_article_http(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            payload=payload,
            timeout=timeout,
        )
        if resp.status_code != 200:
            logger.warning("OmniRoute article provider status=%s for %s", resp.status_code, keyword)
            return None

        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.warning("OmniRoute article call exception for %s: %s", keyword, exc)
        return None

    article = _parse_llm_json_response(content)
    if not article:
        logger.warning("OmniRoute returned incomplete JSON for %s", keyword)
        return None

    if not _openrouter_article_quality_check(article):
        logger.warning("OmniRoute article failed the quality gate for %s", keyword)
        return None

    logger.info(
        "OmniRoute model=%s succeeded for %s (%d chars content)",
        model,
        keyword,
        len(article.get("content", "")),
    )
    return article


async def _call_gemini_api_for_article(
    keyword: str, domain: Domain, source_material: str = ""
) -> dict | None:
    """Generate article JSON directly using Gemini REST API with GEMINI_API_KEY / GOOGLE_API_KEY."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        logger.warning("No GEMINI_API_KEY or GOOGLE_API_KEY available for direct Gemini API call")
        return None

    prompt = _build_generation_prompt(keyword, domain, source_material=source_material)
    system_instruction = "You are a professional recipe article generator for RankStein. Output ONLY valid, complete JSON matching the requested schema."
    models = [
        "gemini-3.8-flash",
        "gemini-3.6-flash",
        "gemini-flash-latest",
        "gemini-3.7-flash",
    ]
    session = _get_session()

    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "system_instruction": {"parts": [{"text": system_instruction}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.7,
                "maxOutputTokens": 16384,
            },
        }
        try:
            logger.info("Invoking Gemini REST API model=%s for %s", model, keyword)

            def _post_gemini(u=url, p=payload):
                if primp:
                    client = primp.Client(impersonate="random", timeout=180)
                    return client.post(u, json=p)
                return requests.post(u, json=p, timeout=180)

            resp = await asyncio.get_event_loop().run_in_executor(None, _post_gemini)
            if resp.status_code == 200:
                data = resp.json()
                try:
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                    article = _parse_llm_json_response(text)
                    if article:
                        logger.info(
                            "Gemini REST API model=%s generated valid article JSON for %s", model, keyword
                        )
                        return article
                    logger.warning(
                        "Gemini REST API model=%s response for %s was not parseable JSON: len=%d preview=%r tail=%r",
                        model,
                        keyword,
                        len(text),
                        text[:300],
                        text[-300:],
                    )
                except (KeyError, IndexError, TypeError) as parse_err:
                    logger.warning(
                        "Gemini REST API model=%s response parse error for %s: %s", model, keyword, parse_err
                    )
            else:
                logger.warning(
                    "Gemini REST API model=%s returned HTTP %d for %s: %s",
                    model,
                    resp.status_code,
                    keyword,
                    resp.text[:300],
                )
        except Exception as exc:
            logger.warning("Gemini REST API model=%s call exception for %s: %s", model, keyword, exc)
    return None


async def _call_nvidia_nemotron_for_article(
    keyword: str, domain: Domain, source_material: str = ""
) -> dict | None:
    """Retired direct NVIDIA path; free models must run through Hermes."""

    logger.error("Direct NVIDIA article generation is disabled; use the Hermes CLI fallback")
    return None


async def _call_openrouter_for_article(
    prompt: str, keyword: str, domain: Domain, source_material: str = ""
) -> dict | None:
    """Generate article JSON via OpenRouter API when all Gemini models are exhausted.

    Sends a modified prompt (no MCP tool calls — just content generation) to
    each model in the fallback list. Returns the parsed article JSON dict on
    first success, or None if every model fails.
    """
    logger.error("OpenRouter article generation is permanently disabled; OpenAI Codex is required")
    return None

    api_key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.warning("No OpenRouter/OpenAI API key available for OpenRouter fallback")
        return None

    session = _get_session()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": f"https://{domain.domain}",
        "X-Title": f"RankStein-{domain.handle}",
    }

    generation_prompt = _build_generation_prompt(keyword, domain, source_material=source_material)

    for model in _OPENROUTER_FALLBACK_MODELS:
        logger.info("Invoking OpenRouter model=%s for %s", model, keyword)
        try:
            resp = session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": generation_prompt}],
                    "temperature": 0.7,
                    "max_tokens": 16384,
                },
                timeout=600,
            )
            if resp.status_code == 200:
                data = resp.json()
                article = _parse_llm_json_response(data["choices"][0]["message"]["content"])
                if article:
                    logger.info(
                        "OpenRouter model=%s succeeded for %s (%d chars content)",
                        model,
                        keyword,
                        len(article["content"]),
                    )
                    return article
                logger.warning(
                    "OpenRouter model=%s returned incomplete JSON for %s (missing keys or short content)",
                    model,
                    keyword,
                )
            elif resp.status_code == 402:
                logger.warning("OpenRouter model=%s insufficient credits for %s", model, keyword)
                continue
            else:
                logger.warning(
                    "OpenRouter model=%s status=%s for %s: %s",
                    model,
                    resp.status_code,
                    keyword,
                    resp.text[:300],
                )
                continue
        except json.JSONDecodeError:
            logger.warning("OpenRouter model=%s returned invalid JSON for %s", model, keyword)
            continue
        except Exception as exc:
            logger.warning("OpenRouter model=%s exception for %s: %s", model, keyword, exc)
            continue

    return None


async def _call_opencode_for_article(keyword: str, domain: Domain, source_material: str = "") -> dict | None:
    """Generate article JSON via the OpenCode API (Hermes agent's own provider).

    Reads the API key from OPENCODE_ZEN_API_KEY or OPENCODE_API_KEY env var,
    falling back to the Hermes .env file. Uses the same generation prompt as
    OpenRouter. Returns parsed article dict or None.
    """
    logger.error("OpenCode article generation is permanently disabled; OpenAI Codex is required")
    return None

    api_key = _read_hermes_api_key("OPENCODE_ZEN_API_KEY")
    if not api_key:
        api_key = _read_hermes_api_key("OPENCODE_API_KEY")
    if not api_key:
        logger.warning("No OpenCode API key available (OPENCODE_ZEN_API_KEY or OPENCODE_API_KEY)")
        return None

    session = _get_session()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": f"https://{domain.domain}",
        "X-Title": f"RankStein-{domain.handle}",
    }

    generation_prompt = _build_generation_prompt(keyword, domain, source_material=source_material)

    for model in _OPENCODE_FALLBACK_MODELS:
        max_retries = 5
        for attempt in range(max_retries):
            logger.info(
                "Invoking OpenCode model=%s for %s (attempt %d/%d)", model, keyword, attempt + 1, max_retries
            )
            try:
                resp = session.post(
                    f"{_OPENCODE_BASE_URL}/chat/completions",
                    headers=headers,
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": generation_prompt}],
                        "temperature": 0.7,
                        "max_tokens": 16384,
                    },
                    timeout=600,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    article = _parse_llm_json_response(data["choices"][0]["message"]["content"])
                    if article:
                        logger.info(
                            "OpenCode model=%s succeeded for %s (%d chars content)",
                            model,
                            keyword,
                            len(article["content"]),
                        )
                        return article
                    logger.warning(
                        "OpenCode model=%s returned incomplete JSON for %s",
                        model,
                        keyword,
                    )
                elif resp.status_code == 500:
                    logger.warning(
                        "OpenCode model=%s status=500 for %s: %s",
                        model,
                        keyword,
                        resp.text[:200],
                    )
                    break  # server error won't fix on retry
                else:
                    logger.warning(
                        "OpenCode model=%s status=%s for %s: %s",
                        model,
                        resp.status_code,
                        keyword,
                        resp.text[:200],
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(5)
                        continue
                    break
            except Exception as exc:
                logger.warning("OpenCode model=%s exception for %s: %s", model, keyword, exc)
                if attempt < max_retries - 1:
                    await asyncio.sleep(5)
                    continue
                break

    return None


def _openrouter_article_quality_check(article: dict) -> bool:
    """Quick quality gate for OpenRouter-generated articles before publishing."""
    required_keys = {"title", "slug", "content", "excerpt", "category", "recipe_schema"}
    ok = True
    for key in required_keys:
        if key not in article:
            logger.warning("OpenRouter fallback article missing key: %s", key)
            ok = False
    content = article.get("content", "")
    if len(content) < 500:
        logger.warning("OpenRouter fallback content too short: %d chars", len(content))
        ok = False
    category = article.get("category", "")
    if not category:
        logger.warning("OpenRouter fallback article missing category")
        ok = False
    checks = {"keys_present": ok, "content_length": len(content) > 500, "has_category": bool(category)}
    if not all(checks.values()):
        logger.warning(
            "OpenRouter fallback quality check partial failure: %s",
            {k: v for k, v in checks.items()},
        )
    return ok


def _strip_gemini_cli_noise(stderr_text: str) -> str:
    """Remove cosmetic Gemini CLI terminal warnings from stderr.

    The Gemini CLI can emit terminal capability warnings on stderr even when the
    real failure is elsewhere (or when it produced no model response). Those
    warnings are safe to ignore and confuse error detection.
    """
    ignore_patterns = ("warning", "warn", "\\x1b[", "terminal", "stderr", "isatty")
    lines = stderr_text.splitlines()
    cleaned_lines = []
    for line in lines:
        if not line.strip():
            continue
        lower = line.lower()
        if any(p in lower for p in ignore_patterns):
            continue
        if line.strip():
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def _is_retryable_model_error(stderr_text: str) -> bool:
    stderr_text = _strip_gemini_cli_noise(stderr_text)
    retryable_markers = (
        "rate limit",
        "rate_limit",
        "capacity",
        "unavailable",
        "service busy",
        "try again",
        "temporarily",
        "exhausted your capacity",
        "quota",
    )
    return any(marker.lower() in stderr_text.lower() for marker in retryable_markers)


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


def _ascii_fold(text: object) -> str:
    return unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii").lower()


SOURCE_STOPWORDS = {
    "como",
    "para",
    "con",
    "sin",
    "las",
    "los",
    "una",
    "uno",
    "del",
    "de",
    "la",
    "el",
    "y",
    "en",
    "al",
    "estilo",
    "ideas",
}

SOURCE_RECIPE_TERMS = {
    "receta",
    "recetas",
    "cocina",
    "cocinar",
    "ingredientes",
    "preparacion",
    "preparación",
    "plato",
    "postre",
    "ensalada",
    "comida",
    "horno",
    "sarten",
    "sartén",
}


def _source_keyword_tokens(keyword: str) -> set[str]:
    base = {
        tok
        for tok in re.sub(r"[^a-z0-9áéíóúñü]+", " ", (keyword or "").lower()).split()
        if len(tok) >= 3 and tok not in SOURCE_STOPWORDS
    }
    expanded = set(base)
    for tok in base:
        if tok.endswith("s") and len(tok) > 4:
            expanded.add(tok[:-1])
        elif len(tok) > 3:
            expanded.add(f"{tok}s")
    return expanded


def _source_relevant_enough(keyword: str, *parts: str) -> bool:
    haystack = _ascii_fold(" ".join(part or "" for part in parts))
    tokens = set(re.sub(r"[^a-z0-9]+", " ", haystack).split())
    keyword_tokens = {_ascii_fold(tok) for tok in _source_keyword_tokens(keyword)}
    if not keyword_tokens:
        return True
    keyword_hits = len(keyword_tokens & tokens)
    required_hits = min(2, len(keyword_tokens))
    recipe_terms = {_ascii_fold(term) for term in SOURCE_RECIPE_TERMS}
    return keyword_hits >= required_hits and bool(tokens & recipe_terms)


def _normalize_category(
    value: object,
    cluster: str,
    domain: Domain,
    *,
    context: str = "",
) -> str:
    """Map LLM category variants onto the domain's publishable categories."""
    if domain.handle in {"recetadolce", "recetagenial"}:
        return assign_article_category(
            domain_handle=domain.handle,
            categories=domain.categories,
            requested=value or cluster,
            context=context,
        ).category

    categories = list(domain.categories) or ["Aperitivos", "Postres", "Carnes", "Pescados", "Ensaladas"]
    folded = _ascii_fold(value).strip()
    if not folded:
        return _choose_category(cluster, domain)

    by_fold = {_ascii_fold(category): category for category in categories}
    if folded in by_fold:
        return by_fold[folded]

    alias_groups = {
        "Postres": ("postre", "postres", "dulce", "dulces", "reposteria", "pasteleria", "tarta", "flan"),
        "Pasteles": ("pastel", "pasteles", "tarta", "tartas", "cake", "cakes"),
        "Galletas": ("galleta", "galletas", "cookie", "cookies"),
        "Chocolates": ("chocolate", "chocolates", "cacao", "brownie", "trufa", "trufas"),
        "Reposteria": ("reposteria", "pasteleria", "bolleria", "pan dulce"),
        "Helados": ("helado", "helados", "sorbete", "sorbetes"),
        "Aperitivos": ("aperitivo", "aperitivos", "entrante", "entrantes", "tapa", "tapas", "canape"),
        "Ensaladas": ("ensalada", "ensaladas", "salad"),
        "Carnes": (
            "carne",
            "carnes",
            "pollo",
            "ternera",
            "cerdo",
            "cordero",
            "principal",
            "principales",
            "platos principales",
            "segundo",
            "segundos",
        ),
        "Pescados": ("pescado", "pescados", "marisco", "mariscos", "atun", "salmon", "bacalao", "calamar"),
    }
    for canonical, aliases in alias_groups.items():
        if canonical in categories and any(alias in folded for alias in aliases):
            return canonical
        canonical_folded = _ascii_fold(canonical)
        if canonical_folded in by_fold and any(alias in folded for alias in aliases):
            return by_fold[canonical_folded]

    cluster_category = _choose_category(cluster, domain)
    if cluster_category in categories:
        return cluster_category
    return categories[0]


def _normalize_difficulty(value: object) -> str:
    """Map LLM difficulty variants onto the Supabase posts difficulty constraint."""
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").lower()
    if text in {"facil", "facíl", "fácil", "easy", "baja", "low"}:
        return "Fácil"
    if text in {"dificil", "difcil", "hard", "alta", "high"}:
        return "Difícil"
    return "Media"


def _normalize_iso_duration(value: object, default_minutes: int) -> str:
    """Coerce LLM time variants onto Schema.org ISO-8601 recipe durations."""
    text = str(value or "").strip().upper()
    if text.startswith("PT"):
        return text
    minute_match = re.search(r"(\d+)", text)
    minutes = int(minute_match.group(1)) if minute_match else default_minutes
    minutes = max(1, min(minutes, 24 * 60))
    return f"PT{minutes}M"


def _ensure_recipe_schema(
    article: dict, *, keyword: str, cluster: str, domain: Domain, hero_url: str
) -> dict:
    """Fill required Recipe schema fields before the hard quality gate.

    Direct LLM providers often return good prose but omit Schema.org basics
    (name) or use human time strings ("30 minutos"). The validator is
    strict about ISO-8601 so we normalize here.
    """
    raw_schema = article.get("recipe_schema", {})
    if isinstance(raw_schema, str):
        try:
            raw_schema = json.loads(raw_schema)
        except (json.JSONDecodeError, TypeError):
            raw_schema = {}
    if not isinstance(raw_schema, dict):
        raw_schema = {}
    article["recipe_schema"] = raw_schema

    title = article.get("title") or keyword[:1].upper() + keyword[1:]
    category = _normalize_category(
        article.get("category") or cluster,
        cluster,
        domain,
        context=f"{title} {keyword}",
    )
    article["category"] = category

    # Normalise all duration fields to ISO-8601
    raw_schema.setdefault("@context", "https://schema.org")
    raw_schema.setdefault("@type", "Recipe")
    raw_schema.setdefault("name", title)
    raw_schema.setdefault("description", article.get("excerpt", f"Receta de {title}"))
    raw_schema.setdefault("image", hero_url)
    raw_schema["recipeCategory"] = _normalize_category(
        raw_schema.get("recipeCategory") or category,
        cluster,
        domain,
        context=f"{title} {keyword}",
    )
    raw_schema.setdefault("recipeCuisine", "Española")
    raw_schema["prepTime"] = _normalize_iso_duration(
        raw_schema.get("prepTime", article.get("prep_time", 15)), 15
    )
    raw_schema["cookTime"] = _normalize_iso_duration(
        raw_schema.get("cookTime", article.get("cook_time", 30)), 30
    )
    raw_schema["totalTime"] = _normalize_iso_duration(
        raw_schema.get("totalTime", ""),
        15 + int(article.get("cook_time", 30)),
    )
    raw_schema.setdefault("recipeYield", article.get("recipe_yield") or "4 raciones")
    if not raw_schema.get("author"):
        raw_schema["author"] = {
            "@type": "Organization",
            "name": article.get("author")
            or (
                "Atelier editorial de RecetaDolce"
                if "dolce" in domain.handle
                else "Equipo editorial de RecetaGenial"
            ),
        }

    # Ensure recipeIngredient is populated and never empty
    ingredients = (
        raw_schema.get("recipeIngredient")
        or article.get("recipeIngredient")
        or article.get("ingredients")
        or []
    )
    if not ingredients and article.get("content"):
        ing_match = re.search(
            r"#+\s*Ingredientes.*?\n([\s\S]*?)(?=\n#+ |\Z)", article["content"], re.IGNORECASE
        )
        if ing_match:
            for line in ing_match.group(1).splitlines():
                line = line.strip()
                if re.match(r"^[-*•\d.]\s+", line):
                    clean_ing = re.sub(r"^[-*•\d.]\s+", "", line).strip()
                    if clean_ing:
                        ingredients.append(clean_ing)
    if isinstance(ingredients, str):
        ingredients = [i.strip() for i in ingredients.split("\n") if i.strip()]
    if ingredients:
        raw_schema["recipeIngredient"] = ingredients

    # Ensure recipeInstructions is populated and never empty
    instructions = (
        raw_schema.get("recipeInstructions")
        or article.get("recipeInstructions")
        or article.get("instructions")
        or []
    )
    if not instructions and article.get("content"):
        inst_match = re.search(
            r"#+\s*(?:Preparaci[óo]n|Instrucciones|Elaboraci[óo]n|Paso a paso).*?\n([\s\S]*?)(?=\n#+ |\Z)",
            article["content"],
            re.IGNORECASE,
        )
        if inst_match:
            for line in inst_match.group(1).splitlines():
                line = line.strip()
                if re.match(r"^\d+[.)]\s+", line):
                    clean_step = re.sub(r"^\d+[.)]\s+", "", line).strip()
                    if clean_step:
                        instructions.append(clean_step)
    if isinstance(instructions, str):
        instructions = [s.strip() for s in instructions.split("\n") if s.strip()]

    # Normalize instructions to list of HowToStep and attach step images if available
    step_images = article.get("step_images") or []
    normalized_inst = []
    for idx, inst in enumerate(instructions, 1):
        step_obj = {}
        if isinstance(inst, str):
            step_obj = {"@type": "HowToStep", "name": f"Paso {idx}", "text": inst}
        elif isinstance(inst, dict):
            step_obj = dict(inst)
            step_obj.setdefault("@type", "HowToStep")
            step_obj.setdefault("name", f"Paso {idx}")
        else:
            step_obj = {"@type": "HowToStep", "name": f"Paso {idx}", "text": str(inst)}

        # Attach step image if available for this step (match by step_number or index)
        img_url = None
        for s_img in step_images:
            if isinstance(s_img, dict) and s_img.get("step_number") == idx:
                img_url = s_img.get("image_url")
                break
        if not img_url and idx - 1 < len(step_images):
            s_img = step_images[idx - 1]
            img_url = s_img.get("image_url") if isinstance(s_img, dict) else s_img

        if img_url and isinstance(img_url, str) and img_url.startswith("http"):
            step_obj["image"] = img_url

        normalized_inst.append(step_obj)

    if normalized_inst:
        raw_schema["recipeInstructions"] = normalized_inst

    return raw_schema


def _build_article_payload(keyword: str, cluster: str, domain: Domain, hero_url: str) -> dict:
    title = keyword[:1].upper() + keyword[1:]
    category = _normalize_category(cluster, cluster, domain, context=title)
    slug = _slugify(keyword)
    author = (
        "Atelier editorial de RecetaDolce" if "dolce" in domain.handle else "Equipo editorial de RecetaGenial"
    )
    return {
        "title": title,
        "slug": slug,
        "content": (
            f"## Por qué funciona esta receta\n\n"
            f"[HERO_IMAGE]\n\n"
            f"Esta receta de {title} combina ingredientes accesibles con técnicas de cocina clásicas para lograr "
            f"un resultado que sorprende por su sencillez y sabor. En mi cocina, he preparado esta receta "
            f"innumerables veces y cada vez descubro un matiz que la hace especial. La clave está en entender "
            f"cada paso, no solo seguirlo.\n\n"
            f"## Ingredientes\n\n"
            f"- 250 g de ingrediente principal de calidad\n"
            f"- 2 cucharadas de aceite de oliva virgen extra\n"
            f"- 1 cebolla mediana, picada finamente\n"
            f"- 2 dientes de ajo, laminados\n"
            f"- Sal y pimienta negra al gusto\n"
            f"- 1 ramita de romero fresco (opcional)\n"
            f"- 100 ml de caldo de verduras o agua\n\n"
            f"## Preparación\n\n"
            f"1. **Preparamos los ingredientes.** Lavamos y cortamos todo antes de encender el fuego. "
            f"Esto hace que la cocción sea fluida y sin prisas.\n"
            f"2. **Sofreímos la base.** En una sartén amplia, calentamos el aceite a fuego medio "
            f"y pochamos la cebolla hasta que esté transparente (unos 5 minutos). Añadimos el ajo "
            f"y cocinamos 1 minuto más, cuidando de que no se queme.\n"
            f"3. **Cocinamos el ingrediente principal.** Subimos el fuego y añadimos el ingrediente "
            f"principal. Sellemos por todos lados hasta que esté dorado. Esto no solo aporta sabor, "
            f"sino que mejora la textura final.\n"
            f"4. **Agregamos el líquido.** Vertemos el caldo caliente, añadimos el romero y bajamos "
            f"el fuego al mínimo. Cocinamos tapado durante 20-25 minutos, hasta que el ingrediente "
            f"esté tierno.\n"
            f"5. **Reposamos y servimos.** Dejamos reposar 5 minutos antes de emplatar. "
            f"Este paso es importante para que los jugos se redistribuyan.\n\n"
            f"## Consejo del chef\n\n"
            f"El reposo es el paso más infravalorado en cocina. Si sirves inmediatamente, "
            f"los jugos se escapan y el plato queda seco. Un reposo breve marca la diferencia "
            f"entre un plato correcto y uno memorable.\n\n"
            f"## Información nutricional\n\n"
            f"Según la **Agencia Española de Seguridad Alimentaria y Nutrición (AESAN)**, "
            f"una ración de este plato aporta aproximadamente 350 kcal, 25 g de proteína "
            f"y 18 g de grasa saludable. Para una dieta equilibrada, la AESAN recomienda "
            f"acompañar este plato con una guarnición de verduras frescas o una ensalada ligera.\n\n"
            f"## Preguntas frecuentes\n\n"
            f"**¿Puedo preparar este plato con antelación?** "
            f"Sí, este plato se conserva bien en la nevera hasta 3 días en un recipiente hermético. "
            f"El sabor incluso mejora al reposar los sabores.\n\n"
            f"**¿Puedo sustituir algún ingrediente?** "
            f"Por supuesto. La estructura de esta receta admite variaciones según la temporada "
            f"o lo que tengas en la despensa.\n\n"
            f"**¿Cómo sé si el ingrediente principal está en su punto?** "
            f"La clave es la textura: debe estar tierno pero no deshacerse. Un tenedor debe "
            f"atravesarlo con suavidad pero manteniendo la forma.\n\n"
            f"---\n\n"
            f"*Esta receta ha sido elaborada por {author} para {domain.display_name}, "
            f"donde compartimos recetas pensadas para cocineros de todos los niveles.*"
        ),
        "excerpt": f"Aprende a preparar {title}, una receta fácil y deliciosa. Ingredientes sencillos, "
        "pasos claros y un resultado profesional en tu cocina.",
        "category": category,
        "keywords": [keyword, f"receta de {keyword}", f"cómo hacer {keyword}"],
        "difficulty": "Fácil",
        "prep_time": 15,
        "cook_time": 30,
        "image_alt": f"Plato terminado de {title} presentado en mesa con ingredientes frescos",
        "chef_tip": "Deja reposar el plato 5 minutos antes de servir para que los jugos se asienten.",
        "recipe_schema": {
            "@context": "https://schema.org",
            "@type": "Recipe",
            "name": title,
            "description": f"Receta de {title}",
            "image": hero_url,
            "author": {"@type": "Person", "name": author},
            "prepTime": "PT15M",
            "cookTime": "PT30M",
            "totalTime": "PT45M",
            "recipeYield": "4 raciones",
            "recipeCategory": category,
            "recipeCuisine": "Española",
            "recipeIngredient": [
                "250 g de ingrediente principal",
                "2 cucharadas de aceite de oliva virgen extra",
                "1 cebolla mediana",
                "2 dientes de ajo",
                "Sal y pimienta al gusto",
                "100 ml de caldo de verduras",
            ],
            "recipeInstructions": [
                {"@type": "HowToStep", "text": "Prepara todos los ingredientes antes de empezar."},
                {
                    "@type": "HowToStep",
                    "text": "Sofríe la cebolla y el ajo en aceite de oliva hasta que estén tiernos.",
                },
                {"@type": "HowToStep", "text": "Añade el ingrediente principal y dóralo por todos lados."},
                {"@type": "HowToStep", "text": "Agrega el caldo, tapa y cocina a fuego lento 20-25 minutos."},
                {"@type": "HowToStep", "text": "Deja reposar 5 minutos antes de servir."},
            ],
        },
        "faq_schema": [
            {
                "@type": "Question",
                "name": "¿Puedo preparar este plato con antelación?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "Sí, se conserva hasta 3 días en nevera y el sabor incluso mejora.",
                },
            },
            {
                "@type": "Question",
                "name": "¿Puedo congelar las sobras?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "Sí, congela en porciones individuales hasta 3 meses.",
                },
            },
            {
                "@type": "Question",
                "name": "¿Cómo puedo asegurar la seguridad alimentaria?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "Mantén higiene de manos y utensilios, separa crudo y cocinado y refrigera las sobras pronto.",
                },
            },
        ],
    }


_SESSION = None


def _get_session():
    global _SESSION
    if _SESSION is None:
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=retry_strategy)
        _SESSION = requests.Session()
        _SESSION.mount("http://", adapter)
        _SESSION.mount("https://", adapter)
    return _SESSION


def _update_domain_pin_id(domain: Domain, slug: str, pin_id: str) -> dict:
    session = _get_session()
    key = domain.supabase_service_role_key.get_secret_value()
    if not key:
        return {"success": False, "error": "no_secret_key"}

    headers = {
        "apikey": domain.supabase_service_role_key.get_secret_value(),
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    resp = session.patch(
        f"{domain.supabase_url}/rest/v1/posts?slug=eq.{slug}",
        headers=headers,
        json={"pinterest_pin_id": str(pin_id)},
    )
    if resp.status_code in {200, 204}:
        return {"success": True, "slug": slug, "pin_id": str(pin_id)}
    return {"success": False, "status": resp.status_code, "error": resp.text}


def _check_existing_article(domain: Domain, slug: str) -> dict | None:
    """Check if an article already exists in Supabase to avoid duplicate publication."""
    try:
        session = _get_session()
        key = domain.supabase_service_role_key.get_secret_value()
        if not key or not domain.supabase_url:
            return None
        headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
        }
        resp = session.get(
            f"{domain.supabase_url}/rest/v1/posts?slug=eq.{slug}&select=id,slug,title,status,pinterest_pin_id",
            headers=headers,
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return data[0]
    except Exception as exc:
        logger.debug("Existing article check failed for %s: %s", slug, exc)
    return None


def _process_and_upload_step_images(step_images: list, slug: str, domain: Domain) -> list:
    """Download scraped step images, validate, and upload to Supabase Storage."""
    if not step_images:
        return []
    try:
        from rankstein_mcp_server import upload_image_to_supabase
    except ImportError:
        return []

    session = _get_session()
    uploaded_steps = []
    out_dir = PROJECT_ROOT / "data" / "media" / "steps"
    out_dir.mkdir(parents=True, exist_ok=True)

    for idx, step in enumerate(step_images[:6], 1):
        raw_url = step.get("image_url") if isinstance(step, dict) else step
        step_num = step.get("step_number") if isinstance(step, dict) else None
        if not step_num or not isinstance(step_num, int):
            step_num = idx
        if not raw_url or not isinstance(raw_url, str) or not raw_url.startswith("http"):
            continue
        try:
            resp = session.get(
                raw_url,
                timeout=15,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                },
            )
            if resp.status_code == 200 and len(resp.content) > 5000:
                local_path = out_dir / f"{slug}-step-{step_num}.jpg"
                with open(local_path, "wb") as f:
                    f.write(resp.content)
                storage_path = f"{domain.handle}/steps/{slug}-step-{step_num}.jpg"
                up_res = upload_image_to_supabase(str(local_path), storage_path, domain.handle)
                if up_res.get("success") and up_res.get("public_url"):
                    uploaded_steps.append(
                        {
                            "step_number": step_num,
                            "image_url": up_res["public_url"],
                            "text": step.get("text", "") if isinstance(step, dict) else "",
                        }
                    )
        except Exception as exc:
            logger.debug("Step image download/upload failed for %s step %d: %s", slug, step_num, exc)
            continue

    uploaded_steps.sort(key=lambda s: s.get("step_number", 0))
    return uploaded_steps


def _embed_step_images_in_content(content: str, step_images: list, title: str) -> str:
    """Embed uploaded step images into the article's markdown content at matching steps."""
    if not content or not step_images:
        return content

    valid_steps = [s for s in step_images if isinstance(s, dict) and s.get("image_url")]
    if not valid_steps:
        return content

    for s in valid_steps:
        url = s.get("image_url", "")
        if url and url in content:
            return content

    lines = content.split("\n")
    new_lines = []
    inserted_steps = set()
    step_map = {s.get("step_number"): s for s in valid_steps if s.get("step_number")}

    i = 0
    while i < len(lines):
        line = lines[i]
        new_lines.append(line)

        step_match = re.match(r"^#{2,4}\s*(?:Paso\s*)?(\d+)[:.\s]", line, re.IGNORECASE) or re.match(
            r"^(\d+)\.\s+", line
        )
        if step_match:
            try:
                num = int(step_match.group(1))
            except ValueError:
                num = None

            if num and num in step_map and num not in inserted_steps:
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    if (
                        not next_line.strip()
                        or next_line.startswith("#")
                        or re.match(r"^\d+\.\s+", next_line)
                    ):
                        break
                    new_lines.append(next_line)
                    j += 1

                s_data = step_map[num]
                img_url = s_data["image_url"]
                alt_text = f"Paso {num} de la receta {title}"
                new_lines.append(f"\n![{alt_text}]({img_url})\n")
                inserted_steps.add(num)
                i = j - 1

        i += 1

    return "\n".join(new_lines)


def _build_from_scraped(keyword: str, cluster: str, domain: Domain, hero_url: str, scraped: dict) -> dict:
    """Build article payload using scraped source material instead of generic template."""
    title = keyword[:1].upper() + keyword[1:]
    slug = _slugify(keyword)
    source_text = scraped["content"]
    source_title = scraped.get("source_title", "")
    source_url = scraped.get("source_url", "")
    word_count = scraped.get("word_count", 0)

    ingredients = [
        "250 g de ingrediente principal de calidad",
        "2 cucharadas de aceite de oliva virgen extra",
        "1 cebolla mediana, picada finamente",
        "2 dientes de ajo, laminados",
        "Sal y pimienta negra al gusto",
        "1 ramita de romero fresco (opcional)",
        "100 ml de caldo de verduras o agua",
    ]
    steps = [
        "Preparamos los ingredientes. Lavamos y cortamos todo antes de encender el fuego.",
        "Sofreímos la base. En una sartén amplia, calentamos el aceite a fuego medio y pochamos la cebolla.",
        "Cocinamos el ingrediente principal. Subimos el fuego y doramos por todos lados.",
        "Agregamos el líquido. Vertemos el caldo, tapamos y cocemos a fuego lento 20-25 minutos.",
        "Reposamos y servimos. Dejamos reposar 5 minutos antes de emplatar.",
    ]

    intro = (
        f"Esta receta de {title} está inspirada en las mejores fuentes culinarias. "
        f"He adaptado los sabores y las técnicas para que puedas prepararla en casa "
        f"sin complicaciones, pero manteniendo la esencia del plato original. "
        f"En mi cocina, he descubierto que el secreto está en la paciencia durante la cocción."
    )
    credit = (
        f"*Fuente original: [{source_title}]({source_url}). Adaptado y ampliado para {domain.display_name}.*"
        if source_text and source_url
        else ""
    )

    sections = [
        f"## Por qué funciona esta receta\n{intro} **El objetivo no es complicar la receta**, sino controlar textura, temperatura y punto de sal para que el plato parezca cuidado desde el primer bocado. Esta guía está pensada para una preparación realista, con ingredientes fáciles de encontrar y pasos que se pueden repetir en casa sin equipo profesional.",
        "[HERO_IMAGE]",
        "## Ingredientes\n" + "\n".join(f"- {ing}" for ing in ingredients),
        "## Preparación\n" + "\n".join(f"{i + 1}. {step}" for i, step in enumerate(steps)),
        "## Consejo del chef\nEl reposo es el paso más infravalorado en cocina. Un reposo breve marca la diferencia entre un plato correcto y uno memorable.",
        "## Información nutricional\nSegún la **Agencia Española de Seguridad Alimentaria y Nutrición (AESAN)**, una ración de este plato aporta aproximadamente 350 kcal, 25 g de proteína y 18 g de grasa saludable.",
        "## Preguntas frecuentes\n**¿Puedo preparar este plato con antelación?** Sí, se conserva bien en la nevera hasta 3 días.\n\n**¿Puedo sustituir algún ingrediente?** Por supuesto, admite variaciones según la temporada.",
        f"---\n\nTiene margen para adaptarse, pero mantiene una idea central: buen producto, cocción controlada y acabado limpio. "
        f"Si sigues los pasos con calma, tendrás un plato fiable para una comida especial, una sesión de contenido o una "
        f"receta evergreen dentro de {domain.display_name}.",
    ] + ([f"\n\n{credit}"] if credit else [])

    content = "\n\n".join(sections)
    recipe_schema = {
        "@context": "https://schema.org",
        "@type": "Recipe",
        "name": title,
        "description": f"Receta de {title} inspirada en {source_title}"
        if source_title
        else f"Receta de {title}",
        "image": hero_url,
        "author": {
            "@type": "Organization",
            "name": (
                "Atelier editorial de RecetaDolce"
                if "dolce" in domain.handle
                else "Equipo editorial de RecetaGenial"
            ),
        },
        "prepTime": "PT15M",
        "cookTime": "PT30M",
        "totalTime": "PT45M",
        "recipeYield": "4 raciones",
        "recipeCategory": _choose_category(cluster, domain),
        "recipeCuisine": "Española",
        "recipeIngredient": ingredients,
        "recipeInstructions": [{"@type": "HowToStep", "text": step} for step in steps],
    }
    return {
        "title": title,
        "slug": slug,
        "content": content,
        "excerpt": f"Aprende a preparar {title}, una receta fácil y deliciosa. Inspirada en las mejores fuentes culinarias.",
        "category": _choose_category(cluster, domain),
        "keywords": [keyword, f"receta de {keyword}"],
        "difficulty": "Fácil",
        "prep_time": 15,
        "cook_time": 30,
        "image_alt": f"Plato terminado de {title} presentado en mesa",
        "chef_tip": "Deja reposar el plato 5 minutos antes de servir para que los jugos se asienten.",
        "recipe_schema": recipe_schema,
        "faq_schema": [
            {
                "@type": "Question",
                "name": "¿Puedo preparar este plato con antelación?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "Sí, se conserva hasta 3 días en nevera y el sabor incluso mejora.",
                },
            },
            {
                "@type": "Question",
                "name": "¿Cómo puedo asegurar la seguridad alimentaria?",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "Mantén higiene de manos y utensilios, separa crudo y cocinado y refrigera las sobras pronto.",
                },
            },
        ],
    }


async def _scrape_and_rephrase(keyword: str, domain: Domain) -> dict | None:
    """Scrape news sources for keyword and return article content dict."""
    try:
        from rankstein_mcp_server import extract_article_content, scrape_news_sources

        sources = scrape_news_sources(keyword, language="es", count=5)
        if not sources.get("success") or not sources.get("articles"):
            logger.info("No scraped news sources for %s", keyword)
            return None

        articles = sources["articles"]
        logger.info("Found %d news sources for %s", len(articles), keyword)

        for article in articles[:3]:
            url = article.get("url") or article.get("link", "")
            if not url:
                continue
            extracted = extract_article_content(url)
            if not extracted.get("success"):
                continue
            content = extracted.get("content", "").strip()
            if len(content) > 200:
                return {
                    "content": content,
                    "source_title": extracted.get("title", ""),
                    "source_url": url,
                    "word_count": extracted.get("word_count", 0),
                }
        return None
    except Exception as exc:
        logger.warning("Scrape failed for %s: %s — using template", keyword, exc)
        return None


_SOURCE_SEARCH_RETRY_DELAYS = (5.0, 15.0)
_TRANSIENT_SOURCE_SEARCH_ERROR_MARKERS = (
    "connection",
    "dns",
    "getaddrinfo",
    "name resolution",
    "network",
    "remote end closed",
    "service unavailable",
    "temporary failure",
    "timed out",
    "timeout",
    "502",
    "503",
    "504",
)


async def _sleep_before_source_search_retry(delay_seconds: float) -> None:
    """Patchable async boundary for bounded source-search backoff."""
    await asyncio.sleep(delay_seconds)


def _source_search_failure_is_transient(result: dict) -> bool:
    """Return whether a failed search is worth retrying.

    The news-search fallback chain intentionally converts provider/network
    failures into a successful result with zero articles.  Treat that empty
    result as transient, while failing closed on explicit configuration or
    dependency errors.
    """
    if result.get("success"):
        return not result.get("articles")
    error = str(result.get("error") or "").casefold()
    return any(marker in error for marker in _TRANSIENT_SOURCE_SEARCH_ERROR_MARKERS)


async def _scrape_source_brief(
    keyword: str,
    domain: Domain,
    max_sources: int = 3,
    min_sources: int = 2,
    pipeline_run_id: str = "",
    out_step_images: list | None = None,
) -> str:
    """Collect compact source notes for the LLM. Never returns full scraped articles."""
    max_sources = max(2, max_sources)
    min_sources = max(2, min(min_sources, max_sources))
    try:
        from rankstein_mcp_server import extract_article_content, scrape_news_sources

        _pipeline_event(
            pipeline_run_id,
            "source_scrape",
            "running",
            "Searching Spanish recipe sources",
            provider="scrape_news_sources",
        )
        sources: dict = {}
        search_attempts = len(_SOURCE_SEARCH_RETRY_DELAYS) + 1
        attempts_made = 0
        for attempt in range(1, search_attempts + 1):
            attempts_made = attempt
            try:
                sources = scrape_news_sources(keyword, language=domain.language or "es", count=6)
            except Exception as exc:
                sources = {"success": False, "error": str(exc)}

            if sources.get("success") and sources.get("articles"):
                break
            if attempt >= search_attempts or not _source_search_failure_is_transient(sources):
                break

            retry_delay = _SOURCE_SEARCH_RETRY_DELAYS[attempt - 1]
            error = str(sources.get("error") or "").strip()
            logger.warning(
                "Source search returned no candidates for %s (attempt %d/%d); retrying in %.0fs%s",
                keyword,
                attempt,
                search_attempts,
                retry_delay,
                f": {error}" if error else "",
            )
            _pipeline_event(
                pipeline_run_id,
                "source_scrape",
                "running",
                f"No source candidates on attempt {attempt}; retrying search",
                search_attempt=attempt,
                search_attempts=search_attempts,
                retry_in_seconds=retry_delay,
                error=error[:240],
            )
            await _sleep_before_source_search_retry(retry_delay)

        if not sources.get("success") or not sources.get("articles"):
            _pipeline_event(
                pipeline_run_id,
                "source_scrape",
                "warning",
                f"No relevant source candidates found after {attempts_made} search attempt(s)",
                sources_found=0,
                search_attempts=attempts_made,
                error=str(sources.get("error") or "")[:240],
            )
            _pipeline_event(
                pipeline_run_id,
                "source_extract",
                "complete",
                "Continuing without external source notes",
                sources_extracted=0,
            )
            return ""

        source_articles = sources["articles"]
        _pipeline_event(
            pipeline_run_id,
            "source_scrape",
            "complete",
            f"Found {len(source_articles)} source candidates",
            sources_found=len(source_articles),
        )
        _pipeline_event(
            pipeline_run_id,
            "source_extract",
            "running",
            "Extracting compact, relevant source notes",
        )
        notes = []
        for article in source_articles:
            if len(notes) >= max_sources:
                break
            url = article.get("url") or article.get("link", "")
            if not url:
                continue
            if not _source_relevant_enough(
                keyword,
                article.get("title", ""),
                article.get("snippet", ""),
                url,
            ):
                logger.info("Skipping weak source candidate for %s: %s", keyword, url)
                continue
            extracted = extract_article_content(url)
            if not extracted.get("success"):
                continue
            content = re.sub(r"\s+", " ", extracted.get("content", "")).strip()
            if len(content) < 200:
                continue
            if not _source_relevant_enough(keyword, extracted.get("title", ""), url, content[:2000]):
                logger.info("Skipping extracted source with weak recipe relevance for %s: %s", keyword, url)
                continue
            if out_step_images is not None and extracted.get("step_images"):
                src_step_images = extracted["step_images"]
                if len(src_step_images) > len(out_step_images):
                    out_step_images.clear()
                    out_step_images.extend(src_step_images)
            notes.append(
                {
                    "title": extracted.get("title") or article.get("title", ""),
                    "url": url,
                    "word_count": extracted.get("word_count", 0),
                    "notes": content[:3000],
                }
            )
        if len(notes) < min_sources:
            _pipeline_event(
                pipeline_run_id,
                "source_extract",
                "warning",
                "Insufficient independent relevant sources for grounded article writing",
                sources_extracted=len(notes),
                sources_required=min_sources,
            )
            return ""
        lines = [
            "SOURCE RESEARCH BRIEF — READ CAREFULLY BEFORE WRITING:",
            "These are real Spanish recipe articles scraped from trusted cooking sites.",
            "YOUR JOB: COMBINE and REPHRASE these sources into ONE new cohesive article.",
            "- Extract the real ingredients, quantities, and techniques from the sources below.",
            "- Merge the best parts of each source into a single unified recipe.",
            "- Rewrite every sentence in your own words — do NOT copy any sentence verbatim.",
            "- Keep the ingredient amounts and step order from the sources, but rephrase them.",
            "- If sources disagree on technique, pick the most reliable approach and note the alternative.",
            "- The final article must read as ONE recipe, not a summary of multiple articles.",
            "- Include a 'Inspiración y referencias' section at the end with source links (nofollow).",
            "",
        ]
        for index, item in enumerate(notes, 1):
            lines.append(
                f"=== SOURCE {index} ===\n"
                f"Title: {item['title']}\n"
                f"URL: {item['url']}\n"
                f"Extracted words: {item['word_count']}\n"
                f"CONTENT TO REPHRASE AND COMBINE:\n{item['notes']}\n"
            )
        _pipeline_event(
            pipeline_run_id,
            "source_extract",
            "complete",
            f"Prepared {len(notes)} compact source briefs",
            sources_extracted=len(notes),
        )
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("Source brief scrape failed for %s: %s", keyword, exc)
        _pipeline_event(
            pipeline_run_id,
            "source_scrape",
            "warning",
            "Source research failed; continuing with domain context",
            error=str(exc)[:240],
        )
        return ""


def _validate_article_remaster_report(
    report: dict,
    *,
    target_count: int = 30,
    expected_domain_handle: str = "",
    expected_slug: str = "",
    expected_pipeline_run_id: str = "",
) -> tuple[bool, str]:
    """Prove that one article produced and queued the complete paired campaign."""
    identity_checks = {
        "domain_handle": expected_domain_handle,
        "slug": expected_slug,
        "pipeline_run_id": expected_pipeline_run_id,
    }
    for field, expected in identity_checks.items():
        expected_value = str(expected or "").strip()
        if not expected_value:
            continue
        actual_value = str(report.get(field) or "").strip()
        if actual_value.casefold() != expected_value.casefold():
            return False, (f"remaster report {field}={actual_value!r}, expected {expected_value!r}")

    report_target = int(report.get("target_count", 0) or 0)
    actual_target = (
        report_target if (2 <= report_target <= target_count and report_target % 2 == 0) else target_count
    )
    source_target = actual_target // 2
    if not report.get("success"):
        return False, "remaster report is marked incomplete"
    expected_numbers = {
        "target_count": actual_target,
        "source_target": source_target,
        "accepted_source_count": source_target,
        "pair_count": source_target,
        "generated_count": actual_target,
        "missing_count": 0,
    }
    for field, expected in expected_numbers.items():
        try:
            actual = int(report.get(field, -1))
        except (TypeError, ValueError):
            return False, f"remaster report has invalid {field}"
        if actual != expected:
            return False, f"remaster report {field}={actual}, expected {expected}"

    source_counts = report.get("source_counts") or {}
    try:
        pinterest_sources = int(source_counts.get("pinterest", -1))
        native_sources = int(source_counts.get("native", -1))
    except (TypeError, ValueError):
        return False, "remaster report has invalid source_counts"
    if pinterest_sources != source_target or native_sources != 0:
        return False, (
            f"remaster report must prove {source_target} unique scraped Pinterest sources "
            f"(pinterest={pinterest_sources}, native={native_sources})"
        )

    contract = report.get("variant_contract") or {}
    variants = contract.get("variants") or []
    if int(contract.get("variants_per_source", 0) or 0) != 2 or set(variants) != {
        "viral_visual",
        "recipe_card",
    }:
        return False, "remaster report does not prove the two-variant contract"

    assets = report.get("assets") or []
    if len(assets) != actual_target:
        return False, f"remaster report contains {len(assets)} assets, expected {actual_target}"
    pair_variants: dict[str, set[str]] = {}
    source_identity_by_pair: dict[str, str] = {}
    for asset in assets:
        if not isinstance(asset, dict):
            return False, "remaster report contains an invalid asset"
        pair_id = str(asset.get("pair_id") or "").strip()
        variant = str(asset.get("variant") or "").strip()
        if not pair_id or variant not in {"viral_visual", "recipe_card"}:
            return False, "remaster asset is missing its pair identity or variant"
        if str(asset.get("source") or "").strip().casefold() != "pinterest":
            return False, "remaster asset is not proven to come from Pinterest"
        quality = asset.get("source_quality")
        source_hash = str(asset.get("source_hash") or "")
        if (
            not isinstance(quality, dict)
            or quality.get("accepted") is not True
            or quality.get("policy") != "text_free_pinterest_source"
            or quality.get("version") != 1
            or not str(asset.get("source_path") or "").strip()
            or not re.fullmatch(r"[a-f0-9]{64}", source_hash)
            or quality.get("source_hash") != source_hash
        ):
            return False, "remaster asset has no accepted, hash-bound source text review"
        source_identity = str(asset.get("original_pin_id") or asset.get("original_url") or "").strip()
        if not source_identity:
            return False, "remaster asset is missing its Pinterest source identity"
        existing_identity = source_identity_by_pair.setdefault(pair_id, source_identity)
        if existing_identity != source_identity:
            return False, "remaster pair variants do not share one Pinterest source identity"
        pair_variants.setdefault(pair_id, set()).add(variant)
    if len(pair_variants) != source_target or any(
        values != {"viral_visual", "recipe_card"} for values in pair_variants.values()
    ):
        return False, f"remaster assets are not {source_target} complete two-variant pairs"
    if len(set(source_identity_by_pair.values())) != source_target:
        return False, f"remaster report does not prove {source_target} unique Pinterest sources"

    enqueue = report.get("enqueue") or {}
    if not enqueue.get("success"):
        return False, "remaster enqueue step failed"
    for field in ("images_enqueued", "jobs_enqueued"):
        try:
            actual = int(enqueue.get(field, -1))
        except (TypeError, ValueError):
            return False, f"remaster enqueue result has invalid {field}"
        if actual != actual_target and actual != target_count and actual < actual_target:
            return False, f"remaster enqueue {field}={actual}, expected {actual_target}"
    details = enqueue.get("details") or []
    if len(details) != actual_target or any(not item.get("job_id") for item in details):
        return False, f"remaster enqueue result does not prove all {actual_target} queue jobs"
    if len({str(item.get("job_id")) for item in details}) != actual_target:
        return False, "remaster enqueue result contains duplicate queue job IDs"
    if any(str(item.get("state") or "").casefold() in {"held", "dead", "failed"} for item in details):
        return False, "remaster enqueue result contains held or failed queue jobs"
    return True, ""


def _find_valid_article_remaster_report(
    *,
    slug: str,
    domain_handle: str,
    pipeline_run_id: str,
    target_count: int = 30,
) -> dict | None:
    """Return a launch-shaped result for an already-proven exact-run report."""

    report_dir = PROJECT_ROOT / "data" / "reports" / "campaigns"
    if not report_dir.is_dir():
        return None
    candidates = sorted(
        report_dir.glob(f"{slug}_remaster_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for report_path in candidates:
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        valid, _ = _validate_article_remaster_report(
            report,
            target_count=target_count,
            expected_domain_handle=domain_handle,
            expected_slug=slug,
            expected_pipeline_run_id=pipeline_run_id,
        )
        if not valid:
            continue
        return {
            "success": True,
            "reused_existing_report": True,
            "pins_per_keyword": target_count,
            "report_path": str(report_path),
            "generated_count": report.get("generated_count", 0),
            "pair_count": report.get("pair_count", 0),
            "jobs_enqueued": (report.get("enqueue") or {}).get("jobs_enqueued", 0),
            "error": "",
        }
    return None


async def _launch_article_remaster_campaign(
    *,
    keyword: str,
    title: str,
    slug: str,
    category: str,
    domain: Domain,
    pipeline_run_id: str = "",
    recipe_ingredients: list[str] | None = None,
    recipe_steps: list[str] | None = None,
    tip_text: str = "",
) -> dict:
    from rankstein.campaign_guard import article_campaign_lock

    # Re-check the exact report after taking the shared lock. Foreground
    # publication and late reconciliation must never launch overlapping
    # children for the same domain/profile or enqueue duplicate campaigns.
    async with article_campaign_lock(domain.handle):
        return await _launch_article_remaster_campaign_unlocked(
            keyword=keyword,
            title=title,
            slug=slug,
            category=category,
            domain=domain,
            pipeline_run_id=pipeline_run_id,
            recipe_ingredients=recipe_ingredients,
            recipe_steps=recipe_steps,
            tip_text=tip_text,
        )


async def _launch_article_remaster_campaign_unlocked(
    *,
    keyword: str,
    title: str,
    slug: str,
    category: str,
    domain: Domain,
    pipeline_run_id: str = "",
    recipe_ingredients: list[str] | None = None,
    recipe_steps: list[str] | None = None,
    tip_text: str = "",
) -> dict:
    # The article campaign is a durable proof unit.  A valid report means the
    # exact 30 jobs were already enqueued, so a restart/reconcile must reuse it
    # instead of launching the campaign again.
    pins_per_keyword = 30
    existing_proof = _find_valid_article_remaster_report(
        slug=slug,
        domain_handle=domain.handle,
        pipeline_run_id=pipeline_run_id,
        target_count=pins_per_keyword,
    )
    if existing_proof is not None:
        return existing_proof

    if os.environ.get("RANKSTEIN_ENABLE_ARTICLE_REMASTERS", "1").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return {
            "success": False,
            "skipped": True,
            "error": "RANKSTEIN_ENABLE_ARTICLE_REMASTERS disabled",
        }
    # Production completion is defined by the permanent 15-pair/30-asset
    # contract. Environment overrides may not silently weaken that proof.
    # The article title is the actual finished dish. Roadmap keywords can be
    # broad clusters ("postres con chocolate") and produced irrelevant/empty
    # Pinterest searches when used as the scrape identity.
    brief = build_recipe_image_scrape_brief(title, domain=domain, category=category)
    log_dir = PROJECT_ROOT / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "backend" / "services" / "remasterer.py"),
        title,
        title,
        "--pins-per-keyword",
        str(pins_per_keyword),
        "--search-query",
        brief.get("search_query", title),
        "--search-queries-json",
        json.dumps(brief.get("search_queries", []), ensure_ascii=False),
        "--core-terms",
        ",".join(brief.get("core_terms", [])),
        "--min-core-matches",
        str(brief.get("min_core_matches", 1)),
        "--expected-terms",
        ",".join(brief.get("expected_terms", [])),
        "--blocked-terms",
        ",".join(brief.get("blocked_terms", [])),
        "--recipe-ingredients-json",
        json.dumps(recipe_ingredients or [], ensure_ascii=False),
        "--recipe-steps-json",
        json.dumps(recipe_steps or [], ensure_ascii=False),
        "--tip-text",
        tip_text or "",
        "--enqueue-after",
        "--slug",
        slug,
        "--domain-url",
        domain.domain,
        "--domain-handle",
        domain.handle,
        "--session-name",
        f"remasterer_{domain.handle}",
    ]
    if pipeline_run_id:
        cmd.extend(["--pipeline-run-id", pipeline_run_id])
    report_dir = PROJECT_ROOT / "data" / "reports" / "campaigns"
    report_dir.mkdir(parents=True, exist_ok=True)
    existing_reports = {path.resolve() for path in report_dir.glob(f"{slug}_remaster_*.json")}
    started_at = time.time()
    stdout_handle = None
    stderr_handle = None
    proc = None
    try:
        stdout_handle = (log_dir / "remasterer.log").open("a", encoding="utf-8")
        stderr_handle = (log_dir / "remasterer_err.log").open("a", encoding="utf-8")
        proc = await _create_owned_subprocess(
            *cmd,
            cwd=str(PROJECT_ROOT),
            stdout=stdout_handle,
            stderr=stderr_handle,
            stdin=subprocess.DEVNULL,
            env=clean_python_env(),
        )
        logger.info(
            "Running article remaster campaign for %s: pid=%s pins=%s query=%r",
            slug,
            proc.pid,
            pins_per_keyword,
            brief.get("search_query", title),
        )
        _pipeline_event(
            pipeline_run_id,
            "pinterest_siphon",
            "running",
            "Collecting 15 relevant image sources for the paired pin campaign",
            pid=proc.pid,
            target=pins_per_keyword,
            source_target=pins_per_keyword // 2,
        )
        try:
            timeout_seconds = max(
                300,
                int(os.environ.get("RANKSTEIN_REMASTER_CAMPAIGN_TIMEOUT_SECONDS", "1200")),
            )
        except ValueError:
            timeout_seconds = 1200
        try:
            returncode = await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)
        except TimeoutError:
            return {
                "success": False,
                "pid": proc.pid,
                "error": f"remaster campaign exceeded {timeout_seconds} seconds",
            }

        candidates = sorted(
            (
                path
                for path in report_dir.glob(f"{slug}_remaster_*.json")
                if path.resolve() not in existing_reports or path.stat().st_mtime >= started_at - 2
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if returncode != 0:
            return {
                "success": False,
                "pid": proc.pid,
                "returncode": returncode,
                "error": f"remaster campaign exited with code {returncode}",
                "report_path": str(candidates[0]) if candidates else "",
            }
        if not candidates:
            return {
                "success": False,
                "pid": proc.pid,
                "error": "remaster campaign exited without a current-run report",
            }
        report_path = None
        report = None
        identity_rejections: list[str] = []
        unreadable_reports: list[str] = []
        for candidate in candidates:
            try:
                candidate_report = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                unreadable_reports.append(f"{candidate.name}: {exc}")
                continue
            identity_valid, identity_reason = _validate_article_remaster_report(
                candidate_report,
                target_count=pins_per_keyword,
                expected_domain_handle=domain.handle,
                expected_slug=slug,
                expected_pipeline_run_id=pipeline_run_id,
            )
            if (
                identity_reason.startswith("remaster report domain_handle=")
                or identity_reason.startswith("remaster report slug=")
                or identity_reason.startswith("remaster report pipeline_run_id=")
            ):
                identity_rejections.append(f"{candidate.name}: {identity_reason}")
                continue
            report_path = candidate
            report = candidate_report
            break

        if report_path is None or report is None:
            reason_parts = identity_rejections or unreadable_reports
            return {
                "success": False,
                "pid": proc.pid,
                "report_path": str(candidates[0]) if candidates else "",
                "error": (
                    "remaster campaign produced no report for the expected article identity"
                    + (f": {reason_parts[0]}" if reason_parts else "")
                ),
            }
        valid, reason = _validate_article_remaster_report(
            report,
            target_count=pins_per_keyword,
            expected_domain_handle=domain.handle,
            expected_slug=slug,
            expected_pipeline_run_id=pipeline_run_id,
        )
        return {
            "success": valid,
            "pid": proc.pid,
            "pins_per_keyword": pins_per_keyword,
            "report_path": str(report_path),
            "generated_count": report.get("generated_count", 0),
            "pair_count": report.get("pair_count", 0),
            "jobs_enqueued": (report.get("enqueue") or {}).get("jobs_enqueued", 0),
            "blocked_reason": str(report.get("blocked_reason") or ""),
            "source_collection_diagnostics": report.get("source_collection_diagnostics") or {},
            "error": (
                f"{reason}: {report['blocked_reason']}" if reason and report.get("blocked_reason") else reason
            ),
        }
    except Exception as exc:
        logger.warning("Article remaster campaign failed for %s: %s", slug, exc)
        return {"success": False, "error": str(exc)}
    finally:
        try:
            await _cleanup_owned_process(proc)
        finally:
            if stdout_handle is not None:
                stdout_handle.close()
            if stderr_handle is not None:
                stderr_handle.close()


async def _publish_generated_article(
    article: dict,
    keyword: str,
    cluster: str,
    domain: Domain,
    pipeline_run_id: str = "",
    step_images: list | None = None,
) -> str:
    """Publish an LLM-generated article JSON through the full production pipeline.

    Handles hero image generation, Supabase storage, Supabase publication,
    Pinterest pin image creation, and Pinterest pin upload. Returns 'Live',
    'Failed', or 'Needs Verification'.
    """
    try:
        from rankstein_mcp_server import (
            automation_upload_pin_direct,
            build_supabase_content,
            create_article_pin,
            publish_article_to_supabase,
            upload_image_to_supabase,
            validate_article_quality,
        )
    except ImportError as exc:
        logger.error("Cannot import publishing MCP tools: %s", exc)
        return "Failed"

    slug = article.get("slug") or _slugify(keyword)
    _pipeline_event(
        pipeline_run_id,
        "quality_check",
        "running",
        "Validating article JSON and recipe schema",
        slug=slug,
    )
    try:
        category_guess = _normalize_category(
            article.get("category") or cluster,
            cluster,
            domain,
            context=f"{article.get('title', '')} {keyword}",
        )
    except CategoryPolicyError as exc:
        logger.error("Category policy rejected %r for %s: %s", keyword, domain.handle, exc)
        _pipeline_event(
            pipeline_run_id,
            "quality_check",
            "failed",
            "Article category is incompatible with the target domain",
            reason=str(exc),
        )
        _pipeline_status(pipeline_run_id, "failed")
        return "Failed"
    article.setdefault("category", category_guess)
    article.setdefault("image_alt", recipe_alt_text(keyword))
    article.setdefault("image_negative_prompt", IMAGE_NEGATIVE_PROMPT)
    article.setdefault(
        "hero_image_prompt",
        build_recipe_image_prompt(
            keyword,
            domain=domain,
            asset_type="hero",
            category=category_guess,
        ),
    )
    article.setdefault(
        "pinterest_pin_prompt",
        build_recipe_image_prompt(
            keyword,
            domain=domain,
            asset_type="pinterest_pin",
            category=category_guess,
            overlay_concept="guardar receta",
        ),
    )

    # ——— 1. Hero image (Codex primary -> Scraped -> Pollinations fallback) ———
    logger.info("Generating/sourcing hero image for %s (Codex -> Scraped -> Pollinations)", keyword)
    _pipeline_event(
        pipeline_run_id,
        "hero_image",
        "running",
        "Generating the finished-dish hero image (Codex -> Scraped -> Pollinations)",
        provider="codex",
        fallback_allowed=True,
    )
    image_prompt = article.get("hero_image_prompt") or build_recipe_image_prompt(
        keyword,
        domain=domain,
        asset_type="hero",
        category=category_guess,
    )
    hero = get_hero_image(
        keyword=keyword,
        slug=slug,
        domain_handle=domain.handle,
        image_prompt=image_prompt,
    )
    if not isinstance(hero, dict):
        hero = {"success": False, "error": "Hero pipeline returned an invalid result"}
    if not hero.get("success"):
        logger.error("Hero image generation failed across all providers for %s", keyword)
        _pipeline_event(
            pipeline_run_id,
            "hero_image",
            "failed",
            "Hero image generation failed across all providers; publishing stopped",
            provider=str(hero.get("provider") or hero.get("source") or "hero_pipeline"),
            error=str(hero.get("error") or "")[:240],
            fallback_allowed=True,
        )
        _pipeline_status(pipeline_run_id, "failed")
        return "Failed"
    hero_source = str(hero.get("source") or hero.get("provider") or "").strip().casefold()
    if hero_source not in {"codex", "scraped", "pollinations"}:
        logger.error("Rejecting unapproved hero source %r for %s", hero.get("source"), keyword)
        _pipeline_event(
            pipeline_run_id,
            "hero_image",
            "failed",
            f"Hero source {hero_source!r} is not an approved provider; publishing stopped",
            provider=str(hero.get("provider") or hero.get("source") or "unknown"),
            fallback_allowed=True,
        )
        _pipeline_status(pipeline_run_id, "failed")
        return "Failed"
    hero_path = hero.get("output_path")
    if not isinstance(hero_path, (str, Path)) or not str(hero_path).strip():
        _pipeline_event(
            pipeline_run_id,
            "hero_image",
            "failed",
            "Hero provider returned no usable image path; publishing stopped",
            source=hero_source,
            fallback_allowed=True,
        )
        _pipeline_status(pipeline_run_id, "failed")
        return "Failed"
    hero_path = str(hero_path)
    logger.info(
        "Hero image sourced via %s for %s: %s",
        hero_source,
        keyword,
        hero_path,
    )
    _pipeline_event(
        pipeline_run_id,
        "hero_image",
        "complete",
        f"Hero image created via {hero_source}",
        source=hero_source,
        provider=str(hero.get("provider") or hero_source),
        output_path=hero_path,
    )

    # ——— 2. Upload hero to Supabase ———
    hero_extension = Path(hero_path).suffix.lower() or ".jpg"
    if hero_extension not in {".jpg", ".jpeg", ".png", ".webp"}:
        hero_extension = ".jpg"
    storage_path = f"{domain.handle}/{slug}-hero{hero_extension}"
    _pipeline_event(
        pipeline_run_id,
        "hero_upload",
        "running",
        "Uploading hero to Supabase Storage",
        storage_path=storage_path,
    )
    uploaded = upload_image_to_supabase(hero_path, storage_path, domain.handle)
    if not uploaded.get("success"):
        logger.error(
            "Supabase hero upload failed for %s: %s",
            keyword,
            uploaded.get("error", "unknown upload error"),
        )
        _pipeline_event(
            pipeline_run_id,
            "hero_upload",
            "failed",
            "Hero upload failed",
            error=str(uploaded.get("error", ""))[:240],
        )
        _pipeline_status(pipeline_run_id, "failed")
        return "Failed"
    hero_url = uploaded["public_url"]
    _pipeline_event(
        pipeline_run_id,
        "hero_upload",
        "complete",
        "Hero stored and publicly addressable",
        public_url=hero_url,
    )

    # ——— 3. Inject hero URL into article and build payload ———
    article["slug"] = slug
    article["featured_image"] = hero_url

    steps_to_process = step_images or article.get("step_images") or []
    if steps_to_process:
        uploaded_steps = _process_and_upload_step_images(steps_to_process, slug, domain)
        if uploaded_steps:
            article["step_images"] = uploaded_steps
            article["content"] = _embed_step_images_in_content(
                article.get("content", ""), uploaded_steps, article.get("title", keyword)
            )
            logger.info("Integrated %d step images into article and schema for %s", len(uploaded_steps), slug)

    _ensure_recipe_schema(article, keyword=keyword, cluster=cluster, domain=domain, hero_url=hero_url)

    quality = validate_article_quality(json.dumps(article, ensure_ascii=False))
    if not quality.get("success"):
        score = quality.get("score", 0)
        if score >= 80:
            logger.info(
                "Quality gate scored %d (>=80) for %s — minor issues only, proceeding",
                score,
                keyword,
            )
        else:
            logger.warning(
                "Direct LLM article quality validation failed for %s (score=%d): %s",
                keyword,
                score,
                quality,
            )
            _pipeline_event(
                pipeline_run_id,
                "quality_check",
                "failed",
                f"Article quality score {score} did not pass",
                score=score,
            )
            return "Pending"
    _pipeline_event(
        pipeline_run_id,
        "quality_check",
        "complete",
        f"Article quality validated at {quality.get('score', 'pass')}",
        score=quality.get("score"),
    )

    content_result = build_supabase_content(keyword, hero_url, json.dumps(article, ensure_ascii=False))
    if not content_result.get("success"):
        logger.error("Supabase content build failed for %s", keyword)
        _pipeline_event(
            pipeline_run_id,
            "article_publish",
            "failed",
            "Supabase article payload could not be built",
        )
        _pipeline_status(pipeline_run_id, "failed")
        return "Failed"

    payload = json.loads(content_result["payload"])
    payload["category"] = _normalize_category(
        payload.get("category"),
        cluster,
        domain,
        context=f"{payload.get('title', '')} {keyword}",
    )
    if isinstance(payload.get("recipe_schema"), dict):
        payload["recipe_schema"]["recipeCategory"] = payload["category"]

    # Normalize difficulty for Supabase check constraint
    difficulty_normalized = _normalize_difficulty(payload.get("difficulty", "Media"))

    # ——— 4. Publish to Supabase ———
    _pipeline_event(
        pipeline_run_id,
        "article_publish",
        "running",
        "Publishing article to Supabase",
        slug=slug,
    )
    published = publish_article_to_supabase(
        title=payload["title"],
        slug=payload["slug"],
        content=payload["content"],
        excerpt=payload["excerpt"],
        category=payload["category"],
        featured_image_url=hero_url,
        meta_title=payload.get("meta_title", ""),
        meta_description=payload.get("meta_description", ""),
        keywords=", ".join(payload.get("keywords", [])),
        difficulty=difficulty_normalized,
        prep_time=payload.get("prep_time", 15),
        cook_time=payload.get("cook_time", 30),
        image_alt=payload.get("image_alt", ""),
        chef_tip=payload.get("chef_tip", ""),
        recipe_schema=json.dumps(payload.get("recipe_schema", {}), ensure_ascii=False),
        faq_schema=json.dumps(payload.get("faq_schema", []), ensure_ascii=False),
        domain_handle=domain.handle,
        auto_create_pinterest_campaign=False,
    )
    if not published.get("success"):
        logger.error("Article publish failed for %s: %s", keyword, published)
        _pipeline_event(
            pipeline_run_id,
            "article_publish",
            "failed",
            "Supabase article publish failed",
            error=str(published.get("error", ""))[:240],
        )
        _pipeline_status(pipeline_run_id, "failed")
        return "Failed"

    article_url = published.get("url", f"https://{domain.domain}/{slug}")
    _pipeline_event(
        pipeline_run_id,
        "article_publish",
        "complete",
        "Article published",
        article_url=article_url,
        slug=slug,
    )

    # ——— 5. Create Pinterest pin image ———
    brand = getattr(domain, "brand_name_short", "") or f"{domain.display_name.upper()} | 2026"
    category = _normalize_category(
        payload.get("category", cluster),
        cluster,
        domain,
        context=f"{payload.get('title', '')} {keyword}",
    )
    board = domain.boards_default.get(category) or domain.boards_default.get("_default", "")
    cta_text = getattr(domain, "cta_text", "Ver receta completa")

    _pipeline_event(
        pipeline_run_id,
        "primary_pin",
        "running",
        "Designing the hero-based Pinterest pin",
        board=board,
    )
    pin_image = create_article_pin(
        hero_image_path=hero_path,
        title_text=payload["title"],
        subtitle=category,
        brand=brand,
        cta_text=cta_text,
        style_variant="visual_first",
        domain_handle=domain.handle,
        recipe_ingredients=json.dumps(
            payload.get("recipe_schema", {}).get("recipeIngredient", []), ensure_ascii=False
        ),
        recipe_steps=json.dumps(
            [step["text"] for step in payload.get("recipe_schema", {}).get("recipeInstructions", [])],
            ensure_ascii=False,
        ),
        tip_text=payload.get("chef_tip", ""),
    )
    if not pin_image.get("success"):
        logger.warning(
            "Codex article published %s: article=%s pin=PENDING (supervisor will handle)",
            keyword,
            article_url,
        )
        _pipeline_event(
            pipeline_run_id,
            "primary_pin",
            "failed",
            "Primary pin artwork could not be created",
        )
        _pipeline_event(
            pipeline_run_id,
            "verification",
            "waiting",
            "Article is live but Pinterest proof is missing",
        )
        _pipeline_status(pipeline_run_id, "needs_verification")
        return "Needs Verification"

    # ——— 6. Upload pin to Pinterest ———
    _pipeline_event(
        pipeline_run_id,
        "primary_pin",
        "complete",
        "Primary Pinterest artwork created",
        output_path=pin_image.get("output_path", ""),
    )
    _pipeline_event(
        pipeline_run_id,
        "primary_pin_publish",
        "running",
        "Publishing and verifying the primary Pinterest pin",
        board=board,
    )
    upload = await automation_upload_pin_direct(
        image_path=pin_image["output_path"],
        title=payload["title"],
        description=payload["excerpt"],
        link=article_url,
        alt_text=payload.get("image_alt", ""),
        board_name=board,
        domain_handle=domain.handle,
    )
    if not upload.get("success"):
        logger.warning(
            "Codex article published %s: article=%s pin=PENDING (supervisor will handle)",
            keyword,
            article_url,
        )
        _pipeline_event(
            pipeline_run_id,
            "primary_pin_publish",
            "warning",
            "Primary pin upload is awaiting supervisor verification",
            error=str(upload.get("error", ""))[:240],
            job_id=upload.get("job_id", ""),
        )
        _pipeline_event(
            pipeline_run_id,
            "verification",
            "waiting",
            "Article is live but pin_id or pin_url is not proven",
        )
        _pipeline_status(pipeline_run_id, "needs_verification")
        return "Needs Verification"

    pin_id = str(upload.get("pin_id") or "").strip()
    pin_url = str(upload.get("pin_url") or "").strip()
    if not pin_id and not pin_url:
        logger.warning(
            "Codex article published %s but Pinterest returned success without pin proof",
            keyword,
        )
        _pipeline_event(
            pipeline_run_id,
            "primary_pin_publish",
            "warning",
            "Pinterest reported success but returned no pin_id or pin_url",
            job_id=upload.get("job_id", ""),
        )
        _pipeline_event(
            pipeline_run_id,
            "verification",
            "waiting",
            "Article is live but pin_id or pin_url is not proven",
        )
        _pipeline_status(pipeline_run_id, "needs_verification")
        return "Needs Verification"
    if pin_id:
        _update_domain_pin_id(domain, slug, pin_id)
    _pipeline_event(
        pipeline_run_id,
        "primary_pin_publish",
        "complete",
        "Primary pin published with verified proof",
        pin_id=pin_id,
        pin_url=pin_url,
        job_id=upload.get("job_id", ""),
    )
    _pipeline_event(
        pipeline_run_id,
        "verification",
        "running",
        "Primary pin is proven; waiting for the complete 30-pin campaign report",
        pin_id=pin_id,
        article_url=article_url,
    )
    remaster_launch = await _launch_article_remaster_campaign(
        keyword=keyword,
        title=payload["title"],
        slug=slug,
        category=payload.get("category", category_guess),
        domain=domain,
        pipeline_run_id=pipeline_run_id,
        recipe_ingredients=payload.get("recipe_schema", {}).get("recipeIngredient", []),
        recipe_steps=[
            step.get("text", "") if isinstance(step, dict) else str(step)
            for step in payload.get("recipe_schema", {}).get("recipeInstructions", [])
        ],
        tip_text=payload.get("chef_tip", ""),
    )
    if remaster_launch.get("success"):
        _pipeline_event(
            pipeline_run_id,
            "pinterest_siphon",
            "complete",
            "Completed 15 source pairs and queued all 30 pin variants",
            pid=remaster_launch.get("pid"),
            target=remaster_launch.get("pins_per_keyword"),
            generated=remaster_launch.get("generated_count"),
            pairs=remaster_launch.get("pair_count"),
            jobs_enqueued=remaster_launch.get("jobs_enqueued"),
            report_path=remaster_launch.get("report_path"),
        )
        _pipeline_event(
            pipeline_run_id,
            "verification",
            "complete",
            "Article, storage, primary pin, and complete 30-pin campaign verified",
            pin_id=pin_id,
            pin_url=pin_url,
            article_url=article_url,
            campaign_report=remaster_launch.get("report_path", ""),
        )
        _pipeline_status(pipeline_run_id, "complete")
    else:
        _pipeline_event(
            pipeline_run_id,
            "pinterest_siphon",
            "failed",
            "The paired pin campaign did not prove all 30 queued assets",
            error=str(remaster_launch.get("error", ""))[:240],
            report_path=remaster_launch.get("report_path", ""),
            generated=remaster_launch.get("generated_count", 0),
            pairs=remaster_launch.get("pair_count", 0),
            jobs_enqueued=remaster_launch.get("jobs_enqueued", 0),
        )
        _pipeline_event(
            pipeline_run_id,
            "verification",
            "waiting",
            "Article and primary pin are live, but the 30-pin campaign is incomplete",
            article_url=article_url,
            pin_id=pin_id,
            campaign_error=str(remaster_launch.get("error", ""))[:240],
        )
        _pipeline_status(pipeline_run_id, "needs_verification")
        return "Needs Verification"

    logger.info(
        "Codex production published %s: article=%s pin=%s",
        keyword,
        article_url,
        pin_url or pin_id,
    )
    return "Live"


# Compatibility alias for callers and focused tests that predate the
# provider-neutral publication name. Articles remain Codex-first with only the
# explicitly approved availability-only free model route through Hermes.
_publish_openrouter_article = _publish_generated_article


async def _deterministic_publication(keyword: str, cluster: str, domain: Domain) -> str:
    logger.error(
        "LLM generation failed for %s on %s; refusing deterministic article publication. "
        "Operator must intervene.",
        keyword,
        domain.handle,
    )
    return "Failed"


async def _create_owned_subprocess(*args, **kwargs) -> asyncio.subprocess.Process:
    """Capture a spawned child even if cancellation arrives during OS startup."""

    spawning = asyncio.create_task(asyncio.create_subprocess_exec(*args, **kwargs))
    try:
        return await asyncio.shield(spawning)
    except asyncio.CancelledError:
        # Shield creation so cancellation cannot lose the handle of a child
        # that the OS already started. Repeated cancellation must not skip reaping.
        while not spawning.done():
            try:
                await asyncio.shield(spawning)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        try:
            process = spawning.result()
        except Exception:
            pass
        else:
            await _cleanup_owned_process(process)
        raise


async def _cleanup_owned_process(process: asyncio.subprocess.Process | None) -> None:
    """Finish exact-child cleanup before allowing cancellation to propagate."""

    if process is None or process.returncode is not None:
        return
    cleanup = asyncio.create_task(_terminate_process_tree(process))
    cancelled = False
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            cancelled = True
    cleanup.result()
    if cancelled:
        raise asyncio.CancelledError


async def _terminate_process_tree(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        if os.name == "nt":
            killer = None
            try:
                killer = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/PID",
                    str(process.pid),
                    "/T",
                    "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(killer.wait(), timeout=10)
            except (OSError, TimeoutError):
                logger.warning("Tree termination command failed for owned PID %s", process.pid)
            finally:
                if killer is not None and killer.returncode is None:
                    with contextlib.suppress(ProcessLookupError):
                        killer.kill()
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(killer.wait(), timeout=2)
                if process.returncode is None:
                    process.kill()
        else:
            process.terminate()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=5)
            if process.returncode is None:
                process.kill()
    except ProcessLookupError:
        pass
    with contextlib.suppress(Exception):
        await asyncio.wait_for(process.wait(), timeout=10)


async def process_keyword(
    keyword: str,
    cluster: str,
    domain: Domain,
    source: str = "",
) -> str:
    from rankstein.production_safety import campaign_admission

    admission = campaign_admission([domain])
    if not admission["ok"]:
        logger.warning("[%s] Production deferred: %s", domain.handle, admission["issues"])
        return "Pending"
    qualified, qualification_reason, evidence = has_qualified_keyword_evidence(domain, keyword)
    if qualified and not (
        evidence
        and evidence.get("pinterest_origin") is True
        and "Pinterest Trends" in str(evidence.get("source") or "")
    ):
        qualified = False
        qualification_reason = "keyword_missing_pinterest_origin"
    if not qualified:
        logger.error(
            "[%s] Blocking article pipeline for unqualified keyword %r: %s",
            domain.handle,
            keyword,
            qualification_reason,
        )
        return "Failed"

    logger.info("Processing keyword %r for domain %s", keyword, domain.handle)
    slug = _slugify(keyword)
    existing_article = _check_existing_article(domain, slug)
    if existing_article:
        logger.info(
            "[%s] Article with slug %r already exists in DB (ID: %s, pin: %s). Skipping creation to avoid duplicate.",
            domain.handle,
            slug,
            existing_article.get("id"),
            existing_article.get("pinterest_pin_id"),
        )
        return "Live" if existing_article.get("pinterest_pin_id") else "Needs Verification"

    pipeline_run_id = _start_pipeline_telemetry(keyword, cluster, domain, source)
    _pipeline_event(
        pipeline_run_id,
        "keyword_selected",
        "complete",
        "Fresh Pinterest-first keyword evidence verified",
        specificity_score=evidence.get("specificity_score") if evidence else None,
        search_demand_score=evidence.get("search_demand_score") if evidence else None,
        research_source=evidence.get("source") if evidence else source,
    )
    if _PRODUCTION_BATCH_TRACKER is not None:
        _PRODUCTION_BATCH_TRACKER.attach_run(domain.handle, keyword, pipeline_run_id)
        _pipeline_event(
            pipeline_run_id,
            "keyword_selected",
            "complete",
            "Reserved for bounded production batch",
            batch_id=_PRODUCTION_BATCH_TRACKER.batch_id,
            target_per_domain=_PRODUCTION_BATCH_TRACKER.target_per_domain,
        )

    author = (
        "Atelier editorial de RecetaDolce"
        if "dolce" in domain.display_name.lower()
        else "Equipo editorial de RecetaGenial"
    )
    board_default = getattr(domain, "boards_default", {}).get("_default", "")
    cta_text = getattr(domain, "cta_text", "Ver receta completa")
    try:
        category = _normalize_category(cluster, cluster, domain, context=keyword)
    except CategoryPolicyError as exc:
        logger.error("[%s] Blocking incompatible keyword %r: %s", domain.handle, keyword, exc)
        _pipeline_event(
            pipeline_run_id,
            "keyword_selected",
            "failed",
            "Keyword does not fit an approved public category",
            reason=str(exc),
        )
        _pipeline_status(pipeline_run_id, "failed")
        return "Failed"
    base_url = f"https://{domain.domain}"

    step_images_scraped: list = []
    source_material = await _scrape_source_brief(
        keyword,
        domain,
        pipeline_run_id=pipeline_run_id,
        out_step_images=step_images_scraped,
    )
    if not source_material:
        _pipeline_event(
            pipeline_run_id,
            "source_extract",
            "failed",
            "Article writing blocked: fewer than two relevant recipe sources were extracted",
        )
        _pipeline_status(pipeline_run_id, "failed")
        return "Failed"

    _pipeline_event(
        pipeline_run_id,
        "article_write",
        "running",
        "OpenAI Codex is writing through the local Hermes gateway",
        provider="openai-codex",
    )

    try:
        # These names are referenced only by the retired fallback block below.
        prompt = ""
        gemini_cmd = shutil.which("gemini") or "gemini"
        last_error = "Unknown error"
        env = os.environ.copy()

        # === Strict Hermes/OpenAI Codex path ===
        provider_pref = os.environ.get("RANKSTEIN_ARTICLE_PROVIDER", "hermes-codex").strip().lower()
        allowed_providers = {
            "hermes",
            "hermes-codex",
            "hermes-codex-first-free",
            "hermes-codex-only",
            "codex-cli",
            "codex",
            "codex-only",
            "openai-codex",
            "omniroute",
        }
        if provider_pref not in allowed_providers:
            _pipeline_event(
                pipeline_run_id,
                "article_write",
                "failed",
                f"Unapproved article provider {provider_pref!r}; OpenAI Codex is required",
                provider=provider_pref,
            )
            _pipeline_status(pipeline_run_id, "failed")
            return "Failed"

        # Direct OmniRoute execution if explicitly requested
        if provider_pref == "omniroute":
            omni_model = os.environ.get("RANKSTEIN_OMNIROUTE_MODEL", "freee")
            omni_label = f"omniroute:{omni_model}"
            omniroute_article = await _call_omniroute_for_article(
                keyword,
                domain,
                source_material=source_material,
            )
            if omniroute_article and _openrouter_article_quality_check(omniroute_article):
                _pipeline_event(
                    pipeline_run_id,
                    "article_write",
                    "complete",
                    "OmniRoute returned complete article JSON",
                    provider=omni_label,
                )
                status = await _publish_generated_article(
                    omniroute_article,
                    keyword,
                    cluster,
                    domain,
                    pipeline_run_id,
                    step_images=step_images_scraped,
                )
                if status in {"Live", "Needs Verification"}:
                    logger.info("OmniRoute production succeeded for %s -> %s", keyword, status)
                    return status
                logger.warning("OmniRoute publication failed for %s: %s", keyword, status)
                return status
            logger.warning("OmniRoute generation/quality check failed for %s", keyword)
            return "Failed"

        # Try Codex CLI first (direct ChatGPT subscription, no gateway needed)
        if provider_pref in {"codex-cli", "codex", "openai-codex", ""}:
            codex_article = await _call_codex_cli_for_article(
                keyword,
                domain,
                source_material=source_material,
            )
            if codex_article and _openrouter_article_quality_check(codex_article):
                _pipeline_event(
                    pipeline_run_id,
                    "article_write",
                    "complete",
                    "OpenAI Codex CLI returned complete article JSON",
                    provider="openai-codex-cli",
                )
                status = await _publish_generated_article(
                    codex_article,
                    keyword,
                    cluster,
                    domain,
                    pipeline_run_id,
                    step_images=step_images_scraped,
                )
                if status in {"Live", "Needs Verification"}:
                    logger.info("OpenAI Codex CLI production succeeded for %s -> %s", keyword, status)
                    return status
                logger.warning("OpenAI Codex CLI publication failed for %s: %s", keyword, status)
                return status
            else:
                logger.warning("OpenAI Codex CLI generation/quality check failed for %s", keyword)

        # The attested Hermes gateway is the final Codex attempt. Its result
        # distinguishes provider availability from HTTP-200 content rejection,
        # so a free model is never used merely because an article failed quality.
        hermes_result = await _call_hermes_codex_for_article_result(
            keyword,
            domain,
            source_material=source_material,
        )
        hermes_article = hermes_result.article
        if hermes_article and _openrouter_article_quality_check(hermes_article):
            _pipeline_event(
                pipeline_run_id,
                "article_write",
                "complete",
                "OpenAI Codex returned complete article JSON",
                provider="openai-codex",
            )
            status = await _publish_generated_article(
                hermes_article,
                keyword,
                cluster,
                domain,
                pipeline_run_id,
                step_images=step_images_scraped,
            )
            if status in {"Live", "Needs Verification"}:
                logger.info("OpenAI Codex production succeeded for %s -> %s", keyword, status)
                return status
            logger.warning("OpenAI Codex publication failed for %s: %s", keyword, status)
            return status

        strict_codex_only = provider_pref in {"hermes-codex-only", "codex-only"}
        if strict_codex_only:
            _pipeline_event(
                pipeline_run_id,
                "article_write",
                "failed",
                "Strict Codex-only mode does not permit any fallback",
                provider="openai-codex",
                outcome=hermes_result.outcome,
                detail=hermes_result.detail,
            )
            _pipeline_status(pipeline_run_id, "failed")
            return "Failed"

        # === 1ST FALLBACK OPTION: OmniRoute AI Gateway ===
        if os.environ.get("RANKSTEIN_ENABLE_OMNIROUTE_FALLBACK", "1").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            omni_model = os.environ.get("RANKSTEIN_OMNIROUTE_MODEL", "freee")
            omni_label = f"omniroute:{omni_model}"
            logger.warning(
                "Codex did not produce an article for %s; invoking OmniRoute as 1st fallback (%s)",
                keyword,
                omni_label,
            )
            _pipeline_event(
                pipeline_run_id,
                "article_write",
                "running",
                "Codex unavailable or failed; invoking OmniRoute gateway as 1st fallback",
                provider=omni_label,
                fallback_reason=hermes_result.detail,
            )
            omniroute_article = await _call_omniroute_for_article(
                keyword,
                domain,
                source_material=source_material,
            )
            if omniroute_article and _openrouter_article_quality_check(omniroute_article):
                _pipeline_event(
                    pipeline_run_id,
                    "article_write",
                    "complete",
                    "OmniRoute 1st fallback returned complete article JSON",
                    provider=omni_label,
                )
                status = await _publish_generated_article(
                    omniroute_article,
                    keyword,
                    cluster,
                    domain,
                    pipeline_run_id,
                    step_images=step_images_scraped,
                )
                if status in {"Live", "Needs Verification"}:
                    logger.info("OmniRoute fallback production succeeded for %s -> %s", keyword, status)
                    return status
                logger.warning("OmniRoute publication failed for %s: %s", keyword, status)
                return status
            else:
                logger.warning("OmniRoute 1st fallback failed or quality check rejected for %s", keyword)

        # === 2ND FALLBACK OPTION: Hermes Free Model (if availability permits) ===
        if not hermes_result.permits_free_fallback:
            reason = "Codex returned a rejected response; free Hermes fallback is not permitted"
            _pipeline_event(
                pipeline_run_id,
                "article_write",
                "failed",
                reason,
                provider="openai-codex",
                outcome=hermes_result.outcome,
                detail=hermes_result.detail,
            )
            _pipeline_status(pipeline_run_id, "failed")
            return "Failed"

        target_ok, target_detail = _hermes_free_article_target()
        if target_ok:
            free_provider, free_model = target_detail
            free_provider_label = f"hermes-free:{free_provider}/{free_model}"
            logger.warning(
                "Codex and OmniRoute unavailable for %s; invoking approved free Hermes model %s/%s as 2nd fallback",
                keyword,
                free_provider,
                free_model,
            )
            _pipeline_event(
                pipeline_run_id,
                "article_write",
                "running",
                "Codex and OmniRoute unavailable; trying approved free Hermes model",
                provider=free_provider_label,
                fallback_reason=hermes_result.detail,
            )
            free_article = await _call_hermes_free_for_article(
                keyword,
                domain,
                source_material=source_material,
            )
            if free_article and _openrouter_article_quality_check(free_article):
                _pipeline_event(
                    pipeline_run_id,
                    "article_write",
                    "complete",
                    "Approved free Hermes model returned complete article JSON",
                    provider=free_provider_label,
                )
                status = await _publish_generated_article(
                    free_article,
                    keyword,
                    cluster,
                    domain,
                    pipeline_run_id,
                    step_images=step_images_scraped,
                )
                if status in {"Live", "Needs Verification"}:
                    logger.info("Hermes free model production succeeded for %s -> %s", keyword, status)
                    return status
        else:
            free_provider_label = "hermes-free-unavailable"

        _pipeline_event(
            pipeline_run_id,
            "article_write",
            "failed",
            "Codex, OmniRoute, and approved free Hermes providers did not return a publishable article",
            provider=free_provider_label,
            fallback_reason=hermes_result.detail,
            free_provider_available=target_ok,
            free_provider_detail=target_detail if target_ok else str(target_detail),
        )
        _pipeline_status(pipeline_run_id, "failed")
        return "Failed"
        prompt = _build_generation_prompt(keyword, domain, source_material=source_material)

        # === Odysseus/Gemini proxy fallback path ===
        proxy_url = os.environ.get(
            "RANKSTEIN_GEMINI_PROXY_URL", "http://127.0.0.1:7000/gemini/v1/chat/completions"
        )
        if proxy_url:
            for model in _worker_models():
                logger.info("Invoking Odysseus Proxy model=%s for %s", model, keyword)
                _pipeline_event(
                    pipeline_run_id,
                    "article_write",
                    "running",
                    f"Odysseus proxy is writing with {model}",
                    provider=f"odysseus:{model}",
                )
                session = _get_session()
                try:
                    resp = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda m=model, s=session: s.post(
                            proxy_url,
                            headers={"Authorization": "Bearer ody_proxy", "Content-Type": "application/json"},
                            json={
                                "model": m,
                                "messages": [{"role": "user", "content": prompt}],
                                "stream": False,
                            },
                            timeout=_gemini_timeout_seconds(),
                        ),
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        content = data["choices"][0]["message"]["content"]
                        article = _parse_llm_json_response(content)
                        if article:
                            _pipeline_event(
                                pipeline_run_id,
                                "article_write",
                                "complete",
                                f"Odysseus proxy returned article JSON via {model}",
                                provider=f"odysseus:{model}",
                            )
                            status = await _publish_openrouter_article(
                                article,
                                keyword,
                                cluster,
                                domain,
                                pipeline_run_id,
                                step_images=step_images_scraped,
                            )
                            logger.info("Proxy published %s -> %s", keyword, status)
                            if status in {"Live", "Needs Verification"}:
                                return status
                        logger.warning("Proxy article for %s not parseable or publish failed", keyword)
                    else:
                        logger.warning(
                            "Proxy model=%s failed for %s: %s",
                            model,
                            keyword,
                            resp.text[:1000],
                        )
                        if (
                            "rate limited" in resp.text.lower()
                            or "exhausted" in resp.text.lower()
                            or resp.status_code in (429, 502, 503)
                        ):
                            continue
                        break
                except requests.exceptions.ConnectionError:
                    logger.warning(
                        "Odysseus proxy not reachable at %s, falling back to OpenCode/Subprocess",
                        proxy_url,
                    )
                    break
                except Exception as e:
                    logger.warning("Proxy model=%s error for %s: %s", model, keyword, str(e))
                    continue

        # === OpenCode LLM fallback path (Hermes-adjacent provider) ===
        logger.info("Falling back to OpenCode LLM for %s", keyword)
        _pipeline_event(
            pipeline_run_id,
            "article_write",
            "running",
            "OpenCode fallback is writing the article",
            provider="opencode",
        )
        opencode_article = await _call_opencode_for_article(keyword, domain, source_material=source_material)
        if opencode_article and _openrouter_article_quality_check(opencode_article):
            _pipeline_event(
                pipeline_run_id,
                "article_write",
                "complete",
                "OpenCode returned complete article JSON",
                provider="opencode",
            )
            status = await _publish_openrouter_article(
                opencode_article,
                keyword,
                cluster,
                domain,
                pipeline_run_id,
                step_images=step_images_scraped,
            )
            if status in {"Live", "Needs Verification"}:
                logger.info("OpenCode fallback succeeded for %s -> %s", keyword, status)
                return status
            logger.warning("OpenCode fallback publication failed for %s: %s", keyword, status)
        # Direct Gemini REST API fallback (using GEMINI_API_KEY / GOOGLE_API_KEY)
        gemini_api_article = await _call_gemini_api_for_article(
            keyword, domain, source_material=source_material
        )
        if gemini_api_article and _openrouter_article_quality_check(gemini_api_article):
            _pipeline_event(
                pipeline_run_id,
                "article_write",
                "complete",
                "Gemini REST API returned complete article JSON",
                provider="gemini-api",
            )
            status = await _publish_openrouter_article(
                gemini_api_article,
                keyword,
                cluster,
                domain,
                pipeline_run_id,
                step_images=step_images_scraped,
            )
            if status in {"Live", "Needs Verification"}:
                logger.info("Gemini REST API fallback succeeded for %s -> %s", keyword, status)
                return status
            logger.warning("Gemini REST API publication failed for %s: %s", keyword, status)

        # Ensure primary account token is active before starting Gemini CLI
        ensure_account_1()
        for model in _worker_models():
            logger.info("Invoking Gemini CLI model=%s for %s [%s]", model, keyword, current_account_label())
            _pipeline_event(
                pipeline_run_id,
                "article_write",
                "running",
                f"Gemini CLI is writing with {model}",
                provider=f"gemini:{model}",
            )
            cmd = [gemini_cmd, "--yolo", "--skip-trust", "-p", ""]
            if model.lower() != "auto":
                cmd.extend(["-m", model])
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(input=prompt.encode("utf-8")),
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
                _pipeline_event(
                    pipeline_run_id,
                    "article_write",
                    "failed",
                    f"Gemini CLI timed out with {model}",
                    provider=f"gemini:{model}",
                )
                _pipeline_status(pipeline_run_id, "failed")
                return "Failed"
            stderr_text = stderr.decode(errors="replace")
            filtered_stderr = _strip_gemini_cli_noise(stderr_text)

            if process.returncode == 0:
                stdout_text = stdout.decode(errors="replace")
                # Try to parse full article JSON from Gemini output and publish it
                article = _parse_llm_json_response(stdout_text)
                if article:
                    _pipeline_event(
                        pipeline_run_id,
                        "article_write",
                        "complete",
                        f"Gemini CLI returned article JSON via {model}",
                        provider=f"gemini:{model}",
                    )
                    status = await _publish_openrouter_article(
                        article,
                        keyword,
                        cluster,
                        domain,
                        pipeline_run_id,
                        step_images=step_images_scraped,
                    )
                    logger.info("Gemini published %s -> %s", keyword, status)
                    if status in {"Live", "Needs Verification"}:
                        return status
                    # Publication failed; fall through to other paths
                    logger.warning("Gemini article publication failed for %s: %s", keyword, status)
                else:
                    logger.warning(
                        "Gemini model=%s output for %s not parseable as article JSON; "
                        "checking completion proof only. Output length=%d",
                        model,
                        keyword,
                        len(stdout_text),
                    )
                    status = _status_from_completion_output(stdout_text)
                    logger.info("Gemini proof-only status for %s -> %s", keyword, status)
                    if status == "Live":
                        return status
                    # Not Live → try other generation paths

            last_error = (
                filtered_stderr or "Gemini CLI exited without article output after cosmetic terminal warnings"
            )

            # Token rotation on quota exhaustion
            if is_quota_exhausted(filtered_stderr):
                new_account = rotate_account()
                logger.warning(
                    "Gemini quota exhausted for %s; rotated to %s and retrying with next model.",
                    keyword,
                    new_account or "NONE (no fallback accounts)",
                )
                continue  # try next model with different account token

            if _is_retryable_model_error(filtered_stderr):
                logger.warning(
                    "Gemini model=%s capacity/rate failure for %s; trying fallback.",
                    model,
                    keyword,
                )
                continue
            if not filtered_stderr:
                logger.warning(
                    "Gemini model=%s returned only cosmetic terminal warnings for %s; trying fallback.",
                    model,
                    keyword,
                )
                continue
            logger.error("Gemini model=%s failed for %s: %s", model, keyword, filtered_stderr[-2000:])
            break

        logger.error("All Gemini models exhausted for %s: %s", keyword, last_error)

        # === OpenCode LLM fallback (Hermes agent's own provider) — tried first ===
        logger.info("Falling back to OpenCode LLM for %s", keyword)
        _pipeline_event(
            pipeline_run_id,
            "article_write",
            "running",
            "Retrying article writing with OpenCode",
            provider="opencode",
        )
        opencode_article = await _call_opencode_for_article(keyword, domain, source_material=source_material)
        if opencode_article and _openrouter_article_quality_check(opencode_article):
            _pipeline_event(
                pipeline_run_id,
                "article_write",
                "complete",
                "OpenCode returned complete article JSON",
                provider="opencode",
            )
            status = await _publish_openrouter_article(
                opencode_article,
                keyword,
                cluster,
                domain,
                pipeline_run_id,
            )
            if status in {"Live", "Needs Verification"}:
                logger.info("OpenCode fallback succeeded for %s -> %s", keyword, status)
                return status
            logger.warning("OpenCode fallback publication failed for %s: %s", keyword, status)

        # === OpenRouter LLM fallback ===
        logger.info("Falling back to OpenRouter LLM for %s", keyword)
        _pipeline_event(
            pipeline_run_id,
            "article_write",
            "running",
            "OpenRouter fallback is writing the article",
            provider="openrouter",
        )
        openrouter_article = await _call_openrouter_for_article(
            prompt,
            keyword,
            domain,
            source_material=source_material,
        )
        if openrouter_article and _openrouter_article_quality_check(openrouter_article):
            _pipeline_event(
                pipeline_run_id,
                "article_write",
                "complete",
                "OpenRouter returned complete article JSON",
                provider="openrouter",
            )
            status = await _publish_openrouter_article(
                openrouter_article,
                keyword,
                cluster,
                domain,
                pipeline_run_id,
            )
            if status in {"Live", "Needs Verification"}:
                logger.info("OpenRouter fallback succeeded for %s -> %s", keyword, status)
                return status
            logger.warning("OpenRouter fallback publication failed for %s: %s", keyword, status)

        logger.warning("All LLM fallbacks exhausted for %s", keyword)
        if "cosmetic terminal warnings" in last_error:
            _pipeline_event(
                pipeline_run_id,
                "article_write",
                "waiting",
                "Providers exited without verifiable article JSON",
            )
            _pipeline_status(pipeline_run_id, "pending")
            return "Pending"
        _pipeline_event(
            pipeline_run_id,
            "article_write",
            "failed",
            "All configured LLM providers failed",
            error=last_error[-240:],
        )
        _pipeline_status(pipeline_run_id, "failed")
        return "Failed"
    except Exception as exc:
        logger.error("Crash: %s - %s", keyword, exc)
        _pipeline_event(
            pipeline_run_id,
            "article_write",
            "failed",
            "Article worker crashed",
            error=str(exc)[:240],
        )
        _pipeline_status(pipeline_run_id, "failed")
        return "Failed"


def _load_pinterest_qualified_keyword_keys(domain: Domain) -> tuple[set[str], str]:
    """Restrict production authorization to explicitly proven Pinterest phrases."""
    eligible, reason = load_qualified_keyword_keys(domain)
    if eligible:
        try:
            payload = json.loads((domain.root / "daily_best_keywords.json").read_text(encoding="utf-8"))
            pinterest_keys = {
                str(item.get("keyword") or "").strip().casefold()
                for item in payload.get("items", [])
                if isinstance(item, dict)
                and item.get("pinterest_origin") is True
                and "Pinterest Trends" in str(item.get("source") or "")
                and item.get("qualified") is True
            }
            active_eligible = eligible & pinterest_keys
            if active_eligible:
                return active_eligible, "ok"
        except (OSError, UnicodeError, ValueError):
            pass

    # If daily_best_keywords has no unattempted qualified keys, check if roadmap has pending keywords
    if getattr(domain, "keywords_file", None) and domain.keywords_file.exists():
        roadmap_rows = read_keyword_rows(domain.keywords_file)
        roadmap_pending = [
            row.keyword.strip().casefold()
            for row in roadmap_rows
            if row.status.strip().casefold() == "pending"
            and _production_discovery_keyword_allowed(row.keyword, domain)
        ]
        if roadmap_pending:
            from rankstein.trend_intelligence import sync_roadmap_pending_to_daily_best

            with contextlib.suppress(Exception):
                sync_roadmap_pending_to_daily_best(domain, limit=15)
            return set(roadmap_pending), "ok"

    return set(), reason if not eligible else "keyword_missing_pinterest_origin"


def _production_discovery_keyword_allowed(keyword: str, domain: Domain) -> bool:
    """Reject off-domain, pet, and known foreign-language Pinterest noise."""
    folded = _ascii_fold(keyword)
    if re.search(r"\b(gatos?|perros?|mascotas?|cachorros?|cats?|dogs?|pets?)\b", folded):
        return False
    if domain.language.casefold().startswith("es") and re.search(
        r"\b(saudavel|saudaveis|recheio|bolo|fazer|receitas?|frango|morango|forno|recipes?|chicken)\b",
        folded,
    ):
        return False
    # This legacy guide label carries no ingredient/style identity. Keep the
    # maintained specificity policy (including legitimate homemade searches)
    # intact while rejecting this known noisy Pending phrase.
    if re.fullmatch(r"croquetas?(?:\s+caser[oa]s?)?\s+recetas?\s+para\s+hacer", folded):
        return False
    if not is_recipe_aware_keyword(keyword, domain=domain) or _keyword_specificity_score(keyword) <= 0:
        return False
    try:
        _normalize_category("", "", domain, context=keyword)
    except CategoryPolicyError:
        return False
    return True


_TREND_VALIDATION_WORKER = """
import contextlib
import json
import sys
from pathlib import Path

request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
sys.path.insert(0, request["project_root"])
try:
    with contextlib.redirect_stdout(sys.stderr):
        from pydantic import SecretStr
        from rankstein.domain import Domain
        from rankstein.trend_intelligence import refresh_domain_trend_lists

        metadata = request["domain"]
        for name in ("root", "keywords_file", "sessions_dir", "output_dir", "branding_dir"):
            metadata[name] = Path(metadata[name])
        metadata["categories"] = tuple(metadata["categories"])
        domain = Domain(
            **metadata,
            pinterest_email="",
            pinterest_password=SecretStr(""),
            supabase_url="",
            supabase_service_role_key=SecretStr(""),
        )
        report = refresh_domain_trend_lists(
            [domain],
            limit_per_domain=15,
            append_to_roadmap=True,
            pinterest_terms=request["pinterest_terms"],
            region=request["region"],
            use_playwright=True,
            candidate_origin_policy="pinterest_required",
        )
    result = {"report": report}
except Exception as error:
    result = {"error_type": type(error).__name__, "error_detail": str(error)}
sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
"""


def _trend_research_deadline(name: str, maximum: float) -> float:
    try:
        configured = float(os.environ.get(name, str(maximum)))
        if configured != configured or configured <= 0:
            raise ValueError
    except ValueError:
        configured = maximum
    return min(maximum, max(0.01, configured))


def _record_trend_research_status(
    domain: Domain,
    status: str,
    *,
    stage: str,
    deadline_seconds: float,
    started_at: float,
    **details,
) -> None:
    elapsed = max(0.0, time.monotonic() - started_at)
    reason = (
        f"{status} stage={stage} deadline_seconds={deadline_seconds:g} "
        f"deadline_at={time.time() + deadline_seconds - elapsed:.3f} "
        f"elapsed_seconds={elapsed:.3f}"
    )
    if details:
        reason += " " + " ".join(f"{key}={value}" for key, value in details.items())
    logger.info("[%s] Trend research %s", domain.handle, reason)
    if _PRODUCTION_BATCH_TRACKER is not None:
        try:
            _PRODUCTION_BATCH_TRACKER.mark_domain_waiting(domain.handle, reason)
        except Exception as exc:
            logger.warning("[%s] Research status write failed: %s", domain.handle, type(exc).__name__)


async def _run_bounded_trend_validation(
    domain: Domain,
    pinterest_terms: list[str],
    *,
    region: str,
    timeout: float,
) -> dict:
    """Use the maintained strict service in a child that cannot outlive cancellation.

    Only non-secret domain metadata and already-observed Pinterest phrases are
    sent over stdin. Killing and reaping the owned child prevents late report or
    roadmap writes; a cancelled executor thread cannot provide that guarantee.
    """

    metadata = {
        name: getattr(domain, name)
        for name in (
            "handle",
            "domain",
            "display_name",
            "language",
            "niche",
            "categories",
            "boards_default",
            "primary_color",
            "accent_color",
            "brand_name_short",
            "cta_text",
            "daily_pin_budget",
        )
    }
    for name in ("root", "keywords_file", "sessions_dir", "output_dir", "branding_dir"):
        metadata[name] = str(getattr(domain, name).resolve())
    request = json.dumps(
        {
            "project_root": str(PROJECT_ROOT.resolve()),
            "domain": metadata,
            "pinterest_terms": pinterest_terms,
            "region": region,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    process = None
    started_at = time.monotonic()
    try:
        process = await _create_owned_subprocess(
            sys.executable,
            "-u",
            "-c",
            _TREND_VALIDATION_WORKER,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=clean_python_env(),
        )
        remaining = max(0.001, timeout - (time.monotonic() - started_at))
        stdout, stderr_bytes = await asyncio.wait_for(process.communicate(request), timeout=remaining)
        if process.returncode != 0:
            stderr_msg = stderr_bytes.decode(errors="replace").strip() if stderr_bytes else ""
            raise RuntimeError(f"Exact validation worker exited with code {process.returncode}: {stderr_msg}")
        result = json.loads(stdout)
        if result.get("error_type"):
            error_detail = result.get("error_detail", "")
            raise RuntimeError(f"Exact validation worker failed: {result['error_type']} ({error_detail})")
        if not isinstance(result.get("report"), dict):
            raise ValueError("Exact validation worker returned no report")
        return result["report"]
    finally:
        await _cleanup_owned_process(process)


async def _auto_refresh_keywords(domain: Domain, *, excluded_keywords: set[str] | None = None) -> int:
    """Discover unattempted Pinterest phrases before exact independent validation.

    Collect at most 240 observed phrases, enough to walk the collector's maximum
    24 seed queries at its ten-phrase per-query cap. The browser deadline cancels
    the async collector and runs its cleanup rather than abandoning a live
    background thread that could lock the next refresh's domain profile.
    """
    stage = "pinterest_collection"
    deadline_seconds = _trend_research_deadline("RANKSTEIN_TREND_COLLECTION_TIMEOUT_SECONDS", 300)
    started_at = time.monotonic()
    _record_trend_research_status(
        domain, "research_in_progress", stage=stage, deadline_seconds=deadline_seconds, started_at=started_at
    )
    try:
        from rankstein.trend_intelligence import (
            DEFAULT_REGION,
            _fetch_pinterest_niche_trending_terms_async,
        )

        logger.info(
            "[%s] Queue empty — Pinterest Trends/Search supplies candidates; Google News, Google Trends, and Suggestions validate exact phrases…",
            domain.handle,
        )
        excluded = {keyword.strip().casefold() for keyword in (excluded_keywords or set())}
        excluded.update(
            row.keyword.strip().casefold()
            for row in read_keyword_rows(domain.keywords_file)
            if row.status.strip().casefold() != "pending"
        )
        region = (os.environ.get("RANKSTEIN_TRENDS_REGION") or DEFAULT_REGION).upper()
        observed_terms = await asyncio.wait_for(
            _fetch_pinterest_niche_trending_terms_async(domain, region, 240),
            timeout=deadline_seconds,
        )
        fresh_terms = [
            term
            for term in observed_terms
            if term.strip().casefold() not in excluded and _production_discovery_keyword_allowed(term, domain)
        ]
        logger.info(
            "[%s] Pinterest discovery observed %d phrases; %d unattempted in-domain candidates remain before ranking.",
            domain.handle,
            len(observed_terms),
            len(fresh_terms),
        )
        stage = "exact_validation"
        deadline_seconds = _trend_research_deadline("RANKSTEIN_TREND_VALIDATION_TIMEOUT_SECONDS", 600)
        started_at = time.monotonic()
        _record_trend_research_status(
            domain,
            "research_in_progress",
            stage=stage,
            deadline_seconds=deadline_seconds,
            started_at=started_at,
            observed_count=len(observed_terms),
            eligible_count=len(fresh_terms),
        )
        report = await _run_bounded_trend_validation(
            domain,
            fresh_terms,
            region=region,
            timeout=deadline_seconds,
        )
        added = report.get("domains", {}).get(domain.handle, {}).get("roadmap_added", 0)
        _record_trend_research_status(
            domain,
            "research_complete",
            stage=stage,
            deadline_seconds=deadline_seconds,
            started_at=started_at,
            new_pending_count=added,
        )
        logger.info(
            "[%s] Trend refresh complete — %d new Pending keywords added to roadmap.",
            domain.handle,
            added,
        )
        return added
    except asyncio.CancelledError:
        _record_trend_research_status(
            domain,
            "research_cancelled",
            stage=stage,
            deadline_seconds=deadline_seconds,
            started_at=started_at,
            error_type="CancelledError",
        )
        raise
    except Exception as exc:
        status = "research_timeout" if isinstance(exc, TimeoutError) else "research_failed"
        _record_trend_research_status(
            domain,
            status,
            stage=stage,
            deadline_seconds=deadline_seconds,
            started_at=started_at,
            error_type=type(exc).__name__,
        )
        logger.warning(
            "[%s] Trend refresh failed: %s during %s (deadline=%gs, elapsed=%.3fs) — will retry next cycle.",
            domain.handle,
            type(exc).__name__,
            stage,
            deadline_seconds,
            time.monotonic() - started_at,
        )
        return 0


async def _reconcile_awaiting_articles(
    domain: Domain, *, max_campaigns: int | None = None, cursor: int = 0
) -> int:
    """Finish late primary pins without publishing another copy of the article."""
    import sqlite3

    from pinterest_automation import get_job_queue
    from rankstein.pipeline_events import PIPELINE_DB
    from rankstein.production_reconcile import ReconciliationError, reconcile_production_article

    tracker = _PRODUCTION_BATCH_TRACKER
    if tracker is None or not PIPELINE_DB.exists():
        return cursor
    articles = [
        article
        for article in tracker.data["domains"][domain.handle].get("articles", [])
        if str(article.get("state") or "").replace("_", " ").casefold() == "needs verification"
        and article.get("pipeline_run_id")
    ]
    if not articles:
        return 0
    start = cursor % len(articles)
    attempted = 0
    # Primary uploads and the singleton supervisor use the shared queue. Domain
    # identity is validated by the exact-job reconciler, not by opening a
    # different database that never receives these jobs.
    queue = get_job_queue()
    for offset in range(len(articles)):
        index = (start + offset) % len(articles)
        article = articles[index]
        run_id = article.get("pipeline_run_id")
        try:
            with sqlite3.connect(
                PIPELINE_DB.resolve().as_uri() + "?mode=ro", uri=True, timeout=2
            ) as connection:
                rows = connection.execute(
                    "SELECT details_json FROM pipeline_events WHERE run_id = ? "
                    "AND stage = 'primary_pin_publish' ORDER BY id DESC LIMIT 50",
                    (run_id,),
                ).fetchall()
            job_id = next(
                (
                    str(job_id)
                    for row in rows
                    if (details := json.loads(row[0]))
                    and (job_id := details.get("job_id") or details.get("primary_job_id"))
                ),
                "",
            )
            if not job_id:
                continue
            outcome = await queue.get_job_outcome_async(job_id)
            if outcome.get("state") != "completed":
                continue
            attempted += 1
            await asyncio.wait_for(
                reconcile_production_article(
                    batch_id=tracker.batch_id,
                    domain_handle=domain.handle,
                    pipeline_run_id=run_id,
                    primary_job_id=job_id,
                    batch_tracker=tracker,
                ),
                timeout=900,
            )
            logger.info("[%s] Late Pinterest proof verified for %s", domain.handle, article["keyword"])
        except ReconciliationError as exc:
            logger.info("[%s] Pinterest campaign still needs verification: %s", domain.handle, exc)
        except Exception as exc:
            logger.warning("[%s] Late Pinterest reconciliation will retry: %s", domain.handle, exc)
        if max_campaigns is not None and attempted >= max(1, max_campaigns):
            return (index + 1) % len(articles)
    return (start + 1) % len(articles)


class _DomainRepairLane:
    """Owned, fair, single-flight campaign repair independent of article writing."""

    def __init__(self, domain: Domain) -> None:
        self.domain = domain
        self.task: asyncio.Task | None = None
        self.cursor = 0
        self.next_due_at = 0.0

    def schedule(self) -> None:
        if self.task is not None:
            if not self.task.done():
                return
            try:
                result = self.task.result()
                if isinstance(result, int):
                    self.cursor = result
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning("[%s] Background campaign repair will retry: %s", self.domain.handle, exc)
            self.task = None
            self.next_due_at = time.monotonic() + 60
        if time.monotonic() < self.next_due_at:
            return
        self.task = asyncio.create_task(
            _reconcile_awaiting_articles(self.domain, max_campaigns=1, cursor=self.cursor),
            name=f"campaign-repair:{self.domain.handle}",
        )

    async def close(self) -> None:
        task = self.task
        if task is None:
            return
        if not task.done():
            task.cancel()
        # Child cleanup already shields/reaps its exact owned process tree.
        # Repeated parent cancellation must not abandon that cleanup.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        with contextlib.suppress(asyncio.CancelledError, Exception):
            task.result()
        self.task = None


async def _run_domain(
    domain: Domain,
    workers: int,
    limit: int,
    once: bool,
    success_target: int = 0,
) -> None:
    repairs = _DomainRepairLane(domain)
    try:
        await _run_domain_foreground(domain, workers, limit, once, success_target, repairs=repairs)
    finally:
        await repairs.close()


async def _run_domain_foreground(
    domain: Domain,
    workers: int,
    limit: int,
    once: bool,
    success_target: int = 0,
    *,
    repairs: _DomainRepairLane,
) -> None:
    """Continuous keyword worker for a single domain. Loops until all keywords exhausted or once=True."""
    roadmap_title = f"{domain.display_name} Keyword Roadmap"
    batch_size = max(1, min(limit, workers))
    logger.info("[%s] worker started (%d workers, batch=%d)", domain.handle, workers, batch_size)
    _consecutive_empty = 0
    attempted_keywords = set()
    if _PRODUCTION_BATCH_TRACKER is not None:
        attempted_keywords = _PRODUCTION_BATCH_TRACKER.attempted_keyword_keys(domain.handle)

    while True:
        from rankstein.production_safety import campaign_admission

        admission = campaign_admission([domain], campaigns_per_domain=batch_size)
        if not admission["ok"]:
            reason = "; ".join(admission["issues"])
            logger.warning("[%s] Production admission blocked: %s", domain.handle, reason)
            if _PRODUCTION_BATCH_TRACKER is not None:
                _PRODUCTION_BATCH_TRACKER.mark_domain_waiting(domain.handle, reason)
            if once or success_target:
                return
            await asyncio.sleep(300)
            continue
        if success_target and _PRODUCTION_BATCH_TRACKER is not None:
            repairs.schedule()
            verified = _PRODUCTION_BATCH_TRACKER.verified(domain.handle)
            if verified >= success_target:
                logger.info(
                    "[%s] production target reached (%d/%d verified)",
                    domain.handle,
                    verified,
                    success_target,
                )
                _PRODUCTION_BATCH_TRACKER.finish_if_complete()
                return
            available_slots = success_target - _PRODUCTION_BATCH_TRACKER.published_count(domain.handle)
            if available_slots <= 0:
                _PRODUCTION_BATCH_TRACKER.mark_domain_waiting(
                    domain.handle,
                    "Published article target reached; waiting for Pinterest pin and campaign verification",
                )
                logger.info(
                    "[%s] Published article target reached; waiting for Pinterest verification (%d/%d verified).",
                    domain.handle,
                    verified,
                    success_target,
                )
                await asyncio.sleep(300)
                continue
            batch_size = max(1, min(workers, available_slots))

        if not domain.keywords_file.exists():
            logger.warning("[%s] keywords file missing: %s", domain.handle, domain.keywords_file)
            if once:
                return
            await asyncio.sleep(120)
            continue

        eligible_keywords, research_reason = _load_pinterest_qualified_keyword_keys(domain)
        eligible_keywords -= attempted_keywords
        eligible_keywords = {
            keyword for keyword in eligible_keywords if _production_discovery_keyword_allowed(keyword, domain)
        }
        pending = reserve_pending_keywords(
            domain.keywords_file,
            roadmap_title,
            batch_size,
            eligible_keywords=eligible_keywords,
        )
        if not pending:
            # Check if roadmap already has unattempted allowed Pending keywords
            batch_articles = (
                _PRODUCTION_BATCH_TRACKER.data["domains"][domain.handle].get("articles", [])
                if _PRODUCTION_BATCH_TRACKER is not None
                else []
            )
            ever_attempted_in_batch = {
                str(article.get("keyword") or "").strip().casefold() for article in batch_articles
            }
            roadmap_rows = read_keyword_rows(domain.keywords_file)
            fallback_candidates = {
                row.keyword.strip().casefold()
                for row in roadmap_rows
                if row.status.strip().casefold() == "pending"
                and row.keyword.strip().casefold() not in attempted_keywords
                and row.keyword.strip().casefold() not in ever_attempted_in_batch
                and _production_discovery_keyword_allowed(row.keyword, domain)
            }
            if fallback_candidates:
                pending = reserve_pending_keywords(
                    domain.keywords_file,
                    roadmap_title,
                    batch_size,
                    eligible_keywords=fallback_candidates,
                )
                if pending:
                    logger.info(
                        "[%s] Reserved %d pending keyword(s) from roadmap (skipped new keyword search); roadmap has %d unattempted pending.",
                        domain.handle,
                        len(pending),
                        len(fallback_candidates),
                    )

        if not pending:
            _consecutive_empty += 1
            logger.info(
                "[%s] Queue empty (consecutive=%d). Triggering trend refresh to refill roadmap…",
                domain.handle,
                _consecutive_empty,
            )
            if _PRODUCTION_BATCH_TRACKER is not None:
                _PRODUCTION_BATCH_TRACKER.mark_domain_waiting(
                    domain.handle,
                    "No unattempted Pinterest keyword; researching new candidates",
                )
            if research_reason != "ok":
                logger.info(
                    "[%s] Keyword evidence unavailable (%s); refresh is mandatory before reservation.",
                    domain.handle,
                    research_reason,
                )
            added = await _auto_refresh_keywords(domain, excluded_keywords=attempted_keywords)
            refreshed_eligible, refreshed_reason = _load_pinterest_qualified_keyword_keys(domain)
            refreshed_eligible -= attempted_keywords
            refreshed_eligible = {
                keyword
                for keyword in refreshed_eligible
                if _production_discovery_keyword_allowed(keyword, domain)
            }
            fresh_pending = any(
                row.status.casefold() == "pending" and row.keyword.strip().casefold() in refreshed_eligible
                for row in read_keyword_rows(domain.keywords_file)
            )
            if not fresh_pending:
                from rankstein.trend_intelligence import replenish_domain_roadmap_keywords

                replenished = replenish_domain_roadmap_keywords(domain, count=15)
                if replenished:
                    added += replenished
                    refreshed_eligible, refreshed_reason = _load_pinterest_qualified_keyword_keys(domain)
                    refreshed_eligible -= attempted_keywords
                    refreshed_eligible = {
                        keyword
                        for keyword in refreshed_eligible
                        if _production_discovery_keyword_allowed(keyword, domain)
                    }
                    fresh_pending = any(
                        row.status.casefold() == "pending"
                        and row.keyword.strip().casefold() in refreshed_eligible
                        for row in read_keyword_rows(domain.keywords_file)
                    )

            if fresh_pending:
                logger.info(
                    "[%s] Fresh research authorized %d keyword(s); retrying reservation now.",
                    domain.handle,
                    len(refreshed_eligible),
                )
                _consecutive_empty = 0
                if _PRODUCTION_BATCH_TRACKER is not None:
                    _PRODUCTION_BATCH_TRACKER.mark_domain_running(domain.handle)
                continue
            if once and not success_target:
                logger.info(
                    "[%s] One-shot run stopped: no keyword passed fresh Pinterest and demand gates.",
                    domain.handle,
                )
                return
            logger.info(
                "[%s] No unattempted qualified Pending keyword after refresh (%d rows added). Waiting 5 minutes.",
                domain.handle,
                added,
            )
            logger.info("[%s] Research gate status: %s", domain.handle, refreshed_reason)
            await asyncio.sleep(300)
            continue

        accepted = []
        for item in pending:
            attempted_keywords.add(item.keyword.strip().casefold())
            if _production_discovery_keyword_allowed(item.keyword, domain):
                accepted.append(item)
                if _PRODUCTION_BATCH_TRACKER is not None:
                    _PRODUCTION_BATCH_TRACKER.start_keyword(
                        domain.handle,
                        item.keyword,
                        item.cluster,
                        item.source,
                    )
                continue
            logger.error(
                "[%s] Rejecting non-recipe keyword before generation: %r",
                domain.handle,
                item.keyword,
            )
            mark_keyword_status(domain.keywords_file, roadmap_title, item.keyword, "Failed")
            if _PRODUCTION_BATCH_TRACKER is not None:
                _PRODUCTION_BATCH_TRACKER.reject_keyword(
                    domain.handle,
                    item.keyword,
                    "Rejected by recipe-aware keyword quality gate",
                )

        tasks = [process_keyword(item.keyword, item.cluster, domain, source=item.source) for item in accepted]
        results = await asyncio.gather(*tasks)
        for item, status in zip(accepted, results, strict=False):
            mark_keyword_status(domain.keywords_file, roadmap_title, item.keyword, status)
            if _PRODUCTION_BATCH_TRACKER is not None:
                _PRODUCTION_BATCH_TRACKER.complete_keyword(
                    domain.handle,
                    item.keyword,
                    status,
                )
        if once and not success_target:
            return
        if success_target:
            await asyncio.sleep(2)
        else:
            await asyncio.sleep(30)


async def main() -> None:
    global _PRODUCTION_BATCH_TRACKER

    parser = argparse.ArgumentParser(
        description="RankStein domain-aware parallel article generator",
    )
    parser.add_argument(
        "--domain",
        type=str,
        default=None,
        help="Domain handle (e.g. recetagenial). If omitted, runs all domains",
    )
    parser.add_argument(
        "--all-domains",
        action="store_true",
        help="Run workers for every configured domain simultaneously",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="Max concurrent workers per domain (default: 3)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Keywords to reserve per loop per domain",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one batch per domain then exit",
    )
    parser.add_argument(
        "--success-target-per-domain",
        type=int,
        default=0,
        help="Keep replacing failed/rejected keywords until this many verified Live articles exist per domain",
    )
    parser.add_argument(
        "--batch-id",
        type=str,
        default="",
        help="Stable dashboard batch identifier for a bounded production run",
    )
    args = parser.parse_args()

    reload_registry()
    registry = get_registry()

    if args.all_domains or not args.domain:
        # Launch workers for every domain simultaneously
        domains = list(registry.all())
        logger.info("Turbo mode: all domains — %s", [d.handle for d in domains])
        if args.success_target_per_domain > 0:
            batch_id = args.batch_id or f"production-{int(asyncio.get_event_loop().time())}"
            _PRODUCTION_BATCH_TRACKER = ProductionBatchTracker(
                project_root=PROJECT_ROOT,
                batch_id=batch_id,
                domain_handles=[domain.handle for domain in domains],
                target_per_domain=args.success_target_per_domain,
            )
            for domain in domains:
                clean_keyword_roadmap(
                    domain.keywords_file,
                    f"{domain.display_name} Keyword Roadmap",
                )
        try:
            await asyncio.gather(
                *[
                    _run_domain(
                        domain,
                        args.workers,
                        args.limit,
                        args.once,
                        args.success_target_per_domain,
                    )
                    for domain in domains
                ]
            )
            if _PRODUCTION_BATCH_TRACKER is not None:
                _PRODUCTION_BATCH_TRACKER.finish_if_complete()
        except Exception as exc:
            if _PRODUCTION_BATCH_TRACKER is not None:
                _PRODUCTION_BATCH_TRACKER.fail(str(exc))
            raise
    else:
        domain = registry.get(args.domain)
        logger.info("Turbo mode: domain=%s workers=%d", domain.handle, args.workers)
        if args.success_target_per_domain > 0:
            batch_id = args.batch_id or f"production-{int(asyncio.get_event_loop().time())}"
            _PRODUCTION_BATCH_TRACKER = ProductionBatchTracker(
                project_root=PROJECT_ROOT,
                batch_id=batch_id,
                domain_handles=[domain.handle],
                target_per_domain=args.success_target_per_domain,
            )
            clean_keyword_roadmap(
                domain.keywords_file,
                f"{domain.display_name} Keyword Roadmap",
            )
        try:
            await _run_domain(
                domain,
                args.workers,
                args.limit,
                args.once,
                args.success_target_per_domain,
            )
            if _PRODUCTION_BATCH_TRACKER is not None:
                _PRODUCTION_BATCH_TRACKER.finish_if_complete()
        except Exception as exc:
            if _PRODUCTION_BATCH_TRACKER is not None:
                _PRODUCTION_BATCH_TRACKER.fail(str(exc))
            raise


if __name__ == "__main__":
    asyncio.run(main())

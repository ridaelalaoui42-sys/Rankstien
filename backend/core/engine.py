"""RankStein AI engine adapters.

The production path is Gemini CLI subscription/OAuth, so autonomous agents can
use the same MCP-enabled tool surface an operator gets in the Gemini CLI. The
Google GenAI SDK remains available only when ``RANKSTEIN_AI_ENGINE=google_api``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.core.config import get_settings

try:  # Legacy fallback path only.
    from google import genai
    from google.genai import types
except Exception:  # pragma: no cover - exercised only when optional dep missing
    genai = None  # type: ignore[assignment]
    types = None  # type: ignore[assignment]

logger = logging.getLogger("rankstein.engine")
_retries = 3
_backoff_base = 2


@dataclass(frozen=True)
class AIClient:
    engine: str
    api_key: str = ""
    cli_path: str = ""
    fallback_model: str = ""
    timeout_seconds: int = 300
    yolo: bool = True


def resolve_gemini_cli(override: str = "") -> str | None:
    """Resolve the Gemini CLI executable used by autonomous agents."""
    candidate = override.strip() or os.environ.get("GEMINI_CLI_PATH", "").strip()
    if candidate and Path(candidate).exists():
        return candidate

    for executable in ("gemini", "gemini.cmd", "gemini.exe", "gemini.bat"):
        found = shutil.which(executable)
        if found:
            return found

    appdata = os.environ.get("APPDATA", "")
    if appdata:
        for ext in ("cmd", "exe", "bat"):
            guess = Path(appdata) / "npm" / f"gemini.{ext}"
            if guess.exists():
                return str(guess)
    return None


def get_genai_client(api_key: str | None = None) -> AIClient:
    """Return the configured AI client wrapper.

    Kept under the historical function name so existing agents/routes continue
    to work while the implementation now defaults to Gemini CLI.
    """
    settings = get_settings()
    if settings.ai_engine == "google_api":
        key = api_key if api_key is not None else settings.google_api_key
        if not key:
            raise RuntimeError("GOOGLE_API_KEY is required when RANKSTEIN_AI_ENGINE=google_api")
        return AIClient(engine="google_api", api_key=key)

    cli_path = resolve_gemini_cli(settings.gemini_cli_path)
    return AIClient(
        engine="gemini_cli",
        cli_path=cli_path or "",
        fallback_model=settings.adk_fallback_model,
        timeout_seconds=settings.gemini_cli_timeout_seconds,
        yolo=settings.gemini_cli_yolo,
    )


def generate_text(client: AIClient, model: str, prompt: str, temperature: float = 0.7) -> str:
    """Generate text from the configured engine."""
    if client.engine == "gemini_cli":
        return _generate_text_cli(client, model, prompt)
    return _generate_text_google_api(client, model, prompt, temperature)


def generate_structured(
    client: AIClient, model: str, prompt: str, temperature: float = 0.3
) -> dict[str, Any]:
    """Generate structured JSON output with robust extraction."""
    raw = generate_text(client, model, prompt, temperature)
    return _extract_json(raw)


async def generate_stream(client: AIClient, model: str, prompt: str, temperature: float = 0.7):
    """Stream output when available; Gemini CLI emits one final chunk."""
    if client.engine == "gemini_cli":
        try:
            yield await asyncio.to_thread(generate_text, client, model, prompt, temperature)
        except Exception as e:
            logger.error("Gemini CLI stream failed: %s", e)
            yield f"ERROR: {e}"
        return

    async for chunk in _generate_stream_google_api(client, model, prompt, temperature):
        yield chunk


def _generate_text_cli(client: AIClient, model: str, prompt: str) -> str:
    if not client.cli_path:
        raise RuntimeError("Gemini CLI not found. Install/authenticate Gemini CLI or set GEMINI_CLI_PATH.")

    models = [model]
    if client.fallback_model and client.fallback_model not in models:
        models.append(client.fallback_model)

    last_error = ""
    env = os.environ.copy()
    env.pop("GOOGLE_API_KEY", None)
    env.pop("GEMINI_API_KEY", None)
    for model_name in models:
        cmd = [client.cli_path, "-p", prompt]
        if model_name.lower() != "auto":
            cmd.extend(["--model", model_name])
        if client.yolo:
            cmd.append("--yolo")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=client.timeout_seconds,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            last_error = f"Gemini CLI timed out after {client.timeout_seconds}s on {model_name}: {exc}"
            logger.warning(last_error)
            continue

        if result.returncode == 0:
            return result.stdout.strip()

        last_error = (result.stderr or result.stdout or "").strip()
        logger.warning("Gemini CLI failed for %s: %s", model_name, last_error)

    raise RuntimeError(last_error or "Gemini CLI failed without output")


def _generate_text_google_api(client: AIClient, model: str, prompt: str, temperature: float) -> str:
    if genai is None or types is None:
        raise RuntimeError("google-genai is not installed; use RANKSTEIN_AI_ENGINE=gemini_cli")

    sdk_client = genai.Client(api_key=client.api_key)
    for attempt in range(_retries):
        try:
            response = sdk_client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=temperature),
            )
            return response.text or ""
        except Exception as e:
            wait = _backoff_base**attempt
            logger.warning("GenAI attempt %d failed: %s. Retrying in %ds...", attempt + 1, e, wait)
            if attempt < _retries - 1:
                import time

                time.sleep(wait)
            else:
                logger.error("GenAI failed after %d attempts: %s", _retries, e)
                raise
    return ""


async def _generate_stream_google_api(client: AIClient, model: str, prompt: str, temperature: float):
    if genai is None or types is None:
        yield "ERROR: google-genai is not installed; use RANKSTEIN_AI_ENGINE=gemini_cli"
        return

    sdk_client = genai.Client(api_key=client.api_key)
    for attempt in range(_retries):
        try:
            response = sdk_client.models.generate_content_stream(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=temperature),
            )
            for chunk in response:
                if chunk.text:
                    yield chunk.text
            return
        except Exception as e:
            wait = _backoff_base**attempt
            logger.warning("Stream attempt %d failed: %s. Retrying in %ds...", attempt + 1, e, wait)
            if attempt < _retries - 1:
                await asyncio.sleep(wait)
            else:
                logger.error("Stream failed after %d attempts", _retries)
                yield f"ERROR: {e}"
                return


def _extract_json(raw_text: str) -> dict[str, Any]:
    """Extract JSON from text, handling code fences and markdown."""
    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    depth = 0
    start = -1
    for i, ch in enumerate(raw_text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(raw_text[start : i + 1])
                except json.JSONDecodeError:
                    start = -1
    logger.warning("Could not extract JSON from response (length: %d)", len(raw_text))
    return {}

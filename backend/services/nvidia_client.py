"""NVIDIA Nemotron LLM client integration for RankStein."""

import json
import logging
import os
import re

import openai

logger = logging.getLogger("NVIDIAClient")

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"


def _repair_and_parse_json(raw_text: str) -> dict:
    """Clean markdown, strip surrounding text, and robustly repair JSON payload."""
    clean = raw_text.strip()
    if "```" in clean:
        clean = clean.replace("```json", "").replace("```", "").strip()

    start = clean.find("{")
    end = clean.rfind("}")
    if start != -1 and end != -1 and end > start:
        clean = clean[start : end + 1]

    # Attempt 1: Standard JSON parse
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass

    # Attempt 2: Remove trailing commas before closing braces/brackets
    repaired = re.sub(r",\s*([\]}])", r"\1", clean)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    # Attempt 3: Fix unescaped control characters/newlines inside double quotes
    repaired = re.sub(r"(?<!\\)\n", r"\\n", repaired)
    return json.loads(repaired)


def generate_article_with_nvidia_nemotron(
    prompt: str, api_key: str | None = None, timeout: int = 300
) -> dict | None:
    """Generate article JSON using NVIDIA's Nemotron 3.5 Lightning endpoint."""
    key = (
        api_key
        or os.environ.get("NVIDIA_API_KEY")
        or "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"
    )
    if not key:
        logger.warning("No NVIDIA_API_KEY available")
        return None

    client = openai.OpenAI(base_url=NVIDIA_BASE_URL, api_key=key, timeout=timeout)

    try:
        logger.info(
            "Invoking NVIDIA Nemotron model=%s via OpenAI client (timeout=%ds)", NVIDIA_MODEL, timeout
        )
        completion = client.chat.completions.create(
            model=NVIDIA_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are RankStein's professional recipe article generator. Return ONLY a valid JSON object matching the requested schema. Do not include markdown fences, reasoning text, or preamble outside the JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            max_tokens=8192,
            extra_body={"chat_template_kwargs": {"enable_thinking": True}, "reasoning_budget": 2048},
        )

        content = completion.choices[0].message.content
        if not content:
            logger.warning("NVIDIA Nemotron returned empty content")
            return None

        article = _repair_and_parse_json(content)
        logger.info("NVIDIA Nemotron successfully generated article JSON (title=%r)", article.get("title"))
        return article
    except Exception as exc:
        logger.warning("NVIDIA Nemotron article generation failed: %s", exc)
        return None

"""RankStein Agents — Base Agent Class"""

from __future__ import annotations

import logging
import time

from backend.agents.production_contract import PRODUCTION_CONTRACT
from backend.core.config import get_settings
from backend.core.engine import generate_stream, generate_structured, get_genai_client

logger = logging.getLogger("rankstein.agent")


class RankSteinAgent:
    """Base class for all RankStein agents.

    By default these agents use the Gemini CLI subscription engine so they can
    run with the same MCP tools available to the operator. Set
    ``RANKSTEIN_AI_ENGINE=google_api`` only for legacy SDK-backed operation.
    """

    def __init__(
        self,
        name: str,
        description: str,
        model: str | None = None,
        instructions: str = "",
        tools: list | None = None,
    ):
        self.name = name
        self.description = description
        self.model = model or get_settings().adk_model
        self.instructions = instructions
        self.tools = tools or []
        self._client = get_genai_client()

    def _build_prompt(self, context: dict | None = None) -> str:
        """Build enriched prompt with context injection."""
        prompt = PRODUCTION_CONTRACT + "\n\n" + self.instructions
        if context:
            prompt += "\n\n--- CONTEXT ---\n"
            for key, value in context.items():
                prompt += f"{key}: {value}\n"
        return prompt

    async def run(self, prompt: str, context: dict | None = None) -> dict:
        """Execute agent with structured output."""
        full_prompt = self._build_prompt(context) + "\n" + prompt
        start = time.time()
        try:
            result = generate_structured(self._client, self.model, full_prompt, temperature=0.3)
            latency_ms = int((time.time() - start) * 1000)
            tokens_est = len(full_prompt.split()) + len(str(result).split())
            return {"output": result, "tokens_used": tokens_est, "latency_ms": latency_ms}
        except Exception as e:
            logger.error("Agent %s run failed: %s", self.name, e)
            return {
                "output": {"error": str(e)},
                "tokens_used": 0,
                "latency_ms": int((time.time() - start) * 1000),
            }

    async def stream(self, prompt: str, context: dict | None = None):
        """Stream agent output token by token."""
        full_prompt = self._build_prompt(context) + "\n" + prompt
        try:
            async for chunk in generate_stream(self._client, self.model, full_prompt):
                yield chunk
        except Exception as e:
            logger.error("Agent %s stream failed: %s", self.name, e)
            yield f"ERROR: {e}"

    def get_info(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "model": self.model,
            "tools": len(self.tools),
        }

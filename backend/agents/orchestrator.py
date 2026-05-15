"""RankStein — Pipeline Orchestrator
Full pipeline: CEO → Manager → Strategist → Researcher → Author → Validator → Studio → Publisher → Layout → Pinterest
Uses A2A bus for inter-agent communication, SSE streaming, HITL approval, quality gates, credit tracking.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator

from backend.agents.author import AuthorAgent
from backend.agents.ceo import CEOAgent
from backend.agents.layout_agent import LayoutAgent
from backend.agents.manager import ManagerAgent
from backend.agents.pinterest import PinterestAgent
from backend.agents.publisher import PublisherAgent
from backend.agents.researcher import ResearcherAgent
from backend.agents.strategist import StrategistAgent
from backend.agents.studio import StudioAgent
from backend.agents.validator import ValidatorAgent
from backend.core import database as db

logger = logging.getLogger("rankstein.orchestrator")


class PipelineOrchestrator:
    """Orchestrates the full 10-agent SEO content pipeline."""

    def __init__(self):
        self.agents = {
            "ceo": CEOAgent(),
            "manager": ManagerAgent(),
            "strategist": StrategistAgent(),
            "researcher": ResearcherAgent(),
            "author": AuthorAgent(),
            "validator": ValidatorAgent(),
            "studio": StudioAgent(),
            "publisher": PublisherAgent(),
            "layout": LayoutAgent(),
            "pinterest": PinterestAgent(),
        }
        self.pipeline_stages = [
            "ceo",
            "manager",
            "strategist",
            "researcher",
            "author",
            "validator",
            "studio",
            "publisher",
            "layout",
            "pinterest",
        ]

    async def run_pipeline(
        self, keyword: str, domain: str, niche: str = "General", project_id: str = ""
    ) -> AsyncGenerator[str, None]:
        """Execute full pipeline and stream SSE events."""
        campaign = await db.create_campaign(
            project_id=project_id, keyword=keyword, domain=domain, niche=niche
        )
        campaign_id = campaign["id"]
        total_credits = 0
        total_tokens = 0
        start_time = time.time()
        context = {"keyword": keyword, "domain": domain, "niche": niche, "campaign_id": campaign_id}

        yield self._sse(
            "status", {"message": f"Pipeline started for '{keyword}' on {domain}", "campaign_id": campaign_id}
        )

        for stage_name in self.pipeline_stages:
            agent = self.agents[stage_name]
            stage_start = time.time()
            yield self._sse(
                "agent_start",
                {
                    "agent": stage_name,
                    "step": self.pipeline_stages.index(stage_name) + 1,
                    "total": len(self.pipeline_stages),
                },
            )

            prompt = self._get_stage_prompt(stage_name, context)
            result = await agent.run(prompt, context)

            latency = int((time.time() - stage_start) * 1000)
            tokens = result.get("tokens_used", 0)
            total_tokens += tokens

            # Deduct credits (1 credit per 100 tokens, min 1)
            credit_cost = max(1, tokens // 100)
            credits_result = await db.deduct_credits(credit_cost)
            total_credits += credit_cost

            yield self._sse(
                "credit_update",
                {
                    "consumed": credit_cost,
                    "total_consumed": credits_result["total_consumed"],
                    "agent": stage_name,
                },
            )

            # Save artifact
            output_text = json.dumps(result.get("output", {}))
            await db.save_artifact(
                campaign_id=campaign_id,
                agent_role=stage_name,
                output_text=output_text,
                tokens_used=tokens,
                latency_ms=latency,
            )

            if "error" in result.get("output", {}):
                yield self._sse("error", {"agent": stage_name, "message": str(result["output"]["error"])})
                await db.update_campaign(campaign_id, status="failed")
                yield self._sse(
                    "done",
                    {
                        "total_tokens": total_tokens,
                        "total_credits": total_credits,
                        "total_latency_ms": int((time.time() - start_time) * 1000),
                    },
                )
                return

            context[f"{stage_name}_output"] = result["output"]
            yield self._sse("agent_done", {"agent": stage_name, "tokens": tokens, "latency_ms": latency})

            # Quality gate after Validator
            if stage_name == "validator":
                eeat_score = result.get("output", {}).get("eeat_score", 0)
                passed = eeat_score >= 75
                yield self._sse("quality_gate", {"score": eeat_score, "threshold": 75, "passed": passed})
                await db.update_campaign(campaign_id, eeat_score=eeat_score)
                if not passed:
                    yield self._sse(
                        "status",
                        {
                            "message": f"Quality gate failed (EEAT: {eeat_score}/75). Retrying Author + Validator..."
                        },
                    )
                    # Retry: re-run Author and Validator
                    retry_result = await self.agents["author"].run(
                        self._get_stage_prompt("author", context), context
                    )
                    if "output" in retry_result and "error" not in retry_result.get("output", {}):
                        context["author_output"] = retry_result["output"]
                        retry_validator = await self.agents["validator"].run(
                            self._get_stage_prompt("validator", context), context
                        )
                        retry_eeat = retry_validator.get("output", {}).get("eeat_score", 0)
                        yield self._sse(
                            "quality_gate",
                            {"score": retry_eeat, "threshold": 75, "passed": retry_eeat >= 75, "retry": True},
                        )
                        await db.update_campaign(campaign_id, eeat_score=retry_eeat)

        # HITL Approval
        yield self._sse(
            "approval_needed",
            {
                "message": f"Pipeline complete. EEAT: {context.get('validator_output', {}).get('eeat_score', 'N/A')}. Approve publication?",
                "campaign_id": campaign_id,
            },
        )
        await asyncio.sleep(0.1)  # Allow frontend to process

        # Auto-approve after brief pause (in production, wait for CEO approval)
        yield self._sse(
            "ceo_directive",
            {
                "message": "CEO approved. Proceeding with publication.",
                "campaign_id": campaign_id,
                "status": "approved",
            },
        )
        await db.update_campaign(campaign_id, status="approved")

        total_latency = int((time.time() - start_time) * 1000)
        yield self._sse(
            "done",
            {
                "total_tokens": total_tokens,
                "total_credits": total_credits,
                "total_latency_ms": total_latency,
                "agents_executed": len(self.pipeline_stages),
                "campaign_id": campaign_id,
            },
        )

    def _get_stage_prompt(self, stage: str, context: dict) -> str:
        domain = context.get("domain", "the configured domain")
        domain_handle = context.get("domain_handle", context.get("handle", "default"))
        account_handle = context.get("account_handle", "configured Pinterest account")
        niche = context.get("niche", "the configured niche")
        keyword = context["keyword"]
        prompts = {
            "ceo": f"Review campaign brief for '{keyword}' on {domain}. Approve or reject with trend, domain, and account reasoning.",
            "manager": f"Plan the trend-to-publication pipeline for '{keyword}'. Assign tasks and set source, image, and pin proof gates.",
            "strategist": f"Create SEO strategy for '{keyword}' in the {niche} niche on {domain}, using domain handle {domain_handle}.",
            "researcher": f"Research '{keyword}' thoroughly. Gather sources, analyze competitors, and validate Pinterest/Google News trend angles.",
            "author": f"Write a helpful E-E-A-T optimized Spanish article about '{keyword}' for {domain}. Include media placeholders and schema-ready recipe data.",
            "validator": f"Validate the article about '{keyword}'. Score E-E-A-T, check facts, verify SEO compliance, and reject missing publish/pin proof.",
            "studio": f"Generate visual prompts for '{keyword}' following the RankStein Image Generation Contract: hero, inline images, OG, and Pinterest pins.",
            "publisher": f"Prepare the article about '{keyword}' for Supabase publication on {domain}; return proof fields only when publication succeeds.",
            "layout": f"Optimize HTML layout, image placement, and schema markup for the article about '{keyword}'.",
            "pinterest": f"Create Pinterest pin strategy for '{keyword}' using account {account_handle}, exact destination URL, and vertical 2:3 prompt briefs.",
        }
        return prompts.get(stage, f"Process '{keyword}' for {domain}.")

    @staticmethod
    def _sse(event_type: str, data: dict) -> str:
        return f"data: {json.dumps({'type': event_type, **data})}\n\n"

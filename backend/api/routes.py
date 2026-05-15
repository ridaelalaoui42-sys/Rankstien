"""RankStein — API Routes
All FastAPI endpoints with authentication, rate limiting, and SSE streaming.
"""

from __future__ import annotations

import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.agents.orchestrator import PipelineOrchestrator
from backend.core import database as db
from backend.core.config import get_settings
from backend.core.engine import generate_structured, get_genai_client
from backend.core.security import get_api_key
from backend.services.competitor_analyzer import (
    analyze_competitors,
    find_content_opportunities,
)
from backend.services.keyword_mapper import (
    build_topic_clusters,
    find_cannibalization_issues,
    map_keywords_to_pages,
)
from backend.services.scraper import estimate_keyword_metrics, scrape_onpage
from backend.services.seo_tools import (
    calculate_content_score,
    calculate_keyword_density,
    calculate_readability_score,
)
from backend.services.site_auditor import (
    offpage_audit,
    onpage_audit,
    technical_audit,
)

logger = logging.getLogger("rankstein.api")
router = APIRouter()
orchestrator = PipelineOrchestrator()


# ── Request Models ─────────────────────────────────────
class PipelineRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=200)
    domain: str = Field(..., min_length=1, max_length=100)
    niche: str = Field(default="General", max_length=100)
    project_id: str = Field(default="")


class DomainCreate(BaseModel):
    name: str = Field(..., min_length=1)
    url: str = Field(..., min_length=1)
    niche: str = Field(default="General")
    schedule: str = Field(default="")


class ProjectCreate(BaseModel):
    domain_id: str = Field(...)
    name: str = Field(..., min_length=1)
    mode: str = Field(default="supervised")


class IntegrationCreate(BaseModel):
    domain_id: str = Field(...)
    type: str = Field(...)
    credentials: dict = Field(default_factory=dict)


class AnalyzeRequest(BaseModel):
    domain: str = Field(...)
    niche: str = Field(default="General")


class KeywordResearchRequest(BaseModel):
    seed_keyword: str = Field(...)
    domain: str = Field(default="")
    depth: str = Field(default="standard")


class OnPageAuditRequest(BaseModel):
    url: str = Field(...)
    domain: str = Field(default="")


class ContentOptimizeRequest(BaseModel):
    content: str = Field(...)
    keyword: str = Field(...)
    niche: str = Field(default="General")


# ── Helper ─────────────────────────────────────────────
def _sse(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


# ── Health ─────────────────────────────────────────────
@router.get("/health")
async def health():
    return {"status": "healthy", "service": "RankStein API", "version": "2.0.0", "agents": 10}


# ── Domains ────────────────────────────────────────────
@router.get("/domains", dependencies=[Depends(get_api_key)])
async def list_domains(status: str | None = None):
    return await db.list_domains(status)


@router.post("/domains", dependencies=[Depends(get_api_key)])
async def create_domain(body: DomainCreate):
    existing = await db.get_domain_by_name(body.name)
    if existing:
        raise HTTPException(409, f"Domain '{body.name}' already exists")
    return await db.create_domain(body.name, body.url, body.niche, body.schedule)


@router.get("/domains/{domain_id}", dependencies=[Depends(get_api_key)])
async def get_domain(domain_id: str):
    d = await db.get_domain(domain_id)
    if not d:
        raise HTTPException(404, "Domain not found")
    return d


@router.patch("/domains/{domain_id}", dependencies=[Depends(get_api_key)])
async def update_domain(domain_id: str, body: dict):
    await db.update_domain(domain_id, **body)
    return {"status": "updated", "id": domain_id}


@router.delete("/domains/{domain_id}", dependencies=[Depends(get_api_key)])
async def delete_domain(domain_id: str):
    await db.delete_domain(domain_id)
    return {"status": "archived", "id": domain_id}


@router.post("/domains/{domain_id}/activate", dependencies=[Depends(get_api_key)])
async def activate_domain(domain_id: str):
    await db.update_domain(domain_id, status="active")
    return {"status": "activated"}


@router.post("/domains/{domain_id}/pause", dependencies=[Depends(get_api_key)])
async def pause_domain(domain_id: str):
    await db.update_domain(domain_id, status="paused")
    return {"status": "paused"}


@router.get("/domains/{domain_id}/agents", dependencies=[Depends(get_api_key)])
async def domain_agents(domain_id: str):
    domain = await db.get_domain(domain_id)
    if not domain:
        raise HTTPException(404, "Domain not found")
    return {"domain_id": domain_id, "agents": orchestrator.agents.keys(), "count": len(orchestrator.agents)}


# ── Projects ───────────────────────────────────────────
@router.get("/projects", dependencies=[Depends(get_api_key)])
async def list_projects(domain_id: str | None = None):
    return await db.list_projects(domain_id)


@router.post("/projects", dependencies=[Depends(get_api_key)])
async def create_project(body: ProjectCreate):
    return await db.create_project(body.domain_id, body.name, body.mode)


@router.get("/projects/{project_id}", dependencies=[Depends(get_api_key)])
async def get_project(project_id: str):
    p = await db.get_project(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    return p


@router.patch("/projects/{project_id}", dependencies=[Depends(get_api_key)])
async def update_project(project_id: str, body: dict):
    await db.update_project(project_id, **body)
    return {"status": "updated", "id": project_id}


@router.get("/projects/{project_id}/performance", dependencies=[Depends(get_api_key)])
async def project_performance(project_id: str):
    p = await db.get_project(project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    campaigns = await db.get_campaigns_for_project(project_id)
    total_words = sum(c.get("word_count", 0) or 0 for c in campaigns)
    avg_eeat = sum(c.get("eeat_score", 0) or 0 for c in campaigns) / max(len(campaigns), 1)
    return {
        "project": p,
        "total_campaigns": len(campaigns),
        "completed": sum(1 for c in campaigns if c["status"] == "complete"),
        "total_words": total_words,
        "avg_eeat": round(avg_eeat, 1),
        "campaigns": campaigns[:10],
    }


@router.get("/projects/{project_id}/campaigns", dependencies=[Depends(get_api_key)])
async def project_campaigns(project_id: str):
    return await db.get_campaigns_for_project(project_id)


# ── Campaigns ──────────────────────────────────────────
@router.get("/campaigns", dependencies=[Depends(get_api_key)])
async def list_campaigns(status: str | None = None, limit: int = 50):
    return await db.list_campaigns(status, limit)


@router.post("/campaigns", dependencies=[Depends(get_api_key)])
async def create_campaign(body: PipelineRequest):
    return await db.create_campaign(body.project_id, body.keyword, body.domain, body.niche)


@router.get("/campaigns/{campaign_id}", dependencies=[Depends(get_api_key)])
async def get_campaign(campaign_id: str):
    c = await db.get_campaign(campaign_id)
    if not c:
        raise HTTPException(404, "Campaign not found")
    return c


@router.get("/campaigns/{campaign_id}/artifacts", dependencies=[Depends(get_api_key)])
async def campaign_artifacts(campaign_id: str):
    return await db.get_artifacts(campaign_id)


@router.get("/campaigns/{campaign_id}/pins", dependencies=[Depends(get_api_key)])
async def campaign_pins(campaign_id: str):
    return await db.get_pins(campaign_id)


@router.post("/campaigns/{campaign_id}/approve", dependencies=[Depends(get_api_key)])
async def approve_campaign(campaign_id: str):
    await db.update_campaign(campaign_id, status="approved")
    return {"status": "approved", "id": campaign_id}


@router.post("/campaigns/{campaign_id}/reject", dependencies=[Depends(get_api_key)])
async def reject_campaign(campaign_id: str, body: dict | None = None):
    await db.update_campaign(campaign_id, status="rejected")
    return {"status": "rejected", "id": campaign_id, "reason": body.get("reason", "") if body else ""}


# ── Integrations ───────────────────────────────────────
@router.get("/integrations", dependencies=[Depends(get_api_key)])
async def list_integrations(domain_id: str | None = None):
    return await db.list_integrations(domain_id)


@router.post("/integrations", dependencies=[Depends(get_api_key)])
async def create_integration(body: IntegrationCreate):
    return await db.save_integration(body.domain_id, body.type, body.credentials)


@router.patch("/integrations/{integration_id}", dependencies=[Depends(get_api_key)])
async def update_integration(integration_id: str, body: dict):
    await db.update_integration(integration_id, **body)
    return {"status": "updated", "id": integration_id}


@router.delete("/integrations/{integration_id}", dependencies=[Depends(get_api_key)])
async def delete_integration(integration_id: str):
    await db.delete_integration(integration_id)
    return {"status": "deleted", "id": integration_id}


@router.post("/integrations/test", dependencies=[Depends(get_api_key)])
async def test_integration(body: dict):
    itype = body.get("type", "")
    url = body.get("url", "")
    username = body.get("username", "")
    password = body.get("password", "")
    if itype == "wordpress" and url and username and password:
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                resp = await http.get(
                    f"{url.rstrip('/')}/wp-json/wp/v2/posts?per_page=1", auth=(username, password)
                )
            return {
                "status": "success" if resp.status_code == 200 else "failed",
                "message": f"HTTP {resp.status_code}",
            }
        except Exception as e:
            return {"status": "failed", "message": str(e)}
    return {"status": "pending", "message": "Test not available for this integration type"}


# ── Pipeline (SSE) ─────────────────────────────────────
@router.post("/orchestrate", dependencies=[Depends(get_api_key)])
async def orchestrate_pipeline(body: PipelineRequest):
    return StreamingResponse(
        orchestrator.run_pipeline(body.keyword, body.domain, body.niche, body.project_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ── SEO Tools ──────────────────────────────────────────
@router.post("/seo/analyze", dependencies=[Depends(get_api_key)])
async def seo_analyze(body: AnalyzeRequest):
    client = get_genai_client()
    prompt = f"""Analyze {body.domain} for SEO opportunities in the {body.niche} niche.
Return JSON: {{"keywords": [{{"keyword": "...", "volume": 1000, "difficulty": 45, "intent": "informational"}}],
"competitors": [{{"domain": "...", "strength": "...", "gap": "..."}}],
"audit": {{"score": 72, "strengths": ["..."], "weaknesses": ["..."], "opportunities": ["..."]}},
"recommended_topics": [{{"title": "...", "keyword": "...", "priority": "high"}}]}}"""
    data = generate_structured(client, get_settings().adk_model, prompt, 0.3)
    data.setdefault("keywords", [])
    data.setdefault("competitors", [])
    data.setdefault("audit", {"score": 0, "strengths": [], "weaknesses": [], "opportunities": []})
    data.setdefault("recommended_topics", [])
    return data


@router.post("/seo/audit", dependencies=[Depends(get_api_key)])
async def seo_audit(body: AnalyzeRequest):
    tech = await technical_audit(body.domain)
    offpage = await offpage_audit(body.domain)
    return {"technical": tech, "offpage": offpage, "domain": body.domain}


@router.post("/seo/keywords", dependencies=[Depends(get_api_key)])
async def keyword_research(body: KeywordResearchRequest):
    data = await estimate_keyword_metrics(body.seed_keyword, body.niche)
    return data


@router.post("/seo/competitors", dependencies=[Depends(get_api_key)])
async def competitor_analysis(body: AnalyzeRequest):
    competitors = await analyze_competitors(body.domain, body.niche)
    opportunities = await find_content_opportunities(body.domain, body.niche, competitors)
    return {"competitors": competitors, "opportunities": opportunities}


@router.post("/seo/keyword-map", dependencies=[Depends(get_api_key)])
async def keyword_mapping(body: dict):
    domain = body.get("domain", "")
    keywords = body.get("keywords", [])
    mappings = await map_keywords_to_pages(domain, keywords)
    clusters = await build_topic_clusters(keywords)
    cannibalization = await find_cannibalization_issues(domain, keywords)
    return {"mappings": mappings, "clusters": clusters, "cannibalization": cannibalization}


@router.post("/seo/onpage", dependencies=[Depends(get_api_key)])
async def onpage(body: OnPageAuditRequest):
    page_data = await scrape_onpage(body.url)
    if not page_data.get("success"):
        return {"error": page_data.get("error"), "url": body.url}
    audit = await onpage_audit(body.url)
    return {"page_data": page_data, "audit": audit}


@router.post("/seo/content-optimize", dependencies=[Depends(get_api_key)])
async def content_optimize(body: ContentOptimizeRequest):
    density = calculate_keyword_density(body.content, body.keyword)
    readability = calculate_readability_score(body.content)
    score = calculate_content_score(body.content, body.keyword, body.niche)
    return {
        "keyword_density": density,
        "readability": readability,
        "content_score": score,
        "recommendations": [
            "Increase keyword density"
            if density < 0.5
            else "Reduce keyword density"
            if density > 2.5
            else "Keyword density is optimal",
            "Improve readability" if readability < 50 else "Readability is good",
        ],
    }


@router.post("/seo/backlinks", dependencies=[Depends(get_api_key)])
async def backlink_analysis(body: AnalyzeRequest):
    offpage = await offpage_audit(body.domain)
    return offpage


# ── Analytics ──────────────────────────────────────────
@router.get("/analytics/overview", dependencies=[Depends(get_api_key)])
async def analytics_overview():
    campaigns = await db.list_campaigns()
    domains = await db.list_domains()
    credits = await db.get_credits()
    total_words = sum(c.get("word_count", 0) or 0 for c in campaigns)
    avg_eeat = sum(c.get("eeat_score", 0) or 0 for c in campaigns) / max(len(campaigns), 1)
    return {
        "total_campaigns": len(campaigns),
        "total_domains": len(domains),
        "total_words": total_words,
        "avg_eeat": round(avg_eeat, 1),
        "credits_remaining": credits.get("balance", 0),
        "credit_tier": credits.get("tier", "free"),
    }


@router.get("/analytics/campaigns", dependencies=[Depends(get_api_key)])
async def analytics_campaigns():
    campaigns = await db.list_campaigns()
    return campaigns


@router.get("/analytics/keywords", dependencies=[Depends(get_api_key)])
async def analytics_keywords():
    return {"message": "Keyword analytics — integrate with Google Search Console for live data"}


# ── Credits ────────────────────────────────────────────
@router.get("/credits", dependencies=[Depends(get_api_key)])
async def get_credits():
    return await db.get_credits()

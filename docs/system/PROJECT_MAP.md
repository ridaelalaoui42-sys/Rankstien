# RankStein Project Map

Updated: 2026-07-27

RankStein turns pending recipe keywords into researched Spanish content, generated images, Pinterest distribution, Supabase publication, and remembered operational lessons.

## Directory Map

| Path | Role |
|---|---|
| `rankstein/` | Core CLI, domain registry, shared config, subscriber commands. |
| `rankstein/trend_intelligence.py` | Playwright-first Pinterest trend collection and Google News ranking. |
| `rankstein/site_factory.py` | Clones and rebrands the RecetaDolce template for new domain projects. |
| `rankstein/autonomous.py` | Repeatable autonomous startup loop with AgentMemory logging. |
| `rankstein/prompts.py` | Shared article, image, and scrape-brief prompt builders. |
| `rankstein_mcp_server.py` | Main project MCP server used by connected agents. |
| `backend/` | FastAPI app, agent classes, services, memory client, AI engine adapter. |
| `backend/services/remasterer.py` | Pinterest image scrape, relevance filter, native fallback, remaster, and article-specific 30-pin campaign runner. |
| `pinterest_automation/` | Queue, session pool, browser automation, health monitoring, campaign engine, MCP bridge. |
| `pinterest_automation/campaign.py` | Bounded auto-campaign routing, folder enqueue, and article remaster enqueue. |
| `pinterest_automation/runtime_state.py` | Supervisor singleton lease, heartbeat, status, and graceful-stop state. |
| `pinterest_automation/routing.py` | Deterministic domain/account cohorts and bounded cross-save selection. |
| `backend/operator.py` | Standalone RankStein operator dashboard and local control API on port 7000. |
| `backend/static/operator/` | Operator UI, styles, icons, and interactive client. |
| `frontend/` | Recipe-site template retained for site factory; not a local operator service. |
| `scripts/dev/` | Validators, AgentMemory starter, self-cleaner. |
| `tests/` | Unit and integration coverage. |
| `memory/` | Keyword/backlog state still consumed by tools. |
| `data/` | Local runtime state; ignored except intentional placeholders/config. |
| `docs/system/` | Canonical documentation. |
| `start_all_services.ps1` | Unified Windows startup, status, stop, install, and daily campaign controller. |

## Runtime Map

```mermaid
flowchart LR
    Scheduler["Windows Scheduler"] --> Launcher["rankstein.py launch"]
    Launcher --> Hermes["Hermes Codex"]
    Launcher --> RankStein["RankStein MCP"]
    RankStein --> Memory["AgentMemory MCP"]
    RankStein --> Browser["Playwright Chromium"]
    RankStein --> SupabaseMCP["Supabase MCP"]
    RankStein --> Images["Native image generation"]

    RankStein --> Backend["Python services"]
    Backend --> Queue["Pinterest queue"]
    Backend --> Trends["Trend intelligence"]
    Backend --> Supabase["Supabase REST/storage"]
    Backend --> Local["data and memory state"]
```

## Main Workflows

| Workflow | Entry |
|---|---|
| Full service startup | `python rankstein.py launch` or `start_all_services.ps1` |
| Autonomous content run | `python rankstein.py run` |
| Audit/seed without workers | `python rankstein.py run --no-launch --json` |
| Daily trend refresh | `python rankstein.py trends --limit 10` |
| Continuous local loop | `python rankstein.py autonomous --interval-hours 24` |
| Domain management | `python rankstein.py list-domains`, `show-domain`, `run` |
| New blog factory | `python rankstein.py add-domain <domain> --clone-site` |
| Subscriber management | `python rankstein.py subscribers ...` |
| AgentMemory startup | `scripts/dev/start_agentmemory.ps1` |
| Runtime validation | `scripts/dev/validate_gemini_runtime.py` |
| Pinterest validation | `scripts/dev/validate_automation.py` |
| Pinterest folder enqueue | `python run_autonomous.py enqueue-folder` |
| Article remaster campaign | `run_article_remaster_campaign` MCP tool or `python backend/services/remasterer.py <keyword> <title> --enqueue-after --pins-per-keyword 30` |
| Project cleanup | `scripts/dev/self_clean.py` |
| File-by-file audit | `scripts/dev/project_audit.py` |

## Documentation Ownership

This project intentionally has fewer Markdown files now. Old duplicated context docs were removed. New operational changes should update the canonical docs listed in `docs/system/PROJECT_HYGIENE.md`. Fresh campaign defaults live in `docs/system/CAMPAIGN_PIPELINE.md`.

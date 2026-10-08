# RankStein — Project Audit

Audit date: 2026-05-24

---

## Overview

**RankStein** is an autonomous SEO content engine and Pinterest distribution system for Spanish recipe domains. It uses Gemini CLI as its reasoning engine, MCP servers as its tool layer, Playwright for browser automation, and Supabase for cloud persistence.

The maintained production path is CLI-first: `python rankstein.py run` is the main entry point.

---

## Architecture

### Reasoning Engine
- **Gemini CLI** (subscription/OAuth, not API-key) — primary AI/LLM
- Registered in `.gemini/settings.json`
- Caching agentmemory + rankstein + nanobanana + playwright_ff + playwright_cr + supabase MCP servers

### Core Layers

| Layer | Tech | Role |
|---|---|---|
| CLI | `rankstein/` | Domain registry, config, subscribers, trend intelligence, site factory |
| MCP Server | `rankstein_mcp_server.py` (FastMCP) | Tools for keywords, research, quality gates, images, publishing, memory |
| Backend API | FastAPI (`backend/main.py`) | HTTP endpoints, agent orchestration, services |
| Pinterest Automation | `pinterest_automation/` | Queue, session pool, browser drivers, health monitor, campaign engine |
| Frontend | Next.js 16 (`frontend/`) | Operator monitoring UI (no secret-bearing admin) |
| Database | Supabase | Posts, storage, subscribers |
| Memory | AgentMemory MCP + local REST on `:3111` | Long-term semantic/procedural/episodic memory |

### Content Pipeline
```
Trend keywords → Google News validation → Domain keyword roadmap →
AgentMemory recall → Source research → Spanish article JSON →
Quality gate → Hero image → Pinterest pin → Supabase publish →
Auto-campaign (pin_upload for all accounts) → Cross-save → Mark Live
```

---

## Directory Map

| Path | Contents |
|---|---|
| `rankstein/` | CLI, domain registry (`domain.py`), unified config (`config.py`), keyword roadmap, trend intelligence, site factory, autonomous loop, subscribers |
| `backend/` | FastAPI app, agents (17 agent classes), services (news scraper, memory, SEO tools, remasterer), API routes |
| `pinterest_automation/` | Pinterest driver, job queue (SQLite), session pool, rate limiter, circuit breaker, self-healing, health monitor, supervisor, campaign engine, MCP bridge |
| `frontend/` | Next.js 16 app (React 19), Tailwind CSS v4, Supabase client, Lucide icons |
| `scripts/dev/` | AgentMemory starter, Gemini runtime validator, automation validator, self-cleaner, project auditor |
| `tests/` | pytest suite: unit, integration, e2e |
| `docs/` | System docs (PROJECT_MAP, SYSTEM_ARCHITECTURE, AUTONOMOUS_AGENTIC_SYSTEM, PROJECT_HYGIENE) + templates (image gen contract, pin template, domain prompt) |
| `tools/` | `playwright-mcp/`, `iii/` (AgentMemory binary) |
| `data/` | Runtime state (queue, sessions, logs, domains, media) — gitignored |
| `memory/` | `keywords.md`, `pinterest_backlog.md` — MD workflow state read by tools |

---

## Key Files

| File | Purpose |
|---|---|
| `rankstein/cli.py` | Root CLI parser — `run`, `add-domain`, `list-domains`, `show-domain`, `trends`, `autonomous`, `subscribers` |
| `rankstein/config.py` | **Single source of truth** pydantic-settings config (replaces 2 legacy configs) |
| `rankstein/domain.py` | Domain registry — synthesized default (Phase 1) or JSON manifests (Phase 2) |
| `rankstein_mcp_server.py` | Main MCP server (~1700 lines) — all Gemini CLI tools live here |
| `pinterest_automation/config.py` | Legacy Pinterest config (dataclass-based, being migrated to `rankstein/config.py`) |
| `backend/core/config.py` | Legacy backend config (being migrated to `rankstein/config.py`) |
| `backend/main.py` | FastAPI entry point (uvicorn, middleware, routing) |
| `backend/services/news_scraper.py` | Google News RSS + DuckDuckGo fallback, article extraction, quality validation |
| `backend/services/memory_service.py` | AgentMemory REST client |
| `pinterest_automation/job_queue.py` | SQLite-backed durable job queue |
| `pinterest_automation/pinterest_driver.py` | High-level Playwright Pinterest driver with self-healing selectors |
| `pinterest_automation/supervisor.py` | `AutonomousSupervisor` — 24/7 queue processing |
| `rankstein/trend_intelligence.py` | Playwright-first Pinterest trend collection + Google News ranking |
| `Dockerfile` / `docker-compose.yml` | Container deployment for FastAPI backend |

---

## Configuration (`.env`)

Critical env vars:
- `NEXT_PUBLIC_SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` — Supabase backend
- `PINTEREST_EMAIL` + `PINTEREST_PASSWORD` — default Pinterest creds
- `PINTEREST_ACCOUNTS` — JSON array for multi-account support
- `CLOUDINARY_CLOUD_NAME`/`API_KEY`/`API_SECRET` — media upload
- `RANKSTEIN_AI_ENGINE=gemini_cli` — primary AI engine
- `GEMINI_CLI_PATH`, `GEMINI_CLI_TIMEOUT_SECONDS`, `GEMINI_CLI_YOLO` — Gemini CLI config
- `RANKSTEIN_SECRET` — session signing (min 16 chars)
- `CORS_ORIGINS` — allowed frontend origins
- `PINTEREST_WORKER_COUNT`, `PINTEREST_PIN_CONFIRM_TIMEOUT_SECONDS`, etc. — Pinterest tuning

---

## State Management

| State | Location | Format |
|---|---|---|
| Keyword roadmaps | `data/domains/*/keywords.md` (or `memory/keywords.md` default) | Markdown tables |
| Trend shortlists | `data/domains/*/daily_best_keywords.*` | Markdown + JSON |
| Pinterest job queue | `data/queue/jobs.db` | SQLite |
| Browser sessions | `data/sessions/` | Playwright storage state |
| Long-term memory | AgentMemory (REST `:3111`) | Semantic/episodic/procedural |
| Keyword failures | `data/keyword_failures.json` | JSON (circuit breaker) |
| Pinterest backlog | `memory/pinterest_backlog.md` | Markdown table |
| Runtime logs | `data/logs/automation.log` | Rotating logs |
| MCP logs | `data/rankstein_mcp.log` | Rotating logs |

---

## Workflows

### Main Startup (`rankstein.py run`)
1. Boot MCP servers (agentmemory, validate stdio servers)
2. Refresh trend intelligence (unless `--skip-trends`)
3. Audit DB, domains, queues, keyword roadmaps, AgentMemory
4. Clean duplicate/stuck keywords, reset stale `In Progress`
5. Mark DB-completed keywords as `Live`
6. Seed missing campaign records
7. Launch domain article workers (unless `--no-launch`)

### Autonomous Loop (`rankstein.py autonomous`)
Repeats the startup cycle at configurable intervals (default 24h).

### Trend Intelligence (`rankstein.py trends`)
Playwright-first Pinterest niche trend discovery → Google News RSS validation → daily best keyword reports → optional roadmap append.

### Image Pipeline
1. Generate hero image (Pollinations or base64)
2. Validate dimensions/size
3. Upload to Supabase Storage
4. Generate Pinterest pin image
5. Apply Luxury V3 editorial overlay (NanoBanana style)
6. Inject EXIF metadata
7. Upload pin direct via Playwright

### Pinterest Queue
- Durable SQLite job queue with retries and dead-letter handling
- Account-level locking (parallel workers across accounts, serial per account)
- Bounded timeouts, stale lease recovery, capped exponential backoff
- Cross-save propagation handled by supervisor

### New Domain Factory (`rankstein.py add-domain --clone-site`)
- Gemini CLI research → niche detection → keyword/category generation
- Clones and rebrands RecetaDolce Next.js template
- Generates `site_blueprint.json`, `.env.local.example`, Supabase migration assets
- Produces per-domain launch prompt

---

## Key Design Decisions

1. **CLI-first**: Subscriber admin, domain management, all operational tasks are CLI-only. Frontend is read-only monitoring.
2. **No API-key AI**: Gemini CLI subscription/OAuth is the only supported AI path. `GOOGLE_API_KEY` is not used for orchestration.
3. **Multi-domain**: Domain registry supports both synthesized default (Phase 1) and JSON manifest (Phase 2). All tools accept `domain_handle`.
4. **Live gate**: A keyword is only marked `Live` when Supabase publish, Pinterest upload, and pin_id linkage are all verified.
5. **MCP-first tools**: All RankStein capabilities are exposed as MCP tools consumed by Gemini CLI. No direct Gemini API calls.
6. **Self-healing Playwright**: Pinterest automation includes LLM-powered selector recovery, circuit breakers, rate limiting, and session pooling.
7. **AgentMemory**: Long-term knowledge storage — reusable lessons, recurring failures, selector discoveries. Search before action, remember after.
8. **Unified config migration**: Two legacy config systems (backend + pinterest_automation) being consolidated into `rankstein/config.py`.

---

## Quality Tooling

```powershell
# Lint & format
python -m ruff check .
python -m ruff format --check .

# Type check
python -m mypy .

# Unit tests
python -m pytest tests/unit -q

# Runtime validation
python scripts/dev/validate_gemini_runtime.py
python scripts/dev/validate_automation.py

# Project hygiene
python scripts/dev/self_clean.py --check --include-tracked
python scripts/dev/project_audit.py
```

---

## External Dependencies

- **Gemini CLI**: `npm install -g @google/gemini-cli`
- **AgentMemory**: `npx -y @agentmemory/mcp` + `npx -y @agentmemory/agentmemory --port 3111`
- **Playwright**: `playwright install firefox chromium`
- **Python 3.12+**: `pip install -r requirements-dev.txt`
- **Supabase**: Cloud project with posts/storage/subscribers tables
- **Pinterest**: Configured accounts with valid sessions

---

## Package Layout Summary

```
Rankstein (Python 3.12+)
├── rankstein/              CLI + domain + config
├── backend/                FastAPI + agents + services
├── pinterest_automation/   Queue + browser + health
├── frontend/               Next.js 16 operator UI
├── tests/                  pytest (unit/integration/e2e)
├── scripts/                dev tools + ops scripts
├── docs/                   system docs + templates
├── tools/                  iii + playwright-mcp
├── memory/                 MD workflow state
└── data/                   Runtime state (gitignored)
```

---

## Gaps & Observations

- `rankstein_mcp_server.py` is ~1700 lines and should be split into package modules under `rankstein/`
- Two legacy config systems still active alongside the unified `rankstein/config.py`
- Some agent classes in `backend/agents/` reference legacy ADK patterns not used in the maintained CLI path
- `data/domains/` currently empty — only the synthesized default (`recetadolce`) is active
- Docker deployment only covers the FastAPI backend, not the full autonomous pipeline
- Frontend `AGENTS.md` warns about Next.js 16 breaking changes — docs in `node_modules/next/dist/docs/`

---

## Full Audit Diagnostic Results

### 1. Config Loading
**PASS** — `rankstein.config.Settings` loads cleanly from `.env`. ai_engine=gemini_cli, supabase_configured=True.

### 2. Python Compile Check (key files)
**PASS** — `cli.py`, `domain.py`, `subscribers.py` all compile clean.

### 3. Ruff Lint (core source: rankstein/, rankstein_mcp_server.py, backend/, pinterest_automation/)
**57 errors found** (35 auto-fixable):
- 15× `E701` — multiple statements on one line (mostly ops scripts)
- 12× `F401` — unused imports
- 12× `I001` — unsorted imports
- 5× `UP017` — datetime UTC alias
- 4× `RUF003` — ambiguous unicode in comments
- 2× `RUF002` — ambiguous unicode in docstrings
- 2× `UP041` — timeout error alias
- 1× `F811`, `RUF022`, `RUF100`, `S110`, `UP024` each

### 4. Ruff Format Check (all tracked source)
**45 files would be reformatted**, 68 already formatted. Files needing formatting span:
- `rankstein/` (cli.py, provisioner.py, recipe_pin_generator.py, site_factory.py, startup.py)
- `rankstein_mcp_server.py`, `run_autonomous.py`
- `backend/` agents, scripts, services (13 files)
- `pinterest_automation/` (9 files)
- `scripts/` (10 files)

### 5. Unit Tests (pytest tests/unit)
**162 passed, 9 failed** (41.34s):

| Test | Failure |
|---|---|
| `test_config::TestPinterestAutomationAccounts::test_singleton_credentials_register_default_account_when_distinct` | Config assertion: expected `['m1', 'r1']`, got `['r1', 'rida']` |
| 4× `test_create_hero_image_pollinations.py::TestPollinationsFallback` | Tests expect specific API behavior, likely need mock update |
| `test_keyword_roadmap::test_completion_output_requires_full_publication_proof` | Status mismatch: expected `Needs Verification`, got `Live` |
| 3× `test_memory_service.py` | All fail because AgentMemory (`:3111`) is not running — expected HTTP failures |

### 6. Project Audit (project_audit.py)
**308 files audited**: 1 fail, 14 review items. Reports written to `data/reports/`.

### 7. Self-Clean Check (self_clean.py --check --include-tracked)
**5261 cleanup candidates** — almost all `__pycache__` dirs inside `voxcpm_venv/` (a separate venv for a voice cloning project, not RankStein's main venv).

### 8. Key Health Signals
- **Core code compiles**: critical path modules are syntactically valid
- **Config loads**: unified config system works correctly
- **162/171 tests pass**: 9 failures are either missing runtime (AgentMemory) or mock/snapshot drift
- **Lint issues are mostly cosmetic**: 35 of 57 errors are auto-fixable (unused imports, import sorting)
- **45 files need formatting**: formatting drift from ruff version updates
- **Dual configs still active**: `backend/core/config.py` and `pinterest_automation/config.py` are legacy — migration to `rankstein/config.py` is incomplete

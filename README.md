# RankStein

RankStein is an autonomous SEO content and Pinterest distribution system for recipe domains. The maintained production path is CLI-first: Hermes Codex generates articles, MCP servers provide tools, Python services execute domain logic, Playwright controls browsers, Supabase stores published data, and AgentMemory stores long-term operational lessons.

Updated: 2026-08-24

## Current State

- Core engine: CLI-first orchestration through `python rankstein.py launch` for full service startup, preflight, workers, Pinterest supervisor, and monitoring.
- Article generation: direct Codex CLI is the production default (`RANKSTEIN_ARTICLE_PROVIDER=codex-cli`, `RANKSTEIN_CODEX_CLI_MODEL=gpt-5.6-sol`). An attested Hermes OpenAI-Codex route is permitted, but Gemini, Odysseus, OpenCode, OpenRouter, and template text are not article fallbacks. Provider failure stops publication.
- Tool layer: RankStein MCP, Playwright Firefox, Playwright Chromium, Supabase MCP, NanoBanana MCP, and AgentMemory MCP.
- Long-term memory: AgentMemory MCP plus local REST worker on `http://127.0.0.1:3111/agentmemory/health`.
- Browser automation: Chromium is the unattended production browser; shared Playwright helpers retain Firefox support for interactive diagnostics.
- Trend intelligence: an empty qualified queue triggers domain-aware discovery from Pinterest Trends/Search, Google News, Google Trends RSS, and Google Suggestions. RankStein preserves source provenance, rejects vague phrases, requires specificity plus independent demand evidence, and isolates individual provider failures.
- Image generation: article heroes use Codex `gpt-image-2` only and fail closed on any provider error; all prompts follow `docs/templates/IMAGE_GENERATION_CONTRACT.md`.
- Pinterest automation: queue execution validates configured account handles, runs bounded Playwright pin jobs, recovers stale leases, and retries transient failures with capped backoff.
- Fresh campaign contract: every article run includes multi-source keyword discovery, source article scraping, Codex article creation, a Codex hero, a verified primary hero-based pin, and exactly 15 unique scraped Pinterest sources transformed into `viral_visual` + `recipe_card` pairs (30 queued pins). See `docs/system/CAMPAIGN_PIPELINE.md`.
- Subscriber administration: CLI-only through `python rankstein.py subscribers ...`.
- Project hygiene: this workspace is local-only; generated payloads, browser profiles, debug scripts, local sessions, and old duplicated context docs stay outside the maintained source path.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt
playwright install firefox chromium
# The local operator uses Python; no Next.js build is needed.
```

Copy `.env.example` to `.env` and fill in local credentials. Do not commit `.env`, browser profiles, Supabase service role keys, Gemini auth files, Pinterest credentials, or generated article payloads.

The production article provider is controlled by `RANKSTEIN_ARTICLE_PROVIDER=codex-cli`. Legacy engine settings do not authorize a non-Codex article provider.

## Run

```powershell
.\.venv\Scripts\python.exe rankstein.py --help
.\.venv\Scripts\python.exe rankstein.py list-domains
.\.venv\Scripts\python.exe rankstein.py launch
.\.venv\Scripts\python.exe rankstein.py run --no-launch --json
.\.venv\Scripts\python.exe rankstein.py trends --domain recetadolce --limit 10
```

`rankstein trends` defaults to `pinterest_required`: every retained phrase must
come from targeted Pinterest Trends/Search evidence before independent demand
and freshness validation. Use `--candidate-origin-policy multi_source` only for
an explicitly requested broad discovery run. The browser collector reconstructs
complete phrases from Pinterest guide chips, rejects UI/pet/foreign-language
noise, and balances multiple dish queries instead of returning one vague family.

`rankstein launch` is the maintained full-system front door. It boots MCP/AgentMemory checks and the standalone RankStein operator, normalizes Pinterest queue boards, runs isolated automation validation, executes the startup audit/seed pass, starts article workers and the Pinterest supervisor only when missing, monitors health, scans recent logs, and writes a JSON report under `data/reports/launcher/`.

For normal Windows operation use the unified controller:

```powershell
.\start_all_services.ps1
.\start_all_services.ps1 -Status
.\start_all_services.ps1 -Stop
.\start_all_services.ps1 -Install -DailyAt 06:30
```

`-Install` creates one idempotent logon task and one daily campaign task. The RankStein operator is at `http://127.0.0.1:7000/operator`; Hermes WhatsApp owns port `3000`. Odysseus and Next.js on port `3001` are no longer suite services. Hermes, authenticated Chromium profiles, and Pinterest workers stay on the Windows host. See `docs/system/OPERATOR_DASHBOARD.md`.

The Pinterest supervisor starts idle by default. Historical-post enqueueing, remaster-folder enqueueing, and the continuous social siphon are opt-in through `RANKSTEIN_ENQUEUE_UNPINNED_POSTS`, `RANKSTEIN_ENQUEUE_REMASTER_FOLDER`, and `RANKSTEIN_ENABLE_REMASTER_SIPHON`. The daily campaign trigger is the production work source.

`rankstein run` is the campaign preflight and worker startup sub-path. It refreshes daily multi-source keyword intelligence unless `--skip-trends` is set, briefs DB/domain/queue stats, cleans each domain keyword roadmap, resets abandoned `In Progress` rows, removes duplicate keywords, reconciles proof-backed completed work, seeds campaign records only for fresh qualified keywords, then launches domain article workers unless `--no-launch` is set.

`rankstein add-domain <domain> --clone-site` is the new blog factory path. It
keeps the existing domain research/provisioning flow, then sanitizes and
rebrands the sibling `recetadolce` Next.js template into a new project folder,
writes `site_blueprint.json`, `.env.local.example`, Supabase migration assets,
Vercel/Supabase helper scripts, and a per-domain launch prompt. Fill the
generated Supabase/Vercel env values before deploying or starting article
workers for the new handle.

`rankstein trends` round-robin collects domain-aware candidates from Pinterest, Google News, Google Trends RSS, and Google Suggestions, retains per-phrase provenance, validates specificity and independent demand/freshness, writes `daily_best_keywords.json/.md` per domain, and appends only qualified `Pending` rows unless `--no-roadmap` is set. Provider failures are fail-soft, while static seeds, stale reports, vague phrases, and unsupported demand fail closed. The default `search_demand_score` is a relative proxy, not literal monthly volume; a configured Google Ads historical-metrics provider is required for true average monthly searches.

Keyword gate controls default to `RANKSTEIN_MIN_SEARCH_DEMAND_SCORE=2` and `RANKSTEIN_KEYWORD_EVIDENCE_MAX_AGE_HOURS=36`. Article workers require the fresh daily evidence row and at least two independently relevant extracted recipe sources before Codex writing begins.

`rankstein autonomous` repeats the startup cycle on an interval. Use `--cycles 1 --no-launch` for a safe single-cycle dry run.

Pinterest queue execution is controlled by `.\.venv\Scripts\python.exe run_autonomous.py run`. Every job must carry a configured `domain_handle` and `account_handle`; unknown or missing identity fails closed. A supervisor lease prevents duplicate pools, and its heartbeat is visible through `run_autonomous.py status`. Throughput is bounded to two workers and two persistent Chromium sessions by default. Account-level locks allow only one create/save flow per account, while persisted domain/account rate budgets and deterministic cohorts prevent quadratic fanout. Cross-saving defaults to zero. When the supervisor is healthy, synchronous primary-pin requests enqueue at priority 1 and wait for its verified result instead of opening a competing browser against the same profile. A pin upload is successful only when a verified `pin_id` or `pin_url` is captured. Any DLQ entry degrades top-level health until it is reconciled or requeued.

Article-specific remaster campaigns are fixed at 15 unique scraped Pinterest sources and 30 assets. The campaign layer passes short dish/ingredient `search_queries`, `core_terms`, `expected_terms`, and `blocked_terms`; the scraper uses bounded retries, overcollection, metadata relevance, and pin-ID deduplication. Normal production never fills missing sources with generated images: fewer than 15 accepted sources creates no variants and mutates no queue. A complete source set creates exactly one `viral_visual` plus one readable `recipe_card` per source, validates all 30 files, then queues the run with pair/source/variant identity. Reports under `data/reports/campaigns/` are domain/run scoped and cannot verify production without 15 unique sources and 30 unique queue job IDs.

Subscriber operations stay out of the frontend:

```powershell
python rankstein.py subscribers add user@example.com --source cli
python rankstein.py subscribers list --limit 25
python rankstein.py subscribers unsubscribe user@example.com
python rankstein.py subscribers export subscribers.csv
```

## Validate

```powershell
python scripts/dev/self_clean.py --check --include-tracked
python scripts/dev/project_audit.py
python -m ruff check .
python -m ruff format --check .
python -m pytest tests/unit -q
python scripts/dev/validate_gemini_runtime.py
python scripts/dev/validate_automation.py
```

Use the self-cleaner before packaging or publishing a clean local copy:

```powershell
python scripts/dev/self_clean.py
python scripts/dev/self_clean.py --apply
```

## Project Map

```text
Rankstein/
  rankstein/                Core CLI, domains, config, subscribers
  rankstein_mcp_server.py   Main RankStein MCP server
  backend/                  FastAPI app, agents, services, memory client
  pinterest_automation/     Queue, session pool, browser automation, health
  frontend/                 Recipe-site template (not the local operator)
  scripts/dev/              Validation, runtime startup, self-cleaning
  data/                     Local runtime state; mostly ignored
  memory/                   Human-readable keyword and Pinterest backlog state
  docs/system/              Canonical architecture, runtime, hygiene docs
  docs/templates/            Prompt contracts and reusable generation templates
```

Start with [docs/system/PROJECT_MAP.md](docs/system/PROJECT_MAP.md) for the full architecture.

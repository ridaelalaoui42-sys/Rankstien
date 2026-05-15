# RankStein

RankStein is an autonomous SEO content and Pinterest distribution system for recipe domains. The maintained production path is CLI-first: Gemini CLI subscription/OAuth reasons over the work, MCP servers provide tools, Python services execute the domain logic, Playwright controls browsers, Supabase stores published data, and AgentMemory stores long-term operational lessons.

Updated: 2026-05-13

## Current State

- Core engine: Gemini CLI subscription/OAuth, launched through `python rankstein.py run` for normal multidomain startup.
- Tool layer: RankStein MCP, Playwright Firefox, Playwright Chromium, Supabase MCP, NanoBanana MCP, and AgentMemory MCP.
- Long-term memory: AgentMemory MCP plus local REST worker on `http://127.0.0.1:3111/agentmemory/health`.
- Browser automation: shared Playwright helpers support Firefox and Chromium.
- Trend intelligence: Playwright-first Pinterest Trends/Search collection validates candidates against Google News and appends unique daily keywords per domain.
- Image generation: all hero, OG, inline, and Pinterest prompts follow `docs/templates/IMAGE_GENERATION_CONTRACT.md`.
- Pinterest automation: queue execution validates configured account handles, runs bounded Playwright pin jobs, recovers stale leases, and retries transient failures with capped backoff.
- Subscriber administration: CLI-only through `python rankstein.py subscribers ...`.
- Project hygiene: this workspace is local-only; generated payloads, browser profiles, debug scripts, local sessions, and old duplicated context docs stay outside the maintained source path.

## Setup

```powershell
python -m venv venv
.\venv\Scripts\pip install -r requirements-dev.txt
playwright install firefox chromium
cd frontend
npm install
cd ..
```

Copy `.env.example` to `.env` and fill in local credentials. Do not commit `.env`, browser profiles, Supabase service role keys, Gemini auth files, Pinterest credentials, or generated article payloads.

## Run

```powershell
python rankstein.py --help
python rankstein.py list-domains
python rankstein.py show-domain recetadolce
python rankstein.py add-domain newfoodblog.com --clone-site
python rankstein.py run
python rankstein.py run --no-launch --json
python rankstein.py run --domain recetadolce --keywords 3 --workers 1
python rankstein.py trends --domain recetadolce --limit 10
python rankstein.py autonomous --cycles 1 --no-launch --trend-limit 10
```

`rankstein run` is the maintained front door. It refreshes daily trend intelligence unless `--skip-trends` is set, briefs DB/domain/queue stats, cleans each domain keyword roadmap, resets abandoned `In Progress` rows, removes duplicate keywords, marks DB-completed keywords as `Live`, seeds missing campaign records, then launches domain article workers unless `--no-launch` is set.

`rankstein add-domain <domain> --clone-site` is the new blog factory path. It
keeps the existing domain research/provisioning flow, then sanitizes and
rebrands the sibling `recetadolce` Next.js template into a new project folder,
writes `site_blueprint.json`, `.env.local.example`, Supabase migration assets,
Vercel/Supabase helper scripts, and a per-domain launch prompt. Fill the
generated Supabase/Vercel env values before deploying or starting article
workers for the new handle.

`rankstein trends` collects Pinterest niche trends with Playwright, compares them with Google News RSS signals, writes `daily_best_keywords.json/.md` per domain, and appends new unique `Pending` rows to each domain roadmap unless `--no-roadmap` is set.

`rankstein autonomous` repeats the startup cycle on an interval. Use `--cycles 1 --no-launch` for a safe single-cycle dry run.

Pinterest queue execution is controlled by `python run_autonomous.py run`. Throughput is intentionally bounded by session health and per-account limits, but the active path avoids long publish-confirmation waits: pin confirmation defaults to 8s, upload jobs time out after 210s, stale processing leases recover after 20 minutes, and retries use capped exponential backoff. Untagged queue jobs route to `PINTEREST_DEFAULT_ACCOUNT_HANDLE` when set, otherwise to `r1` when that configured rida account handle exists. A pin upload is not treated as successful unless a verified `pin_id` or `pin_url` is captured. The default worker count is 2, with an account-level lock so one Pinterest account has only one active create/save flow at a time. The `r1` board map uses live board names (`Aperitivos`, `Arroces`, `Carnes`, `Chocolate`, `ENSALADES`, `Fresas`, `Pescados`), and the default fallback board is `Aperitivos`; do not enqueue the obsolete `recetas` board. Raise workers only after queue payloads are distributed across configured accounts. Override with `PINTEREST_WORKER_COUNT`, `PINTEREST_PIN_CONFIRM_TIMEOUT_SECONDS`, `PINTEREST_PIN_UPLOAD_JOB_TIMEOUT_SECONDS`, `PINTEREST_PROCESSING_LEASE_TIMEOUT_SECONDS`, `PINTEREST_RETRY_BASE_SECONDS`, and `PINTEREST_RETRY_MAX_SECONDS`. MCP fallback is off during batch pinning unless `PINTEREST_ENABLE_MCP_FALLBACK=true`.

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
  frontend/                 Next.js operator UI
  scripts/dev/              Validation, runtime startup, self-cleaning
  data/                     Local runtime state; mostly ignored
  memory/                   Human-readable keyword and Pinterest backlog state
  docs/system/              Canonical architecture, runtime, hygiene docs
  docs/templates/            Prompt contracts and reusable generation templates
```

Start with [docs/system/PROJECT_MAP.md](docs/system/PROJECT_MAP.md) for the full architecture.

# RankStein Agent Instructions

RankStein is a local-first autonomous SEO content and Pinterest distribution system for multiple recipe domains. When running from this repository, treat the workspace root as the active project and prefer the maintained CLI and MCP-backed workflows over one-off scripts.

## Primary Context

- Start with `README.md`, `MEMORY.md`, and `docs/system/PROJECT_MAP.md` for architecture and current state.
- `docs/system/HERMES_SOUL.md` defines the Hermes/RankStein operating identity and production temperament.
- `GEMINI.md` is the detailed operating contract for agentic production runs.
- The maintained source areas are `rankstein/`, `backend/`, `pinterest_automation/`, `frontend/`, `scripts/dev/`, `docs/system/`, and `tests/`.
- Runtime state lives mostly under `data/` and `memory/`; generated payloads, browser profiles, screenshots, cache files, and one-off debug artifacts are not source.

## Runtime Contract

- Use `python rankstein.py launch` as the full multidomain service startup, preflight, worker, supervisor, and monitoring path.
- Use `docs/system/CAMPAIGN_PIPELINE.md` as the permanent fresh-campaign contract.
- Use `python rankstein.py run` as the campaign audit/seed/worker sub-path.
- Use `python rankstein.py run --no-launch --json` for a safer audit/seed pass without article workers.
- Use `python rankstein.py trends --domain <handle> --limit 10` for trend refresh.
- Use `python run_autonomous.py run` for the Pinterest queue/supervisor path.
- Use `python run_autonomous.py enqueue-folder` to enqueue remastered image batches.
- Use `run_article_remaster_campaign` or `backend.services.remasterer` for article-specific 30-image scrape/remaster/enqueue campaigns.
- Use `python run_autonomous.py normalize-queue-boards` after DLQ restores or legacy queue imports to normalize obsolete board labels in active jobs and DLQ rows.
- Use `python rankstein.py subscribers ...` for subscriber administration; do not add subscriber admin flows to the frontend.

## Required Project Awareness

- This system is multidomain. Do not assume RecetaDolce is the only target.
- Before production-style work, inspect all configured domains with `python rankstein.py list-domains` and review readiness with the project startup/status tools.
- Domain identity must flow through every article, prompt, Supabase payload, and Pinterest job: handle, public domain, niche, brand voice, board, and configured account handle.
- A keyword may be marked `Live` only after Supabase publish, storage, and a verified Pinterest `pin_id` or `pin_url` are all proven.
- Article-only success is `Needs Verification`, not `Live`.
- No article may be produced, published, or marked successful from deterministic/template/non-LLM fallback text. If all LLM providers fail, mark the keyword `Failed` and do not publish.
- Article generation is Hermes Codex first by default. `backend/scripts/turbo_articles.py` must call the local Hermes API server (`RANKSTEIN_HERMES_CODEX_URL`, default `http://127.0.0.1:8642/v1`) before Gemini/Odysseus/OpenCode/OpenRouter fallbacks. Keep `RANKSTEIN_ARTICLE_PROVIDER=hermes-codex` unless a human explicitly changes it.

## Pinterest Rules

- Prefer Chromium for unattended browser automation; Firefox profile locks are known blockers.
- Default unattended Pinterest worker count is 2. Increase only after queue payloads are deduplicated and spread across healthy account handles.
- Every Pinterest job must carry a configured `account_handle`; unknown accounts fail closed.
- For the `r1` account, live board names include `Aperitivos`, `Arroces`, `Carnes`, `Chocolate`, `ENSALADES`, `Fresas`, and `Pescados`. The old `recetas` board is obsolete.
- Normalize legacy board labels before enqueue, upload, save, or DLQ requeue. Known mappings include `Postres y Dulces` -> `Chocolate`, `Arroces y Paellas` -> `Arroces`, `Aperitivos y Tapas` -> `Aperitivos`, `Ensaladas y Saludable` -> `ENSALADES`, `Carnes y Tradición` -> `Carnes`, and `Recetas Españolas`/`recetas` -> `Aperitivos`.
- Pin upload success requires a verified `pin_id` or `pin_url`; uncertain publishes must retry.

## Content And Image Rules

- Generated recipe articles must have complete JSON, article markdown, and recipe schema. `recipeIngredient` and `recipeInstructions` must never be empty.
- Fresh campaigns must run keyword scraping, source article scraping, compact source extraction, article creation, hero image creation, hero-based pin creation, then article-specific Pinterest image scraping/remastering for a target of 30 relevant remastered pins.
- Recipe schema should include specific, non-placeholder ingredients and HowToStep-style instructions, plus name, image, description, author, prep/cook/total time, yield, cuisine, and category.
- Reject source-copy blocks, non-Pinterest blockquotes, repeated sentence patterns, internal pipeline notes, and generic placeholders such as "ingrediente principal" or "cocina la base".
- Use `docs/templates/IMAGE_GENERATION_CONTRACT.md` for hero, OG, inline, and Pinterest image prompts.
- Hero and OG prompts should show the actual finished dish, avoid embedded text/logos/watermarks, and include Spanish alt text.
- Pinterest prompts should be vertical 2:3, tied to the destination URL and configured account handle, and use only short overlay concepts.
- Pinterest image scraping must receive a generated scrape brief from the campaign layer. Do not hardcode scraper search keywords inside the scraper.
- If scraped images are irrelevant, undersized, or insufficient, use native image generation to fill the missing remaster slots.
- Article remaster campaigns must queue the exact images generated in the current article run, write `data/reports/campaigns/*_remaster_*.json`, and report incomplete if fewer than 30 remastered assets are produced.

## Memory And Secrets

- Search AgentMemory before action when relevant, and write durable operational lessons after meaningful outcomes.
- Store reusable lessons, selector changes, source-quality preferences, account cooldowns, and runtime patterns.
- Never store secrets, cookies, session paths, full scraped source text, full generated articles, raw browser profiles, or credentials in memory.
- Do not commit `.env`, Supabase service role keys, Gemini auth files, Pinterest credentials, browser profiles, or generated article payloads.

## Hygiene And Validation

- Do not create new root scratch files. Debug scripts go under `scripts/debug/`.
- `scripts/dev/validate_automation.py` must remain isolated from production queue/circuit/rate-limit/health/cache state; do not change it to use live runtime state.
- Run focused tests for changed code. The maintained validation baseline is:
  - `python scripts/dev/self_clean.py --check --include-tracked`
  - `python scripts/dev/project_audit.py`
  - `python -m ruff check .`
  - `python -m ruff format --check .`
  - `python -m pytest tests/unit -q`
  - `python scripts/dev/validate_gemini_runtime.py`
  - `python scripts/dev/validate_automation.py`

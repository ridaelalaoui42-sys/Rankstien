# RankStein Agent Operating Guide

This file is the short operating contract for Gemini CLI and agentic runs.

## Runtime Contract

```text
STANDARD SESSION LAUNCH (one command):
  .\scripts\dev\start_all_mcp.ps1
    -> loads .env
    -> starts agentmemory HTTP server on :3111 (waits for healthy)
    -> validates rankstein_mcp_server.py syntax
    -> validates nanobanana dist/index.js
    -> validates playwright-mcp.cmd in PATH
    -> confirms supabase remote HTTP endpoint
    -> launches Gemini CLI (interactive session)

LAUNCH WITH AUTONOMOUS SUPERVISOR:
  .\scripts\dev\start_all_mcp.ps1 -WithSupervisor
    -> all of the above, plus:
    -> starts run_autonomous.py (Pinterest queue + article workers for ALL domains)

STATUS CHECK (no launch):
  .\scripts\dev\start_all_mcp.ps1 -StatusOnly

FROM python CLI (also boots MCP servers automatically):
  python rankstein.py run
    -> calls start_all_mcp.ps1 -NoGemini (boots servers, skips Gemini relaunch)
    -> refresh Pinterest/Google News trend intelligence
    -> audit DB, domains, queues, keyword roadmaps, AgentMemory
    -> clean duplicate/stuck keyword state and seed missing campaigns
    -> launches turbo_articles.py --all-domains

MCP SERVERS:
  agentmemory      HTTP :3111  (local process, must be started first)
  rankstein        stdio       (Gemini CLI auto-starts from settings.json)
  nanobanana       stdio       (Gemini CLI auto-starts from settings.json)
  playwright_ff    stdio       (Gemini CLI auto-starts from settings.json)
  playwright_cr    stdio       (Gemini CLI auto-starts from settings.json)
  supabase         HTTP remote (always available, no local process)
```

Gemini CLI subscription/OAuth is the primary reasoning path. Do not replace it with an API-key workflow, and do not pass `GOOGLE_API_KEY` or `GEMINI_API_KEY` into Gemini CLI subprocesses. Use `ADK_MODEL=auto` or Gemini 3/3.1 model variants so Gemini CLI can route through the subscription account.

## Trigger Words

These phrases from the user ALWAYS mean the same thing — execute without asking:

| Phrase | Action |
|--------|--------|
| `START ALL` | Run the full daily campaign: startup sequence + backlog + supervisor + article pipeline for ALL domains. No confirmation. |
| `START ALL` (from CLI) | Equivalent to running `.\scripts\dev\start_all_mcp.ps1 -StartAll` |
| `CONTINUE` | Resume the current pipeline from where it stopped. Process all remaining pending keywords. |
| `STATUS` | Call `multidomain_startup_brief()` + `memory_stats()` and report queue depth, domain readiness, and recent failures. |

When you see `START ALL`, immediately execute steps 1–8 of Required Start Of Run and the full pipeline without any preamble or questions.

## Required Start Of Run

**CRITICAL: This system manages MULTIPLE domains simultaneously. Never default to working on a single domain. Every session MUST cover ALL domains in the portfolio. Do NOT ask the user if you should proceed — execute all steps automatically.**

1. **`list_domains()`** — FIRST call on every session, no exceptions. Gets all handles, niches, and credential status. Do not proceed until this returns successfully.
2. **`multidomain_startup_brief()`** — SECOND call on every session. Returns per-domain readiness: keyword counts, queue depth, AgentMemory lessons, and blocked/ready status for every domain at once.
3. **`process_pinterest_backlog()`** — THIRD call, no confirmation needed. Enqueues ALL Failed/Pending/Missing entries from `memory/pinterest_backlog.md` into the job queue immediately. Do not ask the user — just run it.
4. **`start_automation_supervisor()`** — FOURTH call. Starts `run_autonomous.py run` as a background process to process the Pinterest queue across all domains and accounts. No prompting.
5. **Enqueue remastered pins:** run `python run_autonomous.py enqueue-folder` as a background shell command to enqueue ALL images from `data/media/remaster_final/` for upload across all configured Pinterest accounts. The supervisor (step 4) will process them automatically. Do not wait — fire and continue.
6. `memory_stats()` — check AgentMemory health.
7. `search_project_memory(...)` — search for recent failures, selector changes, source-quality notes, and account issues for EACH domain returned in step 1.
8. Ensure DB domain/project/campaign ownership exists before article creation (runs for all domains).
9. Clean domain keyword roadmaps for ALL domains: dedupe, reset stale `In Progress`, mark DB-completed rows as `Live`.

**Multidomain Work Rule:** Once the startup is complete, work the content pipeline for ALL `ready` domains before cycling. Never skip a domain. If credentials are missing, report it and continue with the others. Never ask "should I proceed?" — always proceed.

## Required Pipeline Shape

1. **Auto-process backlog + remaster queue:** call `process_pinterest_backlog()` (enqueues Failed/Pending/Missing pins) then `start_automation_supervisor()` (starts the worker). Then run `python run_autonomous.py enqueue-folder` in background to push ALL remastered images from `data/media/remaster_final/` into the upload queue. The supervisor will handle uploads for all accounts automatically.
2. Select a pending keyword from `data/domains/<handle>/keywords.md` — pick from ALL domains in rotation.
3. Search AgentMemory: `search_project_memory(query=keyword)`.
4. `get_article_data_from_supabase_by_slug(slug, domain_handle)` — if article exists with valid `pin_id`, mark `Live` and skip (no duplicate). No prompting.
5. Mark keyword `In Progress`.
6. Research source articles with `scrape_news_sources`.
7. Extract useful source text with `extract_article_content`.
8. Generate Spanish article JSON from sources without copying. `recipeIngredient` and `recipeInstructions` arrays must NEVER be empty.
9. Pass `validate_article_quality`; revise up to three times.
10. Generate hero image (`create_hero_image_pollinations`), validate, upload to Supabase Storage (`upload_image_to_supabase`).
11. Generate the Pinterest pin image (`create_article_pin`) and upload it DIRECTLY using `automation_upload_pin_direct` to obtain the `pin_id`. Always pass the correct `board_name` from the domain's `boards_default`.
12. Build the final Supabase payload using `build_supabase_content`, ensuring the `pinterest_pin_id` is passed so it replaces the `[PINTEREST_IFRAME]` placeholder.
13. Publish to Supabase using `publish_article_to_supabase` with `domain_handle` — never omit this field.
14. Auto-campaign triggers: `publish_article_to_supabase` enqueues supplemental pin_upload jobs for secondary accounts; cross-save propagation handled by supervisor.
15. Mark `Live` only when Supabase publish (with valid `pin_id`), Pinterest upload, and storage all succeed.
16. Record outcome with `remember_pipeline_event`.
17. **Remaster social traffic loop (runs in background via supervisor):** `run_autonomous.py enqueue-folder` queues all `remaster_final/` images. The supervisor downloads trending Pinterest pins (social siphon), remasters them with domain branding via `apply_luxury_overlay` + `inject_exif_metadata`, saves to `remaster_final/`, then the uploader accounts post them. This runs continuously — no manual trigger needed after step 1.

## Image And Pin Prompt Contract

All image generation instructions must follow `docs/templates/IMAGE_GENERATION_CONTRACT.md`.

- Hero and OG prompts: realistic finished dish, `16:9` or `1200x630`, no embedded text, no logo, no watermark, no fake URL.
- Pinterest prompts: vertical `2:3`, exact destination URL attached to the pin payload, configured account handle attached, short overlay concept only.
- Include negative prompts and Spanish alt text.
- Avoid generic kitchen atmosphere; the dish must be clear, specific, and inspectable.
- Do not store full prompts containing sensitive paths or credentials in AgentMemory.

## Content Quality Rules

- All generated articles MUST have correct JSON schema, proper article markdown, a complete and valid recipe schema (including ingredients, cook/prep times, yields, and step-by-step instructions), and all database fields correctly populated to ensure they render perfectly on the live website.
- Extraction Phase: When scraping source content, agents MUST prioritize extracting the ingredient list and step-by-step instructions to ensure the `recipe_schema` object is fully populated. Empty schema arrays (`recipeInstructions: []`) are strictly prohibited.
- Validation: The `validate_article_quality` tool will enforce full schema completion. Any article with a partial or empty schema will be rejected as a blocking failure.

## Multidomain And Account Rules

- Every campaign must carry `domain_handle`, public domain, niche, and project ownership.
- Every Pinterest job must carry a configured `account_handle`; unknown accounts fail closed.
- Rate limits, session leases, and recovery notes should be tracked per domain/account.
- Never let a RecetaDolce default leak into another domain's URLs, boards, style, or Supabase target.
- New blogs are created through `python rankstein.py add-domain <domain> --clone-site`.
  Follow `docs/templates/UPCOMING_DOMAIN_SYSTEM_PROMPT.md` for the domain factory flow.
  The generated `site_blueprint.json` and `upcoming_domain_system_prompt.md` become
  source of truth before deployment or posting starts.

## Memory Rules

- Store reusable lessons, recurring failures, selector discoveries, source preferences, and workflow changes in AgentMemory.
- Keep keyword tables and backlog state in Markdown because tools still read those files.
- Do not store secrets, cookies, full scraped articles, full generated articles, or raw browser profiles in memory.
- Do not duplicate large Markdown docs into AgentMemory. Store the decision or lesson, not the whole file.

## Hygiene Rules

- Do not create new root scratch files.
- Debug scripts go under `scripts/debug/`.
- Durable code belongs under `rankstein/`, `backend/`, `pinterest_automation/`, or another established package.
- Generated article payloads, browser sessions, Playwright captures, screenshots, caches, and one-off scripts must stay outside the maintained source path.
- Run `python scripts/dev/self_clean.py --check --include-tracked` and `python scripts/dev/project_audit.py` before packaging or publishing a clean local copy.

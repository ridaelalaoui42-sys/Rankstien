# RankStein Project Memory

This file is human-readable project memory. It is not a dump of runtime events. Durable operational lessons should be written to AgentMemory through the RankStein MCP tools.

Updated: 2026-05-14

## Mission

RankStein automates recipe content production and Pinterest distribution for multiple recipe domains, Pinterest accounts, niches, and brand voices. The system should turn a validated domain keyword into a researched Spanish recipe article, hero image, Pinterest pin, Supabase post, and durable run memory without mixing domain state.

## Current Architecture

- Production content engine: OpenAI Codex CLI/OAuth. Article workers fail closed if direct Codex or an explicitly attested Hermes OpenAI-Codex route is unavailable.
- Tool layer: RankStein MCP, Supabase MCP, Playwright Firefox/Chromium MCP, NanoBanana MCP, AgentMemory MCP.
- Long-term memory: AgentMemory MCP plus local REST worker on port `3111`.
- Publishing: Supabase posts/storage through guarded RankStein tools.
- Browser automation: Playwright with configured Pinterest accounts only; pin uploads use bounded confirmation waits, per-job timeouts, stale lease recovery, capped retry backoff, and a stable default of 2 queue workers unless payloads are explicitly spread across account handles.
- Trend intelligence: `python rankstein.py trends` defaults to the strict `pinterest_required` policy: targeted Pinterest Trends/Search evidence supplies every candidate, then independent demand and optional freshness signals validate it. `refresh_trend_keywords` can still use the explicit `multi_source` policy for broad production discovery. Both modes retain provenance, reject vague phrases, require specificity plus independent demand evidence, and write fresh authorization before roadmap reservation or article research.
- Startup path: `python rankstein.py run` refreshes trends, audits DB/domain/queue state, cleans keyword roadmaps, seeds campaigns, then launches domain workers.
- Autonomous loop: `python rankstein.py autonomous` repeats the startup cycle and logs cycle reports through AgentMemory.
- Image prompts: hero, OG, inline, and Pinterest briefs follow `docs/templates/IMAGE_GENERATION_CONTRACT.md`.
- Admin surface: root CLI; subscriber administration is not a frontend feature.
- Pinterest campaign auto-trigger: every Supabase publish auto-enqueues pin_upload jobs for all configured accounts; cross-save propagation handled by the supervisor.
- Folder batch enqueue: `run_autonomous.py enqueue-folder` bulk-processes remastered images across all accounts.

## State Files Still Used By Tools

- `memory/keywords.md`: legacy/default keyword roadmap used by some fallback flows.
- `memory/pinterest_backlog.md`: articles that still need Pinterest recovery or pin campaigns.
- `data/domains/*/keywords.md`: domain-specific keyword state.
- `data/domains/*/daily_best_keywords.*`: daily trend shortlist for operators and agents.
- `data/keyword_failures.json`: circuit-breaker state when present.

These files are workflow state, not duplicate docs. Keep them concise and machine-readable enough for tools to edit.

## Production Invariants

- `data/domains/*/keywords.md` is the source of truth for domain keyword state.
- `Live` is allowed only after Supabase publish, Pinterest upload, and pin id/url linkage are proven.
- Article-only success is `Needs Verification`, not `Live`.
- Campaigns should be attached to a DB domain and DB project before agents run.
- Pinterest work must carry a configured account handle and respect per-account session/rate limits.
- Legacy/untagged Pinterest queue jobs route to `PINTEREST_DEFAULT_ACCOUNT_HANDLE` when set, otherwise to `r1` when present.
- Pinterest upload success requires a verified `pin_id` or `pin_url`; uncertain publishes must retry and must not be marked complete.
- Pinterest board names must match live account boards. For `r1`, use `Aperitivos`, `Arroces`, `Carnes`, `Chocolate`, `ENSALADES`, `Fresas`, or `Pescados`; `recetas` is obsolete and should be remapped before posting.
- Multi-worker Pinterest runs need per-account locking. Parallel workers may run different accounts, but never two simultaneous create/save flows for the same account.
- Article remaster production is scraped-only: accept 15 unique relevant Pinterest pin IDs, create exactly `viral_visual` and `recipe_card` for each source, then prove 30 unique queue jobs. If source intake or any pair is incomplete, create/queue nothing and leave the article `Needs Verification`; Codex image generation is reserved for the article hero.
- Pinterest publish fallback should prefer deterministic selectors and Ctrl+Enter before optional Gemini selector healing; avoid API-key-based Gemini calls in the pinning path.
- Shared MCP fallback should stay disabled during high-volume batch pinning unless explicitly tested with serialized access.
- Domain identity must flow into every prompt: handle, public domain, niche, brand voice, boards, and account.
- Autonomous article work may reserve only a `Pending` keyword present in a fresh `daily_best_keywords.json` row with recorded discovery provenance, positive specificity, and the configured minimum external demand score. Missing/stale evidence, vague candidates, and static seed fallback fail closed; individual discovery providers fail soft so another independent source can refill an empty queue.
- Source extraction must yield at least two independently relevant recipe articles before LLM article writing begins.

## AgentMemory Usage

Search before action:

```text
memory_stats()
search_project_memory("current keyword/domain/pinterest quality issues", 5)
```

Remember after action:

```text
memorize_insight(...)
remember_pipeline_event(...)
```

Use AgentMemory for:

- recurring quality-gate failures
- Pinterest selector/account issues
- source-selection lessons
- successful pin styles
- runtime health patterns
- architecture and workflow decisions
- domain/account-specific cooldowns, recovery patterns, and launch outcomes
- reusable visual prompt wins/failures, compressed as short lessons

Do not use AgentMemory for:

- secrets or credentials
- cookies or session paths
- full article bodies
- raw scraped text
- generated JSON payloads

## Current Verification Baseline

The maintained checks are:

```powershell
python scripts/dev/self_clean.py --check --include-tracked
python scripts/dev/project_audit.py
python -m ruff check .
python -m ruff format --check .
python -m pytest tests/unit -q
python scripts/dev/validate_gemini_runtime.py
python scripts/dev/validate_automation.py
```

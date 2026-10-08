# RankStein Status

Updated: 2026-05-14

## Summary

RankStein is being cleaned into a production-ready, CLI-first autonomous system. The current maintained path is Gemini CLI subscription/OAuth plus MCP tools, with AgentMemory connected for durable long-term memory and Playwright configured for Firefox/Chromium Pinterest automation.

## Active Capabilities

| Area | Status | Notes |
|---|---|---|
| Unified launcher | Active | `python rankstein.py launch` is the main autonomous entry point for services, campaign preflight, workers, supervisor, and monitoring. |
| AgentMemory | Active | Started by `scripts/dev/start_agentmemory.ps1`; REST health on port `3111`. |
| RankStein MCP | Active | Project tools for keywords, research, quality, images, publishing, and memory. |
| Pinterest automation | Active | Multi-account queue validates configured handles; untagged jobs default to rida handle `r1`; account-level locks serialize each Pinterest account; `r1` queue boards are remapped to live boards (`Aperitivos`, `Arroces`, `Carnes`, `Chocolate`, `ENSALADES`, `Fresas`, `Pescados`); pin jobs require verified pin id/url and have bounded publish confirmation, job timeouts, stale lease recovery, and capped retry backoff. |
| Pinterest campaign auto-trigger | Active | `publish_article_to_supabase` auto-creates campaigns for all configured accounts; `run_autonomous.py enqueue-folder` bulk-processes remastered pins; cross-save propagation handled by supervisor. |
| Supabase publishing | Active | Posts, media, and subscriber records use guarded Python/CLI paths. |
| Hero Image Pipeline | Active | Cascading fallback integrated: Layer 1 (Scraping) -> Layer 1.5 (Codex via Odysseus) -> Layer 2 (Pollinations) -> Layer 3 (Pillow). Old test scripts and debug logs have been successfully cleared. |
| Subscriber admin | CLI-only | Use `python rankstein.py subscribers ...`. |
| Frontend | Operator UI | Monitoring/control surface only; no secret-bearing subscriber admin. |
| Trend intelligence | Active | `rankstein trends` uses Playwright-first Pinterest discovery plus Google News validation. |
| Image prompt contract | Active | `docs/templates/IMAGE_GENERATION_CONTRACT.md` governs hero, OG, inline, and Pinterest prompt briefs. |
| File audit | Active | `scripts/dev/project_audit.py` writes file-by-file reports to `data/reports/`. |
| Project hygiene | Active | `scripts/dev/self_clean.py` works in local-only mode without `.git`. |
| Startup orchestration | Active | `rankstein launch` wraps MCP/AgentMemory/Odysseus service checks, queue normalization, automation validation, `rankstein run` preflight, worker launch, supervisor launch, monitoring, and JSON reports. |

## Current Cleanup Decision

The repo now keeps canonical docs in:

- `README.md`
- `GEMINI.md`
- `MEMORY.md`
- `STATUS.md`
- `docs/system/PROJECT_MAP.md`
- `docs/system/SYSTEM_ARCHITECTURE.md`
- `docs/system/AUTONOMOUS_AGENTIC_SYSTEM.md`
- `docs/system/PROJECT_HYGIENE.md`
- `PORTABILITY.md`
- `EXTERNAL_DEPENDENCIES.md`
- `BACKEND_BLUEPRINT.md`

Old duplicated `.gemini` Markdown mirrors, stale planning docs, generated article Markdown, stale debug launchers, and obsolete trend/context notes are removed from the maintained local source path.

## Remaining Operational Work

- Run live `python rankstein.py launch --monitor-seconds 60` after credentials and sessions are available.
- Restart through `python rankstein.py launch` after Pinterest automation or article pipeline code changes so workers and the supervisor pick up the latest code.
- Monitor `data/logs/automation.log` for cross-save propagation outcomes after campaigns auto-trigger.
- Keep AgentMemory enabled for every autonomous run.
- Keep generated artifacts outside the production path with the self-cleaner and file audit.

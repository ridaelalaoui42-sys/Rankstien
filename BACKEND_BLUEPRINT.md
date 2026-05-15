# Backend Blueprint

Updated: 2026-05-13

This is the maintained backend reference. Older ADK/A2A architecture notes were consolidated into this shorter production view.

## Role

The backend contains the Python services that power RankStein's autonomous workflow:

- domain and subscriber management
- configuration loading
- content research and extraction
- quality validation
- memory client calls
- image/media helpers
- image prompt contract enforcement
- FastAPI routes for the operator UI
- agent classes used by API/SSE orchestration

## Main Packages

| Path | Purpose |
|---|---|
| `backend/main.py` | FastAPI app entry point. |
| `backend/api/routes.py` | HTTP API routes. |
| `backend/core/config.py` | Environment/config settings. |
| `backend/core/database.py` | Local SQLite support for API-side state. |
| `backend/core/ai_engine.py` | Gemini CLI/engine adapter used by agents. |
| `backend/services/memory_service.py` | AgentMemory REST client. |
| `backend/services/news_scraper.py` | Source discovery, extraction, validation helpers. |
| `backend/agents/` | Agent classes and orchestrator for API-visible workflows. |
| `backend/scripts/` | Operational scripts that are still part of maintained automation. |

## Runtime Boundaries

- Gemini CLI subscription/OAuth is the primary model runtime.
- RankStein MCP remains the guarded tool surface for autonomous runs.
- Subscriber administration is CLI-only through `rankstein/subscribers.py`.
- Supabase writes should go through project tools or CLI code, not ad hoc scripts.
- Browser automation belongs in `pinterest_automation/` and shared helpers.

## Required Environment

Important values are loaded from `.env` or process environment:

- `NEXT_PUBLIC_SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- Pinterest account credentials where needed
- Gemini CLI subscription/OAuth for orchestration; do not require `GOOGLE_API_KEY` or `GEMINI_API_KEY` for RankStein agent runs
- Optional provider keys only for explicitly enabled standalone services outside the CLI orchestration path
- Cloudinary values only for enabled media workflows

The config layer must not override already-exported CI or shell values with `.env` values.

## Verification

```powershell
python -m pytest tests/unit -q
python scripts/dev/validate_gemini_runtime.py
python scripts/dev/validate_automation.py
python -m py_compile rankstein\cli.py rankstein\domain.py rankstein\subscribers.py
```

Use focused tests when editing a bounded area, then run the broader unit suite before committing.

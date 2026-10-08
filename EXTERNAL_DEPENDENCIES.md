# External Dependencies

Updated: 2026-05-13

These dependencies are required for full RankStein operation but are not stored as committed project secrets or runtime state.

## Gemini CLI

- Install: `npm install -g @google/gemini-cli`
- Auth: Gemini CLI subscription/OAuth account.
- Project config: `.gemini/settings.json`.
- Role: primary reasoning engine for autonomous runs.

## AgentMemory

- MCP command: `npx -y @agentmemory/mcp`
- REST worker: `npx -y @agentmemory/agentmemory --port 3111`
- Starter: `scripts/dev/start_agentmemory.ps1`
- Health: `http://127.0.0.1:3111/agentmemory/health`
- Required runtime: `iii.exe`, either on PATH, under `%USERPROFILE%\.local\bin`, or provided locally in `tools/iii/`.
- RankStein orchestration does not require `GOOGLE_API_KEY` or `GEMINI_API_KEY`.
- Optional provider keys are allowed only for explicitly enabled standalone AgentMemory features outside the normal local CLI run.

## Supabase

- Required for cloud posts, storage, domains, and subscriber records.
- Store `NEXT_PUBLIC_SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in `.env` or CI secrets only.
- Subscriber admin is handled by `python rankstein.py subscribers ...`.

## Pinterest And Playwright

- Install browsers: `playwright install firefox chromium`.
- Credentials and browser sessions stay local and untracked.
- Automation supports configured account handles only.

## Node Projects

- `frontend/`: Next.js operator UI.
- `nanobanana-extension/`: image/MCP extension workspace governed by `docs/templates/IMAGE_GENERATION_CONTRACT.md`.
- Do not commit `node_modules`, build outputs, or local extension state.

## Python

- Python 3.12+.
- Main install: `pip install -r requirements-dev.txt`.
- Optional frontend checks require local Node/npm installation.

## Secrets Policy

Never store service keys, cookies, browser profiles, OAuth files, generated articles, or local payloads in Markdown or the codebase.

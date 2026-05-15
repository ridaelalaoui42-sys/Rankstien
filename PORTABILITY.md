# Portability Guide

Updated: 2026-05-13

Use this guide to make a fresh local copy work like the current RankStein workspace.

## 1. Copy And Install

```powershell
cd C:\Users\REDX420\Desktop\Rankstein
python -m venv venv
.\venv\Scripts\pip install -r requirements-dev.txt
playwright install firefox chromium
```

Install frontend dependencies when needed:

```powershell
cd frontend
npm install
cd ..
```

## 2. Configure Credentials

Copy `.env.example` to `.env` and fill local values:

- Supabase URL and service role key.
- Pinterest credentials for each automation account.
- Cloudinary credentials if media upload flow needs them.
- Gemini CLI subscription/OAuth for orchestration. Do not require `GOOGLE_API_KEY` or `GEMINI_API_KEY` for RankStein agent runs.
- Optional standalone provider keys only for explicitly enabled non-CLI services.

Do not commit `.env` or browser session folders.

## 3. Authenticate Gemini CLI

```powershell
npm install -g @google/gemini-cli
gemini
```

Use the subscription/OAuth account. `.gemini/settings.json` is the project MCP registration file.

## 4. Start AgentMemory

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dev\start_agentmemory.ps1
```

Expected health endpoint:

```text
http://127.0.0.1:3111/agentmemory/health
```

## 5. Run

```powershell
python rankstein.py run
python rankstein.py list-domains
python rankstein.py trends --limit 10
python rankstein.py autonomous --cycles 1 --no-launch
python rankstein.py subscribers list
```

## 6. Verify

```powershell
python scripts/dev/self_clean.py --check --include-tracked
python -m pytest tests/unit -q
python scripts/dev/validate_gemini_runtime.py
python scripts/dev/validate_automation.py
```

Browser sessions in `data/sessions/` and `data/domains/*/data/sessions/` are regenerated locally. They are intentionally not portable through Git.

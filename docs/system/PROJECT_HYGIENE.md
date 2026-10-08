# Project Hygiene

Updated: 2026-05-13

RankStein is currently maintained as a local-only project workspace. Keep source, tests, stable configuration, and canonical documentation in the maintained source path. Generated article payloads, browser profiles, debug scripts, Playwright captures, local queues, logs, cache folders, and duplicated context Markdown stay out of the production path.

## Canonical Markdown

Keep these docs current:

- `README.md`
- `GEMINI.md`
- `MEMORY.md`
- `STATUS.md`
- `docs/system/PROJECT_MAP.md`
- `docs/system/HERMES_SOUL.md`
- `docs/system/SYSTEM_ARCHITECTURE.md`
- `docs/system/AUTONOMOUS_AGENTIC_SYSTEM.md`
- `docs/system/PROJECT_HYGIENE.md`
- `docs/templates/IMAGE_GENERATION_CONTRACT.md`
- `PORTABILITY.md`
- `EXTERNAL_DEPENDENCIES.md`
- `BACKEND_BLUEPRINT.md`

Do not reintroduce mirrored `.gemini/*.md` or `.gemini/context/*.md` copies. The project-level MCP configuration belongs in `.gemini/settings.json`.

## Self-Cleaner

Dry-run:

```powershell
python scripts/dev/self_clean.py
```

Apply cleanup:

```powershell
python scripts/dev/self_clean.py --apply
```

CI/preflight check:

```powershell
python scripts/dev/self_clean.py --check --include-tracked
```

The cleaner is dry-run by default, works without `.git`, and refuses paths outside the project root.

## File Audit

Generate the current file-by-file report:

```powershell
python scripts/dev/project_audit.py
```

Reports are written to:

- `data/reports/file-by-file-audit.json`
- `data/reports/file-by-file-audit.md`

The audit includes source, tests, config, canonical docs, memory prompts, and domain manifests/roadmaps. It excludes dependencies, caches, browser sessions, generated media, and report output.

## Source Rules

- Keep real package/config JSON files. Do not use broad `*.json` cleanup rules.
- Remove generated `article_*.json`, root publish/debug/test scripts, browser sessions, and old local reports.
- Keep `memory/keywords.md`, `memory/pinterest_backlog.md`, `data/domains/*/keywords.md`, and `data/domains/*/daily_best_keywords.*` because tools and operators read them.
- Keep placeholders such as `.gitkeep` so runtime directories exist without tracking their contents.

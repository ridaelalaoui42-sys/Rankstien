# SKILL: cli-rankstein

## Description

Control the API-facing RankStein harness from the command line. For the maintained local autonomous system, prefer the root CLI: `python rankstein.py`.

## Installation

```bash
cd /path/to/Rankstein/cli-harness && pip install -e .
```

## Commands

Run `cli-rankstein --help` for the API harness command list.

## Usage Patterns

### Domain Management

```bash
cli-rankstein domains list --json
cli-rankstein domains add --name <name> --url <url> --niche <niche> --json
```

### SEO Pipeline

```bash
cli-rankstein campaigns launch --keyword "<keyword>" --domain <domain> --niche <niche> --json
```

### SEO Analysis

```bash
cli-rankstein seo keywords --seed "<keyword>" --json
cli-rankstein seo analyze --domain <domain> --json
cli-rankstein seo competitors --domain <domain> --json
```

## Environment

- `RANKSTEIN_API_URL`: API base URL (default: `http://127.0.0.1:8080`)
- `RANKSTEIN_API_KEY`: API harness authentication key

## Current RankStein Note

Updated: 2026-05-13

Use this skill for the API-facing `cli-rankstein` harness. For local domain, trend, autonomous, subscriber, and prompt/image workflows, prefer the root project CLI: `python rankstein.py`. Subscriber commands are intentionally CLI-only and are not part of the frontend admin surface.

RankStein orchestration uses Gemini CLI subscription/OAuth, AgentMemory, Playwright MCP, and NanoBanana MCP. Do not ask for Google/Gemini API keys for normal local runs. Image-generation briefs must follow `docs/templates/IMAGE_GENERATION_CONTRACT.md`.

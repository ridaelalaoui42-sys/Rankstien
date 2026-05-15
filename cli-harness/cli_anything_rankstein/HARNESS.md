# RankStein — Agent-Native CLI Harness

## Overview
**cli-rankstein** is the agent-native command-line interface for RankStein, an enterprise AI SEO platform with a 10-agent fleet (CEO, Manager, Strategist, Researcher, Author, Validator, Studio, Publisher, Layout, Pinterest).

## Installation
```bash
cd cli-harness
pip install -e .
```

## Usage
```bash
# Set environment variables
export RANKSTEIN_API_URL="http://127.0.0.1:8080"
export RANKSTEIN_API_KEY="your-secret-key"

# Check health
cli-rankstein health
cli-rankstein health --json

# Manage domains
cli-rankstein domains list --json
cli-rankstein domains add --name myblog --url https://myblog.com --niche Technology

# Launch SEO pipeline (SSE streaming)
cli-rankstein campaigns launch --keyword "best seo tools" --domain myblog.com --niche General --json

# SEO tools
cli-rankstein seo keywords --seed "ai seo" --json
cli-rankstein seo analyze --domain myblog.com --json
cli-rankstein seo competitors --domain myblog.com --json
cli-rankstein seo onpage --url https://myblog.com/post-1 --json
cli-rankstein seo content-optimize --keyword "seo tools" --content-file article.md --json

# Analytics
cli-rankstein analytics overview --json
cli-rankstein credits --json
```

## Agent Integration
All commands support `--json` flag for structured output that AI agents can parse:
```json
{
  "total_campaigns": 42,
  "total_domains": 5,
  "total_words": 125000,
  "avg_eeat": 89.2,
  "credits_remaining": 4500,
  "credit_tier": "commander"
}
```

## Commands
| Command | Description |
|---------|-------------|
| `health` | API health check |
| `domains list/add/get/update/archive/activate/pause` | Manage connected domains |
| `campaigns list/get/artifacts/approve/reject/launch` | Campaign management + pipeline |
| `seo analyze/audit/keywords/competitors/keyword-map/onpage/content-optimize/backlinks` | SEO tools |
| `integrations list/add/test/remove` | CMS/social integrations |
| `analytics overview/campaigns` | Performance metrics |
| `credits` | Credit balance |
# Current Harness Note - 2026-05-10

This document describes the agent-native API harness. The maintained local CLI entry point is `python rankstein.py`, including `python rankstein.py subscribers ...` for Supabase-backed subscriber operations. Keep the two CLIs conceptually separate when documenting or testing workflows.

---

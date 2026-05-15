# RecetaDolce Content Wizard 🧙‍♂️

The Content Wizard is a legacy frontend-facing description of an older content package flow. The maintained RankStein runtime now uses Gemini CLI subscription/OAuth, AgentMemory, Playwright MCP, NanoBanana MCP, and the root CLI.

## Features
- **High-End Pinterest Pins**: Generates vertical pin briefs with short overlay concepts. Keep ingredients, steps, and URLs in metadata or post-processing, not baked into the model-rendered image.
- **SEO Blog Articles**: 1200+ word articles in Spanish with Meta tags, JSON-LD schemas (Recipe & FAQ), and categories.
- **Premium Photography**: Editorial-quality food photography for both Featured images and Pinterest.
- **Supabase Integration**: Optional one-click publishing to your database and storage.

## Installation
For maintained local operation, install the project dependencies:
```bash
pip install -r requirements-dev.txt
```

## Usage
Prefer the maintained CLI:
```bash
python rankstein.py trends --domain recetadolce --limit 10
python rankstein.py run --domain recetadolce --keywords 1 --workers 1
```

### Options
- `--publish`: Automatically uploads images to Supabase and inserts the post into the `posts` table.

## Output
All generated content is saved in the `output/<slug>/` directory:
- `article.json`: Full blog post data and metadata.
- `featured.jpg`: 4:3 high-end food photo.
- `pinterest_pin.png`: 2:3 vertical luxury pin with editorial layout.

## Model Configuration

- **Text/agent orchestration**: `auto` through Gemini CLI subscription/OAuth.
- **Images**: NanoBanana MCP with `gemini-3.1-flash-image-preview` by default.
- **Image contract**: `docs/templates/IMAGE_GENERATION_CONTRACT.md`.

# Current Content Wizard Note - 2026-05-13

The maintained RankStein runtime uses Gemini CLI subscription/OAuth for autonomous execution. Treat older direct model/API-key wording as historical unless a standalone script explicitly requires it. Subscriber management is CLI-only, and Pinterest publishing must preserve configured account handles for batch automation.

---

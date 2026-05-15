# Multi-Domain Support — File-by-File Plan

**Status:** PLANNING (no code touched yet)
**Author:** Claude Code session 2026-05-03
**Supersedes:** `.planning/multi-account.md` (its multi-account scope becomes a sub-system here — each domain owns its own Pinterest account roster)

---

## Context

Today RankStein is hard-wired to **one blog**: `recetadolce.com` (Spanish recipes, niches Postres/Carnes/Pescados/Ensaladas/Aperitivos). The user wants to add new blogs at will. Each new blog should:

1. Be added with **one command** that prompts only for credentials it can't synthesise (Pinterest login, Supabase keys, optionally domain registrar)
2. Have its **theme, branding, and categories generated automatically from the domain name alone** — the user types `keto-dinners.com` and the system produces the niche, color palette, logo, brand voice, category tree, Pinterest boards, and an initial keyword roadmap with zero further questions
3. Run **fully isolated** from existing blogs: separate Supabase project (or table prefix), separate Pinterest account(s), separate session dirs, separate keyword files, separate output dirs
4. Be **operationally identical** to recetadolce.com once provisioned — same `run_with_gemini.bat`, same Pinterest pin lifecycle, same quality gate, just scoped to that domain

Goal of this plan: produce a `domain_handle` partition layered above today's code such that **adding a domain is a 5-minute interactive wizard**, not a multi-day port.

---

## What "the system asks only for credentials it needs" looks like

Concrete UX for `python rankstein.py add-domain`:

```
Domain (e.g. keto-dinners.com): keto-dinners.com
Detected niche: low-carb / keto / dinner recipes
Detected language (from TLD + niche): English
Generating theme + branding (no questions)... done [3.4s]
Generating category tree from niche... done [Postres, Carnes, ... → Low-Carb Mains, Sheet-Pan, One-Pot, Keto Sides, Quick Dinners]
Generating initial 30-keyword roadmap... done

Now I need credentials I can't generate:
  Pinterest email for this blog: ___
  Pinterest password: ___
  Supabase project URL (or 'create' to spin up new project): ___
  Supabase service role key: ___
  Cloudflare/Vercel deploy hook URL (optional, press enter to skip): ___

Provisioning data/domains/keto-dinners/...
  - session dirs                ✓
  - SQLite intel db             ✓
  - keywords.md (30 entries)    ✓
  - branding (logo + palette)   ✓ [used Pollinations.ai for logo, programmatic palette]
  - GEMINI.md per-domain        ✓
  - .env.keto-dinners (chmod 600) ✓

First Pinterest login...
  Logging in as ____@____ ... ✓
  Session saved to data/domains/keto-dinners/sessions/uploader/

Smoke test: scrape sources for first keyword "easy keto sheet pan dinners"... ✓ (got 5 sources)

Done. Run 'python rankstein.py run --domain keto-dinners' to start the first content cycle.
```

Total interactive friction: **5 fields**. Everything else is auto-derived from the domain name.

---

## Architecture: the `Domain` object

A domain is the **top-level** unit; everything else hangs off it.

```python
@dataclass(frozen=True)
class Domain:
    handle: str                    # "keto-dinners" (slug from domain)
    domain: str                    # "keto-dinners.com"
    display_name: str              # "Keto Dinners" (auto-generated, editable)
    language: str                  # "en", "es", "fr" (TLD + niche heuristic)
    niche: str                     # "low-carb dinner recipes" (LLM-derived)
    
    # File partitions (all under data/domains/<handle>/)
    root: Path                     # data/domains/keto-dinners/
    sessions_dir: Path             # data/domains/keto-dinners/sessions/
    keywords_file: Path            # data/domains/keto-dinners/keywords.md
    db_path: Path                  # data/domains/keto-dinners/intel.db
    branding_dir: Path             # data/domains/keto-dinners/branding/
    output_dir: Path               # data/domains/keto-dinners/output/
    env_file: Path                 # data/domains/keto-dinners/.env (chmod 600)
    
    # Pinterest accounts (1..N, multi-account is a sub-system per domain)
    pinterest_accounts: tuple["PinterestAccount", ...]
    
    # Supabase
    supabase_url: str
    supabase_key_env: str          # name of env var holding the key, not the key itself
    supabase_table_prefix: str     # "" if dedicated project; "ketodinners_" if shared
    
    # Categories — keyword → category tree, generated from niche
    categories: tuple[str, ...]    # ("Low-Carb Mains", "Sheet-Pan", ...)
    boards_default: dict[str, str] # category → Pinterest board name
    
    # Branding
    primary_color: str             # "#3D5A40"
    accent_color: str              # "#D4AF37"
    brand_voice_file: Path         # data/domains/keto-dinners/brand_voice.md (LLM-generated)
    logo_path: Path                # data/domains/keto-dinners/branding/logo.png
    
    # Generation policies
    daily_pin_budget: int = 25     # warmup-friendly default
    cycle_count_per_day: int = 3
```

**Key invariant:** every existing tool in the system that today reads from `memory/keywords.md` or writes to `nanobanana-output/` or hits the Supabase `posts` table now takes a `domain_handle: str` argument and resolves it to a `Domain` object before doing anything. No tool ever has globals for paths or credentials.

---

## Auto-generation: from domain name to fully provisioned blog

This is the magic the user is asking for. Six derivations, all triggered by `add-domain`:

### 1. Niche + language detection (LLM, ~2 sec)

```
prompt: "Given the domain '{domain}', infer:
  - The niche in 5-10 words
  - The primary language (ISO 639-1)
  - Whether it's a recipe blog, lifestyle blog, etc.
Return JSON: {niche, language, vertical}"
```

Used to seed every downstream step. Failure → user is asked to fill in manually (the only fallback path that adds friction).

### 2. Category tree (LLM, ~3 sec)

```
prompt: "Generate a 5-7 category tree for a {vertical} blog about {niche} in {language}.
Categories should be Pinterest-friendly (people search them) and SEO-pillar-shaped.
Return JSON array of category names in {language}."
```

Output stored in `Domain.categories`. Used to bucket articles, generate Pinterest board names, and structure the keyword roadmap.

### 3. Keyword roadmap (LLM, ~10 sec)

```
prompt: "Generate 30 SEO-targetable recipe keywords for a {niche} blog, distributed across these categories: {categories}. Each keyword should:
  - Be 2-6 words, in {language}
  - Have search intent (people would Google it)
  - Mix high-volume and long-tail
Return JSON array of {keyword, category, priority: High|Medium} objects."
```

Output written as `data/domains/{handle}/keywords.md` in the same format as today's `memory/keywords.md` — the existing keyword tools work unchanged.

### 4. Brand voice document (LLM, ~5 sec)

```
prompt: "Write a brand voice guide for a {niche} blog in {language}. Include:
  - Tone (3-4 adjectives)
  - First-person markers in {language} (3 sample phrases)
  - Citation style (which authoritative bodies for {niche}: e.g. AESAN/EFSA for Spanish food, USDA/Mayo Clinic for US health)
  - 5-pillar style description matching 'Helpful Kitchen Peer' or appropriate equivalent
Return as markdown to be saved as brand_voice.md."
```

Saved to `data/domains/{handle}/brand_voice.md`. Loaded into the Gemini prompt at content-generation time (replaces today's hardcoded "Directo al Paladar" guidance).

### 5. Color palette + logo (programmatic + Pollinations, ~8 sec)

**Color palette:**
- 3-color palette derived semantically from niche keywords using a simple lookup (e.g. `keto/low-carb` → forest green + warm gold; `desserts` → pastel pink + cream; `seafood` → ocean blue + pearl white). Falls back to a niche-themed Coolors API hit if the lookup misses.

**Logo:**
- Pollinations.ai prompt: `"minimalist editorial logo for a {niche} blog called {display_name}, vector style, white background, {primary_color} accent, {accent_color} highlight, no text"`
- 1024x1024 PNG saved to `data/domains/{handle}/branding/logo.png`
- Validated by the same dimension/byte gate as hero images
- If Pollinations returns a sub-spec image, retry once with a simpler prompt; failing that, use a programmatic Pillow text-only fallback (NOT today's deleted gradient stub — a clean monogram with the brand colors).

**Theme tokens:**
- Written as `data/domains/{handle}/branding/theme.json`:
```json
{
  "primary": "#3D5A40",
  "accent": "#D4AF37",
  "neutral_bg": "#FAFAF8",
  "neutral_fg": "#1a1a1a",
  "font_heading": "Georgia",
  "font_body": "Arial",
  "logo_path": "branding/logo.png"
}
```
- Pinterest pin generator (`create_article_pin` today) reads this instead of the hardcoded `RECETA GENIAL` brand.

### 6. Pinterest board names (~deterministic, no LLM)

For each category, generate a board name via a templated mapping:
- Spanish recipe blog: `"{Category} {YEAR}"` (today's pattern)
- English keto blog: `"{Category} | Keto"` (vertical-specific suffix)

Stored in `Domain.boards_default`. Used at first pin upload to auto-create boards on Pinterest if they don't exist.

---

## File partitions: where everything lives

Today's flat layout:
```
memory/keywords.md                   ← keywords for recetadolce
data/sessions/pinterest_rida_v7/     ← Pinterest profile
nanobanana-output/                   ← hero images for ALL blogs (would conflict)
data/rankstein_mcp.log               ← single log
.env                                 ← single set of credentials
```

After:
```
data/domains/recetadolce/           ← migrated from current root
  ├── keywords.md
  ├── intel.db                        (SQLite, per-domain agent intel)
  ├── brand_voice.md
  ├── branding/
  │   ├── logo.png
  │   └── theme.json
  ├── sessions/
  │   ├── uploader/                   (Pinterest Firefox profile)
  │   ├── harvester/
  │   └── remasterer/
  ├── output/                         (hero images, pins, pre-EXIF working files)
  ├── logs/
  └── .env                            (PINTEREST_EMAIL, PINTEREST_PASSWORD, SUPABASE_*, chmod 600)

data/domains/keto-dinners/            (provisioned by `add-domain`)
  └── (same structure)

data/domains/_shared/                 (cross-domain caches)
  ├── healing_cache/                  (Playwright self-healing — keyed by selector hash, not domain)
  └── circuit_breakers.json
```

Backward compat for the existing recetadolce install: a one-shot migration script `scripts/migrate_to_domain_layout.py` moves today's `memory/keywords.md` → `data/domains/recetadolce/keywords.md`, today's `data/sessions/pinterest_rida_v7` → `data/domains/recetadolce/sessions/uploader`, etc. The existing `.env` is split into `data/domains/recetadolce/.env` (per-domain) plus a top-level `.env` keeping only system-wide (Gemini, Supabase shared client) values. Migration is idempotent and reversible (mv-only, no deletes).

---

## CLI: `python rankstein.py` becomes the front door

Today there's no top-level CLI — entry is via `run_with_gemini.bat`. This refactor introduces `rankstein.py` at the project root:

```
$ python rankstein.py --help
RankStein — Multi-domain autonomous SEO platform

Commands:
  add-domain <domain>          Provision a new blog with auto-generated branding
  list-domains                 Show all configured domains and their health
  remove-domain <handle>       Tear down a domain (with confirmation; archives data)
  run --domain <handle>        Run one content cycle for a domain
  run --all                    Run cycles for all domains (sequential, with niche routing)
  status [--domain <handle>]   Show cycle/pin/keyword stats per domain
  health                       System-wide health check
  
  # Per-domain ops (existing functionality, now domain-scoped)
  enqueue-pin --domain <h> <image> <title> ...
  pinterest-relogin --domain <h>
```

`run_with_gemini.bat` becomes a thin wrapper:
```bat
python rankstein.py run --domain ${RANKSTEIN_DOMAIN:-recetadolce}
```

---

## File-by-file diff

### 1. New: `rankstein/domain.py` (~250 LOC)

The `Domain` dataclass + `DomainRegistry` (analogous to the deferred `AccountRegistry` in `.planning/multi-account.md`, but at the higher domain level). Loads `data/domains/<handle>/domain.json`. Per-domain Pinterest accounts hang off `Domain.pinterest_accounts: tuple[PinterestAccount, ...]`.

### 2. New: `rankstein/provisioner.py` (~400 LOC)

The `add-domain` orchestrator. Six steps in order:
1. Niche/language detection (Gemini call)
2. Category generation (Gemini call)
3. Keyword roadmap generation (Gemini call)
4. Brand voice document generation (Gemini call)
5. Color palette + logo generation (lookup + Pollinations)
6. Credential collection (interactive prompts) + first Pinterest login + smoke test

Each step has a `--retry-step <n>` flag so a failure on step 3 doesn't waste the steps before. Idempotent — re-running on an existing domain re-validates without re-spending Gemini budget.

### 3. New: `rankstein/cli.py` (~200 LOC)

argparse front-door dispatching to `provisioner`, `domain`, `runner`, `status` modules.

### 4. New: `rankstein.py` (root, ~10 LOC)

Single-line shim: `from rankstein.cli import main; main()`.

### 5. Modified: `pinterest_automation/config.py`

Today globals like `SESSION_DIR = DATA_DIR / "sessions"` (line 18). After: those become functions taking a `Domain`:

```python
def session_dir_for(domain: Domain, role: str = "uploader") -> Path:
    return domain.sessions_dir / role
```

The flat `SESSION_DIR` constant stays as a deprecation alias pointing at `recetadolce`'s session dir during the migration window, then deleted in the next PR.

### 6. Modified: `rankstein_mcp_server.py`

Every tool gains an optional `domain_handle: str = ""` parameter. The default `""` resolves to the system's default domain (initially `recetadolce`). 27 tools touched — all of them go through a single `_resolve_domain(domain_handle)` helper at the top of each tool body, so the diff is mechanical.

The hardcoded `"https://recetadolce.com/{slug}"` at line 1857 becomes `f"https://{domain.domain}/{slug}"`.

`OUTPUT_DIR = PROJECT_ROOT / "nanobanana-output"` (line 69) becomes per-domain via `domain.output_dir`.

`KEYWORDS_FILE` (line 68) becomes per-domain via `domain.keywords_file`.

The 6 hardcoded category names in `validate_article_quality` (categories check) and the boards dict in `pinterest_automation/config.py:133-139` move into `domain.categories` and `domain.boards_default`, so adding a new vertical doesn't require a code edit.

Estimated diff: +180 / -90 LOC in `rankstein_mcp_server.py`.

### 7. Modified: `gemini_rankstein_prompt.md`

Currently embeds Spanish recipe domain knowledge directly (5-pillar style, AESAN/EFSA citations, fixed category list). After the refactor, the prompt becomes **domain-aware** by Jinja-templating the per-domain brand voice + categories at runtime. The MCP server gets a new tool `get_domain_prompt(domain_handle)` that returns the rendered prompt; `run_with_gemini.bat` calls it via stdin.

### 8. New: `tests/unit/test_domain_registry.py`, `test_provisioner.py` (mocked Gemini calls)

(Once `tests/` is restored — see "Open issues" below.)

### 9. Modified: `pinterest_automation/{rate_limiter,session_pool,supervisor}.py`

Same per-account partitioning planned in `.planning/multi-account.md`, but now nested: each `Domain` owns N `PinterestAccount` objects, the rate limiter dimensions become `(domain_handle, account_handle, operation)`. Multi-account becomes a within-domain concern.

### 10. New: `data/domains/recetadolce/` (migration target)

Created by `scripts/migrate_to_domain_layout.py` — see Migration section.

---

## Migration strategy

**Phase 0 — pre-work:**
- Restore `tests/` directory and fix CI red. See "Open issues".

**Phase 1 — refactor with one domain:**
- Land all the code changes. `recetadolce` becomes the default-named domain.
- Migration script moves today's flat layout into `data/domains/recetadolce/`.
- Run existing test suite: identical behavior, all green.
- Risk: low. The default-domain resolution path is a single `if not domain_handle: return registry.default` line.

**Phase 2 — add second domain end-to-end:**
- `python rankstein.py add-domain keto-dinners.com`
- Wizard runs, generates everything, prompts for 5 credential fields.
- Verification: `python rankstein.py run --domain keto-dinners` produces a published article + Pinterest pin on the new account, end to end, in one cycle.

**Phase 3 — concurrent multi-domain:**
- `python rankstein.py run --all` spawns one supervisor per domain (hub-and-spoke as in multi-account plan: each domain runs its own pipeline).
- Validation: 2 articles published simultaneously to 2 different Supabases + 2 different Pinterest accounts, no Firefox profile collisions, no rate-limiter cross-talk.

---

## Open issues — must resolve before code lands

1. **CI is red on main.** As of commit `c387228`:
   - `tests/` directory was deleted in `ff372a5` and `4a09c08` ("remove tests and articles"). CI's `pytest tests/unit` step fails immediately.
   - Ruff: 1025 lint errors, 491 auto-fixable; 65 files would be reformatted.
   - Type check (`mypy`) is `continue-on-error`, so it's not blocking but it's full of warnings.
   
   Recommendation: a pre-multi-domain "CI green" PR that:
     1. Restores `tests/` minimally (the image-gen tests I created earlier this session — they're already deleted from disk; need to re-author).
     2. Runs `ruff check --fix .` to auto-fix the 491 fixable issues.
     3. Runs `ruff format .` on the 65 files needing reformat.
     4. Reviews the remaining ~534 manual ruff issues; either fix them or add narrow `noqa` per-line with reasons.
   
   Estimated effort: ~half a day. **This is the right thing to fix first** so multi-domain lands on a green base.

2. **Supabase: dedicated project per domain or shared with table prefix?**
   Two options:
     - **Dedicated:** each domain gets its own Supabase project. Cleaner isolation, free tier covers most uses, but provisioning a new Supabase project programmatically requires a Supabase management API token (one extra credential).
     - **Shared:** one Supabase project, table-prefix namespacing (`recetadolce_posts`, `ketodinners_posts`). Simpler ops, but a leak in one blog's RLS exposes all blogs.
   Recommendation: **dedicated per domain**, with a fallback to shared if no management token is provided. The wizard asks "Supabase URL or 'create' to provision new" and the latter only works if `SUPABASE_MGMT_TOKEN` is set.

3. **Frontend deployment.** The blog itself (Next.js frontend) lives in `frontend/`. Multi-domain means each blog needs its own frontend deployment (Vercel/Cloudflare). Out of scope for this plan — provisioner ships a Vercel project token field for `keto-dinners.com` deploys, but the actual frontend code being multi-tenant is a separate workstream. Each domain's frontend can be a fork/clone of `frontend/` configured with that domain's Supabase + branding.

4. **Logo quality risk.** Pollinations-generated logos are inconsistent. The wizard should show the generated logo and ask "use this, regenerate, or upload your own?" — that's one extra question (4 → 5 friction points), but the user's request explicitly says "without asking" for theme assets. Accept the inconsistency or add the one question? **Recommendation: silent generation, but with a `python rankstein.py regenerate-logo --domain <h>` command for after-the-fact tweaks.** Honors the user's "without asking" requirement on first install.

5. **Gemini quota across domains.** N domains running concurrently = N× the daily 2.5-flash budget. The free-tier 15-hour cooldown will hit much faster. Per-domain `gemini_api_key` field in the roster lets each domain bring its own paid AI Studio key, sidestepping the shared quota cliff.

---

## Decisions to lock before execution

(Same format as multi-account.md — flag the ambiguities so we can move fast in implementation.)

1. **CI fix first?** Yes — Phase 0 above. Implementation starts after CI is green on main.
2. **Wizard auto-generates everything OR asks for confirmation on theme?** **Auto-generate silently** (per user instruction "without asking"). Provide post-install regeneration commands.
3. **Supabase per domain?** Dedicated project per domain with `create` keyword for auto-provisioning if `SUPABASE_MGMT_TOKEN` is set. Shared-project-with-prefix as fallback.
4. **Niche detection model.** `gemini-2.5-flash` (free, fast, accurate enough for niche/category/keyword generation). User can override with `--model` on `add-domain`.
5. **Default daily pin budget for new domains.** 25/day (Pinterest soft-flags new accounts above ~25/day). Roster field for manual override.
6. **Domain handle slugification rule.** `keto-dinners.com` → `keto-dinners` (strip TLD, lowercase, hyphens preserved). Collisions append `-2`, `-3`. Visible in all CLI output.

---

## Out of scope (flagged for future PRs)

- Frontend multi-tenancy (covered briefly in Open Issue #3)
- Image generation upgrades beyond Pollinations fallback (Nano Banana paid tier, ImagineFlux, etc.)
- Cross-domain analytics dashboard
- Domain transfer / archival workflow (only `remove-domain` planned, with auto-archive to `data/domains/_archive/`)
- Automatic backlink network between domains (delicate Google Sandbox issue, not touching)

---

## Critical files (touch list, summary)

**New:**
- `rankstein.py` (root shim)
- `rankstein/cli.py`
- `rankstein/domain.py`
- `rankstein/provisioner.py`
- `rankstein/branding.py` (color palette + logo generator)
- `rankstein/niche_detector.py` (Gemini-backed niche/category/keyword generators)
- `scripts/migrate_to_domain_layout.py`
- `data/domains/recetadolce/` (migration target)
- `tests/unit/test_domain_registry.py`, `tests/unit/test_provisioner.py`, `tests/unit/test_branding.py`

**Modified:**
- `rankstein_mcp_server.py` (every tool: `domain_handle` arg + `_resolve_domain` helper)
- `gemini_rankstein_prompt.md` (domain-aware via `get_domain_prompt` MCP tool)
- `pinterest_automation/{config,session_pool,supervisor,rate_limiter,job_queue,browser_utils}.py` (subsumes `.planning/multi-account.md`)
- `run_autonomous.py` → `python rankstein.py run` shim
- `run_with_gemini.bat` (calls `python rankstein.py run --domain $DOMAIN`)
- `MEMORY.md`, `STATUS.md`, `README.md` (multi-domain documentation)

Total estimated effort: **3-5 days of focused work.** Phase 0 (CI green) + Phase 1 (refactor) is the minimum viable PR; Phase 2 (wizard + first non-recetadolce domain) is the user-visible win.

---

## Status

Plan written. **Awaiting approval on the 6 locked decisions** before any code lands. Once approved, execution order is:

1. **Phase 0** — Restore tests + ruff fix + push to GitHub. Single commit, gets CI green. ~half a day.
2. **Phase 1** — Refactor to per-domain layout, default domain `recetadolce`, all behavior preserved. Single PR, ~2 days.
3. **Phase 2** — Provisioner CLI + first non-recetadolce domain end-to-end. Single PR, ~1.5 days.
4. **Phase 3** — Concurrent multi-domain runs (subsumes multi-account.md). Single PR, ~1 day.

Total: ~5 days to fully shipped multi-domain with one new blog running live.

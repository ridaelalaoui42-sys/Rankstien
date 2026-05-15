"""``add-domain`` orchestrator — the wizard that materializes a new blog.

Public entry point: ``provision_domain(domain, project_root, *, interactive=True)``.
Called by ``rankstein.cli`` for ``python rankstein.py add-domain <domain>``.

End-to-end flow (per ``.planning/multi-domain.md``):
  1. Detect niche / language / vertical / display_name from the domain name (LLM).
  2. Generate the category tree (LLM).
  3. Generate a 30-keyword starter roadmap (LLM).
  4. Generate the brand voice guide (LLM).
  5. Generate logo + color palette (Pollinations + lookup, no LLM).
  6. Collect credentials (interactive prompts) and write env values.
  7. Write ``data/domains/<handle>/domain.json`` manifest + ``keywords.md``
     + ``brand_voice.md`` + ``branding/{theme.json,logo.png}`` + ``.env``.
  8. Reload the DomainRegistry so the new domain is immediately addressable.

Idempotent: re-running on an existing handle re-validates and surfaces
``[skip]`` for steps that already have artifacts on disk. Failures in any
single step do NOT crash the orchestrator — each step has a fallback so a
partially-provisioned domain is still better than none.
"""

from __future__ import annotations

import getpass
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from rankstein.branding import provision_branding
from rankstein.domain import reload_registry
from rankstein.niche_detector import (
    Keyword,
    NicheInfo,
    detect_niche,
    generate_brand_voice,
    generate_categories,
    generate_keywords,
)
from rankstein.site_factory import SiteProjectResult, create_site_project

logger = logging.getLogger("rankstein.provisioner")


# ───────────────────────────────────────────────────────────────────────────
# Slug + handle utilities
# ───────────────────────────────────────────────────────────────────────────


_HANDLE_PATTERN = re.compile(r"[^a-z0-9-]+")


def domain_to_handle(domain: str) -> str:
    """``keto-dinners.com`` → ``keto-dinners``. Strips TLD, lowercases,
    keeps hyphens. Empty result becomes ``"unnamed"``."""
    stem = domain.split(".")[0].lower()
    cleaned = _HANDLE_PATTERN.sub("-", stem).strip("-")
    return cleaned or "unnamed"


def env_var_name(handle: str, suffix: str) -> str:
    """``keto-dinners`` + ``PINTEREST_EMAIL`` → ``PINTEREST_EMAIL_KETO_DINNERS``."""
    return f"{suffix}_{handle.upper().replace('-', '_')}"


# ───────────────────────────────────────────────────────────────────────────
# Result type
# ───────────────────────────────────────────────────────────────────────────


@dataclass
class ProvisionResult:
    handle: str
    domain: str
    domain_root: Path
    manifest_path: Path
    niche_info: NicheInfo
    categories: list[str]
    keyword_count: int
    fallbacks_used: list[str]
    branding: dict
    site_project: SiteProjectResult | None
    next_steps: list[str]


# ───────────────────────────────────────────────────────────────────────────
# Credential collection
# ───────────────────────────────────────────────────────────────────────────


@dataclass
class _Creds:
    pinterest_email: str
    pinterest_password: str
    supabase_url: str
    supabase_service_role_key: str


def _collect_credentials(*, interactive: bool, defaults: dict[str, str] | None = None) -> _Creds:
    """Prompt the user for the 4 credentials we cannot synthesize.

    When ``interactive=False`` (used in tests and in scripted runs), all
    fields default to empty strings. The provisioner's caller is then
    responsible for populating the per-domain ``.env`` after the fact.
    """
    if not interactive:
        return _Creds("", "", "", "")
    d = defaults or {}
    print("\nProvisioning credentials (press Enter to skip and fill later):")
    pe = input(f"  Pinterest email [{d.get('pinterest_email', '')}]: ").strip() or d.get(
        "pinterest_email", ""
    )
    pp = getpass.getpass("  Pinterest password (hidden): ") or d.get("pinterest_password", "")
    su = input(
        f"  Supabase URL [{d.get('supabase_url', 'https://<project>.supabase.co')}]: "
    ).strip() or d.get("supabase_url", "")
    sk = getpass.getpass("  Supabase service role key (hidden): ") or d.get("supabase_service_role_key", "")
    return _Creds(pe, pp, su, sk)


# ───────────────────────────────────────────────────────────────────────────
# File writers
# ───────────────────────────────────────────────────────────────────────────


def _write_keywords_md(path: Path, keywords: list[Keyword]) -> None:
    lines = [
        "# Keyword Roadmap",
        "",
        "| Keyword | Category | Cluster | Source | Priority | Status |",
        "|---|---|---|---|---|---|",
    ]
    for kw in keywords:
        lines.append(f"| {kw.keyword} | {kw.category} | — | Provisioner | {kw.priority} | Pending |")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_brand_voice(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_per_domain_env(path: Path, handle: str, creds: _Creds) -> None:
    """Write ``data/domains/<handle>/.env`` with env-var-NAMED keys that match
    what the manifest references. The values come from the credentials prompt;
    blanks are written as empty so the user can fill in later."""
    env_lines = [
        f"# Per-domain .env for handle: {handle}",
        "# Generated by rankstein.provisioner. Add to project .env or load via dotenv.",
        "",
        f"{env_var_name(handle, 'PINTEREST_EMAIL')}={creds.pinterest_email}",
        f"{env_var_name(handle, 'PINTEREST_PASSWORD')}={creds.pinterest_password}",
        f"{env_var_name(handle, 'SUPABASE_URL')}={creds.supabase_url}",
        f"{env_var_name(handle, 'SUPABASE_SERVICE_ROLE_KEY')}={creds.supabase_service_role_key}",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(env_lines), encoding="utf-8")
    # File-mode-restrict on Unix; chmod is no-op on Windows.
    try:
        path.chmod(0o600)
    except (OSError, NotImplementedError):
        pass


def _write_manifest(
    path: Path,
    handle: str,
    domain: str,
    niche_info: NicheInfo,
    categories: list[str],
    branding: dict,
) -> None:
    boards_default = {cat: f"{cat} Pins" for cat in categories}
    boards_default["_default"] = f"{niche_info.display_name} Pins"
    manifest = {
        "handle": handle,
        "domain": domain,
        "display_name": niche_info.display_name,
        "language": niche_info.language,
        "niche": niche_info.niche,
        "vertical": niche_info.vertical,
        "categories": categories,
        "boards_default": boards_default,
        "primary_color": branding.get("primary_color", "#D4AF37"),
        "accent_color": branding.get("accent_color", "#1a1a1a"),
        "brand_name_short": f"{niche_info.display_name.upper()} | 2026",
        "cta_text": _cta_for(niche_info.language),
        "daily_pin_budget": 25,
        "pinterest_email_env": env_var_name(handle, "PINTEREST_EMAIL"),
        "pinterest_password_env": env_var_name(handle, "PINTEREST_PASSWORD"),
        "supabase_url_env": env_var_name(handle, "SUPABASE_URL"),
        "supabase_key_env": env_var_name(handle, "SUPABASE_SERVICE_ROLE_KEY"),
        "branding_dir": "branding",
        "keywords_file": "keywords.md",
        "sessions_dir": "sessions",
        "output_dir": "output",
        "schema_version": 1,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def _cta_for(language: str) -> str:
    return {
        "es": "TOCA PARA VER LA RECETA",
        "en": "TAP FOR THE RECIPE",
        "fr": "VOIR LA RECETTE",
        "de": "REZEPT ANSEHEN",
        "it": "VEDI LA RICETTA",
    }.get((language or "en").lower(), "TAP FOR MORE")


# ───────────────────────────────────────────────────────────────────────────
# Top-level orchestrator
# ───────────────────────────────────────────────────────────────────────────


def provision_domain(
    domain: str,
    project_root: Path,
    *,
    interactive: bool = True,
    skip_branding: bool = False,
    keyword_count: int = 30,
    category_count: int = 6,
    interactive_creds_defaults: dict[str, str] | None = None,
    clone_site: bool = False,
    template_path: Path | None = None,
    projects_root: Path | None = None,
    overwrite_site: bool = False,
) -> ProvisionResult:
    """Run the wizard end-to-end for the given domain. Returns a result
    object describing what was created and which steps used a fallback."""
    handle = domain_to_handle(domain)
    domain_root = project_root / "data" / "domains" / handle
    domain_root.mkdir(parents=True, exist_ok=True)

    fallbacks: list[str] = []
    print(f"\nProvisioning {domain} → handle '{handle}' at {domain_root}")

    # Step 1 — niche detection
    print("  [1/6] Detecting niche...", end=" ", flush=True)
    niche_info = detect_niche(domain)
    print(f"niche='{niche_info.niche}' lang={niche_info.language} display='{niche_info.display_name}'")

    # Step 2 — categories
    print("  [2/6] Generating categories...", end=" ", flush=True)
    categories = generate_categories(niche_info.niche, niche_info.language, count=category_count)
    print(f"{len(categories)}: {categories}")

    # Step 3 — keyword roadmap
    print(f"  [3/6] Generating {keyword_count}-keyword roadmap...", end=" ", flush=True)
    keywords = generate_keywords(niche_info.niche, categories, niche_info.language, count=keyword_count)
    print(f"{len(keywords)} keywords")
    if len(keywords) < keyword_count // 2:
        fallbacks.append("keywords")

    # Step 4 — brand voice
    print("  [4/6] Generating brand voice document...", end=" ", flush=True)
    brand_voice_md = generate_brand_voice(niche_info.niche, niche_info.language, niche_info.display_name)
    if "fallback template" in brand_voice_md:
        fallbacks.append("brand_voice")
    print("done")

    # Step 5 — branding (palette + logo + theme.json)
    branding_dir = domain_root / "branding"
    if skip_branding:
        print("  [5/6] Branding... [skipped per flag]")
        branding = {"primary_color": "#D4AF37", "accent_color": "#1a1a1a", "logo_path": "", "theme_path": ""}
    else:
        print("  [5/6] Generating logo + theme...", end=" ", flush=True)
        branding = provision_branding(
            handle=handle,
            niche=niche_info.niche,
            display_name=niche_info.display_name,
            branding_dir=branding_dir,
        )
        print(f"primary={branding['primary_color']} accent={branding['accent_color']}")

    # Step 6 — credentials + manifest + filesystem layout
    print("  [6/6] Collecting credentials & writing manifest...")
    creds = _collect_credentials(interactive=interactive, defaults=interactive_creds_defaults)

    keywords_path = domain_root / "keywords.md"
    brand_voice_path = domain_root / "brand_voice.md"
    env_path = domain_root / ".env"
    manifest_path = domain_root / "domain.json"
    sessions_dir = domain_root / "sessions"
    output_dir = domain_root / "output"

    _write_keywords_md(keywords_path, keywords)
    _write_brand_voice(brand_voice_path, brand_voice_md)
    _write_per_domain_env(env_path, handle, creds)
    _write_manifest(manifest_path, handle, domain, niche_info, categories, branding)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Cause subsequent get_registry().get(handle) calls to find the new domain
    reload_registry()

    site_project: SiteProjectResult | None = None
    if clone_site:
        print("  [site] Cloning and rebranding site project...", end=" ", flush=True)
        site_project = create_site_project(
            handle=handle,
            domain=domain,
            niche_info=niche_info,
            categories=categories,
            branding=branding,
            project_root=project_root,
            domain_root=domain_root,
            template_path=template_path,
            projects_root=projects_root,
            overwrite=overwrite_site,
        )
        print(f"done: {site_project.project_path}")

    next_steps = _format_next_steps(handle, env_path, creds, site_project)
    return ProvisionResult(
        handle=handle,
        domain=domain,
        domain_root=domain_root,
        manifest_path=manifest_path,
        niche_info=niche_info,
        categories=categories,
        keyword_count=len(keywords),
        fallbacks_used=fallbacks,
        branding=branding,
        site_project=site_project,
        next_steps=next_steps,
    )


def _format_next_steps(
    handle: str,
    env_path: Path,
    creds: _Creds,
    site_project: SiteProjectResult | None = None,
) -> list[str]:
    """Build a human-readable post-install checklist."""
    steps: list[str] = []
    missing: list[str] = []
    if not creds.pinterest_email:
        missing.append("PINTEREST_EMAIL")
    if not creds.pinterest_password:
        missing.append("PINTEREST_PASSWORD")
    if not creds.supabase_service_role_key:
        missing.append("SUPABASE_SERVICE_ROLE_KEY")
    if missing:
        steps.append(
            f"Fill the {len(missing)} missing credential(s) in {env_path} "
            f"(or copy them into project .env): {', '.join(missing)}"
        )
    steps.append(
        f"Run 'gemini -p \"login to pinterest\" --yolo' once after credentials "
        f"are in place — the first login persists the cookie session under "
        f"data/domains/{handle}/sessions/."
    )
    steps.append(
        f"Test: run one cycle with 'python rankstein.py run --domain {handle}' "
        f"(once the CLI lands in Phase 2 follow-up)."
    )
    if site_project:
        steps.append(
            f"Review generated site project at {site_project.project_path}; copy "
            f"{site_project.env_example_path.name} to .env.local after Supabase is ready."
        )
        steps.append(
            f"Provision DB from the site folder with "
            f"'powershell -ExecutionPolicy Bypass -File {site_project.supabase_script_path} "
            f"-ProjectRef <ref>'."
        )
        steps.append(
            f"Deploy from the site folder with "
            f"'powershell -ExecutionPolicy Bypass -File {site_project.deploy_script_path} -Production'."
        )
    return steps

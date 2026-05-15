"""Site factory for turning a RankStein domain manifest into a blog project.

The domain provisioner already knows how to infer niche, categories, keywords,
brand voice, and visual tokens from a single domain name. This module wires the
next step: create a sanitized Next.js project from the RecetaDolce template and
drop the deploy/database assets needed to make that project shippable.

No live Vercel or Supabase mutation happens here. The generated project gets
scripts for those steps so operators can run them once credentials and account
context are ready.
"""

from __future__ import annotations

import fnmatch
import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rankstein.niche_detector import NicheInfo

TEXT_EXTENSIONS = {
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".ts",
    ".tsx",
    ".txt",
    ".webmanifest",
    ".xml",
    ".yml",
    ".yaml",
}

SKIP_DIRECTORIES = {
    ".cache",
    ".git",
    ".next",
    ".turbo",
    ".vercel",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "out",
    "scripts",
}

SKIP_FILES = {
    ".env",
    ".env.local",
    ".env.development.local",
    ".env.production.local",
    ".env.test.local",
    "deploy_log.txt",
    "models.json",
    "rebrand.js",
    "test_write.txt",
}

LEGACY_SUPABASE_HOSTS = (
    "hokcljsrrnjxzgdhjice.supabase.co",
    "xjvmnmfczvwkjiasirsl.supabase.co",
)

ROOT_ONLY_SKIP_PATTERNS = (
    "check_*.js",
    "clean_*.js",
    "inspect_*.js",
    "test_*.js",
    "update_categories.js",
)


@dataclass(frozen=True)
class SiteProjectResult:
    """Artifacts created for a generated blog project."""

    handle: str
    domain: str
    project_path: Path
    blueprint_path: Path
    env_example_path: Path
    supabase_migration_path: Path
    deploy_script_path: Path
    supabase_script_path: Path
    launch_prompt_path: Path
    copied_from: Path

    def to_public_dict(self) -> dict[str, str]:
        return {
            "handle": self.handle,
            "domain": self.domain,
            "project_path": str(self.project_path),
            "blueprint_path": str(self.blueprint_path),
            "env_example_path": str(self.env_example_path),
            "supabase_migration_path": str(self.supabase_migration_path),
            "deploy_script_path": str(self.deploy_script_path),
            "supabase_script_path": str(self.supabase_script_path),
            "launch_prompt_path": str(self.launch_prompt_path),
            "copied_from": str(self.copied_from),
        }


def default_template_path(project_root: Path) -> Path:
    """Default to the sibling RecetaDolce project next to RankStein."""
    return project_root.resolve().parent / "recetadolce"


def default_projects_root(project_root: Path) -> Path:
    """New blog projects sit next to RankStein and RecetaDolce by default."""
    return project_root.resolve().parent


def create_site_project(
    *,
    handle: str,
    domain: str,
    niche_info: NicheInfo,
    categories: list[str],
    branding: dict[str, Any],
    project_root: Path,
    domain_root: Path,
    template_path: Path | None = None,
    projects_root: Path | None = None,
    overwrite: bool = False,
) -> SiteProjectResult:
    """Create a sanitized, rebranded site project for a provisioned domain."""
    project_root = project_root.resolve()
    domain_root = domain_root.resolve()
    template = (template_path or default_template_path(project_root)).resolve()
    root = (projects_root or default_projects_root(project_root)).resolve()
    project_path = (root / handle).resolve()

    if not template.is_dir():
        raise FileNotFoundError(f"Template project not found: {template}")

    _copy_template(template, project_path, projects_root=root, handle=handle, overwrite=overwrite)

    public_branding = _install_public_branding(project_path, domain_root, branding)
    blueprint = _build_blueprint(
        handle=handle,
        domain=domain,
        niche_info=niche_info,
        categories=categories,
        branding=branding,
        public_branding=public_branding,
        template=template,
        project_path=project_path,
    )

    _apply_rebrand(project_path, blueprint)
    _patch_next_config(project_path)
    _write_project_package_metadata(project_path, handle, niche_info.display_name)
    _write_site_config(project_path, blueprint)
    _write_manifest(project_path / "public" / "site.webmanifest", blueprint)
    env_example_path = _write_env_example(project_path, blueprint)
    supabase_migration_path = _write_supabase_migration(project_path, project_root, blueprint)
    deploy_script_path = _write_deploy_script(project_path, blueprint)
    supabase_script_path = _write_supabase_script(project_path, blueprint)
    blueprint_path = _write_blueprint(project_path, blueprint)
    _write_domain_blueprint(domain_root, blueprint)
    launch_prompt_path = _write_launch_prompt(domain_root, blueprint)
    _patch_gitignore(project_path)

    return SiteProjectResult(
        handle=handle,
        domain=domain,
        project_path=project_path,
        blueprint_path=blueprint_path,
        env_example_path=env_example_path,
        supabase_migration_path=supabase_migration_path,
        deploy_script_path=deploy_script_path,
        supabase_script_path=supabase_script_path,
        launch_prompt_path=launch_prompt_path,
        copied_from=template,
    )


def _copy_template(
    template: Path,
    project_path: Path,
    *,
    projects_root: Path,
    handle: str,
    overwrite: bool,
) -> None:
    if project_path.exists():
        if not overwrite:
            raise FileExistsError(
                f"Target site project already exists: {project_path}. "
                "Pass overwrite=True or choose another projects root."
            )
        _assert_safe_to_replace(project_path, projects_root, handle)
        shutil.rmtree(project_path)

    shutil.copytree(template, project_path, ignore=_ignore_template_items(template))


def _assert_safe_to_replace(project_path: Path, projects_root: Path, handle: str) -> None:
    resolved = project_path.resolve()
    root = projects_root.resolve()
    if resolved.parent != root or resolved.name != handle or handle in {"", ".", ".."}:
        raise RuntimeError(f"Refusing to replace unsafe generated project path: {resolved}")


def _ignore_template_items(template: Path):
    def _ignore(src: str, names: list[str]) -> set[str]:
        src_path = Path(src)
        rel = src_path.resolve().relative_to(template.resolve())
        ignored: set[str] = set()
        is_root = rel == Path(".")
        for name in names:
            if name in SKIP_DIRECTORIES or name in SKIP_FILES:
                ignored.add(name)
                continue
            if name.startswith(".env"):
                ignored.add(name)
                continue
            if is_root and any(fnmatch.fnmatch(name, pattern) for pattern in ROOT_ONLY_SKIP_PATTERNS):
                ignored.add(name)
        return ignored

    return _ignore


def _install_public_branding(project_path: Path, domain_root: Path, branding: dict[str, Any]) -> dict[str, str]:
    public = project_path / "public"
    public.mkdir(parents=True, exist_ok=True)
    installed: dict[str, str] = {}

    logo_source = Path(str(branding.get("logo_path") or domain_root / "branding" / "logo.png"))
    if logo_source.is_file():
        for filename in ("logo.png", "favicon.png", "apple-touch-icon.png"):
            target = public / filename
            shutil.copy2(logo_source, target)
            installed[filename] = f"/{filename}"
    return installed


def _build_blueprint(
    *,
    handle: str,
    domain: str,
    niche_info: NicheInfo,
    categories: list[str],
    branding: dict[str, Any],
    public_branding: dict[str, str],
    template: Path,
    project_path: Path,
) -> dict[str, Any]:
    primary = str(branding.get("primary_color") or "#D4AF37")
    accent = str(branding.get("accent_color") or "#1a1a1a")
    language = (niche_info.language or "en").lower()
    site_description = _site_description(niche_info.niche, language)
    base_url = f"https://{domain}"

    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "generated_by": "rankstein.site_factory",
        "handle": handle,
        "domain": domain,
        "base_url": base_url,
        "display_name": niche_info.display_name,
        "language": language,
        "vertical": niche_info.vertical,
        "niche": niche_info.niche,
        "site_description": site_description,
        "author_name": f"{niche_info.display_name} Editorial",
        "contact_email": f"hello@{domain}",
        "package_name": _package_name(handle),
        "template_path": str(template),
        "project_path": str(project_path),
        "categories": categories,
        "branding": {
            "primary": primary,
            "primary_light": _mix_hex(primary, "#ffffff", 0.68),
            "primary_deep": _mix_hex(primary, "#000000", 0.35),
            "accent": accent,
            "accent_light": _mix_hex(accent, "#ffffff", 0.72),
            "neutral_bg": str(branding.get("neutral_bg") or "#FAFAF8"),
            "neutral_fg": str(branding.get("neutral_fg") or "#1a1a1a"),
            "public_assets": public_branding,
        },
        "automation": {
            "rankstein_run": f"python rankstein.py run --domain {handle} --keywords 3 --workers 1",
            "rankstein_trends": f"python rankstein.py trends --domain {handle} --limit 10",
            "vercel_deploy_script": "scripts/rankstein-deploy.ps1",
            "supabase_setup_script": "scripts/rankstein-supabase.ps1",
        },
    }


def _site_description(niche: str, language: str) -> str:
    if language == "es":
        return f"Recetas y guias de {niche} con investigacion, claridad editorial y resultados fiables."
    return f"Research-backed {niche} guides with clear steps, editorial polish, and reliable results."


def _package_name(handle: str) -> str:
    cleaned = re.sub(r"[^a-z0-9-]+", "-", handle.lower()).strip("-")
    return cleaned or "rankstein-blog"


def _apply_rebrand(project_path: Path, blueprint: dict[str, Any]) -> None:
    replacements = {
        "RecetaDolce.com": blueprint["domain"],
        "recetadolce.com": blueprint["domain"].lower(),
        "RecetaDolce Studio": f"{blueprint['display_name']} Studio",
        "RecetaDolce Editorial": blueprint["author_name"],
        "RecetaDolce": blueprint["display_name"],
        "Receta Dolce": blueprint["display_name"],
        "recetasdolce": blueprint["package_name"],
        "Isabella Dolce": blueprint["author_name"],
        "Isabella D.": blueprint["author_name"],
        "info@recetadolce.com": blueprint["contact_email"],
        "hola@recetadolce.com": blueprint["contact_email"],
    }

    for path in _iter_text_files(project_path):
        text = path.read_text(encoding="utf-8", errors="ignore")
        original = text
        text = _replace_preserving_cloudinary_urls(text, replacements)
        if path.name == "globals.css":
            text = _patch_css_tokens(text, blueprint)
        if text != original:
            path.write_text(text, encoding="utf-8")


def _iter_text_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRECTORIES for part in path.parts):
            continue
        if path.suffix.lower() in TEXT_EXTENSIONS or path.name in {"package.json", "package-lock.json"}:
            yield path


def _replace_preserving_cloudinary_urls(text: str, replacements: dict[str, str]) -> str:
    protected: list[str] = []

    def _mask(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"__RANKSTEIN_URL_{len(protected) - 1}__"

    text = re.sub(r"https://res\.cloudinary\.com/[^\s'\"<>)]*", _mask, text)
    for old, new in replacements.items():
        text = text.replace(old, new)
    for host in LEGACY_SUPABASE_HOSTS:
        text = text.replace(f"https://{host}", "https://supabase-project-ref.supabase.co")
        text = text.replace(host, "supabase-project-ref.supabase.co")
    for index, url in enumerate(protected):
        text = text.replace(f"__RANKSTEIN_URL_{index}__", url)
    return text


def _patch_next_config(project_path: Path) -> None:
    path = project_path / "next.config.ts"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8", errors="ignore")
    if "const supabaseImageHostname" not in text:
        text = text.replace(
            'import path from "path";',
            """import path from "path";

const supabaseImageHostname = (() => {
  try {
    return new URL(process.env.NEXT_PUBLIC_SUPABASE_URL || "https://supabase-project-ref.supabase.co").hostname;
  } catch {
    return "supabase-project-ref.supabase.co";
  }
})();""",
        )
    text = re.sub(
        r"(?://[^\n]*Supabase[^\n]*\n\s*)?\{\s*protocol:\s*'https',\s*hostname:\s*'supabase-project-ref\.supabase\.co',\s*pathname:\s*'/storage/v1/object/public/\*\*',\s*\},\s*(?://[^\n]*Supabase[^\n]*\n\s*)?\{\s*protocol:\s*'https',\s*hostname:\s*'supabase-project-ref\.supabase\.co',\s*pathname:\s*'/storage/v1/object/public/\*\*',\s*\},",
        """{
        protocol: 'https',
        hostname: supabaseImageHostname,
        pathname: '/storage/v1/object/public/**',
      },""",
        text,
        flags=re.DOTALL,
    )
    path.write_text(text, encoding="utf-8")


def _patch_css_tokens(text: str, blueprint: dict[str, Any]) -> str:
    colors = blueprint["branding"]
    replacements = {
        "--color-brand-dolce": colors["primary"],
        "--color-brand-dolce-light": colors["primary_light"],
        "--color-brand-dolce-deep": colors["primary_deep"],
        "--color-brand-red": colors["accent"],
        "--color-gold-accent": colors["accent"],
        "--color-gold-light": colors["accent_light"],
        "--color-ink": colors["neutral_fg"],
    }
    for token, value in replacements.items():
        text = re.sub(
            rf"({re.escape(token)}:\s*)#[0-9A-Fa-f]{{3,8}}(\s*;)",
            rf"\g<1>{value}\2",
            text,
        )
    rgb = _hex_to_rgb(colors["primary"])
    if rgb:
        text = re.sub(
            r"(--selection-bg:\s*)rgba\([^)]+\)(\s*;)",
            rf"\g<1>rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, 0.18)\2",
            text,
        )
    return text


def _write_project_package_metadata(project_path: Path, handle: str, display_name: str) -> None:
    for filename in ("package.json", "package-lock.json"):
        path = project_path / filename
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        data["name"] = _package_name(handle)
        if isinstance(data.get("packages"), dict) and isinstance(data["packages"].get(""), dict):
            data["packages"][""]["name"] = _package_name(handle)
        data.setdefault("rankstein", {})["display_name"] = display_name
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _write_site_config(project_path: Path, blueprint: dict[str, Any]) -> None:
    config = {
        "handle": blueprint["handle"],
        "domain": blueprint["domain"],
        "baseUrl": blueprint["base_url"],
        "siteName": blueprint["display_name"],
        "siteDescription": blueprint["site_description"],
        "language": blueprint["language"],
        "niche": blueprint["niche"],
        "authorName": blueprint["author_name"],
        "categories": blueprint["categories"],
        "colors": blueprint["branding"],
    }
    target = project_path / "lib" / "rankstein-site.ts"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "export const ranksteinSite = "
        + json.dumps(config, indent=2, ensure_ascii=False)
        + " as const;\n",
        encoding="utf-8",
    )


def _write_manifest(path: Path, blueprint: dict[str, Any]) -> None:
    manifest = {
        "name": blueprint["display_name"],
        "short_name": blueprint["display_name"][:24],
        "icons": [
            {
                "src": "/favicon.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            }
        ],
        "theme_color": blueprint["branding"]["primary"],
        "background_color": blueprint["branding"]["neutral_bg"],
        "display": "standalone",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_env_example(project_path: Path, blueprint: dict[str, Any]) -> Path:
    target = project_path / ".env.local.example"
    lines = [
        f"# Generated by RankStein for {blueprint['domain']}",
        f"NEXT_PUBLIC_BASE_URL={blueprint['base_url']}",
        f"NEXT_PUBLIC_SITE_NAME={blueprint['display_name']}",
        f"RANKSTEIN_DOMAIN_HANDLE={blueprint['handle']}",
        "",
        "# Fill these after creating/linking the Supabase project.",
        "NEXT_PUBLIC_SUPABASE_URL=https://<project-ref>.supabase.co",
        "NEXT_PUBLIC_SUPABASE_ANON_KEY=",
        "SUPABASE_SERVICE_ROLE_KEY=",
        "",
        "# Optional site integrations.",
        "NEXT_PUBLIC_GA_ID=",
        "ADMIN_PASSWORD=",
        "",
    ]
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def _write_supabase_migration(project_path: Path, rankstein_root: Path, blueprint: dict[str, Any]) -> Path:
    schema_source = rankstein_root / "frontend" / "schema.sql"
    if schema_source.is_file():
        schema = schema_source.read_text(encoding="utf-8")
    else:
        schema = _fallback_schema()

    schema = schema.replace("RecetaDolce", blueprint["display_name"])
    schema = schema.replace("recetadolce.com", blueprint["domain"].lower())
    schema = schema.replace(
        "Autenticas recetas de cocina espanola con un toque editorial.",
        blueprint["site_description"],
    )
    schema = schema.replace(
        "AutÃ©nticas recetas de cocina espaÃ±ola con un toque editorial.",
        blueprint["site_description"],
    )

    target = project_path / "supabase" / "migrations" / "0001_rankstein_blog_schema.sql"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(schema, encoding="utf-8")
    return target


def _fallback_schema() -> str:
    return """CREATE TABLE IF NOT EXISTS posts (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  created_at TIMESTAMPTZ DEFAULT now(),
  title TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  content TEXT NOT NULL,
  status TEXT DEFAULT 'draft'
);

CREATE TABLE IF NOT EXISTS settings (
  id TEXT PRIMARY KEY DEFAULT 'global',
  site_name TEXT,
  site_description TEXT
);
"""


def _write_deploy_script(project_path: Path, blueprint: dict[str, Any]) -> Path:
    target = project_path / "scripts" / "rankstein-deploy.ps1"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"""param(
  [switch]$Production
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command vercel -ErrorAction SilentlyContinue)) {{
  throw "Vercel CLI is not installed. Install it with your preferred package manager, then rerun this script."
}}

npm install
npm run build
vercel link --yes

$deployArgs = @("deploy")
if ($Production) {{
  $deployArgs += "--prod"
}}

vercel @deployArgs

Write-Host "RankStein project deployed for {blueprint['domain']}."
Write-Host "Next: run python rankstein.py run --domain {blueprint['handle']} from the RankStein workspace."
""",
        encoding="utf-8",
    )
    return target


def _write_supabase_script(project_path: Path, blueprint: dict[str, Any]) -> Path:
    target = project_path / "scripts" / "rankstein-supabase.ps1"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"""param(
  [Parameter(Mandatory=$true)][string]$ProjectRef
)

$ErrorActionPreference = "Stop"

Write-Host "Linking Supabase project $ProjectRef for {blueprint['domain']}..."
npx supabase link --project-ref $ProjectRef
npx supabase db push

Write-Host "Now copy Supabase URL, anon key, and service role key into .env.local and Vercel env vars."
""",
        encoding="utf-8",
    )
    return target


def _write_blueprint(project_path: Path, blueprint: dict[str, Any]) -> Path:
    target = project_path / "rankstein.site.json"
    target.write_text(json.dumps(blueprint, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def _write_domain_blueprint(domain_root: Path, blueprint: dict[str, Any]) -> Path:
    target = domain_root / "site_blueprint.json"
    target.write_text(json.dumps(blueprint, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def _write_launch_prompt(domain_root: Path, blueprint: dict[str, Any]) -> Path:
    target = domain_root / "upcoming_domain_system_prompt.md"
    target.write_text(_render_launch_prompt(blueprint), encoding="utf-8")
    return target


def _render_launch_prompt(blueprint: dict[str, Any]) -> str:
    return f"""# RankStein Upcoming Domain System Prompt

You are RankStein launching a new autonomous blog from one domain name.

Domain handle: `{blueprint['handle']}`
Public domain: `{blueprint['domain']}`
Brand: `{blueprint['display_name']}`
Language: `{blueprint['language']}`
Niche: `{blueprint['niche']}`
Categories: {", ".join(blueprint['categories'])}

## Operating Contract

1. Use the domain manifest, `site_blueprint.json`, `brand_voice.md`, and `keywords.md` as source of truth.
2. Do not reuse RecetaDolce names, URLs, Pinterest boards, Supabase targets, or author identity.
3. Run trend research first, then seed campaigns, then publish only verified articles.
4. Every article, hero image, OG image, and Pinterest pin must carry `domain_handle={blueprint['handle']}`.
5. Use the generated site project at `{blueprint['project_path']}` for Vercel deployment work.
6. Use Supabase only after the new project credentials have been written to the domain env and Vercel env.
7. Mark keywords `Live` only after Supabase publish, image upload, Pinterest upload, and pin proof all succeed.

## Launch Commands

```powershell
python rankstein.py trends --domain {blueprint['handle']} --limit 10
python rankstein.py run --domain {blueprint['handle']} --keywords 3 --workers 1
```
"""


def _patch_gitignore(project_path: Path) -> None:
    target = project_path / ".gitignore"
    if not target.is_file():
        return
    text = target.read_text(encoding="utf-8", errors="ignore")
    marker = "# RankStein generated project assets"
    if marker in text:
        return
    text = text.rstrip() + f"""

{marker}
!scripts/
!scripts/rankstein-*.ps1
!supabase/
!supabase/**
!supabase/migrations/
!supabase/migrations/*.sql
!rankstein.site.json
!.env.local.example
"""
    target.write_text(text + "\n", encoding="utf-8")


def _mix_hex(a: str, b: str, amount_b: float) -> str:
    rgb_a = _hex_to_rgb(a)
    rgb_b = _hex_to_rgb(b)
    if rgb_a is None or rgb_b is None:
        return a if _hex_to_rgb(a) else "#1a1a1a"
    mixed = tuple(round((1 - amount_b) * rgb_a[i] + amount_b * rgb_b[i]) for i in range(3))
    return f"#{mixed[0]:02X}{mixed[1]:02X}{mixed[2]:02X}"


def _hex_to_rgb(value: str) -> tuple[int, int, int] | None:
    cleaned = value.strip().lstrip("#")
    if len(cleaned) == 3:
        cleaned = "".join(ch * 2 for ch in cleaned)
    if len(cleaned) != 6 or not re.fullmatch(r"[0-9A-Fa-f]{6}", cleaned):
        return None
    return tuple(int(cleaned[i : i + 2], 16) for i in (0, 2, 4))


def dataclass_to_jsonable(result: SiteProjectResult) -> dict[str, str]:
    """Return a JSON-safe dict for CLI output and tests."""
    return {key: str(value) for key, value in asdict(result).items()}

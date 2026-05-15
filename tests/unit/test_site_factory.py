from __future__ import annotations

import json
from pathlib import Path

import pytest

from rankstein.niche_detector import NicheInfo
from rankstein.site_factory import create_site_project


def _write_template(root: Path) -> None:
    (root / "app").mkdir(parents=True)
    (root / "lib").mkdir()
    (root / "public").mkdir()
    (root / "scripts").mkdir()
    (root / "node_modules").mkdir()
    (root / ".vercel").mkdir()

    (root / "app" / "layout.tsx").write_text(
        """
const BASE_URL = 'https://RecetaDolce.com';
const brand = 'RecetaDolce';
const author = 'Isabella Dolce';
const image = 'https://res.cloudinary.com/demo/image/upload/v1/RecetaDolce/hero.jpg';
""",
        encoding="utf-8",
    )
    (root / "app" / "globals.css").write_text(
        """
@theme inline {
  --color-brand-dolce: #C8102E;
  --color-brand-dolce-light: #FFCCD5;
  --color-brand-dolce-deep: #8B0000;
  --color-brand-red: #B22222;
  --color-gold-accent: #D4AF37;
  --color-gold-light: #F9E79F;
  --color-ink: #2D0A14;
}
:root { --selection-bg: rgba(255, 77, 109, 0.2); }
""",
        encoding="utf-8",
    )
    (root / "public" / "site.webmanifest").write_text(
        json.dumps({"name": "RecetaDolce", "theme_color": "#A4133C"}),
        encoding="utf-8",
    )
    (root / "package.json").write_text(
        json.dumps({"name": "recetasdolce", "scripts": {"build": "next build"}}),
        encoding="utf-8",
    )
    (root / "package-lock.json").write_text(
        json.dumps({"name": "recetasdolce", "packages": {"": {"name": "recetasdolce"}}}),
        encoding="utf-8",
    )
    (root / ".gitignore").write_text("node_modules/\n*.sql\nscripts/\n", encoding="utf-8")
    (root / ".env.local").write_text("SUPABASE_SERVICE_ROLE_KEY=secret\n", encoding="utf-8")
    (root / "check_tables.js").write_text("const key = 'secret';\n", encoding="utf-8")
    (root / "scripts" / "legacy_publish.py").write_text("SITE_NAME = 'RecetaDolce'\n", encoding="utf-8")
    (root / "node_modules" / "ignored.txt").write_text("ignored\n", encoding="utf-8")
    (root / ".vercel" / "project.json").write_text("{}", encoding="utf-8")


@pytest.mark.unit
def test_create_site_project_sanitizes_and_rebrands(tmp_path: Path) -> None:
    template = tmp_path / "recetadolce"
    project_root = tmp_path / "Rankstein"
    projects_root = tmp_path / "sites"
    domain_root = project_root / "data" / "domains" / "keto-dinners"
    logo = domain_root / "branding" / "logo.png"
    logo.parent.mkdir(parents=True)
    _write_template(template)
    logo.write_bytes(b"fake-png")

    result = create_site_project(
        handle="keto-dinners",
        domain="keto-dinners.com",
        niche_info=NicheInfo(
            niche="low-carb keto dinner recipes",
            language="en",
            vertical="recipe blog",
            display_name="Keto Dinners",
        ),
        categories=["Sheet Pan", "Slow Cooker"],
        branding={
            "primary_color": "#3D5A40",
            "accent_color": "#D4AF37",
            "logo_path": str(logo),
        },
        project_root=project_root,
        domain_root=domain_root,
        template_path=template,
        projects_root=projects_root,
    )

    site = result.project_path
    assert site == projects_root / "keto-dinners"
    assert (site / "app" / "layout.tsx").is_file()
    assert not (site / ".env.local").exists()
    assert not (site / "check_tables.js").exists()
    assert not (site / "scripts" / "legacy_publish.py").exists()
    assert not (site / "node_modules").exists()
    assert not (site / ".vercel").exists()

    layout = (site / "app" / "layout.tsx").read_text(encoding="utf-8")
    assert "Keto Dinners" in layout
    assert "keto-dinners.com" in layout
    assert "Keto Dinners Editorial" in layout
    assert "RecetaDolce" not in layout.replace("https://res.cloudinary.com/demo/image/upload/v1/RecetaDolce/hero.jpg", "")
    assert "https://res.cloudinary.com/demo/image/upload/v1/RecetaDolce/hero.jpg" in layout

    package = json.loads((site / "package.json").read_text(encoding="utf-8"))
    assert package["name"] == "keto-dinners"
    assert package["rankstein"]["display_name"] == "Keto Dinners"

    manifest = json.loads((site / "public" / "site.webmanifest").read_text(encoding="utf-8"))
    assert manifest["name"] == "Keto Dinners"
    assert manifest["theme_color"] == "#3D5A40"

    css = (site / "app" / "globals.css").read_text(encoding="utf-8")
    assert "--color-brand-dolce: #3D5A40;" in css
    assert "--color-brand-red: #D4AF37;" in css

    assert (site / "public" / "logo.png").read_bytes() == b"fake-png"
    assert result.blueprint_path.is_file()
    assert result.env_example_path.is_file()
    assert result.supabase_migration_path.is_file()
    assert result.deploy_script_path.is_file()
    assert result.supabase_script_path.is_file()
    assert result.launch_prompt_path.is_file()
    assert (domain_root / "site_blueprint.json").is_file()

    gitignore = (site / ".gitignore").read_text(encoding="utf-8")
    assert "!supabase/migrations/*.sql" in gitignore
    assert "!scripts/rankstein-*.ps1" in gitignore


@pytest.mark.unit
def test_create_site_project_refuses_existing_without_overwrite(tmp_path: Path) -> None:
    template = tmp_path / "template"
    project_root = tmp_path / "Rankstein"
    domain_root = project_root / "data" / "domains" / "demo"
    projects_root = tmp_path / "sites"
    _write_template(template)
    project_root.mkdir()
    domain_root.mkdir(parents=True)
    (projects_root / "demo").mkdir(parents=True)

    with pytest.raises(FileExistsError):
        create_site_project(
            handle="demo",
            domain="demo.com",
            niche_info=NicheInfo("demo content", "en", "general", "Demo"),
            categories=["Guides"],
            branding={"primary_color": "#111111", "accent_color": "#eeeeee"},
            project_root=project_root,
            domain_root=domain_root,
            template_path=template,
            projects_root=projects_root,
        )

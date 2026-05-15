"""Tests for ``rankstein.provisioner`` — the ``add-domain`` orchestrator.

The Gemini CLI calls inside ``niche_detector`` are mocked at the module
level so tests don't depend on a working ``gemini`` install or external
API quota. Pollinations HTTP calls are mocked the same way.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from rankstein import branding, provisioner
from rankstein.niche_detector import Keyword, NicheInfo

# ───────────────────────────────────────────────────────────────────────────
# Slug helpers
# ───────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestDomainToHandle:
    @pytest.mark.parametrize(
        "domain, expected",
        [
            ("keto-dinners.com", "keto-dinners"),
            ("Receta-Dolce.com", "receta-dolce"),
            ("foo.bar.baz", "foo"),  # only the first label
            ("FOO_BAR.io", "foo-bar"),
            ("example.invalid", "example"),
            ("@@@@.com", "unnamed"),
            ("", "unnamed"),
        ],
    )
    def test_slug(self, domain: str, expected: str) -> None:
        assert provisioner.domain_to_handle(domain) == expected


@pytest.mark.unit
class TestEnvVarName:
    def test_basic(self) -> None:
        assert provisioner.env_var_name("keto-dinners", "PINTEREST_EMAIL") == ("PINTEREST_EMAIL_KETO_DINNERS")

    def test_no_hyphen(self) -> None:
        assert provisioner.env_var_name("recetadolce", "SUPABASE_URL") == ("SUPABASE_URL_RECETADOLCE")


# ───────────────────────────────────────────────────────────────────────────
# Wizard end-to-end (all LLM + HTTP mocked)
# ───────────────────────────────────────────────────────────────────────────


def _png_bytes(width: int = 1024, height: int = 1024) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(50, 90, 64)).save(buf, "PNG")
    return buf.getvalue()


class _StubResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None


@pytest.fixture
def mocked_external(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Mock all four LLM calls and the Pollinations HTTP call.

    Returns the dict of recorded inputs so individual tests can assert the
    provisioner threaded the right values through.
    """
    recorded: dict = {"niche_calls": 0, "category_calls": 0, "keyword_calls": 0, "voice_calls": 0}

    fake_niche = NicheInfo(
        niche="low-carb keto dinner recipes",
        language="en",
        vertical="recipe blog",
        display_name="Keto Dinners",
    )
    fake_categories = ["Sheet Pan", "Slow Cooker", "Quick Dinners", "Holiday", "Sides", "Mains"]
    fake_keywords = [
        Keyword(keyword=f"easy keto recipe {i}", category=fake_categories[i % 6], priority="High")
        for i in range(15)
    ]
    fake_voice = "## Tone\nWarm, direct, expert.\n\n## Style Pillars\n1. Clear.\n2. Direct.\n"

    def _detect_niche(_domain: str) -> NicheInfo:
        recorded["niche_calls"] += 1
        return fake_niche

    def _generate_categories(_niche: str, _lang: str, count: int = 6) -> list[str]:
        recorded["category_calls"] += 1
        return fake_categories[:count]

    def _generate_keywords(_niche, _cats, _lang, count=30) -> list[Keyword]:
        recorded["keyword_calls"] += 1
        return fake_keywords[:count]

    def _generate_brand_voice(_n, _l, _d) -> str:
        recorded["voice_calls"] += 1
        return fake_voice

    monkeypatch.setattr(provisioner, "detect_niche", _detect_niche)
    monkeypatch.setattr(provisioner, "generate_categories", _generate_categories)
    monkeypatch.setattr(provisioner, "generate_keywords", _generate_keywords)
    monkeypatch.setattr(provisioner, "generate_brand_voice", _generate_brand_voice)
    # Pollinations HTTP
    monkeypatch.setattr(branding.requests, "get", lambda *a, **kw: _StubResponse(_png_bytes()))
    return recorded


@pytest.mark.unit
class TestProvisionDomain:
    def test_creates_full_layout_under_data_domains(self, tmp_path: Path, mocked_external: dict) -> None:
        result = provisioner.provision_domain(
            "keto-dinners.com",
            tmp_path,
            interactive=False,
            keyword_count=15,
            category_count=6,
        )

        assert result.handle == "keto-dinners"
        assert result.domain == "keto-dinners.com"
        domain_root = tmp_path / "data" / "domains" / "keto-dinners"
        assert domain_root.is_dir()

        # All required files present
        assert (domain_root / "domain.json").is_file()
        assert (domain_root / "keywords.md").is_file()
        assert (domain_root / "brand_voice.md").is_file()
        assert (domain_root / ".env").is_file()
        assert (domain_root / "branding" / "logo.png").is_file()
        assert (domain_root / "branding" / "theme.json").is_file()
        assert (domain_root / "sessions").is_dir()
        assert (domain_root / "output").is_dir()

        # Manifest has the right shape
        manifest = json.loads((domain_root / "domain.json").read_text(encoding="utf-8"))
        assert manifest["handle"] == "keto-dinners"
        assert manifest["domain"] == "keto-dinners.com"
        assert manifest["language"] == "en"
        assert manifest["display_name"] == "Keto Dinners"
        assert len(manifest["categories"]) == 6
        assert manifest["pinterest_email_env"] == "PINTEREST_EMAIL_KETO_DINNERS"
        assert manifest["supabase_key_env"] == "SUPABASE_SERVICE_ROLE_KEY_KETO_DINNERS"
        assert manifest["primary_color"] == "#3D5A40"
        assert manifest["cta_text"] == "TAP FOR THE RECIPE"  # english CTA
        assert manifest["schema_version"] == 1

        # All four LLM steps were called once
        assert mocked_external == {
            "niche_calls": 1,
            "category_calls": 1,
            "keyword_calls": 1,
            "voice_calls": 1,
        }

    def test_per_domain_env_uses_correct_var_names(self, tmp_path: Path, mocked_external: dict) -> None:
        provisioner.provision_domain("keto-dinners.com", tmp_path, interactive=False, keyword_count=15)
        env_text = (tmp_path / "data" / "domains" / "keto-dinners" / ".env").read_text(encoding="utf-8")
        assert "PINTEREST_EMAIL_KETO_DINNERS=" in env_text
        assert "PINTEREST_PASSWORD_KETO_DINNERS=" in env_text
        assert "SUPABASE_URL_KETO_DINNERS=" in env_text
        assert "SUPABASE_SERVICE_ROLE_KEY_KETO_DINNERS=" in env_text

    def test_keywords_md_has_headers_and_15_rows(self, tmp_path: Path, mocked_external: dict) -> None:
        provisioner.provision_domain("keto-dinners.com", tmp_path, interactive=False, keyword_count=15)
        text = (tmp_path / "data" / "domains" / "keto-dinners" / "keywords.md").read_text(encoding="utf-8")
        assert "# Keyword Roadmap" in text
        assert "| Keyword | Category" in text
        # 15 keyword rows + header + separator
        rows = [ln for ln in text.splitlines() if ln.startswith("| ") and "Keyword" not in ln]
        assert len(rows) == 15

    def test_skip_branding(self, tmp_path: Path, mocked_external: dict) -> None:
        result = provisioner.provision_domain(
            "keto-dinners.com",
            tmp_path,
            interactive=False,
            skip_branding=True,
            keyword_count=10,
        )
        assert not (tmp_path / "data" / "domains" / "keto-dinners" / "branding" / "logo.png").exists()
        assert result.branding["primary_color"] == "#D4AF37"

    def test_registry_picks_up_new_domain_after_provision(
        self, tmp_path: Path, mocked_external: dict
    ) -> None:
        from rankstein import domain as domain_mod

        provisioner.provision_domain("keto-dinners.com", tmp_path, interactive=False, keyword_count=10)
        # A fresh registry rooted at tmp_path sees the new domain immediately
        reg = domain_mod.DomainRegistry(tmp_path)
        d = reg.get("keto-dinners")
        assert d.domain == "keto-dinners.com"
        assert d.is_synthesized is False
        assert d.language == "en"
        assert "Sheet Pan" in d.categories

    def test_clone_site_threads_site_factory_options(
        self, tmp_path: Path, mocked_external: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: dict = {}
        site_root = tmp_path / "sites" / "keto-dinners"

        def _fake_create_site_project(**kwargs):
            recorded.update(kwargs)
            return provisioner.SiteProjectResult(
                handle="keto-dinners",
                domain="keto-dinners.com",
                project_path=site_root,
                blueprint_path=site_root / "rankstein.site.json",
                env_example_path=site_root / ".env.local.example",
                supabase_migration_path=site_root / "supabase" / "migrations" / "0001.sql",
                deploy_script_path=site_root / "scripts" / "rankstein-deploy.ps1",
                supabase_script_path=site_root / "scripts" / "rankstein-supabase.ps1",
                launch_prompt_path=tmp_path
                / "data"
                / "domains"
                / "keto-dinners"
                / "upcoming_domain_system_prompt.md",
                copied_from=tmp_path / "template",
            )

        monkeypatch.setattr(provisioner, "create_site_project", _fake_create_site_project)

        result = provisioner.provision_domain(
            "keto-dinners.com",
            tmp_path,
            interactive=False,
            keyword_count=10,
            clone_site=True,
            template_path=tmp_path / "template",
            projects_root=tmp_path / "sites",
            overwrite_site=True,
        )

        assert result.site_project is not None
        assert recorded["handle"] == "keto-dinners"
        assert recorded["domain"] == "keto-dinners.com"
        assert recorded["template_path"] == tmp_path / "template"
        assert recorded["projects_root"] == tmp_path / "sites"
        assert recorded["overwrite"] is True
        assert any("generated site project" in step for step in result.next_steps)

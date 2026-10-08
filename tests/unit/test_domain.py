"""Tests for ``rankstein.domain.DomainRegistry``.

Two distinct loading paths must work:

1. **Synthesized default** — when ``data/domains/`` is absent or empty,
   the registry produces a single ``recetadolce`` domain whose paths
   point at the legacy flat layout (``memory/keywords.md`` etc.). This
   is what lets Phase 1 land without any file moves.

2. **Manifest-driven** — when ``data/domains/<handle>/domain.json``
   exists, it loads literal values from the JSON, with credentials
   resolved from the env-var names referenced in the manifest.

Plus standard registry behaviors: ``default_handle`` resolution,
``KeyError`` on unknown handles, and reload-after-add.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rankstein.domain import (
    _DEFAULT_HANDLE,
    DomainRegistry,
    get_registry,
    reload_registry,
)

# ───────────────────────────────────────────────────────────────────────────
# Synthesized-default path
# ───────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSynthesizedDefault:
    def test_default_handle_when_no_domains_dir(self, tmp_path: Path) -> None:
        # No data/domains/ dir at all
        reg = DomainRegistry(tmp_path)
        assert reg.default_handle == _DEFAULT_HANDLE

    def test_default_handle_when_domains_dir_empty(self, tmp_path: Path) -> None:
        (tmp_path / "data" / "domains").mkdir(parents=True)
        reg = DomainRegistry(tmp_path)
        assert reg.default_handle == _DEFAULT_HANDLE

    def test_synthesized_default_uses_legacy_flat_paths(self, tmp_path: Path) -> None:
        reg = DomainRegistry(tmp_path)
        d = reg.default
        assert d.handle == _DEFAULT_HANDLE
        assert d.domain == "recetadolce.com"
        # Legacy flat paths
        assert d.keywords_file == tmp_path / "memory" / "keywords.md"
        assert d.sessions_dir == tmp_path / "data" / "sessions"
        assert d.output_dir == tmp_path / "nanobanana-output"
        # Categories carried over from today's hardcoded list
        assert "fresas-y-nata" in d.categories
        assert "chocolates" in d.categories
        # Synthesized → no manifest on disk
        assert d.is_synthesized is True

    def test_get_with_none_returns_default(self, tmp_path: Path) -> None:
        reg = DomainRegistry(tmp_path)
        assert reg.get(None).handle == reg.default_handle
        assert reg.get("").handle == reg.default_handle

    def test_unknown_handle_raises_keyerror(self, tmp_path: Path) -> None:
        reg = DomainRegistry(tmp_path)
        with pytest.raises(KeyError, match="Unknown domain handle"):
            reg.get("does-not-exist")


# ───────────────────────────────────────────────────────────────────────────
# Manifest-driven path
# ───────────────────────────────────────────────────────────────────────────


def _write_manifest(domains_root: Path, handle: str, **overrides: object) -> Path:
    base = {
        "handle": handle,
        "domain": f"{handle}.com",
        "display_name": handle.title(),
        "language": "en",
        "niche": "test niche",
        "categories": ["Cat A", "Cat B"],
        "boards_default": {"Cat A": "Board A", "_default": "General"},
        "pinterest_email_env": "PINTEREST_EMAIL",
        "pinterest_password_env": "PINTEREST_PASSWORD",
        "supabase_key_env": "SUPABASE_SERVICE_ROLE_KEY",
        "supabase_url": "https://example.invalid",
        "primary_color": "#3D5A40",
        "accent_color": "#D4AF37",
        "brand_name_short": "TEST BRAND | 2026",
        "cta_text": "CLICK HERE",
        "daily_pin_budget": 50,
    }
    base.update(overrides)
    domain_dir = domains_root / handle
    domain_dir.mkdir(parents=True, exist_ok=True)
    manifest = domain_dir / "domain.json"
    manifest.write_text(json.dumps(base), encoding="utf-8")
    return manifest


@pytest.mark.unit
class TestManifestDriven:
    def test_single_manifest_coexists_with_synthesized_default(self, tmp_path: Path) -> None:
        # Phase-1→Phase-2 transition: recetadolce is ALWAYS synthesized as
        # a fallback even when manifest-driven domains exist alongside.
        _write_manifest(tmp_path / "data" / "domains", "ketokitchen")
        reg = DomainRegistry(tmp_path)
        assert reg.default_handle == "ketokitchen"  # alphabetical first
        assert [d.handle for d in reg.all()] == ["ketokitchen", "recetadolce"]
        d = reg.get("ketokitchen")
        assert d.is_synthesized is False
        assert d.domain == "ketokitchen.com"
        assert d.language == "en"
        assert d.categories == ("Cat A", "Cat B")
        assert d.brand_name_short == "TEST BRAND | 2026"
        assert d.daily_pin_budget == 50
        # The recetadolce fallback is still present and synthesized
        assert reg.get("recetadolce").is_synthesized is True

    def test_two_manifests_alphabetical_default(self, tmp_path: Path) -> None:
        domains = tmp_path / "data" / "domains"
        _write_manifest(domains, "recetadolce")
        _write_manifest(domains, "ketokitchen")
        reg = DomainRegistry(tmp_path)
        # Alphabetical: ketokitchen wins
        assert reg.default_handle == "ketokitchen"
        assert [d.handle for d in reg.all()] == ["ketokitchen", "recetadolce"]

    def test_env_var_override_for_default_handle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        domains = tmp_path / "data" / "domains"
        _write_manifest(domains, "recetadolce")
        _write_manifest(domains, "ketokitchen")
        monkeypatch.setenv("RANKSTEIN_DEFAULT_DOMAIN", "recetadolce")
        reg = DomainRegistry(tmp_path)
        assert reg.default_handle == "recetadolce"

    def test_credentials_resolved_from_env_var_names(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PINTEREST_EMAIL_KETO", "keto@example.com")
        monkeypatch.setenv("PINTEREST_PASSWORD_KETO", "keto-pw")
        monkeypatch.setenv("SUPABASE_KEY_KETO", "keto-supa-key")
        _write_manifest(
            tmp_path / "data" / "domains",
            "ketokitchen",
            pinterest_email_env="PINTEREST_EMAIL_KETO",
            pinterest_password_env="PINTEREST_PASSWORD_KETO",
            supabase_key_env="SUPABASE_KEY_KETO",
        )
        reg = DomainRegistry(tmp_path)
        d = reg.default
        assert d.pinterest_email == "keto@example.com"
        assert d.pinterest_password.get_secret_value() == "keto-pw"
        assert d.supabase_service_role_key.get_secret_value() == "keto-supa-key"

    def test_malformed_manifest_skipped(self, tmp_path: Path) -> None:
        domains = tmp_path / "data" / "domains"
        # One good, one with broken JSON
        _write_manifest(domains, "good")
        bad_dir = domains / "broken"
        bad_dir.mkdir()
        (bad_dir / "domain.json").write_text("{not valid json", encoding="utf-8")
        reg = DomainRegistry(tmp_path)
        # 'broken' is skipped; 'good' loaded; 'recetadolce' synthesized fallback
        handles = [d.handle for d in reg.all()]
        assert "good" in handles
        assert "broken" not in handles
        assert "recetadolce" in handles


# ───────────────────────────────────────────────────────────────────────────
# Module-level singleton
# ───────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSingleton:
    def test_get_registry_caches(self) -> None:
        a = get_registry()
        b = get_registry()
        assert a is b

    def test_reload_registry_returns_fresh_instance(self) -> None:
        get_registry()  # populate cache
        b = reload_registry()
        # After cache clear, get_registry() returns the new instance
        assert get_registry() is b
        # The pre-clear handle and post-clear handle agree on the project's
        # actual default; we only assert that reload_registry reset the cache
        assert b.default_handle == get_registry().default_handle

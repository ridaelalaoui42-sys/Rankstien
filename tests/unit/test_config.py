"""Tests for the unified rankstein.config module.

These verify two things:

1. The new Settings class loads the canonical env var names correctly
   (``NEXT_PUBLIC_SUPABASE_URL``, ``SUPABASE_SERVICE_ROLE_KEY``,
   ``PINTEREST_EMAIL``, etc.) — these aliases are load-bearing for backwards
   compatibility with the existing ``.env``.

2. The new Settings produces values that match what the legacy configs would
   produce for the same env. This is the **drift guard**: as long as both
   systems exist, this test fails if they disagree on a shared field.
"""

from __future__ import annotations

import importlib

import pytest

from rankstein.config import Settings, reset_settings_cache


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.mark.unit
class TestEnvAliases:
    """The .env uses Next.js-style names; Settings must accept them."""

    def test_supabase_url_via_next_public_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_URL", "https://example.invalid")
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.supabase_url == "https://example.invalid"

    def test_supabase_anon_key_via_next_public_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "anon-token-xyz")
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.supabase_anon_key.get_secret_value() == "anon-token-xyz"

    def test_pinterest_password_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PINTEREST_PASSWORD", "secret-pw")
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.pinterest_password.get_secret_value() == "secret-pw"

    def test_rankstein_debug_alias_maps_to_debug_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RANKSTEIN_DEBUG", "true")
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.debug_mode is True

    def test_ai_engine_defaults_to_gemini_cli(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ADK_MODEL", raising=False)
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.ai_engine == "gemini_cli"
        assert s.adk_model == "gemini-3.1-flash-lite-preview"

    def test_ai_engine_rejects_unknown_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RANKSTEIN_AI_ENGINE", "unknown")
        with pytest.raises(ValueError, match="RANKSTEIN_AI_ENGINE"):
            Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.unit
class TestSecretsAreNotLeaked:
    """``SecretStr`` should hide secrets in repr / str."""

    def test_pinterest_password_repr_is_masked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PINTEREST_PASSWORD", "super-secret")
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert "super-secret" not in repr(s)
        assert "super-secret" not in str(s)

    def test_supabase_service_role_key_repr_is_masked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "eyJ.bigjwt.payload")
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert "eyJ.bigjwt.payload" not in repr(s)


@pytest.mark.unit
class TestValidators:
    def test_rankstein_secret_min_length_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RANKSTEIN_SECRET", "too-short")
        with pytest.raises(ValueError, match="at least 16 chars"):
            Settings(_env_file=None)  # type: ignore[call-arg]

    def test_rankstein_secret_empty_is_allowed_at_load(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("RANKSTEIN_SECRET", raising=False)
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.rankstein_secret.get_secret_value() == ""

    def test_require_secret_raises_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("RANKSTEIN_SECRET", raising=False)
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        with pytest.raises(RuntimeError, match="not set"):
            s.require_secret()

    def test_log_level_normalized_to_lowercase(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.log_level == "warning"

    def test_invalid_log_level_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOG_LEVEL", "loud")
        with pytest.raises(ValueError, match="log_level"):
            Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.unit
class TestConvenienceAccessors:
    def test_cors_list_splits_and_strips(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test ,,http://c.test")
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.cors_list == ["http://a.test", "http://b.test", "http://c.test"]

    def test_pinterest_configured_requires_both_email_and_password(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PINTEREST_EMAIL", "x@y.test")
        monkeypatch.delenv("PINTEREST_PASSWORD", raising=False)
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.pinterest_configured is False

        monkeypatch.setenv("PINTEREST_PASSWORD", "pw")
        reset_settings_cache()
        s2 = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s2.pinterest_configured is True


@pytest.mark.unit
class TestParityWithLegacyConfigs:
    """Drift guard: rankstein.config must agree with the legacy configs.

    These tests load the same env into both systems and compare the values for
    every overlapping field. As long as both systems exist, we want any
    accidental drift to fail loudly here.
    """

    def test_parity_with_pinterest_automation_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_URL", "https://parity.test")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "parity-key")
        monkeypatch.setenv("PINTEREST_EMAIL", "p@parity.test")
        monkeypatch.setenv("PINTEREST_PASSWORD", "parity-pw")

        new_s = Settings(_env_file=None)  # type: ignore[call-arg]

        # Reload the legacy module so its singletons re-read os.environ
        import pinterest_automation.config as legacy_pa

        importlib.reload(legacy_pa)
        legacy_cfg = legacy_pa.AutomationConfig()

        assert new_s.supabase_url == legacy_cfg.supabase.url
        assert new_s.supabase_service_role_key.get_secret_value() == legacy_cfg.supabase.key
        assert new_s.pinterest_email == legacy_cfg.credentials.email
        assert new_s.pinterest_password.get_secret_value() == legacy_cfg.credentials.password


@pytest.mark.unit
class TestPinterestAutomationAccounts:
    def test_accounts_json_supports_multiple_browser_families(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import pinterest_automation.config as legacy_pa

        monkeypatch.delenv("PINTEREST_EMAIL", raising=False)
        monkeypatch.delenv("PINTEREST_PASSWORD", raising=False)
        monkeypatch.setenv(
            "PINTEREST_ACCOUNTS",
            '[{"name":"r1","session":"turbo_r1","browser":"firefox"},'
            '{"name":"m1","session":"turbo_m1","browser":"chromium"}]',
        )
        cfg = legacy_pa.AutomationConfig()

        assert sorted(cfg.accounts) == ["m1", "r1"]
        assert cfg.accounts["r1"].session_name == "turbo_r1"
        assert cfg.accounts["r1"].browser == "firefox"
        assert cfg.accounts["m1"].session_name == "turbo_m1"
        assert cfg.accounts["m1"].browser == "chromium"

    def test_indexed_accounts_are_loaded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import pinterest_automation.config as legacy_pa

        monkeypatch.delenv("PINTEREST_ACCOUNTS", raising=False)
        monkeypatch.delenv("PINTEREST_EMAIL", raising=False)
        monkeypatch.delenv("PINTEREST_PASSWORD", raising=False)
        monkeypatch.setenv("PINTEREST_ACCOUNT_1_NAME", "m1")
        monkeypatch.setenv("PINTEREST_ACCOUNT_1_SESSION", "turbo_m1")
        monkeypatch.setenv("PINTEREST_ACCOUNT_1_BROWSER", "chrome")

        cfg = legacy_pa.AutomationConfig()

        assert cfg.accounts["m1"].session_name == "turbo_m1"
        assert cfg.accounts["m1"].browser == "chromium"

    def test_singleton_credentials_register_default_account_when_distinct(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import pinterest_automation.config as legacy_pa

        monkeypatch.setenv("PINTEREST_EMAIL", "m@example.test")
        monkeypatch.setenv("PINTEREST_PASSWORD", "pw")
        monkeypatch.setenv("PINTEREST_DEFAULT_ACCOUNT_HANDLE", "m1")
        monkeypatch.setenv(
            "PINTEREST_ACCOUNTS",
            '[{"name":"r1","email":"r@example.test","password":"pw","session":"turbo_r1"}]',
        )

        cfg = legacy_pa.AutomationConfig()

        assert sorted(cfg.accounts) == ["m1", "r1"]
        assert cfg.accounts["m1"].email == "m@example.test"


@pytest.mark.unit
class TestPinterestBoards:
    def test_legacy_board_names_normalize_to_live_boards(self) -> None:
        from pinterest_automation.config import normalize_board_name

        assert normalize_board_name("Postres y Dulces") == "Chocolate"
        assert normalize_board_name("Arroces y Paellas") == "Arroces"
        assert normalize_board_name("Ensaladas y Saludable") == "ENSALADES"
        assert normalize_board_name("recetas") == "Aperitivos"
        assert normalize_board_name("Carnes y Tradición") == "Carnes"

    def test_unknown_or_blank_board_fails_closed_to_default_live_board(self) -> None:
        from pinterest_automation.config import normalize_board_name

        assert normalize_board_name("") == "Aperitivos"
        assert normalize_board_name(None) == "Aperitivos"
        assert normalize_board_name("old-missing-board") == "Aperitivos"

    def test_canonical_board_resolves_to_account_live_label(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from pinterest_automation.config import resolve_account_board_name

        monkeypatch.setenv(
            "PINTEREST_ACCOUNT_BOARD_MAP",
            '{"media":{"ENSALADES":"Ensaladas y Saludable"}}',
        )

        assert resolve_account_board_name("ENSALADES", "media") == "Ensaladas y Saludable"
        assert resolve_account_board_name("ENSALADES", "rida") == "ENSALADES"

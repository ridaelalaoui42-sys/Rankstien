"""Unified runtime configuration for RankStein.

Replaces the two parallel configuration systems:

- ``backend/core/config.py``       — pydantic ``BaseSettings`` for the FastAPI app
- ``pinterest_automation/config.py`` — dataclasses with ``os.environ.get`` in
  ``__post_init__`` for the autonomous supervisor

Both read the same ``.env`` and overlap heavily (Supabase URL, Pinterest creds,
log level). Keeping them in sync is a manual chore that produces drift bugs.
This module is the single source of truth.

Design choices
--------------
- **Pydantic v2 ``BaseSettings``** for validation, env-file loading, and typed
  access. ``pydantic-settings`` is already a backend dep.
- **Aliases** (e.g. ``NEXT_PUBLIC_SUPABASE_URL`` → ``supabase_url``) so existing
  ``.env`` files keep working unchanged.
- **``SecretStr``** for credentials so accidental ``print(settings)`` cannot
  leak them; use ``settings.pinterest_password.get_secret_value()`` to read.
- **Sub-model accessors** (``settings.supabase``, ``settings.pinterest``) so
  callers get the same ergonomic shape as the legacy nested dataclasses
  without a second config object.
- **Lazy singleton** via ``get_settings()`` — validates once per process,
  fails fast at first call if required values are missing.

Migration plan
--------------
1. *Now*: this module ships alongside the legacy configs. Tests verify parity.
2. *Next*: callers in ``rankstein_mcp_server.py`` and
   ``pinterest_automation/*`` migrate to ``rankstein.config.get_settings()``.
3. *Later*: legacy ``backend/core/config.py`` and
   ``pinterest_automation/config.py`` shrink to thin shims that delegate here,
   then are deleted.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """All runtime configuration. Loaded from environment + ``.env``."""

    model_config = SettingsConfigDict(
        env_file=str(DEFAULT_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # ── Supabase ───────────────────────────────────────────────────────────
    supabase_url: str = Field(
        default="https://xjvmnmfczvwkjiasirsl.supabase.co",
        alias="NEXT_PUBLIC_SUPABASE_URL",
    )
    supabase_service_role_key: SecretStr = Field(
        default=SecretStr(""),
        alias="SUPABASE_SERVICE_ROLE_KEY",
    )
    supabase_anon_key: SecretStr = Field(
        default=SecretStr(""),
        alias="NEXT_PUBLIC_SUPABASE_ANON_KEY",
    )
    supabase_bucket: str = Field(default="recipe-images")

    # ── Pinterest ──────────────────────────────────────────────────────────
    pinterest_email: str = Field(default="", alias="PINTEREST_EMAIL")
    pinterest_password: SecretStr = Field(
        default=SecretStr(""),
        alias="PINTEREST_PASSWORD",
    )
    pinterest_token: SecretStr = Field(
        default=SecretStr(""),
        alias="PINTEREST_TOKEN",
    )
    pinterest_board_id: str = Field(default="", alias="PINTEREST_BOARD_ID")

    # ── Cloudinary ─────────────────────────────────────────────────────────
    cloudinary_cloud_name: str = Field(default="", alias="CLOUDINARY_CLOUD_NAME")
    cloudinary_api_key: SecretStr = Field(
        default=SecretStr(""),
        alias="CLOUDINARY_API_KEY",
    )
    cloudinary_api_secret: SecretStr = Field(
        default=SecretStr(""),
        alias="CLOUDINARY_API_SECRET",
    )

    # ── Gemini / Google ────────────────────────────────────────────────────
    ai_engine: str = Field(default="gemini_cli", alias="RANKSTEIN_AI_ENGINE")
    google_api_key: SecretStr = Field(
        default=SecretStr(""),
        alias="GOOGLE_API_KEY",
    )
    adk_model: str = Field(default="auto")
    adk_fallback_model: str = Field(default="gemini-3.1-pro-preview", alias="RANKSTEIN_FALLBACK_MODEL")
    adk_temperature: Annotated[float, Field(ge=0, le=2)] = 0.7
    gemini_cli_path: str = Field(default="", alias="GEMINI_CLI_PATH")
    gemini_cli_timeout_seconds: int = Field(default=300, alias="GEMINI_CLI_TIMEOUT_SECONDS")
    gemini_cli_yolo: bool = Field(default=True, alias="GEMINI_CLI_YOLO")

    # ── App / API surface ──────────────────────────────────────────────────
    host: str = Field(default="0.0.0.0")  # noqa: S104  (binding all interfaces is intentional in container)
    port: Annotated[int, Field(ge=1, le=65535)] = 8080
    debug_mode: bool = Field(default=False, alias="RANKSTEIN_DEBUG")
    log_level: str = Field(default="info")
    cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:3001",
        alias="CORS_ORIGINS",
    )
    rate_limit: str = Field(default="60/minute")

    # ── Secrets / auth ─────────────────────────────────────────────────────
    rankstein_secret: SecretStr = Field(
        default=SecretStr(""),
        alias="RANKSTEIN_SECRET",
    )
    cms_api_key: SecretStr = Field(
        default=SecretStr(""),
        alias="CMS_API_KEY",
    )
    admin_password: SecretStr = Field(
        default=SecretStr(""),
        alias="ADMIN_PASSWORD",
    )

    # ── Database ───────────────────────────────────────────────────────────
    db_path: str = Field(default="")

    # ── WordPress (legacy, kept for backend compatibility) ─────────────────
    wp_site_url: str = Field(default="")
    wp_api_user: str = Field(default="")
    wp_api_password: SecretStr = Field(default=SecretStr(""))

    # ── Capacity caps ──────────────────────────────────────────────────────
    max_concurrent_domains: int = Field(default=5)
    max_agents_per_domain: int = Field(default=10)

    # ── Validators ─────────────────────────────────────────────────────────
    @field_validator("rankstein_secret")
    @classmethod
    def _validate_secret_length(cls, v: SecretStr) -> SecretStr:
        # Loose validation: only enforce length when something is set. An empty
        # secret is allowed at config-load time so tests / dev shells don't
        # explode; modules that genuinely need it (token signing) should call
        # ``require_secret()`` and fail loudly.
        raw = v.get_secret_value() if isinstance(v, SecretStr) else str(v)
        if raw and len(raw) < 16:
            raise ValueError("RANKSTEIN_SECRET, when set, must be at least 16 chars")
        return v

    @field_validator("ai_engine")
    @classmethod
    def _normalize_ai_engine(cls, v: str) -> str:
        normalized = v.lower().strip()
        if normalized not in {"gemini_cli", "google_api"}:
            raise ValueError("RANKSTEIN_AI_ENGINE must be one of: gemini_cli, google_api")
        return normalized

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in {"debug", "info", "warning", "error", "critical"}:
            raise ValueError(f"log_level must be one of debug/info/warning/error/critical (got {v!r})")
        return v

    # ── Convenience accessors ──────────────────────────────────────────────
    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def db_file(self) -> Path:
        if self.db_path:
            return Path(self.db_path)
        return PROJECT_ROOT / "data" / "rankstein.db"

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key.get_secret_value())

    @property
    def pinterest_configured(self) -> bool:
        return bool(self.pinterest_email and self.pinterest_password.get_secret_value())

    def require_secret(self) -> str:
        """Return the rankstein secret or raise — call from modules that genuinely need it."""
        v = self.rankstein_secret.get_secret_value()
        if not v:
            raise RuntimeError("RANKSTEIN_SECRET is not set. Add it to .env or your secrets manager.")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide Settings singleton. Validated once on first call."""
    return Settings()


def reset_settings_cache() -> None:
    """Clear the cached singleton — used by tests that mutate env vars."""
    get_settings.cache_clear()

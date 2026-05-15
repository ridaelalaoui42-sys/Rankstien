"""RankStein — Configuration
Production settings via pydantic-settings with .env file support.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    ai_engine: str = Field(default="gemini_cli", alias="RANKSTEIN_AI_ENGINE")
    google_api_key: str = Field(
        default="", description="Gemini API key (legacy - not needed for CLI pipeline)"
    )
    adk_model: str = Field(default="auto")
    adk_fallback_model: str = Field(default="gemini-3.1-pro-preview", alias="RANKSTEIN_FALLBACK_MODEL")
    adk_temperature: float = Field(default=0.7, ge=0, le=2)
    gemini_cli_path: str = Field(default="", alias="GEMINI_CLI_PATH")
    gemini_cli_timeout_seconds: int = Field(default=300, alias="GEMINI_CLI_TIMEOUT_SECONDS")
    gemini_cli_yolo: bool = Field(default=True, alias="GEMINI_CLI_YOLO")
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8080)
    debug_mode: bool = Field(default=False, alias="RANKSTEIN_DEBUG")
    log_level: str = Field(default="info")
    db_path: str = Field(default="")
    rankstein_secret: str = Field(default="", alias="RANKSTEIN_SECRET")
    cors_origins: str = Field(default="http://localhost:3000,http://localhost:3001")
    rate_limit: str = Field(default="60/minute")
    wp_site_url: str = Field(default="")
    wp_api_user: str = Field(default="")
    wp_api_password: str = Field(default="")
    pinterest_token: str = Field(default="")
    pinterest_board_id: str = Field(default="")
    max_concurrent_domains: int = Field(default=5)
    max_agents_per_domain: int = Field(default=10)

    @field_validator("rankstein_secret")
    @classmethod
    def validate_secret(cls, v: str) -> str:
        if not v or len(v) < 16:
            raise ValueError(
                'RANKSTEIN_SECRET must be set (min 16 chars). Generate: python -c "import secrets; print(secrets.token_hex(32))"'
            )
        return v

    @field_validator("ai_engine")
    @classmethod
    def validate_ai_engine(cls, v: str) -> str:
        normalized = v.lower().strip()
        if normalized not in {"gemini_cli", "google_api"}:
            raise ValueError("RANKSTEIN_AI_ENGINE must be one of: gemini_cli, google_api")
        return normalized

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def db_file(self) -> Path:
        if self.db_path:
            return Path(self.db_path)
        return PROJECT_ROOT / "data" / "rankstein.db"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

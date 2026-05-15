"""Tests for domain isolation in JobQueue and RateLimiter.

These tests ensure that:
1. Different domain handles resolve to different SQLite databases for their JobQueue.
2. Different domain handles get isolated RateLimiter instances with budgets populated from the domain configuration.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pinterest_automation.job_queue import _reset_job_queue_singleton, get_job_queue
from pinterest_automation.rate_limiter import _reset_rate_limiter_singleton, get_rate_limiter
from rankstein.domain import DomainRegistry


def _write_manifest(domains_root: Path, handle: str, budget: int) -> Path:
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
        "daily_pin_budget": budget,
    }
    domain_dir = domains_root / handle
    domain_dir.mkdir(parents=True, exist_ok=True)
    manifest = domain_dir / "domain.json"
    manifest.write_text(json.dumps(base), encoding="utf-8")
    return manifest


@pytest.mark.unit
class TestDomainIsolation:
    @pytest.fixture(autouse=True)
    def setup_isolated_registry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Write two custom domains
        domains_root = tmp_path / "data" / "domains"
        _write_manifest(domains_root, "alpha", budget=15)
        _write_manifest(domains_root, "beta", budget=45)

        # Create the registry rooted at tmp_path
        self.registry = DomainRegistry(tmp_path)

        # Monkeypatch get_registry to return our test-specific registry
        monkeypatch.setattr("rankstein.domain.get_registry", lambda: self.registry)

        # Reset singletons before and after test
        _reset_job_queue_singleton()
        _reset_rate_limiter_singleton()
        yield
        _reset_job_queue_singleton()
        _reset_rate_limiter_singleton()

    def test_job_queue_isolation(self) -> None:
        # Retrieve queue for alpha
        queue_alpha = get_job_queue(domain_handle="alpha")
        # Retrieve queue for beta
        queue_beta = get_job_queue(domain_handle="beta")

        # Verify they are separate instances
        assert queue_alpha is not queue_beta

        # Verify their DB paths point to the respective domain root folders
        assert queue_alpha._db_file == self.registry.get("alpha").root / "jobs.db"
        assert queue_beta._db_file == self.registry.get("beta").root / "jobs.db"

    def test_rate_limiter_isolation(self) -> None:
        # Retrieve rate limiter for alpha
        limiter_alpha = get_rate_limiter(domain_handle="alpha")
        # Retrieve rate limiter for beta
        limiter_beta = get_rate_limiter(domain_handle="beta")

        # Verify they are separate instances
        assert limiter_alpha is not limiter_beta

        # Verify their daily limits are populated correctly from domain configs
        assert limiter_alpha.config.daily_pin_limit == 15
        assert limiter_beta.config.daily_pin_limit == 45

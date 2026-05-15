"""Domain registry — the top-level partition of the multi-domain refactor.

A ``Domain`` represents a single blog / website that RankStein operates on.
It owns its own keyword roadmap, Pinterest sessions, hero output dir,
credentials, categories, and branding. The autonomous content pipeline runs
"per domain": every MCP tool that today reads ``memory/keywords.md`` or
writes to ``nanobanana-output/`` will (in Phase 1+) accept an optional
``domain_handle: str`` parameter and resolve the request through this module.

Two layout modes are supported transparently:

1. **Synthesized default** — when ``data/domains/`` does not exist or
   contains no domain subdirectories, the registry constructs a single
   default domain (``recetadolce``) from the **existing flat layout**:
   ``memory/keywords.md``, ``data/sessions/pinterest_rida_v7/``,
   ``nanobanana-output/``, and credentials from the project ``.env``.
   This is the **Phase 1 path** — no file moves required, today's
   deployment keeps working unchanged.

2. **Roster file** — when ``data/domains/<handle>/domain.json`` exists,
   the registry loads its values literally. This is the **Phase 2 path**
   activated by the ``add-domain`` wizard.

Phase 1 callers should use ``get_registry().get(handle_or_none)`` and pass
``None`` to mean "the default domain". Once Phase 2 lands, callers naturally
become multi-domain-aware just by threading the handle through.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import SecretStr

from rankstein.config import get_settings

# Load .env relative to this file's project structure (parent.parent)
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=False)

# ── Categories / boards default for the synthesized recetadolce domain ────
_RECETADOLCE_CATEGORIES: tuple[str, ...] = (
    "Aperitivos",
    "Postres",
    "Carnes",
    "Pescados",
    "Ensaladas",
)

_RECETADOLCE_BOARDS_DEFAULT: dict[str, str] = {
    "Aperitivos": "Aperitivos y Tapas",
    "Postres": "Postres y Dulces",
    "Carnes": "Carnes y Tradición",
    "Pescados": "Pescados y Mariscos",
    "Ensaladas": "Ensaladas y Saludable",
    "_default": "Recetas Españolas",
}


@dataclass(frozen=True)
class Domain:
    """A single blog / website operated by RankStein.

    All paths are absolute and resolved at construction. All credentials are
    held as ``SecretStr`` so accidental ``print(domain)`` cannot leak them.
    """

    handle: str
    domain: str
    display_name: str
    language: str
    niche: str

    # File partitions
    root: Path
    keywords_file: Path
    sessions_dir: Path
    output_dir: Path
    branding_dir: Path

    # Credentials — resolved, not env-var names
    pinterest_email: str
    pinterest_password: SecretStr
    supabase_url: str
    supabase_service_role_key: SecretStr

    # Niche-driven content config
    categories: tuple[str, ...] = field(default_factory=tuple)
    boards_default: dict[str, str] = field(default_factory=dict)

    # Branding tokens — defaults match today's "Receta Dolce" gold/charcoal.
    # The Phase 2 wizard generates these per-domain from the niche.
    primary_color: str = "#D4AF37"
    accent_color: str = "#1a1a1a"
    brand_name_short: str = "RECETA DOLCE | 2026"
    cta_text: str = "TOCA PARA VER LA RECETA"

    # Operational policies
    daily_pin_budget: int = 25

    @property
    def is_synthesized(self) -> bool:
        """True if this domain was synthesized from flat-layout fallbacks
        rather than loaded from ``data/domains/<handle>/domain.json``.
        Useful for migration logic and diagnostics; never used to gate
        behavior."""
        return not (self.root / "domain.json").exists()


# ───────────────────────────────────────────────────────────────────────────
# Registry
# ───────────────────────────────────────────────────────────────────────────


_DEFAULT_HANDLE = "recetadolce"


class DomainRegistry:
    """Resolves ``Domain`` objects by handle, with synthesized-default fallback."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.domains_root = self.project_root / "data" / "domains"
        self._cache: dict[str, Domain] | None = None

    # ── Public API ─────────────────────────────────────────────────────

    @property
    def default_handle(self) -> str:
        """Handle of the default domain — either configured via
        ``RANKSTEIN_DEFAULT_DOMAIN`` env var, or alphabetically first
        among configured domains, or ``"recetadolce"`` when synthesizing."""
        configured = os.environ.get("RANKSTEIN_DEFAULT_DOMAIN", "").strip()
        if configured:
            return configured
        handles = self._handles()
        return handles[0] if handles else _DEFAULT_HANDLE

    @property
    def default(self) -> Domain:
        """The default ``Domain``."""
        return self.get(self.default_handle)

    def get(self, handle: str | None = None) -> Domain:
        """Resolve a domain by handle. ``None`` or empty string returns the
        default. Raises ``KeyError`` for an unknown non-empty handle."""
        if not handle:
            handle = self.default_handle
        domain = self._all_domains().get(handle)
        if domain is None:
            raise KeyError(
                f"Unknown domain handle: {handle!r}. Available: {sorted(self._all_domains().keys())}"
            )
        return domain

    def all(self) -> list[Domain]:
        """All configured domains, sorted by handle."""
        return [self._all_domains()[h] for h in sorted(self._all_domains())]

    def reload(self) -> None:
        """Drop the cache so subsequent calls re-read disk."""
        self._cache = None

    # ── Internals ──────────────────────────────────────────────────────

    def _handles(self) -> list[str]:
        return sorted(self._all_domains().keys())

    def _all_domains(self) -> dict[str, Domain]:
        if self._cache is None:
            self._cache = self._load_all()
        return self._cache

    def _load_all(self) -> dict[str, Domain]:
        """Load every domain from ``data/domains/*/domain.json``. If none
        exist, synthesize the default domain from the flat legacy layout."""
        domains: dict[str, Domain] = {}
        if self.domains_root.is_dir():
            for child in sorted(self.domains_root.iterdir()):
                if not child.is_dir():
                    continue
                manifest = child / "domain.json"
                if not manifest.is_file():
                    continue
                try:
                    domains[child.name] = self._load_from_manifest(child, manifest)
                except Exception as e:
                    import logging

                    logging.getLogger("rankstein.domain").warning(
                        "Skipping malformed domain manifest at %s: %s", manifest, e
                    )

        if not domains:
            # Phase 1: zero-migration synthesized default from flat layout.
            domains[_DEFAULT_HANDLE] = self._synthesize_default()

        # Ensure recetadolce is ALWAYS available as a fallback/default
        # during the Phase 1 -> Phase 2 transition.
        if _DEFAULT_HANDLE not in domains:
            domains[_DEFAULT_HANDLE] = self._synthesize_default()

        return domains

    def _load_from_manifest(self, root: Path, manifest_path: Path) -> Domain:
        """Build a ``Domain`` from a ``data/domains/<handle>/domain.json``."""
        from dotenv import load_dotenv

        _env_path = self.project_root / ".env"
        if _env_path.exists():
            load_dotenv(_env_path, override=False)

        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        handle = data["handle"]
        email_env = data.get("pinterest_email_env", "PINTEREST_EMAIL")
        email = os.environ.get(email_env, "")

        password_env = data.get("pinterest_password_env", "PINTEREST_PASSWORD")
        password = SecretStr(os.environ.get(password_env, ""))

        key_env = data.get("supabase_key_env", "SUPABASE_SERVICE_ROLE_KEY")
        key_val = os.environ.get(key_env, "")
        supabase_key = SecretStr(key_val)

        if not key_val and os.environ.get("RANKSTEIN_DEBUG_ENV_LOAD", "").lower() in {"1", "true", "yes"}:
            import sys

            sys.stderr.write(
                f"DEBUG: DOMAIN [{handle}]: Credential env var '{key_env}' is EMPTY or NOT FOUND in os.environ (keys count={len(os.environ)}). Env path: {_env_path.absolute()}\n"
            )

        return Domain(
            handle=handle,
            domain=data["domain"],
            display_name=data.get("display_name", handle.title()),
            language=data.get("language", "es"),
            niche=data.get("niche", ""),
            root=root,
            keywords_file=root / data.get("keywords_file", "keywords.md"),
            sessions_dir=root / data.get("sessions_dir", "sessions"),
            output_dir=root / data.get("output_dir", "output"),
            branding_dir=root / data.get("branding_dir", "branding"),
            pinterest_email=email,
            pinterest_password=password,
            supabase_url=data.get("supabase_url", "https://xjvmnmfczvwkjiasirsl.supabase.co"),
            supabase_service_role_key=supabase_key,
            categories=tuple(data.get("categories", ())),
            boards_default=dict(data.get("boards_default", {})),
            primary_color=data.get("primary_color", "#D4AF37"),
            accent_color=data.get("accent_color", "#1a1a1a"),
            brand_name_short=data.get("brand_name_short", "RECETA DOLCE | 2026"),
            cta_text=data.get("cta_text", "TOCA PARA VER LA RECETA"),
            daily_pin_budget=int(data.get("daily_pin_budget", 25)),
        )

    def _synthesize_default(self) -> Domain:
        """Build the recetadolce domain from the existing flat-layout paths
        so Phase 1 lands without any file moves. The `Domain.is_synthesized`
        property returns True for this object — useful for migration logic."""
        settings = get_settings()
        # The synthesized default lives "at the project root" — the legacy
        # flat dirs ARE the domain dirs. ``root`` points at project root so
        # the per-domain paths below still resolve via the standard
        # path-join idiom in callers.
        root = self.project_root
        return Domain(
            handle=_DEFAULT_HANDLE,
            domain="recetadolce.com",
            display_name="Receta Dolce",
            language="es",
            niche="recetas españolas tradicionales y modernas",
            root=root,
            keywords_file=root / "memory" / "keywords.md",
            sessions_dir=root / "data" / "sessions",
            output_dir=root / "nanobanana-output",
            branding_dir=root / "branding",
            pinterest_email=settings.pinterest_email,
            pinterest_password=settings.pinterest_password,
            supabase_url=settings.supabase_url,
            supabase_service_role_key=settings.supabase_service_role_key,
            categories=_RECETADOLCE_CATEGORIES,
            boards_default=dict(_RECETADOLCE_BOARDS_DEFAULT),
            primary_color="#D4AF37",
            accent_color="#1a1a1a",
            brand_name_short="RECETA DOLCE | 2026",
            cta_text="TOCA PARA VER LA RECETA",
            daily_pin_budget=300,  # legacy single-account budget — preserved
        )


# ── Module-level singleton ─────────────────────────────────────────────────


def get_registry() -> DomainRegistry:
    """Project-wide ``DomainRegistry`` rooted at the project root."""
    project_root = Path(__file__).resolve().parent.parent
    return _get_registry(project_root)


def reload_registry() -> DomainRegistry:
    """Clear and recreate the project-wide registry singleton."""
    _get_registry.cache_clear()
    return get_registry()


@lru_cache(maxsize=1)
def _get_registry(project_root: Path) -> DomainRegistry:
    return DomainRegistry(project_root)

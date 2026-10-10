"""
RankStein Pinterest Automation — Unified Configuration
Production-ready central config with env validation and defaults.
"""

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from .browser_utils import DEFAULT_BROWSER_MAP, FIREFOX_USER_AGENT, normalize_browser_type

logger = logging.getLogger("rankstein.config")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load environment variables from .env and OVERRIDE explicit process env.
# This ensures that changes made to the .env file during a session are respected.
load_dotenv(PROJECT_ROOT / ".env", override=False)

DATA_DIR = PROJECT_ROOT / "data"
SESSION_DIR = DATA_DIR / "sessions"
LOG_DIR = DATA_DIR / "logs"
QUEUE_DIR = DATA_DIR / "queue"
HEALING_CACHE_DIR = DATA_DIR / "healing_cache"

for d in [DATA_DIR, SESSION_DIR, LOG_DIR, QUEUE_DIR, HEALING_CACHE_DIR]:
    d.mkdir(parents=True, exist_ok=True)


LIVE_BOARD_ALIASES = {
    "Arroces y Paellas": "Arroces",
    "Postres y Dulces": "Chocolate",
    "Ensaladas y Saludable": "ENSALADES",
    "Aperitivos y Tapas": "Aperitivos",
    "Carnes y Tradición": "Carnes",
    "Carnes y TradiciÃ³n": "Carnes",
    "Pescados y Mariscos": "Pescados",
    "Recetas Españolas": "Aperitivos",
    "Recetas EspaÃ±olas": "Aperitivos",
    "recetas": "Aperitivos",
}
LIVE_BOARD_NAMES = {"Aperitivos", "Arroces", "Carnes", "Chocolate", "ENSALADES", "Fresas", "Pescados"}


def normalize_board_name(board_name: str | None) -> str:
    """Map legacy board labels to the current live Pinterest board names."""
    value = str(board_name or "").strip()
    if not value:
        return "Aperitivos"
    return LIVE_BOARD_ALIASES.get(value, value if value in LIVE_BOARD_NAMES else "Aperitivos")


def resolve_account_board_name(board_name: str | None, account_handle: str | None) -> str:
    """Resolve a canonical board label to the exact live label for one account."""
    canonical = normalize_board_name(board_name)
    handle = str(account_handle or "").strip()
    if not handle:
        return canonical
    try:
        mappings = json.loads(os.environ.get("PINTEREST_ACCOUNT_BOARD_MAP", "{}"))
    except (TypeError, json.JSONDecodeError):
        return canonical
    account_mapping = mappings.get(handle, {}) if isinstance(mappings, dict) else {}
    resolved = account_mapping.get(canonical) if isinstance(account_mapping, dict) else None
    return str(resolved).strip() if resolved else canonical


@dataclass
class RateLimitConfig:
    base_delay_seconds: float = 20.0
    jitter_percent: float = 0.35
    max_delay_seconds: float = 180.0
    daily_pin_limit: int = 50
    hourly_pin_limit: int = 20
    burst_limit: int = 2
    cooldown_after_failures: int = 5
    cooldown_duration_minutes: int = 5

    def __post_init__(self):
        def _env_float(name, default):
            val = os.environ.get(name)
            return float(val) if val else default

        def _env_int(name, default):
            val = os.environ.get(name)
            return int(val) if val else default

        self.base_delay_seconds = _env_float("PINTEREST_BASE_DELAY", self.base_delay_seconds)
        self.hourly_pin_limit = _env_int("PINTEREST_HOURLY_LIMIT", self.hourly_pin_limit)
        self.burst_limit = _env_int("PINTEREST_BURST_LIMIT", self.burst_limit)
        self.daily_pin_limit = _env_int("PINTEREST_DAILY_LIMIT", self.daily_pin_limit)


@dataclass
class BrowserConfig:
    headless: bool = True  # MANDATORY: Always run in headless mode as per system requirements
    viewport_width: int = 1440
    viewport_height: int = 900
    locale: str = "es-ES"
    user_agent: str = FIREFOX_USER_AGENT
    session_name: str = "pinterest_rida_v7"
    max_sessions: int = 2
    session_ttl_minutes: int = 120
    launch_timeout_ms: int = 120000
    navigation_timeout_ms: int = 120000
    action_timeout_ms: int = 60000

    def __post_init__(self):
        self.headless = True
        try:
            self.max_sessions = max(
                1,
                min(
                    int(os.environ.get("PINTEREST_MAX_SESSIONS", str(self.max_sessions))),
                    int(os.environ.get("PINTEREST_MAX_WORKERS", "3")),
                ),
            )
            self.session_ttl_minutes = max(
                30,
                int(
                    os.environ.get(
                        "PINTEREST_SESSION_TTL_MINUTES",
                        str(self.session_ttl_minutes),
                    )
                ),
            )
        except ValueError:
            pass


@dataclass
class SelfHealingConfig:
    enabled: bool = True
    llm_model: str = "gemini-3.1-pro-preview"
    max_selector_length: int = 150
    cache_ttl_hours: int = 168
    fallback_to_js: bool = True
    dom_element_limit: int = 50


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 20
    recovery_timeout_seconds: int = 30
    half_open_max_calls: int = 5
    success_threshold_to_close: int = 3
    save_interval_seconds: int = 60


@dataclass
class HealthConfig:
    heartbeat_interval_seconds: int = 30
    max_stale_seconds: int = 120
    disk_space_threshold_gb: float = 0.5
    log_size_threshold_mb: float = 100.0
    session_max_age_days: int = 30


@dataclass
class SupervisorConfig:
    worker_count: int = 2
    restart_on_crash: bool = True
    max_restarts: int = 10
    restart_window_seconds: int = 3600
    graceful_shutdown_seconds: int = 30
    watch_interval_seconds: int = 5

    def __post_init__(self):
        env_workers = os.environ.get("PINTEREST_WORKER_COUNT")
        if not env_workers and os.environ.get("PINTEREST_ALLOW_LEGACY_WORKER_COUNT", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            env_workers = os.environ.get("WORKER_COUNT")
        if env_workers:
            try:
                # Pinterest browser automation is session-bound. Large worker
                # counts create lock convoys, page navigation races, and DLQ
                # storms. Keep unattended concurrency safely bounded unless the
                # operator explicitly raises PINTEREST_MAX_WORKERS.
                max_workers = int(os.environ.get("PINTEREST_MAX_WORKERS", "10"))
                self.worker_count = max(1, min(int(env_workers), max_workers))
            except ValueError:
                pass


@dataclass
class PinterestCredentials:
    email: str = ""
    password: str = ""
    session_name: str | None = None
    browser: str | None = None

    def __post_init__(self):
        # Default to singleton env vars if not provided
        if not self.email:
            self.email = os.environ.get("PINTEREST_EMAIL", "")
        if not self.password:
            self.password = os.environ.get("PINTEREST_PASSWORD", "")

    @property
    def valid(self) -> bool:
        return bool(self.email and self.password)


@dataclass
class SupabaseConfig:
    url: str = "https://xjvmnmfczvwkjiasirsl.supabase.co"
    key: str = ""
    bucket: str = "recipe-images"

    def __post_init__(self):
        self.url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", self.url)
        self.key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", self.key)

    @property
    def valid(self) -> bool:
        return bool(self.key)


@dataclass
class AutomationConfig:
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    self_healing: SelfHealingConfig = field(default_factory=SelfHealingConfig)
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    health: HealthConfig = field(default_factory=HealthConfig)
    supervisor: SupervisorConfig = field(default_factory=SupervisorConfig)
    credentials: PinterestCredentials = field(default_factory=PinterestCredentials)
    supabase: SupabaseConfig = field(default_factory=SupabaseConfig)
    accounts: dict[str, PinterestCredentials] = field(default_factory=dict)
    boards: dict = field(
        default_factory=lambda: {
            "Arroces": ["arroz", "paella", "fideua", "bogavante", "marisco", "caldoso"],
            "Chocolate": [
                "churros",
                "tarta",
                "helado",
                "postre",
                "mousse",
                "galletas",
                "fresa",
                "chocolate",
                "bizcocho",
                "vainilla",
                "donuts",
                "crema",
                "mermelada",
                "mantequilla",
            ],
            "ENSALADES": [
                "ensalada",
                "vegetariano",
                "quinoa",
                "espina",
                "cesar",
                "griega",
                "aguacate",
                "campera",
                "saludable",
                "fresca",
            ],
            "Aperitivos": [
                "pasabocas",
                "tapa",
                "aperitivo",
                "guacamole",
                "bravas",
                "ajillo",
                "croquetas",
                "jamon",
                "pulpo",
                "tortilla",
                "chips",
                "receta",
                "comida",
                "cocina",
                "dumpling",
            ],
            "Carnes": [
                "pollo",
                "carne",
                "cocido",
                "gazpacho",
                "tradicional",
                "abuela",
                "casera",
                "iberico",
            ],
            "Fresas": ["fresa", "fresas", "fruta"],
            "Pescados": ["pescado", "pescados", "merluza", "bacalao", "salmon", "salmón", "atun", "atún"],
        }
    )
    default_board: str = "Aperitivos"

    def __post_init__(self):
        # Load accounts from PINTEREST_ACCOUNTS env var if available
        raw_accounts = os.environ.get("PINTEREST_ACCOUNTS")
        if raw_accounts:
            try:
                data = self._parse_accounts_json(raw_accounts)
            except Exception:
                data = None

            if isinstance(data, dict):
                data = data.get("accounts")

            if data and isinstance(data, list):
                default_browser = normalize_browser_type(
                    os.environ.get("PINTEREST_DEFAULT_BROWSER") or os.environ.get("PINTEREST_BROWSER"),
                    "chromium",
                )
                for idx, acc in enumerate(data, 1):
                    if not isinstance(acc, dict):
                        continue
                    session_name = acc.get("session") or acc.get("session_dir") or acc.get("name")
                    name = str(acc.get("name") or session_name or f"account_{idx}").strip()
                    if not name:
                        continue
                    session_leaf = Path(str(session_name or name)).name
                    browser = normalize_browser_type(
                        acc.get("browser")
                        or DEFAULT_BROWSER_MAP.get(name)
                        or DEFAULT_BROWSER_MAP.get(session_leaf)
                        or default_browser,
                        default_browser,
                    )
                    self.accounts[name] = PinterestCredentials(
                        email=acc.get("email") or os.environ.get(str(acc.get("email_env", "")), ""),
                        password=acc.get("password") or os.environ.get(str(acc.get("password_env", "")), ""),
                        session_name=session_leaf,
                        browser=browser,
                    )

        self._load_indexed_accounts()
        self._load_default_account_alias()
        self._load_accounts_file()

    def _load_accounts_file(self) -> None:
        if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("PINTEREST_ACCOUNTS_FILE"):
            return
        accounts_file_path = os.environ.get("PINTEREST_ACCOUNTS_FILE")
        accounts_file = (
            Path(accounts_file_path) if accounts_file_path else (DATA_DIR / "pinterest_accounts.json")
        )
        if not accounts_file.is_file():
            return
        try:
            data = json.loads(accounts_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to parse %s: %s", accounts_file, exc)
            return

        default_browser = normalize_browser_type(
            os.environ.get("PINTEREST_DEFAULT_BROWSER") or os.environ.get("PINTEREST_BROWSER"), "chromium"
        )
        acc_list = data.get("accounts")
        if isinstance(acc_list, dict):
            acc_list = list(acc_list.values())
        if isinstance(acc_list, list):
            for acc in acc_list:
                if not isinstance(acc, dict):
                    continue
                name = str(acc.get("handle") or acc.get("name") or "").strip()
                if not name:
                    continue
                session_leaf = Path(str(acc.get("session_name") or acc.get("session") or name)).name
                browser = normalize_browser_type(
                    acc.get("browser")
                    or DEFAULT_BROWSER_MAP.get(name)
                    or DEFAULT_BROWSER_MAP.get(session_leaf)
                    or default_browser,
                    default_browser,
                )
                self.accounts[name] = PinterestCredentials(
                    email=acc.get("email") or os.environ.get(str(acc.get("email_env", "")), ""),
                    password=acc.get("password") or os.environ.get(str(acc.get("password_env", "")), ""),
                    session_name=session_leaf,
                    browser=browser,
                )

    @staticmethod
    def _parse_accounts_json(raw_accounts: str):
        raw = raw_accounts.strip()
        if (raw.startswith("'") and raw.endswith("'")) or (raw.startswith('"') and raw.endswith('"')):
            raw = raw[1:-1].strip()
        try:
            return json.loads(raw)
        except Exception:
            return json.loads(raw.replace('\\"', '"'))

    def _load_indexed_accounts(self) -> None:
        default_browser = normalize_browser_type(
            os.environ.get("PINTEREST_DEFAULT_BROWSER") or os.environ.get("PINTEREST_BROWSER"), "chromium"
        )
        for idx in range(1, 21):
            prefix = f"PINTEREST_ACCOUNT_{idx}_"

            if not any(
                os.environ.get(prefix + key)
                for key in ("SESSION", "SESSION_DIR", "NAME", "EMAIL", "PASSWORD", "BROWSER")
            ):
                continue
            session_name = (
                os.environ.get(prefix + "SESSION_DIR")
                or os.environ.get(prefix + "SESSION")
                or os.environ.get(prefix + "NAME")
                or f"account_{idx}"
            )
            session_leaf = Path(session_name).name
            name = os.environ.get(prefix + "NAME") or session_leaf
            browser = normalize_browser_type(
                os.environ.get(prefix + "BROWSER")
                or DEFAULT_BROWSER_MAP.get(name)
                or DEFAULT_BROWSER_MAP.get(session_leaf)
                or default_browser,
                default_browser,
            )
            self.accounts[name] = PinterestCredentials(
                email=os.environ.get(prefix + "EMAIL", ""),
                password=os.environ.get(prefix + "PASSWORD", ""),
                session_name=session_leaf,
                browser=browser,
            )

    def _load_default_account_alias(self) -> None:
        if not self.credentials.valid:
            return
        if any(acc.email == self.credentials.email for acc in self.accounts.values()):
            return

        handle = (
            os.environ.get("PINTEREST_DEFAULT_ACCOUNT_HANDLE")
            or os.environ.get("PINTEREST_ACCOUNT_HANDLE")
            or "rida"
        ).strip()
        if not handle or handle in self.accounts:
            return

        session_name = os.environ.get("PINTEREST_DEFAULT_SESSION") or self.configured_session_name
        session_leaf = Path(session_name).name
        default_browser = normalize_browser_type(os.environ.get("PINTEREST_BROWSER"), "firefox")
        browser = normalize_browser_type(
            os.environ.get("PINTEREST_DEFAULT_BROWSER")
            or DEFAULT_BROWSER_MAP.get(handle)
            or DEFAULT_BROWSER_MAP.get(session_leaf)
            or default_browser,
            default_browser,
        )
        self.accounts[handle] = PinterestCredentials(
            email=self.credentials.email,
            password=self.credentials.password,
            session_name=session_leaf,
            browser=browser,
        )

    @property
    def configured_session_name(self) -> str:
        browser_config = self.browser
        if isinstance(browser_config, dict):
            return str(browser_config.get("session_name") or BrowserConfig().session_name)
        return browser_config.session_name

    @classmethod
    def from_file(cls, path: Path | None = None) -> "AutomationConfig":
        path = path or DATA_DIR / "automation_config.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                # Filter out accounts if it's already in JSON (prefer env)
                if "accounts" in data:
                    del data["accounts"]
                return cls(**data)
            except Exception:
                pass
        return cls()

    def save(self, path: Path | None = None):
        path = path or DATA_DIR / "automation_config.json"
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")


# Global singleton config instance
_config: AutomationConfig | None = None


def get_config() -> AutomationConfig:
    global _config
    if _config is None:
        _config = AutomationConfig.from_file()
    return _config


def reload_config() -> AutomationConfig:
    global _config
    _config = AutomationConfig.from_file()
    return _config

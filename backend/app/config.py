"""Runtime settings. All secrets come from environment variables only."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


class Settings:
    def __init__(self) -> None:
        self.app_env = _env("APP_ENV", "development")
        self.is_production = self.app_env == "production"
        self.test_mode = _env("AMS_TEST_MODE") == "1" and not self.is_production
        # Only for sandboxes whose DNS returns synthetic "fake-IP" addresses (e.g. 198.18.0.0/15) for public hosts.
        # Never set on a real deployment: it weakens the SSRF guard for the listed ranges. Ignored in production.
        self.ssrf_extra_allowed_cidrs = [c.strip() for c in _env("AMS_SSRF_ALLOW_CIDRS").split(",") if c.strip()] \
            if not self.is_production else []
        db = _env("DATABASE_URL")
        if db.startswith("postgres://"):
            db = "postgresql://" + db[len("postgres://"):]
        if db.startswith("postgresql://"):
            db = "postgresql+psycopg://" + db[len("postgresql://"):]
        self.database_url = db or f"sqlite:///{(BASE_DIR.parent / 'ams_local.db').as_posix()}"
        self.secret_key = _env("SECRET_KEY") or secrets.token_hex(32)
        self.admin_username = _env("ADMIN_USERNAME", "admin")
        self.admin_password = _env("ADMIN_PASSWORD")
        self.session_hours = int(_env("SESSION_HOURS", "8") or 8)
        self.static_dir = Path(_env("STATIC_DIR") or (BASE_DIR.parent.parent / "frontend" / "dist"))
        self.contact = _env("CONTACT_EMAIL", "compliance-screening@example.invalid")
        self.user_agent = f"AdverseMediaScreening/1.0 (+compliance research; contact {self.contact})"
        # Optional keyed providers
        self.keys = {
            "companies_house": _env("COMPANIES_HOUSE_API_KEY"),
            "courtlistener": _env("COURTLISTENER_API_TOKEN"),
            "newsapi": _env("NEWSAPI_KEY"),
            "gnews": _env("GNEWS_API_KEY"),
            "brave": _env("BRAVE_API_KEY"),
            "serper": _env("SERPER_API_KEY"),
            "bing_web": _env("BING_SEARCH_KEY"),
        }
        self.llm_api_key = _env("LLM_API_KEY")
        self.llm_base_url = _env("LLM_BASE_URL", "https://api.x.ai/v1").rstrip("/")
        self.llm_model = _env("LLM_MODEL", "grok-3-mini")
        self.llm_enabled = bool(self.llm_api_key)


KEY_ENV = {"companies_house": "COMPANIES_HOUSE_API_KEY", "courtlistener": "COURTLISTENER_API_TOKEN",
           "newsapi": "NEWSAPI_KEY", "gnews": "GNEWS_API_KEY", "brave": "BRAVE_API_KEY", "serper": "SERPER_API_KEY",
           "bing_web": "BING_SEARCH_KEY"}

settings = Settings()

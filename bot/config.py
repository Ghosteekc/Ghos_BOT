import logging
import os

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


def _running_on_railway() -> bool:
    return bool(
        os.environ.get("RAILWAY_ENVIRONMENT")
        or os.environ.get("RAILWAY_PROJECT_ID")
        or os.environ.get("RAILWAY_SERVICE_ID")
    )


def normalize_database_url(url: str) -> str:
    """Railway/Heroku give postgres://… — SQLAlchemy async needs postgresql+asyncpg://…"""
    u = (url or "").strip()
    if not u:
        return "sqlite+aiosqlite:///./cr_bot.db"
    if u.startswith("postgres://"):
        u = "postgresql://" + u.removeprefix("postgres://")
    scheme, sep, rest = u.partition("://")
    if not sep:
        return u
    if scheme in {"postgresql", "postgres"} and "+asyncpg" not in scheme:
        return f"postgresql+asyncpg://{rest}"
    return u


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
    )

    bot_token: str
    clash_royale_api_key: str
    clash_royale_api_base: str = "https://api.clashroyale.com/v1"
    clash_royale_proxy_secret: str | None = None
    database_url: str = "sqlite+aiosqlite:///./cr_bot.db"
    trial_days: int = 30
    subscription_price_stars: int = 250
    sync_interval_minutes: int = 60
    # Задержка только для sync боёв пользователей (не для top/meta warmup).
    sync_startup_delay_sec: int = 45
    sync_battlelog_min_interval_sec: int = 300
    sync_cr_api_timeout_sec: int = 55
    sync_shutdown_timeout_sec: int = 30
    # Сразу после старта API греть cards/top/meta в фоне.
    startup_warmup_enabled: bool = True
    cr_api_timeout_sec: int = 15
    cr_api_battlelog_timeout_sec: int = 28
    cr_api_retry_max: int = 3
    cr_api_retry_base_delay_sec: float = 1.0
    admin_telegram_id: int | None = None
    admin_telegram_ids: str = ""
    # Public @username without @ — used for referral deep links (t.me/<bot>?start=ref_…)
    bot_username: str = ""
    # Referral Credits v2
    referral_discount_percent: int = 15  # 10–15 recommended; invitee first-purchase discount
    referral_discount_window_days: int = 30
    referral_credits_reward: int = 10
    credits_max_share_percent: int = 50  # never cover more than this % with Credits
    webapp_url: str = "https://your-domain.com"
    support_username: str | None = None
    api_host: str = "0.0.0.0"
    # Local/dev: API_PORT. Railway always injects PORT — preferred in _apply_platform_defaults.
    api_port: int = Field(default=8080, validation_alias=AliasChoices("API_PORT", "PORT"))
    # Localtunnel is for local/dev only. On Railway default is off unless TUNNEL_AUTO_START=true.
    tunnel_auto_start: bool = True
    tunnel_subdomain: str = "ghosteekcr"
    tunnel_skip_loca_lt_check: bool = False
    init_data_max_age_seconds: int = 86400
    init_data_clock_skew_seconds: int = 60
    meta_refresh_hours: int = 6
    meta_top_players_scan: int = 20
    meta_seed_tags: str = ""
    # Persistent meta collector (league / trophy road). Independent from in-memory meta_analyzer.
    meta_collector_interval_minutes: int = 180
    meta_collector_startup_delay_sec: int = 90
    meta_collector_players: int = 40
    meta_collector_concurrency: int = 4
    meta_min_games: int = 5
    meta_trophy_min: int = 10000
    meta_history_days: int = 14
    meta_ranking_limit: int = 16

    # Ghosteek AI response backend: qwen | groq | ollama | template
    # LLM errors fall back to TemplateGenerator automatically.
    ghosteek_ai_backend: str = "qwen"
    # auto = agent if provider.supports_tools() else planner
    # agent = LLM Tool Calling (Planner = recommendation only)
    # planner = INTENT_TOOL_MAP → ToolCaller → LLM/template text
    ghosteek_ai_mode: str = "auto"

    # Local Ollama backend (native /api/chat). Independent from LLM_* cloud settings.
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3:8b"
    ollama_timeout: float = 120.0
    # Local renderer: чуть живее голос; grounding держит FACTS + validator.
    ollama_temperature: float = 0.4
    ollama_num_predict: int = 220
    ollama_num_ctx: int = 2048
    # Top-level /api/chat "think" (Qwen3). False = prevent thinking generation.
    ollama_think: bool = False
    # Tool calling via Ollama — off by default for qwen3:8b (use planner path).
    ollama_enable_tools: bool = False

    # OpenAI-compatible LLM (Qwen / DashScope compatible-mode, etc.)
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = "qwen3-235b-a22b-thinking-2507"
    llm_timeout: float = 90.0
    # Лимит completion tokens — компактные ответы тренера
    llm_max_tokens: int = 512
    llm_temperature: float = 0.3

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: object) -> str:
        return normalize_database_url("" if value is None else str(value))

    @model_validator(mode="after")
    def _apply_platform_defaults(self) -> "Settings":
        if _running_on_railway():
            if "TUNNEL_AUTO_START" not in os.environ:
                object.__setattr__(self, "tunnel_auto_start", False)
            # Prefer platform PORT even if API_PORT=8080 was copied from local .env.
            railway_port = (os.environ.get("PORT") or "").strip()
            if railway_port.isdigit():
                object.__setattr__(self, "api_port", int(railway_port))
            db = (self.database_url or "").lower()
            if db.startswith("sqlite"):
                logger.warning(
                    "DATABASE_URL is SQLite on Railway — the container disk is ephemeral, "
                    "so every redeploy wipes users/battles. Add a Postgres plugin and set "
                    "DATABASE_URL=${{Postgres.DATABASE_URL}}, or mount a persistent volume "
                    "for the .db file."
                )
        return self


settings = Settings()


def get_admin_telegram_ids() -> list[int]:
    ids: list[int] = []
    if settings.admin_telegram_id is not None:
        ids.append(settings.admin_telegram_id)
    for part in settings.admin_telegram_ids.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return list(dict.fromkeys(ids))

logger.info("Configuration loaded successfully")

if not settings.bot_token or settings.bot_token == "your_telegram_bot_token":
    logger.warning("BOT_TOKEN is not set or uses default value. Bot will not be able to connect to Telegram.")

if not settings.clash_royale_api_key or settings.clash_royale_api_key == "your_clash_royale_api_key":
    logger.warning("CLASH_ROYALE_API_KEY is not set or uses default value. API calls will fail.")

# Ghosteek AI — backend/mode only (no API keys / prompts / user data).
logger.info(
    "Ghosteek AI config backend=%s mode=%s ollama_model=%s ollama_think=%s "
    "ollama_num_predict=%s ollama_num_ctx=%s ollama_enable_tools=%s",
    (settings.ghosteek_ai_backend or "qwen").strip().lower(),
    (settings.ghosteek_ai_mode or "auto").strip().lower(),
    (settings.ollama_model or "").strip() or "-",
    bool(settings.ollama_think),
    int(settings.ollama_num_predict),
    int(settings.ollama_num_ctx),
    bool(settings.ollama_enable_tools),
)

logger.debug(f"Clash Royale API base: {settings.clash_royale_api_base}")
logger.debug(f"Database URL: {settings.database_url}")
logger.debug(f"Trial days: {settings.trial_days}")
logger.debug(f"Subscription price: {settings.subscription_price_stars} stars")
logger.debug(f"Sync interval: {settings.sync_interval_minutes} minutes")
logger.debug(f"Admin Telegram IDs: {get_admin_telegram_ids()}")
logger.debug(f"WebApp URL: {settings.webapp_url}")

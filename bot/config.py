import logging
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    bot_token: str
    clash_royale_api_key: str
    clash_royale_api_base: str = "https://api.clashroyale.com/v1"
    clash_royale_proxy_secret: str | None = None
    database_url: str = "sqlite+aiosqlite:///./cr_bot.db"
    trial_days: int = 30
    subscription_price_stars: int = 250
    sync_interval_minutes: int = 60
    sync_cr_api_timeout_sec: int = 20
    sync_shutdown_timeout_sec: int = 30
    cr_api_timeout_sec: int = 15
    cr_api_retry_max: int = 3
    cr_api_retry_base_delay_sec: float = 1.0
    admin_telegram_id: int | None = None
    admin_telegram_ids: str = ""
    webapp_url: str = "https://your-domain.com"
    support_username: str | None = None
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    tunnel_auto_start: bool = True
    tunnel_subdomain: str = "ghosteekcr"
    tunnel_skip_loca_lt_check: bool = False
    init_data_max_age_seconds: int = 86400
    init_data_clock_skew_seconds: int = 60
    meta_refresh_hours: int = 6
    meta_top_players_scan: int = 20
    meta_seed_tags: str = ""


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

logger.debug(f"Clash Royale API base: {settings.clash_royale_api_base}")
logger.debug(f"Database URL: {settings.database_url}")
logger.debug(f"Trial days: {settings.trial_days}")
logger.debug(f"Subscription price: {settings.subscription_price_stars} stars")
logger.debug(f"Sync interval: {settings.sync_interval_minutes} minutes")
logger.debug(f"Admin Telegram IDs: {get_admin_telegram_ids()}")
logger.debug(f"WebApp URL: {settings.webapp_url}")

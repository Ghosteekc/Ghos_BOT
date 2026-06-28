import logging
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    bot_token: str
    clash_royale_api_key: str
    clash_royale_api_base: str = "https://api.clashroyale.com/v1"
    database_url: str = "sqlite+aiosqlite:///./cr_bot.db"
    trial_days: int = 3
    subscription_price_stars: int = 250
    sync_interval_minutes: int = 60
    admin_telegram_id: int | None = None
    webapp_url: str = "https://your-domain.com"
    support_username: str | None = None
    api_host: str = "0.0.0.0"
    api_port: int = 8080


settings = Settings()

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
logger.debug(f"Admin Telegram ID: {settings.admin_telegram_id}")
logger.debug(f"WebApp URL: {settings.webapp_url}")

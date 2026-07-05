import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import uvicorn

from bot.api.app import create_app
from bot.config import settings
from bot.handlers import admin, player, start, support
from bot.middleware.subscription import SubscriptionMiddleware
from bot.models.database import init_db
from bot.services import sync_service
from bot.services.clash_api import ClashRoyaleClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def run_api() -> None:
    app = create_app()
    config = uvicorn.Config(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    logger.info("=" * 50)
    logger.info("Starting Ghosteek CR Assistant")
    logger.info("=" * 50)

    logger.info("Initializing database...")
    await init_db()
    logger.info("Database initialized successfully")

    try:
        async with ClashRoyaleClient() as client:
            logger.info("Testing Clash Royale API connection...")
            await client.get_cards()
            logger.info("Clash Royale API connection successful")
    except Exception as e:
        logger.error(f"Failed to connect to Clash Royale API on startup: {e}", exc_info=True)
        logger.warning("Bot will start, but API calls may fail until the issue is resolved")

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())

    dp.include_router(start.router)
    dp.include_router(player.router)
    dp.include_router(support.router)
    dp.include_router(admin.router)

    stop_event = asyncio.Event()
    sync_task = asyncio.create_task(sync_service.run_periodic(stop_event))
    api_task = asyncio.create_task(run_api())

    logger.info(f"Bot and API started (API on {settings.api_host}:{settings.api_port})")
    logger.info("Starting polling...")
    try:
        await dp.start_polling(bot)
    finally:
        logger.info("Shutting down...")
        stop_event.set()
        api_task.cancel()
        await sync_task
        try:
            await api_task
        except asyncio.CancelledError:
            pass
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())

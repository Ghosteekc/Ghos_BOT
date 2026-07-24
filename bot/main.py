import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import uvicorn

from bot.api.app import create_app
from bot.config import settings
from bot.fsm.sqlite_storage import SqliteStorage
from bot.handlers import admin, player, start, support
from bot.middleware.subscription import SubscriptionMiddleware
from bot.models.database import init_db
from bot.services import sync_service
from bot.services.clash_api import ClashRoyaleClient
from bot.services.tunnel_manager import start_tunnel, stop_tunnel_process

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
    storage = SqliteStorage()
    dp = Dispatcher(storage=storage)

    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())

    dp.include_router(start.router)
    dp.include_router(player.router)
    dp.include_router(support.router)
    dp.include_router(admin.router)

    stop_event = asyncio.Event()
    sync_task = asyncio.create_task(sync_service.run_periodic(stop_event))
    api_task = asyncio.create_task(run_api())

    tunnel_proc = None
    if settings.tunnel_auto_start:
        await asyncio.sleep(1.5)
        tunnel_proc = await asyncio.to_thread(
            start_tunnel,
            subdomain=settings.tunnel_subdomain,
            port=settings.api_port,
            skip_loca_lt_check=settings.tunnel_skip_loca_lt_check,
        )

    logger.info(f"Bot and API started (API on {settings.api_host}:{settings.api_port})")
    if settings.tunnel_auto_start:
        logger.info(
            "Tunnel auto-start enabled -> https://%s.loca.lt",
            settings.tunnel_subdomain,
        )
    logger.info("Starting polling...")
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhook cleared — using long polling")
    try:
        await dp.start_polling(bot)
    finally:
        logger.info("Shutting down...")
        stop_event.set()
        if settings.tunnel_auto_start:
            await asyncio.to_thread(stop_tunnel_process, tunnel_proc)
        api_task.cancel()
        sync_task.cancel()
        try:
            await asyncio.wait_for(sync_task, timeout=settings.sync_shutdown_timeout_sec)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            logger.warning("Battle sync task did not stop within timeout")
        try:
            await api_task
        except asyncio.CancelledError:
            pass
        await storage.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())

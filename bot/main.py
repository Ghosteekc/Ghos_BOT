import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import uvicorn

from bot.api.app import create_app
from bot.config import settings
from bot.fsm.sqlite_storage import SqliteStorage
from bot.handlers import admin, player, start, subscription, support
from bot.middleware.subscription import SubscriptionMiddleware
from bot.models.database import init_db
from bot.services import sync_service
from bot.services import weekly_digest
from bot.services.pro import reminders as pro_reminders
from bot.services import meta_collector
from bot.services.clash_api import ClashRoyaleClient
from bot.services.startup_warmup import warmup_caches
from bot.services.tunnel_manager import start_tunnel, stop_tunnel_process

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def run_api(bot: Bot) -> None:
    app = create_app()
    app.state.bot = bot
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

    # Menu Button: только MenuButtonWebApp + WebAppInfo (не url-кнопка).
    webapp = (settings.webapp_url or "").strip().rstrip("/")
    if webapp and "your-domain" not in webapp and webapp.startswith("https://"):
        try:
            from aiogram.types import MenuButtonWebApp, WebAppInfo

            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="Ghosteek",
                    web_app=WebAppInfo(url=webapp),
                )
            )
            logger.info("Chat menu WebApp button set -> %s", webapp)
        except Exception as e:
            logger.warning("Failed to set chat menu WebApp button: %s", e)
    else:
        logger.warning(
            "Skip chat menu WebApp button: WEBAPP_URL missing or invalid (%r)",
            webapp,
        )

    storage = SqliteStorage()
    dp = Dispatcher(storage=storage)

    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())

    dp.include_router(start.router)
    dp.include_router(player.router)
    dp.include_router(support.router)
    dp.include_router(admin.router)
    dp.include_router(subscription.router)

    stop_event = asyncio.Event()
    sync_task = asyncio.create_task(sync_service.run_periodic(stop_event))
    digest_task = asyncio.create_task(weekly_digest.run_periodic(bot, stop_event))
    pro_reminder_task = asyncio.create_task(pro_reminders.run_periodic(bot, stop_event))
    meta_task = asyncio.create_task(meta_collector.run_periodic(stop_event))
    api_task = asyncio.create_task(run_api(bot))
    warmup_task: asyncio.Task | None = None
    if settings.startup_warmup_enabled:
        # Не ждём окончания: polling/API поднимаются сразу, кеши догоняют в фоне.
        warmup_task = asyncio.create_task(warmup_caches())

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
        digest_task.cancel()
        pro_reminder_task.cancel()
        meta_task.cancel()
        if warmup_task and not warmup_task.done():
            warmup_task.cancel()
        try:
            await asyncio.wait_for(sync_task, timeout=settings.sync_shutdown_timeout_sec)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            logger.warning("Battle sync task did not stop within timeout")
        try:
            await asyncio.wait_for(digest_task, timeout=10)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            logger.warning("Weekly digest task did not stop within timeout")
        try:
            await asyncio.wait_for(pro_reminder_task, timeout=10)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            logger.warning("Pro reminder task did not stop within timeout")
        try:
            await asyncio.wait_for(meta_task, timeout=15)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            logger.warning("Meta collector task did not stop within timeout")
        if warmup_task:
            try:
                await warmup_task
            except asyncio.CancelledError:
                pass
        try:
            await api_task
        except asyncio.CancelledError:
            pass
        await storage.close()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())

import logging
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import get_admin_telegram_ids
from bot.models.database import async_session
from bot.services.beta_invite import (
    MAX_BETA_DAYS,
    MIN_BETA_DAYS,
    create_beta_invite,
    parse_test_command_days,
)
from bot.services.clash_api import SubscriptionService
from bot.services.sync_service import sync_all_once
from bot.user_errors import log_error, user_message

logger = logging.getLogger(__name__)

router = Router()

_TEST_INVITE_RE = re.compile(r"^/test_(\d+)(?:@\w+)?(?:\s|$)", re.IGNORECASE)


def _is_admin(user_id: int) -> bool:
    return user_id in get_admin_telegram_ids()


@router.message(F.text.regexp(_TEST_INVITE_RE))
async def cmd_test_invite(message: Message) -> None:
    """Admin-only: /test_30 → one-time beta invite link for 30 days of Pro."""
    if message.from_user is None:
        return
    if not _is_admin(message.from_user.id):
        await message.answer("🔒 Команда доступна только администратору.")
        return

    days = parse_test_command_days(message.text)
    if days is None:
        await message.answer(
            f"Укажите срок от {MIN_BETA_DAYS} до {MAX_BETA_DAYS} дней.\n"
            "Пример: <code>/test_30</code>"
        )
        return

    bot_username = None
    try:
        me = await message.bot.get_me()
        bot_username = me.username
    except Exception:
        logger.warning("Failed to resolve bot username for beta invite", exc_info=True)

    async with async_session() as session:
        result = await create_beta_invite(
            session,
            created_by_telegram_id=message.from_user.id,
            days=days,
            bot_username=bot_username,
        )

    await message.answer(
        f"🧪 <b>Ссылка для бета-тестера</b>\n\n"
        f"Срок: <b>{days}</b> дн. Ghosteek Pro\n"
        f"Одноразовая — после перехода аннулируется.\n\n"
        f"<code>{result.link}</code>"
    )


@router.message(Command("admin_sub"))
async def cmd_admin_sub(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("🔒 Команда доступна только администратору.")
        return

    async with async_session() as session:
        sub_service = SubscriptionService(session)
        user = await sub_service.get_or_create_user(message.from_user.id)
        await sub_service.activate_unlimited_subscription(user)

    await message.answer(
        "♾️ Безлимитная подписка активирована для вашего аккаунта.\n"
        "Откройте Mini App через Menu Button."
    )


@router.message(Command("deckshop_check"))
async def cmd_deckshop_check(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer("🔒 Команда доступна только администратору.")
        return

    from bot.services.deckshop_data import format_deckshop_status

    text = format_deckshop_status()
    await message.answer("📦 DeckShop\n" + text.replace("DeckShop snapshot", "Snapshot"))


@router.message(Command("sync_now"))
async def cmd_sync_now(message: Message) -> None:
    user_id = message.from_user.id
    if not _is_admin(user_id):
        await message.answer("🔒 Только администратор может запускать синхронизацию.")
        return

    await message.answer("⏳ Запускаю синхронизацию боёв для всех пользователей...")

    try:
        res = await sync_all_once()
        if not res:
            await message.answer("Готово — новых боёв не найдено для всех пользователей.")
            return

        lines = ["Синхронизация завершена:"]
        for tag, cnt in res.items():
            lines.append(f"• {tag}: {cnt} новых")
        await message.answer("\n".join(lines))
    except Exception as exc:
        log_error(logger, "E080", "Admin sync_now failed", exc=exc, user_id=user_id)
        await message.answer(user_message("E080"))

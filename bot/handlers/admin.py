from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import get_admin_telegram_ids
from bot.models.database import async_session
from bot.services.clash_api import SubscriptionService
from bot.services.sync_service import sync_all_once

router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in get_admin_telegram_ids()


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
    except Exception as e:
        await message.answer(f"Ошибка при синхронизации: {e}")

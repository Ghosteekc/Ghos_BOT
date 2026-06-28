from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import settings
from bot.services.sync_service import sync_all_once

router = Router()


@router.message(Command("sync_now"))
async def cmd_sync_now(message: Message) -> None:
    user_id = message.from_user.id
    if settings.admin_telegram_id is not None and user_id != settings.admin_telegram_id:
        await message.answer("🔒 Только администратор может запускать синхронизацию.")
        return

    if settings.admin_telegram_id is None:
        await message.answer("⚠️ Внимание: команда `/sync_now` не защищена (ADMIN_TELEGRAM_ID не задан). Выполняю синхронизацию.")
    else:
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

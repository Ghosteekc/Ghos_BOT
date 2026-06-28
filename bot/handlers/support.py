from aiogram import Router, F
from aiogram.types import Message

from bot.config import settings

router = Router()


@router.message(F.text == "💬 Поддержка")
async def cmd_support(message: Message) -> None:
    if settings.support_username:
        username = settings.support_username.lstrip("@")
        await message.answer(
            "💬 <b>Поддержка</b>\n\n"
            f"Напишите нам: @{username}\n\n"
            "Опишите проблему и приложите скриншот, если возможно."
        )
        return

    if settings.admin_telegram_id:
        await message.answer(
            "💬 <b>Поддержка</b>\n\n"
            "Опишите вашу проблему в следующем сообщении — мы передадим её администратору."
        )
        return

    await message.answer(
        "💬 <b>Поддержка</b>\n\n"
        "Контакт поддержки не настроен. Укажите SUPPORT_USERNAME в .env"
    )

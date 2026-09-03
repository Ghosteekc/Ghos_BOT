from html import escape

from aiogram import Router, F
from aiogram.types import Message

from bot.config import settings
from bot.user_errors import user_message

router = Router()


def _support_url(value: str) -> str:
    """Return a Telegram URL from either a username or a configured link."""
    support = value.strip()
    if support.startswith(("https://", "http://", "tg://")):
        return support
    if support.startswith("t.me/"):
        return f"https://{support}"
    return f"https://t.me/{support.lstrip('@')}"


@router.message(F.text == "💬 Поддержка")
async def cmd_support(message: Message) -> None:
    if settings.support_username:
        support_url = escape(_support_url(settings.support_username), quote=True)
        await message.answer(
            "💬 <b>Поддержка</b>\n\n"
            f'Напишите нам: <a href="{support_url}">Написать нам</a>\n\n'
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
        user_message("E900")
        + "\n\n💬 Опишите проблему в следующем сообщении — мы передадим её администратору."
    )

import logging
from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.keyboards.menus import main_menu
from bot.models.database import async_session
from bot.services.clash_api import SubscriptionService

logger = logging.getLogger(__name__)

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    logger.info(f"User {message.from_user.id} started the bot")
    async with async_session() as session:
        sub_service = SubscriptionService(session)
        user = await sub_service.get_or_create_user(message.from_user.id)

    text = (
        "👑 <b>Ghosteek CR Assistant</b>\n\n"
        "Я помогу улучшить вашу игру с помощью анализа боёв и колод.\n\n"
        "<b>В чате:</b>\n"
        "• Привязка аккаунта по тегу\n"
        "• Профиль и поддержка\n\n"
        "<b>В приложении</b> (Menu Button в Telegram):\n"
        "• Анализ боёв и винрейт колод\n"
        "• Колоды соперников и контр-колоды\n"
        "• Кастомизация и синергии\n\n"
        "Откройте приложение через Menu Button (слева от поля ввода).\n\n"
        "Для начала нажмите «📝 Регистрация» или отправьте тег:\n"
        "<code>/link #ВАШТЕГ</code>\n\n"
        f"{'✅ Тег привязан: ' + user.player_tag if user.player_tag else '❌ Тег не привязан'}"
    )
    await message.answer(text, reply_markup=main_menu())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    logger.info(f"User {message.from_user.id} requested help")
    await message.answer(
        "<b>Команды в чате:</b>\n"
        "/start — главное меню\n"
        "/link — привязать аккаунт (можно отправить только тег)\n"
        "/profile — ваш профиль\n\n"
        "Кнопка «📝 Регистрация» — то же, что /link: бот попросит тег игрока.\n\n"
        "<b>Анализ и статистика</b> доступны в Mini App — "
        "откройте через Menu Button (слева от поля ввода в чате бота).\n\n"
        "Для работы приложения нужен привязанный тег: <code>/link #ТЕГ</code>"
    )

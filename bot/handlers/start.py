import logging
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.config import settings
from bot.keyboards.menus import main_menu, subscription_keyboard
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
        "👑 <b>Clash Royale Coach Bot</b>\n\n"
        "Я помогу улучшить вашу игру с помощью анализа боёв и колод.\n\n"
        "<b>В чате:</b>\n"
        "• Привязка аккаунта по тегу\n"
        "• Профиль и подписка\n"
        "• Поддержка\n\n"
        "<b>В приложении</b> (Menu Button в Telegram):\n"
        "• Анализ боёв и винрейт колод\n"
        "• Колоды соперников и контр-колоды\n"
        "• Кастомизация и синергии\n\n"
        "Откройте приложение через Menu Button (слева от поля ввода).\n\n"
        "Для начала привяжите аккаунт:\n"
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
        "/link #ТЕГ — привязать аккаунт Clash Royale\n"
        "/profile — ваш профиль\n"
        "/subscribe — подписка\n\n"
        "<b>Анализ и статистика</b> доступны в Mini App — "
        "откройте через Menu Button (слева от поля ввода в чате бота).\n\n"
        "Для работы приложения нужны:\n"
        "• Привязанный тег (/link)\n"
        "• Активная подписка (/subscribe)"
    )


@router.message(Command("subscribe"))
@router.message(F.text == "💎 Подписка")
async def cmd_subscribe(message: Message) -> None:
    logger.info(f"User {message.from_user.id} opened subscription page")
    async with async_session() as session:
        sub_service = SubscriptionService(session)
        user = await sub_service.get_or_create_user(message.from_user.id)
        info = await sub_service.get_subscription_info(user)

    if info["active"]:
        expires = info["expires_at"]
        expires_str = expires.strftime("%d.%m.%Y") if expires else "бессрочно"
        await message.answer(f"✅ Подписка активна до {expires_str}")
        return

    trial_available = not info["trial_used"]
    await message.answer(
        "💎 <b>Подписка Clash Royale Coach</b>\n\n"
        "Полный доступ ко всем функциям анализа в приложении:\n"
        "• Разбор боёв и колод\n"
        "• Контр-колоды и синергии\n"
        "• Винрейт и кастомизация\n\n"
        + ("🎁 Доступен бесплатный пробный период!\n" if trial_available else ""),
        reply_markup=subscription_keyboard(trial_available, settings.subscription_price_stars),
    )

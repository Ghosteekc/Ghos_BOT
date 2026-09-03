import logging
from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from bot.keyboards.menus import main_menu
from bot.models.database import async_session
from bot.services.beta_invite import parse_beta_payload, redeem_beta_invite
from bot.services.clash_api import SubscriptionService
from bot.services.referral.service import parse_referral_payload, process_referral_conversion
from bot.services.weekly_digest import send_digest_preview

logger = logging.getLogger(__name__)

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject) -> None:
    if message.from_user is None:
        return
    logger.info("User %s started the bot (args=%r)", message.from_user.id, command.args)

    beta_token = parse_beta_payload(command.args)
    referrer_tg = None if beta_token else parse_referral_payload(command.args)

    async with async_session() as session:
        sub_service = SubscriptionService(session)
        user, created = await sub_service.get_or_create_user_ex(message.from_user.id)

    beta_note = ""
    if beta_token:
        async with async_session() as session:
            sub_service = SubscriptionService(session)
            tester, _ = await sub_service.get_or_create_user_ex(message.from_user.id)
            redeem = await redeem_beta_invite(session, user=tester, token=beta_token)
        if redeem.ok:
            beta_note = (
                f"\n\n🧪 <b>Бета-доступ активирован на {redeem.days} дн.</b>\n"
                "Откройте приложение через Menu Button «Ghosteek»."
            )
            logger.info(
                "Beta invite ok: user=%s days=%s",
                message.from_user.id,
                redeem.days,
            )
        elif redeem.reason == "already_used":
            beta_note = "\n\n⚠️ Эта бета-ссылка уже использована."
        else:
            beta_note = "\n\n⚠️ Бета-ссылка недействительна или устарела."
            logger.info(
                "Beta invite failed: user=%s reason=%s",
                message.from_user.id,
                redeem.reason,
            )

    if referrer_tg is not None:
        async with async_session() as session:
            # Re-load user in this session for conversion write.
            sub_service = SubscriptionService(session)
            referred, _ = await sub_service.get_or_create_user_ex(message.from_user.id)
            result = await process_referral_conversion(
                session,
                referred_user=referred,
                referrer_telegram_id=referrer_tg,
                is_new_user=created,
            )
            logger.info(
                "Referral conversion: referred=%s referrer_tg=%s created=%s result=%s rewards=%s",
                message.from_user.id,
                referrer_tg,
                created,
                result.reason,
                result.rewards_granted,
            )

    text = (
        "👑 <b>Ghosteek Royale</b>\n\n"
        "Я помогу улучшить вашу игру с помощью анализа боёв и колод.\n\n"
        "Приложение целиком — Menu Button «Ghosteek» слева от поля ввода.\n\n"
        "Для начала нажмите «📝 Регистрация» или отправьте тег:\n"
        "<code>/link #ВАШТЕГ</code>\n\n"
        f"{'✅ Тег привязан: ' + user.player_tag if user.player_tag else '❌ Тег не привязан'}"
        f"{beta_note}"
    )
    await message.answer(text, reply_markup=main_menu())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    logger.info(f"User {message.from_user.id} requested help")
    await message.answer(
        "<b>Команды в чате:</b>\n"
        "/start — главное меню\n"
        "/link — привязать аккаунт (можно отправить только тег)\n"
        "/unlink — отвязать аккаунт Clash Royale от этого Telegram\n"
        "/cancel — отменить ввод тега (во время /link)\n"
        "/profile — ваш профиль\n"
        "/digest — превью сводки за текущую неделю (пн–сегодня)\n\n"
        "Кнопка «📝 Регистрация» — то же, что /link: бот попросит тег игрока.\n\n"
        "<b>Ghosteek AI</b> — кнопка «⚡Ghosteek AI» (сразу чат с тренером).\n"
        "<b>Анализ и статистика</b> — Mini App: Menu Button «Ghosteek» "
        "слева от поля ввода.\n\n"
        "Для работы приложения нужен привязанный тег: <code>/link #ТЕГ</code>",
        reply_markup=main_menu(),
    )


@router.message(Command("digest"))
async def cmd_digest_preview(message: Message) -> None:
    """Превью недельной сводки (любое состояние FSM; не блокирует понедельничную рассылку)."""
    async with async_session() as session:
        sub_service = SubscriptionService(session)
        user = await sub_service.get_or_create_user(message.from_user.id)

    await message.answer("⏳ Собираю превью недельной сводки…")
    ok, err = await send_digest_preview(message.bot, user)
    if not ok:
        await message.answer(err or "Не удалось отправить сводку.")

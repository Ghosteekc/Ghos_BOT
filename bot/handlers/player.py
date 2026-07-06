import logging

from aiogram import Router, F
from aiogram.filters import Command, BaseFilter
from aiogram.types import Message

from bot.keyboards.menus import (
    LEGACY_SUBSCRIPTION_BUTTON,
    MENU_BUTTONS,
    PROFILE_BUTTON,
    REGISTRATION_BUTTON,
)
from bot.models.database import async_session
from bot.services.battle_service import get_cached_stats
from bot.services.clash_api import (
    ClashRoyaleAPIError,
    ClashRoyaleClient,
    SubscriptionService,
    normalize_tag,
    validate_tag,
)

logger = logging.getLogger(__name__)

router = Router()

_pending_link: set[int] = set()

LINK_PROMPT = (
    "Отправьте <b>только тег</b> игрока Clash Royale.\n\n"
    "Пример: <code>#ABC123XYZ</code>\n\n"
    "Тег указан в профиле игры под вашим именем."
)


class PendingLinkFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id in _pending_link


async def _prompt_link_tag(message: Message) -> None:
    _pending_link.add(message.from_user.id)
    await message.answer(LINK_PROMPT)


async def _link_player_by_tag(message: Message, raw_tag: str) -> None:
    tag = normalize_tag(raw_tag)
    if not validate_tag(tag):
        _pending_link.add(message.from_user.id)
        await message.answer(
            "❌ Неверный формат тега. Используйте символы: 0289PYLQGRJCUV\n"
            "Пример: <code>#ABC123</code>\n\n"
            "Отправьте тег ещё раз."
        )
        return

    client = ClashRoyaleClient()
    try:
        player = await client.get_player(tag)
    except ClashRoyaleAPIError as e:
        logger.error(f"Failed to link player {tag} for user {message.from_user.id}: {e}")
        error_msg = f"❌ {str(e)}"
        if e.details and e.status == 403:
            error_msg += f"\n\nДетали: {e.details[:200]}"
        _pending_link.add(message.from_user.id)
        await message.answer(error_msg)
        return
    except Exception as e:
        logger.error(
            f"Unexpected error linking player {tag} for user {message.from_user.id}: {e}",
            exc_info=True,
        )
        _pending_link.add(message.from_user.id)
        await message.answer(f"❌ Неожиданная ошибка: {str(e)}")
        return
    finally:
        await client.close()

    try:
        async with async_session() as session:
            sub_service = SubscriptionService(session)
            user = await sub_service.get_or_create_user(message.from_user.id)
            await sub_service.link_player(user, tag, player)

        arena = player.get("arena", {})
        trophies = player.get("trophies", 0)
        logger.info(f"Successfully linked player {tag} to user {message.from_user.id}")
        _pending_link.discard(message.from_user.id)
        await message.answer(
            f"✅ Аккаунт привязан!\n\n"
            f"👤 <b>{player.get('name')}</b>\n"
            f"🏷 Тег: <code>{tag}</code>\n"
            f"🏆 Кубки: {trophies}\n"
            f"🏟 Арена: {arena.get('name', '?')}\n\n"
            "Откройте приложение через Menu Button для анализа боёв и колод."
        )
    except Exception as e:
        logger.error(
            f"Database error linking player {tag} for user {message.from_user.id}: {e}",
            exc_info=True,
        )
        _pending_link.add(message.from_user.id)
        await message.answer(f"❌ Ошибка сохранения данных: {str(e)}")


@router.message(Command("link"))
async def cmd_link(message: Message) -> None:
    args = message.text.split(maxsplit=1) if message.text else []
    if len(args) < 2:
        await _prompt_link_tag(message)
        return

    _pending_link.discard(message.from_user.id)
    await _link_player_by_tag(message, args[1])


@router.message(F.text.in_({REGISTRATION_BUTTON, LEGACY_SUBSCRIPTION_BUTTON}))
async def btn_registration(message: Message) -> None:
    await _prompt_link_tag(message)


@router.message(F.text, ~F.text.in_(MENU_BUTTONS), PendingLinkFilter())
async def handle_pending_tag(message: Message) -> None:
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        await _prompt_link_tag(message)
        return

    _pending_link.discard(message.from_user.id)
    await _link_player_by_tag(message, text)


@router.message(Command("profile"))
@router.message(F.text == PROFILE_BUTTON)
async def cmd_profile(message: Message) -> None:
    async with async_session() as session:
        sub_service = SubscriptionService(session)
        user = await sub_service.get_or_create_user(message.from_user.id)

    if not user.player_tag:
        await message.answer(
            "❌ Тег не привязан.\n\n"
            "Нажмите «📝 Регистрация» или отправьте команду /link"
        )
        return

    client = ClashRoyaleClient()
    try:
        player = await client.get_player(user.player_tag)
    except ClashRoyaleAPIError as e:
        logger.error(f"Failed to load profile for {user.player_tag}: {e}")
        await message.answer(f"❌ Ошибка загрузки профиля: {e}")
        return
    except Exception as e:
        logger.error(f"Unexpected error loading profile for {user.player_tag}: {e}", exc_info=True)
        await message.answer(f"❌ Неожиданная ошибка: {str(e)}")
        return
    finally:
        await client.close()

    arena = player.get("arena", {})
    stats = await get_cached_stats(user.player_tag)
    stats_line = ""
    if stats:
        stats_line = f"\n📊 Сохранено боёв: {stats.total} ({stats.winrate}% WR)"

    arena_name = arena.get("name", "—")
    await message.answer(
        f"👤 <b>{player.get('name')}</b>\n"
        f"🏷 <code>{user.player_tag}</code>\n"
        f"🏆 {player.get('trophies', 0)} кубков\n"
        f"🏟 Арена: {arena_name}"
        f"{stats_line}\n\n"
        "📱 Полный анализ — в Mini App (Menu Button в Telegram)."
    )

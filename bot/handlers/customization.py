import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message

from bot.keyboards.menus import opponent_select_keyboard
from bot.models.database import User
from bot.services.clash_api import ClashRoyaleAPIError, ClashRoyaleClient, normalize_tag
from bot.services.counter_engine import (
    analyze_opponent_deck_from_battles,
    build_synergy_deck,
    customize_deck_for_arena,
    suggest_counter_deck,
)
from bot.services.card_names_ru import card_name_ru
from bot.services.deck_analyzer import get_most_played_cards
from bot.user_errors import log_error, user_message, user_message_plain

logger = logging.getLogger(__name__)

router = Router()

_opponents_cache: dict[int, list] = {}


async def _load_battles(user: User) -> list | None:
    if not user.player_tag:
        logger.warning(f"User has no linked player tag in customization handler")
        return None

    logger.debug(f"Loading battles for customization for {user.player_tag}")
    client = ClashRoyaleClient()
    try:
        battles = await client.get_battlelog(user.player_tag)
        logger.info(f"Loaded {len(battles)} battles for customization for {user.player_tag}")
        return battles
    except ClashRoyaleAPIError as e:
        logger.error(f"Failed to load battles for customization for {user.player_tag}: {e}")
        return None
    finally:
        await client.close()


@router.message(F.text == "🎯 Колоды соперников")
async def opponent_decks(message: Message, user: User) -> None:
    logger.info(f"User {message.from_user.id} requested opponent decks analysis")
    await message.answer("⏳ Анализирую колоды соперников...")
    battles = await _load_battles(user)
    if battles is None:
        await message.answer(user_message("E020"))
        return

    try:
        opponents = analyze_opponent_deck_from_battles(battles, normalize_tag(user.player_tag))
        _opponents_cache[message.from_user.id] = opponents

        if not opponents:
            await message.answer("Нет данных о соперниках.")
            return

        lines = ["🎯 <b>Колоды соперников из ваших боёв:</b>\n"]
        for i, opp in enumerate(opponents[:5]):
            result = "✅ победа" if opp["won_against"] else "❌ поражение"
            threats = ", ".join(opp["threats"]) if opp["threats"] else "нет явных WC"
            lines.append(
                f"<b>#{i + 1}</b> {opp['name']} ({result})\n"
                f"⚗️ {opp['avg_elixir']} | ⚠️ {threats}\n"
                f"{', '.join(opp['deck'])}\n"
            )

        await message.answer("\n".join(lines))
        logger.info(f"Showed {len(opponents)} opponent decks to user {message.from_user.id}")
    except Exception as e:
        log_error(logger, "E050", "Error analyzing opponent decks", exc=e, user_id=message.from_user.id)
        await message.answer(user_message("E050"))


@router.message(F.text == "⚔️ Контр-колоды")
async def counter_decks(message: Message, user: User) -> None:
    logger.info(f"User {message.from_user.id} requested counter decks")
    await message.answer("⏳ Подбираю контр-колоды...")
    battles = await _load_battles(user)
    if battles is None:
        await message.answer(user_message("E020"))
        return

    try:
        opponents = analyze_opponent_deck_from_battles(battles, normalize_tag(user.player_tag))
        _opponents_cache[message.from_user.id] = opponents

        if not opponents:
            await message.answer("Нет данных о соперниках для подбора.")
            return

        preferred = [c for c, _ in get_most_played_cards(battles, normalize_tag(user.player_tag))]

        await message.answer(
            "Выберите соперника для подбора контр-колоды:",
            reply_markup=opponent_select_keyboard(len(opponents)),
        )
    except Exception as e:
        log_error(logger, "E051", "Error preparing counter decks", exc=e, user_id=message.from_user.id)
        await message.answer(user_message("E051"))


@router.callback_query(F.data.startswith("opp_"))
async def counter_deck_detail(callback: CallbackQuery, user: User) -> None:
    idx = int(callback.data.split("_")[1])
    opponents = _opponents_cache.get(callback.from_user.id, [])

    if idx >= len(opponents):
        await callback.answer(user_message_plain("E005"), show_alert=True)
        return

    opp = opponents[idx]
    battles = await _load_battles(user)
    preferred = []
    if battles:
        preferred = [c for c, _ in get_most_played_cards(battles, normalize_tag(user.player_tag))]

    try:
        counter = suggest_counter_deck(
            opp["deck"],
            user.arena_id,
            preferred,
            user_deck=opp.get("user_deck"),
            trophies=user.trophies,
        )

        text = (
            f"⚔️ <b>Контр-колода vs {opp['name']}</b>\n\n"
            f"<b>Колода соперника:</b>\n{', '.join(opp['deck'])}\n\n"
            f"<b>Рекомендуемая колода:</b>\n{', '.join(counter)}\n\n"
            f"💡 Подобрана с учётом счётчиков на: "
            f"{', '.join(opp['threats']) if opp['threats'] else 'универсальный пул'}"
        )
        if preferred:
            text += f"\n⭐ Учтены ваши частые карты: {', '.join(preferred[:3])}"

        await callback.message.edit_text(text)
        logger.info(f"Showed counter deck for opponent {idx} to user {callback.from_user.id}")
    except Exception as e:
        log_error(logger, "E051", "Error showing counter deck", exc=e, user_id=callback.from_user.id)
        await callback.message.edit_text(user_message("E051"))
    await callback.answer()


@router.message(F.text == "🔧 Кастомизация колоды")
async def customize_deck(message: Message, user: User) -> None:
    logger.info(f"User {message.from_user.id} requested deck customization")
    await message.answer("⏳ Анализирую вашу текущую колоду...")
    battles = await _load_battles(user)
    if battles is None:
        await message.answer(user_message("E020"))
        return

    try:
        tag = normalize_tag(user.player_tag)
        preferred = get_most_played_cards(battles, tag)
        pref_names = [c for c, _ in preferred]

        current_deck = []
        for battle in battles:
            team = battle.get("team", [{}])[0]
            if team.get("tag", "").upper() == tag.upper():
                current_deck = [c["name"] for c in team.get("cards", [])]
                break

        if not current_deck:
            await message.answer("Не найдена колода в последних боях.")
            return

        result = customize_deck_for_arena(current_deck, user.arena_id, pref_names, user.trophies)

        issues_text = "\n".join(result["issues"]) if result["issues"] else "✅ Колода уже оптимальна"
        text = (
            f"🔧 <b>Кастомизация колоды</b>\n"
            f"🏟 Арена ID: {user.arena_id or '?'}\n"
            f"⚗️ Эликсир: {result['avg_elixir']}\n\n"
            f"<b>Было:</b>\n{', '.join(result['original'])}\n\n"
            f"<b>Стало:</b>\n{', '.join(result['customized'])}\n\n"
            f"<b>Изменения:</b>\n{issues_text}"
        )
        await message.answer(text)
        logger.info(f"Showed deck customization to user {message.from_user.id}")
    except Exception as e:
        log_error(logger, "E052", "Error customizing deck", exc=e, user_id=message.from_user.id)
        await message.answer(user_message("E052"))


@router.message(F.text == "✨ Синергии")
async def synergy_deck(message: Message, user: User) -> None:
    logger.info(f"User {message.from_user.id} requested synergy deck")
    await message.answer("⏳ Строю колоду на основе ваших карт...")
    battles = await _load_battles(user)
    if battles is None:
        await message.answer(user_message("E020"))
        return

    try:
        tag = normalize_tag(user.player_tag)
        top_cards = get_most_played_cards(battles, tag, top_n=3)
        core = [c for c, _ in top_cards]

        if not core:
            await message.answer("Недостаточно данных о ваших картах.")
            return

        result = build_synergy_deck(core, user.arena_id)

        synergy_lines = []
        for card, syns in result["synergies"].items():
            if syns:
                card_ru = card_name_ru(card, short=True) or card
                syn_ru = ", ".join(card_name_ru(s, short=True) or s for s in syns)
                synergy_lines.append(f"• {card_ru} → {syn_ru}")

        text = (
            f"✨ <b>Колода на основе ваших карт</b>\n\n"
            f"⭐ Основа: {', '.join(core)}\n"
            f"⚗️ Средний эликсир: {result['avg_elixir']}\n\n"
            f"<b>Рекомендуемая колода:</b>\n{', '.join(result['deck'])}\n\n"
            f"<b>Синергии:</b>\n" + ("\n".join(synergy_lines) if synergy_lines else "—")
        )
        await message.answer(text)
        logger.info(f"Showed synergy deck to user {message.from_user.id}")
    except Exception as e:
        log_error(logger, "E053", "Error building synergy deck", exc=e, user_id=message.from_user.id)
        await message.answer(user_message("E053"))

import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message

from bot.keyboards.menus import battle_select_keyboard
from bot.models.database import User
from bot.services.battle_service import filter_pvp_battles, persist_battles
from bot.services.clash_api import ClashRoyaleAPIError, ClashRoyaleClient, normalize_tag
from bot.services.deck_analyzer import analyze_battle, analyze_deck, calculate_deck_winrates
from bot.services.deck_analyzer import get_most_played_cards
from bot.user_errors import log_error, user_message, user_message_plain
from aiogram.filters import Command
from sqlalchemy import select
from bot.models.database import BattleCache, async_session
import json

logger = logging.getLogger(__name__)

router = Router()

_battle_cache: dict[int, list] = {}


async def _load_battles(user: User, telegram_id: int) -> list | None:
    if not user.player_tag:
        logger.warning(f"User {telegram_id} has no linked player tag")
        return None

    client = ClashRoyaleClient()
    try:
        battles = await client.get_battlelog(user.player_tag)
    except ClashRoyaleAPIError as e:
        logger.error(f"Failed to load battles for {user.player_tag}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error loading battles for {user.player_tag}: {e}", exc_info=True)
        return None
    finally:
        await client.close()

    pvp = filter_pvp_battles(battles, user.player_tag)
    _battle_cache[telegram_id] = pvp
    logger.info(f"Loaded {len(pvp)} PvP battles for {user.player_tag}")

    saved_count = await persist_battles(user, pvp)
    if saved_count:
        logger.info("Saved %d new battles for %s", saved_count, user.player_tag)

    return pvp


@router.message(F.text == "📊 Анализ боёв")
async def analyze_battles(message: Message, user: User) -> None:
    logger.info(f"User {message.from_user.id} requested battle analysis")
    await message.answer("⏳ Загружаю последние бои...")
    battles = await _load_battles(user, message.from_user.id)

    if battles is None:
        await message.answer(user_message("E020"))
        return
    if not battles:
        await message.answer("Нет PvP-боёв в истории.")
        return

    # Try to show aggregated stats from BattleCache if available
    async with async_session() as session:
        res = await session.execute(
            select(BattleCache).where(BattleCache.player_tag == normalize_tag(user.player_tag))
        )
        cached = res.scalars().all()

    if cached:
        total = len(cached)
        wins = sum(1 for r in cached if r.result == "win")
        losses = total - wins
        wr = round(wins / total * 100, 1) if total else 0
        await message.answer(
            f"Найдено {len(battles)} последних боёв. По сохранённым данным: {total} боёв — {wins}W/{losses}L (винрейт {wr}%).\nВыберите бой для подробного анализа:",
            reply_markup=battle_select_keyboard(len(battles)),
        )
    else:
        await message.answer(
            f"Найдено {len(battles)} боёв. Выберите бой для анализа:",
            reply_markup=battle_select_keyboard(len(battles)),
        )


@router.callback_query(F.data.startswith("battle_"))
async def battle_detail(callback: CallbackQuery, user: User) -> None:
    idx = int(callback.data.split("_")[1])
    battles = _battle_cache.get(callback.from_user.id, [])

    if idx >= len(battles):
        await callback.answer(user_message_plain("E004"), show_alert=True)
        return

    battle = battles[idx]
    team = battle.get("team", [{}])[0]
    opponent = battle.get("opponent", [{}])[0]

    try:
        analysis = analyze_battle(team, opponent)
        user_stats = analyze_deck(analysis.user_deck)
        opp_stats = analyze_deck(analysis.opponent_deck)

        result_emoji = "🏆 Победа" if analysis.won else "💔 Поражение"
        reasons_text = "\n".join(analysis.reasons)

        text = (
            f"{result_emoji} vs <b>{analysis.opponent_name}</b>\n"
            f"{'+' if analysis.trophy_change >= 0 else ''}{analysis.trophy_change} 🏆\n"
            f"📊 Матчап: {analysis.matchup_score:.0f}/100\n\n"
            f"<b>Ваша колода</b> ({user_stats.avg_elixir} ⚗️):\n"
            f"{', '.join(analysis.user_deck)}\n\n"
            f"<b>Колода соперника</b> ({opp_stats.avg_elixir} ⚗️):\n"
            f"{', '.join(analysis.opponent_deck)}\n\n"
            f"<b>Анализ:</b>\n{reasons_text}"
        )

        if analysis.opponent_threats:
            text += f"\n\n⚠️ <b>Угрозы:</b> {', '.join(analysis.opponent_threats)}"

        await callback.message.edit_text(text)
        logger.info(f"Showed battle {idx} analysis to user {callback.from_user.id}")
    except Exception as e:
        log_error(logger, "E040", "Error showing battle detail", exc=e, user_id=callback.from_user.id)
        await callback.message.edit_text(user_message("E040"))
    await callback.answer()


@router.message(F.text == "📈 Винрейт колод")
async def deck_winrates(message: Message, user: User) -> None:
    logger.info(f"User {message.from_user.id} requested deck winrates")
    await message.answer("⏳ Считаю винрейт...")
    battles = await _load_battles(user, message.from_user.id)

    if battles is None:
        await message.answer(user_message("E020"))
        return

    try:
        winrates = calculate_deck_winrates(battles, normalize_tag(user.player_tag))
        if not winrates:
            await message.answer("Недостаточно данных для расчёта винрейта.")
            return

        lines = ["📈 <b>Винрейт ваших колод:</b>\n"]
        for i, (_, data) in enumerate(winrates.items()):
            if i >= 5:
                break
            wr = data["winrate"]
            emoji = "🟢" if wr >= 55 else "🟡" if wr >= 45 else "🔴"
            cards_short = ", ".join(data["cards"][:4]) + "..."
            lines.append(
                f"{emoji} <b>{wr}%</b> ({data['wins']}W/{data['losses']}L)\n"
                f"   {cards_short}\n"
            )

        await message.answer("\n".join(lines))
        logger.info(f"Showed deck winrates to user {message.from_user.id}")
    except Exception as e:
        log_error(logger, "E041", "Error calculating winrates", exc=e, user_id=message.from_user.id)
        await message.answer(user_message("E041"))


@router.message(Command("stats"))
async def cmd_stats(message: Message, user: User) -> None:
    logger.info(f"User {message.from_user.id} requested detailed stats")
    if not user.player_tag:
        await message.answer(user_message("E003") + "\n\nИспользуйте /link #ВАШТЕГ")
        return

    # Detailed statistics from cached battles
    async with async_session() as session:
        res = await session.execute(
            select(BattleCache).where(BattleCache.player_tag == normalize_tag(user.player_tag))
        )
        cached = res.scalars().all()

    if not cached:
        await message.answer("Нет сохранённых данных. Подождите обновления или вызовите анализ вручную.")
        return

    try:
        total = len(cached)
        wins = sum(1 for r in cached if r.result == "win")
        losses = total - wins
        wr = round(wins / total * 100, 1) if total else 0

        # Top decks
        decks = {}
        for r in cached:
            key = r.user_deck
            if not key:
                continue
            decks.setdefault(key, {"total": 0, "wins": 0})
            decks[key]["total"] += 1
            if r.result == "win":
                decks[key]["wins"] += 1

        sorted_decks = sorted(decks.items(), key=lambda x: x[1]["total"], reverse=True)[:5]

        # Most played cards
        card_counts = {}
        for r in cached:
            for c in (r.user_deck or "").split(","):
                if not c:
                    continue
                card_counts[c] = card_counts.get(c, 0) + 1

        top_cards = sorted(card_counts.items(), key=lambda x: x[1], reverse=True)[:6]

        lines = [
            f"📊 Расширенная статистика для {user.player_tag}",
            f"Всего боёв: {total} — Побед: {wins} / Поражений: {losses} (винрейт {wr}%)",
            "",
            "Топ колод (примерно):",
        ]
        for deck_key, data in sorted_decks:
            cards = deck_key.split(",")
            wrd = round(data["wins"] / data["total"] * 100, 1) if data["total"] else 0
            lines.append(f"• {', '.join(cards[:6])} — {data['total']} игр, {wrd}%")

        lines.append("")
        lines.append("Часто используемые карты:")
        for c, cnt in top_cards:
            lines.append(f"• {c} — {cnt} раз")

        # Current streak (by battle_time ordering)
        try:
            sorted_rows = sorted(cached, key=lambda r: r.battle_time or "", reverse=True)
            streak = 0
            last_win = None
            for r in sorted_rows:
                if r.result == "win":
                    if last_win is None or last_win == True:
                        streak += 1
                        last_win = True
                    else:
                        break
                else:
                    if last_win is None:
                        last_win = False
                        streak = -1
                    else:
                        break
            if streak > 0:
                lines.append("")
                lines.append(f"Текущая серия побед: {streak}")
            elif streak < 0:
                lines.append("")
                lines.append(f"Текущая серия поражений: {abs(streak)}")
        except Exception:
            pass

        await message.answer("\n".join(lines))
        logger.info(f"Showed detailed stats to user {message.from_user.id}")
    except Exception as e:
        log_error(logger, "E042", "Error showing stats", exc=e, user_id=message.from_user.id)
        await message.answer(user_message("E042"))

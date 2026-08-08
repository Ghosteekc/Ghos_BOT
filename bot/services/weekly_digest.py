"""Weekly Telegram digest: stats + best-deck collage + catch-up loop."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)
from sqlalchemy import select

from bot.config import settings
from bot.models.database import User, UserSettings, WeeklyDigestSent, async_session
from bot.services.battle_cache_reader import get_battles_for_winrate_chart
from bot.services.battle_time import battle_day_key, now_msk
from bot.services.card_data import get_card_elixir
from bot.services.card_registry import ensure_cards_loaded
from bot.services.clash_api import ClashRoyaleClient, normalize_tag
from bot.services.deck_analyzer import calculate_deck_winrates
from bot.services.deck_collage import render_deck_collage

logger = logging.getLogger(__name__)

_DAY_NAMES_RU = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)


@dataclass(frozen=True)
class WeekWindow:
    week_key: str
    start: date  # Monday MSK
    end: date  # Sunday MSK


@dataclass
class WeekStats:
    week_key: str
    start: date
    end: date
    total: int
    wins: int
    losses: int
    winrate: float
    trophy_delta: int
    best_streak: int
    best_day_name: str | None
    best_day_wins: int
    best_deck: dict[str, Any] | None
    best_deck_share: float
    form_note: str


def iso_week_key(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def week_bounds(week_key: str) -> WeekWindow:
    year_s, week_s = week_key.split("-W")
    year, week = int(year_s), int(week_s)
    # ISO: week 1 Monday
    start = date.fromisocalendar(year, week, 1)
    end = date.fromisocalendar(year, week, 7)
    return WeekWindow(week_key=week_key, start=start, end=end)


def target_week_for_now(now: datetime | None = None) -> WeekWindow | None:
    """Sunday after 10:00 MSK → current week; Mon–Wed → previous week catch-up."""
    now = now or now_msk()
    if now.tzinfo is None:
        now = now.replace(tzinfo=now_msk().tzinfo)
    else:
        now = now.astimezone(now_msk().tzinfo)

    wd = now.isoweekday()  # Mon=1 … Sun=7
    if wd == 7 and now.hour >= 10:
        return week_bounds(iso_week_key(now.date()))
    if wd in (1, 2, 3):
        last_sunday = now.date() - timedelta(days=wd)
        return week_bounds(iso_week_key(last_sunday))
    return None


def _best_win_streak(results: list[bool]) -> int:
    best = cur = 0
    for won in results:
        if won:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _form_note(winrate: float, total: int) -> str:
    if total < 5:
        return "Мало боёв за неделю — крути лестницу, статистика стабилизируется."
    if winrate >= 65:
        return "Отличная форма! Дави тем же планом атаки."
    if winrate >= 55:
        return "Стабильная игра — продолжай в том же духе."
    if winrate >= 45:
        return "Близко к балансу. Разбери пару ключевых поражений в Mini App."
    return "Неделя тяжёлая. Смени темп или подкрути колоду под мету."


def _merge_live_and_cache(live: list[dict], cached: list[dict]) -> list[dict]:
    by_time: dict[str, dict] = {}
    for b in cached + live:
        t = str(b.get("battleTime") or b.get("battle_time") or "")
        if not t:
            continue
        # Prefer live (richer card metadata) over cache stubs
        if t not in by_time or b.get("type") != "cached":
            by_time[t] = b
    return sorted(
        by_time.values(),
        key=lambda b: str(b.get("battleTime") or ""),
        reverse=True,
    )


def _filter_week(battles: list[dict], window: WeekWindow) -> list[dict]:
    start_key = window.start.strftime("%Y%m%d")
    end_key = window.end.strftime("%Y%m%d")
    out: list[dict] = []
    for b in battles:
        day = battle_day_key(str(b.get("battleTime") or b.get("battle_time") or ""))
        if start_key <= day <= end_key:
            out.append(b)
    return out


def build_week_stats(
    battles: list[dict],
    player_tag: str,
    window: WeekWindow,
) -> WeekStats | None:
    week = _filter_week(battles, window)
    if not week:
        return None

    tag = normalize_tag(player_tag)
    results: list[bool] = []
    trophy_delta = 0
    day_wins: dict[str, int] = {}
    day_total: dict[str, int] = {}

    for b in week:
        team = b.get("team", [{}])[0]
        opp = b.get("opponent", [{}])[0]
        team_tag = team.get("tag") or ""
        if team_tag and normalize_tag(team_tag) != tag:
            continue
        won = int(team.get("crowns") or 0) > int(opp.get("crowns") or 0)
        # Cache stubs use result via crowns in row_to_battle_dict
        if b.get("type") == "cached" and "result" not in team:
            pass
        results.append(won)
        tc = team.get("trophyChange")
        if tc is None:
            tc = b.get("trophy_change")
        try:
            if tc is not None:
                trophy_delta += int(tc)
        except (TypeError, ValueError):
            pass
        day = battle_day_key(str(b.get("battleTime") or ""))
        if day:
            day_total[day] = day_total.get(day, 0) + 1
            if won:
                day_wins[day] = day_wins.get(day, 0) + 1

    total = len(results)
    if total == 0:
        return None
    wins = sum(1 for r in results if r)
    losses = total - wins
    winrate = round(wins / total * 100, 1)

    best_day_name = None
    best_day_wins = 0
    if day_wins:
        best_day = max(day_wins.items(), key=lambda kv: (kv[1], day_total.get(kv[0], 0)))
        try:
            d = datetime.strptime(best_day[0], "%Y%m%d").date()
            best_day_name = _DAY_NAMES_RU[d.weekday()]
            best_day_wins = best_day[1]
        except ValueError:
            pass

    winrates = calculate_deck_winrates(week, tag)
    best_deck = None
    if winrates:
        # Prefer decks with enough games, then winrate, then volume
        ranked = sorted(
            winrates.values(),
            key=lambda d: (min(int(d.get("total") or 0), 12), float(d.get("winrate") or 0), int(d.get("total") or 0)),
            reverse=True,
        )
        best_deck = ranked[0] if ranked else None

    share = 0.0
    if best_deck and total:
        share = round(100.0 * int(best_deck.get("total") or 0) / total, 0)

    return WeekStats(
        week_key=window.week_key,
        start=window.start,
        end=window.end,
        total=total,
        wins=wins,
        losses=losses,
        winrate=winrate,
        trophy_delta=trophy_delta,
        best_streak=_best_win_streak(results),
        best_day_name=best_day_name,
        best_day_wins=best_day_wins,
        best_deck=best_deck,
        best_deck_share=share,
        form_note=_form_note(winrate, total),
    )


def _format_trophy(delta: int) -> str:
    if delta > 0:
        return f"+{delta}"
    return str(delta)


def _avg_elixir(deck: dict[str, Any]) -> float:
    cards = deck.get("deck_cards") or []
    if cards:
        costs = [int(c.get("cost") or get_card_elixir(c.get("name") or "") or 0) for c in cards]
        costs = [c for c in costs if c > 0]
        if costs:
            return round(sum(costs) / len(costs), 1)
    names = deck.get("cards") or []
    costs = [get_card_elixir(n) for n in names]
    costs = [c for c in costs if c > 0]
    return round(sum(costs) / len(costs), 1) if costs else 0.0


def format_digest_caption(stats: WeekStats, player_name: str | None = None) -> str:
    period = f"{stats.start.strftime('%d.%m')}–{stats.end.strftime('%d.%m')}"
    who = f" · {player_name}" if player_name else ""
    lines = [
        f"<b>Ghosteek · недельная сводка</b>{who}",
        f"<i>{period}</i> · {stats.week_key}",
        "",
        f"⚔️ {stats.total} матчей · {stats.wins}П / {stats.losses}Пор · <b>{stats.winrate}%</b>",
        f"🏆 Кубки за неделю: <b>{_format_trophy(stats.trophy_delta)}</b>",
        f"🔥 Лучшая серия побед: <b>{stats.best_streak}</b>",
    ]
    if stats.best_day_name and stats.best_day_wins:
        lines.append(
            f"📅 Лучший день: <b>{stats.best_day_name}</b> ({stats.best_day_wins} побед)"
        )

    if stats.best_deck:
        d = stats.best_deck
        avg = _avg_elixir(d)
        lines.extend(
            [
                "",
                (
                    f"🥇 Лучшая колода: <b>{d.get('winrate', 0)}%</b> "
                    f"({d.get('total', 0)} матчей · ⚡{avg})"
                ),
            ]
        )
        if stats.best_deck_share:
            lines.append(f"Доля игр этой колодой: {int(stats.best_deck_share)}%")

    lines.extend(["", stats.form_note])
    return "\n".join(lines)


def _open_app_keyboard() -> InlineKeyboardMarkup | None:
    webapp = (settings.webapp_url or "").strip().rstrip("/")
    if not webapp or "your-domain" in webapp or not webapp.startswith("https://"):
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📊 Открыть колоды",
                    web_app=WebAppInfo(url=f"{webapp}/decks"),
                )
            ]
        ]
    )


async def _load_week_battles(player_tag: str, window: WeekWindow) -> list[dict]:
    days = max(7, (date.today() - window.start).days + 2)
    cached = await get_battles_for_winrate_chart(player_tag, days=min(days, 21))
    live: list[dict] = []
    try:
        async with ClashRoyaleClient() as client:
            raw = await client.get_battle_log(normalize_tag(player_tag))
            live = list(raw or [])
    except Exception as exc:
        logger.debug("Digest live battlelog failed for %s: %s", player_tag, exc)
    return _merge_live_and_cache(live, cached)


async def already_sent(user_id: int, week_key: str) -> bool:
    async with async_session() as session:
        res = await session.execute(
            select(WeeklyDigestSent.id).where(
                WeeklyDigestSent.user_id == user_id,
                WeeklyDigestSent.week_key == week_key,
            )
        )
        return res.scalar_one_or_none() is not None


async def mark_sent(user_id: int, week_key: str) -> None:
    async with async_session() as session:
        session.add(
            WeeklyDigestSent(
                user_id=user_id,
                week_key=week_key,
                sent_at=datetime.now(timezone.utc),
            )
        )
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            # Unique race — treat as sent
            logger.debug("Digest already marked for user_id=%s week=%s", user_id, week_key)


async def _eligible_users() -> list[User]:
    async with async_session() as session:
        res = await session.execute(
            select(User)
            .join(UserSettings, UserSettings.user_id == User.id)
            .where(UserSettings.telegram_notifications.is_(True))
            .where(User.player_tag.is_not(None))
        )
        users = list(res.scalars().all())
        # Users without settings row: default telegram_notifications=True historically
        res2 = await session.execute(
            select(User)
            .outerjoin(UserSettings, UserSettings.user_id == User.id)
            .where(UserSettings.id.is_(None))
            .where(User.player_tag.is_not(None))
        )
        for u in res2.scalars().all():
            users.append(u)
        # Dedupe by id
        by_id = {u.id: u for u in users}
        return list(by_id.values())


async def send_digest_to_user(bot: Bot, user: User, window: WeekWindow) -> bool:
    if not user.player_tag or not user.telegram_id:
        return False
    if await already_sent(user.id, window.week_key):
        return False

    battles = await _load_week_battles(user.player_tag, window)
    stats = build_week_stats(battles, user.player_tag, window)
    if stats is None:
        # No battles — still mark so we don't spam empty retries all week
        await mark_sent(user.id, window.week_key)
        logger.info(
            "Digest skip (no battles) user_id=%s week=%s",
            user.id,
            window.week_key,
        )
        return False

    caption = format_digest_caption(stats, user.player_name)
    keyboard = _open_app_keyboard()
    photo_bytes: bytes | None = None
    if stats.best_deck:
        cards = stats.best_deck.get("deck_cards") or [
            {"name": n, "evolution_level": 0, "is_hero": False, "icon": ""}
            for n in (stats.best_deck.get("cards") or [])
        ]
        try:
            photo_bytes = await render_deck_collage(cards)
        except Exception:
            logger.exception("Deck collage failed user_id=%s", user.id)

    try:
        if photo_bytes:
            await bot.send_photo(
                chat_id=user.telegram_id,
                photo=BufferedInputFile(photo_bytes, filename="ghosteek-week-deck.png"),
                caption=caption,
                reply_markup=keyboard,
            )
        else:
            await bot.send_message(
                chat_id=user.telegram_id,
                text=caption,
                reply_markup=keyboard,
            )
    except TelegramForbiddenError:
        await mark_sent(user.id, window.week_key)
        logger.info("Digest blocked by user telegram_id=%s", user.telegram_id)
        return False
    except TelegramRetryAfter as e:
        await asyncio.sleep(float(e.retry_after) + 0.5)
        raise
    except Exception:
        logger.exception("Digest send failed user_id=%s", user.id)
        return False

    await mark_sent(user.id, window.week_key)
    logger.info(
        "Digest sent user_id=%s week=%s battles=%s wr=%s",
        user.id,
        window.week_key,
        stats.total,
        stats.winrate,
    )
    return True


async def run_digest_cycle(bot: Bot) -> int:
    window = target_week_for_now()
    if window is None:
        return 0
    await ensure_cards_loaded()
    users = await _eligible_users()
    sent = 0
    for user in users:
        try:
            if await send_digest_to_user(bot, user, window):
                sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(float(e.retry_after) + 0.5)
            try:
                if await send_digest_to_user(bot, user, window):
                    sent += 1
            except Exception:
                logger.exception("Digest retry failed user_id=%s", user.id)
        await asyncio.sleep(0.07)
    return sent


async def run_periodic(bot: Bot, stop_event: asyncio.Event) -> None:
    """Hourly digest loop with catch-up after downtime."""
    logger.info("Weekly digest loop started")
    # First check shortly after startup
    first_delay = 90
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=first_delay)
        return
    except asyncio.TimeoutError:
        pass

    while not stop_event.is_set():
        try:
            n = await run_digest_cycle(bot)
            if n:
                logger.info("Digest cycle sent %s messages", n)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Digest cycle error")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=3600)
            break
        except asyncio.TimeoutError:
            pass
    logger.info("Weekly digest loop stopped")

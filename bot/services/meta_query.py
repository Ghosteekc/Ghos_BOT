"""Read-side meta API: ranked aggregates from Ghosteek sample (not worldwide)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from bot.config import settings
from bot.models.database import MetaDeckAggregate, MetaDeckDailyStat, MetaSnapshot, async_session
from bot.services.card_data import get_card_elixir
from bot.services.card_registry import build_deck_share_link, get_card_info
from bot.services.clan_war_decks import load_clan_war_snapshot
from bot.services.meta_stats import MODE_LEAGUE, MODE_TROPHIES, ranking_score, trend_from_history_values

SAMPLE_NOTE = (
    "Количество боёв в накопленной выборке Ghosteek, а не число всех мировых боёв."
)


def _cards_from_aggregate(row: MetaDeckAggregate) -> list[dict[str, Any]]:
    if row.cards_json:
        try:
            parsed = json.loads(row.cards_json)
            if isinstance(parsed, list) and len(parsed) == 8:
                return parsed
        except json.JSONDecodeError:
            pass
    names = [n.strip() for n in (row.cards_csv or "").split(",") if n.strip()]
    if len(names) != 8:
        names = [n for n in (row.deck_hash or "").split("|") if n]
    infos: list[dict[str, Any]] = []
    for slot, name in enumerate(names[:8]):
        info = get_card_info(name) or {}
        infos.append({
            "id": f"{name.lower().replace(' ', '-')}-{slot}",
            "name": name,
            "icon": info.get("icon") or "",
            "cost": int(info.get("elixir") or get_card_elixir(name) or 0),
            "evolution_level": 0,
            "is_hero": False,
            "slot": slot,
        })
    return infos


def _history_and_trend(
    daily_rows: list[MetaDeckDailyStat],
    *,
    history_days: int,
) -> tuple[list[dict[str, Any]], str, float | None, bool]:
    by_day = {row.day: row for row in daily_rows}
    today = datetime.now(timezone.utc).date()
    history: list[dict[str, Any]] = []
    for offset in range(history_days - 1, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        row = by_day.get(day)
        history.append({
            "day": day,
            "games": int(row.games) if row else 0,
        })
    filled_days = sum(1 for item in history if item["games"] > 0)
    values = [item["games"] for item in history]
    trend, pct = trend_from_history_values(values, history_days=history_days)
    enough = filled_days >= 3
    return history, trend, pct, enough


async def _latest_snapshot(mode: str) -> MetaSnapshot | None:
    async with async_session() as session:
        return (
            await session.execute(
                select(MetaSnapshot)
                .where(MetaSnapshot.mode == mode)
                .order_by(MetaSnapshot.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()


async def get_ladder_meta(mode: str) -> dict[str, Any]:
    if mode not in {MODE_LEAGUE, MODE_TROPHIES}:
        raise ValueError(mode)
    min_games = max(1, settings.meta_min_games)
    history_days = max(7, settings.meta_history_days)
    limit = max(4, settings.meta_ranking_limit)
    snapshot = await _latest_snapshot(mode)
    updated_at = snapshot.created_at if snapshot else None
    snapshot_source = snapshot.source if snapshot else ""

    async with async_session() as session:
        rows = (
            await session.execute(
                select(MetaDeckAggregate)
                .where(MetaDeckAggregate.mode == mode)
                .order_by(MetaDeckAggregate.ranking_score.desc(), MetaDeckAggregate.total_games.desc())
            )
        ).scalars().all()
        hashes = [row.deck_hash for row in rows]
        daily_map: dict[str, list[MetaDeckDailyStat]] = {h: [] for h in hashes}
        if hashes:
            daily_rows = (
                await session.execute(
                    select(MetaDeckDailyStat).where(
                        MetaDeckDailyStat.mode == mode,
                        MetaDeckDailyStat.deck_hash.in_(hashes),
                    )
                )
            ).scalars().all()
            for item in daily_rows:
                daily_map.setdefault(item.deck_hash, []).append(item)

    now = datetime.now(timezone.utc)
    max_games = max((row.total_games for row in rows), default=1)
    rows = sorted(
        rows,
        key=lambda row: (
            ranking_score(
                wins=row.wins,
                games=row.total_games,
                unique_players=row.unique_players,
                last_seen=row.last_seen,
                max_games=max_games,
                now=now,
            ),
            row.total_games,
            row.wins,
        ),
        reverse=True,
    )

    ranked: list[dict[str, Any]] = []
    low_sample: list[dict[str, Any]] = []
    for row in rows:
        if row.total_games <= 0:
            continue
        cards = _cards_from_aggregate(row)
        if len(cards) != 8:
            continue
        names = [c["name"] for c in cards]
        history, trend, trend_pct, enough_history = _history_and_trend(
            daily_map.get(row.deck_hash, []),
            history_days=history_days,
        )
        wr = round(row.wins / row.total_games * 100, 1) if row.total_games else 0.0
        payload = {
            "rank": 0,
            "deck_hash": row.deck_hash,
            "cards": cards,
            "games_count": row.total_games,
            "wins": row.wins,
            "losses": row.losses,
            "win_rate": wr,
            "unique_players": row.unique_players,
            "trend": trend if enough_history else "stable",
            "trend_percent": trend_pct if enough_history else None,
            "history": history if enough_history else [],
            "history_available": enough_history,
            "last_seen": row.last_seen.isoformat() if row.last_seen else None,
            "deck_link": build_deck_share_link(names),
            "low_sample": row.total_games < min_games,
        }
        if row.total_games >= min_games:
            ranked.append(payload)
        else:
            low_sample.append(payload)

    decks = ranked[:limit]
    for index, item in enumerate(decks, start=1):
        item["rank"] = index

    if not decks and low_sample:
        preview = sorted(low_sample, key=lambda item: item["games_count"], reverse=True)[:limit]
        for index, item in enumerate(preview, start=1):
            item["rank"] = index
        decks = preview

    collector_failed = (
        "429" in snapshot_source
        or ":error:" in snapshot_source
    )
    if decks:
        status = "stale" if collector_failed else "ok"
        message = "Мета временно не обновлена." if collector_failed else None
    elif any(row.total_games > 0 for row in rows):
        status = "insufficient"
        message = (
            "Предварительная мета — мало боёв в выборке, данные накапливаются."
            if mode == MODE_TROPHIES
            else "Недостаточно данных для формирования актуальной меты."
        )
    elif updated_at is None:
        status = "empty"
        message = "Недостаточно данных для формирования актуальной меты."
    elif mode == MODE_TROPHIES:
        status = "insufficient"
        message = (
            "В выборке пока нет боёв кубковой дороги (Ladder). "
            "Топ игроки чаще играют Ranked — данные накапливаются."
        )
    else:
        status = "stale"
        message = "Мета временно не обновлена."

    return {
        "mode": mode,
        "status": status,
        "message": message,
        "sample_note": SAMPLE_NOTE,
        "updated_at": updated_at.isoformat() if updated_at else None,
        "min_games": min_games,
        "decks": decks,
    }


async def get_clan_wars_meta() -> dict[str, Any]:
    snap = load_clan_war_snapshot()
    decks = []
    for index, item in enumerate(snap["decks"], start=1):
        names = item["cards"]
        cards = []
        for slot, name in enumerate(names):
            info = get_card_info(name) or {}
            cards.append({
                "id": f"{name.lower().replace(' ', '-')}-{slot}",
                "name": name,
                "icon": info.get("icon") or "",
                "cost": int(info.get("elixir") or get_card_elixir(name) or 0),
                "evolution_level": 0,
                "is_hero": False,
                "slot": slot,
            })
        decks.append({
            "rank": index,
            "cards": cards,
            "name": item.get("name") or "",
            "role": item.get("role") or "",
            "recommendation": item.get("recommendation") or "",
            "deck_link": build_deck_share_link(names),
        })
    available = bool(snap["available"])
    return {
        "mode": "clan_wars",
        "status": "ok" if available else "unavailable",
        "message": None if available else snap.get("message"),
        "source": snap.get("source") or "",
        "source_url": snap.get("source_url") or "",
        "updated_at": snap.get("updated_at"),
        "sample_note": "Колоды КВ из выборки Ghosteek или базовой подборки, если боёв КВ ещё нет.",
        "decks": decks,
    }

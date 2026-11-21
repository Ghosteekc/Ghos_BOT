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

SAMPLE_ORIGIN = "ghosteek_observations"
SAMPLE_NOTE = (
    "Источник: подтверждённые наблюдения Ghosteek из журналов боёв. "
    "Это накопительная выборка, а не глобальная статистика Clash Royale."
)


def _snapshot_is_stale(updated_at: datetime | None, *, now: datetime | None = None) -> bool:
    """Whether confirmed game data is older than its advertised refresh window."""
    if updated_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return now - updated_at > timedelta(hours=max(1, settings.meta_refresh_hours))


def _snapshot_attempt(snapshot: MetaSnapshot | None) -> dict[str, Any]:
    """Read optional collection metadata while keeping legacy snapshots usable."""
    if snapshot is None:
        return {"status": "never"}
    try:
        payload = json.loads(snapshot.payload_json or "{}")
    except (TypeError, json.JSONDecodeError):
        payload = {}
    attempt = payload.get("attempt") if isinstance(payload, dict) else None
    if isinstance(attempt, dict) and isinstance(attempt.get("status"), str):
        return attempt
    # Legacy snapshots did not carry attempt metadata.  Keep the old source
    # markers meaningful, but never pretend a normal old snapshot was fresh.
    source = snapshot.source or ""
    if "429" in source:
        return {"status": "rate_limited"}
    if ":error:" in source:
        return {"status": "failed"}
    return {"status": "legacy"}


def _latest_confirmed_data_at(rows: list[MetaDeckAggregate]) -> datetime | None:
    """Newest battle timestamp represented by the aggregate sample."""
    dates = [row.last_seen for row in rows if row.last_seen is not None]
    return max(dates) if dates else None


def _confirmed_sample_period(
    rows: list[MetaDeckAggregate],
) -> tuple[datetime | None, datetime | None]:
    """Bounds represented by all current aggregates for one mode.

    Aggregates are rebuilt from every persisted observation of that mode;
    no rolling date filter is applied here. Missing legacy timestamps stay
    unknown rather than being inferred from a collector attempt.
    """
    starts = [row.first_seen for row in rows if row.first_seen is not None]
    ends = [row.last_seen for row in rows if row.last_seen is not None]
    return (min(starts) if starts else None, max(ends) if ends else None)


def _freshness_message(
    *,
    collection_status: str,
    data_updated_at: datetime | None,
) -> tuple[str | None, str | None]:
    """Return API status/message without conflating collection attempt and data date."""
    if collection_status == "rate_limited":
        return "rate_limited", "Сбор ограничен API; показана последняя подтверждённая выборка Ghosteek."
    if collection_status == "failed":
        return "failed", "Сбор не завершился; показана последняя подтверждённая выборка Ghosteek."
    if collection_status == "partial":
        return "partial", "Собрана только часть источников; дата ниже относится к последним подтверждённым боям."
    if collection_status == "no_new_data":
        return "no_new_data", "Новых подтверждённых боёв не найдено; показана накопленная выборка Ghosteek."
    if _snapshot_is_stale(data_updated_at):
        return "stale", "Последние подтверждённые игровые данные устарели; показана накопленная выборка Ghosteek."
    return None, None


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
    attempt = _snapshot_attempt(snapshot)
    attempted_at = snapshot.created_at if snapshot else None

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
    sample_started_at, last_battle_at = _confirmed_sample_period(rows)
    data_updated_at = last_battle_at
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

    only_low_sample = bool(decks) and all(item["low_sample"] for item in decks)
    freshness_status, freshness_message = _freshness_message(
        collection_status=str(attempt.get("status") or "legacy"),
        data_updated_at=data_updated_at,
    )
    if decks:
        if freshness_status:
            status = freshness_status
            message = freshness_message
        elif only_low_sample:
            status = "insufficient"
            message = "Предварительная мета — мало боёв в выборке, данные накапливаются."
        else:
            status = "ok"
            message = None
    elif freshness_status in {"rate_limited", "failed", "partial"}:
        status = freshness_status
        message = freshness_message
    elif any(row.total_games > 0 for row in rows):
        status = "insufficient"
        message = (
            "Предварительная мета — мало боёв в выборке, данные накапливаются."
            if mode == MODE_TROPHIES
            else "Недостаточно данных для формирования актуальной меты."
        )
    elif data_updated_at is None:
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
        # Compatibility field now means confirmed game-data freshness, not
        # when the collector happened to run.
        "updated_at": data_updated_at.isoformat() if data_updated_at else None,
        "attempted_at": attempted_at.isoformat() if attempted_at else None,
        "collection_status": str(attempt.get("status") or "legacy"),
        "sample_started_at": sample_started_at.isoformat() if sample_started_at else None,
        "last_battle_at": last_battle_at.isoformat() if last_battle_at else None,
        "is_cumulative": True,
        "sample_origin": SAMPLE_ORIGIN,
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
    source_kind = snap.get("source_kind") or ""
    curated = source_kind == "curated"
    return {
        "mode": "clan_wars",
        "status": "curated" if available and curated else ("ok" if available else "unavailable"),
        "message": (
            "Показаны базовые рекомендации для КВ, а не статистика боёв."
            if available and curated
            else (None if available else snap.get("message"))
        ),
        "source": snap.get("source") or "",
        "source_kind": source_kind,
        "source_url": snap.get("source_url") or "",
        "updated_at": snap.get("updated_at"),
        "sample_note": (
            "Колоды КВ из выборки Ghosteek."
            if not curated
            else "Базовая подборка КВ; показатели популярности и винрейта не рассчитываются."
        ),
        "decks": decks,
    }

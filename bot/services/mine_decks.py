"""Постоянные «Мои колоды»: до 10 слотов, винрейт из всей истории battle_cache.

Правило замены: если уже 10 колод и появляется новая сыгранная —
вытесняется слот с наименьшим числом боёв (при равенстве — самый старый last_seen).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from bot.models.database import TrackedMineDeck, User, async_session
from bot.services.battle_cache_reader import get_cached_battle_rows, row_to_battle_dict
from bot.services.clash_api import normalize_tag
from bot.services.deck_analyzer import calculate_deck_winrates

logger = logging.getLogger(__name__)

MAX_MINE_DECKS = 10


def deck_fingerprint(card_names: list[str]) -> str:
    return "|".join(sorted(n for n in card_names if n))


def _battle_time(battle: dict) -> str:
    return str(battle.get("battleTime") or battle.get("battle_time") or "")


def _recent_deck_sightings(battles: list[dict], player_tag: str) -> list[tuple[str, list[str], str]]:
    """Новые появления колод из свежих боёв: (key, ordered_names, battle_time), свежие первыми."""
    from bot.services.card_icons import cards_from_team

    tag = normalize_tag(player_tag)
    sightings: list[tuple[str, list[str], str]] = []
    seen_in_pass: set[str] = set()

    for battle in battles:
        battle_type = battle.get("type") or "PvP"
        if battle_type in ("friendly", "clanMate", "warDay", "boatBattle", "challenge"):
            continue
        team = battle.get("team", [{}])[0]
        team_tag = team.get("tag") or ""
        if team_tag and normalize_tag(team_tag) != tag:
            continue

        parsed = cards_from_team(team)
        if len(parsed) == 8:
            names = [c["name"] for c in parsed]
        else:
            names = [c.get("name") for c in team.get("cards", []) if c.get("name")]
            if len(names) != 8:
                continue

        key = deck_fingerprint(names)
        if not key or key in seen_in_pass:
            continue
        seen_in_pass.add(key)
        sightings.append((key, names, _battle_time(battle)))

    return sightings


def _merge_battles(live: list[dict], cached: list[dict]) -> list[dict]:
    by_time: dict[str, dict] = {}
    for b in cached + live:
        t = _battle_time(b)
        if not t:
            continue
        # Prefer live (richer card metadata) over cache stubs
        if t not in by_time or b.get("type") != "cached":
            by_time[t] = b
    return sorted(by_time.values(), key=_battle_time, reverse=True)


def _empty_stats(cards: list[str], deck_cards: list[dict] | None = None) -> dict[str, Any]:
    return {
        "cards": list(cards),
        "deck_cards": list(deck_cards or []),
        "wins": 0,
        "losses": 0,
        "total": 0,
        "winrate": 0.0,
    }


async def _load_full_winrates(player_tag: str, live_battles: list[dict]) -> dict[str, dict]:
    tag = normalize_tag(player_tag)
    rows = await get_cached_battle_rows(tag, limit=5000)
    cached = [row_to_battle_dict(r, tag) for r in rows]
    merged = _merge_battles(live_battles or [], cached)
    return calculate_deck_winrates(merged, tag)


async def sync_tracked_mine_decks(
    user: User,
    *,
    live_battles: list[dict],
    profile_deck: list[dict] | None = None,
) -> list[dict[str, Any]]:
    """Обновить слоты и вернуть до 10 колод со статистикой (last_seen desc)."""
    if not user.player_tag:
        return []

    tag = normalize_tag(user.player_tag)
    winrates = await _load_full_winrates(tag, live_battles)
    sightings = _recent_deck_sightings(live_battles or [], tag)

    # Profile current deck — тоже «сыгранная» опора
    profile_key: str | None = None
    profile_names: list[str] = []
    if profile_deck and len(profile_deck) == 8:
        profile_names = [c["name"] for c in profile_deck if c.get("name")]
        if len(profile_names) == 8:
            profile_key = deck_fingerprint(profile_names)
            # Подтянуть порядок/evo из профиля в winrates
            if profile_key in winrates:
                row = dict(winrates[profile_key])
                row["cards"] = profile_names
                row["deck_cards"] = profile_deck
                winrates[profile_key] = row
            else:
                winrates[profile_key] = _empty_stats(profile_names, profile_deck)

    async with async_session() as session:
        res = await session.execute(
            select(TrackedMineDeck).where(TrackedMineDeck.user_id == user.id)
        )
        tracked = list(res.scalars().all())
        by_key = {t.deck_key: t for t in tracked}
        # Не вытеснять колоды, добавленные в этом же sync (иначе 2 новые
        # колоды подряд выбьют друг друга).
        protected: set[str] = set()

        def battle_count(key: str) -> int:
            return int((winrates.get(key) or {}).get("total") or 0)

        def ensure_slot(key: str, cards: list[str], seen: str) -> None:
            nonlocal by_key
            existing = by_key.get(key)
            if existing is not None:
                if cards:
                    existing.cards_csv = ",".join(cards)
                if seen and seen >= (existing.last_seen or ""):
                    existing.last_seen = seen
                return

            if len(by_key) < MAX_MINE_DECKS:
                row = TrackedMineDeck(
                    user_id=user.id,
                    deck_key=key,
                    cards_csv=",".join(cards),
                    last_seen=seen or "",
                )
                session.add(row)
                by_key[key] = row
                protected.add(key)
                return

            # Вытеснить колоду с наименьшим числом боёв
            candidates = [t for t in by_key.values() if t.deck_key not in protected]
            if not candidates:
                return
            victim = min(
                candidates,
                key=lambda t: (battle_count(t.deck_key), t.last_seen or "", t.id or 0),
            )
            logger.info(
                "Mine decks: replace %s (battles=%s) with %s for user_id=%s",
                victim.deck_key,
                battle_count(victim.deck_key),
                key,
                user.id,
            )
            del by_key[victim.deck_key]
            session.delete(victim)
            row = TrackedMineDeck(
                user_id=user.id,
                deck_key=key,
                cards_csv=",".join(cards),
                last_seen=seen or "",
            )
            session.add(row)
            by_key[key] = row
            protected.add(key)

        # Сначала свежие бои (уже от новых к старым уникальные)
        for key, names, seen in sightings:
            ensure_slot(key, names, seen)

        if profile_key:
            ensure_slot(profile_key, profile_names, sightings[0][2] if sightings else "")

        # Bootstrap: если слотов нет — заполнить топом из истории
        if not by_key and winrates:
            for key, data in list(winrates.items())[:MAX_MINE_DECKS]:
                ensure_slot(key, list(data.get("cards") or key.split("|")), "")

        await session.commit()

        # Перечитать после commit
        res = await session.execute(
            select(TrackedMineDeck)
            .where(TrackedMineDeck.user_id == user.id)
            .order_by(TrackedMineDeck.last_seen.desc(), TrackedMineDeck.id.desc())
        )
        tracked = list(res.scalars().all())

    out: list[dict[str, Any]] = []
    for slot in tracked[:MAX_MINE_DECKS]:
        stats = winrates.get(slot.deck_key)
        cards_from_csv = [c for c in (slot.cards_csv or "").split(",") if c]
        if stats:
            row = dict(stats)
            if len(cards_from_csv) == 8 and not row.get("deck_cards"):
                row["cards"] = cards_from_csv
            out.append(row)
        else:
            cards = cards_from_csv or slot.deck_key.split("|")
            out.append(_empty_stats(cards))

    # Текущая колода профиля — первой, если есть в списке
    if profile_key:
        pinned = [r for r in out if deck_fingerprint(r.get("cards") or []) == profile_key]
        rest = [r for r in out if deck_fingerprint(r.get("cards") or []) != profile_key]
        if pinned:
            # обновить карточки профиля
            pinned[0] = {
                **pinned[0],
                "cards": profile_names,
                "deck_cards": profile_deck or pinned[0].get("deck_cards") or [],
            }
            out = pinned + rest

    return out[:MAX_MINE_DECKS]

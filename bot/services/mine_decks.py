"""Постоянные «Мои колоды»: до 10 слотов, винрейт из всей истории battle_cache.

Правило замены: если уже 10 колод и появляется новая сыгранная —
вытесняется слот с наименьшим числом боёв (при равенстве — самый старый last_seen).

Порядок в списке: **сначала недавно сыгранные** (`last_seen` desc).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from bot.models.database import TrackedMineDeck, User, async_session
from bot.services.battle_cache_reader import get_cached_battle_rows, row_to_battle_dict
from bot.services.card_icons import (
    cards_from_team,
    deck_upgrade_score,
    or_merge_modes_onto,
    parse_deck_cards_json,
    serialize_deck_cards,
)
from bot.services.clash_api import normalize_tag
from bot.services.deck_analyzer import calculate_deck_winrates

logger = logging.getLogger(__name__)

MAX_MINE_DECKS = 10

# Параллельные /winrates + /decks иначе оба делают INSERT одной и той же колоды.
_user_sync_locks: dict[int, asyncio.Lock] = {}


def _lock_for_user(user_id: int) -> asyncio.Lock:
    lock = _user_sync_locks.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        _user_sync_locks[user_id] = lock
    return lock


def deck_fingerprint(card_names: list[str]) -> str:
    return "|".join(sorted(n for n in card_names if n))


def _battle_time(battle: dict) -> str:
    return str(battle.get("battleTime") or battle.get("battle_time") or "")


def _recent_deck_sightings(battles: list[dict], player_tag: str) -> list[tuple[str, list[str], str, list[dict]]]:
    """Колоды из боёв: (key, ordered_names, newest_battle_time, OR-merged parsed cards).

    OR-merge across *all* sightings of the same fingerprint so a newer base-art
    battle cannot hide evo/hero that appeared in an older battle in the same window.
    """
    tag = normalize_tag(player_tag)
    # key -> (names, newest_time, list of parsed variants)
    acc: dict[str, tuple[list[str], str, list[list[dict]]]] = {}

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
            parsed = []

        key = deck_fingerprint(names)
        if not key:
            continue
        bt = _battle_time(battle)
        if key not in acc:
            variants = [parsed] if parsed else []
            acc[key] = (names, bt, variants)
            continue
        prev_names, prev_time, variants = acc[key]
        if parsed:
            variants.append(parsed)
        # Keep newest battle time; prefer names from a rich variant when available
        use_names = names if parsed else prev_names
        newest = bt if bt >= (prev_time or "") else prev_time
        acc[key] = (use_names, newest, variants)

    out: list[tuple[str, list[str], str, list[dict]]] = []
    for key, (names, seen, variants) in acc.items():
        if variants:
            merged = or_merge_modes_onto(
                max(variants, key=deck_upgrade_score),
                variants,
                clamp=False,
            )
        else:
            merged = []
        out.append((key, names, seen, merged))
    # Newest first for slot replacement priority
    out.sort(key=lambda item: item[2] or "", reverse=True)
    return out


def _merge_battles(live: list[dict], cached: list[dict]) -> list[dict]:
    by_time: dict[str, dict] = {}
    for b in cached:
        t = _battle_time(b)
        if t:
            by_time[t] = b
    # Live API payloads carry evolutionLevel / hero art — always win over cache stubs
    for b in live:
        t = _battle_time(b)
        if t:
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


def _combine_deck_cards(*candidates: list[dict] | None) -> list[dict]:
    """Pick richest order base, OR evo/hero from every non-empty candidate."""
    variants = [list(c) for c in candidates if c and len(c) == 8]
    if not variants:
        return []
    base = max(variants, key=deck_upgrade_score)
    return or_merge_modes_onto(base, variants, clamp=False)


async def load_full_battles(player_tag: str, live_battles: list[dict] | None = None) -> list[dict]:
    """Merge live battle log with full battle_cache history (same source as winrates)."""
    tag = normalize_tag(player_tag)
    rows = await get_cached_battle_rows(tag, limit=5000)
    cached = [row_to_battle_dict(r, tag) for r in rows]
    return _merge_battles(live_battles or [], cached)


async def _load_full_winrates(player_tag: str, live_battles: list[dict]) -> dict[str, dict]:
    merged = await load_full_battles(player_tag, live_battles)
    return calculate_deck_winrates(merged, normalize_tag(player_tag))


def _touch_existing(
    existing: TrackedMineDeck,
    cards: list[str],
    seen: str,
    deck_cards: list[dict] | None = None,
) -> None:
    if cards:
        existing.cards_csv = ",".join(cards)
    if seen and seen >= (existing.last_seen or ""):
        existing.last_seen = seen
    if not deck_cards or len(deck_cards) != 8:
        return
    stored = parse_deck_cards_json(getattr(existing, "cards_json", None))
    # Prefer incoming order when it carries upgrades; always OR modes so nothing is lost
    if deck_upgrade_score(deck_cards) > 0 or not stored:
        base = deck_cards
    else:
        base = stored
    combined = or_merge_modes_onto(
        base,
        [deck_cards, stored] if stored else [deck_cards],
        clamp=False,
    )
    # Never write a poorer snapshot over a richer stored one
    if deck_upgrade_score(combined) < deck_upgrade_score(stored):
        return
    if not stored or deck_upgrade_score(combined) > deck_upgrade_score(stored) or (
        [c.get("name") for c in combined] != [c.get("name") for c in stored]
        and deck_upgrade_score(combined) >= deck_upgrade_score(stored)
    ):
        existing.cards_json = serialize_deck_cards(combined)
    elif not getattr(existing, "cards_json", None):
        existing.cards_json = serialize_deck_cards(combined)


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
            if profile_key in winrates:
                row = dict(winrates[profile_key])
                row["cards"] = profile_names
                # OR profile modes onto battle-derived cards (never wipe evo from history)
                row["deck_cards"] = _combine_deck_cards(
                    profile_deck,
                    row.get("deck_cards") or [],
                )
                winrates[profile_key] = row
            else:
                winrates[profile_key] = _empty_stats(profile_names, profile_deck)

    async with _lock_for_user(user.id):
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

            async def ensure_slot(
                key: str,
                cards: list[str],
                seen: str,
                deck_cards: list[dict] | None = None,
            ) -> None:
                nonlocal by_key
                existing = by_key.get(key)
                if existing is not None:
                    _touch_existing(existing, cards, seen, deck_cards)
                    return

                if len(by_key) >= MAX_MINE_DECKS:
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
                    await session.delete(victim)
                    await session.flush()

                initial_json = ""
                if deck_cards and len(deck_cards) == 8:
                    initial_json = serialize_deck_cards(deck_cards)
                row = TrackedMineDeck(
                    user_id=user.id,
                    deck_key=key,
                    cards_csv=",".join(cards),
                    cards_json=initial_json,
                    last_seen=seen or "",
                )
                try:
                    async with session.begin_nested():
                        session.add(row)
                        await session.flush()
                    by_key[key] = row
                    protected.add(key)
                    return
                except IntegrityError:
                    logger.warning(
                        "Mine decks: duplicate key %s for user_id=%s — updating existing",
                        key,
                        user.id,
                    )

                # Гонка / уже есть в БД — подтянуть и обновить
                res_existing = await session.execute(
                    select(TrackedMineDeck).where(
                        TrackedMineDeck.user_id == user.id,
                        TrackedMineDeck.deck_key == key,
                    )
                )
                existing = res_existing.scalar_one_or_none()
                if existing is None:
                    return
                by_key[key] = existing
                protected.add(key)
                _touch_existing(existing, cards, seen, deck_cards)

            # Сначала свежие бои (уже от новых к старым уникальные)
            for key, names, seen, parsed in sightings:
                rich = parsed if len(parsed) == 8 else (winrates.get(key) or {}).get("deck_cards")
                await ensure_slot(key, names, seen, rich if rich and len(rich) == 8 else None)

            if profile_key:
                profile_seen = ""
                for sk, _names, seen, _parsed in sightings:
                    if sk == profile_key:
                        profile_seen = seen
                        break
                await ensure_slot(
                    profile_key,
                    profile_names,
                    profile_seen,
                    profile_deck,
                )

            # Подтянуть evo/hero из winrates в уже существующие слоты
            for key, slot in list(by_key.items()):
                stats = winrates.get(key)
                if not stats:
                    continue
                dc = stats.get("deck_cards") or []
                if len(dc) == 8:
                    names = [c.get("name") for c in dc if c.get("name")]
                    if len(names) == 8:
                        _touch_existing(slot, names, slot.last_seen or "", dc)

            # Bootstrap: если слотов нет — заполнить топом из истории (сначала недавно сыгранные)
            if not by_key and winrates:
                keys_by_recency = sorted(
                    winrates.keys(),
                    key=lambda k: (winrates[k].get("last_seen") or "", winrates[k].get("total") or 0),
                    reverse=True,
                )
                for key in keys_by_recency[:MAX_MINE_DECKS]:
                    data = winrates[key]
                    cards = list(data.get("cards") or key.split("|"))
                    seen = data.get("last_seen") or ""
                    await ensure_slot(key, cards, seen, data.get("deck_cards"))

            try:
                await session.commit()
            except IntegrityError:
                logger.exception(
                    "Mine decks: commit IntegrityError for user_id=%s — rollback and read-only",
                    user.id,
                )
                await session.rollback()

            # Перечитать после commit / rollback
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
        stored_cards = parse_deck_cards_json(getattr(slot, "cards_json", None))
        last_seen = slot.last_seen or (stats or {}).get("last_seen") or ""
        if stats:
            row = dict(stats)
            row["last_seen"] = last_seen
            combined = _combine_deck_cards(
                row.get("deck_cards") or [],
                stored_cards,
            )
            if combined:
                row["deck_cards"] = combined
                row["cards"] = [c["name"] for c in combined]
            elif len(cards_from_csv) == 8 and not row.get("deck_cards"):
                row["cards"] = cards_from_csv
            out.append(row)
        else:
            cards = cards_from_csv or slot.deck_key.split("|")
            out.append({**_empty_stats(cards, stored_cards or None), "last_seen": last_seen})

    out.sort(key=lambda row: row.get("last_seen") or "", reverse=True)
    return out[:MAX_MINE_DECKS]


async def clear_tracked_mine_decks_for_user(user_id: int) -> int:
    """Remove all tracked «Мои колоды» slots for a user (e.g. after CR tag rebind)."""
    async with async_session() as session:
        res = await session.execute(
            delete(TrackedMineDeck).where(TrackedMineDeck.user_id == user_id)
        )
        await session.commit()
        deleted = int(res.rowcount or 0)
        if deleted:
            logger.info("Cleared %s tracked mine decks for user_id=%s", deleted, user_id)
        return deleted

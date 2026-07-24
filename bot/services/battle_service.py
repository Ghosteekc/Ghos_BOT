import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from bot.models import database
from bot.models.database import BattleCache, User
from bot.services.clash_api import ClashRoyaleAPIError, ClashRoyaleClient, normalize_tag
from bot.services.battle_time import battle_time_from_record
from bot.services.battle_opponent import resolve_opponent_fields
from bot.services.deck_analyzer import analyze_battle

logger = logging.getLogger(__name__)

# Clash Royale battle log API returns up to 25 recent battles.
BATTLE_LOG_LIMIT = 25

_persist_locks: dict[str, asyncio.Lock] = {}


def battle_has_player(battle: dict, player_tag: str) -> bool:
    tag = normalize_tag(player_tag)
    for side in ("team", "opponent"):
        for player in battle.get(side) or []:
            if normalize_tag(player.get("tag") or "") == tag:
                return True
    return False


def _side_crowns(players: list) -> int:
    if not players:
        return 0
    return max(int(p.get("crowns") or 0) for p in players)


def normalize_battle_for_player(battle: dict, player_tag: str) -> dict | None:
    """Put the linked player in team[0] (supports 2v2 and opponent-side entries)."""
    tag = normalize_tag(player_tag)
    teams = list(battle.get("team") or [])
    opps = list(battle.get("opponent") or [])

    team_idx = next(
        (i for i, p in enumerate(teams) if normalize_tag(p.get("tag") or "") == tag),
        None,
    )
    opp_idx = next(
        (i for i, p in enumerate(opps) if normalize_tag(p.get("tag") or "") == tag),
        None,
    )
    if team_idx is None and opp_idx is None:
        return None

    if team_idx is not None:
        player = dict(teams[team_idx])
        user_crowns = _side_crowns(teams)
        opp_crowns = _side_crowns(opps)
        opponent = dict(opps[0]) if opps else {}
    else:
        player = dict(opps[opp_idx])
        user_crowns = _side_crowns(opps)
        opp_crowns = _side_crowns(teams)
        opponent = dict(teams[0]) if teams else {}
        trophy_change = player.get("trophyChange")
        if trophy_change is not None:
            player["trophyChange"] = -int(trophy_change)

    player["crowns"] = user_crowns
    opponent["crowns"] = opp_crowns

    normalized = dict(battle)
    normalized["team"] = [player]
    normalized["opponent"] = [opponent]
    return normalized


def filter_pvp_battles(battles: list, player_tag: str) -> list:
    excluded = frozenset({
        "friendly",
        "clanmate",
        "warday",
        "boatbattle",
        "challenge",
        "cached",
    })
    result = []
    for b in battles:
        battle_type = (b.get("type") or "").strip().lower().replace(" ", "")
        if battle_type in excluded:
            continue
        if not battle_has_player(b, player_tag):
            continue
        normalized = normalize_battle_for_player(b, player_tag)
        if normalized:
            result.append(normalized)
    return result


async def load_pvp_battles(
    player_tag: str,
    *,
    client: ClashRoyaleClient | None = None,
    bypass_ttl: bool = False,
) -> list | None:
    from bot.services.battle_session_cache import is_fresh

    tag = normalize_tag(player_tag)
    if not bypass_ttl and is_fresh(tag):
        logger.debug("Skipping CR battlelog for %s (fetched within TTL)", tag)
        return None

    logger.debug(f"Loading PvP battles for {player_tag}")
    owns_client = client is None
    client = client or ClashRoyaleClient()
    try:
        battles = await client.get_battlelog(player_tag)
    except ClashRoyaleAPIError:
        logger.warning(f"Failed to load battles for {player_tag}: API error")
        return None
    finally:
        if owns_client:
            await client.close()
    pvp = filter_pvp_battles(battles, player_tag)
    logger.info(f"Loaded {len(pvp)} PvP battles for {player_tag} from API")
    return pvp


def build_battle_cache_row(battle: dict, player_tag: str) -> dict | None:
    """Build insert payload for BattleCache or None if battle time is missing."""
    battle_time = battle_time_from_record(battle)
    if not battle_time:
        logger.debug("Skipping battle without battleTime/warTime for %s", player_tag)
        return None

    team = battle.get("team", [{}])[0]
    opponent = battle.get("opponent", [{}])[0]
    team_cards = [c.get("name") for c in team.get("cards", [])]
    opp_cards = [c.get("name") for c in opponent.get("cards", [])]
    result = "win" if team.get("crowns", 0) > opponent.get("crowns", 0) else "loss"

    try:
        analysis_obj = analyze_battle(team, opponent)
        analysis_text = "\n".join(analysis_obj.reasons)
    except Exception as exc:
        logger.debug("Battle analysis error for %s: %s", player_tag, exc)
        analysis_text = None

    opp_name, opp_tag = resolve_opponent_fields(opponent)

    return {
        "player_tag": normalize_tag(player_tag),
        "battle_time": battle_time,
        "result": result,
        "user_deck": ",".join(c for c in team_cards if c),
        "opponent_deck": ",".join(c for c in opp_cards if c),
        "opponent_name": opp_name,
        "opponent_tag": opp_tag,
        "analysis": analysis_text,
    }


async def _insert_battle_row(session, row: dict) -> bool:
    """Insert battle row; return True when this call stored a new battle."""
    existing = await session.execute(
        select(BattleCache).where(
            BattleCache.player_tag == row["player_tag"],
            BattleCache.battle_time == row["battle_time"],
        )
    )
    battle_row = existing.scalar_one_or_none()
    if battle_row is not None:
        updated = False
        if row.get("opponent_name") and not (battle_row.opponent_name or "").strip():
            battle_row.opponent_name = row["opponent_name"]
            updated = True
        if row.get("opponent_tag") and not (battle_row.opponent_tag or "").strip():
            battle_row.opponent_tag = row["opponent_tag"]
            updated = True
        if updated:
            await session.flush()
        return False

    try:
        await session.execute(
            sqlite_insert(BattleCache)
            .values(**row)
            .on_conflict_do_nothing(index_elements=["player_tag", "battle_time"])
        )
        await session.flush()
    except Exception:
        session.add(BattleCache(**row))
        await session.flush()
        return True

    created = await session.execute(
        select(BattleCache.id).where(
            BattleCache.player_tag == row["player_tag"],
            BattleCache.battle_time == row["battle_time"],
        )
    )
    return created.scalar_one_or_none() is not None


async def persist_battles(user: User, battles: list) -> int:
    """Persist PvP battles; skip duplicates and ignore concurrent double-inserts."""
    if not user.player_tag or not battles:
        return 0

    tag = normalize_tag(user.player_tag)
    lock = _persist_locks.setdefault(tag, asyncio.Lock())

    async with lock:
        logger.info("Persisting %d battles for %s", len(battles), tag)
        saved = 0
        async with database.async_session() as session:
            for battle in battles:
                row = build_battle_cache_row(battle, tag)
                if row is None:
                    continue
                if await _insert_battle_row(session, row):
                    saved += 1

            if saved or session.dirty:
                await session.commit()
                if saved:
                    logger.info("Saved %d new battles for %s", saved, tag)

        return saved


@dataclass
class CachedStats:
    total: int
    wins: int
    losses: int
    winrate: float
    top_decks: list[dict]
    top_cards: list[tuple[str, int]]
    win_streak: int
    loss_streak: int


async def get_cached_stats(player_tag: str) -> CachedStats | None:
    async with database.async_session() as session:
        res = await session.execute(
            select(BattleCache).where(BattleCache.player_tag == normalize_tag(player_tag))
        )
        cached = res.scalars().all()

    if not cached:
        return None

    total = len(cached)
    wins = sum(1 for r in cached if r.result == "win")
    losses = total - wins
    wr = round(wins / total * 100, 1) if total else 0.0

    decks: dict[str, dict] = {}
    for r in cached:
        if not r.user_deck:
            continue
        decks.setdefault(r.user_deck, {"total": 0, "wins": 0})
        decks[r.user_deck]["total"] += 1
        if r.result == "win":
            decks[r.user_deck]["wins"] += 1

    top_decks = []
    for deck_key, data in sorted(decks.items(), key=lambda x: x[1]["total"], reverse=True)[:5]:
        cards = deck_key.split(",")
        deck_wr = round(data["wins"] / data["total"] * 100, 1) if data["total"] else 0
        top_decks.append({"cards": cards, "total": data["total"], "winrate": deck_wr})

    card_counts: dict[str, int] = {}
    for r in cached:
        for c in (r.user_deck or "").split(","):
            if c:
                card_counts[c] = card_counts.get(c, 0) + 1
    top_cards = sorted(card_counts.items(), key=lambda x: x[1], reverse=True)[:6]

    win_streak = 0
    loss_streak = 0
    try:
        sorted_rows = sorted(cached, key=lambda r: r.battle_time or "", reverse=True)
        for r in sorted_rows:
            if r.result == "win":
                if loss_streak:
                    break
                win_streak += 1
            else:
                if win_streak:
                    break
                loss_streak += 1
    except Exception:
        pass

    return CachedStats(
        total=total,
        wins=wins,
        losses=losses,
        winrate=wr,
        top_decks=top_decks,
        top_cards=top_cards,
        win_streak=win_streak,
        loss_streak=loss_streak,
    )


def _is_live_battlelog(battles: list) -> bool:
    """DB cache stubs use type=cached and zero trophyChange — not usable for trophy charts."""
    if not battles:
        return False
    for battle in battles:
        battle_type = (battle.get("type") or "").strip().lower().replace(" ", "")
        if battle_type and battle_type != "cached":
            return True
    return False


async def load_and_persist(user: User, *, force_refresh: bool = False) -> list | None:
    if not user.player_tag:
        return None

    from bot.services.battle_cache_reader import get_battles_from_cache
    from bot.services.battle_session_cache import (
        get_session_battles,
        is_fresh,
        set_session_battles,
    )

    tag = normalize_tag(user.player_tag)

    if not force_refresh:
        session_battles = get_session_battles(user.telegram_id)
        if (
            session_battles is not None
            and is_fresh(tag)
            and _is_live_battlelog(session_battles)
        ):
            return session_battles

    # Always hit CR when session is stale/missing — never treat DB stubs as a fresh log.
    battles = await load_pvp_battles(user.player_tag, bypass_ttl=True)
    if battles is None:
        session_battles = get_session_battles(user.telegram_id)
        if session_battles is not None and _is_live_battlelog(session_battles):
            return session_battles
        cached = await get_battles_from_cache(user.player_tag)
        return cached or None

    if battles:
        await persist_battles(user, battles)
        set_session_battles(user.telegram_id, tag, battles)
        return battles

    session_battles = get_session_battles(user.telegram_id)
    if session_battles is not None and _is_live_battlelog(session_battles):
        return session_battles
    cached = await get_battles_from_cache(user.player_tag)
    return cached or []


async def delete_persisted_battles_for_user(user: User) -> int:
    """Delete battle_cache rows for the linked player tag only."""
    if not user.player_tag:
        return 0

    tag = normalize_tag(user.player_tag)
    if not tag:
        return 0

    async with database.async_session() as session:
        count_res = await session.execute(
            select(func.count())
            .select_from(BattleCache)
            .where(BattleCache.player_tag == tag)
        )
        to_delete = int(count_res.scalar_one() or 0)
        if to_delete:
            await session.execute(delete(BattleCache).where(BattleCache.player_tag == tag))
            await session.commit()
            logger.info("Deleted %d battle_cache rows for %s (user_id=%s)", to_delete, tag, user.id)

    from bot.services.battle_session_cache import clear_user

    clear_user(user.telegram_id, tag)
    return to_delete

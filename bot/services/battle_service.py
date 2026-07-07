import logging
from dataclasses import dataclass

from sqlalchemy import select

from bot.models.database import BattleCache, User, async_session
from bot.services.clash_api import ClashRoyaleAPIError, ClashRoyaleClient, normalize_tag
from bot.services.deck_analyzer import analyze_battle

logger = logging.getLogger(__name__)

# Clash Royale battle log API returns up to 25 recent battles.
BATTLE_LOG_LIMIT = 25


def filter_pvp_battles(battles: list, player_tag: str) -> list:
    tag = normalize_tag(player_tag)
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
        team_tag = b.get("team", [{}])[0].get("tag", "")
        if normalize_tag(team_tag) != tag:
            continue
        result.append(b)
    return result


async def load_pvp_battles(player_tag: str) -> list | None:
    logger.debug(f"Loading PvP battles for {player_tag}")
    client = ClashRoyaleClient()
    try:
        battles = await client.get_battlelog(player_tag)
    except ClashRoyaleAPIError:
        logger.warning(f"Failed to load battles for {player_tag}: API error")
        return None
    finally:
        await client.close()
    pvp = filter_pvp_battles(battles, player_tag)
    logger.info(f"Loaded {len(pvp)} PvP battles for {player_tag} from API")
    return pvp


async def persist_battles(user: User, battles: list) -> None:
    logger.info(f"Persisting {len(battles)} battles for {user.player_tag}")
    async with async_session() as session:
        saved = 0
        for b in battles:
            team = b.get("team", [{}])[0]
            battle_time = b.get("battleTime") or b.get("warTime") or ""
            q = await session.execute(
                select(BattleCache).where(
                    BattleCache.player_tag == normalize_tag(user.player_tag),
                    BattleCache.battle_time == str(battle_time),
                )
            )
            if q.scalar_one_or_none():
                continue

            opponent = b.get("opponent", [{}])[0]
            team_cards = [c.get("name") for c in team.get("cards", [])]
            opp_cards = [c.get("name") for c in opponent.get("cards", [])]
            result = "win" if team.get("crowns", 0) > opponent.get("crowns", 0) else "loss"

            try:
                analysis_obj = analyze_battle(team, opponent)
                analysis_text = "\n".join(analysis_obj.reasons)
            except Exception as e:
                logger.debug(f"Battle analysis error for {user.player_tag}: {e}")
                analysis_text = None

            session.add(BattleCache(
                player_tag=normalize_tag(user.player_tag),
                battle_time=str(battle_time),
                result=result,
                user_deck=",".join(c for c in team_cards if c),
                opponent_deck=",".join(c for c in opp_cards if c),
                analysis=analysis_text,
            ))
            saved += 1
        if saved:
            await session.commit()
            logger.info(f"Saved {saved} new battles for {user.player_tag}")


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
    async with async_session() as session:
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
        if session_battles is not None and is_fresh(tag):
            return session_battles

        cached = await get_battles_from_cache(user.player_tag)
        if cached and is_fresh(tag):
            set_session_battles(user.telegram_id, tag, cached)
            return cached

    battles = await load_pvp_battles(user.player_tag)
    if battles is None:
        cached = await get_battles_from_cache(user.player_tag)
        if cached:
            set_session_battles(user.telegram_id, tag, cached)
        return cached or None

    if battles:
        await persist_battles(user, battles)
        set_session_battles(user.telegram_id, tag, battles)
        return battles

    cached = await get_battles_from_cache(user.player_tag)
    if cached:
        set_session_battles(user.telegram_id, tag, cached)
    return cached or []

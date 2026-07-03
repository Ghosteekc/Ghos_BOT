import asyncio
import logging
from datetime import datetime

from sqlalchemy import select

from bot.models.database import async_session, User, BattleCache
from bot.services.clash_api import ClashRoyaleClient, normalize_tag
from bot.services.deck_analyzer import analyze_battle
from bot.config import settings

logger = logging.getLogger(__name__)


async def sync_user_battles(user: User) -> int:
    """Fetch user's battlelog and persist new PvP battles. Returns number of new saved battles."""
    if not user.player_tag:
        return 0

    client = ClashRoyaleClient()
    try:
        battles = await client.get_battlelog(user.player_tag)
    except Exception as e:
        logger.debug("Failed to fetch battles for %s: %s", user.player_tag, e)
        return 0
    finally:
        await client.close()

    tag = normalize_tag(user.player_tag)
    pvp = [
        b for b in battles
        if b.get("type") in ("PvP", "pathOfLegend")
        and b.get("team", [{}])[0].get("tag", "").upper() == tag.upper()
    ]

    new_count = 0
    async with async_session() as session:
        for b in pvp:
            team = b.get("team", [{}])[0]
            opponent = b.get("opponent", [{}])[0]
            battle_time = b.get("battleTime") or b.get("warTime") or ""

            q = await session.execute(
                select(BattleCache).where(
                    BattleCache.player_tag == normalize_tag(user.player_tag),
                    BattleCache.battle_time == str(battle_time),
                )
            )
            existing = q.scalar_one_or_none()
            if existing:
                continue

            team_cards = [c.get("name") for c in team.get("cards", [])]
            opp_cards = [c.get("name") for c in opponent.get("cards", [])]
            result = "win" if team.get("crowns", 0) > opponent.get("crowns", 0) else "loss"

            try:
                analysis_obj = analyze_battle(team, opponent)
                analysis_text = "\n".join(analysis_obj.reasons)
            except Exception:
                analysis_text = None

            bc = BattleCache(
                player_tag=normalize_tag(user.player_tag),
                battle_time=str(battle_time),
                result=result,
                user_deck=",".join([c for c in team_cards if c]),
                opponent_deck=",".join([c for c in opp_cards if c]),
                analysis=analysis_text,
            )
            session.add(bc)
            new_count += 1
        if new_count:
            await session.commit()

    return new_count


async def sync_all_once() -> dict[str, int]:
    """Sync all users once. Returns dict of player_tag -> new_count."""
    results: dict[str, int] = {}
    async with async_session() as session:
        res = await session.execute(select(User).where(User.player_tag != None))
        users = res.scalars().all()

    for user in users:
        try:
            new = await sync_user_battles(user)
            if new:
                logger.info("Synced %s: %d new battles", user.player_tag, new)
            results[normalize_tag(user.player_tag)] = new
            await asyncio.sleep(1)  # small pause to avoid burst
        except Exception as e:
            logger.exception("Error syncing %s: %s", user.player_tag, e)
    return results


async def run_periodic(stop_event: asyncio.Event) -> None:
    interval = max(1, settings.sync_interval_minutes) * 60
    logger.info("Starting battle sync loop (interval %d seconds)", interval)
    while not stop_event.is_set():
        try:
            await sync_all_once()
            from bot.services.meta_analyzer import refresh_meta_background
            await refresh_meta_background()
        except Exception:
            logger.exception("Unhandled error during battle sync")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass

    logger.info("Battle sync loop stopped")

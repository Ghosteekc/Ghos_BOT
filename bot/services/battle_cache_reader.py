"""Build API responses from persisted BattleCache when live API is unavailable."""

from sqlalchemy import select

from bot.models.database import BattleCache, async_session
from bot.services.clash_api import normalize_tag
from bot.services.deck_analyzer import analyze_deck


async def get_cached_battle_rows(player_tag: str, limit: int = 25) -> list[BattleCache]:
    async with async_session() as session:
        res = await session.execute(
            select(BattleCache)
            .where(BattleCache.player_tag == normalize_tag(player_tag))
            .order_by(BattleCache.battle_time.desc())
            .limit(limit)
        )
        return list(res.scalars().all())


def row_to_battle_dict(row: BattleCache, player_tag: str) -> dict:
    user_cards = [{"name": c} for c in (row.user_deck or "").split(",") if c]
    opp_cards = [{"name": c} for c in (row.opponent_deck or "").split(",") if c]
    won = row.result == "win"
    tag = normalize_tag(player_tag)
    return {
        "type": "cached",
        "battleTime": row.battle_time,
        "gameDuration": 180,
        "team": [{
            "tag": tag,
            "name": "Вы",
            "crowns": 3 if won else 1,
            "trophyChange": 0,
            "cards": user_cards,
        }],
        "opponent": [{
            "tag": "",
            "name": "Соперник",
            "crowns": 1 if won else 3,
            "cards": opp_cards,
        }],
    }


async def get_battles_from_cache(player_tag: str) -> list[dict]:
    rows = await get_cached_battle_rows(player_tag)
    return [row_to_battle_dict(r, player_tag) for r in rows]

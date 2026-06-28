from fastapi import APIRouter, Depends, HTTPException

from bot.api.deps import require_subscription
from bot.api.schemas import BattleDetailResponse, BattleListResponse, BattleSummary, DeckStatsResponse
from bot.models.database import User
from bot.services.battle_service import get_cached_stats, load_and_persist
from bot.services.deck_analyzer import analyze_battle, analyze_deck, calculate_matchup_score

router = APIRouter(prefix="/api/battles", tags=["battles"])

_battle_cache: dict[int, list] = {}


@router.get("", response_model=BattleListResponse)
async def list_battles(user: User = Depends(require_subscription)) -> BattleListResponse:
    battles = await load_and_persist(user)
    if battles is None:
        raise HTTPException(status_code=502, detail="Failed to load battles from Clash Royale API")

    _battle_cache[user.telegram_id] = battles

    summaries: list[BattleSummary] = []
    for i, battle in enumerate(battles[:10]):
        team = battle.get("team", [{}])[0]
        opponent = battle.get("opponent", [{}])[0]
        won = team.get("crowns", 0) > opponent.get("crowns", 0)
        user_deck = [c["name"] for c in team.get("cards", [])]
        opp_deck = [c["name"] for c in opponent.get("cards", [])]
        summaries.append(BattleSummary(
            index=i,
            opponent_name=opponent.get("name", "Соперник"),
            won=won,
            trophy_change=team.get("trophyChange", 0),
            matchup_score=round(calculate_matchup_score(user_deck, opp_deck), 1),
        ))

    stats = await get_cached_stats(user.player_tag)
    return BattleListResponse(
        battles=summaries,
        cached_total=stats.total if stats else None,
        cached_winrate=stats.winrate if stats else None,
    )


@router.get("/{index}", response_model=BattleDetailResponse)
async def battle_detail(index: int, user: User = Depends(require_subscription)) -> BattleDetailResponse:
    battles = _battle_cache.get(user.telegram_id)
    if battles is None:
        battles = await load_and_persist(user)
        if battles is None:
            raise HTTPException(status_code=502, detail="Failed to load battles")
        _battle_cache[user.telegram_id] = battles

    if index < 0 or index >= len(battles):
        raise HTTPException(status_code=404, detail="Battle not found")

    battle = battles[index]
    team = battle.get("team", [{}])[0]
    opponent = battle.get("opponent", [{}])[0]
    analysis = analyze_battle(team, opponent)
    user_stats = analyze_deck(analysis.user_deck)
    opp_stats = analyze_deck(analysis.opponent_deck)

    def _stats(s) -> DeckStatsResponse:
        return DeckStatsResponse(
            avg_elixir=s.avg_elixir,
            win_conditions=s.win_conditions,
            spells=s.spells,
        )

    return BattleDetailResponse(
        index=index,
        won=analysis.won,
        opponent_name=analysis.opponent_name,
        trophy_change=analysis.trophy_change,
        matchup_score=analysis.matchup_score,
        user_deck=analysis.user_deck,
        opponent_deck=analysis.opponent_deck,
        user_stats=_stats(user_stats),
        opponent_stats=_stats(opp_stats),
        reasons=analysis.reasons,
        opponent_threats=analysis.opponent_threats,
    )

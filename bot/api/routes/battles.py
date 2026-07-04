from fastapi import APIRouter, Depends, HTTPException

from bot.api.deps import require_subscription
from bot.api.schemas import BattleDetailResponse, BattleListResponse, BattleSummary, DeckStatsResponse, KeyCardEntry
from bot.models.database import User
from bot.services.battle_service import BATTLE_LOG_LIMIT, get_cached_stats, load_and_persist
from bot.services.battle_session_cache import set_session_battles
from bot.services.battle_time import format_battle_played_at
from bot.services.battle_report import analyze_battle_enhanced
from bot.services.deck_analyzer import analyze_deck, calculate_matchup_score

router = APIRouter(prefix="/api/battles", tags=["battles"])


def _get_battle_cache(user: User) -> list | None:
    from bot.services.battle_session_cache import get_session_battles

    return get_session_battles(user.telegram_id)


def _set_battle_cache(user: User, battles: list) -> None:
    from bot.services.clash_api import normalize_tag

    set_session_battles(user.telegram_id, normalize_tag(user.player_tag or ""), battles)


def _build_battle_summary(index: int, battle: dict) -> BattleSummary:
    team = battle.get("team", [{}])[0]
    opponent = battle.get("opponent", [{}])[0]
    user_deck = [c["name"] for c in team.get("cards", [])]
    opp_deck = [c["name"] for c in opponent.get("cards", [])]
    won = team.get("crowns", 0) > opponent.get("crowns", 0)
    user_stats = analyze_deck(user_deck)
    duration = int(battle.get("gameDuration") or 0)
    analysis = analyze_battle_enhanced(team, opponent, duration=duration)
    opp_tag = opponent.get("tag", "") or ""
    raw_time = str(battle.get("battleTime") or battle.get("warTime") or "")
    return BattleSummary(
        index=index,
        opponent_name=opponent.get("name", "Соперник"),
        opponent_tag=opp_tag.replace("#", ""),
        opponent_trophies=opponent.get("startingTrophies") or opponent.get("trophyChange") or 0,
        won=won,
        trophy_change=team.get("trophyChange", 0),
        matchup_score=round(calculate_matchup_score(user_deck, opp_deck), 1),
        duration=int(battle.get("gameDuration") or 0),
        avg_elixir=user_stats.avg_elixir,
        user_deck=user_deck,
        opponent_deck=opp_deck,
        top_reason=analysis.outcome_summary or (analysis.reasons[0] if analysis.reasons else None),
        timestamp=raw_time,
        played_at=format_battle_played_at(raw_time),
    )


@router.get("", response_model=BattleListResponse)
async def list_battles(user: User = Depends(require_subscription)) -> BattleListResponse:
    battles = await load_and_persist(user)
    if battles is None:
        raise HTTPException(
            status_code=502,
            detail="Не удалось загрузить бои. Проверьте API-ключ Clash Royale.",
        )

    _set_battle_cache(user, battles)

    summaries = [_build_battle_summary(i, battle) for i, battle in enumerate(battles[:BATTLE_LOG_LIMIT])]

    stats = await get_cached_stats(user.player_tag)
    return BattleListResponse(
        battles=summaries,
        cached_total=stats.total if stats else len(battles),
        cached_winrate=stats.winrate if stats else None,
    )


@router.get("/{index}", response_model=BattleDetailResponse)
async def battle_detail(index: int, user: User = Depends(require_subscription)) -> BattleDetailResponse:
    battles = _get_battle_cache(user)
    if battles is None:
        battles = await load_and_persist(user)
        if battles is None:
            raise HTTPException(status_code=502, detail="Failed to load battles")
        _set_battle_cache(user, battles)

    if index < 0 or index >= len(battles):
        raise HTTPException(status_code=404, detail="Battle not found")

    battle = battles[index]
    team = battle.get("team", [{}])[0]
    opponent = battle.get("opponent", [{}])[0]
    duration = int(battle.get("gameDuration") or 0)
    analysis = analyze_battle_enhanced(team, opponent, duration=duration)
    user_stats = analyze_deck(analysis.user_deck)
    opp_stats = analyze_deck(analysis.opponent_deck)

    def _stats(s) -> DeckStatsResponse:
        return DeckStatsResponse(
            avg_elixir=s.avg_elixir,
            win_conditions=s.win_conditions,
            spells=s.spells,
        )

    def _key_cards(items) -> list[KeyCardEntry]:
        return [KeyCardEntry(name=k.name, name_ru=k.name_ru, note=k.note) for k in items]

    return BattleDetailResponse(
        index=index,
        won=analysis.won,
        opponent_name=analysis.opponent_name,
        trophy_change=analysis.trophy_change,
        matchup_score=analysis.matchup_score,
        duration=duration,
        played_at=format_battle_played_at(
            str(battle.get("battleTime") or battle.get("warTime") or "")
        ),
        crown_score=analysis.crown_score,
        outcome_summary=analysis.outcome_summary,
        user_deck=analysis.user_deck,
        opponent_deck=analysis.opponent_deck,
        user_stats=_stats(user_stats),
        opponent_stats=_stats(opp_stats),
        reasons=analysis.reasons,
        opponent_threats=analysis.opponent_threats,
        user_key_cards=_key_cards(analysis.user_key_cards),
        opponent_key_cards=_key_cards(analysis.opponent_key_cards),
        low_impact_cards=_key_cards(analysis.low_impact_cards),
    )

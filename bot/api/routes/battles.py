from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException

from bot.api.deps import require_linked_player, require_subscription
from bot.services.battle_opponent import resolve_opponent_fields
from bot.api.schemas import (
    BattleDetailResponse,
    BattleHistoryClearResponse,
    BattleListResponse,
    BattleSummary,
    DeckStatsResponse,
    KeyCardEntry,
)
from bot.models.database import User
from bot.services.battle_service import (
    BATTLE_LOG_LIMIT,
    delete_persisted_battles_for_user,
    get_cached_stats,
    load_and_persist,
)
from bot.services.battle_session_cache import set_session_battles
from bot.services.battle_time import battle_time_from_record, battle_times_equal, format_battle_played_at
from bot.services.battle_report import analyze_battle_enhanced
from bot.services.card_names_ru import card_name_ru
from bot.services.deck_analyzer import analyze_deck, calculate_matchup_score
from bot.user_errors import http_error

router = APIRouter(prefix="/api/battles", tags=["battles"])


@router.delete("", response_model=BattleHistoryClearResponse)
async def clear_battle_history(user: User = Depends(require_linked_player)) -> BattleHistoryClearResponse:
    """Remove persisted battle history for the authenticated user's linked tag only."""
    deleted_count = await delete_persisted_battles_for_user(user)
    return BattleHistoryClearResponse(ok=True, deleted_count=deleted_count)


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
    top_reason: str | None = None
    try:
        analysis = analyze_battle_enhanced(team, opponent, duration=duration)
        top_reason = analysis.outcome_summary or (analysis.reasons[0] if analysis.reasons else None)
    except Exception:
        top_reason = None
    opp_name, opp_tag = resolve_opponent_fields(opponent)
    raw_time = battle_time_from_record(battle) or ""
    return BattleSummary(
        index=index,
        opponent_name=opp_name,
        opponent_tag=opp_tag,
        opponent_trophies=opponent.get("startingTrophies") or opponent.get("trophyChange") or 0,
        won=won,
        trophy_change=int(team.get("trophyChange") or 0),
        matchup_score=round(calculate_matchup_score(user_deck, opp_deck), 1),
        duration=int(battle.get("gameDuration") or 0),
        avg_elixir=user_stats.avg_elixir,
        user_deck=user_deck,
        opponent_deck=opp_deck,
        top_reason=top_reason,
        timestamp=raw_time,
        played_at=format_battle_played_at(raw_time),
    )


@router.get("", response_model=BattleListResponse)
async def list_battles(user: User = Depends(require_subscription)) -> BattleListResponse:
    battles = await load_and_persist(user)
    if battles is None:
        raise http_error("E020", status=502)

    _set_battle_cache(user, battles)

    summaries = [_build_battle_summary(i, battle) for i, battle in enumerate(battles[:BATTLE_LOG_LIMIT])]

    stats = await get_cached_stats(user.player_tag)
    return BattleListResponse(
        battles=summaries,
        cached_total=stats.total if stats else len(battles),
        cached_winrate=stats.winrate if stats else None,
    )


def _battle_timestamp(battle: dict) -> str:
    return battle_time_from_record(battle) or ""


async def _load_user_battles(user: User) -> list:
    battles = _get_battle_cache(user)
    if battles is None:
        battles = await load_and_persist(user)
        if battles is None:
            raise http_error("E020", status=502)
        _set_battle_cache(user, battles)
    return battles


def _build_battle_detail(index: int, battle: dict) -> BattleDetailResponse:
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
        played_at=format_battle_played_at(_battle_timestamp(battle)),
        crown_score=analysis.crown_score,
        outcome_summary=analysis.outcome_summary,
        user_deck=analysis.user_deck,
        opponent_deck=analysis.opponent_deck,
        user_stats=_stats(user_stats),
        opponent_stats=_stats(opp_stats),
        reasons=analysis.reasons,
        opponent_threats=[
            card_name_ru(threat, short=True) or threat for threat in analysis.opponent_threats
        ],
        user_key_cards=_key_cards(analysis.user_key_cards),
        opponent_key_cards=_key_cards(analysis.opponent_key_cards),
        low_impact_cards=_key_cards(analysis.low_impact_cards),
    )


@router.get("/by-time/{battle_time:path}", response_model=BattleDetailResponse)
async def battle_detail_by_time(
    battle_time: str,
    user: User = Depends(require_subscription),
) -> BattleDetailResponse:
    raw = unquote(battle_time)
    battles = await _load_user_battles(user)
    for i, battle in enumerate(battles):
        if battle_times_equal(_battle_timestamp(battle), raw):
            return _build_battle_detail(i, battle)
    raise http_error("E004", status=404)


@router.get("/{index}", response_model=BattleDetailResponse)
async def battle_detail(index: int, user: User = Depends(require_subscription)) -> BattleDetailResponse:
    battles = await _load_user_battles(user)
    if index < 0 or index >= len(battles):
        raise http_error("E004", status=404)
    return _build_battle_detail(index, battles[index])

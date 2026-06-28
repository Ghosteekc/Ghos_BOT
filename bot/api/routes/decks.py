from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from bot.api.deps import require_subscription
from bot.api.schemas import (
    CounterDeckResponse,
    CustomizeResponse,
    OpponentEntry,
    RecommendationsResponse,
    StatsDeckEntry,
    StatsResponse,
    SynergyResponse,
    WinrateEntry,
)
from bot.models.database import User
from bot.services.battle_service import get_cached_stats, load_and_persist
from bot.services.clash_api import ClashRoyaleAPIError, normalize_tag
from bot.services.counter_engine import (
    analyze_opponent_deck_from_battles,
    build_synergy_deck,
    customize_deck_for_arena,
    suggest_counter_deck,
)
from bot.services.deck_analyzer import calculate_deck_winrates, get_most_played_cards

router = APIRouter(prefix="/api", tags=["decks"])

_opponents_cache: dict[int, list] = {}


async def _get_battles(user: User) -> list:
    battles = await load_and_persist(user)
    if battles is None:
        raise HTTPException(status_code=502, detail="Failed to load battles from Clash Royale API")
    return battles


@router.get("/winrates", response_model=list[WinrateEntry])
async def deck_winrates(user: User = Depends(require_subscription)) -> list[WinrateEntry]:
    battles = await _get_battles(user)
    winrates = calculate_deck_winrates(battles, normalize_tag(user.player_tag))
    result = []
    for i, (_, data) in enumerate(winrates.items()):
        if i >= 10:
            break
        result.append(WinrateEntry(
            cards=data["cards"],
            wins=data["wins"],
            losses=data["losses"],
            total=data["total"],
            winrate=data["winrate"],
        ))
    return result


@router.get("/opponents", response_model=list[OpponentEntry])
async def list_opponents(user: User = Depends(require_subscription)) -> list[OpponentEntry]:
    battles = await _get_battles(user)
    opponents = analyze_opponent_deck_from_battles(battles, normalize_tag(user.player_tag))
    _opponents_cache[user.telegram_id] = opponents
    return [
        OpponentEntry(
            index=i,
            name=opp["name"],
            deck=opp["deck"],
            threats=opp["threats"],
            avg_elixir=opp["avg_elixir"],
            won_against=opp["won_against"],
        )
        for i, opp in enumerate(opponents)
    ]


@router.get("/opponents/{index}/counter", response_model=CounterDeckResponse)
async def counter_deck(index: int, user: User = Depends(require_subscription)) -> CounterDeckResponse:
    opponents = _opponents_cache.get(user.telegram_id)
    if opponents is None:
        battles = await _get_battles(user)
        opponents = analyze_opponent_deck_from_battles(battles, normalize_tag(user.player_tag))
        _opponents_cache[user.telegram_id] = opponents

    if index < 0 or index >= len(opponents):
        raise HTTPException(status_code=404, detail="Opponent not found")

    opp = opponents[index]
    battles = await _get_battles(user)
    preferred = [c for c, _ in get_most_played_cards(battles, normalize_tag(user.player_tag))]
    counter = suggest_counter_deck(opp["deck"], user.arena_id, preferred)

    return CounterDeckResponse(
        opponent_name=opp["name"],
        opponent_deck=opp["deck"],
        counter_deck=counter,
        threats=opp["threats"],
        preferred_cards=preferred[:3],
    )


@router.get("/customize", response_model=CustomizeResponse)
async def customize_deck(user: User = Depends(require_subscription)) -> CustomizeResponse:
    battles = await _get_battles(user)
    tag = normalize_tag(user.player_tag)
    preferred = [c for c, _ in get_most_played_cards(battles, tag)]

    current_deck: list[str] = []
    for battle in battles:
        team = battle.get("team", [{}])[0]
        if team.get("tag", "").upper() == tag.upper():
            current_deck = [c["name"] for c in team.get("cards", [])]
            break

    if not current_deck:
        raise HTTPException(status_code=404, detail="No deck found in recent battles")

    result = customize_deck_for_arena(current_deck, user.arena_id, preferred)
    return CustomizeResponse(
        original=result["original"],
        customized=result["customized"],
        issues=result["issues"],
        avg_elixir=result["avg_elixir"],
    )


@router.get("/synergy", response_model=SynergyResponse)
async def synergy_deck(user: User = Depends(require_subscription)) -> SynergyResponse:
    battles = await _get_battles(user)
    tag = normalize_tag(user.player_tag)
    top_cards = get_most_played_cards(battles, tag, top_n=3)
    core = [c for c, _ in top_cards]

    if not core:
        raise HTTPException(status_code=404, detail="Not enough card data")

    result = build_synergy_deck(core, user.arena_id)
    return SynergyResponse(
        core=core,
        deck=result["deck"],
        synergies=result["synergies"],
        avg_elixir=result["avg_elixir"],
    )


@router.get("/stats", response_model=StatsResponse)
async def extended_stats(user: User = Depends(require_subscription)) -> StatsResponse:
    stats = await get_cached_stats(user.player_tag)
    if stats is None:
        battles = await _get_battles(user)
        if not battles:
            raise HTTPException(status_code=404, detail="No battle data")
        stats = await get_cached_stats(user.player_tag)
        if stats is None:
            raise HTTPException(status_code=404, detail="No cached stats")

    return StatsResponse(
        player_tag=user.player_tag,
        total=stats.total,
        wins=stats.wins,
        losses=stats.losses,
        winrate=stats.winrate,
        top_decks=[
            StatsDeckEntry(cards=d["cards"], total=d["total"], winrate=d["winrate"])
            for d in stats.top_decks
        ],
        top_cards=[{"name": c, "count": cnt} for c, cnt in stats.top_cards],
        win_streak=stats.win_streak,
        loss_streak=stats.loss_streak,
    )


@router.get("/recommendations", response_model=RecommendationsResponse)
async def recommendations(user: User = Depends(require_subscription)) -> RecommendationsResponse:
    battles = await _get_battles(user)
    tag = normalize_tag(user.player_tag)

    current_deck: list[str] = []
    last_battle = None
    for battle in battles:
        team = battle.get("team", [{}])[0]
        if team.get("tag", "").upper() == tag.upper():
            current_deck = [c.get("name") for c in team.get("cards", []) if c.get("name")]
            last_battle = battle
            break

    preferred = [c for c, _ in get_most_played_cards(battles, tag)]

    deck_result = None
    if current_deck:
        try:
            deck_result = customize_deck_for_arena(current_deck, user.arena_id, preferred)
        except Exception:
            deck_result = None

    top_cards = get_most_played_cards(battles, tag, top_n=3)
    core = [c for c, _ in top_cards]
    synergy = build_synergy_deck(core, user.arena_id) if core else None

    last_summary = None
    if last_battle:
        team = last_battle.get("team", [{}])[0]
        opp = last_battle.get("opponent", [{}])[0]
        won = team.get("crowns", 0) > opp.get("crowns", 0)
        try:
            analysis = analyze_battle(team, opp)
            last_summary = {
                "won": won,
                "opponent_name": opp.get("name", "Соперник"),
                "trophy_change": team.get("trophyChange", 0),
                "matchup_score": round(analysis.matchup_score, 1),
                "top_reason": analysis.reasons[0] if analysis.reasons else None,
            }
        except Exception:
            last_summary = None

    return RecommendationsResponse(
        current_deck=current_deck,
        avg_elixir=deck_result["avg_elixir"] if deck_result else 0.0,
        issues=deck_result["issues"] if deck_result else [],
        customized_deck=deck_result["customized"] if deck_result else [],
        synergy_core=core,
        synergy_deck=synergy["deck"] if synergy else [],
        last_battle=last_summary,
    )

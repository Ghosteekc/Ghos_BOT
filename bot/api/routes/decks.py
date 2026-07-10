import logging
from bot.services.battle_day_stats import build_last_results, build_most_used_cards, build_winrate_by_day, compute_daily_trophy_change

from fastapi import APIRouter, Depends, HTTPException, Query

from bot.api.deps import require_linked_player, require_subscription
from bot.api.schemas import (
    ArenaDecksResponse,
    CounterDeckResponse,
    CustomizeResponse,
    DeckCardInfo,
    DeckCompareRequest,
    DeckCompareResponse,
    DeckEntry,
    DeckImprovementSuggestion,
    DeckCardMatchup,
    MineDeckStatsRequest,
    MineDeckStatsResponse,
    DeckListResponse,
    InsightsResponse,
    OpponentEntry,
    RandomDeckResponse,
    RecommendationsResponse,
    StatsDeckEntry,
    StatsOverviewResponse,
    StatsResponse,
    SynergyResponse,
    TopPlayerEntry,
    TopPlayersResponse,
    WinrateEntry,
)
from bot.models.database import User
from bot.services.battle_service import BATTLE_LOG_LIMIT, get_cached_stats, load_and_persist

from bot.services.battle_cache_reader import get_battles_for_winrate_chart
from bot.services.card_registry import build_deck_share_link, ensure_cards_loaded, get_card_info
from bot.services.clash_api import ClashRoyaleAPIError, ClashRoyaleClient, normalize_tag
from bot.services.card_data import get_card_elixir
from bot.services.counter_engine import (
    analyze_opponent_deck_from_battles,
    build_synergy_deck,
    customize_deck_for_arena,
    suggest_counter_deck,
)
from bot.services.deck_analyzer import analyze_battle, analyze_deck, calculate_deck_winrates, get_most_played_cards
from bot.services.arena_decks import build_classic_meta_entries, get_arena_popular_decks
from bot.services.deck_compare import compare_decks
from bot.services.deck_detail import build_mine_deck_stats
from bot.services.top_players import get_top_players
from bot.services.meta_analyzer import _guess_deck_name
from bot.services.random_deck import generate_random_deck
from bot.services.battle_insights import build_insights_report

router = APIRouter(prefix="/api", tags=["decks"])

_opponents_cache: dict[int, list] = {}


async def _get_battles(user: User) -> list:
    battles = await load_and_persist(user)
    if battles is None:
        raise HTTPException(status_code=502, detail="Не удалось загрузить бои")
    return battles


def _stats_from_battles(battles: list, tag: str):
    """Minimal stats object when SQLite cache is empty."""
    from types import SimpleNamespace

    tag_norm = normalize_tag(tag)
    wins = losses = 0
    card_counts: dict[str, int] = {}
    for battle in battles:
        team = battle.get("team", [{}])[0]
        if team.get("tag") and normalize_tag(team.get("tag", "")) != tag_norm:
            continue
        opponent = battle.get("opponent", [{}])[0]
        won = team.get("crowns", 0) > opponent.get("crowns", 0)
        if won:
            wins += 1
        else:
            losses += 1
        for c in team.get("cards", []):
            name = c.get("name")
            if name:
                card_counts[name] = card_counts.get(name, 0) + 1
    total = wins + losses
    wr = round(wins / total * 100, 1) if total else 0.0
    top_cards = sorted(card_counts.items(), key=lambda x: x[1], reverse=True)[:6]
    return SimpleNamespace(
        total=total,
        wins=wins,
        losses=losses,
        winrate=wr,
        top_decks=[],
        top_cards=top_cards,
    )


async def _build_meta_deck_entries() -> tuple[list[DeckEntry], str | None, str | None]:
    items, updated, source = await build_classic_meta_entries()
    entries: list[DeckEntry] = []
    for item in items:
        cards = [
            DeckCardInfo(
                id=c["id"],
                name=c["name"],
                icon=c.get("icon", ""),
                cost=c.get("cost", 0),
                evolution_level=c.get("evolution_level", 0),
                is_hero=c.get("is_hero", False),
                slot=c.get("slot", 0),
            )
            for c in item["cards"]
        ]
        entries.append(DeckEntry(
            id=item["id"],
            name=item["name"],
            cards=cards,
            winrate=item.get("winrate", 0.0),
            total_games=item.get("total_games", 0),
            avg_elixir=item.get("avg_elixir", 0.0),
            type="meta",
            category=item.get("category", "meta"),
            deck_link=item.get("deck_link"),
            description=item.get("description", ""),
        ))
    return entries, updated, source


def _user_current_deck(battles: list, tag: str) -> list[str]:
    tag_norm = normalize_tag(tag)
    for battle in battles:
        team = battle.get("team", [{}])[0]
        if team.get("tag") and normalize_tag(team.get("tag", "")) == tag_norm:
            deck = [c.get("name") for c in team.get("cards", []) if c.get("name")]
            if len(deck) == 8:
                return deck
    return []


async def _cards_to_deck_infos(cards: list[str]) -> list[DeckCardInfo]:
    await ensure_cards_loaded()
    infos: list[DeckCardInfo] = []
    for slot, name in enumerate(cards):
        info = get_card_info(name) or {}
        infos.append(DeckCardInfo(
            id=f"{name.lower().replace(' ', '-')}-{slot}",
            name=name,
            icon=info.get("icon", ""),
            cost=int(info.get("elixir") or get_card_elixir(name)),
            slot=slot,
        ))
    return infos


async def _build_user_deck_entries(battles: list, tag: str) -> list[DeckEntry]:
    await ensure_cards_loaded()
    winrates = calculate_deck_winrates(battles, normalize_tag(tag))
    decks: list[DeckEntry] = []
    for i, (_, data) in enumerate(winrates.items()):
        if i >= 12:
            break
        cards = data["cards"]
        deck_link = build_deck_share_link(cards) if len(cards) == 8 else None
        elixirs = [get_card_elixir(c) for c in cards]
        avg = round(sum(elixirs) / len(elixirs), 1) if elixirs else 0.0
        card_infos = []
        for c in cards:
            info = get_card_info(c)
            card_infos.append(DeckCardInfo(
                id=c.lower().replace(" ", "-"),
                name=c,
                icon=info.get("icon", "") if info else "",
                cost=get_card_elixir(c),
            ))
        decks.append(DeckEntry(
            id=i,
            name=_guess_deck_name(cards),
            cards=card_infos,
            winrate=data["winrate"],
            total_games=data["total"],
            avg_elixir=avg,
            type="mine",
            category="mine",
            deck_link=deck_link,
        ))
    return decks


def _build_stats_overview(
    stats,
    battles: list,
    player_tag: str,
    max_trophies: int = 0,
    *,
    chart_battles: list | None = None,
) -> StatsOverviewResponse:
    elixirs: list[float] = []
    durations: list[int] = []

    for battle in battles[:BATTLE_LOG_LIMIT]:
        team = battle.get("team", [{}])[0]
        opponent = battle.get("opponent", [{}])[0]
        deck = [c["name"] for c in team.get("cards", [])]
        if deck:
            elixirs.append(analyze_deck(deck).avg_elixir)
        durations.append(int(battle.get("gameDuration") or 180))

    winrate_by_day = build_winrate_by_day(chart_battles if chart_battles is not None else battles)
    last_results = build_last_results(battles)

    most_used = build_most_used_cards(battles, player_tag, limit=6) if player_tag else []
    archetypes = [
        {"name": "Игры", "value": stats.total},
        {"name": "Победы", "value": stats.wins},
        {"name": "Поражения", "value": stats.losses},
    ]

    return StatsOverviewResponse(
        total_battles=stats.total,
        wins=stats.wins,
        losses=stats.losses,
        draws=0,
        winrate=stats.winrate,
        avg_elixir=round(sum(elixirs) / len(elixirs), 1) if elixirs else 0.0,
        max_trophies=max_trophies,
        avg_time=round(sum(durations) / len(durations), 0) if durations else 0.0,
        winrate_by_day=winrate_by_day,
        best_cards=[{"name": c, "count": n} for c, n in stats.top_cards],
        most_used_cards=most_used,
        archetypes=archetypes,
        last_results=last_results,
    )


@router.get("/decks", response_model=DeckListResponse)
async def list_decks(
    user: User = Depends(require_linked_player),
    type: str | None = Query(None, alias="type"),
    category: str | None = Query(None),
) -> DeckListResponse:
    filter_type = (type or category or "meta").lower()
    decks: list[DeckEntry] = []
    meta_updated_at: str | None = None
    meta_source: str | None = None

    if filter_type in ("all", "meta"):
        meta, meta_updated_at, meta_source = await _build_meta_deck_entries()
        decks.extend(meta)

    if filter_type in ("all", "mine"):
        battles = await _get_battles(user)
        user_decks = await _build_user_deck_entries(battles, user.player_tag or "")
        decks.extend(user_decks)

    return DeckListResponse(
        decks=decks,
        meta_updated_at=meta_updated_at,
        meta_source=meta_source,
    )


@router.get("/decks/mine/stats", response_model=MineDeckStatsResponse)
async def get_mine_deck_stats(
    deck: str = Query(..., description="8 card names joined by |"),
    user: User = Depends(require_linked_player),
) -> MineDeckStatsResponse:
    cards = [c.strip() for c in deck.split("|") if c.strip()]
    battles = await _get_battles(user)
    data = build_mine_deck_stats(battles, user.player_tag or "", cards)
    if data.get("error"):
        raise HTTPException(status_code=400, detail=data["error"])

    card_infos = await _cards_to_deck_infos(data["cards"])
    return MineDeckStatsResponse(
        name=data["name"],
        cards=card_infos,
        wins=data["wins"],
        losses=data["losses"],
        total_games=data["total_games"],
        winrate=data["winrate"],
        avg_elixir=data["avg_elixir"],
        win_conditions=data["win_conditions"],
        strong_against=[DeckCardMatchup(**item) for item in data["strong_against"]],
        weak_against=[DeckCardMatchup(**item) for item in data["weak_against"]],
        improvements=[DeckImprovementSuggestion(**item) for item in data["improvements"]],
        balanced=data["balanced"],
        sample_note=data["sample_note"],
    )


@router.post("/decks/mine/stats", response_model=MineDeckStatsResponse)
async def post_mine_deck_stats(
    body: MineDeckStatsRequest,
    user: User = Depends(require_linked_player),
) -> MineDeckStatsResponse:
    deck = "|".join(sorted(body.cards))
    return await get_mine_deck_stats(deck=deck, user=user)


@router.get("/decks/arena", response_model=ArenaDecksResponse)
async def list_arena_decks(
    user: User = Depends(require_linked_player),
) -> ArenaDecksResponse:
    battles = await _get_battles(user)
    trophies = user.trophies or 0
    arena_name: str | None = None

    if user.player_tag and trophies <= 0:
        client = ClashRoyaleClient()
        try:
            player = await client.get_player(user.player_tag)
            arena = player.get("arena") or {}
            arena_name = arena.get("name")
            trophies = int(player.get("trophies") or trophies)
        except ClashRoyaleAPIError:
            pass
        finally:
            await client.close()

    data = await get_arena_popular_decks(
        battles,
        user.player_tag or "",
        trophies,
        user.arena_id,
        arena_name=arena_name,
    )
    decks = [
        DeckEntry(
            id=d["id"],
            name=d["name"],
            cards=[DeckCardInfo(**c) for c in d["cards"]],
            winrate=d.get("winrate", 0.0),
            total_games=d.get("total_games", 0),
            avg_elixir=d.get("avg_elixir", 0.0),
            type="arena",
            category=d.get("category", "arena"),
            deck_link=d.get("deck_link"),
            description=d.get("description", ""),
        )
        for d in data["decks"]
    ]
    return ArenaDecksResponse(
        arena_name=data["arena_name"],
        arena_id=data.get("arena_id"),
        trophies=data.get("trophies", 0),
        decks=decks,
        source=data.get("source", "curated"),
        updated_at=data.get("updated_at"),
    )


@router.post("/decks/compare", response_model=DeckCompareResponse)
async def compare_user_deck(
    body: DeckCompareRequest,
    user: User = Depends(require_linked_player),
) -> DeckCompareResponse:
    ref_cards = [c.strip() for c in body.reference_cards if c.strip()]
    if len(ref_cards) != 8:
        raise HTTPException(status_code=400, detail="Нужно ровно 8 карт для сравнения")

    battles = await _get_battles(user)
    user_cards = _user_current_deck(battles, user.player_tag or "")
    if len(user_cards) != 8:
        raise HTTPException(
            status_code=404,
            detail="Не найдена ваша текущая колода в последних боях",
        )

    result = compare_decks(user_cards, ref_cards)
    from bot.services.meta_analyzer import _guess_deck_name

    return DeckCompareResponse(
        reference_name=_guess_deck_name(ref_cards),
        user_deck=await _cards_to_deck_infos(user_cards),
        reference_deck=await _cards_to_deck_infos(ref_cards),
        user_better=result["user_better"],
        user_worse=result["user_worse"],
        reference_better=result["reference_better"],
        reference_worse=result["reference_worse"],
        user_card_notes=result["user_card_notes"],
        reference_card_notes=result["reference_card_notes"],
        matchup_score=result["matchup_score"],
        opponent_matchup_score=result["opponent_matchup_score"],
    )


@router.get("/decks/top-players", response_model=TopPlayersResponse)
async def list_top_players(
    user: User = Depends(require_linked_player),
    limit: int = Query(10, ge=5, le=20),
    refresh: bool = Query(False),
) -> TopPlayersResponse:
    del user
    cache = await get_top_players(limit=limit, force=refresh)
    players = [
        TopPlayerEntry(
            rank=p["rank"],
            player_tag=p["player_tag"],
            player_name=p["player_name"],
            trophies=p.get("trophies", 0),
            clan_name=p.get("clan_name", ""),
            winrate=p.get("winrate", 0.0),
            total_games=p.get("total_games", 0),
            avg_elixir=p.get("avg_elixir", 0.0),
            cards=[DeckCardInfo(**c) for c in p.get("cards", [])],
            deck_link=p.get("deck_link"),
        )
        for p in cache.players
    ]
    updated = cache.updated_at.isoformat() if cache.updated_at else None
    return TopPlayersResponse(players=players, updated_at=updated)


@router.get("/decks/random", response_model=RandomDeckResponse)
async def random_deck(
    user: User = Depends(require_linked_player),
    rofl: bool = Query(False),
    exclude_key: str | None = Query(None, max_length=64),
) -> RandomDeckResponse:
    del user
    try:
        data = await generate_random_deck(rofl=rofl, exclude_key=exclude_key)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    card_infos = [
        DeckCardInfo(
            id=c["name"].lower().replace(" ", "-"),
            name=c["name"],
            icon=c.get("icon", ""),
            cost=c.get("cost", 0),
        )
        for c in data["card_infos"]
    ]
    return RandomDeckResponse(
        cards=data["cards"],
        card_infos=card_infos,
        avg_elixir=data["avg_elixir"],
        deck_link=data.get("deck_link"),
        rofl=data.get("rofl", False),
        rofl_name=data.get("rofl_name"),
        rofl_tagline=data.get("rofl_tagline"),
        rofl_key=data.get("rofl_key"),
    )


@router.get("/insights", response_model=InsightsResponse)
async def battle_insights(user: User = Depends(require_subscription)) -> InsightsResponse:
    battles = await _get_battles(user)
    if not battles:
        raise HTTPException(status_code=404, detail="Нет боёв для анализа")

    report = build_insights_report(battles, user.player_tag or "", limit=7, losses_only=True)
    return InsightsResponse(**report)


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
        raise HTTPException(status_code=404, detail="Соперник не найден")

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
        if normalize_tag(team.get("tag") or "") == tag:
            current_deck = [c["name"] for c in team.get("cards", [])]
            break

    if not current_deck:
        raise HTTPException(status_code=404, detail="Колода не найдена в последних боях")

    result = customize_deck_for_arena(current_deck, user.arena_id, preferred, user.trophies)
    await ensure_cards_loaded()
    return CustomizeResponse(
        original=result["original"],
        customized=result["customized"],
        issues=result["issues"],
        avg_elixir=result["avg_elixir"],
        deck_link=build_deck_share_link(result["customized"]),
    )


@router.get("/synergy", response_model=SynergyResponse)
async def synergy_deck(user: User = Depends(require_subscription)) -> SynergyResponse:
    battles = await _get_battles(user)
    tag = normalize_tag(user.player_tag)
    top_cards = get_most_played_cards(battles, tag, top_n=3)
    core = [c for c, _ in top_cards]

    if not core:
        raise HTTPException(status_code=404, detail="Недостаточно данных по картам")

    result = build_synergy_deck(core, user.arena_id)
    await ensure_cards_loaded()
    return SynergyResponse(
        core=core,
        deck=result["deck"],
        synergies=result["synergies"],
        avg_elixir=result["avg_elixir"],
        deck_link=build_deck_share_link(result["deck"]),
    )


@router.get("/stats", response_model=StatsOverviewResponse)
async def extended_stats(user: User = Depends(require_subscription)) -> StatsOverviewResponse:
    battles = await _get_battles(user)
    if battles is None:
        raise HTTPException(status_code=502, detail="Не удалось загрузить бои")
    stats = await get_cached_stats(user.player_tag)
    if stats is None and battles:
        stats = _stats_from_battles(battles, user.player_tag or "")
    if stats is None or stats.total == 0:
        raise HTTPException(
            status_code=404,
            detail="Нет данных о боях. Сыграйте несколько рейтинговых боёв и обновите страницу.",
        )

    max_trophies = user.trophies or 0
    chart_battles = await get_battles_for_winrate_chart(user.player_tag or "", days=14)

    return _build_stats_overview(
        stats,
        battles,
        user.player_tag or "",
        max_trophies,
        chart_battles=chart_battles or battles,
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
            deck_result = customize_deck_for_arena(current_deck, user.arena_id, preferred, user.trophies)
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

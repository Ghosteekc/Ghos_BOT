import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from bot.api.deps import get_current_user, get_db, get_subscription_info, require_linked_player
from bot.api.schemas import HomeResponse, PlayerCollectionResponse, ProfileResponse, StatsOverviewResponse, SubscriptionInfo
from bot.models.database import User
from bot.api.routes.decks import _build_stats_overview, _stats_from_battles
from bot.api.routes.battles import _build_battle_summary
from bot.services.battle_day_stats import compute_daily_trophy_change
from bot.services.battle_cache_reader import get_battles_for_winrate_chart
from bot.services.battle_service import BATTLE_LOG_LIMIT, get_cached_stats, load_and_persist, load_pvp_battles
from bot.services.player_collection import build_player_collection, build_collection_stats_from_player
from bot.services.clash_api import ClashRoyaleAPIError, ClashRoyaleClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["profile"])


def _player_avatar_url(player: dict) -> tuple[str | None, str | None]:
    """Favorite card icon as player avatar; fallback to clan badge."""
    fav = player.get("currentFavouriteCard") or {}
    fav_icon: str | None = None
    if isinstance(fav, dict):
        icons = fav.get("iconUrls") or {}
        fav_icon = icons.get("medium") or icons.get("evolutionMedium") or icons.get("small")

    clan = player.get("clan") or {}
    badge_icon: str | None = None
    if isinstance(clan, dict):
        badges = clan.get("badgeUrls") or {}
        badge_icon = badges.get("medium") or badges.get("large")

    return fav_icon or badge_icon, fav_icon


def _profile_from_player(
    user: User,
    player: dict,
    sub_info: dict,
    winrate: float | None,
    last_rating_change: int | None = None,
    daily_trophy_change: int | None = None,
) -> ProfileResponse:
    arena = player.get("arena", {})
    arena_id = arena.get("id")
    arena_icon = (
        f"https://royaleapi.github.io/cr-api-assets/arenas/small/{arena_id}.png"
        if arena_id
        else None
    )
    fav = player.get("currentFavouriteCard") or {}
    clan = player.get("clan") or {}
    fav_name = fav.get("name") if isinstance(fav, dict) else None
    avatar_url, favorite_card_icon = _player_avatar_url(player)
    collection_stats = build_collection_stats_from_player(player)

    return ProfileResponse(
        player_tag=user.player_tag,
        player_name=player.get("name"),
        trophies=player.get("trophies", 0),
        exp_level=player.get("expLevel"),
        arena_name=arena.get("name"),
        arena_icon=arena_icon,
        avatar_url=avatar_url,
        favorite_card=fav_name,
        favorite_card_icon=favorite_card_icon,
        winrate=winrate,
        max_trophies=player.get("bestTrophies") or player.get("trophies", 0),
        clan_name=clan.get("name") if isinstance(clan, dict) else None,
        last_rating_change=last_rating_change,
        daily_trophy_change=daily_trophy_change,
        total_wins=player.get("wins"),
        three_crown_wins=player.get("threeCrownWins"),
        collection_level=collection_stats["collection_level"],
        cards_by_level=collection_stats["cards_by_level"],
        subscription=SubscriptionInfo(**sub_info),
    )


@router.get("/me", response_model=ProfileResponse)
async def get_profile(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    sub_info = await get_subscription_info(user, session)
    cached = await get_cached_stats(user.player_tag) if user.player_tag else None
    winrate = cached.winrate if cached else None

    if not user.player_tag:
        return ProfileResponse(
            player_tag=None,
            player_name=user.player_name,
            trophies=None,
            exp_level=None,
            arena_name=None,
            subscription=SubscriptionInfo(**sub_info),
        )

    client = ClashRoyaleClient()
    last_rating_change: int | None = None
    daily_trophy_change: int | None = None
    try:
        player = await client.get_player(user.player_tag)
        daily_trophy_change = await _daily_trophy_for_user(user)
    except ClashRoyaleAPIError as e:
        logger.warning(f"Failed to fetch live profile for {user.player_tag}: {e}")
        player = None
        daily_trophy_change = await _daily_trophy_for_user(user)
    finally:
        await client.close()

    if player:
        return _profile_from_player(
            user, player, sub_info, winrate, last_rating_change, daily_trophy_change,
        )

    arena_name = None
    if user.arena_id:
        arena_names = {
            0: "Тренировочный лагерь", 1: "Гоблинская арена", 2: "Арена песков",
            3: "Драконья арена", 4: "Нижняя пик", 5: "Арена рабочих",
            6: "Сахарная фотография", 7: "Скальная арена", 8: "Арена изобилия",
            9: "Высший пик", 10: "Арена электричества", 11: "Электро-арена",
            12: "Механическая арена", 13: "Запретная арена", 14: "Трофейная арена",
        }
        arena_name = arena_names.get(user.arena_id, f"Арена {user.arena_id}")

    return ProfileResponse(
        player_tag=user.player_tag,
        player_name=user.player_name,
        trophies=user.trophies,
        exp_level=None,
        arena_name=arena_name,
        winrate=winrate,
        daily_trophy_change=daily_trophy_change,
        subscription=SubscriptionInfo(**sub_info),
    )


async def _daily_trophy_for_user(user: User) -> int | None:
    if not user.player_tag:
        return None
    battles = await load_pvp_battles(user.player_tag)
    if not battles:
        return None
    return compute_daily_trophy_change(battles)


@router.get("/profile/collection", response_model=PlayerCollectionResponse)
async def get_player_collection(
    user: User = Depends(require_linked_player),
) -> PlayerCollectionResponse:
    client = ClashRoyaleClient()
    try:
        player = await client.get_player(user.player_tag or "")
    except ClashRoyaleAPIError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    finally:
        await client.close()

    data = await build_player_collection(player)
    return PlayerCollectionResponse(**data)


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "stats_days": 14, "ladder_only_daily_trophies": True}


@router.get("/home", response_model=HomeResponse)
async def home_dashboard(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> HomeResponse:
    """One round-trip for the home screen (profile + battles + stats)."""
    profile = await get_profile(user=user, session=session)

    battles: list = []
    stats: StatsOverviewResponse | None = None

    if user.player_tag:
        loaded = await load_and_persist(user)
        if loaded:
            battles = loaded
            cached = await get_cached_stats(user.player_tag)
            if cached is None:
                cached = _stats_from_battles(loaded, user.player_tag)
            if cached and cached.total > 0:
                chart_battles = await get_battles_for_winrate_chart(user.player_tag, days=14)
                stats = _build_stats_overview(
                    cached,
                    loaded,
                    user.player_tag or "",
                    user.trophies or profile.max_trophies or 0,
                    chart_battles=chart_battles or loaded,
                )

    summaries = [_build_battle_summary(i, b) for i, b in enumerate(battles[:BATTLE_LOG_LIMIT])]
    return HomeResponse(profile=profile, battles=summaries, stats=stats)

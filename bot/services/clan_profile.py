"""Grounded, cached clan data for the WebApp profile surface."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Literal

from bot.services.clash_api import ClashRoyaleAPIError, ClashRoyaleClient, normalize_tag

ClanMemberSort = Literal["rank", "activity_desc", "activity_asc"]

_CACHE_TTL_SECONDS = 90.0
_cache: dict[str, tuple[float, "ClanSnapshot"]] = {}
_inflight: dict[str, asyncio.Task["ClanSnapshot"]] = {}
_lock = asyncio.Lock()


@dataclass(frozen=True)
class ClanMember:
    tag: str
    name: str
    role: str
    trophies: int
    donations: int
    donations_received: int
    clan_rank: int | None
    previous_clan_rank: int | None


@dataclass(frozen=True)
class ClanSnapshot:
    tag: str
    name: str
    description: str | None
    members: int | None
    clan_score: int | None
    clan_war_trophies: int | None
    required_trophies: int | None
    donations_per_week: int | None
    member_list: tuple[ClanMember, ...]


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _build_snapshot(clan: dict, raw_members: list[dict]) -> ClanSnapshot:
    """Map only documented clan/member facts into the small WebApp DTO."""
    members = tuple(
        ClanMember(
            tag=str(member.get("tag") or ""),
            name=str(member.get("name") or "Игрок"),
            role=str(member.get("role") or "member"),
            trophies=_int(member.get("trophies")),
            donations=_int(member.get("donations")),
            donations_received=_int(member.get("donationsReceived")),
            clan_rank=_optional_int(member.get("clanRank")),
            previous_clan_rank=_optional_int(member.get("previousClanRank")),
        )
        for member in raw_members
    )
    return ClanSnapshot(
        tag=str(clan.get("tag") or ""),
        name=str(clan.get("name") or "Клан"),
        description=str(clan["description"]) if clan.get("description") else None,
        members=_optional_int(clan.get("members")),
        clan_score=_optional_int(clan.get("clanScore")),
        clan_war_trophies=_optional_int(clan.get("clanWarTrophies")),
        required_trophies=_optional_int(clan.get("requiredTrophies")),
        donations_per_week=_optional_int(clan.get("donationsPerWeek")),
        member_list=members,
    )


async def _fetch_clan_snapshot(clan_tag: str) -> ClanSnapshot:
    client = ClashRoyaleClient()
    try:
        clan, members = await asyncio.gather(
            client.get_clan(clan_tag),
            client.get_clan_members(clan_tag),
        )
    finally:
        await client.close()
    return _build_snapshot(clan, members)


async def _get_cached_snapshot(clan_tag: str) -> ClanSnapshot:
    tag = normalize_tag(clan_tag)
    now = time.monotonic()
    cached = _cache.get(tag)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    async with _lock:
        cached = _cache.get(tag)
        if cached and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]
        task = _inflight.get(tag)
        if task is None or task.done():
            task = asyncio.create_task(_fetch_clan_snapshot(tag))
            _inflight[tag] = task

    try:
        snapshot = await asyncio.shield(task)
    finally:
        async with _lock:
            if _inflight.get(tag) is task and task.done():
                _inflight.pop(tag, None)

    _cache[tag] = (time.monotonic(), snapshot)
    return snapshot


def sort_members(members: tuple[ClanMember, ...], sort: ClanMemberSort) -> list[ClanMember]:
    """Use explicit weekly-donation activity and stable tie-breakers only."""
    if sort == "activity_desc":
        return sorted(members, key=lambda member: (-member.donations, -member.trophies, member.tag))
    if sort == "activity_asc":
        return sorted(members, key=lambda member: (member.donations, -member.trophies, member.tag))
    return sorted(
        members,
        key=lambda member: (
            member.clan_rank is None,
            member.clan_rank if member.clan_rank is not None else 0,
            -member.trophies,
            member.tag,
        ),
    )


async def get_player_clan_snapshot(player_tag: str) -> ClanSnapshot | None:
    """Resolve the current clan from the live player profile before loading it."""
    client = ClashRoyaleClient()
    try:
        player = await client.get_player(player_tag)
    finally:
        await client.close()

    clan = player.get("clan")
    clan_tag = clan.get("tag") if isinstance(clan, dict) else None
    if not clan_tag:
        return None
    try:
        return await _get_cached_snapshot(str(clan_tag))
    except ClashRoyaleAPIError as exc:
        # The player profile itself was live and has already established the clan tag.
        # A subsequent clan 404 means that the clan changed/disappeared between requests.
        if exc.status == 404:
            return None
        raise

"""Focused tests for the grounded clan profile aggregation."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from bot.api.routes import profile as profile_route
from bot.services import clan_profile


def _member(
    tag: str,
    *,
    donations: int = 0,
    trophies: int = 0,
    rank: int | None = None,
) -> dict:
    return {
        "tag": tag,
        "name": tag,
        "role": "member",
        "trophies": trophies,
        "donations": donations,
        "donationsReceived": 4,
        "clanRank": rank,
        "previousClanRank": rank,
    }


def _snapshot(member_count: int = 3) -> clan_profile.ClanSnapshot:
    return clan_profile._build_snapshot(
        {
            "tag": "#CLAN",
            "name": "Ghosteek",
            "description": "Test clan",
            "members": member_count,
            "clanScore": 1234,
            "clanWarTrophies": 567,
            "requiredTrophies": 5000,
            "donationsPerWeek": 250,
        },
        [
            _member("#B", donations=10, trophies=7000, rank=2),
            _member("#A", donations=10, trophies=7000, rank=1),
            _member("#C", donations=0, trophies=8000, rank=3),
        ][:member_count],
    )


def test_snapshot_keeps_only_grounded_clan_and_member_facts() -> None:
    snapshot = _snapshot()

    assert snapshot.name == "Ghosteek"
    assert snapshot.clan_score == 1234
    assert snapshot.donations_per_week == 250
    assert snapshot.member_list[0].donations_received == 4
    assert snapshot.member_list[0].clan_rank == 2


def test_activity_sort_is_deterministic_and_uses_weekly_donations_only() -> None:
    members = _snapshot().member_list

    assert [member.tag for member in clan_profile.sort_members(members, "activity_desc")] == ["#A", "#B", "#C"]
    assert [member.tag for member in clan_profile.sort_members(members, "activity_asc")] == ["#C", "#A", "#B"]
    assert [member.tag for member in clan_profile.sort_members(members, "rank")] == ["#A", "#B", "#C"]


def test_fifty_members_are_preserved() -> None:
    raw_members = [_member(f"#{index}", donations=index, trophies=9000 - index, rank=index + 1) for index in range(50)]
    snapshot = clan_profile._build_snapshot({"tag": "#CLAN", "name": "Ghosteek", "members": 50}, raw_members)

    assert len(snapshot.member_list) == 50
    assert len(clan_profile.sort_members(snapshot.member_list, "rank")) == 50


async def _run_cache_coalescing() -> None:
    original_fetch = clan_profile._fetch_clan_snapshot
    clan_profile._cache.clear()
    clan_profile._inflight.clear()
    calls = 0

    async def fake_fetch(_tag: str) -> clan_profile.ClanSnapshot:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return _snapshot()

    clan_profile._fetch_clan_snapshot = fake_fetch
    try:
        first, second = await asyncio.gather(
            clan_profile._get_cached_snapshot("#CLAN"),
            clan_profile._get_cached_snapshot("#CLAN"),
        )
        assert first == second
        assert calls == 1
        await clan_profile._get_cached_snapshot("#CLAN")
        assert calls == 1
    finally:
        clan_profile._fetch_clan_snapshot = original_fetch
        clan_profile._cache.clear()
        clan_profile._inflight.clear()


def test_clan_snapshot_cache_coalesces_requests() -> None:
    asyncio.run(_run_cache_coalescing())


async def _run_no_n_plus_one_check() -> None:
    original_client = clan_profile.ClashRoyaleClient
    clan_profile._cache.clear()
    clan_profile._inflight.clear()
    calls: list[str] = []

    class FakeClient:
        async def get_player(self, _tag: str) -> dict:
            calls.append("player")
            return {"clan": {"tag": "#CLAN"}}

        async def get_clan(self, _tag: str) -> dict:
            calls.append("clan")
            return {"tag": "#CLAN", "name": "Ghosteek", "members": 50}

        async def get_clan_members(self, _tag: str) -> list[dict]:
            calls.append("members")
            return [_member(f"#{index}") for index in range(50)]

        async def close(self) -> None:
            return None

    clan_profile.ClashRoyaleClient = FakeClient
    try:
        snapshot = await clan_profile.get_player_clan_snapshot("#PLAYER")
        assert snapshot is not None and len(snapshot.member_list) == 50
        assert calls == ["player", "clan", "members"]
    finally:
        clan_profile.ClashRoyaleClient = original_client
        clan_profile._cache.clear()
        clan_profile._inflight.clear()


def test_clan_loading_does_not_request_each_member() -> None:
    asyncio.run(_run_no_n_plus_one_check())


async def _run_route_states() -> None:
    original_snapshot = profile_route.get_player_clan_snapshot

    async def no_clan(_tag: str) -> None:
        return None

    profile_route.get_player_clan_snapshot = no_clan
    try:
        empty = await profile_route.get_my_clan(user=SimpleNamespace(player_tag="#PLAYER"))
        assert empty.status == "no_clan"
        assert empty.members == []
    finally:
        profile_route.get_player_clan_snapshot = original_snapshot

    async def with_clan(_tag: str) -> clan_profile.ClanSnapshot:
        return _snapshot()

    profile_route.get_player_clan_snapshot = with_clan
    try:
        result = await profile_route.get_my_clan(
            sort="activity_desc",
            user=SimpleNamespace(player_tag="#PLAYER"),
        )
        assert result.status == "available"
        assert result.clan is not None and result.clan.name == "Ghosteek"
        assert [member.tag for member in result.members] == ["#A", "#B", "#C"]
        assert result.activity_basis == "Донаты за текущую неделю"
    finally:
        profile_route.get_player_clan_snapshot = original_snapshot


def test_clan_route_returns_empty_or_sorted_clan() -> None:
    asyncio.run(_run_route_states())

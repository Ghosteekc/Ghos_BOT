"""Meta collector: deck hash, ranking, trend, observation parsing."""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bot.services.meta_observation import observation_from_battle
from bot.services.meta_query import _snapshot_is_stale
from bot.services.meta_stats import (
    battle_result,
    classify_battle_mode,
    deck_hash_from_names,
    observation_dedupe_key,
    ranking_score,
    trend_from_counts,
    trend_from_history_values,
    wilson_lower_bound,
)


def test_deck_hash_ignores_order():
    a = ["Hog Rider", "Musketeer", "Ice Golem", "Ice Spirit", "Skeletons", "Cannon", "Fireball", "The Log"]
    b = list(reversed(a))
    assert deck_hash_from_names(a) == deck_hash_from_names(b)
    assert deck_hash_from_names(a[:7]) == ""


def test_dedupe_key_is_stable_per_player_battle():
    key = observation_dedupe_key("#AAA", "20260818T120000.000Z", "league")
    assert key == observation_dedupe_key("#AAA", "20260818T120000.000Z", "league")
    assert key != observation_dedupe_key("#BBB", "20260818T120000.000Z", "league")


def test_wilson_small_sample_below_raw_winrate():
    raw = 8 / 10
    lb = wilson_lower_bound(8, 10)
    assert 0 < lb < raw


def test_ranking_prefers_volume_over_tiny_hot_streak():
    now = datetime(2026, 8, 18, tzinfo=timezone.utc)
    last = now - timedelta(days=1)
    hot = ranking_score(wins=8, games=10, unique_players=2, last_seen=last, max_games=1000, now=now)
    solid = ranking_score(wins=600, games=1000, unique_players=40, last_seen=last, max_games=1000, now=now)
    assert solid > hot


def test_ranking_same_winrate_prefers_more_games():
    now = datetime(2026, 8, 18, tzinfo=timezone.utc)
    last = now - timedelta(days=1)
    few = ranking_score(wins=80, games=100, unique_players=8, last_seen=last, max_games=500, now=now)
    many = ranking_score(wins=400, games=500, unique_players=8, last_seen=last, max_games=500, now=now)
    assert many > few


def test_trend_up_down_stable():
    assert trend_from_counts(24, 10)[0] == "up"
    assert trend_from_counts(10, 24)[0] == "down"
    assert trend_from_counts(11, 10)[0] == "stable"
    assert trend_from_counts(10, 0)[0] == "stable"


def test_trend_from_history_matches_sparkline_tail():
    assert trend_from_history_values([0, 0, 0, 0, 0, 0, 0, 2, 50, 4])[0] == "down"
    assert trend_from_history_values([1, 2, 4, 5, 6, 7, 8])[0] == "up"
    assert trend_from_history_values([5, 5, 5, 5, 5])[0] == "stable"


def test_classify_trophy_change_ladder():
    assert classify_battle_mode({
        "type": "PvP",
        "gameMode": {"name": "UnknownMode"},
        "team": [{"trophyChange": 30, "startingTrophies": 11000}],
    }) == "trophies"


def test_classify_modes():
    assert classify_battle_mode({"type": "pathOfLegend", "team": [{}]}) == "league"
    assert classify_battle_mode({
        "type": "PvP",
        "gameMode": {"name": "Ranked1v1_NewArena"},
        "team": [{}],
    }) == "league"
    assert classify_battle_mode({
        "type": "PvP",
        "gameMode": {"name": "Ladder"},
        "team": [{"startingTrophies": 11000}],
    }) == "trophies"
    assert classify_battle_mode({"type": "clanMate", "team": [{}]}) is None


def test_observation_skips_low_trophy_pvp():
    battle = {
        "type": "PvP",
        "battleTime": "20260818T120000.000Z",
        "team": [{
            "tag": "#AAA",
            "crowns": 1,
            "startingTrophies": 8000,
            "cards": [{"name": f"Card{i}"} for i in range(8)],
        }],
        "opponent": [{"tag": "#BBB", "crowns": 0}],
    }
    assert observation_from_battle("#AAA", battle, trophy_min=10000) is None


def test_observation_accepts_path_of_legend():
    names = ["Hog Rider", "Musketeer", "Ice Golem", "Ice Spirit", "Skeletons", "Cannon", "Fireball", "The Log"]
    battle = {
        "type": "pathOfLegend",
        "battleTime": "20260818T120000.000Z",
        "team": [{
            "tag": "#AAA",
            "crowns": 3,
            "startingTrophies": 0,
            "cards": [{"name": n} for n in names],
        }],
        "opponent": [{"tag": "#BBB", "crowns": 0}],
    }
    row = observation_from_battle("#AAA", battle, trophy_min=10000)
    assert row is not None
    assert row["mode"] == "league"
    assert row["result"] == "win"
    assert row["deck_hash"] == deck_hash_from_names(names)
    assert row["dedupe_key"] == observation_dedupe_key("#AAA", "20260818T120000.000Z", "league")


def test_observation_accepts_high_trophy_pvp():
    names = ["Hog Rider", "Musketeer", "Ice Golem", "Ice Spirit", "Skeletons", "Cannon", "Fireball", "The Log"]
    battle = {
        "type": "PvP",
        "gameMode": {"name": "Ladder"},
        "battleTime": "20260818T120000.000Z",
        "team": [{
            "tag": "#AAA",
            "crowns": 1,
            "startingTrophies": 12000,
            "cards": [{"name": n} for n in names],
        }],
        "opponent": [{"tag": "#BBB", "crowns": 0}],
    }
    row = observation_from_battle("#AAA", battle, trophy_min=10000)
    assert row is not None
    assert row["mode"] == "trophies"
    assert row["result"] == "win"


def test_ranked_pvp_is_not_trophies():
    names = ["Hog Rider", "Musketeer", "Ice Golem", "Ice Spirit", "Skeletons", "Cannon", "Fireball", "The Log"]
    battle = {
        "type": "PvP",
        "gameMode": {"name": "Ranked1v1_NewArena"},
        "battleTime": "20260818T120000.000Z",
        "team": [{
            "tag": "#AAA",
            "crowns": 1,
            "startingTrophies": 14000,
            "cards": [{"name": n} for n in names],
        }],
        "opponent": [{"tag": "#BBB", "crowns": 0}],
    }
    row = observation_from_battle("#AAA", battle, trophy_min=10000)
    assert row is not None
    assert row["mode"] == "league"


def test_battle_result_draw():
    assert battle_result({"crowns": 1}, {"crowns": 1}) == "draw"


def test_snapshot_staleness_uses_configured_refresh_window():
    now = datetime(2026, 8, 18, 12, tzinfo=timezone.utc)
    assert not _snapshot_is_stale(now - timedelta(hours=1), now=now)
    assert _snapshot_is_stale(now - timedelta(hours=7), now=now)


async def _run_trophy_aggregate_accumulation() -> None:
    """A later collection must retain, rather than replace, earlier Trophy Road games."""
    from bot.models.database import Base, MetaBattleObservation, MetaDeckAggregate
    from bot.services.meta_collector import rebuild_mode_aggregates

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    deck_hash = deck_hash_from_names([f"Card {index}" for index in range(8)])

    def observation(time: str, result: str) -> MetaBattleObservation:
        return MetaBattleObservation(
            dedupe_key=f"#PLAYER|{time}|trophies",
            player_tag="#PLAYER",
            opponent_tag="#OPPONENT",
            battle_time=time,
            mode="trophies",
            deck_hash=deck_hash,
            cards_csv="Card 0,Card 1,Card 2,Card 3,Card 4,Card 5,Card 6,Card 7",
            cards_json="[]",
            result=result,
            source="ghosteek_cache",
        )

    async with session_factory() as session:
        session.add_all([
            observation("20260818T120000.000Z", "win"),
            observation("20260818T130000.000Z", "loss"),
        ])
        await session.commit()
        await rebuild_mode_aggregates(session, "trophies")
        await session.commit()

        first = (
            await session.execute(
                select(MetaDeckAggregate).where(
                    MetaDeckAggregate.mode == "trophies",
                    MetaDeckAggregate.deck_hash == deck_hash,
                )
            )
        ).scalar_one()
        assert (first.total_games, first.wins, first.losses) == (2, 1, 1)

        session.add(observation("20260819T120000.000Z", "win"))
        await session.commit()
        await rebuild_mode_aggregates(session, "trophies")
        await session.commit()

        total = (
            await session.execute(
                select(MetaDeckAggregate).where(
                    MetaDeckAggregate.mode == "trophies",
                    MetaDeckAggregate.deck_hash == deck_hash,
                )
            )
        ).scalar_one()
        assert (total.total_games, total.wins, total.losses) == (3, 2, 1)

    await engine.dispose()


def test_trophy_aggregate_accumulates_across_collection_runs():
    asyncio.run(_run_trophy_aggregate_accumulation())

"""Low-impact cards must not flag splash counters vs swarm decks."""

from bot.services.battle_report import _relevant_user_cards, analyze_battle_enhanced
from bot.services.deck_analyzer import find_opponent_threats


def test_valkyrie_relevant_vs_skeleton_spam_deck():
    user = [
        "Executioner", "Fireball", "Guards", "Hog Rider",
        "Mighty Miner", "The Log", "Tornado", "Valkyrie",
    ]
    opp = [
        "Furnace", "Skeleton King", "Royal Recruits", "Goblin Gang",
        "Arrows", "Skeleton Barrel", "Goblin Hut", "Ice Spirit",
    ]
    relevant = _relevant_user_cards(user, opp, find_opponent_threats(opp))
    assert "Valkyrie" in relevant
    assert "Executioner" in relevant
    assert "The Log" in relevant

    analysis = analyze_battle_enhanced(
        {"name": "Me", "tag": "#ME", "crowns": 0, "cards": [{"name": n} for n in user]},
        {"name": "Opp", "tag": "#OP", "crowns": 1, "cards": [{"name": n} for n in opp]},
    )
    low = {c.name for c in analysis.low_impact_cards}
    assert "Valkyrie" not in low
    assert "Executioner" not in low


def test_opponent_tower_threats_prefer_win_condition_over_small_spell():
    """MK bait: Barrel + MK + Mini PEKKA — не Arrows как «угроза башням»."""
    user = [
        "Hog Rider", "Ice Golem", "Cannon", "Musketeer",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ]
    opp = [
        "Witch", "Mini P.E.K.K.A", "Mega Knight", "Dart Goblin",
        "Skeleton Barrel", "Arrows", "Bats", "Goblin Hut",
    ]
    analysis = analyze_battle_enhanced(
        {"name": "Me", "tag": "#ME", "crowns": 0, "cards": [{"name": n} for n in user]},
        {"name": "Opp", "tag": "#OP", "crowns": 1, "cards": [{"name": n} for n in opp]},
        duration=180,
    )
    key_names = [c.name for c in analysis.opponent_key_cards]
    assert "Arrows" not in key_names
    assert "Dart Goblin" not in key_names
    assert key_names == ["Skeleton Barrel", "Mega Knight", "Mini P.E.K.K.A"]
    assert set(find_opponent_threats(opp)) == {"Skeleton Barrel"}

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

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
    # Dart Goblin — чип, но ниже Barrel / MK / Mini PEKKA → не в топ-3.
    assert "Dart Goblin" not in key_names
    assert key_names == ["Skeleton Barrel", "Mega Knight", "Mini P.E.K.K.A"]
    assert set(find_opponent_threats(opp)) == {"Skeleton Barrel"}


def test_battle_report_shows_all_deck_specific_counters_for_each_threat():
    from bot.services.card_matchups import counters_in_deck
    from bot.services.card_names_ru import card_name_ru

    user = [
        "Tesla", "Valkyrie", "Bowler", "Graveyard",
        "Poison", "Barbarian Barrel", "Furnace", "Miner",
    ]
    opp = [
        "Cannon", "Skeleton King", "Skeleton Barrel", "Mother Witch",
        "Spear Goblins", "Inferno Tower", "Goblins", "X-Bow",
    ]
    assert "Barbarian Barrel" in counters_in_deck("Skeleton Barrel", user)[0]
    analysis = analyze_battle_enhanced(
        {"name": "Me", "tag": "#ME", "crowns": 1, "cards": [{"name": n} for n in user]},
        {"name": "Opp", "tag": "#OP", "crowns": 0, "cards": [{"name": n} for n in opp]},
    )
    assert "Barbarian Barrel" in counters_in_deck("Skeleton Barrel", user)[0]

    threat_label = card_name_ru("Skeleton Barrel")
    line = next(reason for reason in analysis.reasons if threat_label in reason)
    for card in (
        "Barbarian Barrel", "Valkyrie", "Poison", "Furnace", "Tesla", "Bowler"
    ):
        assert card_name_ru(card) in line
    assert "частичные:" in line


def test_princess_is_tower_threat_in_rg_cycle():
    """Princess чипит башни и bait'ит Log — должна быть в угрозах, Ice Golem нет."""
    user = [
        "Hog Rider", "Ice Golem", "Cannon", "Musketeer",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ]
    opp = [
        "Tesla", "Electro Spirit", "Royal Giant", "Bats",
        "Princess", "The Log", "Ice Golem", "Fire Spirit",
    ]
    analysis = analyze_battle_enhanced(
        {"name": "Me", "tag": "#ME", "crowns": 0, "cards": [{"name": n} for n in user]},
        {"name": "Opp", "tag": "#OP", "crowns": 1, "cards": [{"name": n} for n in opp]},
        duration=180,
    )
    key_names = [c.name for c in analysis.opponent_key_cards]
    assert key_names[0] == "Royal Giant"
    assert "Princess" in key_names
    assert "Ice Golem" not in key_names
    princess = next(c for c in analysis.opponent_key_cards if c.name == "Princess")
    assert "чип" in princess.note.lower() or "спелл" in princess.note.lower()


def test_golem_beatdown_threats_prefer_edrag_over_berserker():
    """Golem + E-Drag: электродракон — угроза башням, берсеркша — нет."""
    user = [
        "Hog Rider", "Ice Golem", "Cannon", "Musketeer",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ]
    opp = [
        "Electro Dragon",
        "Berserker",
        "Elite Barbarians",
        "Skeleton Dragons",
        "Tornado",
        "Elixir Collector",
        "Barbarian Barrel",
        "Golem",
    ]
    analysis = analyze_battle_enhanced(
        {"name": "Me", "tag": "#ME", "crowns": 0, "cards": [{"name": n} for n in user]},
        {"name": "Opp", "tag": "#OP", "crowns": 1, "cards": [{"name": n} for n in opp]},
        duration=180,
    )
    key_names = [c.name for c in analysis.opponent_key_cards]
    assert "Berserker" not in key_names
    assert "Electro Dragon" in key_names
    assert "Golem" in key_names
    assert "Elite Barbarians" in key_names
    assert key_names.index("Electro Dragon") < 3

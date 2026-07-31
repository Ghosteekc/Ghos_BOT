"""ElixirEfficiencyAnalyzer — только структура колоды."""

from bot.services.elixir_efficiency import ElixirEfficiencyAnalyzer


def _deck(names: list[str]) -> list[str]:
    assert len(names) == 8
    return names


def test_hog_cycle_is_fast_cycle():
    deck = _deck([
        "Hog Rider", "Ice Golem", "Musketeer", "Cannon",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ])
    r = ElixirEfficiencyAnalyzer.analyze(deck)
    assert r.elixir_profile == "Fast Cycle"
    assert r.average_cost <= 3.2
    assert r.effective_cycle <= 8
    assert any("Хог" in e for e in r.explanations)


def test_golem_is_heavy_beatdown():
    deck = _deck([
        "Golem", "Night Witch", "Baby Dragon", "Mega Minion",
        "Lumberjack", "Tornado", "Lightning", "Barbarian Barrel",
    ])
    r = ElixirEfficiencyAnalyzer.analyze(deck)
    assert r.elixir_profile == "Heavy Beatdown"
    assert r.double_elixir_power >= 45
    assert "Колода раскрывается после двойного эликсира." in r.explanations
    assert any("ошибка" in e.lower() or "темп" in e.lower() for e in r.explanations)


def test_log_bait_is_split_pressure():
    deck = _deck([
        "Goblin Barrel", "Princess", "Goblin Gang", "Dart Goblin",
        "Inferno Tower", "The Log", "Knight", "Ice Spirit",
    ])
    r = ElixirEfficiencyAnalyzer.analyze(deck)
    assert r.elixir_profile == "Split Pressure"
    assert any("сплит" in e.lower() or "бочка" in e.lower() for e in r.explanations)


def test_metrics_match_card_costs():
    deck = _deck([
        "Hog Rider", "Ice Golem", "Musketeer", "Cannon",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ])
    r = ElixirEfficiencyAnalyzer.analyze(deck)
    # 4+2+4+3+1+1+2+4 = 21 / 8 = 2.625
    assert r.average_cost == 2.62 or abs(r.average_cost - 2.62) < 0.02
    # 4 cheapest: 1+1+2+2 = 6
    assert r.effective_cycle == 6
    assert 0 <= r.cheap_rotation <= 100
    assert 0 <= r.punish_speed <= 100
    assert 0 <= r.recovery_speed <= 100


def test_no_battle_history_fields():
    """API отчёта не содержит полей боя — только состав."""
    deck = _deck([
        "Giant", "Witch", "Mini P.E.K.K.A", "Musketeer",
        "Fireball", "Zap", "Skeletons", "Cannon",
    ])
    r = ElixirEfficiencyAnalyzer.analyze(deck)
    data = r.to_dict()
    assert "won" not in data
    assert "duration" not in data
    assert "crowns" not in data
    assert data["elixir_profile"] in {
        "Fast Cycle", "Medium Cycle", "Heavy Control",
        "Heavy Beatdown", "Bridge Pressure", "Split Pressure",
    }


def test_explanations_require_structure():
    """Без тяжёлого танка нет фразы про дабл-эликсир."""
    deck = _deck([
        "Hog Rider", "Ice Golem", "Musketeer", "Cannon",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ])
    r = ElixirEfficiencyAnalyzer.analyze(deck)
    assert "Колода раскрывается после двойного эликсира." not in r.explanations

"""TacticalMatchupAnalyzer — только логически выводимые советы."""

from bot.services.tactical_matchup import TacticalMatchupAnalyzer


def _team(names: list[str]) -> list[str]:
    assert len(names) == 8
    return names


def test_fireball_hold_for_flying_machine():
    user = _team([
        "Hog Rider", "Ice Golem", "Musketeer", "Cannon",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ])
    opp = _team([
        "Royal Hogs", "Flying Machine", "Royal Recruits", "Zappies",
        "Heal Spirit", "The Log", "Barbarian Barrel", "Earthquake",
    ])
    report = TacticalMatchupAnalyzer.analyze(user, opp)
    joined = " ".join(report.critical_interactions + report.worst_mistakes)
    assert "Летучка" in joined
    assert "Не трать" in joined and "Фаербол" in joined


def test_no_fireball_hold_without_target():
    user = _team([
        "Hog Rider", "Ice Golem", "Musketeer", "Cannon",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ])
    opp = _team([
        "Royal Hogs", "Royal Recruits", "Heal Spirit", "Ice Spirit",
        "The Log", "Barbarian Barrel", "Earthquake", "Knight",
    ])
    report = TacticalMatchupAnalyzer.analyze(user, opp)
    joined = " ".join(report.critical_interactions + report.worst_mistakes)
    assert "Фаербол" not in joined
    assert "Fireball" not in joined


def test_executioner_tornado_vs_bait():
    user = _team([
        "Executioner", "Tornado", "Ice Wizard", "Rocket",
        "Ice Spirit", "Skeletons", "The Log", "Knight",
    ])
    opp = _team([
        "Goblin Barrel", "Princess", "Goblin Gang", "Dart Goblin",
        "Inferno Tower", "The Log", "Knight", "Ice Spirit",
    ])
    report = TacticalMatchupAnalyzer.analyze(user, opp)
    joined = " ".join(report.critical_interactions + report.mid_game)
    assert "Палач" in joined and "Торнадо" in joined
    assert "ключевая защита" in joined


def test_hog_after_building_spent():
    user = _team([
        "Hog Rider", "Ice Golem", "Musketeer", "Fireball",
        "Ice Spirit", "Skeletons", "The Log", "Cannon",
    ])
    opp = _team([
        "Giant", "Witch", "Mega Minion", "Tesla",
        "Zap", "Bats", "Mini P.E.K.K.A", "Poison",
    ])
    report = TacticalMatchupAnalyzer.analyze(user, opp)
    joined = " ".join(report.best_openings + report.early_game + report.worst_mistakes)
    assert "Хог" in joined
    assert "Тесла" in joined
    assert "после траты" in joined


def test_poison_hold_vs_graveyard():
    user = _team([
        "Giant", "Night Witch", "Baby Dragon", "Mega Minion",
        "Tornado", "Poison", "Barbarian Barrel", "Lumberjack",
    ])
    opp = _team([
        "Graveyard", "Ice Wizard", "Baby Dragon", "Tornado",
        "Freeze", "Knight", "Bomb Tower", "Skeletons",
    ])
    report = TacticalMatchupAnalyzer.analyze(user, opp)
    joined = " ".join(
        report.critical_interactions + report.mid_game + report.late_game + report.worst_mistakes
    )
    assert "Кладбище" in joined
    assert "Яд" in joined


def test_no_template_advice_without_premise():
    """Без пересечений ролей/контр — нет выдуманных советов про Fireball/GY."""
    user = _team([
        "Knight", "Archers", "Bomber", "Giant",
        "Arrows", "Zap", "Minions", "Cannon",
    ])
    opp = _team([
        "Knight", "Archers", "Bomber", "Giant",
        "Arrows", "Zap", "Minions", "Cannon",
    ])
    report = TacticalMatchupAnalyzer.analyze(user, opp)
    joined = " ".join(
        report.early_game
        + report.mid_game
        + report.late_game
        + report.critical_interactions
        + report.best_openings
        + report.worst_mistakes
        + report.pressure_points
    )
    assert "Фаербол" not in joined
    assert "Кладбище" not in joined
    assert "Летучка" not in joined

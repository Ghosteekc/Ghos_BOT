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
        "Giant", "Flying Machine", "Royal Recruits", "Zappies",
        "Heal Spirit", "The Log", "Barbarian Barrel", "Earthquake",
    ])
    report = TacticalMatchupAnalyzer.analyze(user, opp)
    joined = " ".join(report.critical_interactions + report.worst_mistakes)
    assert "Летучка" in joined
    assert "Фаербол" in joined
    assert "Придержи" in joined or "Ранний" in joined


def test_fireball_prefers_barbarians_over_witch():
    """Пак (варвары) важнее ведьмы — FB на варваров, ведьму другим ответом."""
    user = _team([
        "Hog Rider", "Ice Golem", "Musketeer", "Cannon",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ])
    opp = _team([
        "Giant", "Witch", "Barbarians", "Mega Minion",
        "Zap", "Bats", "Mini P.E.K.K.A", "Poison",
    ])
    report = TacticalMatchupAnalyzer.analyze(user, opp)
    joined = " ".join(report.critical_interactions + report.worst_mistakes)
    assert "Фаербол" in joined
    assert "Варвар" in joined
    assert "Ведьм" in joined


def test_guards_counter_ronin_not_danger():
    """Стражи — счётчик на Ронина; не пишем «нет счётчика»."""
    user = _team([
        "Hog Rider", "Executioner", "Tornado", "Guards",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ])
    opp = _team([
        "Ronin", "Witch", "Mega Minion", "Tesla",
        "Zap", "Bats", "Mini P.E.K.K.A", "Poison",
    ])
    report = TacticalMatchupAnalyzer.analyze(user, opp)
    danger_ronin = [d for d in report.danger_cards if d.name == "Ronin"]
    assert danger_ronin == []
    strong, _ = __import__(
        "bot.services.card_matchups", fromlist=["counters_in_deck"]
    ).counters_in_deck("Ronin", user)
    assert "Guards" in strong


def test_no_fireball_hold_without_target():
    """Без карт из FIREBALL_HOLD_PRIORITY — нет hold-советов про Фаербол.

    Кабаны / варвары / летучка и т.п. — валидные цели; здесь колода без них.
    """
    user = _team([
        "Hog Rider", "Ice Golem", "Musketeer", "Cannon",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ])
    opp = _team([
        "Hog Rider", "Knight", "Archers", "Ice Spirit",
        "Skeletons", "The Log", "Zap", "Mini P.E.K.K.A",
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
    joined = " ".join(report.critical_interactions)
    assert "Палач" in joined and "Торнадо" in joined
    assert "ключевая защита" in joined
    # Не дублируем ту же связку в mid.
    assert not any("Палач" in x and "Торнадо" in x for x in report.mid_game)


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
    openings = " ".join(report.best_openings)
    mistakes = " ".join(report.worst_mistakes)
    assert "Хог" in openings and "Тесла" in openings
    assert "после" in openings.lower()
    assert "защит" in openings.lower() or "дешёв" in openings.lower()
    assert "Хог" in mistakes and "Тесла" in mistakes
    assert "размен" in mistakes.lower() or "цикл" in mistakes.lower()
    # Opening и mistake по одной паре — намеренные инверсии, оба остаются.
    hog_tesla_open = [x for x in report.best_openings if "Хог" in x and "Тесла" in x]
    hog_tesla_mist = [x for x in report.worst_mistakes if "Хог" in x and "Тесла" in x]
    assert len(hog_tesla_open) == 1
    assert len(hog_tesla_mist) == 1
    # Одна тема — не в early и pressure одновременно.
    assert not any("Тесла" in x and "Хог" in x for x in report.early_game)
    assert not any("Тесла" in x for x in report.pressure_points)


def test_elixir_collector_not_treated_as_defensive_stop():
    """Сборщик — не здание-стоп; не пишем «Таран в готовый Сборщик»."""
    user = _team([
        "Battle Ram", "Bandit", "Royal Ghost", "Electro Wizard",
        "Zap", "Poison", "Dark Prince", "Magic Archer",
    ])
    opp = _team([
        "Three Musketeers", "Elixir Collector", "Battle Healer", "Goblin Gang",
        "The Log", "Heal Spirit", "Knight", "Minions",
    ])
    report = TacticalMatchupAnalyzer.analyze(user, opp)
    openings = " ".join(report.best_openings)
    mistakes = " ".join(report.worst_mistakes)
    assert "Сборщик" in openings or "эликсир" in openings.lower()
    assert "готовое" not in mistakes.lower() and "готовую" not in mistakes.lower()
    assert "проигрышный обмен" not in mistakes.lower()
    assert "после траты" not in openings.lower()
    assert "после траты" not in mistakes.lower()


def test_insights_have_reason_not_bare_template():
    user = _team([
        "Hog Rider", "Ice Golem", "Musketeer", "Fireball",
        "Ice Spirit", "Skeletons", "The Log", "Cannon",
    ])
    opp = _team([
        "Giant", "Witch", "Mega Minion", "Tesla",
        "Zap", "Bats", "Mini P.E.K.K.A", "Poison",
    ])
    report = TacticalMatchupAnalyzer.analyze(user, opp)
    for line in report.best_openings + report.worst_mistakes:
        assert "—" in line or ":" in line or "после" in line.lower()
        assert len(line) >= 40
        # Нет голых шаблонов без причины.
        bare = (
            "лучше пускать после траты",
            "проигрышный обмен",
            "используй эффективно",
        )
        low = line.lower()
        assert not any(b in low for b in bare)
    # Нет пустого заполнения одинаковыми шаблонами на все WC.
    assert len(report.best_openings) <= 4
    assert len(report.worst_mistakes) <= 4


def test_no_cross_bucket_duplicates():
    user = _team([
        "Hog Rider", "Executioner", "Tornado", "Valkyrie",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ])
    opp = _team([
        "Royal Giant", "Flying Machine", "Fisherman", "Tesla",
        "Royal Ghost", "Hunter", "The Log", "Earthquake",
    ])
    report = TacticalMatchupAnalyzer.analyze(user, opp)
    buckets = [
        report.early_game,
        report.mid_game,
        report.late_game,
        report.pressure_points,
        report.critical_interactions,
        report.best_openings,
    ]
    # Точные дубликаты строк между секциями запрещены.
    seen: set[str] = set()
    for bucket in buckets:
        for line in bucket:
            assert line not in seen, f"Дубль между секциями: {line}"
            seen.add(line)
    # Opening/mistake по Хог+Тесла могут сосуществовать — это не дубль.
    assert any("Хог" in x and "Тесла" in x for x in report.best_openings)
    assert any("Хог" in x and "Тесла" in x for x in report.worst_mistakes)


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

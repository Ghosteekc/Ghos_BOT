"""MatchPlanBuilder — уникальный план из состава + тактики."""

from bot.services.match_plan import MatchPlanBuilder
from bot.services.tactical_matchup import TacticalMatchupAnalyzer


def _deck(names: list[str]) -> list[str]:
    assert len(names) == 8
    return names


def test_hog_vs_tesla_plan_is_specific():
    my = _deck([
        "Hog Rider", "Ice Golem", "Musketeer", "Cannon",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ])
    enemy = _deck([
        "Giant", "Witch", "Mega Minion", "Tesla",
        "Zap", "Bats", "Mini P.E.K.K.A", "Flying Machine",
    ])
    tactical = TacticalMatchupAnalyzer.analyze(my, enemy)
    plan = MatchPlanBuilder.build(my, enemy, tactical=tactical)

    assert plan.has_content()
    assert plan.win_condition_window
    assert "Хог" in plan.win_condition_window
    assert "Тесла" in plan.win_condition_window or "после" in plan.win_condition_window.lower()

    # Инверсия окна — в тактических ошибках, не дублируется в avoid плана.
    mistakes = " ".join(tactical.worst_mistakes)
    assert "Хог" in mistakes and "Тесла" in mistakes

    save_names = {s.name for s in plan.save_cards}
    assert "Fireball" in save_names  # Flying Machine / Witch у врага
    fb_reasons = [s.reason for s in plan.save_cards if s.name == "Fireball"]
    assert fb_reasons
    assert any(
        "Летучка" in r or "Flying" in r or "Ведьм" in r
        for r in fb_reasons
    )

    phases = plan.game_plan.phase_1 + plan.game_plan.phase_2 + plan.game_plan.phase_3
    assert phases or plan.win_condition_window


def test_golem_plan_differs_from_hog():
    golem = _deck([
        "Golem", "Night Witch", "Baby Dragon", "Mega Minion",
        "Lumberjack", "Tornado", "Lightning", "Barbarian Barrel",
    ])
    hog = _deck([
        "Hog Rider", "Ice Golem", "Musketeer", "Cannon",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ])
    enemy = _deck([
        "Hog Rider", "Ice Golem", "Musketeer", "Tesla",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ])
    p_golem = MatchPlanBuilder.build(golem, enemy)
    p_hog = MatchPlanBuilder.build(hog, enemy)
    assert p_golem.win_condition_window != p_hog.win_condition_window
    assert "Голем" in p_golem.win_condition_window or "набор" in p_golem.win_condition_window.lower()


def test_no_generic_plan_without_premise():
    """Без пересечений hold-целей Fireball не попадает в save_cards."""
    my = _deck([
        "Hog Rider", "Ice Golem", "Musketeer", "Cannon",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ])
    enemy = _deck([
        "Hog Rider", "Ice Golem", "Knight", "Archers",
        "Ice Spirit", "Skeletons", "The Log", "Zap",
    ])
    plan = MatchPlanBuilder.build(my, enemy)
    save_names = {s.name for s in plan.save_cards}
    assert "Fireball" not in save_names


def test_graveyard_poison_save():
    my = _deck([
        "Giant", "Night Witch", "Baby Dragon", "Mega Minion",
        "Tornado", "Poison", "Barbarian Barrel", "Lumberjack",
    ])
    enemy = _deck([
        "Graveyard", "Ice Wizard", "Baby Dragon", "Tornado",
        "Freeze", "Knight", "Bomb Tower", "Skeletons",
    ])
    plan = MatchPlanBuilder.build(my, enemy)
    save_names = {s.name for s in plan.save_cards}
    assert "Poison" in save_names
    joined = " ".join(plan.avoid + plan.game_plan.phase_2)
    assert "Кладбище" in joined or "Яд" in joined or plan.win_condition_window


def test_plan_phases_do_not_repeat_window_topic():
    my = _deck([
        "Hog Rider", "Executioner", "Tornado", "Valkyrie",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ])
    enemy = _deck([
        "Royal Giant", "Flying Machine", "Fisherman", "Tesla",
        "Hunter", "Electro Spirit", "The Log", "Earthquake",
    ])
    plan = MatchPlanBuilder.build(my, enemy)
    assert plan.win_condition_window
    phases = (
        plan.game_plan.phase_1
        + plan.game_plan.phase_2
        + plan.game_plan.phase_3
        + plan.avoid
    )
    # Hog+Tesla тема живёт в окне атаки — не повторяем в фазах/avoid.
    hog_tesla = [
        x for x in phases
        if "Хог" in x and "Тесла" in x
    ]
    assert hog_tesla == []
    # Нет точных дублей внутри плана.
    assert len(phases) == len(set(phases))


def test_advantage_lines_include_reason():
    my = _deck([
        "Hog Rider", "Ice Golem", "Musketeer", "Cannon",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ])
    enemy = _deck([
        "Giant", "Witch", "Mega Minion", "Knight",
        "Zap", "Bats", "Mini P.E.K.K.A", "Poison",
    ])
    plan = MatchPlanBuilder.build(my, enemy)
    adv = [x for x in plan.game_plan.phase_2 if x.startswith("Преимущество:")]
    for line in adv:
        assert "—" in line or ":" in line
        assert len(line) >= 40
        assert "после траты" not in line.lower()
    assert plan.win_condition_window
    assert "—" in plan.win_condition_window or ":" in plan.win_condition_window
    assert "после траты" not in plan.win_condition_window.lower()


def test_save_fireball_barbarians_over_witch():
    my = _deck([
        "Hog Rider", "Ice Golem", "Musketeer", "Cannon",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ])
    enemy = _deck([
        "Giant", "Witch", "Barbarians", "Mega Minion",
        "Zap", "Bats", "Mini P.E.K.K.A", "Poison",
    ])
    plan = MatchPlanBuilder.build(my, enemy)
    fb = next(s for s in plan.save_cards if s.name == "Fireball")
    assert "Варвар" in fb.reason
    assert "Ведьм" in fb.reason


def test_guards_vs_ronin_not_in_avoid_as_no_counter():
    my = _deck([
        "Hog Rider", "Executioner", "Tornado", "Guards",
        "Ice Spirit", "Skeletons", "The Log", "Fireball",
    ])
    enemy = _deck([
        "Ronin", "Witch", "Mega Minion", "Tesla",
        "Zap", "Bats", "Mini P.E.K.K.A", "Poison",
    ])
    plan = MatchPlanBuilder.build(my, enemy)
    avoid_joined = " ".join(plan.avoid)
    assert "нет счётчика" not in avoid_joined.lower()
    assert not any("Ронин" in x and "счётчик" in x.lower() for x in plan.avoid)

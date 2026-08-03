"""Core Conflict Analysis and Stage-1 quality gate."""

from bot.services.deck_builder.core_conflict import (
    MIN_QUALITY_TOTAL,
    analyze_core_conflict,
    evaluation_score,
    filter_quality_results,
    is_quality_result,
)
from bot.services.deck_builder.builder import BuildResult
from bot.services.deck_evaluator.models import (
    AxisScore,
    ConstraintScore,
    EvaluationReport,
)


def _fake_evaluation(total: float) -> EvaluationReport:
    zero = AxisScore(score=0.0)
    ok = ConstraintScore(passed=True, score=100.0)
    return EvaluationReport(
        deck=("Hog Rider", "Ice Golem", "Musketeer", "Cannon", "Ice Spirit", "Skeletons", "The Log", "Fireball"),
        archetype="Cycle",
        hard_constraints=ok,
        soft_constraints=ok,
        role_coverage=zero,
        spell_balance=zero,
        cycle_quality=zero,
        win_plan=zero,
        synergy=AxisScore(score=70.0),
        matchup_coverage=zero,
        archetype_fit=zero,
        elixir_profile=zero,
        total_score=total,
    )


def _fake_result(total: float) -> BuildResult:
    return BuildResult(
        deck=["Hog Rider", "Ice Golem", "Musketeer", "Cannon", "Ice Spirit", "Skeletons", "The Log", "Fireball"],
        archetype="Cycle",
        average_elixir=2.9,
        confidence=50.0,
        evaluation=_fake_evaluation(total),
    )


def test_quality_gate_threshold():
    assert is_quality_result(_fake_result(MIN_QUALITY_TOTAL))
    assert is_quality_result(_fake_result(MIN_QUALITY_TOTAL + 5))
    assert not is_quality_result(_fake_result(MIN_QUALITY_TOTAL - 0.1))
    assert not is_quality_result(None)
    strong = [_fake_result(70), _fake_result(40)]
    assert len(filter_quality_results(strong)) == 1
    assert evaluation_score(strong[0]) == 70.0


def test_conflict_picks_max_gain_card(monkeypatch):
    """Удаление Executioner даёт max score — он и есть конфликтующая карта."""
    scores = {
        frozenset({"Hog Rider", "Mighty Miner", "Valkyrie"}): 91.0,  # drop Executioner
        frozenset({"Hog Rider", "Mighty Miner", "Executioner"}): 70.0,  # drop Valkyrie
        frozenset({"Hog Rider", "Executioner", "Valkyrie"}): 74.0,  # drop Mighty Miner
        frozenset({"Mighty Miner", "Executioner", "Valkyrie"}): 40.0,  # drop Hog
    }

    def fake_build(core, pool=None):
        key = frozenset(core)
        total = scores[key]
        return BuildResult(
            deck=list(core) + ["Ice Spirit", "Skeletons", "The Log", "Cannon", "Fireball"][: 8 - len(core)],
            archetype="Cycle",
            average_elixir=3.0,
            confidence=40.0,
            evaluation=_fake_evaluation(total),
        )

    monkeypatch.setattr(
        "bot.services.deck_builder.core_conflict.build_deck_from_core",
        fake_build,
    )

    core = ["Hog Rider", "Mighty Miner", "Executioner", "Valkyrie"]
    report = analyze_core_conflict(core, pool=set(core), baseline_score=50.0)
    assert report is not None
    assert report.conflicting_card == "Executioner"
    assert report.alternative_score == 91.0
    assert report.quality_gain == 41.0
    assert "Executioner" not in report.alternative_core
    assert set(report.alternative_core) == {"Hog Rider", "Mighty Miner", "Valkyrie"}


def test_conflict_skipped_when_no_viable_builds(monkeypatch):
    def boom(core, pool=None):
        raise ValueError("no_candidates")

    monkeypatch.setattr(
        "bot.services.deck_builder.core_conflict.build_deck_from_core",
        boom,
    )
    report = analyze_core_conflict(
        ["Hog Rider", "Lava Hound", "Princess", "Inferno Tower"],
        baseline_score=0.0,
    )
    assert report is None

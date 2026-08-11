"""Regression: RecommendationReport всегда согласован с improved_deck."""

from __future__ import annotations

from bot.services.deck_builder.quality import evaluate_deck, is_good_deck
from bot.services.recommendation_engine import RecommendationEngine


def _deck(names: list[str]) -> list[str]:
    assert len(names) == 8 and len(set(names)) == 8
    return names


def _final_fields(result):
    """Единый срез полей, которые обязаны относиться к одной колоде."""
    ev = result.evaluation_report
    assert ev is not None
    improved = list(result.improvement_plan.improved_deck)
    return {
        "deck": improved,
        "eval_deck": list(ev.deck),
        "score": float(ev.total_score),
        "balanced": bool(ev.hard_constraints.passed),
        "playable": is_good_deck(report=ev),
        "sanity": bool(result.sanity_report.passed) if result.sanity_report else False,
        "risk_inv": round(100.0 - float(ev.total_score), 1),
        "risk": float(result.risk_assessment.score),
        "why_picks": list(result.decision_explanation.why_picks),
        "gaps": list(result.decision_explanation.why_gaps),
        "balance_hard": list(result.balance_issues.hard),
    }


def test_swap_improves_score_uses_improved_evaluation():
    """Test 1: после swap финальный score = evaluation(improved), не original."""
    deck = _deck([
        "Knight", "Archers", "Bomber", "Giant",
        "Arrows", "Zap", "Minions", "Cannon",
    ])
    original_score = evaluate_deck(deck).total_score
    result = RecommendationEngine.analyze(deck, apply_swaps=True, use_cache=False)
    improved = result.improvement_plan.improved_deck
    assert result.improvement_plan.needed
    assert sorted(improved) != sorted(deck)

    improved_score = evaluate_deck(improved).total_score
    fields = _final_fields(result)
    assert fields["score"] == improved_score
    assert fields["score"] != original_score or improved_score == original_score
    assert sorted(fields["eval_deck"]) == sorted(improved)
    assert abs(fields["risk"] - fields["risk_inv"]) < 0.05


def test_swap_worsens_score_does_not_keep_old_high_score():
    """Test 2: если swap ухудшил score — report не показывает старый высокий."""
    deck = _deck([
        "Hog Rider", "Ice Golem", "Musketeer", "Cannon",
        "Ice Spirit", "Skeletons", "Fireball", "The Log",
    ])
    original_score = evaluate_deck(deck).total_score
    result = RecommendationEngine.analyze(deck, apply_swaps=True, use_cache=False)
    improved = result.improvement_plan.improved_deck
    if sorted(improved) == sorted(deck):
        return  # no-op для этой колоды — Test 4 покрывает

    improved_score = evaluate_deck(improved).total_score
    fields = _final_fields(result)
    assert fields["score"] == improved_score
    if improved_score < original_score:
        assert fields["score"] < original_score


def test_improved_deck_hard_fail_not_playable():
    """Test 3: hard-fail improved → playable False, даже если plan.needed."""
    deck = _deck([
        "Hog Rider", "Giant", "Golem", "Knight",
        "Archers", "Skeletons", "Zap", "Cannon",
    ])
    result = RecommendationEngine.analyze(deck, apply_swaps=True, use_cache=False)
    fields = _final_fields(result)
    assert result.improvement_plan.needed
    # Если evaluation final_deck hard-fail — playable обязан быть False.
    if not result.evaluation_report.hard_constraints.passed:
        assert fields["playable"] is False
        joined = " ".join(fields["why_picks"]).lower()
        assert "подходит для вашей арены" not in joined
        # Не маскируем hard-fail фразой «есть замены», когда swaps уже внутри improved.
        assert "сделают план атаки и защиту ровнее" not in joined


def test_noop_improvement_single_final_evaluation(monkeypatch):
    """Test 4: без изменений колоды — один evaluate на финальный report (не двойной)."""
    deck = _deck([
        "Hog Rider", "Ice Golem", "Musketeer", "Cannon",
        "Ice Spirit", "Skeletons", "Fireball", "The Log",
    ])
    # Колода без gap-swap в большинстве пулов: apply_swaps=False гарантирует no-op.
    import bot.services.recommendation_engine as re

    calls: list[tuple[str, ...]] = []
    real_evaluate = re.evaluate_deck

    def tracking_evaluate(d, **kwargs):
        calls.append(tuple(d))
        return real_evaluate(d, **kwargs)

    monkeypatch.setattr(re, "evaluate_deck", tracking_evaluate)
    result = RecommendationEngine.analyze(deck, apply_swaps=False, use_cache=False)
    improved = result.improvement_plan.improved_deck
    assert sorted(improved) == sorted(deck)
    # Только финальный evaluate для отчёта (без post-swap цикла).
    assert len(calls) == 1
    assert sorted(calls[0]) == sorted(deck)
    assert result.evaluation_report.total_score == evaluate_deck(deck).total_score


def test_remarks_do_not_describe_dropped_card_as_present():
    """Test 5: после drop карты remarks не говорят, что она всё ещё в колоде."""
    from bot.services.card_names_ru import card_name_ru

    deck = _deck([
        "Knight", "Archers", "Bomber", "Giant",
        "Arrows", "Zap", "Minions", "Cannon",
    ])
    result = RecommendationEngine.analyze(deck, apply_swaps=True, use_cache=False)
    improved = result.improvement_plan.improved_deck
    dropped = set(deck) - set(improved)
    if not dropped:
        return

    remarks_lines = [
        line for line in result.decision_explanation.why_picks
        if "→" not in line and not line.startswith("Добавить:")
        and line not in {"Что хорошо", "Что можно улучшить", "Итоговая рекомендация"}
    ]
    for name in dropped:
        labels = {
            name.lower(),
            (card_name_ru(name) or "").lower(),
            (card_name_ru(name, short=True) or "").lower(),
        }
        labels.discard("")
        for line in remarks_lines:
            low = line.lower()
            # «Главная угроза — X» для выкинутой WC недопустимо.
            for label in labels:
                if label and label in low:
                    assert "главная угроза" not in low


def test_score_balanced_sanity_remarks_same_deck():
    """Test 6: score / balanced / playable / sanity / remarks — одна final колода."""
    deck = _deck([
        "Goblin Barrel", "Princess", "Goblin Gang", "Dart Goblin",
        "Inferno Tower", "The Log", "Knight", "Ice Spirit",
    ])
    result = RecommendationEngine.analyze(deck, apply_swaps=True, use_cache=False)
    fields = _final_fields(result)
    improved = fields["deck"]

    assert sorted(fields["eval_deck"]) == sorted(improved)
    assert abs(fields["risk"] - fields["risk_inv"]) < 0.05
    assert fields["playable"] == is_good_deck(report=result.evaluation_report)
    assert fields["balanced"] == result.evaluation_report.hard_constraints.passed
    # Sanity и balance hard согласованы с тем же evaluation.
    assert set(fields["balance_hard"]) == set(result.evaluation_report.hard_constraints.issues)
    # Почему gaps — из того же evaluation (подмножество его сообщений).
    eval_msgs = set(result.evaluation_report.hard_constraints.messages) | set(
        result.evaluation_report.soft_constraints.messages
    )
    for gap in fields["gaps"]:
        assert gap in eval_msgs or gap in set(
            result.evaluation_report.can_improve or ()
        ) or gap in set(result.evaluation_report.weaknesses or ())

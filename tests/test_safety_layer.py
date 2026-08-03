"""Tests for strengthened SafetyLayer post-validation."""
from __future__ import annotations

from bot.services.ghosteek_ai.context.ai_context import (
    AIContext,
    ArenaContext,
    BattleContext,
    EvaluationContext,
    RecommendationContext,
)
from bot.services.ghosteek_ai.safety.layer import SafetyLayer
from bot.services.ghosteek_ai.safety.validators import (
    validate_battle_claims,
    validate_language,
    validate_numbers,
    validate_statistics,
)


def test_validate_language_rewrites_sight_verbs():
    out = validate_language("Я увидел, что Хог давит левую. Я заметил слабость цикла.")
    low = out.lower()
    assert "я увидел" not in low
    assert "я заметил" not in low
    assert "по данным анализа" in low or "по информации матча" in low


def test_validate_numbers_removes_invented_percent():
    ctx = AIContext()
    out = validate_numbers("У тебя 74% шанс на победу в этом матчапе.", ctx)
    assert "74%" not in out
    assert "шанс" in out.lower() or "хорош" in out.lower()


def test_validate_numbers_keeps_known_winrate():
    ctx = AIContext(data={"winrate": 74})
    out = validate_numbers("У тебя 74% шанс на победу.", ctx)
    assert "74%" in out


def test_validate_battle_claims_rewrites_damage_and_replay():
    ctx = AIContext()
    out = validate_battle_claims(
        "Карта нанесла 1240 урона. Я смотрел реплей на 30 секунде.",
        ctx,
    )
    low = out.lower()
    assert "1240" not in low
    assert "репле" not in low or "реплея в данных нет" in low


def test_validate_statistics_without_context():
    out = validate_statistics("По статистике винрейт 81% в этом бою.", AIContext())
    assert "81%" not in out
    assert "шанс" in out.lower() or "хорош" in out.lower() or "матчап" in out.lower()


def test_safety_layer_apply_uses_context_and_keeps_api():
    ctx = AIContext(
        arena=ArenaContext(trophies=9000),
        recommendation=RecommendationContext(synergy_score=82),
        evaluation=EvaluationContext(score=7),
        battle=BattleContext(won=True, outcome_summary="win"),
    )
    raw = (
        "Я посмотрел бой. У тебя 55% шанс. "
        "Карта нанесла 900 урона. Синергия 82 нормальная."
    )
    out = SafetyLayer.apply(raw, ctx)
    low = out.lower()
    assert "я посмотрел" not in low
    assert "55%" not in out
    assert "900" not in out
    # известная синергия может остаться
    assert isinstance(out, str) and len(out) > 10

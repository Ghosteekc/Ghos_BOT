"""Неизменяемый отчёт единой оценки колоды."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


def _round(value: float, digits: int = 1) -> float:
    return round(float(value), digits)


@dataclass(frozen=True)
class AxisScore:
    """Числовая ось 0–100 с опциональными деталями и заметками."""

    score: float
    details: Mapping[str, Any] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": _round(self.score),
            "details": dict(self.details),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class ConstraintScore:
    """Жёсткие / мягкие ограничения."""

    passed: bool
    score: float
    issues: tuple[str, ...] = ()
    messages: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "score": _round(self.score),
            "issues": list(self.issues),
            "messages": list(self.messages),
        }


@dataclass(frozen=True)
class EvaluationReport:
    """Единый снимок качества готовой колоды из 8 карт.

    DeckEvaluator только оценивает — состав колоды не меняется.
    """

    deck: tuple[str, ...]
    archetype: str
    hard_constraints: ConstraintScore
    soft_constraints: ConstraintScore
    role_coverage: AxisScore
    spell_balance: AxisScore
    cycle_quality: AxisScore
    win_plan: AxisScore
    synergy: AxisScore
    matchup_coverage: AxisScore
    archetype_fit: AxisScore
    elixir_profile: AxisScore
    total_score: float
    strengths: tuple[str, ...] = ()
    weaknesses: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "deck": list(self.deck),
            "archetype": self.archetype,
            "hard_constraints": self.hard_constraints.to_dict(),
            "soft_constraints": self.soft_constraints.to_dict(),
            "role_coverage": self.role_coverage.to_dict(),
            "spell_balance": self.spell_balance.to_dict(),
            "cycle_quality": self.cycle_quality.to_dict(),
            "win_plan": self.win_plan.to_dict(),
            "synergy": self.synergy.to_dict(),
            "matchup_coverage": self.matchup_coverage.to_dict(),
            "archetype_fit": self.archetype_fit.to_dict(),
            "elixir_profile": self.elixir_profile.to_dict(),
            "total_score": _round(self.total_score),
            "strengths": list(self.strengths),
            "weaknesses": list(self.weaknesses),
            "reasons": list(self.reasons),
        }

    def as_dict(self) -> dict[str, Any]:
        """Алиас для совместимости с asdict-стилем других сервисов."""
        return self.to_dict()


def empty_evaluation_report(
    deck: list[str] | tuple[str, ...] | None = None,
    *,
    reason: str = "Нужна полная колода из 8 карт",
) -> EvaluationReport:
    """Минимальный отчёт при невалидном входе."""
    zero = AxisScore(score=0.0, notes=(reason,))
    fail = ConstraintScore(passed=False, score=0.0, issues=("deck_size",), messages=(reason,))
    cards = tuple(deck or ())
    return EvaluationReport(
        deck=cards,
        archetype="Unknown",
        hard_constraints=fail,
        soft_constraints=fail,
        role_coverage=zero,
        spell_balance=zero,
        cycle_quality=zero,
        win_plan=zero,
        synergy=zero,
        matchup_coverage=zero,
        archetype_fit=zero,
        elixir_profile=zero,
        total_score=0.0,
        strengths=(),
        weaknesses=(reason,),
        reasons=(reason,),
    )

"""Единый, объяснимый источник оценки матчапа."""

from __future__ import annotations

from dataclasses import dataclass, field


_FACTOR_KEYS = (
    "counter_database",
    "win_condition_interaction",
    "building_availability",
    "air_control",
    "cycle_speed",
    "pressure",
    "spell_advantage",
    "archetypes",
    "card_roles",
)


def _clamp(value: float) -> int:
    return int(max(0, min(100, round(value))))


def rating_for(score: int) -> str:
    if score <= 20:
        return "Очень лёгкий"
    if score <= 40:
        return "Лёгкий"
    if score <= 60:
        return "Равный"
    if score <= 80:
        return "Сложный"
    return "Очень сложный"


@dataclass(frozen=True)
class MatchupFactor:
    key: str
    delta: float
    reason: str


@dataclass
class MatchupEvaluation:
    """Оценка сложности для первой (user) колоды против второй."""

    score: int = 50
    difficulty: int = 50
    rating: str = "Равный"
    reasons: list[str] = field(default_factory=list)
    advantages: list[str] = field(default_factory=list)
    disadvantages: list[str] = field(default_factory=list)
    factors: dict[str, int] = field(default_factory=dict)
    contributions: list[MatchupFactor] = field(default_factory=list)

    @classmethod
    def evaluate(
        cls,
        user_deck: list[str],
        opponent_deck: list[str],
    ) -> MatchupEvaluation:
        """Собирает только факторы, которые непосредственно меняют score."""
        if len(user_deck) < 8 or len(opponent_deck) < 8:
            return cls(factors={key: 50 for key in _FACTOR_KEYS})

        # Хелперы правил остаются рядом с их карточными константами; расчёт и
        # интерпретация выполняются исключительно здесь.
        from bot.services.match_difficulty import (
            _Factor,
            _air_factor,
            _archetype_factor,
            _building_factor,
            _card_role_factors,
            _cycle_pressure_factor,
            _spell_advantage_factor,
            _wc_counter_pressure,
        )

        raw_factors: list[_Factor] = (
            _wc_counter_pressure(user_deck, opponent_deck)
            + _building_factor(user_deck, opponent_deck)
            + _air_factor(user_deck, opponent_deck)
            + _cycle_pressure_factor(user_deck, opponent_deck)
            + _spell_advantage_factor(user_deck, opponent_deck)
            + _archetype_factor(user_deck, opponent_deck)
            + _card_role_factors(user_deck, opponent_deck)
        )

        totals = {key: 0.0 for key in _FACTOR_KEYS}
        contributions: list[MatchupFactor] = []
        seen: set[tuple[str, str]] = set()
        for factor in raw_factors:
            totals[factor.key] = totals.get(factor.key, 0.0) + factor.delta
            if not factor.reason:
                continue
            identity = (factor.key, factor.reason)
            if identity in seen:
                continue
            seen.add(identity)
            contributions.append(MatchupFactor(factor.key, factor.delta, factor.reason))

        score = _clamp(50 + sum(totals.values()))
        disadvantages = [item.reason for item in contributions if item.delta > 0]
        advantages = [item.reason for item in contributions if item.delta < 0]

        # Показываем причины только той стороны, которую подтверждает итог:
        # невозможно получить «Очень сложный» вместе с позитивным матчапом.
        if score > 60:
            reasons = disadvantages
        elif score < 40:
            reasons = advantages
        else:
            reasons = [item.reason for item in contributions]

        if score > 60 and not reasons:
            reasons = ["Структурный перевес соперника по контрам и темпу."]
        elif score < 40 and not reasons:
            reasons = ["Структурный перевес вашей колоды по контрам и темпу."]

        return cls(
            score=score,
            difficulty=score,
            rating=rating_for(score),
            reasons=reasons[:6],
            advantages=advantages[:6],
            disadvantages=disadvantages[:6],
            factors={key: _clamp(50 + value) for key, value in totals.items()},
            contributions=contributions,
        )


def evaluate_matchup(user_deck: list[str], opponent_deck: list[str]) -> MatchupEvaluation:
    return MatchupEvaluation.evaluate(user_deck, opponent_deck)

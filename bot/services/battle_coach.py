"""Battle Coach — только слой, которого нет в других блоках разбора.

CR API не отдаёт реплей. Тактика / план / сложность / summary уже есть отдельно.
Coach оставляет: перелом по длительности/счёту и гипотезу «если бы» по дыре в контрах.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from bot.services.card_matchups import counters_in_deck
from bot.services.card_names_ru import card_name_ru
from bot.services.elixir_efficiency import ElixirEfficiencyReport
from bot.services.match_difficulty import MatchDifficultyReport
from bot.services.match_plan import MatchPlanReport
from bot.services.tactical_matchup import TacticalMatchupReport

_DATA_LIMIT_NOTE = (
    "Clash Royale API не отдаёт реплей и таймлайн действий. "
    "Перелом и альтернатива ниже — по длительности, счёту и дырам в контрах состава, "
    "без выдуманных ходов боя."
)


def _ru(card: str) -> str:
    return card_name_ru(card) or card


@dataclass
class CoachInsight:
    """Один коучинговый вывод с явным уровнем уверенности."""

    title: str
    text: str
    evidence: list[str] = field(default_factory=list)
    confidence: str = "medium"  # high | medium | low | insufficient

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def usable(self) -> bool:
        return self.confidence != "insufficient" and bool(self.text.strip())


@dataclass
class BattleCoachReport:
    main_mistakes: list[CoachInsight] = field(default_factory=list)
    best_moment: CoachInsight | None = None
    turning_point: CoachInsight | None = None
    outcome_decider: CoachInsight | None = None
    danger_moment: CoachInsight | None = None
    counterfactual: CoachInsight | None = None
    data_notes: list[str] = field(default_factory=list)
    sufficient: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "main_mistakes": [m.to_dict() for m in self.main_mistakes],
            "best_moment": self.best_moment.to_dict() if self.best_moment else None,
            "turning_point": self.turning_point.to_dict() if self.turning_point else None,
            "outcome_decider": self.outcome_decider.to_dict() if self.outcome_decider else None,
            "danger_moment": self.danger_moment.to_dict() if self.danger_moment else None,
            "counterfactual": self.counterfactual.to_dict() if self.counterfactual else None,
            "data_notes": list(self.data_notes),
            "sufficient": self.sufficient,
        }

    def has_content(self) -> bool:
        return bool(
            (self.turning_point and self.turning_point.usable)
            or (self.counterfactual and self.counterfactual.usable)
        )


def _insufficient(title: str, reason: str) -> CoachInsight:
    return CoachInsight(
        title=title,
        text=reason,
        evidence=[],
        confidence="insufficient",
    )


def _dedupe_lines(lines: list[str], *, limit: int = 6) -> list[str]:
    out: list[str] = []
    for line in lines:
        text = (line or "").strip()
        if not text or text in out:
            continue
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _build_turning_point(
    *,
    won: bool,
    duration: int,
    crowns_user: int,
    crowns_opp: int,
    crown_score: str,
    user_elixir: ElixirEfficiencyReport | None,
    opp_elixir: ElixirEfficiencyReport | None,
) -> CoachInsight:
    evidence: list[str] = []
    if crown_score:
        evidence.append(f"счёт: {crown_score}")
    if duration:
        evidence.append(f"длительность: {duration}с")

    if duration >= 180:
        profile = ""
        if user_elixir:
            profile = user_elixir.elixir_profile
            evidence.append(f"ваш elixir profile: {profile}")
        side = "ваше" if won else "соперника"
        text = (
            f"Бой ушёл за {duration // 60}:{duration % 60:02d} — перелом вероятнее "
            f"в фазе дабл-эликсира / овертайма, где реализовалось преимущество {side}."
        )
        if profile and "Beatdown" in profile and won:
            text += f" Профиль «{profile}» сильнее именно в дабле."
        elif profile and "Cycle" in profile and not won and opp_elixir and "Beatdown" in (
            opp_elixir.elixir_profile or ""
        ):
            text += " Тяжёлая колода соперника набрала силу позже."
            evidence.append(f"opp profile: {opp_elixir.elixir_profile}")
        return CoachInsight(
            title="Переломный момент",
            text=text,
            evidence=evidence,
            confidence="medium",
        )

    if duration and duration <= 90:
        return CoachInsight(
            title="Переломный момент",
            text=(
                f"Короткий бой ({duration}с, счёт {crown_score or f'{crowns_user}:{crowns_opp}'}). "
                "Перелом, скорее всего, случился рано — через быстрый цикл или ошибку на открытии. "
                "Точный ход API не показывает."
            ),
            evidence=evidence,
            confidence="low",
        )

    if abs(crowns_user - crowns_opp) >= 2 or (won and crowns_user == 3):
        return CoachInsight(
            title="Переломный момент",
            text=(
                f"Крупный разрыв по коронам ({crown_score or f'{crowns_user}:{crowns_opp}'}). "
                "Перелом связан с взятием башни, а не с равным эндшпилем — "
                "без реплея нельзя назвать секунду."
            ),
            evidence=evidence,
            confidence="medium",
        )

    return _insufficient(
        "Переломный момент",
        "По длительности и счёту нельзя надёжно выделить перелом без таймлайна боя.",
    )


def _build_counterfactual(
    *,
    won: bool,
    user_deck: list[str],
    threats: list[str],
    missing_counters: list[str],
) -> CoachInsight:
    """Только конкретная замена карты — не пересказ avoid/mistakes/difficulty."""
    for threat in threats:
        strong, partial = counters_in_deck(threat, user_deck)
        if strong:
            continue
        candidates = [c for c in missing_counters if c not in user_deck][:2]
        if not candidates and not partial:
            continue
        pick = candidates[0] if candidates else partial[0]
        text = (
            f"Если бы вместо слабого ответа на {_ru(threat)} в колоде был {_ru(pick)}, "
            f"вероятнее удалось бы стабильнее гасить пуш и "
            + ("удержать башни дольше." if not won else "снизить риск даже при победе.")
        )
        return CoachInsight(
            title="Если бы сделали иначе",
            text=text,
            evidence=[
                f"угроза: {_ru(threat)}",
                f"альтернатива по базе контр: {_ru(pick)}",
                "гипотеза по составу, не кадр реплея",
            ],
            confidence="medium",
        )

    return _insufficient(
        "Если бы сделали иначе",
        "Нет устойчивой альтернативы по дыре в контрах — не дублируем тактику и план.",
    )


class BattleCoach:
    """Собирает только непересекающийся с tactical/plan/difficulty/summary слой."""

    @staticmethod
    def analyze(
        *,
        won: bool,
        user_deck: list[str],
        opponent_deck: list[str],
        threats: list[str],
        missing_counters: list[str],
        outcome_summary: str = "",
        matchup_score: float = 50.0,
        duration: int = 0,
        crowns_user: int = 0,
        crowns_opp: int = 0,
        crown_score: str = "",
        tactical: TacticalMatchupReport | None = None,
        match_plan: MatchPlanReport | None = None,
        match_difficulty: MatchDifficultyReport | None = None,
        user_elixir: ElixirEfficiencyReport | None = None,
        opponent_elixir: ElixirEfficiencyReport | None = None,
        user_key_cards: list[Any] | None = None,
        opponent_key_cards: list[Any] | None = None,
        low_impact_cards: list[Any] | None = None,
    ) -> BattleCoachReport:
        # Неиспользуемые kwargs сохранены для совместимости вызова из battle_report.
        _ = (
            outcome_summary,
            matchup_score,
            tactical,
            match_plan,
            match_difficulty,
            user_key_cards,
            opponent_key_cards,
            low_impact_cards,
            opponent_deck,
        )
        notes = [_DATA_LIMIT_NOTE]
        if len(user_deck) < 8 or len(opponent_deck) < 8:
            notes.append("Колоды неполные — часть выводов недоступна.")
            return BattleCoachReport(
                main_mistakes=[],
                best_moment=None,
                turning_point=_insufficient("Переломный момент", "Нужны обе колоды из 8 карт."),
                outcome_decider=None,
                danger_moment=None,
                counterfactual=_insufficient("Если бы сделали иначе", "Нужны обе колоды из 8 карт."),
                data_notes=notes,
                sufficient=False,
            )

        turning = _build_turning_point(
            won=won,
            duration=duration,
            crowns_user=crowns_user,
            crowns_opp=crowns_opp,
            crown_score=crown_score,
            user_elixir=user_elixir,
            opp_elixir=opponent_elixir,
        )
        alt = _build_counterfactual(
            won=won,
            user_deck=user_deck,
            threats=threats,
            missing_counters=missing_counters,
        )

        usable = sum(1 for item in (turning, alt) if item and item.usable)
        if usable < 1:
            notes.append("Уникальных выводов для Coach нет — смотрите тактику, план и сложность матчапа.")

        return BattleCoachReport(
            main_mistakes=[],
            best_moment=None,
            turning_point=turning if turning.usable else None,
            outcome_decider=None,
            danger_moment=None,
            counterfactual=alt if alt.usable else None,
            data_notes=_dedupe_lines(notes, limit=4),
            sufficient=usable >= 1,
        )


def build_battle_coach(**kwargs: Any) -> BattleCoachReport:
    return BattleCoach.analyze(**kwargs)

"""RecommendationEngine: объяснение Builder и улучшение пользовательской колоды.

План улучшений:
  Intent → gaps → solve one → virtual apply → EvaluationReport → re-detect → …

Score колоды и тексты советов — только из Builder EvaluationReport
(evaluate_deck). После каждого swap EvaluationReport пересчитывается.
Собственный total_score / risk-формула по hard*18+soft*10 запрещены.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from enum import Enum

from bot.services.deck_builder.quality import (
    balance_issues_from_report,
    evaluate_deck,
    is_good_deck,
)
from bot.services.deck_builder.constraint_messages import SOFT_MESSAGES
from bot.services.deck_builder.builder import _detect_archetype
from bot.services.deck_builder.constants import (
    ROLE_AIR,
    ROLE_ANTI_TANK,
    ROLE_BUILDING,
    ROLE_DEFENSIVE,
    ROLE_SPLASH,
)
from bot.services.deck_builder.loader import get_database
from bot.services.deck_game_plan import GamePlan, build_game_plan
from bot.services.deck_intent import DeckIntent, DeckIntentEngine
from bot.services.deck_improver import (
    CandidateRating,
    GapSolution,
    _CATEGORY_ROLE,
    _apply_arena_fixes,
    _build_synergy_map,
    _card_ru,
    _collect_improvement_gaps,
    _fix_elixir_if_needed,
    _gap_relevant_for_intent,
    _gather_replacement_candidates,
    _list_replaceable,
    _locked_cards,
    _trim_spell_and_win_limits,
    candidate_sort_key,
    is_better_candidate,
    rank_candidates,
    search_gap_solution,
    SolutionTier,
)
from bot.services.card_names_ru import format_card_combo_ru
from bot.services.recommendation_cache import (
    recommendation_cache,
    recommendation_cache_key,
)

logger = logging.getLogger(__name__)

class DeckOrigin(str, Enum):
    """Происхождение колоды для политики рекомендаций."""

    PLAYER = "player"
    BUILDER = "builder"

# Меньше = важнее. Единый порядок для всех режимов.
_GAP_PRIORITY: dict[str, int] = {
    "win_condition": 10,
    "spells": 20,
    "finishers": 30,
    "anti_air": 40,
    "defense": 50,
    "splash": 60,
    "point_target": 70,
    "swarm": 80,
    "cycle": 90,
    "support": 100,
    "focus": 110,
}

_SOFT_FOR_CATEGORY: dict[str, str] = {
    "finishers": "big_spell",
    "anti_air": "air_defense",
    "splash": "anti_swarm",
    "defense": "building",
    "point_target": "anti_tank",
    "swarm": "small_spell",
    "cycle": "cycle",
}


@dataclass(frozen=True)
class BalanceIssues:
    hard: list[str]
    soft: list[str]
    messages: list[str]


@dataclass(frozen=True)
class ImprovementStep:
    category: str
    message: str
    drop: str | None
    pick: str | None
    suggested_cards: list[str]
    tier: str | None
    rating: CandidateRating | None
    reason: str | None = None  # пользовательская причина (без tier/score)


@dataclass(frozen=True)
class ImprovementPlan:
    needed: bool
    steps: list[ImprovementStep]
    improved_deck: list[str]
    locked: list[str]


@dataclass(frozen=True)
class RejectedCandidateExplanation:
    """Почему кандидат отклонён относительно выбранной карты (только debug)."""

    card: str
    reasons: list[str]


@dataclass(frozen=True)
class PickExplanation:
    """Объяснение одного выбора после оценки всех факторов CandidateRating."""

    category: str
    pick: str
    drop: str | None
    pros: list[str]
    rejected: list[RejectedCandidateExplanation]
    reason: str = ""  # одна фраза для UI


@dataclass(frozen=True)
class DecisionExplanation:
    archetype: str
    primary_win: str | None
    why_gaps: list[str]  # debug / внутренние
    why_picks: list[str]  # только пользовательские строки для issues
    rejected: list[str]  # debug: незакрытые gaps
    pick_explanations: list[PickExplanation] = field(default_factory=list)


@dataclass
class CandidateRanking:
    by_gap: dict[str, list[CandidateRating]] = field(default_factory=dict)
    applied: list[CandidateRating] = field(default_factory=list)


@dataclass(frozen=True)
class RiskAssessment:
    score: float
    factors: list[str]
    open_gaps: list[str]


@dataclass(frozen=True)
class DeckCoaching:
    """Объяснение готовой колоды Builder без подбора замен."""

    strengths: list[str]
    play_style: str
    key_combinations: list[str]
    usage_tips: list[str]
    card_choices: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "strengths": list(self.strengths),
            "play_style": self.play_style,
            "key_combinations": list(self.key_combinations),
            "usage_tips": list(self.usage_tips),
            "card_choices": list(self.card_choices),
        }


@dataclass(frozen=True)
class RecommendationResult:
    intent: DeckIntent
    game_plan: GamePlan
    balance_issues: BalanceIssues
    improvement_plan: ImprovementPlan
    decision_explanation: DecisionExplanation
    candidate_ranking: CandidateRanking
    risk_assessment: RiskAssessment
    origin: str = DeckOrigin.PLAYER.value
    coaching: DeckCoaching | None = None
    evaluation_report: object | None = None  # EvaluationReport — единый слой оценки
    sanity_report: object | None = None  # DeckSanityReport — gate перед coaching
    def to_dict(self) -> dict:
        """Полный внутренний снимок (логирование / режим разработчика)."""
        def rating_dict(r: CandidateRating | None) -> dict | None:
            if r is None:
                return None
            return asdict(r)

        report = self.evaluation_report
        return {
            "intent": {
                "archetype": self.intent.archetype,
                "play_style": self.intent.play_style,
                "primary_win": self.intent.primary_win,
                "required_soft_checks": sorted(self.intent.required_soft_checks),
                "min_air_defense": self.intent.min_air_defense,
                "require_building": self.intent.require_building,
                "min_cycle_cards": self.intent.min_cycle_cards,
                "required_role_ids": sorted(self.intent.required_role_ids),
                "attack_bias": self.intent.attack_bias,
            },
            "game_plan": self.game_plan.to_dict(),
            "evaluation_report": report.to_dict() if report is not None else None,
            "balance_issues": {
                "hard": list(self.balance_issues.hard),
                "soft": list(self.balance_issues.soft),
                "messages": list(self.balance_issues.messages),
            },
            "improvement_plan": {
                "needed": self.improvement_plan.needed,
                "steps": [
                    {
                        "category": s.category,
                        "message": s.message,
                        "drop": s.drop,
                        "pick": s.pick,
                        "suggested_cards": list(s.suggested_cards),
                        "tier": s.tier,
                        "rating": rating_dict(s.rating),
                        "reason": s.reason,
                    }
                    for s in self.improvement_plan.steps
                ],
                "improved_deck": list(self.improvement_plan.improved_deck),
                "locked": list(self.improvement_plan.locked),
            },
            "decision_explanation": {
                "archetype": self.decision_explanation.archetype,
                "primary_win": self.decision_explanation.primary_win,
                "why_gaps": list(self.decision_explanation.why_gaps),
                "why_picks": list(self.decision_explanation.why_picks),
                "rejected": list(self.decision_explanation.rejected),
                "pick_explanations": [
                    {
                        "category": pe.category,
                        "pick": pe.pick,
                        "drop": pe.drop,
                        "reason": pe.reason,
                        "pros": list(pe.pros),
                        "rejected": [
                            {"card": rc.card, "reasons": list(rc.reasons)}
                            for rc in pe.rejected
                        ],
                    }
                    for pe in self.decision_explanation.pick_explanations
                ],
                "swaps": [
                    {
                        "drop": pe.drop,
                        "pick": pe.pick,
                        "reason": pe.reason,
                    }
                    for pe in self.decision_explanation.pick_explanations
                    if pe.pick
                ],
            },
            "candidate_ranking": {
                "by_gap": {
                    cat: [asdict(r) for r in ratings]
                    for cat, ratings in self.candidate_ranking.by_gap.items()
                },
                "applied": [asdict(r) for r in self.candidate_ranking.applied],
            },
            "risk_assessment": {
                "score": self.risk_assessment.score,
                "factors": list(self.risk_assessment.factors),
                "open_gaps": list(self.risk_assessment.open_gaps),
            },
            "origin": self.origin,
            "coaching": self.coaching.to_dict() if self.coaching else None,
            "sanity_report": (
                self.sanity_report.to_dict() if self.sanity_report is not None else None
            ),
        }

    def to_public_dict(self) -> dict:
        """Только данные для UI — без tier, rating, scores, служебных enum."""
        swaps = [
            {
                "drop": pe.drop,
                "pick": pe.pick,
                "reason": pe.reason,
            }
            for pe in self.decision_explanation.pick_explanations
            if pe.pick
        ]
        return {
            "intent": {
                "archetype": self.intent.archetype,
                "play_style": self.intent.play_style,
                "primary_win": self.intent.primary_win,
                "required_soft_checks": sorted(self.intent.required_soft_checks),
                "min_air_defense": self.intent.min_air_defense,
                "require_building": self.intent.require_building,
                "min_cycle_cards": self.intent.min_cycle_cards,
                "required_role_ids": sorted(self.intent.required_role_ids),
                "attack_bias": self.intent.attack_bias,
            },
            "game_plan": self.game_plan.to_dict(),
            "evaluation_report": (
                self.evaluation_report.to_dict() if self.evaluation_report is not None else None
            ),
            "balance_issues": {
                "hard": [],
                "soft": [],
                "messages": list(self.balance_issues.messages),
            },
            "improvement_plan": {
                "needed": self.improvement_plan.needed,
                "steps": [
                    {
                        "category": s.category,
                        "message": s.message,
                        "drop": s.drop,
                        "pick": s.pick,
                        "suggested_cards": list(s.suggested_cards),
                        "tier": None,
                        "rating": None,
                        "reason": s.reason,
                    }
                    for s in self.improvement_plan.steps
                ],
                "improved_deck": list(self.improvement_plan.improved_deck),
                "locked": list(self.improvement_plan.locked),
            },
            "decision_explanation": {
                "archetype": self.decision_explanation.archetype,
                "primary_win": self.decision_explanation.primary_win,
                "why_gaps": [],
                "why_picks": list(self.decision_explanation.why_picks),
                "rejected": [],
                "pick_explanations": [
                    {
                        "category": pe.category,
                        "pick": pe.pick,
                        "drop": pe.drop,
                        "reason": pe.reason,
                        "pros": [],
                        "rejected": [],
                    }
                    for pe in self.decision_explanation.pick_explanations
                ],
                "swaps": swaps,
            },
            "candidate_ranking": {"by_gap": {}, "applied": []},
            "risk_assessment": {
                "score": self.risk_assessment.score,
                "factors": list(self.risk_assessment.factors),
                "open_gaps": list(self.risk_assessment.open_gaps),
            },
            "origin": self.origin,
            "coaching": self.coaching.to_dict() if self.coaching else None,
            "sanity_report": (
                self.sanity_report.to_dict() if self.sanity_report is not None else None
            ),
        }

    def improvements_ui(self) -> list[dict]:
        """Формат DeckImprovementSuggestion — понятные шаги без внутренних метрик."""
        out: list[dict] = []
        seen: set[str] = set()
        for step in self.improvement_plan.steps:
            if step.category in seen:
                continue
            seen.add(step.category)
            suggested = [c for c in step.suggested_cards if c != step.pick]
            if step.pick:
                suggested = [step.pick, *suggested]
            message = step.message
            if step.drop and step.pick and step.reason:
                message = (
                    f"{_card_ru(step.drop)} → {_card_ru(step.pick)}. "
                    f"Причина: {step.reason}"
                )
            elif step.drop and step.pick:
                message = f"{_card_ru(step.drop)} → {_card_ru(step.pick)}"
            out.append({
                "category": step.category,
                "message": message,
                "suggested_cards": suggested[:4],
            })
        return out

    def to_improve_dict(
        self,
        *,
        original: list[str],
        issues: list[str],
        synergies: dict[str, list[str]] | None = None,
        avg_elixir: float | None = None,
    ) -> dict:
        improved = self.improvement_plan.improved_deck
        return {
            "needed": self.improvement_plan.needed,
            "original": list(original),
            "improved": list(improved),
            "issues": list(issues),
            "avg_elixir": avg_elixir if avg_elixir is not None else 0.0,
            "synergies": synergies or {},
            "locked": list(self.improvement_plan.locked),
            "game_plan": self.game_plan.to_dict() if len(improved) == 8 else None,
            "recommendation": self.to_public_dict(),
        }


def _balance_issues_for(deck: list[str], db, archetype: str) -> BalanceIssues:
    """Hard/soft только из EvaluationReport (Builder SoT) — без локального score."""
    report = evaluate_deck(deck, archetype=archetype, db=db)
    return _balance_issues_from_evaluation(report)


def _balance_issues_from_evaluation(report) -> BalanceIssues:
    """Срез BalanceIssues из уже посчитанного EvaluationReport (без повторного score)."""
    view = balance_issues_from_report(report)
    return BalanceIssues(hard=view.hard, soft=view.soft, messages=view.messages)


def _why_gaps_from_evaluation(report) -> list[str]:
    """Советы/пробелы только из актуального EvaluationReport."""
    msgs = list(report.hard_constraints.messages) + list(report.soft_constraints.messages)
    if not msgs:
        msgs = list(report.can_improve or report.weaknesses or ())
    out: list[str] = []
    seen: set[str] = set()
    for m in msgs:
        text = (m or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out[:16]


def _remarks_for_final_deck(
    lines: list[str],
    *,
    final_deck: list[str],
    original: list[str],
) -> list[str]:
    """Убрать советы, которые всё ещё описывают уже выкинутые карты как присутствующие.

    Строки с «→» (факт замены) оставляем. Имена карт только из final_deck / pick.
    """
    from bot.services.card_names_ru import card_name_ru

    dropped = set(original) - set(final_deck)
    if not dropped:
        return list(lines)

    dropped_labels = set()
    for name in dropped:
        dropped_labels.add(name.lower())
        ru = (card_name_ru(name) or "").strip()
        if ru:
            dropped_labels.add(ru.lower())
        short = (card_name_ru(name, short=True) or "").strip()
        if short:
            dropped_labels.add(short.lower())

    kept: list[str] = []
    for raw in lines:
        text = (raw or "").strip()
        if not text:
            continue
        if "→" in text or text.startswith("Добавить:"):
            kept.append(text)
            continue
        low = text.lower()
        if any(label and label in low for label in dropped_labels):
            continue
        kept.append(text)
    return kept


def _why_gap(gap: dict, intent: DeckIntent) -> str:
    cat = gap["category"]
    soft = _SOFT_FOR_CATEGORY.get(cat)
    msg = gap.get("message") or ""
    if soft and soft in SOFT_MESSAGES:
        return SOFT_MESSAGES[soft]
    if cat == "win_condition":
        return "Нет понятной главной угрозы для башни"
    if cat == "spells":
        return "Не хватает нормального набора заклинаний"
    return msg or "Есть слабое место в составе"


_CATEGORY_PRO: dict[str, str] = {
    "anti_air": "усиливает защиту воздуха",
    "splash": "усиливает контроль спама",
    "defense": "усиливает защиту",
    "point_target": "усиливает ответ на танки",
    "finishers": "усиливает добивание",
    "spells": "закрывает слот заклинания",
    "cycle": "поддерживает цикл колоды",
    "swarm": "усиливает контроль мелких юнитов",
    "support": "усиливает поддержку атаки",
    "win_condition": "усиливает главную угрозу для башни",
}


def _pick_pros(
    rating: CandidateRating,
    intent: DeckIntent,
    category: str,
    game_plan: GamePlan | None,
) -> list[str]:
    """Плюсы выбранной карты — по осям CandidateRating и категории gap."""
    from bot.services.card_data import card_has_role, is_building

    pros: list[str] = []
    cat_pro = _CATEGORY_PRO.get(category)
    if cat_pro:
        pros.append(cat_pro)

    # «Контрпуш» только если карта реально даёт давление после защиты,
    # а не чистое здание вроде Надгробия.
    pick = rating.card
    can_counterpush = (
        card_has_role(pick, "counterpush")
        or card_has_role(pick, "mini_tank")
        or (
            not is_building(pick)
            and category in {"anti_air", "support", "splash"}
            and rating.gameplan_fit >= 52
        )
    )
    if (
        intent.attack_bias >= 0.55
        and category in {"anti_air", "defense", "support", "splash", "point_target"}
        and rating.gameplan_fit >= 52
        and can_counterpush
    ):
        pros.append("усиливает контрпуш")

    if rating.deck_identity >= 55:
        pros.append(f"подходит под {intent.archetype}")
    if rating.primary_win_support >= 60 and intent.primary_win:
        pros.append(f"поддерживает {_card_ru(intent.primary_win)}")
    elif rating.primary_win_support >= 60:
        pros.append("поддерживает главную угрозу для башни")
    if rating.tempo_fit >= 60:
        pros.append("сохраняет средний эликсир")
    if rating.existing_synergy >= 62:
        pros.append("хорошо синергирует с колодой")
    if rating.secondary_combo_support >= 60:
        pros.append("усиливает ключевые комбинации")
    if rating.future_synergy >= 62:
        pros.append("открывает сильные связки дальше")
    if rating.role_overlap >= 68:
        pros.append("закрывает роль без вредного дубля")
    if rating.strategy_fit >= 58 and not cat_pro:
        pros.append(f"совместим со стратегией {intent.archetype}")
    if game_plan and rating.gameplan_fit >= 60 and game_plan.primary_threat:
        threat = game_plan.primary_threat
        if threat not in " | ".join(pros):
            pros.append("усиливает игровой план колоды")

    # Уникальные, порядок стабильный, без пустых.
    seen: set[str] = set()
    out: list[str] = []
    for p in pros:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out[:5] or ["улучшает баланс колоды"]


def _reject_reasons(
    winner: CandidateRating,
    loser: CandidateRating,
    intent: DeckIntent,
    category: str,
) -> list[str]:
    """Минусы отклонённого кандидата относительно победителя."""
    from bot.services.card_data import get_card_elixir

    reasons: list[str] = []
    w_elixir = get_card_elixir(winner.card)
    l_elixir = get_card_elixir(loser.card)

    if loser.tempo_fit + 8 <= winner.tempo_fit or l_elixir >= w_elixir + 1:
        if l_elixir >= w_elixir + 1 or loser.tempo_fit < 50:
            reasons.append("слишком дорогая")
        elif intent.min_cycle_cards >= 2:
            reasons.append("ломает цикл")
        else:
            reasons.append("хуже по темпу эликсира")
    elif intent.min_cycle_cards >= 2 and l_elixir >= 4 and w_elixir <= 3:
        reasons.append("ломает цикл")

    if loser.existing_synergy + 8 <= winner.existing_synergy:
        reasons.append("слабее синергия с колодой")

    if loser.primary_win_support + 8 <= winner.primary_win_support:
        reasons.append("хуже поддерживает главную угрозу для башни")

    if loser.deck_identity + 8 <= winner.deck_identity:
        reasons.append(f"хуже подходит под {intent.archetype}")

    if loser.role_overlap + 8 <= winner.role_overlap:
        if category in {"splash", "swarm"}:
            reasons.append("ухудшает защиту от мелких юнитов")
        elif category == "anti_air":
            reasons.append("слабее закрывает воздух")
        else:
            reasons.append("хуже баланс ролей")

    if loser.gameplan_fit + 8 <= winner.gameplan_fit:
        reasons.append("слабее усиливает игровой план")

    if loser.strategy_fit + 10 <= winner.strategy_fit:
        reasons.append("хуже подходит под стратегию")

    if loser.future_synergy + 10 <= winner.future_synergy and not reasons:
        reasons.append("меньше потенциала связок")

    if not reasons:
        if loser.total + 0.5 < winner.total:
            reasons.append(
                f"ниже общий рейтинг ({loser.total:.0f} vs {winner.total:.0f})",
            )
        else:
            reasons.append("чуть слабее по сумме факторов")

    seen: set[str] = set()
    out: list[str] = []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out[:2]


_PRO_PHRASE: dict[str, str] = {
    "усиливает защиту воздуха": "улучшает защиту воздуха",
    "усиливает контрпуш": "сохраняя давление в контратаке",
    "сохраняет средний эликсир": "сохраняя средний эликсир",
    "усиливает контроль спама": "улучшает контроль спама",
    "усиливает контроль мелких юнитов": "улучшает контроль мелких юнитов",
    "усиливает защиту": "улучшает защиту",
    "поддерживает цикл колоды": "поддерживая цикл колоды",
    "хорошо синергирует с колодой": "усиливая синергию колоды",
}


def build_user_reason(pros: list[str], *, category: str = "") -> str:
    """Одна понятная фраза для UI (без scores / tier)."""
    del category
    if not pros:
        return "Улучшает состав колоды под выбранную стратегию."

    mapped: list[str] = []
    for p in pros[:3]:
        key = p.strip().rstrip(".")
        phrase = _PRO_PHRASE.get(key, key)
        if phrase.startswith("поддерживает "):
            phrase = "поддерживая " + phrase[len("поддерживает "):]
        if phrase.startswith("подходит под "):
            phrase = "сохраняя стиль " + phrase[len("подходит под "):]
        mapped.append(phrase)

    # Предпочитаем «улучшает…» + деепричастие «сохраняя…» как в UX-примере.
    main = next((m for m in mapped if m.startswith("улучшает") or m.startswith("Улучшает")), mapped[0])
    others = [m for m in mapped if m != main]
    gerund = next((m for m in others if m.startswith("сохран") or m.startswith("усилив") or m.startswith("поддерж")), None)
    extra = [m for m in others if m != gerund]

    if main and main[0].islower():
        main = main[0].upper() + main[1:]

    parts = [main]
    if gerund:
        parts.append(gerund)
    elif extra:
        parts.append(extra[0])

    text = ", ".join(parts)
    if not text.endswith("."):
        text += "."
    return text


def format_user_swap(drop: str | None, pick: str, reason: str) -> list[str]:
    """Пользовательские строки для issues / why_picks."""
    if drop:
        lines = [f"{_card_ru(drop)} → {_card_ru(pick)}"]
    else:
        lines = [f"Добавить: {_card_ru(pick)}"]
    if reason:
        lines.append(f"Причина: {reason}")
    return lines


def build_pick_explanation(
    *,
    pick_rating: CandidateRating,
    alternatives: list[CandidateRating],
    intent: DeckIntent,
    category: str,
    drop: str | None,
    game_plan: GamePlan | None = None,
) -> PickExplanation:
    """Сохранить объяснение после выбора лучшей карты."""
    pros = _pick_pros(pick_rating, intent, category, game_plan)
    reason = build_user_reason(pros, category=category)
    rejected: list[RejectedCandidateExplanation] = []
    for alt in alternatives:
        if alt.card == pick_rating.card:
            continue
        rejected.append(
            RejectedCandidateExplanation(
                card=alt.card,
                reasons=_reject_reasons(pick_rating, alt, intent, category),
            ),
        )
        if len(rejected) >= 3:
            break
    return PickExplanation(
        category=category,
        pick=pick_rating.card,
        drop=drop,
        pros=pros,
        rejected=rejected,
        reason=reason,
    )


def flatten_pick_explanation(pe: PickExplanation) -> list[str]:
    """Пользовательский текст для issues (без debug / rejected / scores)."""
    return format_user_swap(pe.drop, pe.pick, pe.reason)


def _sort_gaps(gaps: list[dict]) -> list[dict]:
    return sorted(
        gaps,
        key=lambda g: (_GAP_PRIORITY.get(g["category"], 500), g["category"]),
    )


def _avoid_roles_for(category: str) -> frozenset[str] | None:
    if category == "anti_air":
        return frozenset({ROLE_AIR})
    if category == "point_target":
        return frozenset({ROLE_ANTI_TANK, ROLE_DEFENSIVE})
    if category == "defense":
        return frozenset({ROLE_BUILDING, ROLE_DEFENSIVE, ROLE_SPLASH})
    return None


def _rank_gap_candidates(
    deck: list[str],
    gap: dict,
    pool: set[str],
    locked: set[str],
    intent: DeckIntent,
    db,
    *,
    game_plan: GamePlan | None = None,
    exclude_picks: set[str] | None = None,
    limit: int = 5,
) -> list[CandidateRating]:
    category = gap["category"]
    role = _CATEGORY_ROLE.get(category)
    suggestions = gap.get("suggested_cards") or []
    soft_check = _SOFT_FOR_CATEGORY.get(category)
    drops = _list_replaceable(deck, locked, db)
    if not drops:
        return []
    candidates = _gather_replacement_candidates(
        deck,
        pool,
        role=role,
        suggestions=suggestions,
        db=db,
        soft_check=soft_check,
        include_full_pool=False,
    )
    if not candidates:
        candidates = _gather_replacement_candidates(
            deck,
            pool,
            role=role,
            suggestions=suggestions,
            db=db,
            soft_check=soft_check,
            include_full_pool=True,
        )
    if exclude_picks:
        candidates = [c for c in candidates if c not in exclude_picks]
    # card → (rating, drop) для tie-break с elixir delta
    best_by_card: dict[str, tuple[CandidateRating, str]] = {}
    for drop in drops[:4]:
        ranked = rank_candidates(
            deck,
            drop,
            candidates,
            intent,
            db,
            role=role,
            category=category,
            tier=SolutionTier.ACCEPTABLE,
            game_plan=game_plan,
        )
        for r in ranked[:limit]:
            prev = best_by_card.get(r.card)
            if prev is None or is_better_candidate(
                r,
                prev[0],
                challenger_drop=drop,
                incumbent_drop=prev[1],
                intent=intent,
                db=db,
            ):
                best_by_card[r.card] = (r, drop)
    ordered = sorted(
        best_by_card.values(),
        key=lambda pair: candidate_sort_key(pair[0], pair[1], intent, db),
    )
    return [r for r, _ in ordered[:limit]]


def _solve_gap(
    deck: list[str],
    pool: set[str],
    locked: set[str],
    gap: dict,
    intent: DeckIntent,
    db,
    *,
    game_plan: GamePlan | None = None,
    exclude_drops: set[str] | None = None,
    exclude_picks: set[str] | None = None,
) -> GapSolution | None:
    """Найти одну замену для gap на текущей (виртуальной) колоде."""
    category = gap["category"]
    if category == "focus":
        return None
    if not _gap_relevant_for_intent(category, intent):
        return None

    role = _CATEGORY_ROLE.get(category)
    avoid = _avoid_roles_for(category)
    suggestions = list(gap.get("suggested_cards") or [])
    if exclude_picks:
        suggestions = [c for c in suggestions if c not in exclude_picks]

    # Не выкидываем карты, которые уже поставили предыдущими шагами сценария.
    extra_locked = set(locked)
    if exclude_drops:
        extra_locked |= exclude_drops

    solution = search_gap_solution(
        deck,
        pool,
        extra_locked,
        intent,
        db,
        category=category,
        role=role,
        suggestions=suggestions,
        avoid_roles=avoid,
        game_plan=game_plan,
    )
    if solution is None:
        return None
    if exclude_picks and solution.pick in exclude_picks:
        return None
    if exclude_drops and solution.drop in exclude_drops:
        return None
    return solution


def _tornado_pierce_partners(deck: list[str]) -> list[str]:
    """Карты, которым Tornado даёт прострел по линии."""
    partners: list[str] = []
    if "Magic Archer" in deck:
        partners.append("Magic Archer")
    if "Executioner" in deck:
        partners.append("Executioner")
    return partners


def _tornado_pierce_advantage(partners: list[str]) -> str | None:
    if not partners:
        return None
    names = " и ".join(_card_ru(p) for p in partners)
    if len(partners) == 1:
        return (
            f"Позволяет {_card_ru(partners[0])} простреливать вражеских юнитов и башню"
        )
    return f"Позволяет {names} простреливать вражеских юнитов и башню"


_TORNADO_KING_TOWER_ADVANTAGE = (
    "Способно стягивать на ГЗ нетяжёлые вражеские карты (кроме карт с ускорением)"
)


def build_deck_coaching(
    intent: DeckIntent,
    game_plan: GamePlan,
    *,
    deck: list[str],
    synergy_notes: list[str] | None = None,
) -> DeckCoaching:
    """Сильные стороны / стиль / комбинации / советы — без замен карт."""
    strengths: list[str] = []
    if intent.primary_win:
        strengths.append(f"Главная угроза — {_card_ru(intent.primary_win)}")
    if intent.attack_bias >= 0.65:
        strengths.append("Сильное давление и потенциал контрпуша")
    elif intent.attack_bias <= 0.45:
        strengths.append("Контроль темпа и выгодные обмены")
    else:
        strengths.append("Гибкий баланс атаки и защиты")
    if intent.min_cycle_cards >= 2:
        strengths.append("Быстрый цикл для повторных атак")
    if intent.require_building:
        strengths.append("Опора на здания в плане игры")
    # synergy_notes уже показаны блоком «Синергия» — не дублируем в strengths.
    for key in game_plan.key_cards[:2]:
        if intent.primary_win and key == intent.primary_win:
            continue
        line = f"Ключевая карта — {_card_ru(key)}"
        if line not in strengths:
            strengths.append(line)

    tornado_partners = _tornado_pierce_partners(deck)
    pierce = _tornado_pierce_advantage(tornado_partners)
    tornado_extras: list[str] = []
    if "Tornado" in deck:
        if pierce:
            tornado_extras.append(pierce)
        tornado_extras.append(_TORNADO_KING_TOWER_ADVANTAGE)

    tips: list[str] = []
    seen_tips: list[str] = []

    def _add_tip(line: str) -> None:
        text = (line or "").strip()
        if not text:
            return
        key = text.casefold()
        for seen in seen_tips:
            if key == seen:
                return
            # Перефраз / вложенная копия (например primary_threat ⊂ how_to_win).
            if len(key) >= 28 and (key in seen or seen in key):
                return
        seen_tips.append(key)
        tips.append(text)

    if game_plan.when_to_attack:
        _add_tip(game_plan.when_to_attack)
    if game_plan.how_to_win:
        _add_tip(game_plan.how_to_win)
    if game_plan.primary_threat:
        _add_tip(game_plan.primary_threat)
    if not tips:
        tips.append(f"Играйте в стиле «{intent.play_style}» от сильных обменов.")

    combos_en = list(game_plan.core_combinations[:4])
    if "Tornado" in deck and tornado_partners:
        for partner in tornado_partners:
            combo_line = f"Tornado + {partner}"
            if combo_line not in combos_en and f"{partner} + Tornado" not in combos_en:
                combos_en.insert(0, combo_line)
    role_labels = {
        "win_condition": "главная угроза для башни",
        "big_spell": "закрывает добивание и защиту",
        "small_spell": "контролирует мелкий спам и поддерживает цикл",
        "air_defense": "закрывает воздушную защиту",
        "anti_tank": "останавливает тяжёлые цели",
        "anti_swarm": "закрывает наземный спам",
        "splash": "даёт сплеш против роя",
        "building": "даёт контроль через здание",
        "cycle": "ускоряет возврат ключевых карт",
        "counterpush": "усиливает контратаку",
        "support": "поддерживает основной пуш",
        "dps": "добавляет урон в защите и контратаке",
    }
    card_choices: list[dict[str, object]] = []
    used_combo_lines: set[str] = set()
    for card in deck:
        from bot.services.card_data import get_card_roles

        roles = sorted(get_card_roles(card))
        role_text = [role_labels[role] for role in roles if role in role_labels][:3]
        combo_en = next((line for line in combos_en if card in line), "")
        # roles уже показываются отдельно — не копируем первую роль в reason.
        reason = ""
        # Без реальной связки не подставляем заглушку; одну пару — только у одной карты.
        synergy = ""
        if combo_en and combo_en not in used_combo_lines:
            synergy = format_card_combo_ru(combo_en)
            used_combo_lines.add(combo_en)

        if card == "Tornado":
            advantages = [_TORNADO_KING_TOWER_ADVANTAGE]
            if pierce:
                advantages.insert(0, pierce)
                role_text = list(role_text)
                role_text.insert(0, "доп. преимущество: прострел с лучником/палачом")
            reason = ". ".join(advantages) + "."
            if pierce:
                partners_ru = " / ".join(_card_ru(p) for p in tornado_partners)
                synergy = f"{_card_ru('Tornado')} + {partners_ru}: {pierce}."
            else:
                synergy = _TORNADO_KING_TOWER_ADVANTAGE + "."

        # Tornado: reason/synergy могут пересекаться — оставляем одно.
        if reason and synergy and (
            reason.rstrip(".") == synergy.rstrip(".")
            or reason in synergy
            or synergy in reason
        ):
            synergy = ""

        card_choices.append({
            "card": _card_ru(card),
            "roles": role_text,
            "reason": reason[:1].upper() + reason[1:] if reason else reason,
            "synergy": synergy,
        })

    # Преимущества Tornado важнее generic-строк — всегда оставляем в strengths.
    base_cap = max(0, 6 - len(tornado_extras))
    merged_strengths = [s for s in strengths if s not in tornado_extras][:base_cap] + tornado_extras
    return DeckCoaching(
        strengths=merged_strengths,
        play_style=intent.play_style,
        # Комбинации = синергия; UI показывает их отдельным блоком, здесь не дублируем.
        key_combinations=[],
        usage_tips=tips[:4],
        card_choices=card_choices,
    )


def build_improvement_plan(
    deck: list[str],
    *,
    intent: DeckIntent,
    pool: set[str],
    db,
    locked: set[str] | None = None,
    max_steps: int = 6,
    allowed_categories: frozenset[str] | None = None,
) -> tuple[
    ImprovementPlan,
    CandidateRanking,
    list[str],
    list[str],
    list[str],
    list[PickExplanation],
]:
    """Единый сценарий улучшения для всех режимов.

    1) gaps на текущей колоде
    2) sort by priority
    3) решить ровно одну проблему
    4) виртуально применить замену
    5) пересчитать gaps; уже закрытые категории не трогать
    """
    virtual = list(deck)
    locked_now = set(locked or _locked_cards(virtual, db))
    arch = intent.archetype

    steps: list[ImprovementStep] = []
    ranking = CandidateRanking()
    why_gaps: list[str] = []
    why_picks: list[str] = []
    rejected: list[str] = []
    pick_explanations: list[PickExplanation] = []

    solved_categories: set[str] = set()
    protected_picks: set[str] = set()  # карты, поставленные сценарием — не дропать
    used_picks: set[str] = set()

    for _ in range(max_steps):
        if len(virtual) != 8:
            break

        intent = DeckIntentEngine.infer(virtual, archetype=arch)
        game_plan = build_game_plan(virtual, archetype=intent.archetype, intent=intent)
        locked_now = _locked_cards(virtual, db) | protected_picks

        raw_gaps = _collect_improvement_gaps(virtual, db, intent)
        gaps = [
            g for g in _sort_gaps(raw_gaps)
            if g["category"] not in solved_categories
            and (allowed_categories is None or g["category"] in allowed_categories)
        ]
        if not gaps:
            break

        # Первая (самая важная) незакрытая проблема — единственная цель шага.
        gap = gaps[0]
        if gap["category"] not in {w.split(":", 1)[0] for w in why_gaps}:
            why_gaps.append(_why_gap(gap, intent))

        gap_ranked = _rank_gap_candidates(
            virtual,
            gap,
            pool,
            locked_now,
            intent,
            db,
            game_plan=game_plan,
            exclude_picks=used_picks,
        )
        ranking.by_gap[gap["category"]] = gap_ranked

        solution = _solve_gap(
            virtual,
            pool,
            locked_now,
            gap,
            intent,
            db,
            game_plan=game_plan,
            exclude_drops=protected_picks,
            exclude_picks=used_picks,
        )
        if solution is None:
            rejected.append(
                f"{gap['category']}: нет совместимой замены на текущем шаге сценария",
            )
            # Не застреваем: помечаем категорию, чтобы попробовать следующую по приоритету.
            solved_categories.add(gap["category"])
            continue

        # Виртуально применяем замену.
        deck_before = list(virtual)
        virtual[virtual.index(solution.drop)] = solution.pick

        # Обязательно: EvaluationReport Builder на актуальном составе после swap.
        post_swap_report = evaluate_deck(virtual, archetype=intent.archetype, db=db)
        logger.debug(
            "post-swap EvaluationReport total=%.1f hard_ok=%s soft_issues=%s after %s→%s",
            post_swap_report.total_score,
            post_swap_report.hard_constraints.passed,
            list(post_swap_report.soft_constraints.issues),
            solution.drop,
            solution.pick,
        )

        protected_picks.add(solution.pick)
        used_picks.add(solution.pick)
        solved_categories.add(gap["category"])
        ranking.applied.append(solution.rating)

        suggested = list(gap.get("suggested_cards") or [])
        if solution.pick not in suggested:
            suggested = [solution.pick, *suggested][:4]

        # Добираем отклонённых на том же drop — в т.ч. suggested_cards.
        role = _CATEGORY_ROLE.get(gap["category"])
        suggested_for_rank = list(gap.get("suggested_cards") or [])
        cand_pool = _gather_replacement_candidates(
            deck_before,
            pool,
            role=role,
            suggestions=suggested_for_rank,
            db=db,
            soft_check=_SOFT_FOR_CATEGORY.get(gap["category"]),
            include_full_pool=True,
        )
        prior_picks = used_picks - {solution.pick}
        if prior_picks:
            cand_pool = [c for c in cand_pool if c not in prior_picks]
        ranked_full = rank_candidates(
            deck_before,
            solution.drop,
            cand_pool,
            intent,
            db,
            role=role,
            category=gap["category"],
            tier=SolutionTier.ANY_IMPROVEMENT,
            game_plan=game_plan,
        )
        suggested_set = set(suggested_for_rank)
        preferred = [
            r for r in ranked_full
            if r.card in suggested_set and r.card != solution.pick
        ]
        others = [
            r for r in ranked_full
            if r.card not in suggested_set and r.card != solution.pick
        ]
        seen = {solution.pick}
        merged: list[CandidateRating] = []
        for r in [*preferred, *gap_ranked, *others]:
            if r.card in seen:
                continue
            merged.append(r)
            seen.add(r.card)
            if len(merged) >= 3:
                break

        pe = build_pick_explanation(
            pick_rating=solution.rating,
            alternatives=merged,
            intent=intent,
            category=gap["category"],
            drop=solution.drop,
            game_plan=game_plan,
        )
        pick_explanations.append(pe)
        why_picks.extend(flatten_pick_explanation(pe))

        # Текст шага = проблема, которую закрыли этим swap (+ reason).
        # Не подставляем post_swap.can_improve: там уже СЛЕДУЮЩие дыры другой колоды.
        step_message = pe.reason or gap["message"]

        steps.append(
            ImprovementStep(
                category=gap["category"],
                message=step_message,
                drop=solution.drop,
                pick=solution.pick,
                suggested_cards=suggested,
                tier=solution.tier.value,
                rating=solution.rating,
                reason=pe.reason,
            ),
        )
        logger.debug(
            "swap %s → %s category=%s tier=%s candidate_total=%.2f eval_total=%.1f reason=%s",
            solution.drop,
            solution.pick,
            gap["category"],
            solution.tier.value,
            solution.rating.total,
            post_swap_report.total_score,
            pe.reason,
        )

    # Открытые gaps после сценария — без независимых suggested_cards.
    final_intent = DeckIntentEngine.infer(virtual, archetype=arch)
    swapped_cats = {s.category for s in steps if s.drop and s.pick}
    for gap in _sort_gaps(_collect_improvement_gaps(virtual, db, final_intent)):
        if gap["category"] in swapped_cats:
            continue
        if any(s.category == gap["category"] for s in steps):
            continue
        steps.append(
            ImprovementStep(
                category=gap["category"],
                message=gap["message"],
                drop=None,
                pick=None,
                suggested_cards=[],
                tier=None,
                rating=None,
            ),
        )
        cat_prefix = f"{gap['category']}:"
        if not any(w.startswith(cat_prefix) for w in why_gaps):
            why_gaps.append(_why_gap(gap, final_intent))

    locked_final = sorted(_locked_cards(virtual, db) | protected_picks)
    plan = ImprovementPlan(
        needed=any(s.drop and s.pick for s in steps),
        steps=steps,
        improved_deck=list(virtual),
        locked=locked_final,
    )
    return plan, ranking, why_gaps, why_picks, rejected, pick_explanations


def _risk_assessment(
    report,
    game_plan: GamePlan,
    open_gaps: list[str],
) -> RiskAssessment:
    """Риск только из EvaluationReport.total_score + тексты отчёта — без своего score."""
    balance = _balance_issues_from_evaluation(report)
    factors: list[str] = []
    factors.extend(balance.messages)
    for note in report.can_improve or report.weaknesses or ():
        if note and note not in factors:
            factors.append(note)
    for w in game_plan.critical_weaknesses:
        if w not in factors:
            factors.append(w)
    for g in open_gaps:
        line = f"открытый gap: {g}"
        if line not in factors:
            factors.append(line)

    # Risk = инверсия Builder total_score (SoT), не локальная формула весов.
    score = max(0.0, min(100.0, 100.0 - float(report.total_score)))
    return RiskAssessment(score=round(score, 1), factors=factors[:12], open_gaps=list(open_gaps))


class RecommendationEngine:
    """Единая точка рекомендаций по колоде."""

    @staticmethod
    def analyze(
        deck: list[str],
        *,
        archetype: str | None = None,
        pool: set[str] | None = None,
        apply_swaps: bool = True,
        arena_id: int | None = None,
        trophies: int | None = None,
        preferred_cards: list[str] | None = None,
        use_cache: bool = True,
        origin: DeckOrigin | str = DeckOrigin.PLAYER,
        builder_score: float | None = None,
        synergy_notes: list[str] | None = None,
    ) -> RecommendationResult:
        """Объясняет колоду либо улучшает явную пользовательскую колоду.

        ``origin=builder`` всегда explanation-only: выбор карт уже завершён
        Builder и здесь не пересматривается. Поиск замен разрешён лишь когда
        пользователь явно запросил ``apply_swaps=True`` для своей колоды.
        """
        from bot.services.counter_engine import _get_arena_pool

        origin_val = (
            origin.value if isinstance(origin, DeckOrigin) else str(origin or DeckOrigin.PLAYER.value)
        )
        if origin_val not in {DeckOrigin.PLAYER.value, DeckOrigin.BUILDER.value}:
            origin_val = DeckOrigin.PLAYER.value
        is_builder = origin_val == DeckOrigin.BUILDER.value

        original = list(deck)
        cache_key = recommendation_cache_key(
            original,
            archetype=archetype,
            apply_swaps=apply_swaps,
            arena_id=arena_id,
            trophies=trophies,
            preferred_cards=preferred_cards,
            pool=pool,
            origin=origin_val,
            builder_score=builder_score,
        )
        if use_cache:
            cached = recommendation_cache.get(cache_key)
            if cached is not None:
                return cached

        db = get_database()

        if len(original) != 8:
            from bot.services.deck_evaluator.models import empty_evaluation_report

            intent = DeckIntentEngine.infer(original, archetype=archetype or "Meta")
            empty_plan = GamePlan(
                how_to_win="",
                primary_threat="",
                when_to_attack="",
                key_cards=[],
                core_combinations=[],
                critical_weaknesses=["Нужна полная колода из 8 карт"],
            )
            evaluation = empty_evaluation_report(original)
            balance = _balance_issues_from_evaluation(evaluation)
            result = RecommendationResult(
                intent=intent,
                game_plan=empty_plan,
                balance_issues=balance,
                improvement_plan=ImprovementPlan(
                    needed=False,
                    steps=[],
                    improved_deck=original,
                    locked=[],
                ),
                decision_explanation=DecisionExplanation(
                    archetype=intent.archetype,
                    primary_win=intent.primary_win,
                    why_gaps=_why_gaps_from_evaluation(evaluation),
                    why_picks=[],
                    rejected=["Нужна полная колода из 8 карт"],
                    pick_explanations=[],
                ),
                candidate_ranking=CandidateRanking(),
                risk_assessment=_risk_assessment(evaluation, empty_plan, []),
                origin=origin_val,
                coaching=None,
                evaluation_report=evaluation,
            )
            if use_cache:
                recommendation_cache.put(cache_key, result)
            return result

        work = list(original)
        card_pool = set(pool or _get_arena_pool(arena_id, trophies))
        card_pool.update(work)
        card_pool.update(preferred_cards or [])

        is_improver = origin_val == DeckOrigin.PLAYER.value and apply_swaps
        prep_notes: list[str] = []
        if is_improver:
            _apply_arena_fixes(work, card_pool, prep_notes)

        locked = _locked_cards(work, db)
        arch = archetype or _detect_archetype(list(locked) or work)
        intent = DeckIntentEngine.infer(work, archetype=arch)

        # RecommendationEngine не является вторым Builder.
        # Замены существуют только в явном режиме Improve My Deck.
        allow_swaps = is_improver
        if is_improver:
            gaps0 = _collect_improvement_gaps(work, db, intent)
            if gaps0 and not prep_notes:
                _fix_elixir_if_needed(work, card_pool, locked, prep_notes, intent)
                locked = _locked_cards(work, db)
                intent = DeckIntentEngine.infer(work, archetype=arch)

        if allow_swaps:
            plan, ranking, _plan_why_gaps, why_picks, rejected, pick_explanations = (
                build_improvement_plan(
                    work,
                    intent=intent,
                    pool=card_pool,
                    db=db,
                    locked=locked,
                    max_steps=6,
                )
            )
            del _plan_why_gaps  # финальные gaps — только из EvaluationReport ниже
        else:
            plan = ImprovementPlan(
                needed=False,
                steps=[],
                improved_deck=list(work),
                locked=sorted(locked),
            )
            ranking = CandidateRanking()
            why_gaps, why_picks, rejected, pick_explanations = [], [], [], []

        why_picks = [*prep_notes, *why_picks]

        improved = list(plan.improved_deck)
        if is_improver:
            locked_set = set(plan.locked)
            _trim_spell_and_win_limits(improved, locked_set, db)
            plan = ImprovementPlan(
                needed=improved != original or plan.needed,
                steps=plan.steps,
                improved_deck=improved,
                locked=sorted(_locked_cards(improved, db) | locked_set),
            )

        # ── Final SoT: всегда одна колода = improved_deck (или original, если trim сломал 8).
        final_deck = (
            list(plan.improved_deck) if len(plan.improved_deck) == 8 else list(original)
        )
        if final_deck != list(plan.improved_deck):
            plan = ImprovementPlan(
                needed=plan.needed,
                steps=plan.steps,
                improved_deck=final_deck,
                locked=plan.locked,
            )

        intent = DeckIntentEngine.infer(final_deck, archetype=arch)
        game_plan = build_game_plan(
            final_deck, archetype=intent.archetype, intent=intent,
        )

        from bot.services.deck_sanity_validator import validate_deck_sanity

        # Единственный итоговый EvaluationReport — по final_deck.
        # Нет отдельного «original_evaluation», который мог бы просочиться в result.
        evaluation = evaluate_deck(final_deck, archetype=intent.archetype, db=db)
        balance = _balance_issues_from_evaluation(evaluation)
        why_gaps = _why_gaps_from_evaluation(evaluation)
        risk = _risk_assessment(evaluation, game_plan, [])

        # playable / hard-fail — только из evaluation final_deck, не из plan.needed.
        deck_playable = is_good_deck(report=evaluation)

        sanity = validate_deck_sanity(
            final_deck,
            intent=intent,
            game_plan=game_plan,
            evaluation=evaluation,
            archetype=intent.archetype,
            db=db,
            balance_hard=list(balance.hard),
            balance_messages=list(balance.messages),
            risk_score=risk.score,
        )

        coaching: DeckCoaching | None = None
        from bot.services.card_data import secondary_pressure_in
        from bot.services.player_remarks import build_player_remarks

        eval_good = list(evaluation.whats_good or evaluation.strengths or ())
        eval_improve = _remarks_for_final_deck(
            list(evaluation.can_improve or evaluation.weaknesses or ()),
            final_deck=final_deck,
            original=original,
        )
        # Факт уже применённых замен (стрелки) — не путать с «ещё нужны замены».
        swap_lines = [line for line in why_picks if "→" in line or line.startswith("Добавить:")]

        # Swaps уже внутри final_deck: has_mandatory_swaps только если итог всё ещё плох
        # и остались нерешённые шаги без pick (дыры без замены).
        unresolved = any(s.drop is None and s.pick is None for s in plan.steps)
        has_mandatory_swaps = (not deck_playable) and unresolved

        if is_builder and sanity.passed and deck_playable:
            coaching = build_deck_coaching(
                intent,
                game_plan,
                deck=final_deck,
                synergy_notes=synergy_notes,
            )
            remarks = build_player_remarks(
                strengths=coaching.strengths[:4],
                improvements=eval_improve[:3],
                deck_playable=deck_playable,
                has_mandatory_swaps=False,
                primary_win=intent.primary_win,
                secondary_pressure=secondary_pressure_in(final_deck),
            )
            why_picks = remarks.as_issue_lines()
            if coaching.play_style:
                why_picks = [f"Стиль игры: {coaching.play_style}", *why_picks]
        else:
            remarks = build_player_remarks(
                strengths=eval_good or [
                    f"Главная угроза — {intent.primary_win}" if intent.primary_win else ""
                ],
                improvements=[*swap_lines, *eval_improve][:6],
                deck_playable=deck_playable,
                has_mandatory_swaps=has_mandatory_swaps,
                primary_win=intent.primary_win,
                secondary_pressure=secondary_pressure_in(final_deck),
                final_override=(
                    evaluation.final_recommendation
                    if evaluation.final_recommendation and deck_playable
                    else None
                ),
            )
            why_picks = remarks.as_issue_lines()
            if swap_lines and plan.needed and "Что можно улучшить" not in why_picks:
                why_picks = [
                    *why_picks[:-2],
                    "Что можно улучшить",
                    *swap_lines[:4],
                    "Итоговая рекомендация",
                    remarks.final_recommendation,
                ]

        end_gaps = _collect_improvement_gaps(final_deck, db, intent) if is_improver else []

        open_cats = [g["category"] for g in end_gaps]
        explanation = DecisionExplanation(
            archetype=intent.archetype,
            primary_win=intent.primary_win,
            why_gaps=why_gaps[:16],
            why_picks=why_picks[:48],
            rejected=rejected[:16],
            pick_explanations=pick_explanations[:8],
        )
        risk = _risk_assessment(evaluation, game_plan, open_cats)

        result = RecommendationResult(
            intent=intent,
            game_plan=game_plan,
            balance_issues=balance,
            improvement_plan=plan,
            decision_explanation=explanation,
            candidate_ranking=ranking,
            risk_assessment=risk,
            origin=origin_val,
            coaching=coaching,
            evaluation_report=evaluation,
            sanity_report=sanity,
        )
        if use_cache:
            recommendation_cache.put(cache_key, result)
        return result

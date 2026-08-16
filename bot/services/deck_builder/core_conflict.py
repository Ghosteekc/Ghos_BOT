"""Core Conflict Analysis — fallback, когда полное ядро из 4 карт не даёт качественной колоды.

Для каждой карты Core: убрать → собрать колоду → EvaluationReport.total_score.
Конфликтующая = та, чьё удаление даёт максимальный прирост качества.
Основной Core пользователем не меняется — только предлагается альтернатива.
"""

from __future__ import annotations

from dataclasses import dataclass

from bot.services.card_names_ru import card_name_ru
from bot.services.deck_builder.builder import (
    BuildResult,
    _core_primary_win,
    _detect_archetype,
    build_deck_from_core,
)
from bot.services.deck_builder.loader import get_database

# Выше validation floor (52): «действительно качественная» сборка Stage 1.
MIN_QUALITY_TOTAL = 62.0


def evaluation_score(result: BuildResult | None) -> float:
    """Итоговая оценка колоды из EvaluationReport (единый DeckEvaluator)."""
    if result is None or result.evaluation is None:
        return 0.0
    return float(result.evaluation.total_score)


def is_quality_result(result: BuildResult | None) -> bool:
    return evaluation_score(result) >= MIN_QUALITY_TOTAL


def filter_quality_results(results: list[BuildResult]) -> list[BuildResult]:
    return [r for r in results if is_quality_result(r)]


@dataclass(frozen=True)
class DropTrial:
    removed: str
    reduced_core: list[str]
    result: BuildResult | None
    score: float


@dataclass(frozen=True)
class CoreConflictReport:
    conflicting_card: str
    reason: str
    baseline_score: float
    alternative_score: float
    quality_gain: float
    alternative_core: list[str]
    alternative_result: BuildResult
    drop_scores: dict[str, float]
    message: str


def _conflict_reason(
    removed: str,
    full_core: list[str],
    alt: BuildResult,
) -> str:
    remaining = [c for c in full_core if c != removed]
    primary = _core_primary_win(remaining) or _core_primary_win(full_core)
    removed_ru = card_name_ru(removed)
    if primary and primary != removed:
        primary_ru = card_name_ru(primary)
        arch = alt.archetype or _detect_archetype(remaining)
        return (
            f"{removed_ru} значительно ограничивает жизнеспособные архетипы "
            f"вокруг {primary_ru} (без неё сильная сборка: {arch})."
        )
    arch_full = _detect_archetype(full_core)
    arch_alt = alt.archetype or _detect_archetype(remaining)
    if arch_full != arch_alt:
        return (
            f"{removed_ru} конфликтует с направлением ядра "
            f"({arch_full} → без карты: {arch_alt})."
        )
    return (
        f"Удаление «{removed_ru}» сильнее всего повышает качество итоговой колоды "
        f"при сохранении остальных карт ядра."
    )


def _public_message(removed: str, reason: str) -> str:
    removed_ru = card_name_ru(removed)
    return (
        "Не удалось построить действительно сильную колоду вокруг всех четырёх "
        f"выбранных карт.\n\n"
        f"Наиболее конфликтующая карта: {removed_ru}\n\n"
        f"Причина: {reason}\n\n"
        "Если заменить только эту карту, можно получить более сильную колоду "
        "(альтернативный вариант ниже). Основная сборка на полном ядре не меняется."
    )


def analyze_core_conflict(
    core: list[str],
    pool: set[str] | None = None,
    *,
    baseline_score: float = 0.0,
) -> CoreConflictReport | None:
    """Leave-one-out по Core: максимальный прирост score после удаления карты."""
    if len(core) != 4 or len(set(core)) != 4:
        return None

    base_pool = set(pool) if pool is not None else None

    trials: list[DropTrial] = []
    for removed in core:
        reduced = [c for c in core if c != removed]
        # Конфликтующая карта не должна вернуться филлером из пула.
        if base_pool is None:
            trial_pool = set(get_database().cards.keys()) - {removed}
        else:
            trial_pool = set(base_pool) - {removed}
        result: BuildResult | None = None
        score = -1.0
        try:
            result = build_deck_from_core(reduced, pool=trial_pool)
            # Защита: не засчитываем сборку, куда removed снова попал как filler.
            if result is not None and removed in result.deck:
                result = None
                score = -1.0
            else:
                score = evaluation_score(result)
        except ValueError:
            result = None
            score = -1.0
        trials.append(
            DropTrial(
                removed=removed,
                reduced_core=reduced,
                result=result,
                score=score,
            ),
        )

    viable = [t for t in trials if t.result is not None and t.score >= 0]
    if not viable:
        return None

    # Максимальный прирост относительно baseline; при равенстве — выше абсолютный score.
    best = max(
        viable,
        key=lambda t: (t.score - baseline_score, t.score, t.removed),
    )
    # Нет смысла предлагать альтернативу, если выигрыша почти нет.
    gain = best.score - baseline_score
    if gain < 4.0 and best.score < MIN_QUALITY_TOTAL:
        return None
    if best.result is None:
        return None
    if best.removed in best.result.deck:
        return None

    reason = _conflict_reason(best.removed, core, best.result)
    return CoreConflictReport(
        conflicting_card=best.removed,
        reason=reason,
        baseline_score=round(baseline_score, 1),
        alternative_score=round(best.score, 1),
        quality_gain=round(gain, 1),
        alternative_core=list(best.reduced_core),
        alternative_result=best.result,
        drop_scores={t.removed: round(t.score, 1) for t in trials},
        message=_public_message(best.removed, reason),
    )

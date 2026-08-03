"""DeckEvaluator — единый слой оценки готовой колоды из 8 карт.

Только читает состав. Не меняет карты, не предлагает свапы.
Внутри переиспользует хелперы осей (balance, synergy, win_plan, elixir…).
Публичный контракт и единственный итоговый score — EvaluationReport.
ScoreBreakdown.total не влияет на total_score / ранжирование Builder.
"""

from __future__ import annotations

from bot.services.card_data import get_card_elixir
from bot.services.deck_analyzer import analyze_deck
from bot.services.deck_builder.archetype_detect import detect_archetype_from_cards
from bot.services.deck_builder.balance import (
    compute_score_breakdown,
    count_role,
    has_role,
)
from bot.services.deck_builder.constants import (
    ROLE_AIR,
    ROLE_ANTI_SWARM,
    ROLE_ANTI_TANK,
    ROLE_BIG_SPELL,
    ROLE_BUILDING,
    ROLE_CYCLE,
    ROLE_DEFENSIVE,
    ROLE_SMALL_SPELL,
    ROLE_SPLASH,
)
from bot.services.deck_builder.loader import DeckDatabase, get_database
from bot.services.deck_builder.win_plan_check import evaluate_win_plan
from bot.services.deck_evaluator.models import (
    AxisScore,
    ConstraintScore,
    EvaluationReport,
    empty_evaluation_report,
)
from bot.services.deck_game_plan import build_game_plan
from bot.services.deck_intent import DeckIntentEngine
from bot.services.deck_synergy import evaluate_deck_synergy
from bot.services.elixir_efficiency import analyze_elixir_efficiency

_HARD_MESSAGES: dict[str, str] = {
    "deck_size": "Колода должна содержать ровно 8 карт",
    "duplicate_cards": "В колоде есть дубликаты карт",
    "missing_core": "В колоде нет всех карт ядра",
    "win_condition": "Нет атакующего win-condition",
    "too_many_wins": "Слишком много win-condition",
    "too_many_spells": "Слишком много заклинаний",
}

_SOFT_MESSAGES: dict[str, str] = {
    "big_spell": "Нет большого заклинания для добивания / защиты",
    "small_spell": "Нет малого заклинания для цикла и контроля спама",
    "air_defense": "Недостаточно anti-air против Balloon / Lava",
    "anti_tank": "Слабый ответ на тяжёлые танки",
    "anti_swarm": "Слабая защита от спама",
    "building": "Нет здания при осадном / контрольном плане",
    "cycle": "Недостаточно карт цикла для стратегии",
    "elixir": "Средний эликсир вне комфортного диапазона архетипа",
}

_WIN_PLAN_LABELS: dict[str, str] = {
    "primary_win": "Нет явного primary win-condition",
    "secondary_threat": "Слабая вторичная угроза",
    "constant_pressure": "Нет постоянного давления / цикла",
    "finishing_power": "Слабое добивание башни",
    "building_break": "Слабый ответ на здания",
    "counterattack": "Слабая контратака",
}

# Веса итогового total_score (сумма = 1.0).
_TOTAL_WEIGHTS: dict[str, float] = {
    "synergy": 0.18,
    "win_plan": 0.14,
    "role_coverage": 0.12,
    "matchup_coverage": 0.12,
    "spell_balance": 0.10,
    "cycle_quality": 0.10,
    "archetype_fit": 0.10,
    "elixir_profile": 0.08,
    "soft_constraints": 0.06,
}


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(value)))


def _messages_for(issues: list[str], table: dict[str, str]) -> tuple[str, ...]:
    return tuple(table.get(key, key) for key in issues)


def _constraint_score(issues: list[str], *, hard: bool) -> ConstraintScore:
    n = len(issues)
    if hard:
        score = 100.0 if n == 0 else max(0.0, 100.0 - n * 28.0)
        table = _HARD_MESSAGES
    else:
        score = 100.0 if n == 0 else max(0.0, 100.0 - n * 14.0)
        table = _SOFT_MESSAGES
    return ConstraintScore(
        passed=n == 0,
        score=_clamp(score),
        issues=tuple(issues),
        messages=_messages_for(issues, table),
    )


def _role_coverage_axis(
    deck: list[str],
    db: DeckDatabase,
    required_role_ids: frozenset[str] | set[str],
) -> AxisScore:
    stats = analyze_deck(deck)
    cheap = sum(
        1
        for c in deck
        if (db.get_card(c).elixir if db.get_card(c) else get_card_elixir(c)) <= 2
    )
    role_ok: dict[str, bool] = {
        "win_condition": bool(stats.win_conditions),
        "big_spell": has_role(deck, db, ROLE_BIG_SPELL),
        "small_spell": has_role(deck, db, ROLE_SMALL_SPELL),
        "air": count_role(deck, db, ROLE_AIR) >= 1,
        "anti_air": count_role(deck, db, ROLE_AIR) >= 1,
        "air_defense": count_role(deck, db, ROLE_AIR) >= 1,
        "anti_tank": has_role(deck, db, ROLE_ANTI_TANK),
        "anti_swarm": has_role(deck, db, ROLE_ANTI_SWARM) or has_role(deck, db, ROLE_SPLASH),
        "splash": has_role(deck, db, ROLE_SPLASH) or has_role(deck, db, ROLE_ANTI_SWARM),
        "defense": has_role(deck, db, ROLE_DEFENSIVE) or has_role(deck, db, ROLE_BUILDING),
        "building": has_role(deck, db, ROLE_BUILDING),
        "defensive": has_role(deck, db, ROLE_DEFENSIVE),
        "cycle": count_role(deck, db, ROLE_CYCLE) >= 1 or cheap >= 2,
        "dps": has_role(deck, db, "dps"),
        "tank": has_role(deck, db, "tank"),
        "support": has_role(deck, db, "support"),
    }

    required = set(required_role_ids) if required_role_ids else {
        "win_condition", "big_spell", "small_spell", "anti_air", "anti_swarm", "cycle",
    }
    checkable = {r for r in required if r in role_ok} or {
        "win_condition", "big_spell", "small_spell", "anti_air", "anti_swarm", "cycle",
    }
    hits = sum(1 for r in checkable if role_ok.get(r))
    score = 100.0 * hits / max(len(checkable), 1)
    missing = sorted(r for r in checkable if not role_ok.get(r))
    present = sorted(r for r in checkable if role_ok.get(r))
    notes = tuple(f"Нет роли: {m}" for m in missing[:4])
    return AxisScore(
        score=_clamp(score),
        details={
            "present": present,
            "required": sorted(checkable),
            "missing": missing,
            "win_conditions": list(stats.win_conditions),
            "spells": list(stats.spells),
            "buildings": list(stats.buildings),
        },
        notes=notes,
    )


def _cycle_quality_axis(
    deck: list[str],
    db: DeckDatabase,
    *,
    soft_issues: list[str],
    elixir_report,
    win_plan,
) -> AxisScore:
    cycle_n = count_role(deck, db, ROLE_CYCLE)
    cheap = sum(
        1
        for c in deck
        if (db.get_card(c).elixir if db.get_card(c) else get_card_elixir(c)) <= 2
    )
    effective = int(getattr(elixir_report, "effective_cycle", 0) or 0)
    cheap_rotation = int(getattr(elixir_report, "cheap_rotation", 0) or 0)

    score = 45.0
    score += min(cycle_n, 3) * 10.0
    score += min(cheap, 3) * 6.0
    if effective and effective <= 10:
        score += 18.0
    elif effective and effective <= 12:
        score += 10.0
    elif effective and effective >= 16:
        score -= 12.0
    score += cheap_rotation * 0.12
    if "cycle" in soft_issues:
        score -= 18.0
    if win_plan.constant_pressure:
        score += 8.0
    notes: list[str] = []
    if "cycle" in soft_issues:
        notes.append(_SOFT_MESSAGES["cycle"])
    elif cycle_n + cheap >= 3:
        notes.append("Достаточно карт для быстрого цикла")
    return AxisScore(
        score=_clamp(score),
        details={
            "cycle_cards": cycle_n,
            "cheap_cards": cheap,
            "effective_cycle": effective,
            "cheap_rotation": cheap_rotation,
        },
        notes=tuple(notes[:3]),
    )


def _win_plan_axis(win_plan, game_plan) -> AxisScore:
    flags = (
        ("primary_win", win_plan.primary_win),
        ("secondary_threat", win_plan.secondary_threat),
        ("constant_pressure", win_plan.constant_pressure),
        ("finishing_power", win_plan.finishing_power),
        ("building_break", win_plan.building_break),
        ("counterattack", win_plan.counterattack),
    )
    hits = sum(1 for _, ok in flags if ok)
    score = 100.0 * hits / len(flags)
    missing = win_plan.missing()
    notes = tuple(_WIN_PLAN_LABELS.get(m, m) for m in missing[:4])
    if not notes and game_plan.how_to_win:
        notes = (game_plan.how_to_win,)
    return AxisScore(
        score=_clamp(score),
        details={
            "complete": win_plan.complete,
            "primary_card": win_plan.primary_card,
            "flags": {name: ok for name, ok in flags},
            "how_to_win": game_plan.how_to_win,
            "primary_threat": game_plan.primary_threat,
        },
        notes=notes,
    )


def _synergy_axis(deck: list[str], axis_synergy: float) -> AxisScore:
    """Синергия EvaluationReport: deck_synergy + ось ролей/ядра (axis helper)."""
    evaluation = evaluate_deck_synergy(deck)
    score = evaluation.score * 0.65 + float(axis_synergy) * 0.35
    return AxisScore(
        score=_clamp(score),
        details={
            "deck_synergy": evaluation.score,
            "axis_synergy": round(axis_synergy, 1),
            "breakdown": {
                "core": evaluation.breakdown.core,
                "role": evaluation.breakdown.role,
                "game_plan": evaluation.breakdown.game_plan,
                "conflict": evaluation.breakdown.conflict,
            },
        },
        notes=tuple(evaluation.notes[:5]),
    )


def _matchup_coverage_axis(
    *,
    anti_air: float,
    anti_swarm: float,
    defense: float,
    offense: float,
    opponent: list[str] | None,
    user_deck: list[str],
) -> AxisScore:
    """Покрытие типовых угроз без оппонента; при наличии — оценка матчапа.

    MatchupEvaluation.score = сложность для user (выше = хуже).
    Coverage = 100 − difficulty.
    """
    defensive = (
        float(anti_air) * 0.34
        + float(anti_swarm) * 0.33
        + float(defense) * 0.33
    )
    notes: list[str] = []
    details: dict = {
        "anti_air": round(anti_air, 1),
        "anti_swarm": round(anti_swarm, 1),
        "defense": round(defense, 1),
        "offense": round(offense, 1),
    }
    score = defensive
    if opponent and len(opponent) == 8:
        from bot.services.matchup_evaluation import evaluate_matchup

        matchup = evaluate_matchup(user_deck, opponent)
        coverage = 100.0 - float(matchup.score)
        score = coverage * 0.55 + defensive * 0.45
        details["matchup_difficulty"] = round(matchup.score, 1)
        details["matchup_rating"] = matchup.rating
        notes = list(matchup.reasons[:3]) + list(matchup.advantages[:2])
    else:
        if anti_air < 50:
            notes.append("Слабое покрытие воздуха")
        if anti_swarm < 55:
            notes.append("Слабое покрытие спама")
        if defense < 50:
            notes.append("Слабая общая защита")
    return AxisScore(score=_clamp(score), details=details, notes=tuple(notes[:5]))


def _elixir_axis(elixir_report, axis_elixir: float) -> AxisScore:
    """Профиль эликсира: efficiency-отчёт + ось archetype elixir range."""
    profile_pts = (
        int(elixir_report.cheap_rotation)
        + int(elixir_report.punish_speed)
        + int(elixir_report.recovery_speed)
        + int(elixir_report.double_elixir_power)
        + int(elixir_report.overtime_strength)
    ) / 5.0
    score = float(axis_elixir) * 0.45 + profile_pts * 0.55
    return AxisScore(
        score=_clamp(score),
        details={
            "average_cost": elixir_report.average_cost,
            "effective_cycle": elixir_report.effective_cycle,
            "elixir_profile": elixir_report.elixir_profile,
            "cheap_rotation": elixir_report.cheap_rotation,
            "punish_speed": elixir_report.punish_speed,
            "recovery_speed": elixir_report.recovery_speed,
            "double_elixir_power": elixir_report.double_elixir_power,
            "overtime_strength": elixir_report.overtime_strength,
            "axis_elixir": round(axis_elixir, 1),
        },
        notes=tuple(elixir_report.explanations[:4]),
    )


def _compose_total(
    *,
    hard: ConstraintScore,
    soft: ConstraintScore,
    role_coverage: AxisScore,
    spell_balance: AxisScore,
    cycle_quality: AxisScore,
    win_plan: AxisScore,
    synergy: AxisScore,
    matchup_coverage: AxisScore,
    archetype_fit: AxisScore,
    elixir_profile: AxisScore,
) -> float:
    """Итог только из осей EvaluationReport — без якоря к ScoreBreakdown.total."""
    parts = {
        "synergy": synergy.score,
        "win_plan": win_plan.score,
        "role_coverage": role_coverage.score,
        "matchup_coverage": matchup_coverage.score,
        "spell_balance": spell_balance.score,
        "cycle_quality": cycle_quality.score,
        "archetype_fit": archetype_fit.score,
        "elixir_profile": elixir_profile.score,
        "soft_constraints": soft.score,
    }
    total = sum(parts[k] * _TOTAL_WEIGHTS[k] for k in _TOTAL_WEIGHTS)
    if not hard.passed:
        total = min(total, 42.0)
        total -= 8.0 * len(hard.issues)
    return round(_clamp(total), 1)


def _strengths_weaknesses(
    *,
    hard: ConstraintScore,
    soft: ConstraintScore,
    win_plan: AxisScore,
    synergy: AxisScore,
    matchup_coverage: AxisScore,
    game_plan,
    coaching_strengths: list[str] | None,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    strengths: list[str] = []
    for s in coaching_strengths or []:
        if s and s not in strengths:
            strengths.append(s)
    for note in synergy.notes:
        if note and note not in strengths and len(strengths) < 6:
            strengths.append(note)
    if win_plan.score >= 80 and win_plan.details.get("how_to_win"):
        line = str(win_plan.details["how_to_win"])
        if line not in strengths:
            strengths.append(line)

    weaknesses: list[str] = []
    weaknesses.extend(hard.messages)
    weaknesses.extend(soft.messages)
    for w in game_plan.critical_weaknesses:
        if w and w not in weaknesses:
            weaknesses.append(w)
    weaknesses.extend(n for n in win_plan.notes if n not in weaknesses)
    weaknesses.extend(n for n in matchup_coverage.notes if n not in weaknesses)

    reasons: list[str] = []
    for bucket in (strengths[:3], weaknesses[:4], soft.messages[:2]):
        for line in bucket:
            if line and line not in reasons:
                reasons.append(line)

    return tuple(strengths[:6]), tuple(weaknesses[:8]), tuple(reasons[:10])


class DeckEvaluator:
    """Единая точка оценки готовой колоды. Не мутирует состав."""

    @staticmethod
    def evaluate(
        deck: list[str],
        *,
        core: list[str] | None = None,
        archetype: str | None = None,
        opponent: list[str] | None = None,
        db: DeckDatabase | None = None,
    ) -> EvaluationReport:
        """Оценить колоду из 8 карт и вернуть неизменяемый EvaluationReport."""
        cards = list(deck)
        if len(cards) != 8 or len(set(cards)) != len(cards):
            return empty_evaluation_report(cards)

        database = db or get_database()
        arch = archetype or detect_archetype_from_cards(cards)
        core_cards = list(core) if core else []

        intent = DeckIntentEngine.infer(cards, archetype=arch)
        # Axis helpers из balance — входные оси EvaluationReport.
        # axes.total не используется (ранжирование только по EvaluationReport).
        axes = compute_score_breakdown(cards, database, core_cards, arch)
        win_plan = evaluate_win_plan(cards, database, arch, intent=intent)
        game_plan = build_game_plan(cards, archetype=arch, intent=intent)
        elixir_report = analyze_elixir_efficiency(cards)

        hard = _constraint_score(list(axes.hard_issues), hard=True)
        soft = _constraint_score(list(axes.soft_issues), hard=False)
        role_coverage = _role_coverage_axis(cards, database, intent.required_role_ids)
        spell_balance = AxisScore(
            score=_clamp(axes.spell_balance),
            details={
                "has_big": has_role(cards, database, ROLE_BIG_SPELL),
                "has_small": has_role(cards, database, ROLE_SMALL_SPELL),
            },
            notes=tuple(
                m for key, m in (
                    ("big_spell", _SOFT_MESSAGES["big_spell"]),
                    ("small_spell", _SOFT_MESSAGES["small_spell"]),
                )
                if key in soft.issues
            ),
        )
        cycle_quality = _cycle_quality_axis(
            cards,
            database,
            soft_issues=list(soft.issues),
            elixir_report=elixir_report,
            win_plan=win_plan,
        )
        win_plan_axis = _win_plan_axis(win_plan, game_plan)
        synergy = _synergy_axis(cards, axes.synergy)
        matchup_coverage = _matchup_coverage_axis(
            anti_air=axes.anti_air,
            anti_swarm=axes.anti_swarm,
            defense=axes.defense,
            offense=axes.offense,
            opponent=opponent,
            user_deck=cards,
        )
        archetype_fit = AxisScore(
            score=_clamp(axes.archetype_fit),
            details={"archetype": arch, "play_style": intent.play_style},
            notes=(f"Архетип: {arch}",),
        )
        elixir_profile = _elixir_axis(elixir_report, axes.elixir)

        coaching_strengths: list[str] = []
        try:
            from bot.services.recommendation_engine import build_deck_coaching

            coaching = build_deck_coaching(
                intent,
                game_plan,
                deck=cards,
                synergy_notes=list(synergy.notes),
            )
            coaching_strengths = list(coaching.strengths)
        except Exception:
            coaching_strengths = []

        strengths, weaknesses, reasons = _strengths_weaknesses(
            hard=hard,
            soft=soft,
            win_plan=win_plan_axis,
            synergy=synergy,
            matchup_coverage=matchup_coverage,
            game_plan=game_plan,
            coaching_strengths=coaching_strengths,
        )

        total = _compose_total(
            hard=hard,
            soft=soft,
            role_coverage=role_coverage,
            spell_balance=spell_balance,
            cycle_quality=cycle_quality,
            win_plan=win_plan_axis,
            synergy=synergy,
            matchup_coverage=matchup_coverage,
            archetype_fit=archetype_fit,
            elixir_profile=elixir_profile,
        )

        return EvaluationReport(
            deck=tuple(cards),
            archetype=arch,
            hard_constraints=hard,
            soft_constraints=soft,
            role_coverage=role_coverage,
            spell_balance=spell_balance,
            cycle_quality=cycle_quality,
            win_plan=win_plan_axis,
            synergy=synergy,
            matchup_coverage=matchup_coverage,
            archetype_fit=archetype_fit,
            elixir_profile=elixir_profile,
            total_score=total,
            strengths=strengths,
            weaknesses=weaknesses,
            reasons=reasons,
        )

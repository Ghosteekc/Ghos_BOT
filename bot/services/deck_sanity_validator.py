"""Deck Sanity Validator — независимая проверка колоды после Builder.

Ghosteek не оправдывает ошибки конструктора. Validator выполняется
после сборки и до генерации coaching / текста «как играть».
Если есть критические проблемы — честный вердикт, без плана игры.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from bot.services.card_data import (
    card_has_role,
    get_card_elixir,
    is_tower_threat,
    primary_wins_in,
)
from bot.services.deck_builder.constants import (
    ARCHETYPE_ELIXIR,
    DEFAULT_ELIXIR_MAX,
    ROLE_AIR,
    ROLE_ANTI_TANK,
    ROLE_BIG_SPELL,
    ROLE_DPS,
    ROLE_SMALL_SPELL,
    ROLE_TANK,
    ROLE_WIN,
)
from bot.services.deck_builder.loader import DeckDatabase, get_database
from bot.services.deck_builder.win_plan_check import evaluate_win_plan
from bot.services.deck_evaluator import EvaluationReport
from bot.services.deck_evaluator.evaluator import DeckEvaluator
from bot.services.deck_game_plan import GamePlan, build_game_plan
from bot.services.deck_intent import DeckIntent, DeckIntentEngine

# Известные комбо с двумя win-condition — не считаем дублем ролей.
_COMBO_WIN_PAIRS = frozenset({
    frozenset({"Lava Hound", "Balloon"}),
})

# Роли, избыток которых ломает баланс (порог → duplicate).
_DUPLICATE_ROLE_LIMITS: dict[str, int] = {
    ROLE_BIG_SPELL: 2,
    ROLE_SMALL_SPELL: 3,
    ROLE_WIN: 3,
    ROLE_TANK: 2,
}


@dataclass(frozen=True)
class SanityIssue:
    code: str
    severity: str  # critical | warning
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "severity": self.severity, "message": self.message}


@dataclass(frozen=True)
class DeckSanityReport:
    """Результат независимой проверки перед объяснением Ghosteek."""

    passed: bool
    checks: dict[str, bool]
    issues: tuple[SanityIssue, ...] = ()
    avg_elixir: float = 0.0

    @property
    def critical_issues(self) -> list[SanityIssue]:
        return [i for i in self.issues if i.severity == "critical"]

    @property
    def critical_messages(self) -> list[str]:
        return [i.message for i in self.critical_issues]

    def coach_verdict(self) -> str:
        msgs = self.critical_messages
        if msgs:
            return msgs[0]
        if self.issues:
            return self.issues[0].message
        return "Сборка выглядит стабильной."

    def coach_why(self) -> str:
        msgs = self.critical_messages
        if len(msgs) >= 2:
            return msgs[1]
        if self.critical_issues:
            return "Builder мог ошибиться — не буду оправдывать слабую сборку."
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": dict(self.checks),
            "issues": [i.to_dict() for i in self.issues],
            "critical_messages": self.critical_messages,
            "avg_elixir": round(self.avg_elixir, 2),
            "coach_verdict": self.coach_verdict(),
            "coach_why": self.coach_why(),
        }


def _issue(code: str, message: str, *, critical: bool = True) -> SanityIssue:
    return SanityIssue(
        code=code,
        severity="critical" if critical else "warning",
        message=message,
    )


def _avg_elixir(deck: list[str]) -> float:
    if not deck:
        return 0.0
    return sum(get_card_elixir(c) for c in deck) / len(deck)


def _role_cards(deck: list[str], role: str) -> list[str]:
    return [c for c in deck if card_has_role(c, role)]


def _has_attack_win(deck: list[str]) -> bool:
    return any(is_tower_threat(c) for c in deck)


def _allows_combo_wins(deck: list[str]) -> bool:
    wins = {c for c in deck if is_tower_threat(c) or card_has_role(c, ROLE_WIN)}
    return any(pair <= wins for pair in _COMBO_WIN_PAIRS)


def _check_structure(
    deck: list[str],
    intent: DeckIntent,
    *,
    win_plan_ok: bool,
) -> tuple[dict[str, bool], list[SanityIssue]]:
    checks: dict[str, bool] = {}
    issues: list[SanityIssue] = []

    has_win = _has_attack_win(deck) or win_plan_ok
    checks["win_condition"] = has_win
    if not has_win:
        issues.append(_issue(
            "win_condition",
            "Эта сборка выглядит нестабильной. Не удалось найти полноценную win condition. "
            "Я бы пересобрал её.",
        ))

    air_n = len(_role_cards(deck, ROLE_AIR))
    need_air = max(1, intent.min_air_defense) if intent.min_air_defense > 0 else 1
    # Anti-air всегда критичен для лестницы — даже Meta.
    has_air = air_n >= need_air or air_n >= 1
    checks["anti_air"] = has_air
    if not has_air:
        issues.append(_issue(
            "anti_air",
            "Колода слишком слабо защищается от воздуха.",
        ))

    has_tank_killer = bool(_role_cards(deck, ROLE_ANTI_TANK))
    # Для архетипов без явного anti_tank в soft — warning, иначе critical.
    tank_required = "anti_tank" in intent.required_soft_checks
    checks["tank_killer"] = has_tank_killer
    if not has_tank_killer:
        issues.append(_issue(
            "tank_killer",
            "Нет надёжного способа останавливать тяжёлые танки.",
            critical=tank_required,
        ))

    has_dps = bool(_role_cards(deck, ROLE_DPS))
    checks["dps"] = has_dps
    if not has_dps:
        issues.append(_issue(
            "dps",
            "Не хватает стабильного DPS для защиты и контратаки.",
            critical=False,
        ))

    has_small = bool(_role_cards(deck, ROLE_SMALL_SPELL))
    small_required = "small_spell" in intent.required_soft_checks
    checks["small_spell"] = has_small
    if not has_small:
        issues.append(_issue(
            "small_spell",
            "Нет маленького заклинания — колода будет проигрывать мелкому спаму."
            if small_required
            else "Нет маленького заклинания — добивать мелкий спам будет сложно.",
            critical=small_required,
        ))

    has_big = bool(_role_cards(deck, ROLE_BIG_SPELL))
    checks["big_spell"] = has_big
    if not has_big:
        issues.append(_issue(
            "big_spell",
            "В колоде отсутствует стабильный способ добивать башню.",
        ))
    lo, hi = ARCHETYPE_ELIXIR.get(intent.archetype, (2.6, DEFAULT_ELIXIR_MAX))
    avg = _avg_elixir(deck)
    # Слишком тяжёлая для архетипа или абсолютный потолок.
    elixir_ok = avg <= (hi + 0.35) and avg <= (DEFAULT_ELIXIR_MAX + 0.4)
    checks["avg_elixir"] = elixir_ok
    if not elixir_ok:
        issues.append(_issue(
            "avg_elixir",
            f"Средний эликсир слишком высокий ({avg:.1f}) — сборка будет вязнуть в темпе.",
        ))

    # Конфликтующие роли — только две независимые Primary WC.
    conflict = False
    conflict_msg = ""
    attack_wins = primary_wins_in(deck)
    if len(attack_wins) >= 2 and not _allows_combo_wins(deck):
        conflict = True
        names = " и ".join(attack_wins[:2])
        conflict_msg = (
            f"В колоде две главные угрозы ({names}) — непонятно, от чего строить атаки. "
            "Оставьте одну основную win condition; chip и давление можно держать рядом."
        )
    tanks = _role_cards(deck, ROLE_TANK)
    heavy_tanks = [c for c in tanks if get_card_elixir(c) >= 5]
    siege = any(c in {"X-Bow", "Mortar"} for c in deck)
    if siege and heavy_tanks and intent.archetype not in {"Royal Giant", "Beatdown"}:
        conflict = True
        conflict_msg = (
            "Осада и тяжёлый танк тянут колоду в разные планы — сборка выглядит нестабильной."
        )
    if intent.archetype in {"Cycle", "Log Bait", "Split Lane"} and len(heavy_tanks) >= 1:
        conflict = True
        conflict_msg = (
            f"Тяжёлый танк не сочетается со стилем «{intent.play_style}» — роли конфликтуют."
        )
    checks["conflicting_roles"] = not conflict
    if conflict:
        issues.append(_issue("conflicting_roles", conflict_msg or "В колоде конфликтующие роли."))

    # Дубликаты ролей
    dup = False
    dup_msgs: list[str] = []
    for role, limit in _DUPLICATE_ROLE_LIMITS.items():
        cards = _role_cards(deck, role)
        if role == ROLE_WIN and (_allows_combo_wins(deck) or len(primary_wins_in(deck)) <= 1):
            # Primary + secondary pressure — не «слишком много win condition».
            continue
        if len(cards) >= limit:
            dup = True
            label = {
                ROLE_BIG_SPELL: "больших заклинаний",
                ROLE_SMALL_SPELL: "маленьких заклинаний",
                ROLE_WIN: "главных угроз башне",
                ROLE_TANK: "танков",
            }.get(role, role)
            dup_msgs.append(f"слишком много {label} ({len(cards)})")
    checks["duplicate_roles"] = not dup
    if dup:
        issues.append(_issue(
            "duplicate_roles",
            "Состав несбалансирован: " + ", ".join(dup_msgs) + ".",
            critical=False,
        ))

    return checks, issues


def _check_intent(deck: list[str], intent: DeckIntent) -> tuple[bool, SanityIssue | None]:
    missing: list[str] = []
    if intent.primary_win and intent.primary_win not in deck:
        missing.append(f"нет главной угрозы «{intent.primary_win}»")

    role_map = {
        "win_condition": ROLE_WIN,
        "big_spell": ROLE_BIG_SPELL,
        "small_spell": ROLE_SMALL_SPELL,
        "anti_air": ROLE_AIR,
        "air_defense": ROLE_AIR,
        "anti_tank": ROLE_ANTI_TANK,
        "dps": ROLE_DPS,
        "tank": ROLE_TANK,
    }
    for role_id in intent.required_role_ids:
        role = role_map.get(role_id, role_id)
        if role_id == "splash":
            if not any(card_has_role(c, "splash") or card_has_role(c, "anti_swarm") for c in deck):
                missing.append("нет splash / anti-swarm")
            continue
        if role and not any(card_has_role(c, role) for c in deck):
            # win_condition уже покрыт отдельным check — не дублируем как critical intent
            if role_id == "win_condition":
                continue
            missing.append(f"нет роли {role_id}")

    if intent.min_cycle_cards > 0:
        cycle_n = sum(
            1 for c in deck if card_has_role(c, "cycle") or get_card_elixir(c) <= 2
        )
        if cycle_n < intent.min_cycle_cards:
            missing.append("недостаточно cycle-карт под Intent")

    if missing:
        return False, _issue(
            "intent_mismatch",
            "Сборка не соответствует заявленному стилю игры: " + "; ".join(missing[:3]) + ".",
        )
    return True, None


def _check_game_plan(game_plan: GamePlan) -> tuple[bool, list[SanityIssue]]:
    issues: list[SanityIssue] = []
    ok = True
    if not (game_plan.how_to_win or "").strip():
        ok = False
        issues.append(_issue(
            "game_plan_mismatch",
            "Нет понятного плана победы — объяснять такую колоду рано.",
        ))
    threat = (game_plan.primary_threat or "").strip()
    if threat.startswith("Нет явной") or not threat:
        ok = False
        issues.append(_issue(
            "game_plan_mismatch",
            "В колоде отсутствует стабильный способ добивать башню.",
        ))
    for w in game_plan.critical_weaknesses[:2]:
        ok = False
        issues.append(_issue(
            "game_plan_mismatch",
            f"План игры указывает на дыру: {w}.",
        ))
    return ok, issues


def _check_evaluation(evaluation: EvaluationReport) -> tuple[bool, list[SanityIssue]]:
    issues: list[SanityIssue] = []
    ok = True
    if not evaluation.hard_constraints.passed:
        ok = False
        # Только игровые формулировки — без кодов ограничений.
        detail = (evaluation.hard_constraints.messages[0]
                  if evaluation.hard_constraints.messages
                  else "в составе есть критичные дыры")
        issues.append(_issue(
            "evaluation_fail",
            f"Состав пока нестабилен: {detail}",
        ))
    if evaluation.total_score < 48.0:
        ok = False
        issues.append(_issue(
            "evaluation_fail",
            "Сборка пока слабая для стабильной лестницы — не хватает согласованного плана.",
        ))
    if evaluation.win_plan.score < 35.0:
        ok = False
        issues.append(_issue(
            "evaluation_fail",
            "Не видно рабочего способа стабильно давить башню.",
        ))
    # Слабый anti-air из matchup_coverage
    details = evaluation.matchup_coverage.details or {}
    anti_air = float(details.get("anti_air", evaluation.matchup_coverage.score))
    if anti_air < 40.0:
        ok = False
        issues.append(_issue(
            "anti_air",
            "Колода слишком слабо защищается от воздуха.",
        ))
    return ok, issues


def _check_recommendation(
    *,
    balance_hard: list[str] | None,
    balance_messages: list[str] | None,
    risk_score: float | None,
) -> tuple[bool, list[SanityIssue]]:
    issues: list[SanityIssue] = []
    ok = True
    hard = list(balance_hard or [])
    # Слишком много независимых WC и т.п. — только если hard реально остался.
    structural = [k for k in hard if k not in {"too_many_wins"}]
    # too_many_wins после Primary/Secondary уже редкий; если всплыл — мягкий warning.
    if "too_many_wins" in hard and not structural:
        issues.append(_issue(
            "recommendation_fail",
            "В колоде несколько главных угроз башне — атаки будут размытыми. "
            "Оставьте одну основную win condition.",
            critical=False,
        ))
    elif structural:
        ok = False
        msg = (balance_messages or [None])[0]
        if not msg or "too_many" in (msg or "").lower() or "win-condition" in (msg or "").lower():
            msg = "В составе есть критичные дыры — сначала закройте их, потом шлифуйте детали."
        issues.append(_issue("recommendation_fail", msg))
    if risk_score is not None and risk_score >= 75.0:
        ok = False
        msgs = balance_messages or []
        detail = msgs[0] if msgs else "высокий риск провала плана"
        from bot.services.player_remarks import looks_internal, sanitize_player_line

        clean = sanitize_player_line(detail) if not looks_internal(detail) else None
        issues.append(_issue(
            "recommendation_fail",
            clean
            or "План колоды пока рискованный — усильте ответы на типовые угрозы лестницы.",
        ))
    return ok, issues


def validate_deck_sanity(
    deck: list[str],
    *,
    intent: DeckIntent | None = None,
    game_plan: GamePlan | None = None,
    evaluation: EvaluationReport | None = None,
    archetype: str | None = None,
    db: DeckDatabase | None = None,
    balance_hard: list[str] | None = None,
    balance_messages: list[str] | None = None,
    risk_score: float | None = None,
) -> DeckSanityReport:
    """Независимая проверка колоды. Не мутирует состав.

    Порядок: структура ролей → Intent → GamePlan → EvaluationReport → Recommendation signals.
    """
    cards = [c for c in deck if c]
    if len(cards) != 8:
        issue = _issue(
            "win_condition",
            "Эта сборка выглядит нестабильной. Нужна полная колода из 8 карт.",
        )
        return DeckSanityReport(
            passed=False,
            checks={"deck_size": False},
            issues=(issue,),
            avg_elixir=_avg_elixir(cards),
        )

    database = db or get_database()
    arch = archetype or (intent.archetype if intent else None)
    resolved_intent = intent or DeckIntentEngine.infer(cards, archetype=arch or "Meta")
    resolved_plan = game_plan or build_game_plan(
        cards, archetype=resolved_intent.archetype, intent=resolved_intent,
    )
    resolved_eval = evaluation or DeckEvaluator.evaluate(
        cards, archetype=resolved_intent.archetype, db=database,
    )
    win_plan = evaluate_win_plan(
        cards, database, resolved_intent.archetype, intent=resolved_intent,
    )

    checks, issues = _check_structure(cards, resolved_intent, win_plan_ok=win_plan.primary_win)

    intent_ok, intent_issue = _check_intent(cards, resolved_intent)
    checks["intent_match"] = intent_ok
    if intent_issue:
        issues.append(intent_issue)

    plan_ok, plan_issues = _check_game_plan(resolved_plan)
    checks["game_plan_match"] = plan_ok
    issues.extend(plan_issues)

    eval_ok, eval_issues = _check_evaluation(resolved_eval)
    checks["evaluation_match"] = eval_ok
    # anti_air мог уже добавиться — дедуп по code+message
    issues.extend(eval_issues)

    rec_ok, rec_issues = _check_recommendation(
        balance_hard=balance_hard,
        balance_messages=balance_messages,
        risk_score=risk_score,
    )
    checks["recommendation_match"] = rec_ok
    issues.extend(rec_issues)

    # Дедупликация сообщений
    seen: set[str] = set()
    unique: list[SanityIssue] = []
    for item in issues:
        key = f"{item.code}:{item.message}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    critical = [i for i in unique if i.severity == "critical"]
    return DeckSanityReport(
        passed=not critical,
        checks=checks,
        issues=tuple(unique),
        avg_elixir=_avg_elixir(cards),
    )


def sanity_payload_from_data(data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Достать sanity_report dict из tool / recommendation / deck entry payload."""
    if not isinstance(data, dict):
        return None
    direct = data.get("sanity_report")
    if isinstance(direct, dict) and "passed" in direct:
        return direct
    rec = data.get("recommendation")
    if isinstance(rec, dict):
        sr = rec.get("sanity_report")
        if isinstance(sr, dict) and "passed" in sr:
            return sr
    decks = data.get("decks")
    if isinstance(decks, list) and decks and isinstance(decks[0], dict):
        first = decks[0]
        sr = first.get("sanity_report")
        if isinstance(sr, dict) and "passed" in sr:
            return sr
        nested = first.get("recommendation")
        if isinstance(nested, dict):
            sr = nested.get("sanity_report")
            if isinstance(sr, dict) and "passed" in sr:
                return sr
    return None


def sanity_from_mapping(data: Mapping[str, Any] | None) -> DeckSanityReport | None:
    """Восстановить отчёт из dict (tool / API payload)."""
    if not isinstance(data, dict) or not data:
        return None
    if "passed" not in data:
        return None
    raw_issues = data.get("issues") or []
    issues: list[SanityIssue] = []
    for item in raw_issues:
        if not isinstance(item, dict):
            continue
        issues.append(SanityIssue(
            code=str(item.get("code") or "unknown"),
            severity=str(item.get("severity") or "critical"),
            message=str(item.get("message") or ""),
        ))
    if not issues and data.get("critical_messages"):
        for msg in data["critical_messages"]:
            issues.append(_issue("evaluation_fail", str(msg)))
    return DeckSanityReport(
        passed=bool(data.get("passed")),
        checks=dict(data.get("checks") or {}),
        issues=tuple(issues),
        avg_elixir=float(data.get("avg_elixir") or 0.0),
    )

"""Battle Coach — коучинг по итогам боя на доступных данных API.

CR API не отдаёт реплей / таймлайн ходов. Все «моменты» — выводы из:
составов колод, счёта по коронам, длительности, матчапа, тактики и плана.
Если фактов мало — честно пишем insufficient / data_notes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from bot.services.card_matchups import counters_in_deck
from bot.services.card_names_ru import card_name_ru
from bot.services.deck_analyzer import analyze_deck
from bot.services.elixir_efficiency import ElixirEfficiencyReport
from bot.services.match_difficulty import MatchDifficultyReport
from bot.services.match_plan import MatchPlanReport
from bot.services.matchup_evaluation import rating_for
from bot.services.tactical_matchup import TacticalMatchupReport

_DATA_LIMIT_NOTE = (
    "Clash Royale API не отдаёт реплей и таймлайн действий. "
    "Моменты ниже выведены из составов колод, счёта, длительности и матчапа — "
    "без выдуманных событий боя."
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
            self.main_mistakes
            or (self.best_moment and self.best_moment.usable)
            or (self.turning_point and self.turning_point.usable)
            or (self.outcome_decider and self.outcome_decider.usable)
            or (self.danger_moment and self.danger_moment.usable)
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


def _build_mistakes(
    *,
    won: bool,
    user_deck: list[str],
    opponent_deck: list[str],
    threats: list[str],
    missing_counters: list[str],
    tactical: TacticalMatchupReport | None,
    match_plan: MatchPlanReport | None,
    match_difficulty: MatchDifficultyReport | None,
    matchup_score: float,
    low_impact: list[Any],
    user_stats,
) -> list[CoachInsight]:
    mistakes: list[CoachInsight] = []

    # 1) Пробелы контры по угрозам WC (факт состава).
    for threat in threats[:3]:
        strong, partial = counters_in_deck(threat, user_deck)
        if strong:
            continue
        if partial:
            mistakes.append(
                CoachInsight(
                    title=f"Слабая контра на {_ru(threat)}",
                    text=(
                        f"В колоде нет сильного ответа на {_ru(threat)} — только частичный "
                        f"({', '.join(_ru(c) for c in partial[:2])}). "
                        + (
                            "В этом матче это повышало риск по башням."
                            if not won
                            else "Победа состоялась несмотря на этот пробел."
                        )
                    ),
                    evidence=[
                        f"угроза соперника: {_ru(threat)}",
                        f"частичные ответы: {', '.join(_ru(c) for c in partial[:3])}",
                    ],
                    confidence="high",
                )
            )
        else:
            rec = [c for c in missing_counters if c not in user_deck][:3]
            mistakes.append(
                CoachInsight(
                    title=f"Нет контры на {_ru(threat)}",
                    text=(
                        f"На {_ru(threat)} в вашей колоде нет зафиксированной контры. "
                        + (
                            f"Кандидаты по базе матчапов: {', '.join(_ru(c) for c in rec)}."
                            if rec
                            else "Усилить ответ на эту угрозу."
                        )
                    ),
                    evidence=[f"угроза: {_ru(threat)}", "сильных/частичных контр в колоде нет"],
                    confidence="high",
                )
            )
        if len(mistakes) >= 3:
            return mistakes[:3]

    # 2) Тактические «worst mistakes» — это правила состава, не факты хода.
    if tactical:
        for line in tactical.worst_mistakes[:3]:
            mistakes.append(
                CoachInsight(
                    title="Типичная ошибка ценности в этом матчапе",
                    text=line,
                    evidence=["выведено из пересечения составов (tactical matchup)"],
                    confidence="medium",
                )
            )
            if len(mistakes) >= 3:
                return mistakes[:3]

    # 3) Avoid из match plan.
    if match_plan:
        for line in match_plan.avoid[:2]:
            mistakes.append(
                CoachInsight(
                    title="Чего избегать в этом матчапе",
                    text=line,
                    evidence=["match plan по составам колод"],
                    confidence="medium",
                )
            )
            if len(mistakes) >= 3:
                return mistakes[:3]

    # 4) Тяжёлый цикл vs лёгкий соперник.
    opp_stats = analyze_deck(opponent_deck)
    if user_stats.avg_elixir > opp_stats.avg_elixir + 1.0:
        mistakes.append(
            CoachInsight(
                title="Медленный цикл эликсира",
                text=(
                    f"Средний эликсир вашей колоды {user_stats.avg_elixir} против "
                    f"{opp_stats.avg_elixir} у соперника — он чаще возвращал win-condition."
                ),
                evidence=[
                    f"avg elixir user={user_stats.avg_elixir}",
                    f"avg elixir opp={opp_stats.avg_elixir}",
                ],
                confidence="high",
            )
        )
        if len(mistakes) >= 3:
            return mistakes[:3]

    # 5) Карты «мало повлияли» — только как риск состава.
    if low_impact and len(mistakes) < 3:
        names = [_ru(getattr(c, "name", str(c))) for c in low_impact[:2]]
        mistakes.append(
            CoachInsight(
                title="Карты слабо стыкуются с матчапом",
                text=(
                    f"{', '.join(names)} плохо закрывают угрозы соперника по составу — "
                    "в бою они с высокой вероятностью давали меньше ценности."
                ),
                evidence=[f"low-impact кандидаты: {', '.join(names)}"],
                confidence="medium",
            )
        )
        if len(mistakes) >= 3:
            return mistakes[:3]

    # 6) Поражение без дыр в контрах: честные риски матчапа (не выдуманные ходы).
    if not won and len(mistakes) < 3:
        if match_difficulty and match_difficulty.reasons:
            mistakes.append(
                CoachInsight(
                    title="Сложный матчап по составу",
                    text=(
                        f"{match_difficulty.reasons[0]} "
                        "Бумажная контра могла быть, но давление соперника всё равно выше — "
                        "ошибка, скорее всего, в тайминге/эликсире, который API не показывает."
                    ),
                    evidence=[
                        f"difficulty: {match_difficulty.rating} ({match_difficulty.difficulty})",
                        match_difficulty.reasons[0],
                    ],
                    confidence="medium",
                )
            )
        elif matchup_score >= 55:
            mistakes.append(
                CoachInsight(
                    title="Невыгодный матчап",
                    text=(
                        f"Матчап {matchup_score:.0f}/100 ({rating_for(round(matchup_score))}). "
                        "Даже при наличии ответов колода соперника давила сильнее — "
                        "конкретный промах хода восстановить нельзя."
                    ),
                    evidence=[f"matchup={matchup_score:.0f}"],
                    confidence="low",
                )
            )
        if len(mistakes) >= 3:
            return mistakes[:3]

        if tactical and tactical.pressure_points:
            mistakes.append(
                CoachInsight(
                    title="Не удержали ключевое давление",
                    text=(
                        f"По составу опасная линия давления: {tactical.pressure_points[0]} "
                        "В поражении это наиболее вероятная зона, где размен пошёл не в вашу пользу."
                    ),
                    evidence=[tactical.pressure_points[0], "tactical pressure_points"],
                    confidence="medium",
                )
            )
            if len(mistakes) >= 3:
                return mistakes[:3]

        if tactical and tactical.critical_interactions:
            mistakes.append(
                CoachInsight(
                    title="Критическое взаимодействие матчапа",
                    text=(
                        f"{tactical.critical_interactions[0]} "
                        "Если этот размен проигран, исход по коронам часто решается здесь."
                    ),
                    evidence=[tactical.critical_interactions[0]],
                    confidence="medium",
                )
            )

    return mistakes[:3]


def _build_best_moment(
    *,
    won: bool,
    tactical: TacticalMatchupReport | None,
    match_plan: MatchPlanReport | None,
    user_key_cards: list[Any],
    crown_score: str,
) -> CoachInsight:
    evidence: list[str] = []
    if match_plan and match_plan.win_condition_window:
        evidence.append(f"окно атаки: {match_plan.win_condition_window}")
        text = (
            f"Лучшее окно по составу — {match_plan.win_condition_window}. "
            + (
                "Исход партии согласуется с реализацией этого окна."
                if won
                else "Поражение могло случиться, если окно не использовали или сорвали."
            )
        )
        if tactical and tactical.best_openings:
            text += f" Открытие: {tactical.best_openings[0]}"
            evidence.append(f"opening: {tactical.best_openings[0]}")
        if won and user_key_cards:
            top = user_key_cards[0]
            name = _ru(getattr(top, "name", ""))
            text += f" Ключевой инструмент давления (оценка): {name}."
            evidence.append(f"key card: {name}")
        if crown_score:
            evidence.append(f"короны: {crown_score}")
        return CoachInsight(
            title="Лучший момент (по составу)",
            text=text,
            evidence=evidence,
            confidence="medium" if evidence else "low",
        )

    if tactical and tactical.best_openings:
        return CoachInsight(
            title="Лучший момент (по составу)",
            text=f"Сильнейшее открытие матчапа: {tactical.best_openings[0]}",
            evidence=[f"best opening: {tactical.best_openings[0]}"],
            confidence="medium",
        )

    return _insufficient(
        "Лучший момент",
        "Недостаточно данных, чтобы выделить лучший момент без реплея.",
    )


def _build_turning_point(
    *,
    won: bool,
    duration: int,
    crowns_user: int,
    crowns_opp: int,
    crown_score: str,
    user_elixir: ElixirEfficiencyReport | None,
    opp_elixir: ElixirEfficiencyReport | None,
    matchup_score: float,
) -> CoachInsight:
    evidence: list[str] = []
    if crown_score:
        evidence.append(f"счёт: {crown_score}")
    if duration:
        evidence.append(f"длительность: {duration}с")

    # Overtime / double elixir heuristic from duration only (API fact).
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

    if matchup_score >= 60 and not won:
        return CoachInsight(
            title="Переломный момент",
            text=(
                f"Матчап был сложным ({matchup_score:.0f}/100, {rating_for(round(matchup_score))}). "
                "Перелом с высокой вероятностью наступил, когда ключевая угроза соперника "
                "прошла без полного ответа."
            ),
            evidence=evidence + [f"matchup={matchup_score:.0f}"],
            confidence="low",
        )

    return _insufficient(
        "Переломный момент",
        "По длительности и счёту нельзя надёжно выделить перелом без таймлайна боя.",
    )


def _build_outcome_decider(
    *,
    won: bool,
    outcome_summary: str,
    matchup_score: float,
    threats: list[str],
    user_key_cards: list[Any],
    opponent_key_cards: list[Any],
    match_difficulty: MatchDifficultyReport | None,
) -> CoachInsight:
    evidence = [f"исход: {'победа' if won else 'поражение'}", f"матчап {matchup_score:.0f}/100"]
    parts = [outcome_summary.strip()] if outcome_summary.strip() else []

    if not won and threats:
        evidence.append(f"угрозы: {', '.join(_ru(t) for t in threats[:2])}")
        parts.append(
            f"Главный фактор риска по составу — угрозы {_ru(threats[0])}"
            + (f" / {_ru(threats[1])}" if len(threats) > 1 else "")
            + "."
        )
    if won and user_key_cards:
        top = _ru(getattr(user_key_cards[0], "name", ""))
        parts.append(f"Давление вашей стороны опиралось на {top} (оценка по роли WC).")
        evidence.append(f"user key: {top}")
    if not won and opponent_key_cards:
        top = _ru(getattr(opponent_key_cards[0], "name", ""))
        parts.append(f"Давление соперника опиралось на {top} (оценка по роли WC).")
        evidence.append(f"opp key: {top}")
    if match_difficulty and match_difficulty.reasons:
        parts.append(match_difficulty.reasons[0])
        evidence.append(f"difficulty: {match_difficulty.rating}")

    text = " ".join(p for p in parts if p).strip()
    if not text:
        return _insufficient(
            "Что решило исход",
            "Недостаточно фактов API, чтобы назвать решающий фактор.",
        )
    return CoachInsight(
        title="Что решило исход",
        text=text,
        evidence=evidence,
        confidence="high" if outcome_summary else "medium",
    )


def _build_danger_moment(
    *,
    tactical: TacticalMatchupReport | None,
    threats: list[str],
    opponent_key_cards: list[Any],
) -> CoachInsight:
    if tactical and tactical.danger_cards:
        d = tactical.danger_cards[0]
        evidence = [f"danger card: {_ru(d.name)}", d.reason]
        extra = ""
        if tactical.pressure_points:
            extra = f" Давление: {tactical.pressure_points[0]}"
            evidence.append(tactical.pressure_points[0])
        return CoachInsight(
            title="Самый опасный момент (по составу)",
            text=f"Самая опасная карта матчапа — {_ru(d.name)}: {d.reason}.{extra}",
            evidence=evidence,
            confidence="high",
        )

    if threats:
        return CoachInsight(
            title="Самый опасный момент (по составу)",
            text=(
                f"Главная угроза колоды соперника — {_ru(threats[0])}. "
                "Без реплея нельзя сказать, в какую секунду она прошла."
            ),
            evidence=[f"threat: {_ru(threats[0])}"],
            confidence="medium",
        )

    if opponent_key_cards:
        name = _ru(getattr(opponent_key_cards[0], "name", ""))
        return CoachInsight(
            title="Самый опасный момент (по составу)",
            text=f"По оценке ролей наибольшее давление давала карта {name}.",
            evidence=[f"opp key card: {name}"],
            confidence="low",
        )

    return _insufficient(
        "Самый опасный момент",
        "Не удалось выделить опасный момент: мало данных о угрозах соперника.",
    )


def _build_counterfactual(
    *,
    won: bool,
    user_deck: list[str],
    threats: list[str],
    missing_counters: list[str],
    tactical: TacticalMatchupReport | None,
    match_plan: MatchPlanReport | None,
    match_difficulty: MatchDifficultyReport | None,
) -> CoachInsight:
    # Prefer concrete deck gap: "if you had counter X".
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

    # Spell value mistake from tactical.
    if tactical and tactical.worst_mistakes:
        line = tactical.worst_mistakes[0]
        return CoachInsight(
            title="Если бы сделали иначе",
            text=(
                f"Если избежать сценария «{line}», обмен эликсиром в матчапе "
                f"с высокой вероятностью был бы выгоднее. "
                "Это правило состава, а не восстановленный ход боя."
            ),
            evidence=[line, "tactical worst_mistakes"],
            confidence="medium",
        )

    if match_plan and match_plan.avoid:
        line = match_plan.avoid[0]
        return CoachInsight(
            title="Если бы сделали иначе",
            text=(
                f"Если не заходить в ситуацию «{line}», исход по башням "
                f"вероятнее сместился бы в вашу пользу. Точный кадр API не даёт."
            ),
            evidence=[line, "match_plan.avoid"],
            confidence="low",
        )

    if match_plan and match_plan.win_condition_window:
        return CoachInsight(
            title="Если бы сделали иначе",
            text=(
                f"Если бы давление строили строго в окне «{match_plan.win_condition_window}», "
                + (
                    "шанс на башни был бы выше."
                    if not won
                    else "победа могла стоить меньше риска по башням."
                )
                + " Это вероятностный вывод по составу, не факт таймлайна."
            ),
            evidence=[f"win_condition_window: {match_plan.win_condition_window}"],
            confidence="low",
        )

    if not won and match_difficulty and match_difficulty.reasons:
        return CoachInsight(
            title="Если бы сделали иначе",
            text=(
                f"При более безопасной игре против фактора «{match_difficulty.reasons[0]}» "
                "вероятнее удалось бы дотянуть до выгодного эндшпиля. "
                "Конкретную замену хода API восстановить не может."
            ),
            evidence=[match_difficulty.reasons[0], f"rating={match_difficulty.rating}"],
            confidence="low",
        )

    return _insufficient(
        "Если бы сделали иначе",
        "Недостаточно устойчивых альтернатив по составу, чтобы честно описать другой исход.",
    )


class BattleCoach:
    """Собирает коучинг-отчёт только из уже посчитанного анализа боя."""

    @staticmethod
    def analyze(
        *,
        won: bool,
        user_deck: list[str],
        opponent_deck: list[str],
        threats: list[str],
        missing_counters: list[str],
        outcome_summary: str,
        matchup_score: float,
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
        notes = [_DATA_LIMIT_NOTE]
        if len(user_deck) < 8 or len(opponent_deck) < 8:
            notes.append("Колоды неполные — часть выводов недоступна.")
            return BattleCoachReport(
                main_mistakes=[],
                best_moment=_insufficient("Лучший момент", "Нужны обе колоды из 8 карт."),
                turning_point=_insufficient("Переломный момент", "Нужны обе колоды из 8 карт."),
                outcome_decider=_insufficient("Что решило исход", "Нужны обе колоды из 8 карт."),
                danger_moment=_insufficient("Самый опасный момент", "Нужны обе колоды из 8 карт."),
                counterfactual=_insufficient("Если бы сделали иначе", "Нужны обе колоды из 8 карт."),
                data_notes=notes,
                sufficient=False,
            )

        user_stats = analyze_deck(user_deck)
        mistakes = _build_mistakes(
            won=won,
            user_deck=user_deck,
            opponent_deck=opponent_deck,
            threats=threats,
            missing_counters=missing_counters,
            tactical=tactical,
            match_plan=match_plan,
            match_difficulty=match_difficulty,
            matchup_score=matchup_score,
            low_impact=list(low_impact_cards or []),
            user_stats=user_stats,
        )
        best = _build_best_moment(
            won=won,
            tactical=tactical,
            match_plan=match_plan,
            user_key_cards=list(user_key_cards or []),
            crown_score=crown_score,
        )
        turning = _build_turning_point(
            won=won,
            duration=duration,
            crowns_user=crowns_user,
            crowns_opp=crowns_opp,
            crown_score=crown_score,
            user_elixir=user_elixir,
            opp_elixir=opponent_elixir,
            matchup_score=matchup_score,
        )
        decider = _build_outcome_decider(
            won=won,
            outcome_summary=outcome_summary,
            matchup_score=matchup_score,
            threats=threats,
            user_key_cards=list(user_key_cards or []),
            opponent_key_cards=list(opponent_key_cards or []),
            match_difficulty=match_difficulty,
        )
        danger = _build_danger_moment(
            tactical=tactical,
            threats=threats,
            opponent_key_cards=list(opponent_key_cards or []),
        )
        alt = _build_counterfactual(
            won=won,
            user_deck=user_deck,
            threats=threats,
            missing_counters=missing_counters,
            tactical=tactical,
            match_plan=match_plan,
            match_difficulty=match_difficulty,
        )

        usable = sum(
            1
            for item in (*mistakes, best, turning, decider, danger, alt)
            if item and getattr(item, "usable", False)
        )
        if usable < 2:
            notes.append("Доступных фактов мало — показаны только выводы с явной опорой на данные.")

        return BattleCoachReport(
            main_mistakes=mistakes,
            best_moment=best,
            turning_point=turning,
            outcome_decider=decider,
            danger_moment=danger,
            counterfactual=alt,
            data_notes=_dedupe_lines(notes, limit=4),
            sufficient=usable >= 3,
        )


def build_battle_coach(**kwargs: Any) -> BattleCoachReport:
    return BattleCoach.analyze(**kwargs)

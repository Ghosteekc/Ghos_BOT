"""Enhanced battle outcome analysis (deck-based; CR API has no per-card damage stats)."""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.services.card_data import (
    COUNTERS,
    POINT_TARGET_COUNTERS,
    WIN_CONDITIONS,
    get_card_elixir,
    get_card_role,
    has_point_target_answer,
    is_point_target_threat,
    is_pure_spell,
    is_spam_card,
)
from bot.services.card_names_ru import card_name_ru
from bot.services.deck_analyzer import (
    BattleAnalysis,
    analyze_battle,
    analyze_deck,
    extract_deck,
    find_opponent_threats,
)

TOWER_SPELLS = {"Fireball", "Rocket", "Lightning", "Poison", "Earthquake", "Freeze"}
CHIP_CARDS = {"Royal Giant", "Mortar", "X-Bow", "Goblin Drill", "Miner"}

AIR_CARDS = {
    "Minions", "Minion Horde", "Baby Dragon", "Mega Minion", "Inferno Dragon",
    "Balloon", "Lava Hound", "Bats", "Skeleton Dragons", "Phoenix", "Flying Machine",
    "Electro Dragon",
}


@dataclass
class KeyCardInsight:
    name: str
    name_ru: str
    note: str


@dataclass
class EnhancedBattleAnalysis(BattleAnalysis):
    outcome_summary: str = ""
    user_key_cards: list[KeyCardInsight] = field(default_factory=list)
    opponent_key_cards: list[KeyCardInsight] = field(default_factory=list)
    low_impact_cards: list[KeyCardInsight] = field(default_factory=list)
    crown_score: str = ""


def _generic_counters(threat: str) -> list[str]:
    role = get_card_role(threat)
    if threat in AIR_CARDS or role == "air":
        return ["Inferno Tower", "Musketeer", "Inferno Dragon", "Wizard"]
    if is_spam_card(threat):
        return ["Wizard", "Baby Dragon", "Valkyrie", "Arrows", "The Log"]
    if is_point_target_threat(threat):
        return list(POINT_TARGET_COUNTERS) + ["Inferno Tower", "Tesla"]
    if role == "building" or threat in CHIP_CARDS:
        return ["Earthquake", "Rocket", "Miner", "Royal Giant"]
    if is_pure_spell(threat):
        return []
    return ["Knight", "Valkyrie", "Mini P.E.K.K.A", "Inferno Tower", "Tornado"]


def _counter_list(threat: str) -> list[str]:
    return COUNTERS.get(threat) or _generic_counters(threat)


def _damage_score(
    card: str,
    *,
    is_winner: bool,
    crowns: int,
    deck: list[str],
) -> float:
    score = 0.0
    role = get_card_role(card)

    if card in WIN_CONDITIONS or role == "win_condition":
        score += 10.0
    if card in CHIP_CARDS:
        score += 9.0
    if card in TOWER_SPELLS or role == "spell":
        score += 6.0 + min(crowns, 3)
    if role == "building" and card in CHIP_CARDS:
        score += 8.0
    if card == "Miner":
        score += 7.0

    synergies = deck
    if card == "Balloon" and "Lumberjack" in synergies:
        score += 2.0
    if card == "Hog Rider" and any(c in synergies for c in ("Ice Golem", "Ice Spirit")):
        score += 1.5
    if card == "Golem" and "Night Witch" in synergies:
        score += 2.0

    if is_winner:
        score += 1.5

    return score


def _rank_damage_dealers(
    deck: list[str],
    *,
    is_winner: bool,
    crowns: int,
) -> list[tuple[str, float]]:
    ranked = [(c, _damage_score(c, is_winner=is_winner, crowns=crowns, deck=deck)) for c in deck]
    ranked.sort(key=lambda x: (-x[1], x[0]))
    return ranked


def _relevant_user_cards(user_deck: list[str], opp_deck: list[str], threats: list[str]) -> set[str]:
    relevant: set[str] = set()
    user_stats = analyze_deck(user_deck)
    opp_stats = analyze_deck(opp_deck)

    relevant.update(user_stats.win_conditions)
    relevant.update(user_stats.spells)
    relevant.update(user_stats.buildings)

    for threat in threats:
        relevant.update(c for c in _counter_list(threat) if c in user_deck)

    if _air_in_deck(opp_deck) and user_stats.air_coverage:
        relevant.update(c for c in user_deck if c in {
            "Musketeer", "Wizard", "Inferno Dragon", "Mini P.E.K.K.A", "Inferno Tower",
            "Tesla", "Archers", "Baby Dragon",
        })

    if _swarm_in_deck(opp_deck) and user_stats.splash_coverage:
        relevant.update(c for c in user_deck if get_card_role(c) in ("splash", "spell"))

    if _point_target_in_deck(opp_deck) and user_stats.point_target_coverage:
        relevant.update(c for c in user_deck if c in POINT_TARGET_COUNTERS)

    if user_stats.avg_elixir <= opp_stats.avg_elixir + 0.3:
        relevant.update(c for c in user_deck if get_card_elixir(c) <= 2)

    return relevant


def _air_in_deck(deck: list[str]) -> list[str]:
    return [c for c in deck if c in AIR_CARDS or get_card_role(c) == "air"]


def _swarm_in_deck(deck: list[str]) -> list[str]:
    return [c for c in deck if is_spam_card(c)]


def _point_target_in_deck(deck: list[str]) -> list[str]:
    return [c for c in deck if is_point_target_threat(c)]


def _build_outcome_summary(
    *,
    won: bool,
    user_deck: list[str],
    opp_deck: list[str],
    threats: list[str],
    matchup_score: float,
    user_stats,
    opp_stats,
    crowns_user: int,
    crowns_opp: int,
    duration: int,
    user_top: str | None,
    opp_top: str | None,
    missing_threat: str | None,
) -> str:
    user_top_ru = card_name_ru(user_top) if user_top else ""
    opp_top_ru = card_name_ru(opp_top) if opp_top else ""

    if not won and missing_threat:
        counters = [c for c in _counter_list(missing_threat) if c not in user_deck]
        hint = ", ".join(card_name_ru(c) for c in counters[:3]) if counters else "усилить защиту"
        return (
            f"Поражение: «{card_name_ru(missing_threat)}» соперника не была нейтрализована. "
            f"В колоде не хватает: {hint}."
        )

    opp_air = _air_in_deck(opp_deck)
    if not won and opp_air and not user_stats.air_coverage:
        air_ru = ", ".join(card_name_ru(c) for c in opp_air[:2])
        return f"Поражение: не хватило защиты от воздуха ({air_ru})."

    if not won and _swarm_in_deck(opp_deck) and not user_stats.splash_coverage:
        return "Поражение: слабый сплеш — спам соперника добил по башням."

    opp_point = _point_target_in_deck(opp_deck)
    if not won and opp_point and not has_point_target_answer(user_deck):
        pt_ru = ", ".join(card_name_ru(c) for c in opp_point[:2])
        return (
            f"Поражение: слабый ответ на точечный урон ({pt_ru}) — "
            f"Стражи и подобные карты держат таких юнитов лучше сплеша."
        )

    if not won and user_stats.avg_elixir > opp_stats.avg_elixir + 1.0:
        return (
            f"Поражение: колода слишком тяжёлая ({user_stats.avg_elixir} эл.), "
            f"соперник быстрее циклил ({opp_stats.avg_elixir} эл.)."
        )

    if not won and not user_stats.spells and opp_stats.spells:
        return "Поражение: у соперника было преимущество в заклинаниях."

    if not won and matchup_score < 40 and opp_top_ru:
        return (
            f"Поражение: неблагоприятный матчап ({matchup_score:.0f}/100). "
            f"Ключевая угроза — «{opp_top_ru}»."
        )

    if not won and opp_top_ru:
        return f"Поражение: «{opp_top_ru}» соперника, вероятно, нанесла больше всего урона башням."

    if won and matchup_score >= 60 and threats:
        threat_ru = card_name_ru(threats[0])
        return f"Победа: удачный матчап ({matchup_score:.0f}/100), удалось контрить «{threat_ru}»."

    if won and user_stats.spells and not opp_stats.spells:
        return "Победа: контроль поля заклинаниями и давление по башням."

    if won and duration and duration <= 120 and user_stats.avg_elixir < opp_stats.avg_elixir:
        return "Победа: быстрый цикл — легкая колода успела чаще давить по башням."

    if won and crowns_user == 3 and user_top_ru:
        return f"Победа: «{user_top_ru}» — главный источник урона башням (разгром {crowns_user}:{crowns_opp})."

    if won and user_top_ru:
        return f"Победа: «{user_top_ru}» вероятнее всего добила больше всего урона башням."

    return "Победа — колода реализовала преимущество." if won else "Поражение — соперник лучше реализовал колоду."


def _build_reasons(
    analysis: BattleAnalysis,
    *,
    outcome_summary: str,
    user_top: str | None,
    opp_top: str | None,
    low_impact: list[KeyCardInsight],
    crown_score: str,
    duration: int,
) -> list[str]:
    reasons: list[str] = [outcome_summary]

    if analysis.matchup_score >= 60 and analysis.won:
        reasons.append(f"Матчап: {analysis.matchup_score:.0f}/100 — благоприятный.")
    elif analysis.matchup_score < 40 and not analysis.won:
        reasons.append(f"Матчап: {analysis.matchup_score:.0f}/100 — неблагоприятный.")

    if crown_score:
        reasons.append(f"Счёт по коронам: {crown_score}.")

    if duration:
        mins, secs = divmod(duration, 60)
        reasons.append(f"Длительность: {mins}:{secs:02d}.")

    if user_top:
        reasons.append(
            f"Ваша ключевая карта по урону башням (оценка): «{card_name_ru(user_top)}»."
        )
    if opp_top:
        reasons.append(
            f"Ключевая карта соперника по урону башням (оценка): «{card_name_ru(opp_top)}»."
        )

    for threat in analysis.opponent_threats:
        counters = _counter_list(threat)
        user_has = [c for c in counters if c in analysis.user_deck]
        if user_has:
            if analysis.won:
                reasons.append(
                    f"Счётчик на «{card_name_ru(threat)}»: {', '.join(card_name_ru(c) for c in user_has[:2])}."
                )
            else:
                reasons.append(
                    f"Счётчик на «{card_name_ru(threat)}» был ({', '.join(card_name_ru(c) for c in user_has[:2])}), "
                    f"но сыграл слабо или не вовремя."
                )
        else:
            rec = ", ".join(card_name_ru(c) for c in counters[:3])
            reasons.append(
                f"Нет счётчика на «{card_name_ru(threat)}». Рекомендуется: {rec}."
            )

    user_stats = analyze_deck(analysis.user_deck)
    opp_stats = analyze_deck(analysis.opponent_deck)

    if user_stats.avg_elixir > opp_stats.avg_elixir + 1.0:
        if not analysis.won:
            reasons.append(
                f"Средний эликсир выше ({user_stats.avg_elixir} против {opp_stats.avg_elixir}) — "
                f"соперник чаще успевал атаковать."
            )
    if not user_stats.spells and opp_stats.spells:
        reasons.append("В колоде нет заклинаний — сложнее добивать башни и контрить поле.")

    if low_impact:
        names = ", ".join(c.name_ru for c in low_impact[:3])
        reasons.append(
            f"Мало влияли на исход (оценка по колоде): {names}."
        )

    return reasons


def analyze_battle_enhanced(
    user_team: dict,
    opponent_team: dict,
    duration: int = 0,
) -> EnhancedBattleAnalysis:
    base = analyze_battle(user_team, opponent_team)
    user_deck = base.user_deck
    opp_deck = base.opponent_deck
    crowns_user = user_team.get("crowns", 0)
    crowns_opp = opponent_team.get("crowns", 0)
    crown_score = f"{crowns_user}:{crowns_opp}"

    user_ranked = _rank_damage_dealers(user_deck, is_winner=base.won, crowns=crowns_user)
    opp_ranked = _rank_damage_dealers(opp_deck, is_winner=not base.won, crowns=crowns_opp)
    user_top = user_ranked[0][0] if user_ranked and user_ranked[0][1] > 0 else None
    opp_top = opp_ranked[0][0] if opp_ranked and opp_ranked[0][1] > 0 else None

    missing_threat: str | None = None
    for threat in base.opponent_threats:
        if not any(c in user_deck for c in _counter_list(threat)):
            missing_threat = threat
            break

    user_stats = analyze_deck(user_deck)
    opp_stats = analyze_deck(opp_deck)
    threats = find_opponent_threats(opp_deck)

    outcome_summary = _build_outcome_summary(
        won=base.won,
        user_deck=user_deck,
        opp_deck=opp_deck,
        threats=threats,
        matchup_score=base.matchup_score,
        user_stats=user_stats,
        opp_stats=opp_stats,
        crowns_user=crowns_user,
        crowns_opp=crowns_opp,
        duration=duration,
        user_top=user_top,
        opp_top=opp_top,
        missing_threat=missing_threat,
    )

    user_key_cards = [
        KeyCardInsight(
            name=c,
            name_ru=card_name_ru(c),
            note="Вероятный основной урон по башням" if i == 0 else "Дополнительное давление",
        )
        for i, (c, s) in enumerate(user_ranked[:2])
        if s >= 5
    ]
    opponent_key_cards = [
        KeyCardInsight(
            name=c,
            name_ru=card_name_ru(c),
            note="Главная угроза по башням" if i == 0 else "Вспомогательная угроза",
        )
        for i, (c, s) in enumerate(opp_ranked[:2])
        if s >= 5
    ]

    relevant = _relevant_user_cards(user_deck, opp_deck, threats)
    low_impact_raw = [c for c in user_deck if c not in relevant][:4]
    low_impact = [
        KeyCardInsight(
            name=c,
            name_ru=card_name_ru(c),
            note="Не подходит под матчап или редко полезна — возможно, не успели сыграть",
        )
        for c in low_impact_raw
    ]

    reasons = _build_reasons(
        base,
        outcome_summary=outcome_summary,
        user_top=user_top,
        opp_top=opp_top,
        low_impact=low_impact,
        crown_score=crown_score,
        duration=duration,
    )

    return EnhancedBattleAnalysis(
        won=base.won,
        user_deck=base.user_deck,
        opponent_deck=base.opponent_deck,
        opponent_name=base.opponent_name,
        trophy_change=base.trophy_change,
        reasons=reasons,
        matchup_score=base.matchup_score,
        counter_cards_missing=base.counter_cards_missing,
        opponent_threats=base.opponent_threats,
        outcome_summary=outcome_summary,
        user_key_cards=user_key_cards,
        opponent_key_cards=opponent_key_cards,
        low_impact_cards=low_impact,
        crown_score=crown_score,
    )

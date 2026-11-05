"""Human-readable win/loss insights from battle history."""

from collections import Counter

from bot.services.battle_report import analyze_battle_list_item
from bot.services.card_data import WIN_CONDITIONS, card_has_role
from bot.services.card_matchups import (
    counters_in_deck,
    local_counter_available,
    local_counter_has_card,
)
from bot.services.card_names_ru import card_name_ru
from bot.services.clash_api import normalize_tag
from bot.services.deck_analyzer import battle_outcome, extract_deck
from bot.services.tactical_matchup import analyze_tactical_matchup


def build_battle_insight(battle: dict, player_tag: str) -> dict | None:
    team = battle.get("team", [{}])[0]
    opponent = battle.get("opponent", [{}])[0]

    team_tag = team.get("tag") or ""
    if team_tag and normalize_tag(team_tag) != normalize_tag(player_tag):
        return None

    user_deck = extract_deck(team)
    if not user_deck:
        return None

    duration = int(battle.get("gameDuration") or 0)
    try:
        analysis = analyze_battle_list_item(team, opponent, duration=duration)
    except Exception:
        return None

    tags: list[str] = []
    summary = analysis.outcome_summary

    if analysis.outcome == "loss":
        if "воздух" in summary.lower():
            tags.append("air_defense")
        if "сплеш" in summary.lower() or "спам" in summary.lower():
            tags.append("splash")
        if "точечн" in summary.lower() or "страж" in summary.lower():
            tags.append("point_target")
        if "тяжёл" in summary.lower() or "циклил" in summary.lower():
            tags.append("cycle")
        if "заклинан" in summary.lower():
            tags.append("spells")
        if "матчап" in summary.lower():
            tags.append("matchup")
        if analysis.opponent_threats:
            tags.append("threat")
    else:
        if "матчап" in summary.lower():
            tags.append("matchup")
        if "заклинан" in summary.lower():
            tags.append("spells")
        if analysis.user_key_cards:
            tags.append("win_condition")

    return {
        "won": analysis.won,
        "outcome": analysis.outcome,
        "opponent_name": opponent.get("name", "Соперник"),
        "summary": summary,
        "tags": tags,
        "matchup_score": round(analysis.matchup_score, 1),
        "details": analysis.reasons[1:5],
        "timestamp": str(battle.get("battleTime") or battle.get("warTime") or ""),
    }


def _win_conditions(deck: list[str]) -> list[str]:
    return [
        card_name_ru(card, short=True) or card
        for card in deck
        if card in WIN_CONDITIONS or card_has_role(card, "win_condition")
    ]


def _tactical_lines(user_deck: list[str], opponent_deck: list[str]) -> list[str]:
    """Small, deterministic playbook for this exact pair of played decks."""
    report = analyze_tactical_matchup(user_deck, opponent_deck)
    lines: list[str] = []
    for bucket in (
        report.critical_interactions,
        report.pressure_points,
        report.best_openings,
        report.early_game,
        report.worst_mistakes,
    ):
        for line in bucket:
            if line and line not in lines:
                lines.append(line)
            if len(lines) >= 3:
                return lines
    return lines


def _counter_check(
    threat: str,
    user_deck: list[str],
) -> tuple[list[str], list[str], str, bool]:
    """Return confirmed answers and an explicit lookup state.

    An empty, completed lookup means only that no *confirmed project-database*
    answer was found in this exact deck. It never claims the threat has no
    possible in-game counters. Errors or incomplete source coverage remain
    ``unknown`` instead of being converted to an empty result.
    """
    if not local_counter_available() or not local_counter_has_card(threat):
        return [], [], "unknown", False
    if any(not local_counter_has_card(card) for card in user_deck):
        return [], [], "unknown", False
    try:
        strong, partial = counters_in_deck(threat, user_deck)
    except Exception:
        return [], [], "unknown", False
    if strong:
        return strong, partial, "strong", True
    if partial:
        return strong, partial, "partial", True
    return [], [], "not_found", True


def build_loss_threats(
    battles: list[dict],
    player_tag: str,
    *,
    scan_limit: int = 40,
    limit: int = 4,
) -> list[dict]:
    """Aggregate recurring enemy deck threats and answers available in the played deck.

    Each row keeps a representative played matchup, so an answer is never
    presented as available merely because it existed in another deck. Presence
    in a deck does not prove the card was played in that battle.
    """
    tag = normalize_tag(player_tag)
    grouped: dict[str, dict] = {}

    for battle in battles[:scan_limit]:
        team = battle.get("team", [{}])[0]
        opponent = battle.get("opponent", [{}])[0]
        team_tag = team.get("tag") or ""
        if team_tag and normalize_tag(team_tag) != tag:
            continue
        # A draw is not evidence of a loss pattern. Keep this aggregation to
        # actual losses only, independently of how a caller presents draws.
        if battle_outcome(team, opponent) != "loss":
            continue

        try:
            user_deck = extract_deck(team)
            opponent_deck = extract_deck(opponent)
        except Exception:
            # Malformed stored cards make this matchup indeterminate, never a
            # negative claim about counter coverage.
            continue
        if len(user_deck) != 8 or len(opponent_deck) != 8:
            continue

        try:
            analysis = analyze_battle_list_item(
                team,
                opponent,
                duration=int(battle.get("gameDuration") or 0),
            )
        except Exception:
            continue

        for threat in analysis.opponent_threats:
            if not threat:
                continue
            row = grouped.get(threat)
            if row is None:
                strong, partial, counter_status, counter_check_performed = _counter_check(threat, user_deck)
                try:
                    tactics = _tactical_lines(user_deck, opponent_deck)
                except Exception:
                    # Tactics are optional and must not erase a completed
                    # counter lookup or turn an error into a game claim.
                    tactics = []
                row = {
                    "card": threat,
                    "card_ru": card_name_ru(threat, short=True) or threat,
                    "losses": 0,
                    "strong_counters": [card_name_ru(card, short=True) or card for card in strong],
                    "partial_counters": [card_name_ru(card, short=True) or card for card in partial],
                    "counter_status": counter_status,
                    "counter_check_performed": counter_check_performed,
                    "win_conditions": _win_conditions(user_deck),
                    "tactics": tactics,
                }
                grouped[threat] = row
            row["losses"] += 1

    def _rank(item: dict) -> tuple[int, int, int]:
        return (
            int(item["losses"]),
            len(item["strong_counters"]),
            len(item["partial_counters"]),
        )

    return sorted(grouped.values(), key=_rank, reverse=True)[:limit]


def build_insights_report(
    battles: list[dict],
    player_tag: str,
    limit: int = 7,
    *,
    losses_only: bool = True,
) -> dict:
    insights: list[dict] = []
    tag_counter: Counter[str] = Counter()

    for i, battle in enumerate(battles[:40]):
        if len(insights) >= limit:
            break
        try:
            row = build_battle_insight(battle, player_tag)
        except Exception:
            # One malformed history row is insufficient evidence, not a
            # reason to report that the player has no losses.
            continue
        if not row:
            continue
        if losses_only and row["won"]:
            continue
        row["battle_index"] = i
        insights.append(row)
        tag_counter.update(row["tags"])

    patterns: list[str] = []
    if tag_counter.get("air_defense", 0) >= 2:
        patterns.append(
            f"Повторяющийся риск состава: защита от воздуха ({tag_counter['air_defense']} поражений)."
        )
    if tag_counter.get("splash", 0) >= 2:
        patterns.append(f"Повторяющийся риск: мало сплеша в {tag_counter['splash']} поражениях против спама.")
    if tag_counter.get("point_target", 0) >= 2:
        patterns.append(
            f"Повторяющийся риск против точечного урона — {tag_counter['point_target']} поражений. "
            f"Стражи могут помочь против P.E.K.K.A и подобных."
        )
    if tag_counter.get("cycle", 0) >= 2:
        patterns.append("Тяжёлая колода может уступать в темпе — рассмотрите снижение среднего эликсира.")
    if tag_counter.get("spells", 0) >= 2:
        patterns.append("Добавьте заклинания — без них сложнее контролировать поле.")

    wins = sum(1 for x in insights if x["won"])
    losses = len(insights) - wins

    threats = build_loss_threats(battles, player_tag)
    source_outcomes = [
        battle_outcome(battle.get("team", [{}])[0], battle.get("opponent", [{}])[0])
        for battle in battles[:40]
    ]
    source_losses = source_outcomes.count("loss")
    source_unknowns = source_outcomes.count("unknown")
    if source_losses == 0 and source_unknowns == 0:
        analysis_status = "no_losses"
        analysis_message = "В загруженной истории нет подтверждённых поражений. Сыграйте ещё бои, если хотите получить разбор."
    elif source_losses == 0:
        analysis_status = "insufficient"
        analysis_message = "Не удалось определить — в части боёв не хватает данных о результате. Обновите историю после следующего полного боя."
    elif not insights and not threats:
        analysis_status = "insufficient"
        analysis_message = "Не удалось определить — недостаточно полных данных боя для проверки угроз и ответов. Обновите историю после следующего полного боя."
    else:
        analysis_status = "ok"
        analysis_message = None
    return {
        "insights": insights,
        "patterns": patterns,
        "threats": threats,
        "sample_size": len(insights),
        "wins": wins,
        "losses": losses,
        "analysis_status": analysis_status,
        "analysis_message": analysis_message,
    }

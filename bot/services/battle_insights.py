"""Human-readable win/loss insights from battle history."""

from collections import Counter

from bot.services.battle_report import analyze_battle_enhanced
from bot.services.clash_api import normalize_tag
from bot.services.deck_analyzer import extract_deck


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
    analysis = analyze_battle_enhanced(team, opponent, duration=duration)

    tags: list[str] = []
    summary = analysis.outcome_summary

    if not analysis.won:
        if "воздух" in summary.lower():
            tags.append("air_defense")
        if "сплеш" in summary.lower() or "рой" in summary.lower():
            tags.append("splash")
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
        "opponent_name": opponent.get("name", "Соперник"),
        "summary": summary,
        "tags": tags,
        "matchup_score": round(analysis.matchup_score, 1),
        "details": analysis.reasons[1:5],
        "timestamp": str(battle.get("battleTime") or battle.get("warTime") or ""),
    }


def build_insights_report(battles: list[dict], player_tag: str, limit: int = 10) -> dict:
    insights: list[dict] = []
    tag_counter: Counter[str] = Counter()

    for i, battle in enumerate(battles):
        if len(insights) >= limit:
            break
        row = build_battle_insight(battle, player_tag)
        if not row:
            continue
        row["battle_index"] = i
        insights.append(row)
        if not row["won"]:
            tag_counter.update(row["tags"])

    patterns: list[str] = []
    if tag_counter.get("air_defense", 0) >= 2:
        patterns.append(
            f"Частая проблема: защита от воздуха ({tag_counter['air_defense']} поражений)."
        )
    if tag_counter.get("splash", 0) >= 2:
        patterns.append(f"Слабый сплеш — {tag_counter['splash']} поражений против роя.")
    if tag_counter.get("cycle", 0) >= 2:
        patterns.append("Тяжёлая колода мешает — попробуйте снизить средний эликсир.")
    if tag_counter.get("spells", 0) >= 2:
        patterns.append("Добавьте заклинания — без них сложнее контролировать поле.")

    wins = sum(1 for x in insights if x["won"])
    losses = len(insights) - wins
    if insights and wins >= 3 and not patterns:
        patterns.append(f"Хорошая серия: {wins} побед из последних {len(insights)} боёв.")

    return {
        "insights": insights,
        "patterns": patterns,
        "sample_size": len(insights),
        "wins": wins,
        "losses": losses,
    }

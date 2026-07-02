"""Human-readable win/loss insights from battle history."""

from collections import Counter

from bot.services.card_data import WIN_CONDITIONS, get_card_role
from bot.services.card_names_ru import card_name_ru
from bot.services.clash_api import normalize_tag
from bot.services.deck_analyzer import analyze_battle, analyze_deck, extract_deck

AIR_CARDS = {
    "Minions", "Minion Horde", "Baby Dragon", "Mega Minion", "Inferno Dragon",
    "Balloon", "Lava Hound", "Bats", "Skeleton Dragons", "Phoenix", "Flying Machine",
    "Minions", "Electro Dragon",
}

SWARM_CARDS = {
    "Goblins", "Spear Goblins", "Skeleton Army", "Goblin Gang", "Barbarians",
    "Elite Barbarians", "Minion Horde", "Bats", "Skeletons", "Guards",
}


def _air_in_deck(deck: list[str]) -> list[str]:
    return [c for c in deck if c in AIR_CARDS or get_card_role(c) == "air"]


def _swarm_in_deck(deck: list[str]) -> list[str]:
    return [c for c in deck if c in SWARM_CARDS or get_card_role(c) == "swarm"]


def _primary_win_card(deck: list[str]) -> str | None:
    for card in deck:
        if card in WIN_CONDITIONS or get_card_role(card) == "win_condition":
            return card
    return deck[0] if deck else None


def build_battle_insight(battle: dict, player_tag: str) -> dict | None:
    team = battle.get("team", [{}])[0]
    opponent = battle.get("opponent", [{}])[0]

    team_tag = team.get("tag") or ""
    if team_tag and normalize_tag(team_tag) != normalize_tag(player_tag):
        return None

    user_deck = extract_deck(team)
    opp_deck = extract_deck(opponent)
    if not user_deck:
        return None

    won = team.get("crowns", 0) > opponent.get("crowns", 0)
    user_stats = analyze_deck(user_deck)
    opp_stats = analyze_deck(opponent)
    analysis = analyze_battle(team, opponent)

    summary = ""
    tags: list[str] = []

    opp_air = _air_in_deck(opp_deck)
    if not won and opp_air and not user_stats.air_coverage:
        air_ru = ", ".join(card_name_ru(c) for c in opp_air[:3])
        summary = f"Вы проиграли, потому что не смогли задефать воздушные карты ({air_ru})."
        tags.append("air_defense")
    elif not won and _swarm_in_deck(opp_deck) and not user_stats.splash_coverage:
        summary = "Вы проиграли — в колоде не хватило сплеша против роя соперника."
        tags.append("splash")
    elif not won and user_stats.avg_elixir > opp_stats.avg_elixir + 1.0:
        summary = (
            f"Вы проиграли — колода слишком тяжёлая ({user_stats.avg_elixir} эл.), "
            f"соперник быстрее циклил ({opp_stats.avg_elixir} эл.)."
        )
        tags.append("cycle")
    elif not won and not user_stats.spells and opp_stats.spells:
        summary = "Вы проиграли — у соперника было преимущество в заклинаниях."
        tags.append("spells")
    elif won:
        win_card = _primary_win_card(user_deck)
        if win_card:
            summary = (
                f"Вы выиграли — «{card_name_ru(win_card)}» стала главной угрозой "
                f"и помогла добить башни."
            )
            tags.append("win_condition")
        elif user_stats.spells and not opp_stats.spells:
            summary = "Вы выиграли благодаря контролю поля заклинаниями."
            tags.append("spells")
        elif analysis.matchup_score >= 55:
            summary = f"Вы выиграли — удачный матчап ({analysis.matchup_score:.0f}/100)."
            tags.append("matchup")
        else:
            summary = "Вы выиграли — колода сработала лучше, чем ожидалось."
    elif analysis.opponent_threats:
        threat = analysis.opponent_threats[0]
        summary = (
            f"Вы проиграли — не удалось нейтрализовать «{card_name_ru(threat)}» соперника."
        )
        tags.append("threat")
    else:
        clean = (analysis.reasons[0] if analysis.reasons else "").lstrip("📊✅❌⚠️🎯 ")
        summary = clean or ("Победа" if won else "Поражение")

    return {
        "won": won,
        "opponent_name": opponent.get("name", "Соперник"),
        "summary": summary,
        "tags": tags,
        "matchup_score": round(analysis.matchup_score, 1),
        "details": analysis.reasons[:4],
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

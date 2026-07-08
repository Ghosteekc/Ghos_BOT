from collections import Counter
from dataclasses import dataclass

from bot.services.card_data import (
    COUNTERS,
    SYNERGIES,
    WIN_CONDITIONS,
    get_card_elixir,
    get_card_role,
)
from bot.services.clash_api import normalize_tag


@dataclass
class DeckStats:
    cards: list[str]
    avg_elixir: float
    win_conditions: list[str]
    spells: list[str]
    buildings: list[str]
    air_coverage: bool
    splash_coverage: bool


@dataclass
class BattleAnalysis:
    won: bool
    user_deck: list[str]
    opponent_deck: list[str]
    opponent_name: str
    trophy_change: int
    reasons: list[str]
    matchup_score: float
    counter_cards_missing: list[str]
    opponent_threats: list[str]


def extract_deck(team: dict) -> list[str]:
    return [card["name"] for card in team.get("cards", [])]


def analyze_deck(cards: list[str]) -> DeckStats:
    elixirs = [get_card_elixir(c) for c in cards]
    avg = sum(elixirs) / len(elixirs) if elixirs else 0.0

    win_conds = [c for c in cards if c in WIN_CONDITIONS or get_card_role(c) == "win_condition"]
    spells = [c for c in cards if get_card_role(c) == "spell"]
    buildings = [c for c in cards if get_card_role(c) == "building"]

    anti_air = {
        "Musketeer", "Wizard", "Executioner", "Inferno Dragon", "Mini P.E.K.K.A",
        "Mega Minion", "Electro Wizard", "Hunter", "Inferno Tower", "Tesla",
        "Archers", "Bats", "Minions", "Phoenix", "Firecracker", "Ice Wizard",
        "Baby Dragon",
    }
    splash_cards = {"Wizard", "Baby Dragon", "Valkyrie", "Bowler", "Executioner",
                    "Fireball", "Arrows", "Poison", "Earthquake", "Electro Dragon",
                    "Goblin Demolisher", "Magic Archer"}

    return DeckStats(
        cards=cards,
        avg_elixir=round(avg, 2),
        win_conditions=win_conds,
        spells=spells,
        buildings=buildings,
        air_coverage=len(set(cards) & anti_air) >= 1,
        splash_coverage=bool(set(cards) & splash_cards),
    )


def find_opponent_threats(opponent_deck: list[str]) -> list[str]:
    threats = []
    for card in opponent_deck:
        if card in WIN_CONDITIONS or get_card_role(card) == "win_condition":
            threats.append(card)
    return threats


def calculate_matchup_score(user_deck: list[str], opponent_deck: list[str]) -> float:
    """Оценка матчапа от 0 (плохо) до 100 (отлично) на основе счётчиков."""
    threats = find_opponent_threats(opponent_deck)
    if not threats:
        return 50.0

    countered = 0
    for threat in threats:
        counters = COUNTERS.get(threat, [])
        if any(c in user_deck for c in counters):
            countered += 1

    base_score = (countered / len(threats)) * 70

    user_stats = analyze_deck(user_deck)
    opp_stats = analyze_deck(opponent_deck)

    if user_stats.avg_elixir > opp_stats.avg_elixir + 1.0:
        base_score -= 10
    elif user_stats.avg_elixir < opp_stats.avg_elixir - 0.5:
        base_score += 5

    if not user_stats.air_coverage and any(
        c in {"Balloon", "Lava Hound", "Minions", "Minion Horde"} for c in opponent_deck
    ):
        base_score -= 15

    if not user_stats.splash_coverage and any(
        get_card_role(c) == "swarm" for c in opponent_deck
    ):
        base_score -= 10

    return max(0.0, min(100.0, base_score))


def analyze_battle(user_team: dict, opponent_team: dict) -> BattleAnalysis:
    user_deck = extract_deck(user_team)
    opponent_deck = extract_deck(opponent_team)
    crowns_user = user_team.get("crowns", 0)
    crowns_opp = opponent_team.get("crowns", 0)
    won = crowns_user > crowns_opp
    trophy_change = user_team.get("trophyChange", 0)

    matchup_score = calculate_matchup_score(user_deck, opponent_deck)
    threats = find_opponent_threats(opponent_deck)
    reasons = []
    missing_counters = []

    for threat in threats:
        counters = COUNTERS.get(threat, [])
        user_has = [c for c in counters if c in user_deck]
        if user_has:
            if won:
                reasons.append(f"✅ {threat} — у вас есть счётчик: {', '.join(user_has)}")
            else:
                reasons.append(
                    f"⚠️ {threat} — счётчик есть ({', '.join(user_has)}), "
                    f"но, возможно, использован не вовремя"
                )
        else:
            missing_counters.extend(counters[:2])
            if won:
                reasons.append(
                    f"🎯 Вы победили без прямого счётчика на {threat} — "
                    f"хорошая игра или уровень карт"
                )
            else:
                reasons.append(
                    f"❌ Нет счётчика на {threat}. Рекомендуется: "
                    f"{', '.join(counters[:3])}"
                )

    user_stats = analyze_deck(user_deck)
    opp_stats = analyze_deck(opponent_deck)

    if user_stats.avg_elixir > opp_stats.avg_elixir + 1.0:
        if not won:
            reasons.append(
                f"❌ Ваша колода тяжелее ({user_stats.avg_elixir} против "
                f"{opp_stats.avg_elixir} эликсира) — соперник быстрее циклил"
            )
        else:
            reasons.append("✅ Выиграли несмотря на более тяжёлую колоду")

    if not user_stats.spells and opp_stats.spells:
        reasons.append("❌ У вас нет заклинаний — сложнее контролировать поле")
    elif user_stats.spells and not opp_stats.spells:
        reasons.append("✅ Преимущество в заклинаниях")

    if matchup_score >= 60 and won:
        reasons.insert(0, f"📊 Благоприятный матчап ({matchup_score:.0f}/100)")
    elif matchup_score < 40 and not won:
        reasons.insert(0, f"📊 Неблагоприятный матчап ({matchup_score:.0f}/100)")

    return BattleAnalysis(
        won=won,
        user_deck=user_deck,
        opponent_deck=opponent_deck,
        opponent_name=opponent_team.get("name", "Соперник"),
        trophy_change=trophy_change,
        reasons=reasons,
        matchup_score=matchup_score,
        counter_cards_missing=list(set(missing_counters)),
        opponent_threats=threats,
    )


def calculate_deck_winrates(battles: list[dict], player_tag: str) -> dict[str, dict]:
    """Винрейт по колодам (ключ — отсортированный список карт)."""
    deck_results: dict[str, list[bool]] = {}

    for battle in battles:
        battle_type = battle.get("type") or "PvP"
        if battle_type in ("friendly", "clanMate", "warDay", "boatBattle", "challenge"):
            continue

        team = battle.get("team", [{}])[0]
        opponent = battle.get("opponent", [{}])[0]

        team_tag = team.get("tag") or ""
        if team_tag and normalize_tag(team_tag) != normalize_tag(player_tag):
            continue

        deck_key = "|".join(sorted(extract_deck(team)))
        if not deck_key:
            continue

        won = team.get("crowns", 0) > opponent.get("crowns", 0)
        deck_results.setdefault(deck_key, []).append(won)

    winrates = {}
    for deck_key, results in deck_results.items():
        wins = sum(results)
        total = len(results)
        cards = deck_key.split("|")
        winrates[deck_key] = {
            "cards": cards,
            "wins": wins,
            "losses": total - wins,
            "total": total,
            "winrate": round(wins / total * 100, 1) if total else 0,
        }

    return dict(sorted(winrates.items(), key=lambda x: x[1]["total"], reverse=True))


def get_most_played_cards(battles: list[dict], player_tag: str, top_n: int = 5) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for battle in battles:
        team = battle.get("team", [{}])[0]
        if team.get("tag", "").upper() != player_tag.upper():
            continue
        for card in extract_deck(team):
            counter[card] += 1
    return counter.most_common(top_n)

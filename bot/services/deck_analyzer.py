from collections import Counter
from dataclasses import dataclass

from bot.services.card_data import (
    SYNERGIES,
    card_has_role,
    get_card_elixir,
    has_point_target_answer,
    is_point_target_threat,
    is_spam_card,
)
from bot.services.card_profile import get_card_profile

# TODO(card-profile): локальные anti_air / splash sets дублируют CardProfile roles.
# Не менять алгоритм analyze_deck — только помечено для будущей миграции.
from bot.services.card_matchups import counters_in_deck, ru, ru_list
from bot.services.clash_api import normalize_tag
from bot.services.matchup_evaluation import MatchupEvaluation, evaluate_matchup


@dataclass
class DeckStats:
    cards: list[str]
    avg_elixir: float
    win_conditions: list[str]
    spells: list[str]
    buildings: list[str]
    air_coverage: bool
    splash_coverage: bool
    point_target_coverage: bool


@dataclass
class BattleAnalysis:
    won: bool
    user_deck: list[str]
    opponent_deck: list[str]
    opponent_name: str
    trophy_change: int
    reasons: list[str]
    matchup_score: float
    matchup_evaluation: MatchupEvaluation
    counter_cards_missing: list[str]
    opponent_threats: list[str]


def extract_deck(team: dict) -> list[str]:
    return [card["name"] for card in team.get("cards", [])]


def analyze_deck(cards: list[str]) -> DeckStats:
    elixirs = [get_card_elixir(c) for c in cards]
    avg = sum(elixirs) / len(elixirs) if elixirs else 0.0

    # Мультироли: win/spell/building/air/splash — по полному roles[], не primary.
    win_conds = [c for c in cards if card_has_role(c, "win_condition")]
    spells = [c for c in cards if card_has_role(c, "spell")]
    buildings = [c for c in cards if card_has_role(c, "building")]

    air_coverage = any(get_card_profile(c).is_air_defense for c in cards)
    splash_coverage = any(card_has_role(c, "splash") for c in cards)

    return DeckStats(
        cards=cards,
        avg_elixir=round(avg, 2),
        win_conditions=win_conds,
        spells=spells,
        buildings=buildings,
        air_coverage=air_coverage,
        splash_coverage=splash_coverage,
        point_target_coverage=has_point_target_answer(cards),
    )


def find_opponent_threats(opponent_deck: list[str]) -> list[str]:
    threats = []
    for card in opponent_deck:
        if card_has_role(card, "win_condition"):
            threats.append(card)
    return threats


def calculate_matchup_score(user_deck: list[str], opponent_deck: list[str]) -> float:
    """Единый score сложности матчапа: выше = сложнее для user_deck."""
    return float(evaluate_matchup(user_deck, opponent_deck).score)


def analyze_battle(user_team: dict, opponent_team: dict) -> BattleAnalysis:
    user_deck = extract_deck(user_team)
    opponent_deck = extract_deck(opponent_team)
    crowns_user = user_team.get("crowns", 0)
    crowns_opp = opponent_team.get("crowns", 0)
    won = crowns_user > crowns_opp
    trophy_change = user_team.get("trophyChange", 0)

    matchup = evaluate_matchup(user_deck, opponent_deck)
    matchup_score = float(matchup.score)
    threats = find_opponent_threats(opponent_deck)
    reasons = []
    missing_counters = []

    for threat in threats:
        strong, partial = counters_in_deck(threat, user_deck)
        t_ru = ru(threat)
        if strong:
            if won:
                reasons.append(f"✅ {t_ru} — контра: {ru_list(strong)}")
            else:
                reasons.append(
                    f"⚠️ {t_ru} — контра есть ({ru_list(strong)}), но не сработала вовремя",
                )
        elif partial:
            missing_counters.extend(partial[:2])
            if won:
                reasons.append(f"🎯 Победа без полной контры на {t_ru} (есть только {ru_list(partial)})")
            else:
                reasons.append(f"⚠️ Слабая контра на {t_ru}: {ru_list(partial)}")
        else:
            from bot.services.card_matchups import get_matchups

            row = get_matchups(threat)
            rec = list(row.counters_strong)[:3] if row else []
            missing_counters.extend(rec[:2])
            if won:
                reasons.append(f"🎯 Победа без контры на {t_ru} — сильная игра")
            else:
                reasons.append(
                    f"❌ Нет контры на {t_ru}. Подойдут: {ru_list(rec) if rec else '—'}",
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

    opp_spam = [c for c in opponent_deck if is_spam_card(c)]
    if not won and opp_spam and not user_stats.splash_coverage:
        reasons.append("❌ Слабый сплеш — спам соперника сложно зачищать")

    opp_point = [c for c in opponent_deck if is_point_target_threat(c)]
    if not won and opp_point and not user_stats.point_target_coverage:
        reasons.append(
            f"❌ Слабый ответ на точечный урон ({ru_list(opp_point[:2])}) — "
            f"Стражи держат P.E.K.K.A, Хог и подобных",
        )

    reasons.insert(0, f"📊 Матчап: {matchup_score:.0f}/100 — {matchup.rating}.")
    reasons.extend(f"Матчап: {reason}" for reason in matchup.reasons[:3])

    return BattleAnalysis(
        won=won,
        user_deck=user_deck,
        opponent_deck=opponent_deck,
        opponent_name=opponent_team.get("name", "Соперник"),
        trophy_change=trophy_change,
        reasons=reasons,
        matchup_score=matchup_score,
        matchup_evaluation=matchup,
        counter_cards_missing=list(set(missing_counters)),
        opponent_threats=threats,
    )


def calculate_deck_winrates(battles: list[dict], player_tag: str) -> dict[str, dict]:
    """Винрейт по колодам (ключ — набор карт).

    Порядок слотов и эволюции/герои берутся из боёв (как в игре), а не из
    алфавитной сортировки имён.
    """
    from bot.services.card_icons import cards_from_team, merge_deck_variants

    deck_results: dict[str, list[bool]] = {}
    deck_variants: dict[str, list[list[dict]]] = {}

    for battle in battles:
        battle_type = battle.get("type") or "PvP"
        if battle_type in ("friendly", "clanMate", "warDay", "boatBattle", "challenge"):
            continue

        team = battle.get("team", [{}])[0]
        opponent = battle.get("opponent", [{}])[0]

        team_tag = team.get("tag") or ""
        if team_tag and normalize_tag(team_tag) != normalize_tag(player_tag):
            continue

        parsed = cards_from_team(team)
        if len(parsed) != 8:
            # Cached stubs may only have names — keep order as stored.
            raw_names = [c.get("name") for c in team.get("cards", []) if c.get("name")]
            if len(raw_names) != 8:
                continue
            parsed = [
                {
                    "name": name,
                    "icon": "",
                    "evolution_level": 0,
                    "is_hero": False,
                    "cost": get_card_elixir(name),
                    "slot": i,
                }
                for i, name in enumerate(raw_names)
            ]

        deck_key = "|".join(sorted(c["name"] for c in parsed))
        if not deck_key:
            continue

        won = team.get("crowns", 0) > opponent.get("crowns", 0)
        deck_results.setdefault(deck_key, []).append(won)
        deck_variants.setdefault(deck_key, []).append(parsed)

    winrates = {}
    for deck_key, results in deck_results.items():
        wins = sum(results)
        total = len(results)
        merged = merge_deck_variants(deck_variants.get(deck_key, []))
        if not merged:
            merged = [
                {
                    "name": name,
                    "icon": "",
                    "evolution_level": 0,
                    "is_hero": False,
                    "cost": get_card_elixir(name),
                    "slot": i,
                }
                for i, name in enumerate(deck_key.split("|"))
            ]
        winrates[deck_key] = {
            "cards": [c["name"] for c in merged],
            "deck_cards": merged,
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

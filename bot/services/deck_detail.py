"""Per-deck stats: matchups, improvements, winrate from battle history."""

from __future__ import annotations

from bot.services.card_data import COUNTERS, WIN_CONDITIONS, get_card_elixir, get_card_role, is_pure_spell
from bot.services.card_names_ru import card_name_ru
from bot.services.clash_api import normalize_tag
from bot.services.deck_analyzer import analyze_deck, extract_deck
from bot.services.meta_analyzer import _guess_deck_name

_SMALL_SPELLS = {"Zap", "The Log", "Giant Snowball", "Barbarian Barrel", "Ice Spirit", "Electro Spirit"}
_FINISHERS = {"Fireball", "Rocket", "Lightning", "Poison"}
_ANTI_AIR_SUGGESTIONS = ["Musketeer", "Mega Minion", "Inferno Dragon", "Tesla", "Archers"]
_SPLASH_SUGGESTIONS = ["Valkyrie", "Wizard", "Baby Dragon", "Fireball", "Arrows"]
_DEFENSE_SUGGESTIONS = ["Cannon", "Tesla", "Tombstone", "Inferno Tower"]
_CYCLE_SUGGESTIONS = ["Skeletons", "Ice Spirit", "Electro Spirit", "Ice Golem"]
_POINT_TARGET_SUGGESTIONS = ["Guards", "Knight", "Ice Golem", "Skeleton Army"]


def deck_key(cards: list[str]) -> str:
    return "|".join(sorted(cards))


def _effective_counters(deck: list[str], threat: str) -> list[str]:
    if is_pure_spell(threat):
        return []
    return [c for c in COUNTERS.get(threat, []) if c in deck and c != threat]


def _filter_battles_for_deck(battles: list[dict], player_tag: str, cards: list[str]) -> list[dict]:
    if len(cards) != 8:
        return []
    key = deck_key(cards)
    tag_norm = normalize_tag(player_tag)
    out: list[dict] = []

    for battle in battles:
        battle_type = battle.get("type") or "PvP"
        if battle_type in ("friendly", "clanMate", "warDay", "boatBattle", "challenge"):
            continue
        team = battle.get("team", [{}])[0]
        team_tag = team.get("tag") or ""
        if team_tag and normalize_tag(team_tag) != tag_norm:
            continue
        user_cards = extract_deck(team)
        if deck_key(user_cards) != key:
            continue
        out.append(battle)

    return out


def _analyze_opponent_card_matchups(deck_cards: list[str], deck_battles: list[dict]) -> tuple[list[dict], list[dict]]:
    """Cards opponents played that this deck handles well or poorly."""
    card_stats: dict[str, dict[str, int]] = {}

    for battle in deck_battles:
        team = battle.get("team", [{}])[0]
        opponent = battle.get("opponent", [{}])[0]
        won = team.get("crowns", 0) > opponent.get("crowns", 0)
        for card in set(extract_deck(opponent)):
            stat = card_stats.setdefault(card, {"wins": 0, "total": 0})
            stat["total"] += 1
            if won:
                stat["wins"] += 1

    strong: list[dict] = []
    weak: list[dict] = []

    for card, stat in card_stats.items():
        total = stat["total"]
        if total < 2:
            continue
        wins = stat["wins"]
        wr = round(wins / total * 100, 1)
        counters = _effective_counters(deck_cards, card)
        label = card_name_ru(card, short=True) or card

        if wr >= 55 and counters:
            strong.append({
                "card": card,
                "card_ru": label,
                "winrate": wr,
                "games": total,
                "reason": f"Есть ответ ({', '.join(card_name_ru(c, short=True) or c for c in counters[:2])})",
            })
        elif wr <= 45 or (not counters and wr < 52):
            if counters:
                reason = f"Винрейт {wr:.0f}% — счётчик есть, но матчап слабый"
            else:
                rec = ", ".join(card_name_ru(c, short=True) or c for c in COUNTERS.get(card, [])[:3])
                reason = f"Винрейт {wr:.0f}% — нет прямого счётчика"
                if rec:
                    reason += f". Подойдут: {rec}"
            weak.append({
                "card": card,
                "card_ru": label,
                "winrate": wr,
                "games": total,
                "reason": reason,
            })

    strong.sort(key=lambda x: (-x["games"], -x["winrate"]))
    weak.sort(key=lambda x: (-x["games"], x["winrate"]))
    return strong[:8], weak[:8]


def _suggest_improvements(cards: list[str]) -> list[dict]:
    if len(cards) != 8:
        return []

    stats = analyze_deck(cards)
    deck_set = set(cards)
    suggestions: list[dict] = []

    def add(category: str, message: str, suggested: list[str], *, force: bool = False) -> None:
        missing = [c for c in suggested if c not in deck_set][:4]
        if not missing and not force:
            return
        suggestions.append({
            "category": category,
            "message": message,
            "suggested_cards": missing,
        })

    if not stats.spells:
        add(
            "spells",
            "В колоде нет заклинаний — сложнее контролировать поле и добивать башни",
            ["The Log", "Fireball", "Zap", "Arrows"],
        )
    elif len(stats.spells) == 1 and not any(s in _FINISHERS for s in stats.spells):
        add(
            "finishers",
            "Мало добивающих заклинаний — добавьте Fireball или Rocket для финиша",
            ["Fireball", "Rocket", "Lightning"],
        )

    if not stats.air_coverage:
        add(
            "anti_air",
            "Слабая защита от воздуха — Balloon и Minions будут опасны",
            _ANTI_AIR_SUGGESTIONS,
        )

    if not stats.splash_coverage:
        add(
            "splash",
            "Нет сплеша — спам и связки Goblin Gang / Skeleton Army сложно зачищать",
            _SPLASH_SUGGESTIONS,
        )

    if not stats.buildings:
        add(
            "defense",
            "Нет построек — Hog Rider и Balloon сложнее останавливать на мосту",
            _DEFENSE_SUGGESTIONS,
        )

    if not stats.point_target_coverage:
        add(
            "point_target",
            "Нет ответа на точечный урон — Стражи держат P.E.K.K.A, Мини P.E.K.K.A, Хог и подобных",
            _POINT_TARGET_SUGGESTIONS,
        )

    if not any(c in _SMALL_SPELLS for c in cards):
        add(
            "swarm",
            "Нет дешёвого ответа на спам — Zap или Ice Spirit сильно помогут в цикле",
            list(_SMALL_SPELLS),
        )

    if stats.avg_elixir > 4.2 and not any(get_card_role(c) == "cycle" for c in cards):
        add(
            "cycle",
            f"Тяжёлая колода ({stats.avg_elixir} эл.) — добавьте дешёвый цикл для давления",
            _CYCLE_SUGGESTIONS,
        )

    if len(stats.win_conditions) > 2:
        add(
            "focus",
            "Несколько win-condition — колода менее сфокусирована, сложнее циклировь к нужной карте",
            [],
            force=True,
        )

    if not stats.win_conditions:
        add(
            "win_condition",
            "Нет явного win-condition — добавьте карту для урона по башне",
            ["Hog Rider", "Balloon", "Royal Giant", "Miner", "Goblin Barrel"],
        )

    heavy_tanks = {"Golem", "Electro Giant", "Giant", "Lava Hound", "Elixir Golem"}
    if deck_set & heavy_tanks and len(stats.spells) < 2:
        add(
            "support",
            "Битдаун без второго заклинания — добавьте Poison или Lightning для поддержки пуша",
            ["Lightning", "Poison", "Zap"],
        )

    return suggestions


def build_mine_deck_stats(battles: list[dict], player_tag: str, cards: list[str]) -> dict:
    if len(cards) != 8:
        return {"error": "Нужна полная колода из 8 карт"}

    deck_battles = _filter_battles_for_deck(battles, player_tag, cards)
    wins = 0
    for battle in deck_battles:
        team = battle.get("team", [{}])[0]
        opponent = battle.get("opponent", [{}])[0]
        if team.get("crowns", 0) > opponent.get("crowns", 0):
            wins += 1
    total = len(deck_battles)
    losses = total - wins
    winrate = round(wins / total * 100, 1) if total else 0.0

    stats = analyze_deck(cards)
    strong, weak = _analyze_opponent_card_matchups(cards, deck_battles)
    improvements = _suggest_improvements(cards)
    balanced = len(improvements) == 0

    sample_note = ""
    if total == 0:
        sample_note = "Нет боёв с этой колодой в истории — статистика по матчапам недоступна"
    elif total < 5:
        sample_note = f"Мало данных ({total} боёв) — выводы могут быть неточными"

    return {
        "name": _guess_deck_name(cards),
        "cards": cards,
        "wins": wins,
        "losses": losses,
        "total_games": total,
        "winrate": winrate,
        "avg_elixir": stats.avg_elixir,
        "win_conditions": stats.win_conditions,
        "strong_against": strong,
        "weak_against": weak,
        "improvements": improvements,
        "balanced": balanced,
        "sample_note": sample_note,
    }

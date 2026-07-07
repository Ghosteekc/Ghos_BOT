"""Side-by-side deck comparison with per-card matchup analysis.

Counter data is curated from common Clash Royale meta (RoyaleAPI guides, deck guides,
in-game roles). The official API does not expose card-vs-card counters.
"""

from __future__ import annotations

from bot.services.card_data import COUNTERS, WIN_CONDITIONS, get_card_role
from bot.services.card_names_ru import card_name_ru
from bot.services.deck_analyzer import analyze_deck, calculate_matchup_score, find_opponent_threats

_ANTI_AIR = {
    "Musketeer", "Wizard", "Executioner", "Inferno Dragon", "Mini P.E.K.K.A",
    "Mega Minion", "Electro Wizard", "Hunter", "Inferno Tower", "Tesla",
    "Archers", "Bats", "Minions", "Phoenix", "Firecracker", "Ice Wizard",
    "Baby Dragon",
}

_AIR_OFFENSE = {
    "Minions", "Minion Horde", "Baby Dragon", "Mega Minion", "Inferno Dragon",
    "Balloon", "Lava Hound", "Bats", "Skeleton Dragons", "Phoenix",
    "Flying Machine",
}

_SPLASH = {
    "Wizard", "Baby Dragon", "Valkyrie", "Bowler", "Executioner",
    "Fireball", "Arrows", "Poison", "Earthquake", "Electro Dragon",
    "Goblin Demolisher", "Magic Archer",
}

_SWARM = {
    "Skeletons", "Goblins", "Goblin Gang", "Minion Horde", "Bats",
    "Skeleton Army", "Guards", "Barbarians", "Spear Goblins", "Wall Breakers",
    "Ice Spirit", "Electro Spirit", "Fire Spirit",
}

_BUILDING_PULL = {"Hog Rider", "Battle Ram", "Giant", "Golem", "Royal Giant", "Goblin Drill", "Miner"}

_HEAVY_TANKS = {
    "P.E.K.K.A", "Mega Knight", "Giant", "Golem", "Electro Giant",
    "Giant Skeleton", "Sparky", "Elite Barbarians", "Royal Giant", "Boss Bandit",
}

_RONIN_TARGETS = {
    "P.E.K.K.A", "Mega Knight", "Prince", "Boss Bandit", "Giant",
    "Golem", "Electro Giant", "Sparky", "Elite Barbarians", "Rune Giant",
}

_SMALL_SPELLS = {
    "The Log", "Zap", "Arrows", "Barbarian Barrel", "Giant Snowball",
    "Electro Spirit", "Fire Spirit",
}

_BIG_SPELLS = {"Fireball", "Rocket", "Lightning", "Poison", "Earthquake", "Freeze"}


def _label(card: str) -> str:
    return card_name_ru(card, short=True) or card


def _labels(cards: list[str]) -> str:
    return ", ".join(_label(c) for c in cards[:3])


def _has_air_offense(cards: list[str]) -> bool:
    return bool(set(cards) & _AIR_OFFENSE)


def _swarm_cards(deck: list[str]) -> list[str]:
    return [c for c in deck if c in _SWARM or get_card_role(c) in ("swarm", "cycle")]


def _has_swarm(deck: list[str]) -> bool:
    swarm = _swarm_cards(deck)
    return len(swarm) >= 2 or any(c in _SWARM for c in deck)


def _cards_that_counter(target: str, deck: list[str]) -> list[str]:
    known = COUNTERS.get(target, [])
    return [c for c in deck if c in known and c != target]


def _cards_we_counter(card: str, opp_deck: list[str]) -> list[str]:
    """Opponent cards that `card` hard-counters."""
    return [c for c in opp_deck if card in COUNTERS.get(c, []) and c != card]


def _recommended_counters(threat: str, deck: list[str], *, limit: int = 3) -> list[str]:
    deck_set = set(deck)
    return [c for c in COUNTERS.get(threat, []) if c not in deck_set][:limit]


def _dedupe(items: list[str], limit: int = 6) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out[:limit]


def _note(card: str, tone: str, text: str) -> dict:
    return {"card": card, "card_ru": _label(card), "tone": tone, "text": text}


def _analyze_own_card(card: str, own_deck: list[str], opp_deck: list[str]) -> dict:
    """Value of our card against opponent deck."""
    label = _label(card)
    role = get_card_role(card)
    opp_counters = _cards_that_counter(card, opp_deck)
    we_counter = _cards_we_counter(card, opp_deck)
    opp_buildings = [c for c in opp_deck if get_card_role(c) == "building"]
    opp_threats = find_opponent_threats(opp_deck)
    is_win_con = card in WIN_CONDITIONS or role == "win_condition"

    if card == "Ronin":
        targets = [c for c in opp_deck if c in _RONIN_TARGETS]
        if targets:
            return _note(card, "good", f"{label} — силён против {_labels(targets)} соперника")
        return _note(
            card,
            "warn",
            f"{label} — против этой колоды мало тяжёлых целей, ценность ниже обычного",
        )

    if we_counter:
        key = [c for c in we_counter if c in WIN_CONDITIONS or c in {"Witch", "Mother Witch", "Mega Knight"}]
        targets = key or we_counter
        return _note(card, "good", f"{label} — контрит {_labels(targets)} соперника")

    if card in _SMALL_SPELLS:
        opp_swarm = _swarm_cards(opp_deck)
        if len(opp_swarm) >= 2:
            return _note(card, "good", f"{label} — зачищает рой соперника ({_labels(opp_swarm[:2])})")
        return _note(card, "warn", f"{label} — у соперника мало роя, заклинание менее полезно")

    if is_win_con:
        text = f"{label} — {'сильная' if card in _HEAVY_TANKS else 'хорошая'} атакующая карта"
        if opp_counters:
            return _note(card, "warn", f"{text}, но соперник контрит через {_labels(opp_counters)}")
        if opp_buildings and card in _BUILDING_PULL:
            return _note(card, "warn", f"{text}, но соперник ставит {_labels(opp_buildings)} в центр")
        return _note(card, "good", f"{text} — сопернику сложнее остановить")

    if role == "building":
        pull = [t for t in opp_threats if t in _BUILDING_PULL]
        if pull:
            return _note(card, "good", f"{label} — здание против {_labels(pull)} соперника")
        return _note(card, "neutral", f"{label} — здание для обороны, но у соперника мало прямых пушей")

    if role == "splash" and _has_swarm(opp_deck):
        return _note(card, "good", f"{label} — сплеш против роя соперника")

    if card in _ANTI_AIR and _has_air_offense(opp_deck):
        air = [c for c in opp_deck if c in _AIR_OFFENSE][:2]
        return _note(card, "good", f"{label} — защита от воздуха ({_labels(air)})")

    if card in _BIG_SPELLS:
        return _note(card, "neutral", f"{label} — добивание и контроль, следите за эликсиром")

    if role in ("cycle", "swarm"):
        return _note(card, "neutral", f"{label} — цикл и давление по эликсиру")

    if card in {"Tornado", "Ice Golem"}:
        return _note(card, "good", f"{label} — контроль и связка с атакой")

    return _note(card, "neutral", f"{label} — {_role_label(role)} в вашей колоде")


def _analyze_enemy_card(card: str, enemy_deck: list[str], your_deck: list[str]) -> dict:
    """Threat of opponent card vs our deck."""
    label = _label(card)
    role = get_card_role(card)
    your_counters = _cards_that_counter(card, your_deck)
    your_buildings = [c for c in your_deck if get_card_role(c) == "building"]
    is_win_con = card in WIN_CONDITIONS or role == "win_condition"

    if card in _SMALL_SPELLS:
        your_swarm = _swarm_cards(your_deck)
        if len(your_swarm) < 2:
            return _note(
                card,
                "good",
                f"{label} — почти бесполезен: у вас нет роя для зачистки",
            )
        return _note(
            card,
            "warn",
            f"{label} — зачищает ваш рой ({_labels(your_swarm[:3])})",
        )

    if card == "Ronin":
        your_tanks = [c for c in your_deck if c in _HEAVY_TANKS or c in _RONIN_TARGETS]
        if your_tanks:
            return _note(card, "warn", f"{label} — опасен против ваших {_labels(your_tanks)}")
        return _note(card, "good", f"{label} — у вас нет тяжёлых целей, Ронин соперника слабее")

    if your_counters:
        if len(your_counters) >= 2 or (your_buildings and card in _BUILDING_PULL):
            parts = _labels(your_counters)
            if your_buildings and card in _BUILDING_PULL:
                parts = f"{parts}, {_labels(your_buildings)}"
            return _note(card, "good", f"{label} — ваши {parts} держат эту угрозу")
        return _note(
            card,
            "warn",
            f"{label} — {_attack_label(card)}, ваш {_labels(your_counters)} помогает, но одного мало",
        )

    if is_win_con:
        rec = _recommended_counters(card, your_deck) or list(COUNTERS.get(card, [])[:3])
        text = f"{label} — {_attack_label(card)}"
        if _has_air_offense([card]) and bool(set(your_deck) & _ANTI_AIR):
            air = [c for c in your_deck if c in _ANTI_AIR][:2]
            return _note(card, "warn", f"{text}, частичный ответ — {_labels(air)}, усилите ПВО")
        if rec:
            return _note(card, "bad", f"{text}, прямого ответа нет — добавьте {_labels(rec)}")
        return _note(card, "bad", f"{text}, у вас нет надёжного счётчика")

    if role == "building":
        breakers = [c for c in your_deck if c in {"Earthquake", "Miner", "Royal Giant", "Rocket", "Lightning"}]
        if breakers:
            return _note(card, "warn", f"{label} — здание соперника, ломается {_labels(breakers)}")
        return _note(card, "neutral", f"{label} — оборонительное здание соперника")

    if role == "splash" and _has_swarm(your_deck):
        return _note(card, "warn", f"{label} — сплеш зачищает ваш рой")

    if card in {"Witch", "Mother Witch"}:
        return _note(card, "warn", f"{label} — поддержка с роями, нужен сплеш или Valkyrie")

    if card in _BIG_SPELLS:
        return _note(card, "neutral", f"{label} — заклинание для добивания и контроля")

    return _note(card, "neutral", f"{label} — {_role_label(role)} в колоде соперника")


def _role_label(role: str) -> str:
    labels = {
        "win_condition": "атакующая карта",
        "tank": "танк",
        "splash": "сплеш",
        "building": "здание",
        "spell": "заклинание",
        "cycle": "цикл",
        "support": "поддержка",
        "swarm": "рой",
        "air": "воздух",
    }
    return labels.get(role, "карта")


def _attack_label(card: str) -> str:
    if card in _HEAVY_TANKS:
        return "сильная атакующая карта"
    if card in WIN_CONDITIONS:
        return "хорошая атакующая карта"
    return "угроза"


def _build_card_notes(user_cards: list[str], ref_cards: list[str]) -> tuple[list[dict], list[dict]]:
    user_notes = [_analyze_own_card(c, user_cards, ref_cards) for c in user_cards]
    ref_notes = [_analyze_enemy_card(c, ref_cards, user_cards) for c in ref_cards]
    return user_notes, ref_notes


def compare_decks(user_cards: list[str], ref_cards: list[str]) -> dict:
    user_better: list[str] = []
    user_worse: list[str] = []
    ref_better: list[str] = []
    ref_worse: list[str] = []

    if len(user_cards) != 8 or len(ref_cards) != 8:
        return {
            "user_better": [],
            "user_worse": ["Нужна полная колода из 8 карт для сравнения"],
            "reference_better": [],
            "reference_worse": [],
            "user_card_notes": [],
            "reference_card_notes": [],
            "matchup_score": 50.0,
            "opponent_matchup_score": 50.0,
        }

    u = analyze_deck(user_cards)
    r = analyze_deck(ref_cards)
    user_notes, ref_notes = _build_card_notes(user_cards, ref_cards)

    for threat in find_opponent_threats(ref_cards):
        u_cnt = _cards_that_counter(threat, user_cards)
        t = _label(threat)
        if u_cnt:
            user_better.append(f"Есть ответ на {t} ({_labels(u_cnt)})")
        else:
            user_worse.append(f"Сложнее остановить {t} соперника")
            ref_better.append(f"{t} этой колоды сложнее остановить")

    for threat in find_opponent_threats(user_cards):
        r_cnt = _cards_that_counter(threat, ref_cards)
        t = _label(threat)
        if r_cnt:
            ref_better.append(f"Есть ответ на ваш {t} ({_labels(r_cnt)})")
            user_worse.append(f"Ваш {t} встречает контр ({_labels(r_cnt)})")
        else:
            ref_worse.append(f"Слабее против вашего {t}")
            user_better.append(f"Ваш {t} труднее остановить")

    for card in ref_cards:
        counters = _cards_that_counter(card, user_cards)
        if card in {"Witch", "Mother Witch"} and counters:
            user_better.append(f"Ваша {_labels(counters)} контрит {_label(card)} соперника")

    for card in ref_cards:
        if card in _SMALL_SPELLS and not _has_swarm(user_cards):
            user_better.append(f"{_label(card)} соперника почти бесполезен — нет вашего роя")

    if _has_air_offense(user_cards) or _has_air_offense(ref_cards):
        u_air = len(set(user_cards) & _ANTI_AIR)
        r_air = len(set(ref_cards) & _ANTI_AIR)
        if u_air > r_air:
            user_better.append(f"Лучше защита от воздуха ({u_air} vs {r_air} карт)")
            ref_worse.append(f"Слабее против воздуха ({r_air} vs {u_air} карт)")
        elif r_air > u_air:
            user_worse.append(f"Слабее против воздуха ({u_air} vs {r_air} карт)")
            ref_better.append(f"Лучше защита от воздуха ({r_air} vs {u_air} карт)")

    if _has_swarm(ref_cards) or _has_swarm(user_cards):
        u_spl = len(set(user_cards) & _SPLASH)
        r_spl = len(set(ref_cards) & _SPLASH)
        if u_spl > r_spl and _has_swarm(ref_cards):
            user_better.append("Лучше сплеш против роя соперника")
            ref_worse.append("Слабее против роя")
        elif r_spl > u_spl and _has_swarm(user_cards):
            ref_better.append("Лучше сплеш против вашего роя")
            user_worse.append("Ваш рой легче зачищается")

    if u.avg_elixir + 0.3 < r.avg_elixir:
        user_better.append(f"Быстрее цикл ({u.avg_elixir} vs {r.avg_elixir} эликсира)")
        ref_worse.append(f"Медленнее цикл ({r.avg_elixir} vs {u.avg_elixir} эликсира)")
    elif r.avg_elixir + 0.3 < u.avg_elixir:
        user_worse.append(f"Медленнее цикл ({u.avg_elixir} vs {r.avg_elixir} эликсира)")
        ref_better.append(f"Быстрее цикл ({r.avg_elixir} vs {u.avg_elixir} эликсира)")

    u_build, r_build = len(u.buildings), len(r.buildings)
    if u_build > r_build and r_build == 0:
        user_better.append("Есть постройка для обороны")
        ref_worse.append("Нет построек — сложнее держать оборону")
    elif r_build > u_build and u_build == 0:
        user_worse.append("Нет построек для обороны")
        ref_better.append("Есть постройка для обороны")

    if not user_better and not user_worse and not ref_better and not ref_worse:
        user_better.append("Колоды сбалансированы — явных перекосов нет")

    return {
        "user_better": _dedupe(user_better),
        "user_worse": _dedupe(user_worse),
        "reference_better": _dedupe(ref_better),
        "reference_worse": _dedupe(ref_worse),
        "user_card_notes": user_notes,
        "reference_card_notes": ref_notes,
        "matchup_score": round(calculate_matchup_score(user_cards, ref_cards), 1),
        "opponent_matchup_score": round(calculate_matchup_score(ref_cards, user_cards), 1),
    }

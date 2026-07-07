"""Side-by-side deck comparison — relative strengths vs the other deck."""

from __future__ import annotations

from bot.services.card_data import COUNTERS, WIN_CONDITIONS, get_card_role
from bot.services.card_names_ru import card_name_ru
from bot.services.deck_analyzer import analyze_deck, calculate_matchup_score, find_opponent_threats

_ANTI_AIR = {
    "Musketeer", "Wizard", "Executioner", "Inferno Dragon", "Mini P.E.K.K.A",
    "Mega Minion", "Electro Wizard", "Hunter", "Inferno Tower", "Tesla",
    "Archers", "Bats", "Minions", "Phoenix", "Firecracker", "Ice Wizard",
    "Baby Dragon", "Musketeer",
}

_AIR_OFFENSE = {
    "Minions", "Minion Horde", "Baby Dragon", "Mega Minion", "Inferno Dragon",
    "Balloon", "Lava Hound", "Bats", "Skeleton Dragons", "Phoenix",
    "Flying Machine", "Mega Minion",
}

_SPLASH = {
    "Wizard", "Baby Dragon", "Valkyrie", "Bowler", "Executioner",
    "Fireball", "Arrows", "Poison", "Earthquake", "Electro Dragon",
    "Goblin Demolisher", "Magic Archer",
}

_SWARM = {
    "Skeletons", "Goblins", "Goblin Gang", "Minion Horde", "Bats",
    "Skeleton Army", "Guards", "Barbarians", "Spear Goblins", "Wall Breakers",
}

_BUILDING_COUNTERS = {"Hog Rider", "Battle Ram", "Giant", "Golem", "Royal Giant", "Goblin Drill", "Miner"}

_ROLE_RU = {
    "win_condition": "атакующая карта",
    "tank": "танк",
    "splash": "сплеш",
    "building": "здание для обороны",
    "spell": "заклинание",
    "cycle": "карта для цикла",
    "support": "поддержка",
    "swarm": "рой",
    "air": "воздушная карта",
}

_HEAVY_WIN_CONS = {
    "Balloon", "Golem", "Lava Hound", "Giant", "P.E.K.K.A", "Electro Giant",
    "Royal Giant", "Sparky", "Three Musketeers",
}


def _label(card: str) -> str:
    return card_name_ru(card, short=True) or card


def _labels(cards: list[str]) -> str:
    return ", ".join(_label(c) for c in cards[:3])


def _air_defense_count(cards: list[str]) -> int:
    return len(set(cards) & _ANTI_AIR)


def _has_air_offense(cards: list[str]) -> bool:
    return bool(set(cards) & _AIR_OFFENSE)


def _has_swarm(cards: list[str]) -> bool:
    return bool(set(cards) & _SWARM)


def _splash_count(cards: list[str]) -> int:
    return len(set(cards) & _SPLASH)


def _effective_counters(deck: list[str], threat: str) -> list[str]:
    """Cards in deck that counter threat (excluding the threat card itself)."""
    counters = COUNTERS.get(threat, [])
    return [c for c in counters if c in deck and c != threat]


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


def _attack_phrase(card: str) -> str:
    if card in _HEAVY_WIN_CONS:
        return "сильная атакующая карта"
    if card in WIN_CONDITIONS or get_card_role(card) == "win_condition":
        return "хорошая атакующая карта"
    return _ROLE_RU.get(get_card_role(card), "карта")


def _analyze_own_card(card: str, own_deck: list[str], opp_deck: list[str]) -> dict:
    """How useful is this card in your deck against the other deck."""
    label = _label(card)
    role = get_card_role(card)
    is_threat = card in WIN_CONDITIONS or role == "win_condition"
    opp_counters = _effective_counters(opp_deck, card)
    opp_buildings = [c for c in opp_deck if get_card_role(c) == "building"]
    opp_threats = find_opponent_threats(opp_deck)
    counters_threats = [
        t for t in opp_threats
        if card in COUNTERS.get(t, []) and card in own_deck
    ]

    tone = "neutral"
    text = ""

    if is_threat:
        text = f"{label} — {_attack_phrase(card)}"
        if opp_counters:
            tone = "warn"
            text += f", но у соперника есть {_labels(opp_counters)} против неё"
        elif opp_buildings and card in _BUILDING_COUNTERS:
            tone = "warn"
            text += f", но соперник может поставить {_labels(opp_buildings)} в центр"
        else:
            tone = "good"
            text += ", сопернику сложнее остановить эту угрозу"
    elif role == "building":
        tone = "good" if any(t in _BUILDING_COUNTERS for t in opp_threats) else "neutral"
        text = f"{label} — здание для обороны"
        if opp_threats:
            text += f", помогает держать {_labels(opp_threats)} соперника"
    elif counters_threats:
        tone = "good"
        text = f"{label} — ответ на {_labels(counters_threats)} соперника"
    elif role == "splash" and _has_swarm(opp_deck):
        tone = "good"
        text = f"{label} — сплеш, эффективен против роя соперника"
    elif (card in _ANTI_AIR or role == "air") and _has_air_offense(opp_deck):
        tone = "good"
        text = f"{label} — защита от воздуха соперника"
    elif role == "spell":
        text = f"{label} — заклинание для контроля поля и добивания башен"
    elif role in ("cycle", "swarm"):
        text = f"{label} — {_ROLE_RU.get(role, 'карта')} для быстрого цикла"
    else:
        text = f"{label} — {_ROLE_RU.get(role, 'поддержка')} в вашей колоде"

    return {"card": card, "card_ru": label, "tone": tone, "text": text}


def _analyze_enemy_card(card: str, enemy_deck: list[str], your_deck: list[str]) -> dict:
    """How dangerous is opponent card against your deck + what to do."""
    label = _label(card)
    role = get_card_role(card)
    is_threat = card in WIN_CONDITIONS or role == "win_condition"
    your_counters = _effective_counters(your_deck, card)
    your_buildings = [c for c in your_deck if get_card_role(c) == "building"]
    partial_air = card in _AIR_OFFENSE and bool(set(your_deck) & _ANTI_AIR) and not your_counters

    tone = "neutral"
    text = ""

    if is_threat:
        text = f"{label} — {_attack_phrase(card)}"
        if your_counters:
            if len(your_counters) >= 2 or (your_buildings and card in _BUILDING_COUNTERS):
                tone = "warn"
                parts = _labels(your_counters)
                if your_buildings and card in _BUILDING_COUNTERS:
                    parts = f"{parts}, {_labels(your_buildings)}"
                text += f", у вас есть {parts} для защиты — важен тайминг"
            else:
                tone = "bad"
                text += f", у вас есть {_labels(your_counters)} для дефа, но этого недостаточно"
                rec = _recommended_counters(card, your_deck)
                if rec:
                    text += f", рекомендуется {_labels(rec)}"
        elif partial_air:
            tone = "bad"
            air_cards = [c for c in your_deck if c in _ANTI_AIR][:2]
            text += f", у вас есть {_labels(air_cards)} для дефа, но этого недостаточно"
            rec = _recommended_counters(card, your_deck) or ["Inferno Tower", "Musketeer", "Tesla"]
            text += f", рекомендуется {_labels(rec)}"
        else:
            tone = "bad"
            rec = _recommended_counters(card, your_deck) or list(COUNTERS.get(card, [])[:3])
            if rec:
                text += f", у вас нет надёжного ответа — рекомендуется {_labels(rec)}"
            else:
                text += ", у вас нет прямого счётчика — усилите оборону"
    elif role == "building":
        your_breakers = [
            c for c in your_deck
            if c in {"Earthquake", "Miner", "Royal Giant", "Rocket", "Lightning"}
        ]
        if your_breakers:
            tone = "warn"
            text = f"{label} — здание соперника, ваш {_labels(your_breakers)} может его ломать"
        else:
            tone = "neutral"
            text = f"{label} — здание для обороны соперника"
    elif role == "splash" and _has_swarm(your_deck):
        tone = "warn"
        text = f"{label} — сплеш соперника зачищает ваш рой"
    elif (card in _ANTI_AIR or role == "air") and _has_air_offense(your_deck):
        tone = "warn"
        text = f"{label} — воздушная защита соперника против вашего воздуха"
    elif role == "spell":
        text = f"{label} — заклинание соперника для контроля и добивания"
    else:
        text = f"{label} — {_ROLE_RU.get(role, 'поддержка')} в колоде соперника"

    return {"card": card, "card_ru": label, "tone": tone, "text": text}


def _build_card_notes(user_cards: list[str], ref_cards: list[str]) -> tuple[list[dict], list[dict]]:
    user_notes = [_analyze_own_card(c, user_cards, ref_cards) for c in user_cards]
    ref_notes = [_analyze_enemy_card(c, ref_cards, user_cards) for c in ref_cards]
    return user_notes, ref_notes


def compare_decks(user_cards: list[str], ref_cards: list[str]) -> dict[str, list[str]]:
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

    # --- Win conditions: can each deck stop the other's plan? ---
    for threat in find_opponent_threats(ref_cards):
        u_cnt = _effective_counters(user_cards, threat)
        t = _label(threat)
        if u_cnt:
            user_better.append(f"Есть ответ на {t} ({_labels(u_cnt)})")
        else:
            user_worse.append(f"Сложнее остановить {t} соперника")
            ref_better.append(f"{t} этой колоды сложнее остановить")

    for threat in find_opponent_threats(user_cards):
        r_cnt = _effective_counters(ref_cards, threat)
        t = _label(threat)
        if r_cnt:
            ref_better.append(f"Есть ответ на ваш {t} ({_labels(r_cnt)})")
            user_worse.append(f"Ваш {t} встречает контр ({_labels(r_cnt)})")
        else:
            ref_worse.append(f"Слабее против вашего {t}")
            user_better.append(f"Ваш {t} труднее остановить")

    # --- Air: only if at least one deck pushes air ---
    if _has_air_offense(user_cards) or _has_air_offense(ref_cards):
        u_air = _air_defense_count(user_cards)
        r_air = _air_defense_count(ref_cards)
        if u_air > r_air:
            user_better.append(f"Лучше защита от воздуха ({u_air} vs {r_air} карт)")
            ref_worse.append(f"Слабее против воздуха ({r_air} vs {u_air} карт)")
        elif r_air > u_air:
            user_worse.append(f"Слабее против воздуха ({u_air} vs {r_air} карт)")
            ref_better.append(f"Лучше защита от воздуха ({r_air} vs {u_air} карт)")

    # --- Swarm / splash: only if opponent uses swarm ---
    if _has_swarm(ref_cards) or _has_swarm(user_cards):
        u_spl = _splash_count(user_cards)
        r_spl = _splash_count(ref_cards)
        if u_spl > r_spl and _has_swarm(ref_cards):
            user_better.append("Лучше сплеш против роя соперника")
            ref_worse.append("Слабее против роя")
        elif r_spl > u_spl and _has_swarm(user_cards):
            ref_better.append("Лучше сплеш против вашего роя")
            user_worse.append("Ваш рой легче зачищается")

    # --- Spells (relative) ---
    u_spells = len(u.spells)
    r_spells = len(r.spells)
    if u_spells > r_spells + 1:
        user_better.append(f"Больше заклинаний ({u_spells} vs {r_spells})")
        ref_worse.append(f"Меньше заклинаний ({r_spells} vs {u_spells})")
    elif r_spells > u_spells + 1:
        user_worse.append(f"Меньше заклинаний ({u_spells} vs {r_spells})")
        ref_better.append(f"Больше заклинаний ({r_spells} vs {u_spells})")

    # --- Cycle speed ---
    if u.avg_elixir + 0.3 < r.avg_elixir:
        user_better.append(f"Быстрее цикл ({u.avg_elixir} vs {r.avg_elixir} эликсира)")
        ref_worse.append(f"Медленнее цикл ({r.avg_elixir} vs {u.avg_elixir} эликсира)")
    elif r.avg_elixir + 0.3 < u.avg_elixir:
        user_worse.append(f"Медленнее цикл ({u.avg_elixir} vs {r.avg_elixir} эликсира)")
        ref_better.append(f"Быстрее цикл ({r.avg_elixir} vs {u.avg_elixir} эликсира)")

    # --- Buildings ---
    u_build = len(u.buildings)
    r_build = len(r.buildings)
    if u_build > r_build and r_build == 0:
        user_better.append("Есть постройка для обороны")
        ref_worse.append("Нет построек — сложнее держать оборону")
    elif r_build > u_build and u_build == 0:
        user_worse.append("Нет построек для обороны")
        ref_better.append("Есть постройка для обороны")
    elif r_build > u_build:
        ref_better.append("Больше построек для обороны")
        user_worse.append("Меньше построек для обороны")
    elif u_build > r_build:
        user_better.append("Больше построек для обороны")
        ref_worse.append("Меньше построек для обороны")

    # --- Win-condition count stability ---
    if len(u.win_conditions) >= 2 and len(r.win_conditions) <= 1:
        user_worse.append("Несколько win-condition — менее сфокусированная колода")
        ref_better.append("Один чёткий план победы")

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

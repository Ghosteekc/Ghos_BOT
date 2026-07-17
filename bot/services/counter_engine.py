from bot.services.card_data import (
    ARENA_CARD_POOL,
    CARD_META,
    POINT_TARGET_COUNTERS,
    WIN_CONDITIONS,
    get_card_elixir,
    get_card_role,
    is_point_target_threat,
    is_spam_card,
)
from bot.services.card_names_ru import card_name_ru
from bot.services.card_matchups import card_counters_target, synergy_partners
from bot.services.deck_analyzer import analyze_deck, extract_deck, find_opponent_threats
from bot.services.deck_improver import improve_player_deck

_AIR_OFFENSE = {
    "Minions", "Minion Horde", "Baby Dragon", "Mega Minion", "Inferno Dragon",
    "Balloon", "Lava Hound", "Bats", "Skeleton Dragons", "Phoenix",
    "Flying Machine", "Electro Dragon",
}

_ANTI_AIR = {
    "Musketeer", "Wizard", "Executioner", "Inferno Dragon", "Mini P.E.K.K.A",
    "Mega Minion", "Electro Wizard", "Hunter", "Inferno Tower", "Tesla",
    "Archers", "Bats", "Minions", "Phoenix", "Firecracker", "Ice Wizard",
    "Baby Dragon",
}

_FLYING_TROOPS = {
    "Minions", "Minion Horde", "Mega Minion", "Inferno Dragon", "Baby Dragon",
    "Balloon", "Lava Hound", "Bats", "Skeleton Dragons", "Phoenix",
    "Flying Machine", "Electro Dragon",
}

_MAX_WIN_CONDITIONS = 1
_MAX_SPELLS = 2
_MAX_BUILDINGS = 1

_SPELL_KILLERS = {
    "Zap", "The Log", "Arrows", "Barbarian Barrel", "Giant Snowball",
    "Rage", "Fireball", "Poison", "Earthquake", "Lightning",
}

_REFLECT_CHAMPIONS = {"Monk", "Ronin"}

_PUSH_THREATS = {
    "Hog Rider", "Giant", "Golem", "Battle Ram", "Royal Hogs", "Goblin Giant",
    "Electro Giant", "P.E.K.K.A", "Lava Hound", "Miner",
}

_EXTRA_THREATS = {
    "Giant", "Skeleton Barrel", "Balloon", "Mega Knight", "Electro Giant",
    "P.E.K.K.A", "Dark Prince", "Valkyrie", "Witch", "Royal Giant", "Goblin Barrel",
}

_SUPPORT_THREATS = frozenset({
    "Wizard", "Executioner", "Night Witch", "Witch", "Mother Witch",
    "Baby Dragon", "Electro Wizard", "Mega Minion", "Hunter", "Firecracker",
    "Ice Wizard", "Magic Archer", "Lumberjack", "Mini P.E.K.K.A",
})

_CHAMPION_THREATS = frozenset({
    "Little Prince", "Monk", "Golden Knight", "Archer Queen",
    "Skeleton King", "Mighty Miner", "Boss Bandit", "Ronin",
})

_SPAM_THREATS = frozenset({
    "Skeleton Army", "Goblin Gang", "Minion Horde", "Guards", "Barbarians",
    "Goblins", "Skeletons", "Bats",
})

_OPP_SPLASH = frozenset({
    "Wizard", "Executioner", "Witch", "Night Witch", "Baby Dragon",
    "Bowler", "Valkyrie", "Fireball", "Poison", "Arrows", "Royal Delivery",
})

_SPLASH_VULNERABLE = frozenset({
    "Mega Knight", "Mini P.E.K.K.A", "P.E.K.K.A", "Wizard", "Witch",
    "Night Witch", "Skeleton Army", "Goblin Gang", "Barbarians",
    "Elite Barbarians", "Mega Minion", "Minion Horde",
})

# Тяжёлые атакующие карты — не подходят как контр-пики
_COUNTER_DECK_BANNED = frozenset({
    "Mega Knight", "P.E.K.K.A", "Golem", "Giant", "Electro Giant",
    "Lava Hound", "Sparky", "Elixir Golem", "Boss Bandit", "Rune Giant",
    "Three Musketeers", "Elite Barbarians", "Wall Breakers", "Goblin Giant",
    "Skeleton Barrel", "Battle Ram", "Ram Rider", "Monk", "Ronin",
})

_MIN_COUNTER_SCORE = 2.0


def _card_ru(name: str) -> str:
    return card_name_ru(name, short=True) or name


def suggest_counter_deck(
    opponent_deck: list[str],
    arena_id: int | None = None,
    preferred_cards: list[str] | None = None,
    user_deck: list[str] | None = None,
    trophies: int | None = None,
) -> list[str]:
    """Собрать контр-колоду под угрозы соперника с учётом его заклинаний и структуры."""
    preferred_cards = preferred_cards or []
    pool = _get_arena_pool(arena_id, trophies)
    pool.update(opponent_deck)
    pool.update(preferred_cards)
    pool.update(user_deck or [])

    threats = _key_threats(opponent_deck)
    opp_has_air = _deck_has_air(opponent_deck)

    ranked: list[tuple[float, str]] = []
    for card in pool:
        if card in opponent_deck:
            continue
        if card in _COUNTER_DECK_BANNED:
            continue
        if not opp_has_air and _skip_without_opponent_air(card):
            continue
        score = _score_counter_card(card, opponent_deck, threats, preferred_cards)
        if score >= _MIN_COUNTER_SCORE:
            ranked.append((score, card))
    ranked.sort(key=lambda x: (-x[0], x[1]))

    deck: list[str] = []
    for _, card in ranked:
        if len(deck) >= 8:
            break
        if _can_add(card, deck):
            deck.append(card)

    deck = _ensure_spell(deck, pool, opponent_deck, threats)
    deck = _ensure_win_condition(deck, pool, preferred_cards)
    deck = _ensure_building(deck, pool, opponent_deck)
    deck = _trim_excess(deck, opponent_deck, threats, preferred_cards)
    deck = _fill_counter_gaps(deck, ranked, pool, opponent_deck)
    deck = _trim_weak_cards(deck, ranked, opponent_deck, threats, preferred_cards)

    if len(deck) < 8:
        deck = _fill_counter_gaps(deck, ranked, pool, opponent_deck)
        for _, card in ranked:
            if len(deck) >= 8:
                break
            if card in deck or card in opponent_deck:
                continue
            if _can_add(card, deck):
                deck.append(card)

    return deck[:8]


_GROUND_COUNTERS = {"Inferno Tower", "Tesla", "Cannon", "Tombstone"}

_GROUND_ANTI_AIR = frozenset({
    "Musketeer", "Hunter", "Archers", "Firecracker", "Wizard", "Executioner",
    "Bowler", "Valkyrie", "Mini P.E.K.K.A",
})


def _skip_without_opponent_air(card: str) -> bool:
    """Не брать чистый анти-воздух, если у соперника нет воздуха."""
    if card in _GROUND_COUNTERS or card in _GROUND_ANTI_AIR:
        return False
    return _is_anti_air_specialist(card) or card in _FLYING_TROOPS


def _key_threats(opponent_deck: list[str]) -> list[str]:
    threats: list[str] = []
    danger = (
        _EXTRA_THREATS | _SUPPORT_THREATS | _CHAMPION_THREATS | _SPAM_THREATS | _AIR_OFFENSE
    )

    for card in opponent_deck:
        if card in WIN_CONDITIONS or get_card_role(card) == "win_condition":
            threats.append(card)

    for card in opponent_deck:
        if card in danger and card not in threats:
            threats.append(card)

    if _deck_has_air(opponent_deck):
        for card in opponent_deck:
            if card in _AIR_OFFENSE and card not in threats:
                threats.append(card)

    return list(dict.fromkeys(threats))


def _monk_worth_it(opponent_deck: list[str]) -> bool:
    if not set(opponent_deck) & {"Fireball", "Rocket"}:
        return False
    if set(opponent_deck) & {"Giant", "Golem", "Lava Hound", "Electro Giant", "Goblin Giant"}:
        return False
    return True


def _swarm_hard_countered(card: str, opponent_deck: list[str]) -> bool:
    if not (is_spam_card(card) or card in {"Skeleton Army", "Goblin Gang", "Minion Horde"}):
        return False
    return bool(set(opponent_deck) & _SPELL_KILLERS)


def _deck_role_counts(deck: list[str]) -> dict[str, int]:
    return {
        "win": sum(1 for c in deck if c in WIN_CONDITIONS or get_card_role(c) == "win_condition"),
        "spell": sum(1 for c in deck if get_card_role(c) == "spell"),
        "building": sum(1 for c in deck if get_card_role(c) == "building"),
    }


def _can_add(card: str, deck: list[str]) -> bool:
    if card in deck:
        return False
    counts = _deck_role_counts(deck)
    role = get_card_role(card)
    if card in WIN_CONDITIONS or role == "win_condition":
        return counts["win"] < _MAX_WIN_CONDITIONS
    if role == "spell":
        return counts["spell"] < _MAX_SPELLS
    if role == "building":
        return counts["building"] < _MAX_BUILDINGS
    return True


def _opponent_splash_count(opponent_deck: list[str]) -> int:
    return sum(1 for c in opponent_deck if c in _OPP_SPLASH)


def _score_counter_card(
    card: str,
    opponent_deck: list[str],
    threats: list[str],
    preferred: list[str],
) -> float:
    if card in _COUNTER_DECK_BANNED:
        return -100.0
    if card in _REFLECT_CHAMPIONS and not _monk_worth_it(opponent_deck):
        return -100.0
    if _swarm_hard_countered(card, opponent_deck):
        return -100.0

    score = 0.0
    threat_set = set(threats)

    for threat in threats:
        tier = card_counters_target(card, threat)
        weight = 8.0 if threat in WIN_CONDITIONS or get_card_role(threat) == "win_condition" else 5.0
        if tier == "strong":
            score += weight
        elif tier == "partial":
            score += weight * 0.35
        if is_point_target_threat(threat) and card in POINT_TARGET_COUNTERS and card not in _REFLECT_CHAMPIONS:
            score += 2.5

    for opp in opponent_deck:
        if opp in threat_set:
            continue
        tier = card_counters_target(card, opp)
        if tier == "strong":
            score += 1.0
        elif tier == "partial":
            score += 0.3

    splash_n = _opponent_splash_count(opponent_deck)
    for opp in opponent_deck:
        if opp in _SPELL_KILLERS and _swarm_hard_countered(card, [opp]):
            score -= 6.0
        tier = card_counters_target(opp, card)
        if tier == "strong":
            score -= 7.0
        elif tier == "partial":
            score -= 2.5

    if splash_n >= 2 and card in _SPLASH_VULNERABLE:
        score -= 12.0
    elif splash_n >= 1 and card in {"Mega Knight", "Mini P.E.K.K.A", "Skeleton Army", "Goblin Gang"}:
        score -= 6.0

    if card == "Ice Golem" and _deck_has_air(opponent_deck):
        score -= 8.0

    if "Balloon" in opponent_deck and card in {"Inferno Tower", "Musketeer", "Inferno Dragon", "Tesla", "Hunter"}:
        score += 6.0

    if set(opponent_deck) & _CHAMPION_THREATS:
        if card in {"Ice Golem", "Mini P.E.K.K.A", "Lumberjack", "Hunter"}:
            score -= 10.0
        if card in {"Musketeer", "Bowler", "Executioner", "Tesla", "Inferno Tower", "Inferno Dragon"}:
            score += 5.0

    elixir = get_card_elixir(card)
    if elixir >= 6:
        score -= 10.0
    elif elixir >= 5:
        score -= 4.0

    if card in preferred[:10]:
        score += 1.5
    if card in preferred[:3]:
        score += 1.0

    if card in WIN_CONDITIONS or get_card_role(card) == "win_condition":
        score -= 4.0

    return score


def _card_score_in_context(card: str, opponent_deck: list[str], threats: list[str]) -> float:
    return _score_counter_card(card, opponent_deck, threats, [])


def _replace_weakest(
    deck: list[str],
    new_card: str,
    opponent_deck: list[str],
    threats: list[str],
    *,
    skip_win: bool = True,
) -> list[str]:
    if new_card in deck:
        return deck
    candidates = []
    for i, card in enumerate(deck):
        if skip_win and (card in WIN_CONDITIONS or get_card_role(card) == "win_condition"):
            continue
        candidates.append((i, _card_score_in_context(card, opponent_deck, threats)))
    if not candidates:
        return deck
    worst_idx = min(candidates, key=lambda x: x[1])[0]
    out = list(deck)
    out[worst_idx] = new_card
    return out


def _ensure_spell(
    deck: list[str],
    pool: set[str],
    opponent_deck: list[str] | None = None,
    threats: list[str] | None = None,
) -> list[str]:
    if any(get_card_role(c) == "spell" for c in deck):
        return deck
    opponent_deck = opponent_deck or []
    threats = threats or []
    for spell in ("Zap", "The Log", "Fireball"):
        if spell not in pool:
            continue
        if len(deck) < 8 and _can_add(spell, deck):
            deck.append(spell)
            return deck
        if len(deck) >= 8:
            deck = _replace_weakest(deck, spell, opponent_deck, threats)
            return deck
    return deck


def _ensure_win_condition(deck: list[str], pool: set[str], preferred: list[str]) -> list[str]:
    if any(c in WIN_CONDITIONS or get_card_role(c) == "win_condition" for c in deck):
        return deck
    for wc in list(preferred) + ["Hog Rider", "Royal Giant", "Miner", "Balloon"]:
        if wc not in pool or wc not in WIN_CONDITIONS:
            continue
        if len(deck) < 8 and _can_add(wc, deck):
            deck.append(wc)
            return deck
    return deck


def _ensure_building(deck: list[str], pool: set[str], opponent_deck: list[str]) -> list[str]:
    if any(get_card_role(c) == "building" for c in deck):
        return deck
    if not set(opponent_deck) & _PUSH_THREATS:
        return deck
    for building in ("Cannon", "Tesla", "Tombstone", "Inferno Tower"):
        if building not in pool:
            continue
        if len(deck) < 8 and _can_add(building, deck):
            deck.append(building)
            return deck
    return deck


def _fill_counter_gaps(
    deck: list[str],
    ranked: list[tuple[float, str]],
    pool: set[str],
    opponent_deck: list[str],
) -> list[str]:
    out = list(deck)
    for score, card in ranked:
        if len(out) >= 8:
            break
        if card in out or card in opponent_deck or card in _COUNTER_DECK_BANNED:
            continue
        if score < _MIN_COUNTER_SCORE:
            continue
        if _can_add(card, out):
            out.append(card)

    for score, card in ranked:
        if len(out) >= 8:
            break
        if card in out or card in opponent_deck:
            continue
        if score < 1.0:
            continue
        if _can_add(card, out):
            out.append(card)

    return out


def _trim_weak_cards(
    deck: list[str],
    ranked: list[tuple[float, str]],
    opponent_deck: list[str],
    threats: list[str],
    preferred: list[str],
) -> list[str]:
    out = list(deck)
    ranked_map = {card: score for score, card in ranked}
    candidates = [card for score, card in ranked if card not in out]

    for _ in range(8):
        if not candidates:
            break
        weakest = min(
            out,
            key=lambda c: (
                1 if c in WIN_CONDITIONS or get_card_role(c) == "win_condition" else 0,
                1 if get_card_role(c) == "spell" and _deck_role_counts(out)["spell"] <= 1 else 0,
                _card_score_in_context(c, opponent_deck, threats),
            ),
        )
        weak_score = _card_score_in_context(weakest, opponent_deck, threats)
        if weak_score >= _MIN_COUNTER_SCORE:
            break

        replaced = False
        for card in candidates:
            if not _can_add(card, out) and card not in out:
                continue
            new_score = ranked_map.get(card, _card_score_in_context(card, opponent_deck, threats))
            if new_score <= weak_score + 1.0:
                continue
            if card in out:
                continue
            idx = out.index(weakest)
            if get_card_role(card) == "spell" and get_card_role(weakest) == "spell":
                out[idx] = card
            elif card in WIN_CONDITIONS and weakest in WIN_CONDITIONS:
                out[idx] = card
            elif card not in WIN_CONDITIONS and weakest not in WIN_CONDITIONS:
                out[idx] = card
            else:
                continue
            candidates.remove(card)
            replaced = True
            break
        if not replaced:
            break

    return _trim_excess(out, opponent_deck, threats, preferred)


def _trim_excess(
    deck: list[str],
    opponent_deck: list[str],
    threats: list[str],
    preferred: list[str],
) -> list[str]:
    out = list(deck)

    while _deck_role_counts(out)["spell"] > _MAX_SPELLS:
        spells = [c for c in out if get_card_role(c) == "spell"]
        drop = min(spells, key=lambda c: _card_score_in_context(c, opponent_deck, threats))
        out.remove(drop)

    while _deck_role_counts(out)["win"] > _MAX_WIN_CONDITIONS:
        wins = [c for c in out if c in WIN_CONDITIONS or get_card_role(c) == "win_condition"]
        drop = min(
            wins,
            key=lambda c: (
                0 if c in preferred[:3] else 1,
                _card_score_in_context(c, opponent_deck, threats),
            ),
        )
        out.remove(drop)

    while _deck_role_counts(out)["building"] > _MAX_BUILDINGS:
        buildings = [c for c in out if get_card_role(c) == "building"]
        drop = min(buildings, key=lambda c: _card_score_in_context(c, opponent_deck, threats))
        out.remove(drop)

    return out


def _deck_has_air(deck: list[str]) -> bool:
    return any(c in _AIR_OFFENSE or get_card_role(c) == "air" for c in deck)


def _is_anti_air_specialist(card: str) -> bool:
    return card in _ANTI_AIR and card not in {"Baby Dragon", "Wizard", "Electro Wizard", "Mini P.E.K.K.A"}


def build_synergy_deck(
    current_deck: list[str],
    arena_id: int | None = None,
    trophies: int | None = None,
    preferred_cards: list[str] | None = None,
) -> dict | None:
    """Точечное улучшение текущей колоды. None — если замены не нужны."""
    result = improve_player_deck(
        current_deck,
        arena_id,
        trophies,
        preferred_cards,
    )
    if not result["needed"]:
        return None

    stats = analyze_deck(result["improved"])
    return {
        "deck": result["improved"],
        "synergies": result["synergies"],
        "avg_elixir": result["avg_elixir"],
        "win_conditions": stats.win_conditions,
        "core": result["locked"],
        "issues": result["issues"],
    }


def customize_deck_for_arena(
    current_deck: list[str],
    arena_id: int | None,
    preferred_cards: list[str] | None = None,
    trophies: int | None = None,
) -> dict:
    """Кастомизация колоды: только обязательные замены под арену и баланс."""
    result = improve_player_deck(
        current_deck,
        arena_id,
        trophies,
        preferred_cards,
    )
    new_stats = analyze_deck(result["improved"])
    return {
        "original": result["original"],
        "customized": result["improved"],
        "issues": result["issues"],
        "avg_elixir": new_stats.avg_elixir,
        "win_conditions": new_stats.win_conditions,
        "needed": result["needed"],
    }


def _get_arena_pool(arena_id: int | None, trophies: int | None = None) -> set[str]:
    # Легендарная арена / Path of Legend (id ~54xxxxxx) или высокий рейтинг — полный каталог
    if arena_id is not None and arena_id >= 54000000:
        return set(CARD_META.keys())
    if trophies is not None and trophies >= 7500:
        return set(CARD_META.keys())

    pool = set(ARENA_CARD_POOL["low"])
    if arena_id is None or arena_id >= 5:
        pool.update(ARENA_CARD_POOL["mid"])
    if arena_id is not None and arena_id >= 10:
        pool.update(ARENA_CARD_POOL["high"])
    return pool


def _find_replacement(card: str, pool: set[str], current: list[str]) -> str | None:
    role = get_card_role(card)
    elixir = get_card_elixir(card)

    role_map = {
        "win_condition": ["Hog Rider", "Balloon", "Royal Giant", "Giant", "Miner"],
        "spell": ["Zap", "Fireball", "Arrows", "The Log"],
        "building": ["Cannon", "Tesla", "Inferno Tower"],
        "tank": ["Knight", "Valkyrie", "Ice Golem", "Guards", "Mini P.E.K.K.A"],
        "support": ["Musketeer", "Archers", "Wizard", "Electro Wizard"],
        "swarm": ["Skeletons", "Goblins", "Bats", "Goblin Gang"],
    }

    candidates = role_map.get(role, [])
    for c in candidates:
        if c in pool and c not in current:
            return c

    for c in pool:
        if c not in current and abs(get_card_elixir(c) - elixir) <= 1:
            return c
    return None


def analyze_opponent_deck_from_battles(battles: list[dict], player_tag: str) -> list[dict]:
    """Список последних колод соперников."""
    opponents = []
    seen = set()

    for battle in battles:
        team = battle.get("team", [{}])[0]
        if team.get("tag", "").upper() != player_tag.upper():
            continue

        opponent = battle.get("opponent", [{}])[0]
        deck = extract_deck(opponent)
        deck_key = "|".join(sorted(deck))

        if deck_key in seen:
            continue
        seen.add(deck_key)

        stats = analyze_deck(deck)
        user_deck = extract_deck(team)
        opponents.append({
            "name": opponent.get("name", "?"),
            "tag": opponent.get("tag", ""),
            "deck": deck,
            "user_deck": user_deck,
            "threats": find_opponent_threats(deck),
            "avg_elixir": stats.avg_elixir,
            "won_against": team.get("crowns", 0) > opponent.get("crowns", 0),
        })

        if len(opponents) >= 10:
            break

    return opponents

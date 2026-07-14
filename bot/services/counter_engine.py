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
        if not opp_has_air and _skip_without_opponent_air(card):
            continue
        score = _score_counter_card(card, opponent_deck, threats, preferred_cards)
        if score > 0:
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

    for filler in ("Skeletons", "Ice Spirit", "Electro Spirit", "Knight", "Archers"):
        if len(deck) >= 8:
            break
        if filler in pool and _can_add(filler, deck):
            deck.append(filler)

    while len(deck) < 8:
        added = False
        for _, card in ranked:
            if card not in deck and _can_add(card, deck):
                deck.append(card)
                added = True
                break
        if not added:
            for card in pool:
                if card not in deck and card not in opponent_deck and _can_add(card, deck):
                    deck.append(card)
                    added = True
                    break
        if not added:
            break

    return _trim_excess(deck, opponent_deck, threats, preferred_cards)[:8]


_GROUND_COUNTERS = {"Inferno Tower", "Tesla", "Cannon", "Tombstone"}


def _skip_without_opponent_air(card: str) -> bool:
    """Не брать чистый анти-воздух, если у соперника нет воздуха."""
    if card in _GROUND_COUNTERS:
        return False
    return _is_anti_air_specialist(card) or card in _FLYING_TROOPS


def _key_threats(opponent_deck: list[str]) -> list[str]:
    base = find_opponent_threats(opponent_deck)
    extra = [c for c in opponent_deck if c in _EXTRA_THREATS and c not in base]
    return list(dict.fromkeys(base + extra))


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


def _score_counter_card(
    card: str,
    opponent_deck: list[str],
    threats: list[str],
    preferred: list[str],
) -> float:
    if card in _REFLECT_CHAMPIONS and not _monk_worth_it(opponent_deck):
        return -1.0
    if _swarm_hard_countered(card, opponent_deck):
        return -1.0

    score = 0.0
    for threat in threats:
        tier = card_counters_target(card, threat)
        if tier == "strong":
            score += 7.0
        elif tier == "partial":
            score += 2.5
        if is_point_target_threat(threat) and card in POINT_TARGET_COUNTERS and card not in _REFLECT_CHAMPIONS:
            score += 3.0

    for opp in opponent_deck:
        if opp in threats:
            continue
        tier = card_counters_target(card, opp)
        if tier == "strong":
            score += 1.5
        elif tier == "partial":
            score += 0.5

    for opp in opponent_deck:
        if opp in _SPELL_KILLERS and _swarm_hard_countered(card, [opp]):
            score -= 5.0
        tier = card_counters_target(opp, card)
        if tier == "strong":
            score -= 4.0
        elif tier == "partial":
            score -= 1.5

    if card in preferred[:10]:
        score += 1.5
    if card in preferred[:3]:
        score += 1.0

    if card in WIN_CONDITIONS or get_card_role(card) == "win_condition":
        score -= 2.0

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
    core_cards: list[str],
    arena_id: int | None = None,
) -> dict:
    """Сборка колоды вокруг любимых карт пользователя."""
    pool = _get_arena_pool(arena_id)
    deck = [c for c in core_cards if c in pool][:3]
    suggestions: dict[str, list[str]] = {}

    for core in deck:
        strong, partial = synergy_partners(core, pool, limit=4)
        available = strong + [p for p in partial if p not in strong]
        suggestions[core] = available[:4]
        for s in available[:2]:
            if len(deck) < 8 and s not in deck:
                deck.append(s)

    has_spell = any(get_card_role(c) == "spell" for c in deck)
    if not has_spell:
        for spell in ["Zap", "Fireball", "The Log", "Arrows"]:
            if spell in pool and spell not in deck:
                deck.append(spell)
                break

    has_win = any(c in WIN_CONDITIONS or get_card_role(c) == "win_condition" for c in deck)
    if not has_win:
        for wc in core_cards:
            if wc in WIN_CONDITIONS:
                has_win = True
                break
        if not has_win:
            for wc in ["Hog Rider", "Balloon", "Royal Giant"]:
                if wc in pool and wc not in deck:
                    deck.append(wc)
                    break

    fill_cards = ["Knight", "Skeletons", "Ice Spirit", "Musketeer", "Cannon", "Ice Golem"]
    for card in fill_cards:
        if len(deck) >= 8:
            break
        if card in pool and card not in deck:
            deck.append(card)

    stats = analyze_deck(deck[:8])
    return {
        "deck": deck[:8],
        "synergies": suggestions,
        "avg_elixir": stats.avg_elixir,
        "win_conditions": stats.win_conditions,
    }


def customize_deck_for_arena(
    current_deck: list[str],
    arena_id: int | None,
    preferred_cards: list[str] | None = None,
    trophies: int | None = None,
) -> dict:
    """Кастомизация колоды под арену и предпочтения."""
    pool = _get_arena_pool(arena_id, trophies)
    # Карты из колоды и частых пиков игрока — он уже ими играет
    pool.update(current_deck)
    pool.update(preferred_cards or [])
    preferred_cards = preferred_cards or []
    issues = []
    new_deck = list(current_deck)
    had_fixes = False

    for i, card in enumerate(new_deck):
        if card not in pool:
            had_fixes = True
            issues.append(f"❌ {_card_ru(card)} — редкая для низкой арены, предложена замена")
            replacement = _find_replacement(card, pool, new_deck)
            if replacement:
                new_deck[i] = replacement
                issues.append(f"   → замена на {_card_ru(replacement)}")

    stats = analyze_deck(new_deck)
    if stats.avg_elixir > 4.2:
        heavy = max(new_deck, key=get_card_elixir)
        if get_card_elixir(heavy) >= 5:
            light_opts = [c for c in ["Skeletons", "Ice Spirit", "Bats", "Fire Spirit"]
                          if c in pool and c not in new_deck]
            if light_opts and heavy in new_deck:
                had_fixes = True
                idx = new_deck.index(heavy)
                new_deck[idx] = light_opts[0]
                issues.append(f"⚖️ {_card_ru(heavy)} → {_card_ru(light_opts[0])} (снижение среднего эликсира)")

    for pref in preferred_cards[:3]:
        if pref in pool and pref not in new_deck:
            replaceable = [
                c for c in new_deck
                if c not in preferred_cards
                and c not in WIN_CONDITIONS
                and get_card_role(c) != "win_condition"
            ]
            if not replaceable:
                continue
            weakest = min(replaceable, key=lambda c: preferred_cards.count(c) if c in preferred_cards else 0)
            idx = new_deck.index(weakest)
            new_deck[idx] = pref
            issues.append(f"⭐ Рекомендуем {_card_ru(pref)} вместо {_card_ru(weakest)} — часто играете")

    stats = analyze_deck(new_deck)
    if not stats.spells:
        for spell in ["Zap", "Fireball", "Arrows"]:
            if spell in pool:
                replace_idx = next(
                    (i for i, c in enumerate(new_deck) if get_card_role(c) not in ("win_condition", "spell")),
                    None,
                )
                if replace_idx is not None:
                    had_fixes = True
                    old = new_deck[replace_idx]
                    new_deck[replace_idx] = spell
                    issues.append(f"🪄 Добавлено заклинание {_card_ru(spell)} вместо {_card_ru(old)}")
                    break

    new_stats = analyze_deck(new_deck)
    return {
        "original": current_deck,
        "customized": new_deck,
        "issues": issues,
        "avg_elixir": new_stats.avg_elixir,
        "win_conditions": new_stats.win_conditions,
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

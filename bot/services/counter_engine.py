from bot.services.card_data import (
    ARENA_CARD_POOL,
    CARD_META,
    COUNTERS,
    POINT_TARGET_COUNTERS,
    SYNERGIES,
    WIN_CONDITIONS,
    get_card_elixir,
    get_card_role,
    is_point_target_threat,
    is_spam_card,
)
from bot.services.card_names_ru import card_name_ru
from bot.services.card_matchups import synergy_partners
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

_MAX_COUNTER_SWAPS = 2


def _card_ru(name: str) -> str:
    return card_name_ru(name, short=True) or name


def suggest_counter_deck(
    opponent_deck: list[str],
    arena_id: int | None = None,
    preferred_cards: list[str] | None = None,
    user_deck: list[str] | None = None,
    trophies: int | None = None,
) -> list[str]:
    """Подбор контр-колоды: ваша колода из боя + точечные замены под карты соперника."""
    preferred_cards = preferred_cards or []
    pool = _get_arena_pool(arena_id, trophies)
    pool.update(opponent_deck)
    pool.update(user_deck or [])
    pool.update(preferred_cards)

    if user_deck and len(user_deck) == 8:
        deck = list(user_deck)
    else:
        deck = []
        for card in preferred_cards:
            if card in pool and card not in deck and len(deck) < 8:
                deck.append(card)

    opp_has_air = _deck_has_air(opponent_deck)
    needed = _prioritized_counters(opponent_deck, opp_has_air)
    missing = [c for c in needed if c not in deck and c in pool]

    swaps = 0
    for counter in missing:
        if swaps >= _MAX_COUNTER_SWAPS:
            break
        slot = _find_swap_slot(deck, counter, opponent_deck, user_deck or deck, opp_has_air)
        if slot is not None:
            deck[slot] = counter
            swaps += 1
        elif len(deck) < 8:
            deck.append(counter)

    deck = _fill_deck(deck, pool, opponent_deck, opp_has_air)
    return deck[:8]


def _deck_has_air(deck: list[str]) -> bool:
    return any(c in _AIR_OFFENSE or get_card_role(c) == "air" for c in deck)


def _is_air_unit(card: str) -> bool:
    return card in _AIR_OFFENSE or get_card_role(card) == "air"


def _is_anti_air_specialist(card: str) -> bool:
    return card in _ANTI_AIR and card not in {"Baby Dragon", "Wizard", "Electro Wizard", "Mini P.E.K.K.A"}


def _counters_opponent_card(counter: str, opponent_card: str) -> bool:
    return counter in COUNTERS.get(opponent_card, [])


def _counters_any_opponent(card: str, opponent_deck: list[str]) -> bool:
    return any(_counters_opponent_card(card, opp) for opp in opponent_deck)


def _prioritized_counters(opponent_deck: list[str], opp_has_air: bool) -> list[str]:
    """Счётчики по каждой карте соперника, отсортированные по полезности."""
    scores: dict[str, int] = {}

    for opp_card in opponent_deck:
        for counter in COUNTERS.get(opp_card, []):
            if not opp_has_air and (_is_anti_air_specialist(counter) or counter in _FLYING_TROOPS):
                continue
            scores[counter] = scores.get(counter, 0) + 1

    if not opp_has_air:
        for card in opponent_deck:
            if is_spam_card(card):
                for counter in ("The Log", "Arrows", "Zap", "Wizard", "Valkyrie"):
                    scores[counter] = scores.get(counter, 0) + 1

        for card in opponent_deck:
            if is_point_target_threat(card):
                for counter in POINT_TARGET_COUNTERS:
                    scores[counter] = scores.get(counter, 0) + 2

    if opp_has_air:
        for counter in _ANTI_AIR:
            if _counters_any_opponent(counter, opponent_deck):
                scores[counter] = scores.get(counter, 0) + 2

    ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    return [name for name, _ in ranked]


def _swap_score(
    card: str,
    opponent_deck: list[str],
    opp_has_air: bool,
    user_core: list[str],
) -> int:
    """Чем выше — тем охотнее заменяем."""
    if card in user_core and _counters_any_opponent(card, opponent_deck):
        return -100

    score = 0
    if card in WIN_CONDITIONS or get_card_role(card) == "win_condition":
        score -= 8
    if get_card_role(card) == "spell":
        score -= 4
    if not _counters_any_opponent(card, opponent_deck):
        score += 4
    if not opp_has_air and (_is_anti_air_specialist(card) or _is_air_unit(card)):
        score += 12
    if opp_has_air and _is_air_unit(card) and not _is_anti_air_specialist(card):
        score += 6
    return score


def _is_protected_user_card(card: str, user_core: list[str]) -> bool:
    if card not in user_core:
        return False
    if card in WIN_CONDITIONS or get_card_role(card) == "win_condition":
        return True
    if get_card_role(card) == "spell":
        return True
    return False


def _find_swap_slot(
    deck: list[str],
    counter: str,
    opponent_deck: list[str],
    user_core: list[str],
    opp_has_air: bool,
) -> int | None:
    best_idx: int | None = None
    best_score = 0
    for i, card in enumerate(deck):
        if card == counter or _is_protected_user_card(card, user_core):
            continue
        score = _swap_score(card, opponent_deck, opp_has_air, user_core)
        if score > best_score:
            best_score = score
            best_idx = i
    return best_idx if best_score > 0 else None


def _fill_deck(
    deck: list[str],
    pool: set[str],
    opponent_deck: list[str],
    opp_has_air: bool,
) -> list[str]:
    if not any(get_card_role(c) == "spell" for c in deck):
        for spell in ("Zap", "The Log", "Fireball", "Arrows"):
            if spell in pool and spell not in deck:
                if len(deck) < 8:
                    deck.append(spell)
                break

    if opp_has_air and not any(c in _ANTI_AIR for c in deck):
        for card in ("Musketeer", "Tesla", "Inferno Tower", "Wizard", "Mega Minion"):
            if card in pool and card not in deck:
                if len(deck) < 8:
                    deck.append(card)
                break

    fill = ["Knight", "Skeletons", "Ice Spirit", "Valkyrie", "Cannon", "Ice Golem"]
    if not opp_has_air:
        fill = [c for c in fill if c not in _FLYING_TROOPS]

    for card in fill:
        if len(deck) >= 8:
            break
        if card in pool and card not in deck:
            deck.append(card)

    while len(deck) < 8:
        added = False
        for card in pool:
            if card not in deck and (opp_has_air or card not in _FLYING_TROOPS):
                deck.append(card)
                added = True
                break
        if not added:
            break

    return deck


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

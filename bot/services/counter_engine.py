from bot.services.card_data import (
    ARENA_CARD_POOL,
    CARD_META,
    COUNTERS,
    SYNERGIES,
    WIN_CONDITIONS,
    get_card_elixir,
    get_card_role,
)
from bot.services.card_names_ru import card_name_ru
from bot.services.deck_analyzer import analyze_deck, extract_deck, find_opponent_threats


def _card_ru(name: str) -> str:
    return card_name_ru(name, short=True) or name


def suggest_counter_deck(
    opponent_deck: list[str],
    arena_id: int | None = None,
    preferred_cards: list[str] | None = None,
) -> list[str]:
    """Подбор контр-колоды под колоду соперника."""
    preferred_cards = preferred_cards or []
    pool = _get_arena_pool(arena_id)
    threats = find_opponent_threats(opponent_deck)

    selected: list[str] = []
    used_elixir = 0.0
    max_elixir = 4.0

    for card in preferred_cards:
        if card in pool and card not in selected and len(selected) < 8:
            selected.append(card)
            used_elixir += get_card_elixir(card)

    for threat in threats:
        counters = COUNTERS.get(threat, [])
        for counter in counters:
            if counter in pool and counter not in selected and len(selected) < 8:
                selected.append(counter)
                break

    if not any(get_card_role(c) == "win_condition" or c in WIN_CONDITIONS for c in selected):
        for wc in ["Hog Rider", "Balloon", "Royal Giant", "Miner", "Mortar"]:
            if wc in pool and wc not in selected:
                selected.append(wc)
                break

    for card in ["Zap", "The Log", "Fireball", "Arrows", "Poison"]:
        if card in pool and card not in selected and len(selected) < 8:
            if get_card_role(card) == "spell":
                selected.append(card)
                break

    for card in ["Musketeer", "Knight", "Valkyrie", "Ice Golem", "Skeletons", "Ice Spirit"]:
        if card in pool and card not in selected and len(selected) < 8:
            selected.append(card)

    while len(selected) < 8:
        for card in pool:
            if card not in selected:
                selected.append(card)
                if len(selected) >= 8:
                    break
        break

    return selected[:8]


def build_synergy_deck(
    core_cards: list[str],
    arena_id: int | None = None,
) -> dict:
    """Сборка колоды вокруг любимых карт пользователя."""
    pool = _get_arena_pool(arena_id)
    deck = [c for c in core_cards if c in pool][:3]
    suggestions: dict[str, list[str]] = {}

    for core in deck:
        synergies = SYNERGIES.get(core, [])
        available = [s for s in synergies if s in pool and s not in deck]
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

    if had_fixes:
        for pref in preferred_cards[:3]:
            if pref in pool and pref not in new_deck:
                weakest = min(new_deck, key=lambda c: preferred_cards.count(c) if c in preferred_cards else 0)
                if weakest not in preferred_cards:
                    idx = new_deck.index(weakest)
                    new_deck[idx] = pref
                    issues.append(f"⭐ Добавлена любимая карта {_card_ru(pref)} вместо {_card_ru(weakest)}")

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
        "tank": ["Knight", "Valkyrie", "Ice Golem", "Mini P.E.K.K.A"],
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
        opponents.append({
            "name": opponent.get("name", "?"),
            "tag": opponent.get("tag", ""),
            "deck": deck,
            "threats": find_opponent_threats(deck),
            "avg_elixir": stats.avg_elixir,
            "won_against": team.get("crowns", 0) > opponent.get("crowns", 0),
        })

        if len(opponents) >= 10:
            break

    return opponents

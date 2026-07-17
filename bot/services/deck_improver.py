"""Точечное улучшение колоды — сохраняет win-condition и спеллы игрока."""

from __future__ import annotations

from bot.services.card_data import WIN_CONDITIONS, get_card_elixir, get_card_role
from bot.services.card_matchups import synergy_partners
from bot.services.card_names_ru import card_name_ru
from bot.services.deck_analyzer import analyze_deck
from bot.services.deck_builder.builder import (
    _avg_elixir,
    _card_roles,
    _count_spells,
    _count_wins,
    _detect_archetype,
    _is_spell,
    _is_win,
    _pair_synergy,
    _pick_for_role,
)
from bot.services.deck_builder.constants import (
    GENERIC_CARDS,
    MAX_SPELLS,
    MAX_WINS,
    ROLE_AIR,
    ROLE_ANTI_SWARM,
    ROLE_ANTI_TANK,
    ROLE_BIG_SPELL,
    ROLE_BUILDING,
    ROLE_CYCLE,
    ROLE_DEFENSIVE,
    ROLE_SMALL_SPELL,
    ROLE_SPLASH,
    ROLE_WIN,
)
from bot.services.deck_builder.loader import get_database
from bot.services.deck_detail import _suggest_improvements

_CATEGORY_ROLE: dict[str, str | None] = {
    "spells": ROLE_BIG_SPELL,
    "finishers": ROLE_BIG_SPELL,
    "anti_air": ROLE_AIR,
    "splash": ROLE_SPLASH,
    "defense": ROLE_BUILDING,
    "point_target": ROLE_ANTI_TANK,
    "swarm": ROLE_SMALL_SPELL,
    "cycle": ROLE_CYCLE,
    "win_condition": ROLE_WIN,
    "support": ROLE_BIG_SPELL,
    "focus": None,
}


def _card_ru(name: str) -> str:
    return card_name_ru(name, short=True) or name


def _locked_cards(deck: list[str], db) -> set[str]:
    """Основной win-condition и заклинания игрока не трогаем."""
    locked: set[str] = set()
    wins = [
        c for c in deck
        if _is_win(db, c) or c in WIN_CONDITIONS or get_card_role(c) == "win_condition"
    ]
    if wins:
        locked.add(wins[0])

    for card in deck:
        if card in locked:
            continue
        if _is_spell(db, card) or get_card_role(card) == "spell":
            locked.add(card)
    return locked


def _avg_synergy_with_deck(db, card: str, deck: list[str]) -> float:
    others = [c for c in deck if c != card]
    if not others:
        return 0.0
    return sum(_pair_synergy(db, card, other) for other in others) / len(others)


def _pick_replaceable(
    deck: list[str],
    locked: set[str],
    *,
    avoid_roles: frozenset[str] | None = None,
) -> str | None:
    candidates = [c for c in deck if c not in locked]
    if not candidates:
        return None

    def rank(card: str) -> tuple[int, int, float, int]:
        roles = _card_roles(get_database(), card)
        penalty = 1 if avoid_roles and roles & avoid_roles else 0
        generic = 0 if card in GENERIC_CARDS else 1
        syn = _avg_synergy_with_deck(get_database(), card, deck)
        elixir = get_card_elixir(card)
        return (penalty, generic, syn, -elixir)

    return min(candidates, key=rank)


def _pick_replacement(
    deck: list[str],
    pool: set[str],
    locked: set[str],
    archetype: str,
    *,
    role: str | None = None,
    suggestions: list[str] | None = None,
    db=None,
) -> str | None:
    db = db or get_database()
    deck_set = set(deck)

    if suggestions:
        for card in suggestions:
            if card in pool and card not in deck_set:
                return card

    if role:
        pick = _pick_for_role(deck, db, pool, role, list(locked), archetype)
        if pick:
            return pick

    return None


def _apply_arena_fixes(
    deck: list[str],
    pool: set[str],
    issues: list[str],
) -> bool:
    changed = False
    for index, card in enumerate(list(deck)):
        if card in pool:
            continue
        changed = True
        issues.append(f"❌ {_card_ru(card)} — недоступна на вашей арене")
        replacement = _find_arena_replacement(card, pool, deck)
        if replacement:
            deck[index] = replacement
            issues.append(f"   → замена на {_card_ru(replacement)}")
    return changed


def _find_arena_replacement(card: str, pool: set[str], current: list[str]) -> str | None:
    role = get_card_role(card)
    elixir = get_card_elixir(card)
    role_map = {
        "win_condition": ["Hog Rider", "Balloon", "Royal Giant", "Giant", "Miner", "Graveyard"],
        "spell": ["Zap", "Fireball", "Arrows", "The Log", "Poison"],
        "building": ["Cannon", "Tesla", "Inferno Tower", "Tombstone"],
        "tank": ["Knight", "Valkyrie", "Ice Golem", "Guards", "Mini P.E.K.K.A"],
        "support": ["Musketeer", "Archers", "Wizard", "Electro Wizard"],
        "swarm": ["Skeletons", "Goblins", "Bats", "Goblin Gang"],
    }
    for candidate in role_map.get(role, []):
        if candidate in pool and candidate not in current:
            return candidate
    for candidate in pool:
        if candidate not in current and abs(get_card_elixir(candidate) - elixir) <= 1:
            return candidate
    return None


def _fix_elixir_if_needed(deck: list[str], pool: set[str], locked: set[str], issues: list[str]) -> bool:
    stats = analyze_deck(deck)
    if stats.avg_elixir <= 4.2:
        return False

    heavy = max(deck, key=get_card_elixir)
    if get_card_elixir(heavy) < 5 or heavy in locked:
        return False

    light_opts = [c for c in ["Skeletons", "Ice Spirit", "Bats", "Fire Spirit"] if c in pool and c not in deck]
    if not light_opts:
        return False

    deck[deck.index(heavy)] = light_opts[0]
    issues.append(f"⚖️ {_card_ru(heavy)} → {_card_ru(light_opts[0])} (снижение среднего эликсира)")
    return True


def _fix_too_many_wins(
    deck: list[str],
    locked: set[str],
    pool: set[str],
    archetype: str,
    issues: list[str],
    db,
) -> bool:
    wins = [c for c in deck if _is_win(db, c)]
    if len(wins) <= MAX_WINS:
        return False

    removable = [c for c in wins if c not in locked]
    if not removable:
        return False

    drop = removable[0]
    pick = _pick_replacement(
        deck,
        pool,
        locked,
        archetype,
        role=ROLE_DEFENSIVE,
        suggestions=["The Log", "Zap", "Fireball", "Musketeer", "Ice Golem"],
        db=db,
    )
    if not pick:
        pick = _pick_replacement(deck, pool, locked, archetype, role=ROLE_CYCLE, db=db)
    if not pick:
        return False

    deck[deck.index(drop)] = pick
    issues.append(f"🎯 {_card_ru(drop)} → {_card_ru(pick)}: лишний win-condition")
    return True


def _apply_suggestion(
    deck: list[str],
    pool: set[str],
    locked: set[str],
    archetype: str,
    suggestion: dict,
    issues: list[str],
    db,
) -> bool:
    category = suggestion["category"]
    message = suggestion["message"]
    suggested_cards = suggestion.get("suggested_cards") or []

    if category == "focus":
        return _fix_too_many_wins(deck, locked, pool, archetype, issues, db)

    role = _CATEGORY_ROLE.get(category)
    avoid_roles: frozenset[str] | None = None
    if category == "anti_air":
        avoid_roles = frozenset({ROLE_AIR})
    elif category == "point_target":
        avoid_roles = frozenset({ROLE_ANTI_TANK, ROLE_DEFENSIVE})
    elif category == "defense":
        avoid_roles = frozenset({ROLE_BUILDING, ROLE_DEFENSIVE})

    drop = _pick_replaceable(deck, locked, avoid_roles=avoid_roles)
    if not drop:
        return False

    pick = _pick_replacement(
        deck,
        pool,
        locked,
        archetype,
        role=role,
        suggestions=suggested_cards,
        db=db,
    )
    if not pick or pick == drop:
        return False

    if _is_win(db, pick) and _count_wins(deck, db) >= MAX_WINS:
        return False
    if _is_spell(db, pick) and _count_spells(deck, db) >= MAX_SPELLS:
        return False

    deck[deck.index(drop)] = pick
    issues.append(f"🔧 {_card_ru(drop)} → {_card_ru(pick)}: {message}")
    return True


def _trim_spell_and_win_limits(deck: list[str], locked: set[str], db) -> None:
    while _count_spells(deck, db) > MAX_SPELLS:
        removable = [c for c in deck if _is_spell(db, c) and c not in locked]
        if not removable:
            break
        worst = min(removable, key=lambda c: _avg_synergy_with_deck(db, c, deck))
        deck.remove(worst)

    while _count_wins(deck, db) > MAX_WINS:
        extra = [c for c in deck if _is_win(db, c) and c not in locked]
        if not extra:
            break
        deck.remove(extra[0])


def _build_synergy_map(deck: list[str], locked: set[str], pool: set[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    deck_set = set(deck)
    for card in sorted(locked):
        strong, partial = synergy_partners(card, pool, limit=6)
        partners = [p for p in strong + partial if p in deck_set and p != card][:4]
        if partners:
            result[card] = partners
    return result


def improve_player_deck(
    current_deck: list[str],
    arena_id: int | None,
    trophies: int | None = None,
    preferred_cards: list[str] | None = None,
    *,
    pool: set[str] | None = None,
) -> dict:
    """Улучшает колоду точечными заменами. Возвращает needed=False, если менять нечего."""
    from bot.services.counter_engine import _get_arena_pool

    if len(current_deck) != 8:
        return {
            "needed": False,
            "original": current_deck,
            "improved": list(current_deck),
            "issues": ["Нужна полная колода из 8 карт"],
            "avg_elixir": 0.0,
            "synergies": {},
            "locked": [],
        }

    pool = set(pool or _get_arena_pool(arena_id, trophies))
    pool.update(current_deck)
    pool.update(preferred_cards or [])

    db = get_database()
    issues: list[str] = []
    deck = list(current_deck)
    locked = _locked_cards(deck, db)

    arena_changed = _apply_arena_fixes(deck, pool, issues)
    locked = _locked_cards(deck, db)
    archetype = _detect_archetype(list(locked) or deck)

    suggestions = _suggest_improvements(deck)
    needs_balance = bool(suggestions) or arena_changed

    if not needs_balance:
        stats = analyze_deck(deck)
        return {
            "needed": False,
            "original": current_deck,
            "improved": deck,
            "issues": issues,
            "avg_elixir": stats.avg_elixir,
            "synergies": {},
            "locked": sorted(locked),
        }

    if not arena_changed:
        _fix_elixir_if_needed(deck, pool, locked, issues)

    if _count_wins(deck, db) > MAX_WINS:
        _fix_too_many_wins(deck, locked, pool, archetype, issues, db)
        locked = _locked_cards(deck, db)
        suggestions = _suggest_improvements(deck)

    for suggestion in suggestions:
        if len(deck) != 8:
            break
        _apply_suggestion(deck, pool, locked, archetype, suggestion, issues, db)
        locked = _locked_cards(deck, db)

    _trim_spell_and_win_limits(deck, locked, db)

    changed = deck != current_deck
    if not changed:
        stats = analyze_deck(deck)
        return {
            "needed": False,
            "original": current_deck,
            "improved": current_deck,
            "issues": issues,
            "avg_elixir": stats.avg_elixir,
            "synergies": {},
            "locked": sorted(locked),
        }

    stats = analyze_deck(deck)
    return {
        "needed": True,
        "original": current_deck,
        "improved": deck,
        "issues": issues,
        "avg_elixir": stats.avg_elixir,
        "synergies": _build_synergy_map(deck, locked, pool),
        "locked": sorted(locked),
    }

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

_SMALL_SPELLS = frozenset({
    "Zap", "The Log", "Giant Snowball", "Barbarian Barrel", "Ice Spirit", "Electro Spirit",
})
_FINISHERS = frozenset({"Fireball", "Rocket", "Lightning", "Poison"})
_ANTI_AIR_CARDS = frozenset({
    "Musketeer", "Wizard", "Executioner", "Inferno Dragon", "Mini P.E.K.K.A",
    "Mega Minion", "Electro Wizard", "Hunter", "Inferno Tower", "Tesla",
    "Archers", "Bats", "Minions", "Phoenix", "Firecracker", "Ice Wizard", "Baby Dragon",
})
_SPLASH_CARDS = frozenset({
    "Wizard", "Baby Dragon", "Valkyrie", "Bowler", "Executioner",
    "Fireball", "Arrows", "Poison", "Earthquake", "Electro Dragon",
    "Goblin Demolisher", "Magic Archer",
})
_DEFENSE_ROLES = frozenset({
    ROLE_AIR, ROLE_SPLASH, ROLE_ANTI_TANK, ROLE_DEFENSIVE, ROLE_ANTI_SWARM, ROLE_BUILDING,
})

_SPLASH_TROOPS = frozenset({
    "Executioner", "Wizard", "Bowler", "Valkyrie", "Baby Dragon",
    "Electro Wizard", "Hunter", "Magic Archer", "Firecracker",
})

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


def _has_small_spell_answer(cards: list[str]) -> bool:
    return any(c in _SMALL_SPELLS for c in cards)


def _has_finisher(cards: list[str], db) -> bool:
    return any(c in _FINISHERS or ROLE_BIG_SPELL in _card_roles(db, c) for c in cards)


def _is_defensive_core(db, card: str) -> bool:
    if card in _ANTI_AIR_CARDS or card in _SPLASH_TROOPS:
        return True
    roles = _card_roles(db, card)
    return bool(roles & _DEFENSE_ROLES)


def _defensive_core_cards(deck: list[str], db) -> set[str]:
    return {c for c in deck if _is_defensive_core(db, c)}


def _needs_building(deck: list[str], stats, db) -> bool:
    if stats.buildings:
        return False
    defensive = _defensive_core_cards(deck, db)
    if len(defensive) >= 2 and stats.air_coverage and stats.point_target_coverage:
        return False
    if stats.air_coverage and stats.splash_coverage and stats.point_target_coverage:
        return False
    return True


def _collect_improvement_gaps(deck: list[str], db) -> list[dict]:
    """Только реальные пробелы — если роль уже закрыта картами в колоде, замечания нет."""
    if len(deck) != 8:
        return []

    stats = analyze_deck(deck)
    deck_set = set(deck)
    gaps: list[dict] = []

    def add(category: str, message: str, suggested: list[str]) -> None:
        missing = [c for c in suggested if c not in deck_set][:4]
        if not missing:
            return
        gaps.append({
            "category": category,
            "message": message,
            "suggested_cards": missing,
        })

    has_spells = bool(stats.spells) or any(_is_spell(db, c) for c in deck)
    if not has_spells:
        add(
            "spells",
            "В колоде нет заклинаний — сложнее контролировать поле и добивать башни",
            ["The Log", "Fireball", "Zap", "Arrows"],
        )
    elif not _has_finisher(deck, db):
        add(
            "finishers",
            "Мало добивающих заклинаний — добавьте Fireball или Rocket для финиша",
            ["Fireball", "Rocket", "Lightning"],
        )

    if not stats.air_coverage:
        add(
            "anti_air",
            "Слабая защита от воздуха — Balloon и Minions будут опасны",
            ["Musketeer", "Mega Minion", "Inferno Dragon", "Tesla", "Archers"],
        )

    if not stats.splash_coverage:
        add(
            "splash",
            "Нет сплеша — спам и связки Goblin Gang / Skeleton Army сложно зачищать",
            ["Valkyrie", "Wizard", "Baby Dragon", "Fireball", "Arrows"],
        )

    if _needs_building(deck, stats, db):
        add(
            "defense",
            "Нет построек — Hog Rider и Balloon сложнее останавливать на мосту",
            ["Cannon", "Tesla", "Tombstone", "Inferno Tower"],
        )

    if not stats.point_target_coverage:
        add(
            "point_target",
            "Нет ответа на точечный урон — Стражи держат P.E.K.K.A, Мини P.E.K.K.A, Хог и подобных",
            ["Guards", "Knight", "Ice Golem", "Skeleton Army"],
        )

    if not _has_small_spell_answer(deck):
        add(
            "swarm",
            "Нет дешёвого ответа на спам — Zap или Ice Spirit сильно помогут в цикле",
            list(_SMALL_SPELLS),
        )

    if stats.avg_elixir > 4.2 and not any(ROLE_CYCLE in _card_roles(db, c) for c in deck):
        add(
            "cycle",
            f"Тяжёлая колода ({stats.avg_elixir} эл.) — добавьте дешёвый цикл для давления",
            ["Skeletons", "Ice Spirit", "Electro Spirit", "Ice Golem"],
        )

    if not stats.win_conditions:
        add(
            "win_condition",
            "Нет явного win-condition — добавьте карту для урона по башне",
            ["Hog Rider", "Balloon", "Royal Giant", "Miner", "Goblin Barrel"],
        )

    return gaps


def _swap_keeps_balance(deck: list[str], drop: str, pick: str, db) -> bool:
    before = analyze_deck(deck)
    after_deck = list(deck)
    after_deck[after_deck.index(drop)] = pick
    after = analyze_deck(after_deck)

    if before.air_coverage and not after.air_coverage:
        return False
    if before.splash_coverage and not after.splash_coverage:
        return False
    if before.point_target_coverage and not after.point_target_coverage:
        return False
    if _has_finisher(deck, db) and not _has_finisher(after_deck, db):
        return False
    if _has_small_spell_answer(deck) and not _has_small_spell_answer(after_deck):
        return False
    return True


def _locked_cards(deck: list[str], db) -> set[str]:
    """Win-condition и заклинания игрока не трогаем."""
    locked: set[str] = set()
    for card in deck:
        if _is_win(db, card) or card in WIN_CONDITIONS or get_card_role(card) == "win_condition":
            locked.add(card)
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
    db,
    *,
    avoid_roles: frozenset[str] | None = None,
) -> str | None:
    protected = locked | _defensive_core_cards(deck, db)
    candidates = [
        c for c in deck
        if c not in protected
        and not (_is_win(db, c) or c in WIN_CONDITIONS or get_card_role(c) == "win_condition")
    ]
    if not candidates:
        return None

    generic = [c for c in candidates if c in GENERIC_CARDS]
    pool = generic or candidates

    def rank(card: str) -> tuple[int, int, float, int]:
        roles = _card_roles(db, card)
        penalty = 1 if avoid_roles and roles & avoid_roles else 0
        generic_rank = 0 if card in GENERIC_CARDS else 1
        syn = _avg_synergy_with_deck(db, card, deck)
        elixir = get_card_elixir(card)
        return (penalty, generic_rank, syn, -elixir)

    return min(pool, key=rank)


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
        return False

    role = _CATEGORY_ROLE.get(category)
    avoid_roles: frozenset[str] | None = None
    if category == "anti_air":
        avoid_roles = frozenset({ROLE_AIR})
    elif category == "point_target":
        avoid_roles = frozenset({ROLE_ANTI_TANK, ROLE_DEFENSIVE})
    elif category == "defense":
        avoid_roles = frozenset({ROLE_BUILDING, ROLE_DEFENSIVE, ROLE_SPLASH})

    drop = _pick_replaceable(deck, locked, db, avoid_roles=avoid_roles)
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
    if _is_win(db, drop) or drop in WIN_CONDITIONS:
        return False
    if not _swap_keeps_balance(deck, drop, pick, db):
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

    suggestions = _collect_improvement_gaps(deck, db)
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

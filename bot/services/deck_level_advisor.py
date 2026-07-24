"""Arena-aware card level advice and same-style higher-level deck swaps."""

from __future__ import annotations

from bot.services.card_data import WIN_CONDITIONS, get_card_elixir, get_card_role
from bot.services.card_level import to_display_level
from bot.services.card_matchups import synergy_partners
from bot.services.card_names_ru import card_name_ru
from bot.services.card_registry import get_card_info, resolve_card_icon
from bot.services.deck_analyzer import analyze_deck
from bot.services.deck_builder.loader import get_database

# Trophy Road arenas 1–32 — keep in sync with webapp arenaRecommendations.ts
_ARENA_MIN_TROPHIES: list[tuple[int, int]] = [
    (0, 1),
    (300, 2),
    (600, 3),
    (1000, 4),
    (1300, 5),
    (1600, 6),
    (2000, 7),
    (2300, 8),
    (2600, 9),
    (3000, 10),
    (3400, 11),
    (3800, 12),
    (4200, 13),
    (4600, 14),
    (5000, 15),
    (5500, 16),
    (6000, 17),
    (6500, 18),
    (7000, 19),
    (7500, 20),
    (8000, 21),
    (8500, 22),
    (9000, 23),
    (9500, 24),
    (10000, 25),
    (10500, 26),
    (11000, 27),
    (11500, 28),
    (12000, 29),
    (12500, 30),
    (13000, 31),
    (13500, 32),
]

_ARENA_NAME_ALIASES: dict[str, int] = {
    "goblin stadium": 1,
    "goblin": 1,
    "bone pit": 2,
    "barbarian bowl": 3,
    "barbarian": 3,
    "spell valley": 4,
    "charm valley": 4,
    "builder": 5,
    "p.e.k.k.a": 6,
    "pekka": 6,
    "playhouse": 6,
    "royal arena": 7,
    "frozen peak": 8,
    "jungle": 9,
    "hog mountain": 10,
    "electro valley": 11,
    "electro": 11,
    "spooky town": 12,
    "rascal": 13,
    "serenity peak": 14,
    "miner": 15,
    "executioner": 16,
    "royal crypt": 17,
    "silent sanctuary": 18,
    "dragon spa": 19,
    "boot camp": 20,
    "training camp": 20,
    "clash fest": 21,
    "фестиваль clash": 21,
    "pancake": 22,
    "блин": 22,
    "valkalla": 23,
    "вальхалла": 23,
    "legendary arena": 24,
    "legendary": 24,
    "легендарная": 24,
    "lumberlove": 25,
    "лесоруб": 25,
    "royal road": 26,
    "королевская дорога": 26,
    "musketeer street": 27,
    "мушкет": 27,
    "summit of heroes": 28,
    "вершина героев": 28,
    "magic academy": 29,
    "академия магии": 29,
    "ultimate clash pit": 30,
    "решающего clash": 30,
    "little prince": 31,
    "маленького принца": 31,
    "spirit square": 32,
    "площадь духов": 32,
}


def resolve_arena_by_trophies(trophies: int | None) -> int:
    t = int(trophies or 0)
    resolved = 1
    for min_trophies, arena in _ARENA_MIN_TROPHIES:
        if t >= min_trophies:
            resolved = arena
    return resolved


def resolve_arena_by_name(arena_name: str | None) -> int | None:
    if not arena_name:
        return None
    normalized = arena_name.lower()
    for key, arena in _ARENA_NAME_ALIASES.items():
        if key in normalized:
            return arena
    return None


def get_recommended_level_for_arena(arena: int) -> int:
    """Same thresholds as webapp getRecommendedLevelForArena."""
    if arena <= 4:
        return 6
    if arena <= 8:
        return 8
    if arena <= 12:
        return 10
    if arena <= 16:
        return 12
    if arena <= 20:
        return 13
    if arena <= 28:
        return 14
    if arena <= 30:
        return 15
    return 16


def resolve_player_arena_number(
    *,
    trophies: int | None,
    arena_id: int | None,
    arena_name: str | None = None,
) -> int:
    by_name = resolve_arena_by_name(arena_name)
    if by_name is not None:
        return by_name
    # Path of Legends / missing name → trophy road bracket (same as Recommendations UI)
    if arena_id is not None and arena_id >= 54_000_000:
        return resolve_arena_by_trophies(trophies)
    return resolve_arena_by_trophies(trophies)


def recommended_display_level(
    *,
    trophies: int | None,
    arena_id: int | None,
    arena_name: str | None = None,
) -> int:
    """Target card level from Recommendations (arenaRecommendations), not a separate ladder heuristic."""
    arena = resolve_player_arena_number(
        trophies=trophies,
        arena_id=arena_id,
        arena_name=arena_name,
    )
    return get_recommended_level_for_arena(arena)


def _normalize(name: str) -> str:
    return name.strip().lower()


def build_owned_level_map(player: dict) -> dict[str, dict]:
    """Map card name -> {level, rarity, icon, elixir} from CR player payload."""
    owned: dict[str, dict] = {}
    for raw in player.get("cards") or []:
        name = raw.get("name")
        if not name:
            continue
        info = get_card_info(name) or {}
        rarity = (raw.get("rarity") or info.get("rarity") or "").lower()
        api_level = raw.get("level")
        display = to_display_level(int(api_level) if api_level is not None else None, rarity)
        icons = raw.get("iconUrls") or {}
        api_icon = icons.get("medium") or icons.get("evolutionMedium") or ""
        icon = (
            resolve_card_icon(name, api_icon)
            or info.get("icon")
            or api_icon
            or ""
        )
        elixir = int(raw.get("elixirCost") or info.get("elixir") or get_card_elixir(name) or 0)
        owned[name] = {
            "name": name,
            "level": display,
            "rarity": rarity,
            "icon": icon,
            "elixir": elixir,
        }
    return owned


def _resolve_owned(owned: dict[str, dict], name: str) -> dict | None:
    if name in owned:
        return owned[name]
    key = _normalize(name)
    for cand, meta in owned.items():
        if _normalize(cand) == key:
            return meta
    return None


def annotate_deck_levels(
    deck: list[str],
    owned: dict[str, dict],
    recommended: int,
) -> list[dict]:
    rows: list[dict] = []
    for i, name in enumerate(deck):
        info = _resolve_owned(owned, name) or {}
        level = info.get("level")
        needs = level is not None and int(level) < recommended
        deficit = max(0, recommended - int(level)) if level is not None else 0
        card_info = get_card_info(name) or {}
        rows.append({
            "id": f"{name.lower().replace(' ', '-')}-{i}",
            "name": name,
            "name_ru": card_name_ru(name, short=True) or name,
            "icon": info.get("icon")
            or resolve_card_icon(name, card_info.get("icon") or "")
            or card_info.get("icon")
            or "",
            "cost": int(info.get("elixir") or card_info.get("elixir") or get_card_elixir(name) or 0),
            "level": level,
            "recommended_level": recommended,
            "needs_upgrade": needs,
            "deficit": deficit,
            "slot": i,
        })
    return rows


def upgrade_priority(cards: list[dict]) -> list[dict]:
    weak = [c for c in cards if c.get("needs_upgrade")]
    weak.sort(key=lambda c: (-int(c.get("deficit") or 0), int(c.get("level") or 0), c.get("name") or ""))
    return [
        {
            "name": c["name"],
            "name_ru": c.get("name_ru") or c["name"],
            "level": c.get("level"),
            "recommended_level": c.get("recommended_level"),
            "deficit": c.get("deficit") or 0,
            "icon": c.get("icon") or "",
        }
        for c in weak
    ]


def _primary_wins(deck: list[str]) -> list[str]:
    return [c for c in deck if c in WIN_CONDITIONS]


def _same_style_candidate(
    old: str,
    candidate: str,
    deck: list[str],
    locked: set[str],
) -> bool:
    if candidate in deck or candidate in locked:
        return False
    if abs(get_card_elixir(candidate) - get_card_elixir(old)) > 1:
        return False
    old_role = get_card_role(old)
    new_role = get_card_role(candidate)
    if old_role == new_role:
        return True
    # Soft fallback: allow support/tank swaps within defense-ish roles
    defense = {"support", "tank", "swarm", "building"}
    return old_role in defense and new_role in defense


def build_higher_level_style_deck(
    current_deck: list[str],
    owned: dict[str, dict],
    *,
    recommended: int,
    pool: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Swap underleveled / weak cards for higher-level owned cards of similar role.

    Keeps primary win-conditions locked. Returns (deck, notes).
    """
    if len(current_deck) != 8:
        return list(current_deck), []

    deck = list(current_deck)
    locked = set(_primary_wins(deck)[:2]) or set(_primary_wins(deck))
    notes: list[str] = []
    owned_names = set(owned.keys())
    if pool:
        owned_names &= set(pool)
    owned_names |= set(current_deck)

    db = get_database()

    for idx, card in enumerate(list(deck)):
        if card in locked:
            continue
        current_info = _resolve_owned(owned, card)
        current_level = int(current_info["level"]) if current_info and current_info.get("level") is not None else 0
        # Prefer upgrading slots that are below recommended, but also allow +2 level gains
        best: tuple[int, float, str] | None = None  # (level, synergy, name)

        for cand in owned_names:
            if not _same_style_candidate(card, cand, deck, locked):
                continue
            info = _resolve_owned(owned, cand)
            if not info or info.get("level") is None:
                continue
            cand_level = int(info["level"])
            if cand_level <= current_level:
                continue
            # Require meaningful upgrade: at least +1, and if current is ok vs arena, need +2
            if current_level >= recommended and cand_level < current_level + 2:
                continue
            strong, partial = synergy_partners(cand, set(deck) - {card} | {cand}, limit=8)
            syn = float(len(strong)) + 0.45 * float(len(partial))
            # Slight bonus if roles match via builder DB
            try:
                from bot.services.deck_builder.builder import _pair_synergy
                syn += max((_pair_synergy(db, cand, other) for other in deck if other != card), default=0.0) * 0.15
            except Exception:
                pass
            score = (cand_level, syn, cand)
            if best is None or score[0] > best[0] or (score[0] == best[0] and score[1] > best[1]):
                best = score

        if best is None:
            continue
        new_card = best[2]
        old_level = current_level
        new_level = int((_resolve_owned(owned, new_card) or {}).get("level") or 0)
        deck[idx] = new_card
        notes.append(
            f"{card_name_ru(card, short=True) or card} (ур. {old_level}) → "
            f"{card_name_ru(new_card, short=True) or new_card} (ур. {new_level})"
        )

    return deck, notes


def merge_deck_levels_from_battle(
    owned: dict[str, dict],
    battle_cards: list[dict] | None,
) -> dict[str, dict]:
    """Fill missing current-deck levels from the latest battle payload."""
    if not battle_cards:
        return owned
    out = dict(owned)
    for raw in battle_cards:
        name = raw.get("name")
        if not name or _resolve_owned(out, name):
            continue
        info = get_card_info(name) or {}
        rarity = (raw.get("rarity") or info.get("rarity") or "").lower()
        api_level = raw.get("level")
        display = to_display_level(int(api_level) if api_level is not None else None, rarity)
        icons = raw.get("iconUrls") or {}
        api_icon = icons.get("medium") or icons.get("evolutionMedium") or ""
        out[name] = {
            "name": name,
            "level": display,
            "rarity": rarity,
            "icon": resolve_card_icon(name, api_icon) or info.get("icon") or api_icon or "",
            "elixir": int(raw.get("elixirCost") or info.get("elixir") or get_card_elixir(name) or 0),
        }
    return out


def enrich_customize_result(
    base: dict,
    *,
    player: dict,
    trophies: int | None,
    arena_id: int | None,
    arena_name: str | None = None,
    pool: set[str] | None = None,
    battle_cards: list[dict] | None = None,
) -> dict:
    recommended = recommended_display_level(
        trophies=trophies,
        arena_id=arena_id,
        arena_name=arena_name,
    )
    owned = merge_deck_levels_from_battle(build_owned_level_map(player), battle_cards)

    original = list(base.get("original") or [])
    customized = list(base.get("customized") or original)
    original_cards = annotate_deck_levels(original, owned, recommended)
    upgrades = upgrade_priority(original_cards)

    alt_deck, alt_notes = build_higher_level_style_deck(
        original,
        owned,
        recommended=recommended,
        pool=pool,
    )
    level_alt_needed = alt_deck != original and bool(alt_notes)
    if not level_alt_needed:
        alt_deck = list(original)
        alt_notes = []

    alt_cards = annotate_deck_levels(alt_deck, owned, recommended)
    alt_stats = analyze_deck(alt_deck) if alt_deck else analyze_deck(original)
    synergy_needed = bool(base.get("needed")) or list(original) != list(customized)
    balanced = (not synergy_needed) and (not level_alt_needed) and (not upgrades)

    issues = list(base.get("issues") or [])
    if upgrades:
        names = ", ".join(
            f"{u['name_ru']} (ур. {u['level']} < {u['recommended_level']})"
            for u in upgrades[:4]
        )
        issues.append(f"Ниже рекомендуемого уровня ({recommended}): {names}")
    issues.extend(alt_notes)

    return {
        **base,
        "original": original,
        "customized": customized,
        "issues": issues,
        "recommended_level": recommended,
        "original_cards": original_cards,
        "customized_cards": annotate_deck_levels(customized, owned, recommended),
        "upgrade_priority": upgrades,
        "level_alt_deck": alt_deck,
        "level_alt_cards": alt_cards,
        "level_alt_needed": level_alt_needed,
        "level_alt_avg_elixir": alt_stats.avg_elixir,
        "synergy_needed": synergy_needed,
        "balanced": balanced,
    }

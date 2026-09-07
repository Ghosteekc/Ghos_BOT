"""Canonical, validated access to the static Cards Knowledge catalog.

``bot/data/cards.json`` owns card facts used by the application: canonical
names, elixir cost, type and role tags.  This module deliberately contains no
gameplay inference and no fallback profile for an unknown card.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


CARDS_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "cards.json"
CARD_TYPES = frozenset({"troop", "spell", "building"})
CARD_ROLES = frozenset({
    "win_condition", "tank", "mini_tank", "splash", "small_spell",
    "big_spell", "building", "air_defense", "flying", "swarm", "cycle",
    "anti_tank", "defensive", "anti_swarm", "counterpush", "dps",
    "support", "spell",
})


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key in cards catalog: {key!r}")
        result[key] = value
    return result


@lru_cache(maxsize=1)
def load_card_catalog() -> dict[str, dict[str, Any]]:
    """Load canonical static card data and reject malformed JSON keys."""
    raw = json.loads(
        CARDS_DATA_PATH.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicate_keys
    )
    cards = raw.get("cards") if isinstance(raw, dict) else None
    if not isinstance(cards, dict):
        raise ValueError("cards.json must contain an object at 'cards'")
    return cards


def canonical_card_names() -> frozenset[str]:
    return frozenset(load_card_catalog())


def resolve_canonical_card_name(raw_name: str | None) -> str | None:
    """Resolve an exact canonical name case-insensitively; never guess."""
    if not isinstance(raw_name, str):
        return None
    query = raw_name.strip()
    if not query:
        return None
    for name in load_card_catalog():
        if name.casefold() == query.casefold():
            return name
    return None


def evolution_has_role(name: str, role: str) -> bool:
    """Whether an explicitly equipped evolution adds a catalog role."""
    record = load_card_catalog().get(name)
    return bool(
        isinstance(record, dict)
        and role in (record.get("evolution_roles") or [])
    )


def validate_card_catalog() -> list[str]:
    """Return catalog integrity errors without inventing corrections."""
    errors: list[str] = []
    normalized_names: set[str] = set()
    for name, data in load_card_catalog().items():
        if not isinstance(name, str) or not name.strip():
            errors.append("empty canonical card name")
            continue
        normalized_name = name.strip().casefold()
        if normalized_name in normalized_names:
            errors.append(f"duplicate normalized canonical card name {name!r}")
        normalized_names.add(normalized_name)
        if not isinstance(data, dict):
            errors.append(f"{name}: record must be an object")
            continue
        elixir = data.get("elixir")
        if isinstance(elixir, bool) or not isinstance(elixir, int) or not 0 <= elixir <= 10:
            errors.append(f"{name}: invalid elixir {elixir!r}")
        card_type = data.get("type")
        if card_type not in CARD_TYPES:
            errors.append(f"{name}: invalid type {card_type!r}")
        roles = data.get("roles")
        if not isinstance(roles, list) or not roles:
            errors.append(f"{name}: roles must be a non-empty list")
            continue
        if len(roles) != len(set(roles)):
            errors.append(f"{name}: duplicate roles")
        invalid_roles = set(roles) - CARD_ROLES
        if invalid_roles:
            errors.append(f"{name}: invalid roles {sorted(invalid_roles)!r}")
        evolution_roles = data.get("evolution_roles", [])
        if not isinstance(evolution_roles, list):
            errors.append(f"{name}: evolution_roles must be a list")
        elif len(evolution_roles) != len(set(evolution_roles)):
            errors.append(f"{name}: duplicate evolution_roles")
        elif invalid_evolution_roles := set(evolution_roles) - CARD_ROLES:
            errors.append(
                f"{name}: invalid evolution_roles {sorted(invalid_evolution_roles)!r}"
            )
        abilities = data.get("abilities", [])
        if not isinstance(abilities, list) or any(
            not isinstance(ability, str) or not ability.strip() for ability in abilities
        ):
            errors.append(f"{name}: abilities must be a list of non-empty strings")
        elif len(abilities) != len(set(abilities)):
            errors.append(f"{name}: duplicate abilities")
        for field in ("forms", "components"):
            entries = data.get(field, [])
            if not isinstance(entries, list):
                errors.append(f"{name}: {field} must be a list")
                continue
            ids: set[str] = set()
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                    errors.append(f"{name}: {field} entry must have string id")
                    continue
                entry_id = entry["id"].strip()
                if not entry_id or entry_id in ids:
                    errors.append(f"{name}: duplicate/empty {field} id")
                ids.add(entry_id)
                entry_roles = entry.get("roles")
                if not isinstance(entry_roles, list) or not entry_roles:
                    errors.append(f"{name}: {field}.{entry_id} roles must be non-empty list")
                elif invalid := set(entry_roles) - CARD_ROLES:
                    errors.append(f"{name}: {field}.{entry_id} invalid roles {sorted(invalid)!r}")
                if field == "forms":
                    form_elixir = entry.get("elixir")
                    if isinstance(form_elixir, bool) or not isinstance(form_elixir, int) or not 0 <= form_elixir <= 10:
                        errors.append(f"{name}: {field}.{entry_id} invalid elixir {form_elixir!r}")
    return errors

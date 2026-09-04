"""Cross-source validation for Cards Knowledge data.

The validator reports stale references rather than silently accepting them.
It intentionally does not judge counter strength: those relations are
contextual and their tiers belong to their current data source.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from bot.services.card_knowledge import canonical_card_names, validate_card_catalog


def _relation_errors(
    label: str, relations: Mapping[str, Iterable[str]], known_names: frozenset[str]
) -> list[str]:
    errors: list[str] = []
    for source, targets in relations.items():
        if source not in known_names:
            errors.append(f"{label}: unknown source {source!r}")
        for target in targets:
            if target not in known_names:
                errors.append(f"{label}: {source!r} references unknown card {target!r}")
    return errors


def validate_card_knowledge() -> list[str]:
    """Validate catalog, human names and all current relationship snapshots."""
    from bot.data.deckshop_counters import DECKSHOP_COUNTERS
    from bot.services.card_data import (
        COUNTERS,
        MANUAL_COUNTERS_DENIED,
        MANUAL_COUNTERS_PARTIAL,
        MANUAL_COUNTERS_STRONG,
        SYNERGIES,
    )
    from bot.services.card_names_ru import CARD_NAMES_RU, CARD_NAMES_SHORT
    from bot.services.deck_builder.constants import KNOWN_SYNERGY_PAIRS

    known_names = canonical_card_names()
    errors = validate_card_catalog()
    for label, mapping in (("CARD_NAMES_RU", CARD_NAMES_RU), ("CARD_NAMES_SHORT", CARD_NAMES_SHORT)):
        for name, display_name in mapping.items():
            if name not in known_names:
                errors.append(f"{label}: unknown canonical card {name!r}")
            if not isinstance(display_name, str) or not display_name.strip():
                errors.append(f"{label}: empty display name for {name!r}")

    for label, relations in (
        ("COUNTERS", COUNTERS),
        ("SYNERGIES", SYNERGIES),
        ("MANUAL_COUNTERS_STRONG", MANUAL_COUNTERS_STRONG),
        ("MANUAL_COUNTERS_PARTIAL", MANUAL_COUNTERS_PARTIAL),
        ("MANUAL_COUNTERS_DENIED", MANUAL_COUNTERS_DENIED),
    ):
        errors.extend(_relation_errors(label, relations, known_names))

    for pair in KNOWN_SYNERGY_PAIRS:
        for name in pair:
            if name not in known_names:
                errors.append(f"KNOWN_SYNERGY_PAIRS: unknown card {name!r}")

    for source, row in DECKSHOP_COUNTERS.items():
        if source not in known_names:
            errors.append(f"DECKSHOP_COUNTERS: unknown source {source!r}")
        if not isinstance(row, dict):
            errors.append(f"DECKSHOP_COUNTERS: {source!r} row must be an object")
            continue
        for field in ("counters_vs_attack", "counters_vs_defense", "synergy_offense"):
            tiers = row.get(field) or {}
            if not isinstance(tiers, dict):
                errors.append(f"DECKSHOP_COUNTERS: {source!r}.{field} must be an object")
                continue
            for tier, targets in tiers.items():
                if tier not in {"strong", "partial"}:
                    errors.append(f"DECKSHOP_COUNTERS: {source!r}.{field} invalid tier {tier!r}")
                if not isinstance(targets, list):
                    errors.append(f"DECKSHOP_COUNTERS: {source!r}.{field}.{tier} must be a list")
                    continue
                if len(targets) != len(set(targets)):
                    errors.append(
                        f"DECKSHOP_COUNTERS: {source!r}.{field}.{tier} contains duplicate cards"
                    )
                for target in targets:
                    if target not in known_names:
                        errors.append(
                            f"DECKSHOP_COUNTERS: {source!r}.{field} references unknown card {target!r}"
                        )
                    elif target == source and field.startswith("counters_"):
                        errors.append(
                            f"DECKSHOP_COUNTERS: {source!r}.{field} must not contain a self-counter"
                        )
    return errors

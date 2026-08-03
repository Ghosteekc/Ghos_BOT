"""Tests for collection evolution/hero unlock parsing."""
from __future__ import annotations

from bot.services.player_collection import (
    _card_display_mode,
    _parse_card_upgrades,
    _resolve_icons,
)


def test_dual_path_both_unlocked_uses_catalog_hero_cap():
    """Season heroMedium may be missing on player payload; catalog still counts."""
    owned = {
        "name": "Valkyrie",
        "evolutionLevel": 3,
        "maxEvolutionLevel": 3,
        "iconUrls": {
            "medium": "base.png",
            "evolutionMedium": "evo.png",
            # no heroMedium yet
        },
    }
    info = {
        "name": "Valkyrie",
        "icon": "base.png",
        "evolution_icon": "evo.png",
        "hero_icon": "/cards/valkyrie-hero.png",
        "max_evolution_level": 3,
    }
    upgrades = _parse_card_upgrades(owned, info)
    assert upgrades["evolution_unlocked"] is True
    assert upgrades["hero_unlocked"] is True
    assert (
        _card_display_mode(
            True,
            evolution_unlocked=upgrades["evolution_unlocked"],
            hero_unlocked=upgrades["hero_unlocked"],
        )
        == "split"
    )


def test_dual_path_hero_only_level_2():
    owned = {
        "evolutionLevel": 2,
        "iconUrls": {"medium": "m", "evolutionMedium": "e", "heroMedium": "h"},
    }
    info = {"evolution_icon": "e", "hero_icon": "h", "max_evolution_level": 3}
    upgrades = _parse_card_upgrades(owned, info)
    assert upgrades["evolution_unlocked"] is False
    assert upgrades["hero_unlocked"] is True
    assert (
        _card_display_mode(
            True,
            evolution_unlocked=False,
            hero_unlocked=True,
        )
        == "hero"
    )


def test_dual_path_evo_only_level_1():
    owned = {
        "evolutionLevel": 1,
        "iconUrls": {"medium": "m", "evolutionMedium": "e", "heroMedium": "h"},
    }
    info = {"evolution_icon": "e", "hero_icon": "h"}
    upgrades = _parse_card_upgrades(owned, info)
    assert upgrades["evolution_unlocked"] is True
    assert upgrades["hero_unlocked"] is False


def test_resolve_icons_keeps_evo_and_hero_distinct():
    owned = {"iconUrls": {"medium": "base.png", "evolutionMedium": "evo.png"}}
    info = {
        "name": "Valkyrie",
        "icon": "base.png",
        "evolution_icon": "evo.png",
        "hero_icon": "/cards/valkyrie-hero.png",
    }
    base, evo, hero = _resolve_icons(owned, info)
    assert base == "base.png"
    assert evo == "evo.png"
    assert hero == "/cards/valkyrie-hero.png"
    assert evo != hero

"""The collection endpoint must expose only a confirmed API currentDeck."""

from __future__ import annotations

import asyncio

from bot.services import player_collection


def _catalog() -> dict[str, dict]:
    names = [
        "Knight",
        "Archers",
        "Goblins",
        "Fireball",
        "Giant",
        "Musketeer",
        "Mini P.E.K.K.A",
        "Zap",
    ]
    return {
        name.lower(): {
            "name": name,
            "icon": "",
            "evolution_icon": "",
            "hero_icon": "",
            "max_evolution_level": 0,
            "elixir": 3,
            "rarity": "common",
            "max_level": 16,
        }
        for name in names
    }


def _player_with_deck(names: list[str]) -> dict:
    return {
        "cards": [
            {
                "name": name,
                "level": 10,
                "maxLevel": 16,
                "count": 42,
                "rarity": "common",
                "iconUrls": {},
            }
            for name in names
        ],
        "currentDeck": [{"name": name} for name in names],
        "badges": [],
    }


def test_collection_exposes_confirmed_current_deck_only(monkeypatch) -> None:
    catalog = _catalog()

    async def load_catalog() -> dict[str, dict]:
        return catalog

    monkeypatch.setattr(player_collection, "ensure_cards_loaded", load_catalog)
    monkeypatch.setattr(player_collection, "get_card_info", lambda name: catalog.get(name.lower()))
    monkeypatch.setattr(player_collection, "resolve_card_name", lambda name: catalog.get(name.lower(), {}).get("name"))
    monkeypatch.setattr(player_collection, "canonical_card_names", lambda: set(c["name"] for c in catalog.values()))

    names = [card["name"] for card in catalog.values()]
    result = asyncio.run(player_collection.build_player_collection(_player_with_deck(names)))

    assert result["current_deck"] == names


def test_collection_omits_incomplete_or_unknown_current_deck(monkeypatch) -> None:
    catalog = _catalog()

    async def load_catalog() -> dict[str, dict]:
        return catalog

    monkeypatch.setattr(player_collection, "ensure_cards_loaded", load_catalog)
    monkeypatch.setattr(player_collection, "get_card_info", lambda name: catalog.get(name.lower()))
    monkeypatch.setattr(player_collection, "resolve_card_name", lambda name: catalog.get(name.lower(), {}).get("name"))
    monkeypatch.setattr(player_collection, "canonical_card_names", lambda: set(c["name"] for c in catalog.values()))

    names = [card["name"] for card in catalog.values()]
    player = _player_with_deck(names)
    player["currentDeck"][-1] = {"name": "Not a real card"}
    result = asyncio.run(player_collection.build_player_collection(player))

    assert result["current_deck"] == []

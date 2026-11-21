import asyncio

from bot.api.routes.misc import card_counters
from bot.services import card_registry, player_collection
from bot.services.clash_api import ClashRoyaleAPIError


def test_card_refresh_recovers_and_updates_collection_and_mastery(monkeypatch):
    clock = [1000.0]
    initial = {"id": 1, "name": "Knight"}
    new_card = {
        "id": 2,
        "name": "New Test Card",
        "iconUrls": {
            "medium": "https://example.com/base.png",
            "evolutionMedium": "https://example.com/evo.png",
            "heroMedium": "https://example.com/hero.png",
        },
    }
    responses = iter([
        ClashRoyaleAPIError("unavailable", 503),
        {"items": [initial]},
        {"items": []},
        {"items": [initial, {**new_card, "id": 1}]},
        {"items": [
            {**initial, "iconUrls": {"evolutionMedium": "https://example.com/knight-evo.png"}},
            new_card,
        ]},
    ])

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get_cards(self):
            result = next(responses)
            if isinstance(result, Exception):
                raise result
            return result

    monkeypatch.setattr(card_registry, "time", type("Clock", (), {"monotonic": lambda: clock[0]}))
    monkeypatch.setattr(card_registry, "ClashRoyaleClient", Client)
    monkeypatch.setattr(card_registry, "_cards_by_name", None)
    monkeypatch.setattr(card_registry, "_next_refresh_at", 0.0)

    async def check():
        assert await card_registry.ensure_cards_loaded() == {}
        assert await card_registry.ensure_cards_loaded() == {}
        clock[0] += card_registry._RETRY_SECONDS
        previous = await card_registry.ensure_cards_loaded()
        assert set(previous) == {"knight"}
        clock[0] += card_registry._REFRESH_SECONDS
        assert await card_registry._refresh_cards() is previous
        clock[0] += card_registry._RETRY_SECONDS
        assert await card_registry._refresh_cards() is previous
        clock[0] += card_registry._RETRY_SECONDS
        await card_registry._refresh_cards()

        catalog = await card_registry.get_cards_catalog()
        assert next(card for card in catalog if card["id"] == 1)["icon_evo"].endswith("knight-evo.png")
        added = next(card for card in catalog if card["id"] == 2)
        assert added["has_hero"] is True
        assert added["max_evolution_level"] == 3
        assert added["name_ru"] == new_card["name"]

        result = await player_collection.build_player_collection({
            "cards": [{"id": 2, "name": "Old Test Name", "evolutionLevel": 3}],
            "badges": [{"name": "MasteryNewTestCard"}, {"name": "MasteryImaginaryCard"}],
        })
        assert result["cards_total"] == 2
        owned = next(card for card in result["cards"] if card["owned"])
        assert owned["name"] == new_card["name"]
        assert owned["display_mode"] == "split"
        assert [badge["card_name"] for badge in result["masteries"]] == [new_card["name"]]
        counters = await card_counters(new_card["name"], user=None)
        assert counters.card == new_card["name"]
        assert counters.counters == counters.countered_by == []

    asyncio.run(check())


def test_hero_art_does_not_create_an_evolution():
    catalog = card_registry._parse_catalog({"items": [{
        "id": 1,
        "name": "New Hero Test Card",
        "maxEvolutionLevel": 2,
        "iconUrls": {"heroMedium": "https://example.com/hero.png"},
    }]})
    info = catalog["new hero test card"]
    assert not info["has_evolution"]
    assert player_collection._parse_card_upgrades({"evolutionLevel": 2}, info) == {
        "hero_unlocked": True,
        "evolution_unlocked": False,
        "evolution_stat": False,
    }

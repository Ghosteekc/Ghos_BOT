# Cards Knowledge

## Authoritative data

`bot/data/cards.json` is the authoritative static catalog for canonical card
names, elixir, type, and role tags. It is loaded by
`bot.services.deck_builder.loader.DeckDatabase` and exposed to other domains
through `bot.services.card_profile`. `bot.services.card_knowledge` validates
and resolves this catalog without a fallback for unknown names.

The live Clash Royale API, cached in `bot.services.card_registry`, is the
authoritative runtime source for Supercell card IDs, icons, collection details,
and deck-link IDs. It does not replace the local knowledge catalog's roles.

## Known legacy conflict

`bot.services.card_data` still duplicates card names and part of the semantic
knowledge (`CARD_META`, `WIN_CONDITIONS`, `COUNTERS`, `SYNERGIES`, and manual
counter overrides). `bot/data/deckshop_counters.py` is a separate offline
snapshot for counter and synergy tiers. These remain compatibility inputs;
they are not alternative sources for card identity, elixir, type, or roles.

Do not migrate or edit Deck Intelligence algorithms when changing card facts.
First update `cards.json`, then run `validate_card_knowledge()` to detect stale
references in legacy relationships, display-name maps, DeckShop snapshot, and
known synergy pairs. Counter tiers stay contextual (`strong` / `partial`) and
must not be presented as unconditional facts.

Some counter maps are intentionally closed. For example, Rocket is a strong
counter only to Sparky, Witch, Elixir Collector, and Elite Barbarians; it must
not acquire additional targets from generic building, role, or snapshot rules.
Rocket remains a finishing spell by default. Spell-cycle is a deck-level plan
when it is the only tower-damage plan, not an unconditional `win_condition`
role on the card.

## Consumers

Deck Intelligence reads `DeckDatabase` / `CardProfile`; Battle and Meta use the
same profile helpers plus relationship adapters. Ghosteek AI resolves user card
aliases during intent extraction and `card_info` now returns `UNKNOWN_CARD`
instead of fabricating a fallback profile. Replay recognition uses the live
registry snapshot and accepts only catalog-backed card IDs/names.

"""Точечная политика Ghosteek поверх снимка контр DeckShop.

DeckShop остаётся базовым источником связей. Здесь хранятся только
подтверждённые продуктовые поправки, которые не должны теряться при
следующем обновлении снимка.
"""

from __future__ import annotations


# Хог — win condition, а не универсальная защитная контра.
COUNTER_SOURCES_EXCLUDED = frozenset({"Hog Rider"})

# Подтверждённые ответы, отсутствующие в снимке DeckShop.
COUNTER_TIER_OVERRIDES: dict[str, dict[str, str]] = {
    "Mighty Miner": {"Valkyrie": "strong"},
}

# Это контекст колоды, а не связь графа «карта контрит саму себя».
# Поэтому правило применяется только при поиске ответов среди карт колоды.
MIRROR_ANSWER_TIERS: dict[str, str] = {
    "Valkyrie": "strong",
}

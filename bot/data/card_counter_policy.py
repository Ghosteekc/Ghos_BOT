"""Точечная политика Ghosteek поверх снимка контр DeckShop.

DeckShop остаётся базовым источником связей. Здесь хранятся только
подтверждённые продуктовые поправки, которые не должны теряться при
следующем обновлении снимка.
"""

from __future__ import annotations


# Хог — win condition, а не универсальная защитная контра. Клон и Зеркало
# воздействуют только на собственные розыгрыши, поэтому не являются контрами.
COUNTER_SOURCES_EXCLUDED = frozenset({"Clone", "Hog Rider", "Mirror"})

# Некоторые win condition — полноценные защитные бойцы. Разрешение точечное:
# это не отменяет запрет для Хога и атакующих зданий.
COUNTER_SOURCES_ALLOWED = frozenset({"Elite Barbarians"})

# Подтверждённые ответы, отсутствующие в снимке DeckShop.
COUNTER_TIER_OVERRIDES: dict[str, dict[str, str]] = {
    # Лучницы уверенно разбирают лёгкие воздушные отряды; в снимке эти
    # взаимодействия были занижены до partial.
    "Archers": {"Bats": "strong", "Minions": "strong"},
    "Mighty Miner": {"Valkyrie": "strong"},
    # Сборщик — стационарное вложение эликсира: его надёжно наказывают
    # тяжёлые заклинания, Earthquake и прямое давление на здания.
    "Earthquake": {"Elixir Collector": "strong"},
    "Goblin Drill": {"Elixir Collector": "strong"},
    "Lightning": {"Elixir Collector": "strong"},
    "Miner": {"Elixir Collector": "strong"},
    "Rocket": {"Elixir Collector": "strong"},
    "Wall Breakers": {"Elixir Collector": "strong"},
    # Доктор сбрасывает накопление урона связью с Монстром.
    "Goblinstein": {"Inferno Tower": "strong"},
}

# Это контекст колоды, а не связь графа «карта контрит саму себя».
# Поэтому правило применяется только при поиске ответов среди карт колоды.
MIRROR_ANSWER_TIERS: dict[str, str] = {
    "Valkyrie": "strong",
}

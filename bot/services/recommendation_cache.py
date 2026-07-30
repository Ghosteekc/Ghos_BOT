"""Кэш рекомендаций — одинаковая колода → одинаковый план улучшения."""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING, Hashable

if TYPE_CHECKING:
    from bot.services.recommendation_engine import RecommendationResult


def recommendation_cache_key(
    deck: list[str],
    *,
    archetype: str | None = None,
    apply_swaps: bool = True,
    arena_id: int | None = None,
    trophies: int | None = None,
    preferred_cards: list[str] | None = None,
    pool: set[str] | None = None,
    origin: str = "player",
    builder_score: float | None = None,
) -> tuple[Hashable, ...]:
    """Стабильный ключ: колода + контекст + происхождение (builder/player)."""
    deck_key = tuple(deck)
    preferred_key = tuple(sorted(preferred_cards or []))
    if pool is not None:
        pool_key: tuple[Hashable, ...] = ("custom", tuple(sorted(pool)))
    else:
        pool_key = (
            "arena",
            arena_id if arena_id is not None else -1,
            trophies if trophies is not None else -1,
        )
    score_key = round(float(builder_score), 1) if builder_score is not None else None
    return (
        deck_key,
        archetype or "",
        bool(apply_swaps),
        preferred_key,
        pool_key,
        origin or "player",
        score_key,
    )


class RecommendationCache:
    """LRU-кэш RecommendationResult. Без случайности, только hit/miss."""

    def __init__(self, maxsize: int = 256) -> None:
        self._maxsize = max(1, maxsize)
        self._store: OrderedDict[tuple[Hashable, ...], RecommendationResult] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: tuple[Hashable, ...]) -> RecommendationResult | None:
        item = self._store.get(key)
        if item is None:
            self.misses += 1
            return None
        self._store.move_to_end(key)
        self.hits += 1
        return item

    def put(self, key: tuple[Hashable, ...], value: RecommendationResult) -> None:
        if key in self._store:
            self._store.move_to_end(key)
            self._store[key] = value
        else:
            self._store[key] = value
            while len(self._store) > self._maxsize:
                self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()
        self.hits = 0
        self.misses = 0

    def __len__(self) -> int:
        return len(self._store)


# Глобальный кэш для всех режимов (конструктор / анализ / улучшение / сравнение).
recommendation_cache = RecommendationCache()

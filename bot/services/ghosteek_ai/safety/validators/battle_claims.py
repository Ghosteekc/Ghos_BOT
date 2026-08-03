"""validate_battle_claims — запрет выдуманных фактов боя без опоры на AIContext."""

from __future__ import annotations

import re
from typing import Any

from bot.services.ghosteek_ai.safety.facts import AllowedFacts, extract_allowed_facts
from bot.services.ghosteek_ai.safety.text_units import map_units

_DAMAGE_RE = re.compile(
    r"("
    r"(?:нанес\w*|нанесла|нанесли)\s+\d|"
    r"\d+[\s.,]?\d*\s*(?:урона|dmg|damage)|"
    r"урон\s*(?:карты|по\s+карт|=|:)?\s*\d|"
    r"точный\s+урон|"
    r"сколько\s+урона|"
    r"\bdmg\s*[:=]?\s*\d|"
    r"\bhp\s*[:=]?\s*\d|"
    r"\bхп\s*[:=]?\s*\d"
    r")",
    re.IGNORECASE,
)

_DPS_RE = re.compile(r"(\bdps\b|дпс)", re.IGNORECASE)

_OPP_ELIXIR_RE = re.compile(
    r"("
    r"эликсир\w*\s+(?:у\s+)?(?:соперник\w*|оппонент\w*|враг\w*)|"
    r"(?:соперник\w*|оппонент\w*|враг\w*)\s+[^.!?]{0,40}эликсир|"
    r"эликсир\w*\s+в\s+руке|"
    r"elixir\s+in\s+hand"
    r")",
    re.IGNORECASE,
)

_REPLAY_RE = re.compile(
    r"("
    r"репле\w*|"
    r"\breplay\b|"
    r"кадр\w*\s+боя|"
    r"запись\s+боя"
    r")",
    re.IGNORECASE,
)

_TIMER_RE = re.compile(
    r"("
    r"на\s+\d{1,3}\s*секунд|"
    r"в\s+\d{1,3}\s*секунд|"
    r"таймер\w*|"
    r"на\s+\d{1,2}:\d{2}|"
    r"на\s+какой\s+секунд|"
    r"в\s+какую\s+секунд"
    r")",
    re.IGNORECASE,
)

_POSITION_RE = re.compile(
    r"("
    r"позиционирован\w*|"
    r"стоял\w*\s+на\s+(?:клетк|тайл|позиц)|"
    r"поставил\w*\s+на\s+\d|"
    r"в\s+конкретн\w*\s+момент\w*\s+боя|"
    r"на\s+\d+\s*тайл"
    r")",
    re.IGNORECASE,
)

_NEUTRAL_DAMAGE = (
    "Точный урон карт по кадрам в данных нет — опираюсь на состав и матчап"
)
_NEUTRAL_DPS = "DPS по кадрам недоступен, поэтому оцениваю роль карты в составе"
_NEUTRAL_ELIXIR = (
    "Эликсир соперника в руке в данных нет — смотрим на темп и трейды по колоде"
)
_NEUTRAL_REPLAY = (
    "Реплея в данных нет — разбор идёт по составу, матчапу и исходу"
)
_NEUTRAL_TIMER = (
    "Точных секунд боя в данных нет — держимся механики и темпа"
)
_NEUTRAL_POSITION = (
    "Точного позиционирования по кадрам нет — совет через линии и ответы на угрозу"
)


def validate_battle_claims(
    text: str,
    ctx: Any | None = None,
    *,
    facts: AllowedFacts | None = None,
) -> str:
    """Переписать утверждения про урон/DPS/реплей/таймер/позицию без данных в контексте."""
    allowed = facts if facts is not None else extract_allowed_facts(ctx)

    def per_unit(unit: str) -> str:
        if _DAMAGE_RE.search(unit) and not allowed.has_damage:
            return _NEUTRAL_DAMAGE
        if _DPS_RE.search(unit) and not allowed.has_dps:
            return _NEUTRAL_DPS
        if _OPP_ELIXIR_RE.search(unit) and not allowed.has_opponent_elixir:
            return _NEUTRAL_ELIXIR
        if _REPLAY_RE.search(unit) and not allowed.has_replay:
            return _NEUTRAL_REPLAY
        if _TIMER_RE.search(unit) and not allowed.has_timer:
            return _NEUTRAL_TIMER
        if _POSITION_RE.search(unit) and not allowed.has_positioning:
            return _NEUTRAL_POSITION
        return unit

    return map_units(text, per_unit)

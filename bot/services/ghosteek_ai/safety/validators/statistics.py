"""validate_statistics — winrate / шансы / score без опоры на AIContext."""

from __future__ import annotations

import re
from typing import Any

from bot.services.ghosteek_ai.safety.facts import AllowedFacts, extract_allowed_facts
from bot.services.ghosteek_ai.safety.text_units import map_units

_STAT_CLAIM_RE = re.compile(
    r"("
    r"\d{1,3}(?:[.,]\d+)?\s*%\s*(?:шанс|винрейт|побед|wr|winrate)|"
    r"(?:шанс(?:ы|а)?|винрейт|вероятность\s+победы)\s*"
    r"(?:около\s*|примерно\s*|~)?\s*\d{1,3}(?:[.,]\d+)?\s*%|"
    r"статистика\s+показывает|"
    r"по\s+статистике\s+\d|"
    r"винрейт\s+\d"
    r")",
    re.IGNORECASE,
)

_SCORE_STAT_RE = re.compile(
    r"("
    r"(?:оценка|рейтинг|балл)\s*(?:колод\w*\s*)?(?:—|:)?\s*\d{1,3}|"
    r"score\s*[:=]\s*\d"
    r")",
    re.IGNORECASE,
)

_NEUTRAL_STATS = "Шансы хорошие — точнее опирайся на матчап и состав, без выдуманных процентов"
_NEUTRAL_SCORE = "Оценку держим качественной: смотри сильные и слабые стороны состава"


def validate_statistics(
    text: str,
    ctx: Any | None = None,
    *,
    facts: AllowedFacts | None = None,
) -> str:
    """Смягчить статистические утверждения без winrate/score в контексте."""
    allowed = facts if facts is not None else extract_allowed_facts(ctx)

    def per_unit(unit: str) -> str:
        if _STAT_CLAIM_RE.search(unit) and not (allowed.has_winrate or allowed.percentages):
            return _NEUTRAL_STATS
        if _SCORE_STAT_RE.search(unit) and not (
            allowed.has_score or allowed.has_evaluation or allowed.has_synergy
        ):
            return _NEUTRAL_SCORE
        return unit

    return map_units(text, per_unit)

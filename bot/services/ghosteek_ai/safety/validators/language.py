"""validate_language — зрительные/всеведущие формулировки → анализ данных."""

from __future__ import annotations

import re
from typing import Any

from bot.services.ghosteek_ai.safety.facts import AllowedFacts
from bot.services.ghosteek_ai.safety.text_units import map_units

# «Я увидел / посмотрел / заметил …»
_SIGHT_RE = re.compile(
    r"(?P<full>"
    r"(?:^|[\s,;:—–-])"
    r"(?P<phrase>"
    r"я\s+увидел(?:а|и)?|"
    r"я\s+посмотрел(?:а|и)?|"
    r"я\s+заметил(?:а|и)?|"
    r"я\s+наблюдал(?:а|и)?|"
    r"я\s+видел(?:а|и)?|"
    r"видно\s+по\s+репле|"
    r"по\s+реплею\s+видно"
    r")"
    r")",
    re.IGNORECASE,
)

_ANALYSIS_PHRASE = "По данным анализа"
_MATCH_PHRASE = "По информации матча"


def validate_language(
    text: str,
    ctx: Any | None = None,
    *,
    facts: AllowedFacts | None = None,
) -> str:
    """Заменить «я увидел/посмотрел/заметил» на опору на анализ/матч."""
    del facts  # язык не зависит от чисел; ctx может пригодиться позже
    has_battle = False
    if ctx is not None:
        battle = getattr(ctx, "battle", None)
        if battle is not None and (
            getattr(battle, "raw", None)
            or getattr(battle, "outcome_summary", None)
            or getattr(battle, "won", None) is not None
        ):
            has_battle = True

    replacement = _MATCH_PHRASE if has_battle else _ANALYSIS_PHRASE

    def per_unit(unit: str) -> str:
        def repl(match: re.Match[str]) -> str:
            prefix = match.group(0)[: len(match.group(0)) - len(match.group("phrase"))]
            # сохранить ведущий пробел/пунктуацию
            lead = prefix if prefix.startswith((" ", ",", ";", ":", "—", "–", "-")) else ""
            if not lead and match.start() > 0:
                lead = " "
            # начало предложения — с заглавной
            phrase = replacement
            if match.start() == 0 or (match.start() <= 1 and not unit[: match.start()].strip()):
                phrase = phrase[0].upper() + phrase[1:]
                lead = ""
            return f"{lead}{phrase}"

        return _SIGHT_RE.sub(repl, unit)

    return map_units(text, per_unit)

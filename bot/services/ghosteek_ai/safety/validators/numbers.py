"""validate_numbers — сверка числовых утверждений с AIContext."""

from __future__ import annotations

import re
from typing import Any

from bot.services.ghosteek_ai.safety.facts import AllowedFacts, extract_allowed_facts
from bot.services.ghosteek_ai.safety.text_units import map_units

# Проценты / шансы / винрейт
_PERCENT_CLAIM_RE = re.compile(
    r"(?P<full>"
    r"(?:у\s+тебя\s+)?"
    r"(?P<num>\d{1,3}(?:[.,]\d+)?)\s*%"
    r"(?:\s*(?:шанс(?:а|у|ом)?|винрейт|winrate|\bwr\b|вероятност\w*|побед\w*))?"
    r"|"
    r"(?:шанс(?:ы|а)?|винрейт|вероятность)\s*(?:на\s+победу\s*)?(?:около\s*|примерно\s*|~)?\s*"
    r"(?P<num2>\d{1,3}(?:[.,]\d+)?)\s*%"
    r")",
    re.IGNORECASE,
)

# Кубки / трофеи
_TROPHY_CLAIM_RE = re.compile(
    r"(?P<full>(?P<num>\d{3,5})\s*(?:кубк\w*|трофе\w*|trophies))",
    re.IGNORECASE,
)

# Synergy / score / оценка
_SCORE_CLAIM_RE = re.compile(
    r"(?P<full>"
    r"(?:синерг\w*|synergy|оценк\w*|рейтинг|score|балл\w*)\s*"
    r"(?:равн\w*\s*|составляет\s*|—\s*|:\s*)?"
    r"(?P<num>\d{1,3}(?:[.,]\d+)?)"
    r"(?:\s*/\s*\d{1,3})?"
    r"(?:\s*%)?"
    r")",
    re.IGNORECASE,
)

_NEUTRAL_CHANCE = "Шансы хорошие"
_NEUTRAL_SCORE = "По синергии и оценке картина умеренно уверенная"
_NEUTRAL_TROPHIES = "Кубки в данных есть, но точную цифру сейчас не фиксирую"


def _parse_num(raw: str) -> float | None:
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def _rewrite_percent_unit(unit: str, facts: AllowedFacts) -> str:
    def repl(match: re.Match[str]) -> str:
        raw = match.group("num") or match.group("num2")
        if raw is None:
            return _NEUTRAL_CHANCE
        value = _parse_num(raw)
        if value is None:
            return _NEUTRAL_CHANCE
        if facts.has_winrate or facts.has_score or facts.percentages:
            if facts.allows_percentage(value):
                return match.group(0)
            return _NEUTRAL_CHANCE
        return _NEUTRAL_CHANCE

    if not _PERCENT_CLAIM_RE.search(unit):
        return unit
    return _PERCENT_CLAIM_RE.sub(repl, unit)


def _rewrite_trophy_unit(unit: str, facts: AllowedFacts) -> str:
    def repl(match: re.Match[str]) -> str:
        value = _parse_num(match.group("num"))
        if value is None:
            return _NEUTRAL_TROPHIES
        if facts.has_trophies and facts.allows_number(value, tol=1.0):
            return match.group(0)
        if facts.has_trophies:
            # есть кубки, но цифра не совпала — нейтрально
            return _NEUTRAL_TROPHIES
        return _NEUTRAL_TROPHIES

    if not _TROPHY_CLAIM_RE.search(unit):
        return unit
    return _TROPHY_CLAIM_RE.sub(repl, unit)


def _rewrite_score_unit(unit: str, facts: AllowedFacts) -> str:
    def repl(match: re.Match[str]) -> str:
        value = _parse_num(match.group("num"))
        if value is None:
            return _NEUTRAL_SCORE
        if (facts.has_synergy or facts.has_evaluation or facts.has_score) and facts.allows_number(
            value, tol=1.0
        ):
            return match.group(0)
        if facts.has_synergy or facts.has_evaluation or facts.has_score:
            return _NEUTRAL_SCORE
        return _NEUTRAL_SCORE

    if not _SCORE_CLAIM_RE.search(unit):
        return unit
    # не трогаем чистые проценты — их закрывает percent validator
    if _PERCENT_CLAIM_RE.search(unit) and "%" in unit:
        return unit
    return _SCORE_CLAIM_RE.sub(repl, unit)


def validate_numbers(text: str, ctx: Any | None = None, *, facts: AllowedFacts | None = None) -> str:
    """Убрать/смягчить числа, которых нет в AIContext."""
    allowed = facts if facts is not None else extract_allowed_facts(ctx)

    def per_unit(unit: str) -> str:
        out = _rewrite_percent_unit(unit, allowed)
        out = _rewrite_trophy_unit(out, allowed)
        out = _rewrite_score_unit(out, allowed)
        return out

    return map_units(text, per_unit)

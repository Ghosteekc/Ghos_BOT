"""Пользовательские замечания по колоде — без внутренних кодов движка.

Структура для UI / issues:
  Что хорошо.
  Что можно улучшить.
  Итоговая рекомендация.
"""

from __future__ import annotations

from dataclasses import dataclass

# Фразы, которые нельзя показывать, если колода признана пригодной.
_REBUILD_MARKERS = (
    "пересобрать",
    "критический дисбаланс",
    "не стабильная сборка",
    "провалена по жёстким",
    "нужно пересобрать",
    "recommendationengine",
    "evaluationreport",
    "too_many_wins",
    "score breakdown",
)

_INTERNAL_MARKERS = (
    "recommendationengine",
    "evaluationreport",
    "too_many_wins",
    "deck_size",
    "duplicate_cards",
    "missing_core",
    "win_condition",
    "too_many_spells",
    "primary_win",
    "secondary_threat",
    "score breakdown",
    "/100",
)


@dataclass(frozen=True)
class PlayerRemarks:
    whats_good: tuple[str, ...]
    can_improve: tuple[str, ...]
    final_recommendation: str

    def as_issue_lines(self) -> list[str]:
        lines: list[str] = []
        if self.whats_good:
            lines.append("Что хорошо")
            lines.extend(self.whats_good)
        if self.can_improve:
            lines.append("Что можно улучшить")
            lines.extend(self.can_improve)
        if self.final_recommendation:
            lines.append("Итоговая рекомендация")
            lines.append(self.final_recommendation)
        return lines

    def to_dict(self) -> dict[str, object]:
        return {
            "whats_good": list(self.whats_good),
            "can_improve": list(self.can_improve),
            "final_recommendation": self.final_recommendation,
        }


def looks_internal(text: str) -> bool:
    low = (text or "").lower()
    if any(m in low for m in _INTERNAL_MARKERS):
        return True
    # Сырой код в скобках: (too_many_wins), (34/100)
    if "(" in text and ")" in text:
        inner = text[text.find("(") + 1 : text.find(")")].strip().lower()
        if inner.replace("_", "").isalnum() and ("_" in inner or "/" in inner):
            return True
        if "/100" in inner:
            return True
    return False


def looks_rebuild(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in _REBUILD_MARKERS)


def sanitize_player_line(text: str) -> str | None:
    """Убрать технические строки; вернуть None если текст нельзя показывать."""
    line = (text or "").strip()
    if not line:
        return None
    # Срезать ведущие маркеры sanity/debug.
    while line and line[0] in "⚠✔·•-–— ":
        line = line[1:].lstrip()
    if looks_internal(line):
        return None
    return line


def filter_improvable(
    lines: list[str] | tuple[str, ...],
    *,
    deck_playable: bool,
) -> list[str]:
    out: list[str] = []
    for raw in lines:
        clean = sanitize_player_line(raw)
        if not clean:
            continue
        if deck_playable and looks_rebuild(clean):
            continue
        if clean not in out:
            out.append(clean)
    return out


def build_player_remarks(
    *,
    strengths: list[str] | tuple[str, ...] = (),
    improvements: list[str] | tuple[str, ...] = (),
    deck_playable: bool,
    has_mandatory_swaps: bool = False,
    primary_win: str | None = None,
    secondary_pressure: list[str] | None = None,
    final_override: str | None = None,
) -> PlayerRemarks:
    """Собрать согласованный блок замечаний для игрока."""
    good = filter_improvable(list(strengths), deck_playable=False)[:4]

    # Secondary pressure — это плюс плана, не конфликт.
    for name in secondary_pressure or []:
        try:
            from bot.services.card_names_ru import card_name_ru
            label = card_name_ru(name, short=True) or name
        except Exception:
            label = name
        tip = (
            f"{label} даёт дополнительное давление, а не вторую независимую win condition"
        )
        if tip not in good and len(good) < 4:
            if primary_win:
                good.append(tip)

    improve = filter_improvable(list(improvements), deck_playable=deck_playable)[:4]

    if final_override:
        final = sanitize_player_line(final_override) or final_override
    elif has_mandatory_swaps:
        final = "Есть конкретные замены, которые сделают план атаки и защиту ровнее."
    elif deck_playable:
        final = (
            "Колода подходит для вашей арены — обязательных замен нет. "
            "Можно играть так и точечно усиливать слабые места."
        )
    elif improve:
        final = "Сначала закройте перечисленные дыры — после этого сборка станет стабильнее."
    else:
        final = "Колоде не хватает ясного плана — уточните главную угрозу и ответы на воздух/танки."

    # Если «подходит» — не оставляем пустой improve с противоречием.
    if deck_playable and not improve:
        improve = []

    return PlayerRemarks(
        whats_good=tuple(good[:4]),
        can_improve=tuple(improve[:4]),
        final_recommendation=final,
    )

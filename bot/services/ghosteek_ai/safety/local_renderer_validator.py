"""Deterministic facts-only gate for local Qwen3 renderer.

Не вызывает LLM. Не чинит текст эвристиками.
При нарушении policy → короткий fallback.
Cloud SafetyLayer не затрагивается (вызывается только при ctx.render_facts).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from bot.services.card_names_ru import CARD_NAMES_RU, CARD_NAMES_SHORT, card_name_ru

# Единственный пользовательский fallback при invalid local response.
LOCAL_RENDERER_INVALID_FALLBACK = "Не могу подтвердить этот вывод по доступным данным."
LOCAL_RENDERER_UNKNOWN_TOPIC_FALLBACK = (
    "Этого у меня в данных нет — не буду выдумывать. "
    "Могу разобрать колоду, бой или карту."
)

_TEMPLATE_ONLY = frozenset({"clarify", "unsupported", "unknown", ""})

_BANNED_CARD_ALIASES = frozenset(
    {
        # Только ложные «карты», не слово «тренер» (= коуч) в ответе.
        "elixir trainer",
        "эликсирный тренер",
        "эликс тренер",
        # Исторические галлюцинации (Elixir Golem counter) — не карты CR.
        "сокровище",
        "лагерь",
        "армада",
        "пожар",
    }
)

# «дракон» без dragon-карты в allowlist — частая выдумка.
_DRAGON_HINT_RE = re.compile(r"\bдракон\w*\b", re.IGNORECASE)
_WIN_CLAIM_RE = re.compile(
    r"(?:win\s*condition|вин-?кондишн\w*|основн\w+\s+угроз\w*)\s*[:—-]?\s*([A-Za-zА-Яа-яёЁ .]+)",
    re.IGNORECASE,
)

# Типичные generic coach tips (не из текущего ToolResult).
_GENERIC_COACH_TIP_RE = re.compile(
    r"("
    r"всегда\s+смотр\w+\s+на\s+эликсир|"
    r"не\s+забывай\s+про\s+цикл|"
    r"играй\s+от\s+защиты|"
    r"держи\s+темп\s+любой\s+ценой|"
    r"универсальн\w+\s+совет|"
    r"в\s+clash\s+royale\s+важно|"
    r"как\s+известно\s+в\s+мете"
    r")",
    re.IGNORECASE,
)

# Игровые механики / жаргон, которые можно проверить детерминированно.
_MECHANIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("beatdown", re.compile(r"\bbeatdown\b", re.I)),
    ("bridge_spam", re.compile(r"\bbridge\s*spam\b", re.I)),
    ("split_push", re.compile(r"\bsplit\s*push\b", re.I)),
    ("spell_cycle", re.compile(r"\bspell\s*cycle\b", re.I)),
    ("counterpush", re.compile(r"\bcounter[\s-]?push\b", re.I)),
    ("win_condition", re.compile(r"\bwin\s*condition\b", re.I)),
    ("kite", re.compile(r"\bkite\w*\b", re.I)),
    ("overcommit", re.compile(r"\bovercommit\w*\b", re.I)),
    ("positive_elixir_trade", re.compile(r"\bpositive\s+elixir\s+trade\b", re.I)),
    ("lane_control", re.compile(r"\blane\s*control\b", re.I)),
    ("вин-кондишн", re.compile(r"вин-?кондишн\w*", re.I)),
    ("контрпуш", re.compile(r"контрпуш\w*", re.I)),
    ("оверкоммит", re.compile(r"оверкоммит\w*\b", re.I)),
    ("спелл-цикл", re.compile(r"спелл[-\s]?цикл\w*", re.I)),
    ("китинг", re.compile(r"\bкитинг\w*\b", re.I)),
    ("бриджспам", re.compile(r"бридж[-\s]?спам\w*", re.I)),
    ("битдаун", re.compile(r"\bбитдаун\w*\b", re.I)),
)

_NUMBER_RE = re.compile(
    r"(?<![A-Za-zА-Яа-я])(\d+(?:[.,]\d+)?)(?![A-Za-zА-Яа-я])"
)


def _build_card_surface_index() -> list[tuple[str, str]]:
    pairs: dict[str, str] = {}
    for en, ru in CARD_NAMES_RU.items():
        pairs[en.lower()] = en
        pairs[ru.lower()] = en
    for en, ru in CARD_NAMES_SHORT.items():
        pairs[ru.lower()] = en
        pairs[en.lower()] = en
    return sorted(pairs.items(), key=lambda x: len(x[0]), reverse=True)


_CARD_SURFACE_INDEX = _build_card_surface_index()


@dataclass(frozen=True)
class LocalRendererValidation:
    ok: bool
    reason: str = ""


def _envelope_data(envelope: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        return {}
    data = envelope.get("data")
    return dict(data) if isinstance(data, dict) else {}


def _facts_blob(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("facts", "allowed_entities", "allowed_card_ids", "answer_constraints"):
        val = data.get(key)
        if isinstance(val, list):
            parts.extend(str(x) for x in val)
        elif val is not None:
            parts.append(str(val))
    return " ".join(parts).lower()


def _allowed_card_surfaces(allowed_card_ids: list[str]) -> set[str]:
    expanded: set[str] = set()
    for en in allowed_card_ids:
        if not isinstance(en, str) or not en.strip():
            continue
        expanded.add(en.lower())
        expanded.add(card_name_ru(en).lower())
        short = CARD_NAMES_SHORT.get(en)
        if short:
            expanded.add(short.lower())
        for canon_en, ru in CARD_NAMES_RU.items():
            if ru.lower() == en.lower() or canon_en.lower() == en.lower():
                expanded.add(canon_en.lower())
                expanded.add(ru.lower())
    return expanded


def _allowed_numbers(data: dict[str, Any]) -> set[float]:
    nums: set[float] = set()
    blob = _facts_blob(data)
    for match in _NUMBER_RE.finditer(blob):
        try:
            nums.add(float(match.group(1).replace(",", ".")))
        except ValueError:
            continue
    return nums


def find_ungrounded_cards(text: str, allowed_card_ids: list[str]) -> list[str]:
    """Canonical EN card ids mentioned in text but absent from allowlist.

    Сначала маскируем allowlist (длинные имена первыми), чтобы «Golem»
    внутри «Elixir Golem» не считался отдельной картой.
    """
    allowed = _allowed_card_surfaces(allowed_card_ids)
    masked = text or ""
    for surface in sorted(allowed, key=len, reverse=True):
        pattern = re.compile(rf"(?<!\w){re.escape(surface)}(?!\w)", re.IGNORECASE)
        masked = pattern.sub(" ", masked)

    found: list[str] = []
    seen: set[str] = set()
    for surface, canonical in _CARD_SURFACE_INDEX:
        if canonical in seen:
            continue
        if canonical.lower() in allowed or surface in allowed:
            continue
        pattern = re.compile(rf"(?<!\w){re.escape(surface)}(?!\w)", re.IGNORECASE)
        if pattern.search(masked):
            seen.add(canonical)
            found.append(canonical)
    return found


def find_ungrounded_numbers(text: str, allowed_nums: set[float]) -> list[float]:
    bad: list[float] = []
    for match in _NUMBER_RE.finditer(text or ""):
        try:
            val = float(match.group(1).replace(",", "."))
        except ValueError:
            continue
        if any(abs(val - n) <= 0.05 for n in allowed_nums):
            continue
        bad.append(val)
    return bad


def find_ungrounded_mechanics(text: str, facts_blob: str) -> list[str]:
    """Механики в тексте, которых нет в facts (детерминированный словарь)."""
    blob = facts_blob or ""
    bad: list[str] = []
    for name, pattern in _MECHANIC_PATTERNS:
        if not pattern.search(text or ""):
            continue
        if pattern.search(blob):
            continue
        if name.replace("_", " ") in blob or name.replace("_", "-") in blob:
            continue
        if name in blob:
            continue
        bad.append(name)
    return bad


def find_banned_aliases(text: str, facts_blob: str) -> list[str]:
    low = (text or "").lower()
    bad: list[str] = []
    for alias in _BANNED_CARD_ALIASES:
        if alias in low and alias not in (facts_blob or ""):
            bad.append(alias)
    return bad


def find_ungrounded_dragon_mention(text: str, allowed_card_ids: list[str]) -> bool:
    """Голое «дракон» без явного dragon-card из allowlist в тексте → invalid.

    Исторически модель писала просто «дракон» вместо реальной карты.
    """
    if not _DRAGON_HINT_RE.search(text or ""):
        return False
    low = (text or "").lower()
    for card in allowed_card_ids:
        if not isinstance(card, str):
            continue
        is_dragon = "dragon" in card.lower() or "дракон" in card_name_ru(card).lower()
        if not is_dragon:
            continue
        surfaces = {card.lower(), card_name_ru(card).lower()}
        short = CARD_NAMES_SHORT.get(card)
        if short:
            surfaces.add(short.lower())
        if any(s and s in low for s in surfaces):
            return False
    # Есть слово «дракон», но ни одна dragon-карта из allowlist не названа явно.
    return True


def _win_condition_cards_from_facts(facts: list[str], allowed_card_ids: list[str]) -> set[str]:
    out: set[str] = set()
    for line in facts:
        fl = line.lower()
        if not any(
            k in fl
            for k in (
                "win condition",
                "вин-кондишн",
                "основная угроза",
                "главная угроза",
            )
        ):
            continue
        for card in allowed_card_ids:
            if not isinstance(card, str):
                continue
            if card.lower() in fl or card_name_ru(card).lower() in fl:
                out.add(card.lower())
    return out


def find_invented_win_condition(
    text: str,
    facts: list[str],
    allowed_card_ids: list[str],
) -> str | None:
    """Новый win condition, которого нет в facts."""
    wc_allowed = _win_condition_cards_from_facts(facts, allowed_card_ids)
    for match in _WIN_CLAIM_RE.finditer(text or ""):
        chunk = (match.group(1) or "").strip().lower()
        if not chunk:
            continue
        for card in allowed_card_ids:
            if not isinstance(card, str):
                continue
            surfaces = {card.lower(), card_name_ru(card).lower()}
            short = CARD_NAMES_SHORT.get(card)
            if short:
                surfaces.add(short.lower())
            if not any(s and s in chunk for s in surfaces):
                continue
            if not wc_allowed:
                return card
            if card.lower() not in wc_allowed:
                return card
    return None


def find_generic_coach_tips(text: str, facts_blob: str) -> list[str]:
    """Generic tips не из текущего ToolResult."""
    blob = facts_blob or ""
    bad: list[str] = []
    for match in _GENERIC_COACH_TIP_RE.finditer(text or ""):
        tip = match.group(0)
        if tip.lower() not in blob:
            bad.append(tip)
    # Известные штампы из coach_tips.json
    for tip in (
        "Не переливай эликсир.",
        "Не открывай танка первым.",
        "Постоянно ротируй цикл.",
        "Играй от защиты и собирай контрпуш.",
    ):
        if tip.lower() in (text or "").lower() and tip.lower() not in blob:
            bad.append(tip)
    return bad


_INVENTED_IDENTITY_RE = re.compile(
    r"([A-Za-zА-Яа-яЁё][\w.-]{2,})\s*"
    r"(?:(?:—+|–+|:+)\s*(?:это\s+)?|\s+это\s+)"
    r"(?:такая\s+|такой\s+)?"
    r"(карта|стратеги\w*|механик\w*|тактик\w*)",
    re.IGNORECASE,
)


def find_invented_identity_claim(text: str, allowed_card_ids: list[str]) -> str | None:
    """«Holdik это стратегия» / «Narek это карта» без allowlist — выдумка."""
    if allowed_card_ids:
        return None
    match = _INVENTED_IDENTITY_RE.search(text or "")
    if not match:
        return None
    name = (match.group(1) or "").strip()
    if name.lower() in {"это", "как", "тут", "там", "просто", "clash", "royale"}:
        return None
    return name


_SWAP_HINT_RE = re.compile(
    r"("
    r"замени\w*"
    r"|поменя\w*"
    r"|смен\w*"
    r"|вместо\s+"
    r"|→"
    r"|->"
    r")",
    re.IGNORECASE,
)


def facts_allow_card_swap(facts: list[str] | str) -> bool:
    """Только строки FACTS — не answer_constraints (там те же фразы как инструкция)."""
    if isinstance(facts, list):
        blob = " ".join(str(x) for x in facts).lower()
    else:
        blob = (facts or "").lower()
    if "замены не нужны" in blob:
        return False
    return "рекомендуемая замена" in blob or "причина замены" in blob


def find_invented_card_swap(text: str, facts: list[str] | str) -> bool:
    """Свап в тексте, которого нет в ToolResult facts."""
    if not _SWAP_HINT_RE.search(text or ""):
        return False
    return not facts_allow_card_swap(facts)


def validate_local_renderer_response(
    text: str,
    envelope: dict[str, Any] | None,
    *,
    ctx: Any | None = None,
) -> LocalRendererValidation:
    """Строгая проверка local renderer ответа против facts envelope."""
    del ctx  # reserved for future tool-specific hooks
    raw = (text or "").strip()
    if not raw:
        return LocalRendererValidation(False, "empty_response")

    if raw == LOCAL_RENDERER_INVALID_FALLBACK:
        return LocalRendererValidation(True, "fallback")

    if not isinstance(envelope, dict) or not envelope:
        return LocalRendererValidation(False, "empty_envelope")

    if envelope.get("ok") is False:
        return LocalRendererValidation(False, "tool_failed")

    tool = str(envelope.get("tool") or "").strip().lower()
    if tool in _TEMPLATE_ONLY:
        return LocalRendererValidation(False, "unsupported_tool")

    data = _envelope_data(envelope)
    facts = [str(x) for x in (data.get("facts") or []) if str(x).strip()]
    allowed_cards = [
        str(x)
        for x in (data.get("allowed_card_ids") or [])
        if isinstance(x, str) and x.strip()
    ]
    facts_blob = _facts_blob(data)

    # Conversational: Qwen формулирует свободно. Блокируем только выдуманные карты.
    if tool == "chat":
        banned = find_banned_aliases(raw, facts_blob)
        if banned:
            return LocalRendererValidation(False, f"banned_alias:{banned[0]}")
        if find_ungrounded_dragon_mention(raw, allowed_cards):
            return LocalRendererValidation(False, "unknown_entity:дракон")
        ungrounded_cards = find_ungrounded_cards(raw, allowed_cards)
        if ungrounded_cards:
            return LocalRendererValidation(False, f"unknown_card:{ungrounded_cards[0]}")
        invented = find_invented_identity_claim(raw, allowed_cards)
        if invented:
            return LocalRendererValidation(False, f"invented_identity:{invented}")
        return LocalRendererValidation(True, "ok_chat")

    if not facts and not allowed_cards:
        return LocalRendererValidation(False, "empty_toolresult_facts")

    banned = find_banned_aliases(raw, facts_blob)
    if banned:
        return LocalRendererValidation(False, f"banned_alias:{banned[0]}")

    if find_ungrounded_dragon_mention(raw, allowed_cards):
        return LocalRendererValidation(False, "unknown_entity:дракон")

    ungrounded_cards = find_ungrounded_cards(raw, allowed_cards)
    if ungrounded_cards:
        return LocalRendererValidation(False, f"unknown_card:{ungrounded_cards[0]}")

    if find_invented_card_swap(raw, facts):
        return LocalRendererValidation(False, "invented_card_swap")

    invented_wc = find_invented_win_condition(raw, facts, allowed_cards)
    if invented_wc:
        return LocalRendererValidation(False, f"invented_win_condition:{invented_wc}")

    allowed_nums = _allowed_numbers(data)
    bad_nums = find_ungrounded_numbers(raw, allowed_nums)
    if bad_nums:
        return LocalRendererValidation(False, f"unknown_number:{bad_nums[0]}")

    bad_mech = find_ungrounded_mechanics(raw, facts_blob)
    if bad_mech:
        return LocalRendererValidation(False, f"unknown_mechanic:{bad_mech[0]}")

    tips = find_generic_coach_tips(raw, facts_blob)
    if tips:
        return LocalRendererValidation(False, f"generic_coach_tip:{tips[0][:40]}")

    return LocalRendererValidation(True, "ok")


def apply_local_renderer_gate(
    text: str,
    envelope: dict[str, Any] | None,
    *,
    ctx: Any | None = None,
) -> str:
    """Если invalid — заменить весь ответ на fallback (без эвристик)."""
    result = validate_local_renderer_response(text, envelope, ctx=ctx)
    if result.ok and (text or "").strip():
        return (text or "").strip()
    if (result.reason or "").startswith("invented_identity"):
        return LOCAL_RENDERER_UNKNOWN_TOPIC_FALLBACK
    return LOCAL_RENDERER_INVALID_FALLBACK

"""Stage 7: Grounded Moment Explanation.

FACTS = Source of Truth. Qwen only renders wording.
No raw video, no invented events/cards/elixir/damage/winner, no coaching.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from bot.services.ghosteek_ai.llm.messages import ChatMessage, MessageRole
from bot.services.ghosteek_ai.llm.prompt_builder import PromptBuilder
from bot.services.ghosteek_ai.replay.card_catalog import CardCatalog
from bot.services.ghosteek_ai.replay.evidence import ReplayVisualMoment
from bot.services.ghosteek_ai.replay.events import EVENT_CARD_PLAY_CONFIRMED
from bot.services.ghosteek_ai.replay.models import (
    OBS_BUILDING_VISIBLE,
    OBS_CARD_PLAY_CANDIDATE,
    OBS_CARD_VISIBLE,
    OBS_DEFENSIVE_INTERACTION_CANDIDATE,
    OBS_OFFENSIVE_INTERACTION_CANDIDATE,
    OBS_SPELL_VISIBLE,
    OBS_TOWER_DAMAGE_CANDIDATE,
    OBS_TROOP_VISIBLE,
    OBS_UNKNOWN,
    moment_max,
    moment_qwen_timeout_seconds,
    moment_render_enabled,
)
from bot.services.ghosteek_ai.safety.local_renderer_validator import find_ungrounded_cards

logger = logging.getLogger(__name__)


def _replay_wording_provider() -> Any:
    """Text renderer for moments/summary: cloud Groq/Qwen on Railway, Ollama only if configured."""
    from bot.config import settings
    from bot.services.ghosteek_ai.llm.provider import (
        OllamaProvider,
        get_llm_provider,
        ollama_config_from_settings,
    )

    backend = (settings.ghosteek_ai_backend or "").strip().lower()
    if backend in {"ollama", "local"}:
        return OllamaProvider(ollama_config_from_settings())
    if backend in {"qwen", "dashscope", "openai", "openai_compatible", "groq"}:
        return get_llm_provider(backend)
    if (settings.llm_api_key or "").strip() and (settings.llm_base_url or "").strip():
        base = (settings.llm_base_url or "").lower()
        return get_llm_provider("groq" if "groq.com" in base else "qwen")
    return OllamaProvider(ollama_config_from_settings())


EXPLANATION_CARD_VISIBLE = "CARD_VISIBLE"
EXPLANATION_CARD_PLAY_CONFIRMED = "CARD_PLAY_CONFIRMED"
EXPLANATION_TROOP_VISIBLE = "TROOP_VISIBLE"
EXPLANATION_SPELL_VISIBLE = "SPELL_VISIBLE"
EXPLANATION_BUILDING_VISIBLE = "BUILDING_VISIBLE"
EXPLANATION_TOWER_DAMAGE_CONFIRMED = "TOWER_DAMAGE_CONFIRMED"
EXPLANATION_DEFENSIVE_INTERACTION_CONFIRMED = "DEFENSIVE_INTERACTION_CONFIRMED"
EXPLANATION_OFFENSIVE_INTERACTION_CONFIRMED = "OFFENSIVE_INTERACTION_CONFIRMED"
EXPLANATION_UNKNOWN = "UNKNOWN"

_ALLOWED_KINDS = frozenset(
    {
        EXPLANATION_CARD_VISIBLE,
        EXPLANATION_CARD_PLAY_CONFIRMED,
        EXPLANATION_TROOP_VISIBLE,
        EXPLANATION_SPELL_VISIBLE,
        EXPLANATION_BUILDING_VISIBLE,
        EXPLANATION_TOWER_DAMAGE_CONFIRMED,
        EXPLANATION_DEFENSIVE_INTERACTION_CONFIRMED,
        EXPLANATION_OFFENSIVE_INTERACTION_CONFIRMED,
        EXPLANATION_UNKNOWN,
    }
)

_CANDIDATE_OR_UNSAFE = frozenset(
    {
        OBS_UNKNOWN,
        OBS_CARD_PLAY_CANDIDATE,
        OBS_TOWER_DAMAGE_CANDIDATE,
        OBS_DEFENSIVE_INTERACTION_CANDIDATE,
        OBS_OFFENSIVE_INTERACTION_CANDIDATE,
        "unknown",
    }
)

REPLAY_MOMENT_SYSTEM_PROMPT = """Ты — Ghosteek AI, игровой тренер Clash Royale.
Твоя задача — понятно и естественно объяснить уже подтверждённые события реплея.

Работай ТОЛЬКО с предоставленными facts.
Запрещено:
- придумывать карты, card play, эликсир, HP, damage, победителя;
- придумывать действия игрока или соперника;
- делать вывод о правильности хода;
- использовать мету как доказательство события;
- превращать candidate в confirmed;
- менять timestamp;
- добавлять события, которых нет во входных facts;
- давать coaching-советы.

Разделяй OBSERVATION и INTERPRETATION:
- CARD_VISIBLE → «виден X», НЕ «ты поставил X»;
- CARD_PLAY_CONFIRMED → можно сказать «ты разыграл X».

Ответ короткий, живой, по-человечески. Без технического жаргона.
Если данных мало — прямо скажи об ограничении простым языком.

Верни ТОЛЬКО JSON без markdown:
{"title":"...","description":"..."}
"""

REPLAY_SUMMARY_SYSTEM_PROMPT = """Ты — Ghosteek AI, тренер Clash Royale.
Собери короткий живой итог по уже подтверждённым facts реплея.

Запрещено придумывать карты, эликсир, урон, победителя, розыгрыши и советы.
Без технического жаргона. Варьируй формулировки, смысл не меняй.

Верни ТОЛЬКО JSON без markdown:
{"overview":"...","limitations":"..."}
"""

_PLAY_CLAIM_RE = re.compile(
    r"(ты\s+(?:разыграл|поставил|сыграл|кинул)|(?:разыграл|поставил|сыграл)\s+)",
    re.IGNORECASE,
)
_ELIXIR_RE = re.compile(
    r"(эликсир\s*[:=]?\s*\d|\d+\s*эликсир|elixir\s*[:=]?\s*\d|потратил\s+\d+)",
    re.IGNORECASE,
)
_DAMAGE_RE = re.compile(
    r"(\d+\s*(?:урона|урон|hp)|(?:нанес|снял|потеряла)\s+\d+|tower\s+(?:hp|damage)|\b\d+\s*damage\b)",
    re.IGNORECASE,
)
_WINNER_RE = re.compile(
    r"(ты\s+(?:выиграл|проиграл)|победа\s+за|противник\s+победил|you\s+(?:won|lost)|winner\s*(?:is|=))",
    re.IGNORECASE,
)
_COACHING_RE = re.compile(
    r"(нужно\s+было|следовало|ошибк[аи]|плохо\s+(?:поставил|сыграл)|неправильно|проиграл\s+из-за)",
    re.IGNORECASE,
)
_TECH_RE = re.compile(
    r"(grounded|observation_type|source\s*=\s*vision|confirmed\s+card\s+intervals|\bevent_type\b|card_play_candidate)",
    re.IGNORECASE,
)
_TS_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:сек|s)\b", re.IGNORECASE)
_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)

_TITLE_MAX = 80
_DESC_MAX = 280
_SUMMARY_MAX = 420

_LIMITATION_HUMAN = {
    "card_play_events_not_detected": "розыгрыши карт по кадрам не зафиксированы",
    "card_play_events_not_confirmed": "точные розыгрыши карт не подтверждены",
    "exact_card_timing_unavailable": "точные тайминги карт недоступны",
    "elixir_values_not_extracted": "числовые значения эликсира не извлечены",
    "damage_events_not_detected": "урон по башням и войскам не зафиксирован",
    "deck_identity_not_confirmed": "полная колода не подтверждена",
    "Frame vision for card plays is disabled on this server "
    "(REPLAY_VISION_ENABLED=0).": (
        "распознавание розыгрышей по кадрам выключено на сервере"
    ),
}


@dataclass(frozen=True)
class MomentExplanation:
    title: str
    short_description: str
    explanation_kind: str
    source: str  # qwen | fallback


@dataclass(frozen=True)
class ReplayGroundedSummary:
    overview: str
    limitations: str
    source: str  # qwen | fallback

    def to_dict(self) -> dict[str, str]:
        return {
            "overview": self.overview,
            "limitations": self.limitations,
            "source": self.source,
        }


def classify_explanation_kind(
    moment: ReplayVisualMoment,
    *,
    confirmed_events: Sequence[Any] = (),
    catalog: CardCatalog | None = None,
) -> str:
    et = str(moment.event_type or "").strip()
    if et in _CANDIDATE_OR_UNSAFE:
        return EXPLANATION_UNKNOWN
    if et == OBS_CARD_VISIBLE:
        if _has_confirmed_play(moment, confirmed_events, catalog=catalog):
            return EXPLANATION_CARD_PLAY_CONFIRMED
        return EXPLANATION_CARD_VISIBLE
    if et in {EVENT_CARD_PLAY_CONFIRMED, "card_play_confirmed"}:
        return EXPLANATION_CARD_PLAY_CONFIRMED
    if et == OBS_TROOP_VISIBLE:
        return EXPLANATION_TROOP_VISIBLE
    if et == OBS_SPELL_VISIBLE:
        return EXPLANATION_SPELL_VISIBLE
    if et == OBS_BUILDING_VISIBLE:
        return EXPLANATION_BUILDING_VISIBLE
    return EXPLANATION_UNKNOWN


def _has_confirmed_play(
    moment: ReplayVisualMoment,
    confirmed_events: Sequence[Any],
    *,
    catalog: CardCatalog | None = None,
) -> bool:
    card = (moment.card_name or "").strip().lower()
    if not card:
        return False
    ts = float(moment.timestamp_seconds)
    for ev in confirmed_events:
        et = str(getattr(ev, "event_type", "") or "")
        if et not in {EVENT_CARD_PLAY_CONFIRMED, "card_play_confirmed"}:
            continue
        ev_ts = float(getattr(ev, "timestamp_seconds", -1) or -1)
        if abs(ev_ts - ts) > 2.0:
            continue
        name = _event_card_name(ev, catalog=catalog)
        if name and name.lower() == card:
            return True
    return False


def _event_card_name(ev: Any, *, catalog: CardCatalog | None = None) -> str:
    details = getattr(ev, "details", None) or {}
    if isinstance(details, dict):
        name = str(details.get("card_name") or "").strip()
        if name:
            return name
    card_id = getattr(ev, "card_id", None)
    if card_id is None and isinstance(details, dict):
        card_id = details.get("card_id")
    if card_id is None:
        return ""
    cat = catalog
    if cat is None:
        try:
            cat = CardCatalog.from_loaded_registry()
        except Exception:
            return ""
    if cat is None or len(cat) == 0:
        return ""
    resolved = cat.resolve(card_id=str(card_id))
    return resolved.card_name if resolved else ""


def fallback_moment_explanation(
    moment: ReplayVisualMoment,
    *,
    kind: str | None = None,
    confirmed_events: Sequence[Any] = (),
) -> MomentExplanation:
    kind = kind or classify_explanation_kind(moment, confirmed_events=confirmed_events)
    ts = round(float(moment.timestamp_seconds), 1)
    card = (moment.card_name or "").strip()
    label = card or _human_event_label(moment.event_type)
    title = f"{ts} сек — {label}"

    if kind == EXPLANATION_CARD_PLAY_CONFIRMED and card:
        desc = f"Ты разыграл {card}. Это подтверждено анализом кадров."
    elif kind == EXPLANATION_CARD_VISIBLE and card:
        desc = (
            f"На {ts} секунде на поле подтверждён {card}. "
            f"Сам момент розыгрыша пока не подтверждён, поэтому не буду делать вывод о твоём решении."
        )
    elif kind == EXPLANATION_TROOP_VISIBLE and card:
        desc = f"На {ts} секунде уверенно виден юнит {card}."
    elif kind == EXPLANATION_SPELL_VISIBLE and card:
        desc = f"На {ts} секунде на поле подтверждено заклинание {card}."
    elif kind == EXPLANATION_BUILDING_VISIBLE and card:
        desc = f"На {ts} секунде на арене видно здание {card}."
    elif kind == EXPLANATION_TOWER_DAMAGE_CONFIRMED:
        desc = f"На {ts} секунде подтверждено повреждение башни по кадрам."
    elif kind in {
        EXPLANATION_DEFENSIVE_INTERACTION_CONFIRMED,
        EXPLANATION_OFFENSIVE_INTERACTION_CONFIRMED,
    }:
        desc = (
            f"На {ts} секунде видно игровое взаимодействие. "
            f"Детали хода пока не уточняю сверх фактов."
        )
    else:
        desc = (
            f"На {ts} секунде удалось уверенно распознать только отдельные элементы поля. "
            f"Для более точного вывода по этому моменту данных пока недостаточно."
        )
    return MomentExplanation(
        title=title[:_TITLE_MAX],
        short_description=desc[:_DESC_MAX],
        explanation_kind=kind,
        source="fallback",
    )


def fallback_replay_summary(
    *,
    moments: Sequence[ReplayVisualMoment] = (),
    limitations: Sequence[str] = (),
) -> ReplayGroundedSummary:
    from bot.services.ghosteek_ai.replay.models import vision_enabled

    if not vision_enabled() and not moments:
        overview = (
            "Реплей Clash Royale распознан, но разбор розыгрышей по кадрам "
            "на сервере пока выключен. Поэтому тайминги и конкретные карты в бою "
            "ещё не описываются."
        )
    elif not moments:
        overview = (
            "Пока удалось уверенно распознать только отдельные элементы поля. "
            "Для полноценного разбора этого реплея данных недостаточно."
        )
    else:
        names: list[str] = []
        for m in moments:
            if m.card_name and m.card_name not in names:
                names.append(m.card_name)
        if names:
            overview = (
                "В реплее уверенно распознаны несколько игровых объектов: "
                f"{', '.join(names[:4])}."
            )
        else:
            overview = (
                "В реплее уверенно распознаны несколько элементов интерфейса "
                "и отдельные игровые объекты."
            )
    lim = _format_limitations_text(limitations)
    return ReplayGroundedSummary(
        overview=overview[:_SUMMARY_MAX],
        limitations=lim[:_SUMMARY_MAX],
        source="fallback",
    )


def _format_limitations_text(limitations: Sequence[str]) -> str:
    human: list[str] = []
    for item in limitations:
        text = str(item).strip()
        if not text:
            continue
        mapped = _LIMITATION_HUMAN.get(text, text)
        if mapped and mapped not in human:
            human.append(mapped)
        if len(human) >= 3:
            break
    if human:
        return "Ограничения анализа: " + "; ".join(human) + "."
    return (
        "Пока анализ не позволяет надёжно восстановить все розыгрыши карт "
        "и точные значения эликсира."
    )


def validate_moment_explanation(
    *,
    title: str,
    description: str,
    moment: ReplayVisualMoment,
    kind: str,
    allowed_cards: set[str],
    allowed_timestamps: set[float],
    catalog: CardCatalog | None = None,
) -> str | None:
    title = (title or "").strip()
    description = (description or "").strip()
    if not title or not description:
        return "empty"
    if len(title) > _TITLE_MAX or len(description) > _DESC_MAX:
        return "too_long"
    if kind not in _ALLOWED_KINDS:
        return "bad_kind"
    blob = f"{title}\n{description}"
    if _TECH_RE.search(blob):
        return "technical_jargon"
    if _ELIXIR_RE.search(blob):
        return "invented_elixir"
    if _DAMAGE_RE.search(blob):
        return "invented_damage"
    if _WINNER_RE.search(blob):
        return "invented_winner"
    if _COACHING_RE.search(blob):
        return "coaching"
    if kind != EXPLANATION_CARD_PLAY_CONFIRMED and _PLAY_CLAIM_RE.search(blob):
        return "card_visible_as_play"
    if kind == EXPLANATION_CARD_PLAY_CONFIRMED and not (moment.card_name or "").strip():
        return "play_without_card"

    for match in _TS_RE.finditer(blob):
        raw = match.group(1).replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            return "bad_timestamp"
        if not _timestamp_allowed(value, allowed_timestamps):
            return "invented_timestamp"

    allowed_list = [c for c in allowed_cards if c]
    ungrounded = find_ungrounded_cards(blob, allowed_list)
    if ungrounded:
        return "hallucinated_card"

    mentioned = _extract_card_mentions(blob, allowed_cards, catalog)
    allowed_l = {c.lower() for c in allowed_cards}
    for name in mentioned:
        if name.lower() not in allowed_l:
            return "hallucinated_card"

    if moment.card_name:
        other = [n for n in mentioned if n.lower() != moment.card_name.lower()]
        if other:
            return "extra_card"
    return None


def validate_summary_text(
    *,
    overview: str,
    limitations: str,
    allowed_cards: set[str],
    allowed_timestamps: set[float],
    catalog: CardCatalog | None = None,
) -> str | None:
    overview = (overview or "").strip()
    limitations = (limitations or "").strip()
    if not overview or not limitations:
        return "empty"
    if len(overview) > _SUMMARY_MAX or len(limitations) > _SUMMARY_MAX:
        return "too_long"
    blob = f"{overview}\n{limitations}"
    if _ELIXIR_RE.search(blob):
        return "invented_elixir"
    if _DAMAGE_RE.search(blob):
        return "invented_damage"
    if _WINNER_RE.search(blob):
        return "invented_winner"
    if _COACHING_RE.search(blob):
        return "coaching"
    if _TECH_RE.search(blob):
        return "technical_jargon"
    for match in _TS_RE.finditer(blob):
        raw = match.group(1).replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            return "bad_timestamp"
        if allowed_timestamps and not _timestamp_allowed(value, allowed_timestamps):
            return "invented_timestamp"
    allowed_list = [c for c in allowed_cards if c]
    if find_ungrounded_cards(blob, allowed_list):
        return "hallucinated_card"
    allowed_l = {c.lower() for c in allowed_cards}
    for name in _extract_card_mentions(blob, allowed_cards, catalog):
        if name.lower() not in allowed_l:
            return "hallucinated_card"
    return None


def _timestamp_allowed(value: float, allowed: set[float]) -> bool:
    if not allowed:
        return True
    for ts in allowed:
        if abs(float(ts) - value) <= 0.6:
            return True
        if abs(float(round(float(ts))) - value) <= 0.05:
            return True
    return False


def _extract_card_mentions(
    text: str,
    allowed_cards: set[str],
    catalog: CardCatalog | None,
) -> list[str]:
    found: list[str] = []
    lower = text.lower()
    names = set(allowed_cards)
    if catalog is not None:
        for card in catalog.all_cards():
            names.add(card.card_name)
    for name in sorted(names, key=len, reverse=True):
        if name and name.lower() in lower and name not in found:
            found.append(name)
    return found


def _human_event_label(event_type: str) -> str:
    mapping = {
        OBS_CARD_VISIBLE: "карта на поле",
        OBS_TROOP_VISIBLE: "юнит",
        OBS_SPELL_VISIBLE: "заклинание",
        OBS_BUILDING_VISIBLE: "здание",
        OBS_TOWER_DAMAGE_CANDIDATE: "момент на поле",
        OBS_DEFENSIVE_INTERACTION_CANDIDATE: "момент на поле",
        OBS_OFFENSIVE_INTERACTION_CANDIDATE: "момент на поле",
        OBS_CARD_PLAY_CANDIDATE: "момент на поле",
    }
    return mapping.get(event_type, "момент")


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        match = _JSON_OBJ_RE.search(text)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None


def _moment_fact_payload(
    moment: ReplayVisualMoment,
    kind: str,
    *,
    limitations: Sequence[str],
) -> dict[str, Any]:
    return {
        "explanation_kind": kind,
        "event_type": moment.event_type,
        "timestamp_seconds": round(float(moment.timestamp_seconds), 3),
        "card_name": moment.card_name,
        "confidence": round(float(moment.confidence), 4),
        "source": moment.source,
        "evidence_frame": {
            "timestamp_seconds": round(float(moment.evidence_frame.timestamp_seconds), 3),
            "frame_index": int(moment.evidence_frame.frame_index),
        },
        "limitations": list(limitations)[:8],
        "rules": {
            "CARD_VISIBLE": "say visible only; do not claim the player played the card",
            "CARD_PLAY_CONFIRMED": "may say the player played the card",
            "UNKNOWN": "neutral observation; admit limited data",
        },
    }


class _MomentPromptBuilder(PromptBuilder):
    def __init__(self, facts_json: str) -> None:
        super().__init__(system_prompt=REPLAY_MOMENT_SYSTEM_PROMPT, constraints="")
        self._facts_json = facts_json

    def build(self, ctx: Any = None, **kwargs: Any) -> list[ChatMessage]:
        del kwargs
        user_msg = "Сформулируй короткое объяснение только по этим facts."
        if ctx is not None and getattr(ctx, "raw_message", None):
            user_msg = str(ctx.raw_message).strip() or user_msg
        return [
            ChatMessage(role=MessageRole.SYSTEM, content=REPLAY_MOMENT_SYSTEM_PROMPT),
            ChatMessage(role=MessageRole.SYSTEM, content=f"FACTS JSON:\n{self._facts_json}"),
            ChatMessage(role=MessageRole.USER, content=user_msg),
        ]


class _SummaryPromptBuilder(PromptBuilder):
    def __init__(self, facts_json: str) -> None:
        super().__init__(system_prompt=REPLAY_SUMMARY_SYSTEM_PROMPT, constraints="")
        self._facts_json = facts_json

    def build(self, ctx: Any = None, **kwargs: Any) -> list[ChatMessage]:
        del kwargs
        user_msg = "Собери короткий итог реплея только по facts."
        if ctx is not None and getattr(ctx, "raw_message", None):
            user_msg = str(ctx.raw_message).strip() or user_msg
        return [
            ChatMessage(role=MessageRole.SYSTEM, content=REPLAY_SUMMARY_SYSTEM_PROMPT),
            ChatMessage(role=MessageRole.SYSTEM, content=f"FACTS JSON:\n{self._facts_json}"),
            ChatMessage(role=MessageRole.USER, content=user_msg),
        ]


class ReplayMomentRenderer:
    """Explain confirmed visual moments. Qwen renders; validator fact-locks."""

    def __init__(
        self,
        *,
        provider: Any | None = None,
        catalog: CardCatalog | None = None,
        max_moments: int | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._provider = provider
        self._owns_provider = provider is None
        self._catalog = catalog
        self._max = int(max_moments) if max_moments is not None else moment_max()
        self._timeout = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else moment_qwen_timeout_seconds()
        )

    async def _ensure_provider(self) -> Any:
        if self._provider is None:
            self._provider = _replay_wording_provider()
            self._owns_provider = True
        return self._provider

    async def close(self) -> None:
        if self._owns_provider and self._provider is not None:
            await self._provider.close()
        if self._owns_provider:
            self._provider = None

    async def arender_moments(
        self,
        moments: Sequence[ReplayVisualMoment],
        *,
        confirmed_events: Sequence[Any] = (),
        limitations: Sequence[str] = (),
        use_qwen: bool = True,
    ) -> list[ReplayVisualMoment]:
        if not moment_render_enabled():
            return list(moments)
        try:
            selected = list(moments)[: max(0, self._max)]
            out: list[ReplayVisualMoment] = []
            qwen_budget = self._max if use_qwen else 0
            for moment in selected:
                kind = classify_explanation_kind(
                    moment,
                    confirmed_events=confirmed_events,
                    catalog=self._catalog,
                )
                explanation: MomentExplanation | None = None
                if qwen_budget > 0:
                    explanation = await self._explain_with_qwen(
                        moment, kind=kind, limitations=limitations
                    )
                    qwen_budget -= 1
                if explanation is None:
                    explanation = fallback_moment_explanation(
                        moment, kind=kind, confirmed_events=confirmed_events
                    )
                out.append(
                    replace(
                        moment,
                        title=explanation.title,
                        short_description=explanation.short_description,
                        explanation_kind=explanation.explanation_kind,
                        explanation_source=explanation.source,
                    )
                )
            return out
        finally:
            await self.close()

    async def _explain_with_qwen(
        self,
        moment: ReplayVisualMoment,
        *,
        kind: str,
        limitations: Sequence[str],
    ) -> MomentExplanation | None:
        allowed_cards = {c for c in [moment.card_name] if c}
        allowed_ts = {
            round(float(moment.timestamp_seconds), 3),
            round(float(moment.evidence_frame.timestamp_seconds), 3),
        }
        payload = _moment_fact_payload(moment, kind, limitations=limitations)
        try:
            raw = await self._call_qwen(
                _MomentPromptBuilder(json.dumps(payload, ensure_ascii=False)),
                user_message="Верни JSON title+description по facts.",
            )
        except Exception:
            logger.info("moment renderer Qwen failed — fallback", exc_info=True)
            return None
        data = _parse_json_object(raw)
        if data is None:
            return None
        title = str(data.get("title") or "").strip()
        desc = str(data.get("description") or data.get("short_description") or "").strip()
        reason = validate_moment_explanation(
            title=title,
            description=desc,
            moment=moment,
            kind=kind,
            allowed_cards=allowed_cards,
            allowed_timestamps=allowed_ts,
            catalog=self._catalog,
        )
        if reason:
            logger.info("moment renderer rejected qwen output: %s", reason)
            return None
        return MomentExplanation(
            title=title[:_TITLE_MAX],
            short_description=desc[:_DESC_MAX],
            explanation_kind=kind,
            source="qwen",
        )

    async def _call_qwen(self, builder: PromptBuilder, *, user_message: str) -> str:
        from types import SimpleNamespace

        from bot.services.ghosteek_ai.generator.llm_generator import LLMResponseGenerator

        provider = await self._ensure_provider()
        gen = LLMResponseGenerator(provider=provider, prompt_builder=builder)
        ctx = SimpleNamespace(raw_message=user_message)
        result = await asyncio.wait_for(
            gen.agenerate(
                ctx,
                tools=None,
                temperature=0.45,
                max_tokens=160,
                num_ctx=4096,
                think=False,
            ),
            timeout=self._timeout,
        )
        if not isinstance(result, str):
            raise ValueError("moment renderer expected text response")
        return result.strip()


class ReplaySummaryRenderer:
    """Short grounded replay summary. No coaching, no invented events."""

    def __init__(
        self,
        *,
        provider: Any | None = None,
        catalog: CardCatalog | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._provider = provider
        self._owns_provider = provider is None
        self._catalog = catalog
        self._timeout = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else moment_qwen_timeout_seconds()
        )

    async def _ensure_provider(self) -> Any:
        if self._provider is None:
            self._provider = _replay_wording_provider()
            self._owns_provider = True
        return self._provider

    async def close(self) -> None:
        if self._owns_provider and self._provider is not None:
            await self._provider.close()
        if self._owns_provider:
            self._provider = None

    async def arender(
        self,
        *,
        moments: Sequence[ReplayVisualMoment] = (),
        facts: Sequence[str] = (),
        limitations: Sequence[str] = (),
        timeline: Sequence[Any] = (),
        use_qwen: bool = True,
    ) -> ReplayGroundedSummary:
        if not moment_render_enabled():
            return fallback_replay_summary(moments=moments, limitations=limitations)

        allowed_cards = {m.card_name for m in moments if m.card_name}
        allowed_ts = {round(float(m.timestamp_seconds), 3) for m in moments}
        compact_moments = [
            {
                "timestamp_seconds": round(float(m.timestamp_seconds), 3),
                "event_type": m.event_type,
                "card_name": m.card_name,
                "explanation_kind": getattr(m, "explanation_kind", None)
                or classify_explanation_kind(m, catalog=self._catalog),
                "title": getattr(m, "title", None),
                "short_description": getattr(m, "short_description", None),
            }
            for m in list(moments)[: moment_max()]
        ]
        payload = {
            "visual_moments": compact_moments,
            "facts": [str(x) for x in facts][:20],
            "limitations": [str(x) for x in limitations][:12],
            "timeline_len": len(list(timeline)),
            "note": "Do not invent cards, elixir, damage, winner, or plays.",
        }
        if not use_qwen:
            return fallback_replay_summary(moments=moments, limitations=limitations)
        try:
            try:
                raw = await self._call_qwen(json.dumps(payload, ensure_ascii=False))
            except Exception:
                logger.info("summary renderer Qwen failed — fallback", exc_info=True)
                return fallback_replay_summary(moments=moments, limitations=limitations)
            data = _parse_json_object(raw)
            if data is None:
                return fallback_replay_summary(moments=moments, limitations=limitations)
            overview = str(data.get("overview") or "").strip()
            lim = str(data.get("limitations") or "").strip()
            reason = validate_summary_text(
                overview=overview,
                limitations=lim,
                allowed_cards=allowed_cards,
                allowed_timestamps=allowed_ts,
                catalog=self._catalog,
            )
            if reason:
                logger.info("summary renderer rejected qwen output: %s", reason)
                return fallback_replay_summary(moments=moments, limitations=limitations)
            return ReplayGroundedSummary(
                overview=overview[:_SUMMARY_MAX],
                limitations=lim[:_SUMMARY_MAX],
                source="qwen",
            )
        finally:
            await self.close()

    async def _call_qwen(self, facts_json: str) -> str:
        from types import SimpleNamespace

        from bot.services.ghosteek_ai.generator.llm_generator import LLMResponseGenerator

        provider = await self._ensure_provider()
        builder = _SummaryPromptBuilder(facts_json)
        gen = LLMResponseGenerator(provider=provider, prompt_builder=builder)
        ctx = SimpleNamespace(raw_message="Верни JSON overview+limitations по facts.")
        result = await asyncio.wait_for(
            gen.agenerate(
                ctx,
                tools=None,
                temperature=0.45,
                max_tokens=220,
                num_ctx=4096,
                think=False,
            ),
            timeout=self._timeout,
        )
        if not isinstance(result, str):
            raise ValueError("summary renderer expected text response")
        return result.strip()

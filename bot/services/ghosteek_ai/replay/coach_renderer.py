"""Replay coach: Qwen renders structured analysis → natural coach text.

Qwen is NOT source of truth. No raw video/frames. Fallback on any failure.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from bot.services.card_names_ru import card_name_ru
from bot.services.ghosteek_ai.llm.messages import ChatMessage, MessageRole
from bot.services.ghosteek_ai.llm.prompt_builder import PromptBuilder
from bot.services.ghosteek_ai.replay.battle_timeline import ReplayBattleTimeline
from bot.services.ghosteek_ai.replay.card_recognizer import ConfirmedCardFact
from bot.services.ghosteek_ai.replay.events import (
    EVENT_CARD_PLAY_CANDIDATE,
    ReplayEvent,
)
from bot.services.ghosteek_ai.replay.tactical_analysis import ReplayTacticalAnalysis
from bot.services.ghosteek_ai.safety.local_renderer_validator import (
    find_ungrounded_cards,
)

logger = logging.getLogger(__name__)

REPLAY_COACH_TOOL = "replay_coach"

REPLAY_COACH_SYSTEM_PROMPT = """Ты — Ghosteek AI, игровой тренер Clash Royale.

Ты разговариваешь с пользователем как живой доброжелательный тренер.

Твои ответы:
- естественные
- понятные
- краткие
- разнообразные по формулировкам
- без канцелярита
- без повторяющихся шаблонов

Но ты НИКОГДА не выдумываешь игровые факты.

Источник истины — только предоставленный structured replay data в блоках FACTS / CARDS / EVENTS / LIMITATIONS.

Если событие не подтверждено — считай его неизвестным.
Если данных недостаточно для вывода — прямо скажи это.

Нельзя придумывать:
- карты
- тайминги
- эликсир
- урон
- HP башен
- действия игрока
- действия противника
- причины поражения

Нельзя превращать предположение в факт.

Если есть candidate event, используй формулировки:
"похоже"
"возможно"
"по доступным кадрам"

Если confidence высокий и timestamp есть в EVENTS:
можно сказать вроде «На N-й секунде…» только для подтверждённых событий.

Если данных недостаточно:
"Этот момент я пока не могу подтвердить по видео."

Не повторяй весь технический timeline.
Пользователь должен получать именно тренерский вывод.

Предпочтительная структура (не копируй каждый раз одинаково):
короткий вывод → что было хорошо → что можно улучшить → 1–3 момента → следующий совет.

Не упоминай raw video, ffmpeg, frames files, Qwen, Ollama, JSON.
Не анализируй видео сам — его тебе не передавали.
"""

REPLAY_COACH_TEMPERATURE = 0.38
REPLAY_COACH_NUM_PREDICT = 320
REPLAY_COACH_NUM_CTX = 4096
REPLAY_COACH_THINK = False

_INVENTED_CLAIM_RE = re.compile(
    r"("
    r"плохо\s+потратил\s+эликсир|"
    r"слишком\s+рано\s+поставил|"
    r"проиграл\s+из-за\s+плохой\s+защиты|"
    r"tower\s+hp|"
    r"\b\d+\s*hp\b|"
    r"нанес\s+\d+\s*урон|"
    r"потратил\s+\d+\s*эликсир"
    r")",
    re.IGNORECASE,
)

_RAW_MEDIA_RE = re.compile(
    r"("
    r"raw\s+video|"
    r"ffmpeg|"
    r"frame_path|"
    r"\.mp4\b|"
    r"base64|"
    r"/tmp/|"
    r"ollama|"
    r"\bqwen\b"
    r")",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ReplayCoachResult:
    text: str
    source: str  # "qwen" | "template"
    envelope: dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "coach_reply": self.text,
            "coach_source": self.source,
        }


def replay_coach_generate_kwargs() -> dict[str, Any]:
    from bot.config import settings

    configured_temp = float(getattr(settings, "ollama_temperature", 0) or 0)
    if 0.3 <= configured_temp <= 0.45:
        temperature = configured_temp
    else:
        temperature = REPLAY_COACH_TEMPERATURE

    configured_predict = int(getattr(settings, "ollama_num_predict", 0) or 0)
    if 256 <= configured_predict <= 384:
        max_tokens = configured_predict
    else:
        max_tokens = REPLAY_COACH_NUM_PREDICT

    configured_ctx = int(getattr(settings, "ollama_num_ctx", 0) or 0)
    num_ctx = max(configured_ctx, REPLAY_COACH_NUM_CTX) if configured_ctx else REPLAY_COACH_NUM_CTX

    return {
        "temperature": temperature,
        "max_tokens": max_tokens,
        "num_ctx": num_ctx,
        "think": False,
    }


def build_replay_coach_envelope(
    *,
    tactical: ReplayTacticalAnalysis | None,
    battle_timeline: ReplayBattleTimeline | None,
    confirmed_cards: Sequence[ConfirmedCardFact] = (),
    confirmed_events: Sequence[ReplayEvent] = (),
    events: Sequence[ReplayEvent] = (),
    limitations: Sequence[str] = (),
) -> dict[str, Any]:
    """Compact FACTS envelope. Never includes video/frames."""
    cards = [c for c in confirmed_cards if float(c.confidence) >= 0.90]
    conf_events = list(confirmed_events)
    if not conf_events and battle_timeline is not None:
        conf_events = list(battle_timeline.confirmed_events)

    allowed_names: list[str] = []
    for card in cards:
        name = str(card.card_name or "").strip()
        if name and name not in allowed_names:
            allowed_names.append(name)
    for ev in conf_events:
        # card_id alone is not a display name — only confirmed_cards names are authoritative labels
        pass

    facts: list[str] = []
    if tactical is not None:
        if tactical.summary:
            facts.append(f"summary: {tactical.summary}")
        for line in tactical.positive_actions[:6]:
            facts.append(f"positive: {line}")
        for line in tactical.possible_mistakes[:4]:
            facts.append(f"caution: {line}")
        for line in tactical.matchup_observations[:6]:
            facts.append(f"matchup: {line}")
        for line in tactical.deck_observations[:8]:
            facts.append(f"deck: {line}")
        for line in tactical.recommendations[:6]:
            facts.append(f"tip: {line}")
        facts.append(f"analysis_confidence: {round(float(tactical.confidence), 3)}")
        lim = tactical.limitations
        for item in lim.what_we_know[:8]:
            facts.append(f"know: {item}")
        for item in lim.what_we_dont_know[:8]:
            facts.append(f"unknown: {item}")

    if battle_timeline is not None and battle_timeline.summary is not None:
        s = battle_timeline.summary
        facts.append(
            "timeline_summary: "
            f"confirmed_events={s.confirmed_event_count}, "
            f"confirmed_cards={s.confirmed_card_count}, "
            f"known_duration={s.known_duration}, "
            f"unknown_gaps={s.unknown_intervals_count}"
        )
        facts.append(f"replay_duration_seconds: {round(float(battle_timeline.duration_seconds), 3)}")

    allowed_timestamps: list[float] = []
    event_lines: list[str] = []
    for ev in conf_events:
        ts = round(float(ev.timestamp_seconds), 3)
        if ts not in allowed_timestamps:
            allowed_timestamps.append(ts)
        card_bit = ""
        if ev.card_id:
            # Prefer confirmed card name for this id
            match = next((c.card_name for c in cards if c.card_id == ev.card_id), None)
            if match:
                card_bit = f" card={match}"
                if match not in allowed_names:
                    allowed_names.append(match)
        event_lines.append(
            f"confirmed_event t={ts} type={ev.event_type} "
            f"player={ev.player} conf={round(float(ev.confidence), 3)}{card_bit}"
        )
    facts.extend(event_lines[:20])

    candidate_notes: list[str] = []
    for ev in events:
        if ev.event_type != EVENT_CARD_PLAY_CANDIDATE:
            continue
        ts = round(float(ev.timestamp_seconds), 3)
        match = next((c.card_name for c in cards if c.card_id == ev.card_id), None)
        label = match or "unknown_card"
        if match and match not in allowed_names:
            # candidates may reference confirmed card names only
            pass
        if match:
            candidate_notes.append(
                f"candidate_only t={ts} type=card_play_candidate card={label} "
                f"(not confirmed play — say похоже/возможно)"
            )
        else:
            candidate_notes.append(
                f"candidate_only t={ts} type=card_play_candidate "
                "(card not in confirmed_cards — do not name a card)"
            )
    facts.extend(candidate_notes[:8])

    for card in cards:
        facts.append(
            f"confirmed_card name={card.card_name} "
            f"first_seen={round(float(card.first_seen), 3)} "
            f"last_seen={round(float(card.last_seen), 3)} "
            f"conf={round(float(card.confidence), 3)}"
        )
        ts_a = round(float(card.first_seen), 3)
        ts_b = round(float(card.last_seen), 3)
        if ts_a not in allowed_timestamps:
            allowed_timestamps.append(ts_a)
        if ts_b not in allowed_timestamps:
            allowed_timestamps.append(ts_b)

    for item in limitations:
        facts.append(f"pipeline_limitation: {item}")

    if not facts:
        facts.append("insufficient_replay_data: no confirmed cards or events")

    # RU labels for validator allowlist
    allowed_ids = list(allowed_names)
    for name in list(allowed_names):
        ru = card_name_ru(name)
        if ru and ru not in allowed_ids:
            allowed_ids.append(ru)

    return {
        "tool": REPLAY_COACH_TOOL,
        "ok": True,
        "data": {
            "facts": facts,
            "allowed_card_ids": allowed_ids,
            "allowed_timestamps": sorted(allowed_timestamps),
            "candidate_notes": candidate_notes,
            "has_video_payload": False,
            "has_raw_frames": False,
        },
    }


def format_facts_block(envelope: dict[str, Any]) -> str:
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    facts = [str(x) for x in (data.get("facts") or []) if str(x).strip()]
    cards = [str(x) for x in (data.get("allowed_card_ids") or []) if str(x).strip()]
    stamps = data.get("allowed_timestamps") or []
    lines = ["FACTS:"]
    lines.extend(f"- {f}" for f in facts[:40])
    lines.append("CARDS (only these names allowed):")
    if cards:
        lines.extend(f"- {c}" for c in cards[:24])
    else:
        lines.append("- (none confirmed)")
    lines.append("EVENTS timestamps (only these seconds allowed as exact times):")
    if stamps:
        lines.extend(f"- {t}" for t in stamps[:30])
    else:
        lines.append("- (none)")
    lines.append("LIMITATIONS: treat unknown/* lines as unavailable facts.")
    return "\n".join(lines)


def render_replay_coach_fallback(envelope: dict[str, Any]) -> str:
    """Deterministic coach text when Qwen fails or violates facts."""
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    facts = [str(x) for x in (data.get("facts") or [])]
    cards = [str(x) for x in (data.get("allowed_card_ids") or []) if str(x).strip()]
    # Prefer EN names (skip RU duplicates roughly)
    en_cards = [c for c in cards if re.search(r"[A-Za-z]", c)][:6]

    positives = [f[10:] for f in facts if f.startswith("positive: ")][:2]
    cautions = [f[9:] for f in facts if f.startswith("caution: ")][:2]
    tips = [f[5:] for f in facts if f.startswith("tip: ")][:2]
    summary = next((f[9:] for f in facts if f.startswith("summary: ")), "")

    parts: list[str] = []
    if en_cards:
        parts.append(
            "По подтверждённым данным реплея вижу карты: "
            + ", ".join(en_cards)
            + "."
        )
    elif summary:
        parts.append(summary.split(".")[0].strip() + ".")
    else:
        parts.append("По этому реплею пока мало подтверждённых фактов для уверенного разбора.")

    if positives:
        parts.append("Что видно уверенно: " + positives[0])
    if cautions:
        parts.append(cautions[0])
    else:
        parts.append(
            "Этот момент я пока не могу подтвердить по видео — "
            "тайминги plays, эликсир и урон не извлечены."
        )
    if tips:
        parts.append("Дальше: " + tips[0])
    else:
        parts.append(
            "Пришли уточнение ключевого момента текстом — разберём на том, что уже подтверждено."
        )
    return " ".join(p.strip() for p in parts if p.strip())


def validate_replay_coach_response(text: str, envelope: dict[str, Any] | None) -> tuple[bool, str]:
    raw = (text or "").strip()
    if not raw:
        return False, "empty_response"
    if not isinstance(envelope, dict) or not envelope:
        return False, "empty_envelope"
    if envelope.get("tool") != REPLAY_COACH_TOOL:
        return False, "wrong_tool"
    if _RAW_MEDIA_RE.search(raw):
        return False, "raw_media_mention"
    if _INVENTED_CLAIM_RE.search(raw):
        return False, "invented_claim"

    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    allowed = [
        str(x)
        for x in (data.get("allowed_card_ids") or [])
        if isinstance(x, str) and x.strip()
    ]
    ungrounded = find_ungrounded_cards(raw, allowed)
    if ungrounded:
        return False, f"unknown_card:{ungrounded[0]}"

    # Exact second mentions like «на 32» / «32-й» / «32.5» must be allowlisted
    allowed_ts = {
        round(float(t), 3)
        for t in (data.get("allowed_timestamps") or [])
        if _is_number(t)
    }
    allowed_ints = {int(round(t)) for t in allowed_ts}
    for match in re.finditer(
        r"(?:на\s+)?(\d{1,3})(?:[.,](\d+))?\s*(?:-?й|-?ой|-?ей)?\s*(?:сек|секунд)",
        raw,
        re.IGNORECASE,
    ):
        whole = float(f"{match.group(1)}.{match.group(2)}") if match.group(2) else float(match.group(1))
        whole_r = round(whole, 3)
        as_int = int(match.group(1))
        if whole_r not in allowed_ts and as_int not in allowed_ints:
            return False, f"unknown_timestamp:{whole_r}"

    return True, "ok"


def apply_replay_coach_gate(text: str, envelope: dict[str, Any] | None) -> str:
    ok, _reason = validate_replay_coach_response(text, envelope)
    if ok:
        return (text or "").strip()
    return render_replay_coach_fallback(envelope or {"tool": REPLAY_COACH_TOOL, "data": {}})


class ReplayCoachPromptBuilder(PromptBuilder):
    def __init__(self, envelope: dict[str, Any]) -> None:
        super().__init__(system_prompt=REPLAY_COACH_SYSTEM_PROMPT, constraints="")
        self._envelope = envelope

    def build(
        self,
        ctx: Any = None,
        *,
        include_tool_results: bool = True,
        planner_recommendation: Any | None = None,
    ) -> list[ChatMessage]:
        del include_tool_results, planner_recommendation
        user_msg = "Сформулируй короткий тренерский разбор реплея по FACTS."
        if ctx is not None and getattr(ctx, "raw_message", None):
            user_msg = str(ctx.raw_message).strip() or user_msg
        return [
            ChatMessage(role=MessageRole.SYSTEM, content=REPLAY_COACH_SYSTEM_PROMPT),
            ChatMessage(role=MessageRole.SYSTEM, content=format_facts_block(self._envelope)),
            ChatMessage(role=MessageRole.USER, content=user_msg),
        ]


class ReplayCoachRenderer:
    """Structured analysis → natural coach reply via local Qwen (fallback-safe)."""

    def __init__(self, *, provider: Any | None = None) -> None:
        self._provider = provider

    def render_template(
        self,
        *,
        tactical: ReplayTacticalAnalysis | None,
        battle_timeline: ReplayBattleTimeline | None,
        confirmed_cards: Sequence[ConfirmedCardFact] = (),
        confirmed_events: Sequence[ReplayEvent] = (),
        events: Sequence[ReplayEvent] = (),
        limitations: Sequence[str] = (),
    ) -> ReplayCoachResult:
        envelope = build_replay_coach_envelope(
            tactical=tactical,
            battle_timeline=battle_timeline,
            confirmed_cards=confirmed_cards,
            confirmed_events=confirmed_events,
            events=events,
            limitations=limitations,
        )
        return ReplayCoachResult(
            text=render_replay_coach_fallback(envelope),
            source="template",
            envelope=envelope,
        )

    async def arender(
        self,
        *,
        tactical: ReplayTacticalAnalysis | None,
        battle_timeline: ReplayBattleTimeline | None,
        confirmed_cards: Sequence[ConfirmedCardFact] = (),
        confirmed_events: Sequence[ReplayEvent] = (),
        events: Sequence[ReplayEvent] = (),
        limitations: Sequence[str] = (),
        user_message: str | None = None,
    ) -> ReplayCoachResult:
        envelope = build_replay_coach_envelope(
            tactical=tactical,
            battle_timeline=battle_timeline,
            confirmed_cards=confirmed_cards,
            confirmed_events=confirmed_events,
            events=events,
            limitations=limitations,
        )
        # Never send media
        assert envelope["data"].get("has_video_payload") is False
        assert envelope["data"].get("has_raw_frames") is False

        try:
            text = await self._call_qwen(envelope, user_message=user_message)
            gated = apply_replay_coach_gate(text, envelope)
            source = "qwen" if gated == (text or "").strip() else "template"
            if source == "template":
                gated = render_replay_coach_fallback(envelope)
            return ReplayCoachResult(text=gated, source=source, envelope=envelope)
        except Exception:
            logger.exception("replay coach Qwen failed — using template")
            return ReplayCoachResult(
                text=render_replay_coach_fallback(envelope),
                source="template",
                envelope=envelope,
            )

    async def _call_qwen(
        self,
        envelope: dict[str, Any],
        *,
        user_message: str | None,
    ) -> str:
        from types import SimpleNamespace

        from bot.services.ghosteek_ai.generator.llm_generator import OllamaResponseGenerator

        provider = self._provider
        if provider is None:
            from bot.services.ghosteek_ai.llm.provider import (
                OllamaProvider,
                ollama_config_from_settings,
            )

            provider = OllamaProvider(ollama_config_from_settings())

        builder = ReplayCoachPromptBuilder(envelope)
        gen = OllamaResponseGenerator(provider=provider, prompt_builder=builder)
        ctx = SimpleNamespace(raw_message=user_message or "Разбери этот реплей.")
        result = await gen.agenerate(ctx, tools=None, **replay_coach_generate_kwargs())
        if not isinstance(result, str):
            raise ValueError("replay coach expected text response")
        return result.strip()


def _is_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False

"""Replay Analysis grounded trainer renderer (Qwen3.5:9b).

Architecture:
  Replay video → validation → sampling → HUD → events → ReplayFacts
  → Qwen3.5:9b → Safety/fact-lock → ReplayAnalysisCard

Qwen is NOT source of truth. No raw video/frames. Compact ReplayFacts only.
On any fact-lock violation → deterministic fallback template.
Does not weaken the general CR local-renderer fact-lock.
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
    EVENT_ARENA_VISIBLE,
    EVENT_BATTLE_END,
    EVENT_BATTLE_START,
    EVENT_BATTLE_UI_VISIBLE,
    EVENT_CARD_BAR_VISIBLE,
    EVENT_CARD_IDENTITY_VISIBLE,
    EVENT_CARD_PLAY_CANDIDATE,
    EVENT_CARD_PLAY_CONFIRMED,
    EVENT_ELIXIR_HUD_VISIBLE,
    EVENT_OVERTIME_VISIBLE,
    EVENT_RESULT_VISIBLE,
    ReplayEvent,
)
from bot.services.ghosteek_ai.replay.tactical_analysis import ReplayTacticalAnalysis
from bot.services.ghosteek_ai.safety.local_renderer_validator import (
    find_ungrounded_cards,
)

logger = logging.getLogger(__name__)

REPLAY_COACH_TOOL = "replay_coach"
REPLAY_RENDERER_TOOL = REPLAY_COACH_TOOL

REPLAY_RENDERER_SYSTEM_PROMPT = """Ты Ghosteek AI — дружелюбный тренер Clash Royale.
Ты объясняешь результат разбора реплея человеку, коротко и естественно.
Ты не являешься источником фактов игры.
Источником фактов являются только переданные ReplayFacts.

Правила:
1. Никогда не утверждай, что игрок сыграл определённую карту, если её нет в confirmed_events / confirmed plays.
2. Никогда не называй карту по догадке.
3. Никогда не придумывай timestamp.
4. Никогда не придумывай количество эликсира.
5. Никогда не утверждай damage/winner, если этого нет в facts.
6. Candidate event нельзя выдавать как факт. Для кандидатов только «похоже» / «возможно» / «по доступным кадрам».
7. Если данных недостаточно — прямо скажи это.
8. Не повторяй технические названия event_type пользователю.
9. Переводи технические ограничения в нормальную человеческую речь.
10. Ответ должен быть живым, но фактически ограниченным.
11. Не используй шаблон «Grounded replay analysis...» в пользовательском ответе.
12. Не проси пользователя ждать подтверждённых карт, если анализ уже завершён.
13. Если данных мало, дай полезный вывод о качестве доступного анализа.
14. Не делай вид, что просмотрел видео напрямую — тебе передали только structured facts.

Формат ответа:
Краткий вывод тренера: 1–3 предложения.
Что заметил: 2–5 конкретных подтверждённых наблюдений (если есть).
Что улучшить: только если достаточно фактов.
Если данных мало: коротко объясни, чего именно не удалось подтвердить.

Стиль: русский, естественный, дружелюбный, как хороший игровой тренер;
без канцелярита; без «уважаемый пользователь»; без чрезмерных предупреждений;
без повторов; разные формулировки допустимы, смысл grounded.

Не упоминай raw video, ffmpeg, frames, Qwen, Ollama, JSON, debug objects.
"""

# Backward-compatible alias used by Stage 7 tests / imports
REPLAY_COACH_SYSTEM_PROMPT = REPLAY_RENDERER_SYSTEM_PROMPT

REPLAY_COACH_TEMPERATURE = 0.38
REPLAY_COACH_NUM_PREDICT = 320
REPLAY_COACH_NUM_CTX = 4096
REPLAY_COACH_THINK = False

_HUMAN_EVENT_LABELS = {
    EVENT_BATTLE_START: "начало боя",
    EVENT_BATTLE_END: "конец боя",
    EVENT_RESULT_VISIBLE: "экран результата",
    EVENT_CARD_IDENTITY_VISIBLE: "карта видна",
    EVENT_CARD_PLAY_CONFIRMED: "подтверждённый розыгрыш карты",
    EVENT_CARD_PLAY_CANDIDATE: "возможный розыгрыш (не подтверждён)",
    EVENT_CARD_BAR_VISIBLE: "видна панель карт",
    EVENT_ARENA_VISIBLE: "видна арена",
    EVENT_ELIXIR_HUD_VISIBLE: "виден эликсир-HUD",
    EVENT_BATTLE_UI_VISIBLE: "виден боевой интерфейс",
    EVENT_OVERTIME_VISIBLE: "овертайм",
}

_INVENTED_CLAIM_RE = re.compile(
    r"("
    r"плохо\s+потратил\s+эликсир|"
    r"слишком\s+рано\s+поставил|"
    r"проиграл\s+из-за\s+плохой\s+защиты|"
    r"tower\s+hp|"
    r"\b\d+\s*hp\b|"
    r"нанес\s+\d+\s*урон|"
    r"потратил\s+\d+\s*эликсир|"
    r"эликсир\s*[:=]?\s*\d+"
    r")",
    re.IGNORECASE,
)

_DAMAGE_CLAIM_RE = re.compile(
    r"("
    r"\b\d+\s*(?:урона|урон|damage)\b|"
    r"(?:нанес|нанесла|нанесли|снял|сняла)\s+\d+|"
    r"башн[аеиую]\s+(?:потеряла|получила)\s+\d+|"
    r"tower\s+(?:took|lost)\s+\d+"
    r")",
    re.IGNORECASE,
)

_WINNER_CLAIM_RE = re.compile(
    r"("
    r"ты\s+выиграл|"
    r"ты\s+проиграл|"
    r"победа\s+за\s+тобой|"
    r"противник\s+победил|"
    r"opponent\s+won|"
    r"you\s+won|"
    r"you\s+lost|"
    r"winner\s*(?:is|=)|"
    r"итог\s*[:=]\s*(?:победа|поражение)"
    r")",
    re.IGNORECASE,
)

_ASSERTED_PLAY_RE = re.compile(
    r"("
    r"ты\s+(?:сыграл|поставил|разыграл|кинул)|"
    r"игрок\s+(?:сыграл|поставил|разыграл)|"
    r"подтвержд[её]нн(?:ый|о)\s+розыгрыш|"
    r"точно\s+сыграл|"
    r"played\s+(?:the\s+)?card|"
    r"deployed\s+"
    r")",
    re.IGNORECASE,
)

_CANDIDATE_AS_FACT_RE = re.compile(
    r"("
    r"точно\s+(?:сыграл|поставил)|"
    r"подтверждено[,:]?\s+ты\s+сыграл|"
    r"факт[,:]?\s+ты\s+сыграл|"
    r"однозначно\s+сыграл"
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
    r"\bqwen\b|"
    r"я\s+просмотрел\s+видео|"
    r"я\s+посмотрел\s+видео|"
    r"по\s+кадрам\s+файла|"
    r"watched\s+the\s+video"
    r")",
    re.IGNORECASE,
)

_BANNED_UX_RE = re.compile(
    r"("
    r"grounded\s+replay\s+analysis|"
    r"дожд(?:ись|итесь)\s+подтвержд|"
    r"подожд(?:и|ите)\s+подтвержд|"
    r"wait\s+for\s+confirmed|"
    r"event_type|"
    r"card_play_candidate|"
    r"card_play_confirmed|"
    r"card_identity_visible|"
    r"battle_start\b|"
    r"confirmed_events|"
    r"candidate_events"
    r")",
    re.IGNORECASE,
)

_TECHNICAL_PLAYER_LINE_RE = re.compile(
    r"("
    r"grounded\s+replay|"
    r"confirmed\s+event|"
    r"card\s+interval|"
    r"unknown\s+gaps|"
    r"confidence\s*[≥>=]|"
    r"card_play|"
    r"card-level|"
    r"database[- ]counter|"
    r"timeline\s+remain|"
    r"\bplays\b|"
    r"\bffmpeg\b|"
    r"\bqwen\b|"
    r"\bollama\b"
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


def _card_label(card_id: str | None, cards: Sequence[ConfirmedCardFact]) -> str | None:
    if not card_id:
        return None
    match = next((c.card_name for c in cards if c.card_id == card_id), None)
    return str(match).strip() if match else None


def _event_card_label(
    ev: ReplayEvent,
    cards: Sequence[ConfirmedCardFact],
) -> str | None:
    """Resolve card name from confirmed facts, event details, or card_id."""
    label = _card_label(ev.card_id, cards)
    if label:
        return label
    details = ev.details if isinstance(ev.details, dict) else {}
    raw = details.get("card_name")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if not ev.card_id:
        return None
    try:
        from bot.services.ghosteek_ai.replay.card_catalog import CardCatalog

        resolved = CardCatalog.from_loaded_registry().resolve(card_id=ev.card_id)
        if resolved is not None and resolved.card_name:
            return str(resolved.card_name).strip()
    except Exception:
        return None
    return None


def _human_event_label(event_type: str) -> str:
    return _HUMAN_EVENT_LABELS.get(event_type, "наблюдение")


def _humanize_limitation(item: str) -> str:
    mapping = {
        "card_play_events_not_detected": "розыгрыши карт по кадрам не зафиксированы",
        "card_play_events_not_confirmed": "точные розыгрыши карт не подтверждены",
        "exact_card_timing_unavailable": "точные тайминги карт недоступны",
        "elixir_values_not_extracted": "числовые значения эликсира не извлечены",
        "damage_events_not_detected": "урон по башням/войскам не зафиксирован",
        "deck_identity_not_confirmed": "полная колода не подтверждена",
        "Exact card-play events are not confirmed for most sampled frames.": (
            "точные розыгрыши карт не подтверждены для большинства кадров"
        ),
        "Specific card identities are not confirmed from sampled frames.": (
            "конкретные карты по кадрам не подтверждены"
        ),
        "Grounded gameplay events require visual evidence from sampled frames.": (
            "нужны визуальные подтверждения по кадрам"
        ),
    }
    return mapping.get(item, item)


def build_replay_coach_envelope(
    *,
    tactical: ReplayTacticalAnalysis | None,
    battle_timeline: ReplayBattleTimeline | None,
    confirmed_cards: Sequence[ConfirmedCardFact] = (),
    confirmed_events: Sequence[ReplayEvent] = (),
    events: Sequence[ReplayEvent] = (),
    candidate_events: Sequence[ReplayEvent] = (),
    limitations: Sequence[str] = (),
    facts: Sequence[str] = (),
) -> dict[str, Any]:
    """Compact ReplayFacts envelope for Qwen. Never includes video/frames/debug dumps."""
    # Vision often returns 0.75–0.89; keep those mentionable (plays still need confirmed plays).
    cards = [c for c in confirmed_cards if float(c.confidence) >= 0.75]
    conf_events = list(confirmed_events)
    if not conf_events and battle_timeline is not None:
        conf_events = list(battle_timeline.confirmed_events)

    candidates = [
        e for e in candidate_events if e.event_type == EVENT_CARD_PLAY_CANDIDATE
    ]
    if not candidates:
        candidates = [e for e in events if e.event_type == EVENT_CARD_PLAY_CANDIDATE]

    allowed_names: list[str] = []
    for card in cards:
        name = str(card.card_name or "").strip()
        if name and name not in allowed_names:
            allowed_names.append(name)

    confirmed_play_names: list[str] = []
    for ev in conf_events:
        if ev.event_type != EVENT_CARD_PLAY_CONFIRMED:
            continue
        label = _event_card_label(ev, cards)
        if label and label not in confirmed_play_names:
            confirmed_play_names.append(label)

    compact_facts: list[str] = []
    for line in facts:
        text = str(line).strip()
        if text and text not in compact_facts:
            compact_facts.append(text)

    if tactical is not None:
        if tactical.summary:
            compact_facts.append(f"summary: {tactical.summary}")
        for line in tactical.positive_actions[:6]:
            compact_facts.append(f"positive: {line}")
        for line in tactical.possible_mistakes[:4]:
            compact_facts.append(f"caution: {line}")
        for line in tactical.matchup_observations[:6]:
            compact_facts.append(f"matchup: {line}")
        for line in tactical.deck_observations[:8]:
            compact_facts.append(f"deck: {line}")
        for line in tactical.recommendations[:6]:
            compact_facts.append(f"tip: {line}")
        compact_facts.append(f"analysis_confidence: {round(float(tactical.confidence), 3)}")
        lim = tactical.limitations
        for item in lim.what_we_know[:8]:
            compact_facts.append(f"know: {item}")
        for item in lim.what_we_dont_know[:8]:
            compact_facts.append(f"unknown: {item}")

    if battle_timeline is not None and battle_timeline.summary is not None:
        s = battle_timeline.summary
        compact_facts.append(
            "timeline_summary: "
            f"confirmed_events={s.confirmed_event_count}, "
            f"confirmed_cards={s.confirmed_card_count}, "
            f"known_duration={s.known_duration}, "
            f"unknown_gaps={s.unknown_intervals_count}"
        )
        compact_facts.append(
            f"replay_duration_seconds: {round(float(battle_timeline.duration_seconds), 3)}"
        )

    allowed_timestamps: list[float] = []
    event_lines: list[str] = []
    for ev in conf_events:
        ts = round(float(ev.timestamp_seconds), 3)
        if ts not in allowed_timestamps:
            allowed_timestamps.append(ts)
        label = _event_card_label(ev, cards)
        if label and label not in allowed_names:
            allowed_names.append(label)
        card_bit = f" card={label}" if label else ""
        event_lines.append(
            f"confirmed_event t={ts} observation={_human_event_label(ev.event_type)} "
            f"player={ev.player} conf={round(float(ev.confidence), 3)}{card_bit}"
        )
    compact_facts.extend(event_lines[:20])

    # Vision/heuristic events that carry a card but are not in conf_events
    # (e.g. troop_visible below play-confirm threshold) must still be mentionable.
    for ev in events:
        label = _event_card_label(ev, cards)
        if label and label not in allowed_names:
            allowed_names.append(label)
        ts = round(float(ev.timestamp_seconds), 3)
        if ts not in allowed_timestamps:
            allowed_timestamps.append(ts)

    candidate_notes: list[str] = []
    for ev in candidates:
        ts = round(float(ev.timestamp_seconds), 3)
        label = _event_card_label(ev, cards)
        if label and label not in allowed_names:
            allowed_names.append(label)
        if label:
            candidate_notes.append(
                f"candidate_only t={ts} observation=возможный розыгрыш "
                f"card={label} (не подтверждён — говори похоже/возможно)"
            )
        else:
            candidate_notes.append(
                "candidate_only observation=возможный розыгрыш "
                "(карта не в confirmed_cards — не называй карту)"
            )
    compact_facts.extend(candidate_notes[:8])

    for card in cards:
        compact_facts.append(
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

    if battle_timeline is not None:
        duration_ts = round(float(battle_timeline.duration_seconds), 3)
        if duration_ts > 0 and duration_ts not in allowed_timestamps:
            allowed_timestamps.append(duration_ts)
        duration_int = int(round(duration_ts))
        if duration_int > 0 and float(duration_int) not in allowed_timestamps:
            allowed_timestamps.append(float(duration_int))

    for item in limitations:
        human = _humanize_limitation(str(item))
        if human:
            compact_facts.append(f"pipeline_limitation: {human}")

    has_damage = any(
        bool(
            re.search(
                r"(?:damage_event|dealt\s+\d+\s*damage|урон\s*[:=]\s*\d+)",
                f,
                re.IGNORECASE,
            )
        )
        for f in compact_facts
    )
    # Only treat explicit winner facts as available — result screen alone is not enough
    joined = " ".join(compact_facts).lower()
    has_winner = any(
        token in joined
        for token in ("winner=", "winner:", "итог победа", "итог поражение", "confirmed winner")
    )

    if not compact_facts:
        compact_facts.append("insufficient_replay_data: no confirmed cards or events")

    allowed_ids = list(allowed_names)
    for name in list(allowed_names):
        ru = card_name_ru(name)
        if ru and ru not in allowed_ids:
            allowed_ids.append(ru)

    return {
        "tool": REPLAY_COACH_TOOL,
        "ok": True,
        "data": {
            "facts": compact_facts,
            "allowed_card_ids": allowed_ids,
            "allowed_timestamps": sorted(allowed_timestamps),
            "candidate_notes": candidate_notes,
            "confirmed_play_card_names": confirmed_play_names,
            "has_damage_facts": has_damage,
            "has_winner_facts": has_winner,
            "has_video_payload": False,
            "has_raw_frames": False,
            "has_full_timeline": False,
            "has_debug_objects": False,
        },
    }


def format_facts_block(envelope: dict[str, Any]) -> str:
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    facts = [str(x) for x in (data.get("facts") or []) if str(x).strip()]
    cards = [str(x) for x in (data.get("allowed_card_ids") or []) if str(x).strip()]
    stamps = data.get("allowed_timestamps") or []
    plays = [str(x) for x in (data.get("confirmed_play_card_names") or []) if str(x).strip()]
    lines = [
        "ReplayFacts (compact — единственный источник фактов):",
        "FACTS:",
    ]
    lines.extend(f"- {f}" for f in facts[:40])
    lines.append("CARDS (only these names allowed):")
    if cards:
        lines.extend(f"- {c}" for c in cards[:24])
    else:
        lines.append("- (none confirmed)")
    lines.append("CONFIRMED PLAYS (only these may be stated as played):")
    if plays:
        lines.extend(f"- {p}" for p in plays[:16])
    else:
        lines.append("- (none — do not claim any card was played)")
    lines.append("EVENTS timestamps (only these seconds allowed as exact times):")
    if stamps:
        lines.extend(f"- {t}" for t in stamps[:30])
    else:
        lines.append("- (none)")
    lines.append("LIMITATIONS: treat unknown/* and pipeline_limitation lines as unavailable facts.")
    lines.append("Candidates are NOT facts.")
    return "\n".join(lines)


def _player_safe_line(text: str) -> str:
    raw = (text or "").strip()
    if not raw or _TECHNICAL_PLAYER_LINE_RE.search(raw):
        return ""
    return raw


def render_replay_coach_fallback(envelope: dict[str, Any]) -> str:
    """Deterministic grounded coach text when Qwen fails or violates facts."""
    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
    facts = [str(x) for x in (data.get("facts") or [])]
    cards = [str(x) for x in (data.get("allowed_card_ids") or []) if str(x).strip()]
    en_cards = [c for c in cards if re.search(r"[A-Za-z]", c)][:6]
    plays = [str(x) for x in (data.get("confirmed_play_card_names") or []) if str(x).strip()]

    positives = [_player_safe_line(f[10:]) for f in facts if f.startswith("positive: ")]
    positives = [p for p in positives if p][:3]
    cautions = [_player_safe_line(f[9:]) for f in facts if f.startswith("caution: ")]
    cautions = [c for c in cautions if c][:2]
    tips = [_player_safe_line(f[5:]) for f in facts if f.startswith("tip: ")]
    tips = [t for t in tips if t][:2]
    knows = [_player_safe_line(f[6:]) for f in facts if f.startswith("know: ")]
    knows = [k for k in knows if k][:3]

    insufficient = (
        "Реплей распознался, но по этому видео я пока не могу надёжно определить "
        "сыгранные карты и конкретные моменты. Поэтому не буду придумывать разбор из воздуха.\n\n"
        "Попробуй отправить запись в более высоком качестве или с полностью видимой "
        "ареной и панелью карт."
    )

    if not en_cards and not plays and not positives and not knows:
        return insufficient

    parts: list[str] = []
    if en_cards and plays:
        parts.append(
            "Я нашёл несколько моментов, которые можно разобрать уверенно. "
            f"Вот что бросается в глаза: вижу {', '.join(en_cards[:3])}, "
            f"уверенный розыгрыш — {', '.join(plays[:2])}."
        )
    elif en_cards:
        parts.append(
            "Я нашёл несколько моментов, которые можно разобрать уверенно. "
            f"Вот что бросается в глаза: уверенно вижу карты {', '.join(en_cards[:4])}."
        )
    else:
        parts.append(
            "Я нашёл несколько моментов, которые можно разобрать уверенно. "
            "Вот что бросается в глаза."
        )

    noticed: list[str] = []
    noticed.extend(positives[:2])
    noticed.extend(knows[:2])
    if noticed:
        parts.append("Что заметил: " + "; ".join(noticed[:4]) + ".")

    if tips and (en_cards or plays):
        parts.append("Что улучшить: " + tips[0])
    elif cautions and (en_cards or plays):
        parts.append(cautions[0])
    else:
        parts.append(
            "Чего не удалось подтвердить: точные розыгрыши, числовой эликсир и урон "
            "по этой записи пока не извлекаются — опираюсь только на то, что видно уверенно."
        )

    text = " ".join(p.strip() for p in parts if p.strip())
    text = re.sub(r"Grounded\s+replay\s+analysis\s*:[^.!?\n]*[.!]?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"Дождитесь\s+подтверждённых\s+карт[^.!?\n]*[.!]?\s*", "", text, flags=re.IGNORECASE)
    return text.strip() or insufficient


def validate_replay_coach_response(text: str, envelope: dict[str, Any] | None) -> tuple[bool, str]:
    """Replay renderer fact-lock. Does not weaken the general CR local-renderer fact-lock."""
    raw = (text or "").strip()
    if not raw:
        return False, "empty_response"
    if not isinstance(envelope, dict) or not envelope:
        return False, "empty_envelope"
    if envelope.get("tool") != REPLAY_COACH_TOOL:
        return False, "wrong_tool"
    if _RAW_MEDIA_RE.search(raw):
        return False, "raw_media_mention"
    if _BANNED_UX_RE.search(raw):
        return False, "banned_ux_or_tech_leak"
    if _INVENTED_CLAIM_RE.search(raw):
        return False, "invented_claim"

    data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}

    if _DAMAGE_CLAIM_RE.search(raw) and not data.get("has_damage_facts"):
        return False, "unsupported_damage"
    if _WINNER_CLAIM_RE.search(raw) and not data.get("has_winner_facts"):
        return False, "unsupported_winner"

    allowed = [
        str(x)
        for x in (data.get("allowed_card_ids") or [])
        if isinstance(x, str) and x.strip()
    ]
    ungrounded = find_ungrounded_cards(raw, allowed)
    if ungrounded:
        return False, f"unknown_card:{ungrounded[0]}"

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
        whole = (
            float(f"{match.group(1)}.{match.group(2)}")
            if match.group(2)
            else float(match.group(1))
        )
        whole_r = round(whole, 3)
        as_int = int(match.group(1))
        if whole_r not in allowed_ts and as_int not in allowed_ints:
            return False, f"unknown_timestamp:{whole_r}"

    confirmed_plays = {
        str(x).strip().lower()
        for x in (data.get("confirmed_play_card_names") or [])
        if str(x).strip()
    }
    if _CANDIDATE_AS_FACT_RE.search(raw) and not confirmed_plays:
        return False, "candidate_as_confirmed"
    if _ASSERTED_PLAY_RE.search(raw):
        if not confirmed_plays:
            return False, "candidate_as_confirmed"
        for name in allowed:
            if not name or name.lower() in confirmed_plays:
                continue
            surfaces = {name.lower()}
            ru = card_name_ru(name)
            if ru:
                surfaces.add(ru.lower())
            for surface in surfaces:
                if not surface:
                    continue
                if re.search(
                    rf"(?:сыграл|поставил|разыграл|кинул|played|deployed)\s+[^.!?]{{0,40}}{re.escape(surface)}",
                    raw,
                    re.IGNORECASE,
                ) or re.search(
                    rf"{re.escape(surface)}[^.!?]{{0,40}}(?:сыграл|поставил|разыграл|played|deployed)",
                    raw,
                    re.IGNORECASE,
                ):
                    return False, "candidate_as_confirmed"

    return True, "ok"


def apply_replay_coach_gate(text: str, envelope: dict[str, Any] | None) -> str:
    ok, reason = validate_replay_coach_response(text, envelope)
    if ok:
        return (text or "").strip()
    logger.info("replay renderer fact-lock rejected: %s", reason)
    return render_replay_coach_fallback(envelope or {"tool": REPLAY_COACH_TOOL, "data": {}})


class ReplayCoachPromptBuilder(PromptBuilder):
    def __init__(self, envelope: dict[str, Any]) -> None:
        super().__init__(system_prompt=REPLAY_RENDERER_SYSTEM_PROMPT, constraints="")
        self._envelope = envelope

    def build(
        self,
        ctx: Any = None,
        *,
        include_tool_results: bool = True,
        planner_recommendation: Any | None = None,
    ) -> list[ChatMessage]:
        del include_tool_results, planner_recommendation
        user_msg = "Сформулируй короткий тренерский разбор реплея только по ReplayFacts."
        if ctx is not None and getattr(ctx, "raw_message", None):
            user_msg = str(ctx.raw_message).strip() or user_msg
        return [
            ChatMessage(role=MessageRole.SYSTEM, content=REPLAY_RENDERER_SYSTEM_PROMPT),
            ChatMessage(role=MessageRole.SYSTEM, content=format_facts_block(self._envelope)),
            ChatMessage(role=MessageRole.USER, content=user_msg),
        ]


class ReplayCoachRenderer:
    """Compact ReplayFacts → natural coach reply via local Qwen3.5:9b (fallback-safe)."""

    def __init__(self, *, provider: Any | None = None) -> None:
        self._provider = provider
        self._owns_provider = provider is None

    async def _ensure_provider(self) -> Any:
        if self._provider is None:
            from bot.services.ghosteek_ai.replay.replay_llm_provider import replay_wording_provider

            self._provider = replay_wording_provider()
            self._owns_provider = True
        return self._provider

    async def close(self) -> None:
        if self._owns_provider and self._provider is not None:
            await self._provider.close()
        if self._owns_provider:
            self._provider = None

    def render_template(
        self,
        *,
        tactical: ReplayTacticalAnalysis | None,
        battle_timeline: ReplayBattleTimeline | None,
        confirmed_cards: Sequence[ConfirmedCardFact] = (),
        confirmed_events: Sequence[ReplayEvent] = (),
        events: Sequence[ReplayEvent] = (),
        candidate_events: Sequence[ReplayEvent] = (),
        limitations: Sequence[str] = (),
        facts: Sequence[str] = (),
    ) -> ReplayCoachResult:
        envelope = build_replay_coach_envelope(
            tactical=tactical,
            battle_timeline=battle_timeline,
            confirmed_cards=confirmed_cards,
            confirmed_events=confirmed_events,
            events=events,
            candidate_events=candidate_events,
            limitations=limitations,
            facts=facts,
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
        candidate_events: Sequence[ReplayEvent] = (),
        limitations: Sequence[str] = (),
        facts: Sequence[str] = (),
        user_message: str | None = None,
    ) -> ReplayCoachResult:
        envelope = build_replay_coach_envelope(
            tactical=tactical,
            battle_timeline=battle_timeline,
            confirmed_cards=confirmed_cards,
            confirmed_events=confirmed_events,
            events=events,
            candidate_events=candidate_events,
            limitations=limitations,
            facts=facts,
        )
        assert envelope["data"].get("has_video_payload") is False
        assert envelope["data"].get("has_raw_frames") is False
        assert envelope["data"].get("has_full_timeline") is False
        assert envelope["data"].get("has_debug_objects") is False

        try:
            try:
                text = await self._call_qwen(envelope, user_message=user_message)
                gated = apply_replay_coach_gate(text, envelope)
                source = "qwen" if gated == (text or "").strip() else "template"
                if source == "template":
                    gated = render_replay_coach_fallback(envelope)
                return ReplayCoachResult(text=gated, source=source, envelope=envelope)
            except Exception:
                logger.exception("replay renderer Qwen failed — using template")
                return ReplayCoachResult(
                    text=render_replay_coach_fallback(envelope),
                    source="template",
                    envelope=envelope,
                )
        finally:
            await self.close()

    async def _call_qwen(
        self,
        envelope: dict[str, Any],
        *,
        user_message: str | None,
    ) -> str:
        from types import SimpleNamespace

        from bot.services.ghosteek_ai.generator.llm_generator import LLMResponseGenerator

        provider = await self._ensure_provider()

        builder = ReplayCoachPromptBuilder(envelope)
        gen = LLMResponseGenerator(provider=provider, prompt_builder=builder)
        ctx = SimpleNamespace(raw_message=user_message or "Разбери этот реплей.")
        result = await gen.agenerate(ctx, tools=None, **replay_coach_generate_kwargs())
        if not isinstance(result, str):
            raise ValueError("replay renderer expected text response")
        return result.strip()


def _is_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False

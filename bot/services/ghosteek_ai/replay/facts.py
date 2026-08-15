"""Build grounded replay facts from detection + timeline. No coaching, no invented plays."""

from __future__ import annotations

from collections.abc import Sequence

from bot.services.ghosteek_ai.replay.battle_timeline import ReplayBattleTimeline
from bot.services.ghosteek_ai.replay.card_recognizer import (
    AmbiguousCardObservation,
    ConfirmedCardFact,
)
from bot.services.ghosteek_ai.replay.events import ReplayEvent
from bot.services.ghosteek_ai.replay.models import (
    DEFAULT_LIMITATIONS,
    OBS_ARENA_VISIBLE,
    OBS_CARD_BAR_VISIBLE,
    OBS_ELIXIR_HUD_VISIBLE,
    OBS_GAMEPLAY_SCREEN,
    STATUS_CR,
    ReplayAnalysisResult,
    ReplayDetection,
    TimelineObservation,
)
from bot.services.ghosteek_ai.replay.tactical_analysis import ReplayTacticalAnalysis


_FORBIDDEN_FACT_TOKENS = (
    "hog",
    "witch",
    "fireball",
    "golem",
    "cannon",
    "miner",
    "knight",
    "goblin",
    "played",
    "damage",
    "tower took",
    "elixir spent",
    "mistake",
    "should have",
    "win condition",
)


class ReplayFactsBuilder:
    """Compact facts envelope for cr_replay only. Explicit limitations always included."""

    def build(
        self,
        detection: ReplayDetection,
        timeline: list[TimelineObservation],
        *,
        duration_seconds: float,
        confirmed_cards: Sequence[ConfirmedCardFact] | None = None,
        ambiguous_cards: Sequence[AmbiguousCardObservation] | None = None,
        events: Sequence[ReplayEvent] | None = None,
        confirmed_events: Sequence[ReplayEvent] | None = None,
        battle_timeline: ReplayBattleTimeline | None = None,
        tactical_analysis: ReplayTacticalAnalysis | None = None,
        coach_reply: str | None = None,
        coach_source: str | None = None,
    ) -> ReplayAnalysisResult | None:
        if detection.status != STATUS_CR:
            return None

        counts = _count_types(timeline)
        frames = max(1, int(detection.frames_analyzed))
        facts = _facts_from_counts(counts, frames)
        facts = [f for f in facts if not _looks_invented(f)]

        cards = [c for c in (confirmed_cards or ()) if float(c.confidence) >= 0.90]
        ambiguous = list(ambiguous_cards or ())
        all_events = list(events or ())
        confirmed_only = list(confirmed_events or ())

        return ReplayAnalysisResult(
            status=detection.status,
            confidence=float(detection.confidence),
            duration_seconds=float(duration_seconds),
            frames_analyzed=int(detection.frames_analyzed),
            timeline=list(timeline),
            facts=facts,
            limitations=list(DEFAULT_LIMITATIONS),
            confirmed_cards=list(cards),
            ambiguous_cards=ambiguous,
            events=all_events,
            confirmed_events=confirmed_only,
            battle_timeline=battle_timeline,
            tactical_analysis=tactical_analysis,
            coach_reply=coach_reply,
            coach_source=coach_source,
        )


def _count_types(timeline: list[TimelineObservation]) -> dict[str, int]:
    counts: dict[str, int] = {}
    seen_frames: dict[str, set[int]] = {}
    for item in timeline:
        bucket = seen_frames.setdefault(item.observation_type, set())
        if item.frame_index in bucket:
            continue
        bucket.add(item.frame_index)
        counts[item.observation_type] = counts.get(item.observation_type, 0) + 1
    return counts


def _facts_from_counts(counts: dict[str, int], frames: int) -> list[str]:
    facts: list[str] = []
    if counts.get(OBS_GAMEPLAY_SCREEN, 0) > 0 or counts.get(OBS_ARENA_VISIBLE, 0) > 0:
        facts.append("Clash Royale gameplay interface detected")
    arena_n = counts.get(OBS_ARENA_VISIBLE, 0)
    if arena_n >= max(2, int(0.4 * frames)):
        facts.append("Arena layout detected consistently")
    elif arena_n > 0:
        facts.append(f"Arena layout detected in {arena_n} of {frames} analyzed frames")
    card_n = counts.get(OBS_CARD_BAR_VISIBLE, 0)
    if card_n > 0:
        facts.append(f"Card bar detected in {card_n} of {frames} analyzed frames")
    elixir_n = counts.get(OBS_ELIXIR_HUD_VISIBLE, 0)
    if elixir_n > 0:
        facts.append(f"Elixir HUD detected in {elixir_n} of {frames} analyzed frames")
    if not facts:
        facts.append("Clash Royale HUD signals detected across sampled frames")
    return facts[:8]


def _looks_invented(text: str) -> bool:
    low = text.lower()
    return any(token in low for token in _FORBIDDEN_FACT_TOKENS)

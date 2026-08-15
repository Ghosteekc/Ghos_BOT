"""Build grounded replay facts from detection + timeline. No coaching, no invented plays."""

from __future__ import annotations

from collections.abc import Sequence

from bot.services.ghosteek_ai.replay.battle_timeline import ReplayBattleTimeline
from bot.services.ghosteek_ai.replay.card_recognizer import (
    AmbiguousCardObservation,
    ConfirmedCardFact,
)
from bot.services.ghosteek_ai.replay.cycle import ReplayCycleState
from bot.services.ghosteek_ai.replay.elixir import ElixirObservation
from bot.services.ghosteek_ai.replay.events import (
    EVENT_CARD_PLAY,
    EVENT_CARD_PLAY_CANDIDATE,
    ReplayEvent,
)
from bot.services.ghosteek_ai.replay.game_state import GameStateObservation
from bot.services.ghosteek_ai.replay.models import (
    DEFAULT_LIMITATIONS,
    DEFAULT_UNAVAILABLE,
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
        game_state_observations: Sequence[GameStateObservation] | None = None,
        elixir_observations: Sequence[ElixirObservation] | None = None,
        cycle: ReplayCycleState | None = None,
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
        game_states = list(game_state_observations or ())
        elixir = list(elixir_observations or ())

        limitations = _limitations_for(all_events, confirmed_only, cards, elixir)
        confirmed_bits, uncertain_bits, unavailable_bits = _availability(
            confirmed_only=confirmed_only,
            all_events=all_events,
            cards=cards,
            ambiguous=ambiguous,
            elixir=elixir,
            cycle=cycle,
        )

        return ReplayAnalysisResult(
            status=detection.status,
            confidence=float(detection.confidence),
            duration_seconds=float(duration_seconds),
            frames_analyzed=int(detection.frames_analyzed),
            timeline=list(timeline),
            facts=facts,
            limitations=limitations,
            confirmed_cards=list(cards),
            ambiguous_cards=ambiguous,
            events=all_events,
            confirmed_events=confirmed_only,
            battle_timeline=battle_timeline,
            tactical_analysis=tactical_analysis,
            coach_reply=coach_reply,
            coach_source=coach_source,
            game_state_observations=game_states,
            elixir_observations=elixir,
            cycle=cycle,
            what_is_confirmed=confirmed_bits,
            what_is_uncertain=uncertain_bits,
            what_is_unavailable=unavailable_bits,
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


def _limitations_for(
    events: Sequence[ReplayEvent],
    confirmed: Sequence[ReplayEvent],
    cards: Sequence[ConfirmedCardFact],
    elixir: Sequence[ElixirObservation],
) -> list[str]:
    out = list(DEFAULT_LIMITATIONS)
    has_candidate = any(e.event_type == EVENT_CARD_PLAY_CANDIDATE for e in events)
    has_play = any(e.event_type == EVENT_CARD_PLAY for e in confirmed)
    if has_play:
        out = [x for x in out if x not in {"card_play_events_not_detected", "card_play_events_not_confirmed"}]
    elif has_candidate:
        out = [x for x in out if x != "card_play_events_not_detected"]
    if cards:
        if len(cards) < 8:
            # Keep deck_identity_not_confirmed — partial card set is not a deck.
            pass
        else:
            out = [x for x in out if x != "deck_identity_not_confirmed"]
    if any(e.value is not None for e in elixir):
        out = [x for x in out if x != "elixir_values_not_extracted"]
    # unique preserve order
    uniq: list[str] = []
    for item in out:
        if item not in uniq:
            uniq.append(item)
    return uniq


def _availability(
    *,
    confirmed_only: Sequence[ReplayEvent],
    all_events: Sequence[ReplayEvent],
    cards: Sequence[ConfirmedCardFact],
    ambiguous: Sequence[AmbiguousCardObservation],
    elixir: Sequence[ElixirObservation],
    cycle: ReplayCycleState | None,
) -> tuple[list[str], list[str], list[str]]:
    confirmed_bits: list[str] = []
    uncertain_bits: list[str] = []
    unavailable_bits = list(DEFAULT_UNAVAILABLE)

    if cards:
        confirmed_bits.append(f"confirmed_cards:{len(cards)}")
    if any(e.event_type == EVENT_CARD_PLAY for e in confirmed_only):
        n = sum(1 for e in confirmed_only if e.event_type == EVENT_CARD_PLAY)
        confirmed_bits.append(f"confirmed_card_play:{n}")
        unavailable_bits = [x for x in unavailable_bits if x != "confirmed card plays"]
    if any(e.event_type == "battle_started" for e in confirmed_only):
        confirmed_bits.append("battle_started")

    if any(e.event_type == EVENT_CARD_PLAY_CANDIDATE for e in all_events):
        uncertain_bits.append("card_play_candidate")
    if ambiguous:
        uncertain_bits.append(f"ambiguous_cards:{len(ambiguous)}")
    if elixir and all(e.value is None for e in elixir):
        uncertain_bits.append("elixir_hud_visible_without_numeric_value")
    if cycle is not None and cycle.limitations:
        uncertain_bits.extend(cycle.limitations[:4])

    if not any(e.value is not None for e in elixir):
        if "exact elixir" not in unavailable_bits:
            unavailable_bits.append("exact elixir")

    return confirmed_bits, uncertain_bits, unavailable_bits

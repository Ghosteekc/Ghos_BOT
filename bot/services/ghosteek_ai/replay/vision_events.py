"""Validate vision observations and integrate into timeline + replay events."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from bot.services.ghosteek_ai.replay.card_catalog import CardCatalog
from bot.services.ghosteek_ai.replay.events import (
    CONF_AUTHORITATIVE,
    EVENT_CARD_PLAY_CANDIDATE,
    EVENT_UNKNOWN,
    EventEvidence,
    ReplayEvent,
    location_to_player,
)
from bot.services.ghosteek_ai.replay.models import (
    SOURCE_VISION,
    TimelineObservation,
    replay_event_confidence_threshold,
)
from bot.services.ghosteek_ai.replay.vision_analyzer import (
    SIDE_OPPONENT,
    SIDE_PLAYER,
    SIDE_UNKNOWN,
    VISION_EVENT_TYPES,
    VisionObservation,
    normalize_event_type,
    normalize_lane,
    normalize_side,
)

_CARD_CONFIDENCE_MIN = 0.75


def parse_raw_observations(
    payload: Mapping[str, Any] | Sequence[Any],
    *,
    frame_index: int,
    timestamp_seconds: float,
    catalog: CardCatalog | None = None,
) -> list[VisionObservation]:
    """Parse model JSON into validated VisionObservation objects."""
    items: list[Any]
    if isinstance(payload, Mapping):
        raw = payload.get("observations")
        if raw is None:
            raw = payload.get("events")
        items = list(raw) if isinstance(raw, list) else []
    elif isinstance(payload, list):
        items = list(payload)
    else:
        return []

    cat = catalog if catalog is not None else CardCatalog()
    out: list[VisionObservation] = []
    for item in items:
        obs = _parse_one(
            item,
            frame_index=frame_index,
            timestamp_seconds=timestamp_seconds,
            catalog=cat,
        )
        if obs is not None:
            out.append(obs)
    return out


def _parse_one(
    item: Any,
    *,
    frame_index: int,
    timestamp_seconds: float,
    catalog: CardCatalog,
) -> VisionObservation | None:
    if not isinstance(item, Mapping):
        return None

    event_type = normalize_event_type(str(item.get("event_type") or item.get("type") or ""))
    if event_type is None:
        return None

    try:
        confidence = float(item.get("confidence", 0.0))
    except (TypeError, ValueError):
        return None

    card_name, card_id = _resolve_card(item, catalog=catalog, confidence=confidence)
    side = normalize_side(item.get("side"))
    lane = normalize_lane(item.get("lane"))

    details = {
        k: v
        for k, v in item.items()
        if k
        not in {
            "event_type",
            "type",
            "confidence",
            "card_name",
            "card_id",
            "side",
            "lane",
            "timestamp_seconds",
        }
    }

    try:
        return VisionObservation(
            timestamp_seconds=float(item.get("timestamp_seconds", timestamp_seconds)),
            frame_index=int(item.get("frame_index", frame_index)),
            event_type=event_type,
            confidence=confidence,
            card_name=card_name,
            card_id=card_id,
            side=side,
            lane=lane,
            details=details,
        )
    except ValueError:
        return None


def _resolve_card(
    item: Mapping[str, Any],
    *,
    catalog: CardCatalog,
    confidence: float,
) -> tuple[str | None, str | None]:
    """Never invent card names — catalog match + confidence required."""
    if confidence < _CARD_CONFIDENCE_MIN:
        return None, None

    raw_name = item.get("card_name")
    raw_id = item.get("card_id")
    name = str(raw_name).strip() if raw_name not in (None, "", "null", "unknown") else None
    card_id = str(raw_id).strip() if raw_id not in (None, "", "null") else None

    if not name and not card_id:
        return None, None

    resolved = catalog.resolve(card_id=card_id, card_name=name)
    if resolved is None:
        return None, None
    if name and catalog.resolve(card_name=name) is None:
        return None, None
    return resolved.card_name, resolved.card_id


def partition_vision_observations(
    observations: Sequence[VisionObservation],
    *,
    threshold: float | None = None,
) -> tuple[list[VisionObservation], list[VisionObservation]]:
    """Return (confirmed, candidate) by configurable confidence threshold."""
    cut = float(threshold) if threshold is not None else replay_event_confidence_threshold()
    confirmed: list[VisionObservation] = []
    candidates: list[VisionObservation] = []
    for obs in observations:
        if float(obs.confidence) >= cut:
            confirmed.append(obs)
        else:
            candidates.append(obs)
    return confirmed, candidates


def observation_to_timeline(obs: VisionObservation) -> TimelineObservation:
    return TimelineObservation(
        timestamp_seconds=float(obs.timestamp_seconds),
        frame_index=int(obs.frame_index),
        observation_type=obs.event_type,
        confidence=float(obs.confidence),
        source=SOURCE_VISION,
    )


def observation_to_replay_event(obs: VisionObservation) -> ReplayEvent:
    player = _side_to_player(obs.side)
    details: dict[str, Any] = dict(obs.details)
    if obs.card_name:
        details["card_name"] = obs.card_name
    if obs.lane:
        details["lane"] = obs.lane
    details["vision_confirmed"] = float(obs.confidence) >= replay_event_confidence_threshold()

    event_type = obs.event_type
    if event_type == "card_visible":
        event_type = "card_identity_visible"
    elif event_type == "card_play_candidate":
        event_type = EVENT_CARD_PLAY_CANDIDATE

    return ReplayEvent(
        timestamp_seconds=float(obs.timestamp_seconds),
        event_type=event_type,
        player=player,
        card_id=obs.card_id,
        confidence=float(obs.confidence),
        source=SOURCE_VISION,
        evidence=EventEvidence(
            frame_indices=(int(obs.frame_index),),
            observation_ids=(f"vision:{obs.frame_index}:{obs.event_type}",),
            timestamps=(float(obs.timestamp_seconds),),
        ),
        details=details,
    )


def merge_timeline_with_vision(
    timeline: Sequence[TimelineObservation],
    observations: Sequence[VisionObservation],
) -> list[TimelineObservation]:
    merged = list(timeline)
    for obs in observations:
        merged.append(observation_to_timeline(obs))
    merged.sort(
        key=lambda item: (item.timestamp_seconds, item.frame_index, item.observation_type)
    )
    return merged


def vision_observations_to_events(
    observations: Sequence[VisionObservation],
) -> list[ReplayEvent]:
    events: list[ReplayEvent] = []
    for obs in observations:
        if float(obs.confidence) < CONF_AUTHORITATIVE:
            continue
        try:
            events.append(observation_to_replay_event(obs))
        except ValueError:
            continue
    return events


def confirmed_facts_from_vision(
    observations: Sequence[VisionObservation],
    *,
    threshold: float | None = None,
) -> list[ConfirmedCardFact]:
    """Promote vision card sightings into ConfirmedCardFact.

    Heuristic frame probe often returns nothing; vision is the real source of
    card names. Without this, coach fact-lock rejects grounded card mentions.
    """
    from bot.services.ghosteek_ai.replay.card_recognizer import ConfirmedCardFact

    # Align with event authority floor (0.75), not the stricter 0.90 play threshold —
    # otherwise troop_visible at 0.86 never becomes a mentionable confirmed card.
    cut = float(threshold) if threshold is not None else float(CONF_AUTHORITATIVE)
    best: dict[str, ConfirmedCardFact] = {}
    for obs in observations:
        if not obs.card_id or not obs.card_name:
            continue
        conf = float(obs.confidence)
        if conf < cut:
            continue
        ts = float(obs.timestamp_seconds)
        prev = best.get(obs.card_id)
        if prev is None:
            best[obs.card_id] = ConfirmedCardFact(
                card_id=obs.card_id,
                card_name=obs.card_name,
                confidence=conf,
                first_seen=ts,
                last_seen=ts,
            )
            continue
        best[obs.card_id] = ConfirmedCardFact(
            card_id=prev.card_id,
            card_name=prev.card_name,
            confidence=max(float(prev.confidence), conf),
            first_seen=min(float(prev.first_seen), ts),
            last_seen=max(float(prev.last_seen), ts),
        )
    return sorted(best.values(), key=lambda c: (-float(c.confidence), c.card_name))


def merge_event_lists(
    heuristic: Sequence[ReplayEvent],
    vision: Sequence[ReplayEvent],
) -> list[ReplayEvent]:
    combined = list(heuristic) + list(vision)
    combined.sort(
        key=lambda e: (e.timestamp_seconds, e.event_type, e.card_id or "", e.player)
    )
    return combined


def repartition_merged_events(
    events: Sequence[ReplayEvent],
    *,
    threshold: float | None = None,
) -> tuple[list[ReplayEvent], list[ReplayEvent], list[ReplayEvent]]:
    """Return (all authoritative, confirmed, candidates) including vision events."""
    cut = float(threshold) if threshold is not None else replay_event_confidence_threshold()
    all_events = [e for e in events if float(e.confidence) >= CONF_AUTHORITATIVE]
    candidates = [e for e in all_events if e.event_type == EVENT_CARD_PLAY_CANDIDATE]
    confirmed = [
        e
        for e in all_events
        if float(e.confidence) >= cut and e.event_type != EVENT_CARD_PLAY_CANDIDATE
    ]
    # High-confidence card_play_candidate from vision stays candidate unless promoted elsewhere
    return all_events, confirmed, candidates


def _side_to_player(side: str) -> str:
    if side == SIDE_PLAYER:
        return location_to_player("player_hand")
    if side == SIDE_OPPONENT:
        return location_to_player("opponent_hand")
    return SIDE_UNKNOWN


def vision_event_label(event_type: str) -> str:
    if event_type in VISION_EVENT_TYPES:
        return event_type.replace("_", " ")
    return EVENT_UNKNOWN

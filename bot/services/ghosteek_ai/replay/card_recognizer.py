"""Replay card recognition adapter. Catalog SoT only; no LLM; no invented plays."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from bot.services.ghosteek_ai.replay.card_catalog import CardCatalog, CatalogCard

CONF_HIGH = 0.90
CONF_MEDIUM = 0.75

LOC_PLAYER_HAND = "player_hand"
LOC_OPPONENT_HAND = "opponent_hand"
LOC_PLAYED_AREA = "played_card_area"
LOC_UNKNOWN = "unknown"

CARD_LOCATIONS = frozenset(
    {LOC_PLAYER_HAND, LOC_OPPONENT_HAND, LOC_PLAYED_AREA, LOC_UNKNOWN}
)

SOURCE_HEURISTIC = "heuristic"
DEFAULT_GROUP_GAP_SECONDS = 1.5
_AMBIGUOUS_GAP = 0.08  # second candidate within this of top → ambiguous


@dataclass(frozen=True)
class CardCandidate:
    card_id: str
    card_name: str
    confidence: float

    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "card_name": self.card_name,
            "confidence": round(float(self.confidence), 4),
        }


@dataclass(frozen=True)
class ConfirmedCardObservation:
    card_id: str
    card_name: str
    confidence: float
    frame_index: int
    timestamp_seconds: float
    location: str
    source: str = SOURCE_HEURISTIC

    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "card_name": self.card_name,
            "confidence": round(float(self.confidence), 4),
            "frame_index": int(self.frame_index),
            "timestamp_seconds": round(float(self.timestamp_seconds), 3),
            "location": self.location,
            "source": self.source,
        }


@dataclass(frozen=True)
class AmbiguousCardObservation:
    candidates: tuple[CardCandidate, ...]
    frame_index: int
    timestamp_seconds: float
    location: str
    source: str = SOURCE_HEURISTIC

    def to_dict(self) -> dict:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "frame_index": int(self.frame_index),
            "timestamp_seconds": round(float(self.timestamp_seconds), 3),
            "location": self.location,
            "source": self.source,
        }


@dataclass(frozen=True)
class ConfirmedCardFact:
    """Authoritative card presence interval (HIGH confidence only). Not a play event."""

    card_id: str
    card_name: str
    confidence: float
    first_seen: float
    last_seen: float

    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "card_name": self.card_name,
            "confidence": round(float(self.confidence), 4),
            "first_seen": round(float(self.first_seen), 3),
            "last_seen": round(float(self.last_seen), 3),
        }


@dataclass(frozen=True)
class RawCardProbeHit:
    """Unvalidated probe output. Must be resolved against CardCatalog."""

    card_id: str | None
    card_name: str | None
    confidence: float
    location: str = LOC_UNKNOWN


class FrameCardProbe(Protocol):
    """Optional visual probe. VisionCardRecognizer can replace this later."""

    def probe(
        self,
        frame_path: str,
        *,
        frame_index: int,
        timestamp_seconds: float,
    ) -> Sequence[RawCardProbeHit]:
        ...


class ReplayCardRecognizer(ABC):
    @abstractmethod
    def recognize_frame(
        self,
        frame_path: str,
        *,
        frame_index: int,
        timestamp_seconds: float,
    ) -> tuple[list[ConfirmedCardObservation], list[AmbiguousCardObservation]]:
        """Return HIGH confirmed sightings and ambiguous groups for one frame."""


class HeuristicCardRecognizer(ReplayCardRecognizer):
    """
    Catalog-validated recognizer.

    Without an injected FrameCardProbe, returns no cards (safe default).
    Never invents card names outside CardCatalog.
    """

    def __init__(
        self,
        catalog: CardCatalog | None = None,
        *,
        probe: FrameCardProbe | None = None,
    ) -> None:
        self._catalog = catalog if catalog is not None else CardCatalog.from_loaded_registry()
        self._probe = probe

    @property
    def catalog(self) -> CardCatalog:
        return self._catalog

    def recognize_frame(
        self,
        frame_path: str,
        *,
        frame_index: int,
        timestamp_seconds: float,
    ) -> tuple[list[ConfirmedCardObservation], list[AmbiguousCardObservation]]:
        if self._probe is None or len(self._catalog) == 0:
            return [], []
        hits = list(
            self._probe.probe(
                frame_path,
                frame_index=frame_index,
                timestamp_seconds=timestamp_seconds,
            )
        )
        return classify_probe_hits(
            hits,
            catalog=self._catalog,
            frame_index=frame_index,
            timestamp_seconds=timestamp_seconds,
            source=SOURCE_HEURISTIC,
        )


class VisionCardRecognizer(ReplayCardRecognizer):
    """Vision-ready swap-in. Not enabled in Stage 5A (no vision model wired)."""

    SOURCE = "vision"

    def __init__(self, catalog: CardCatalog | None = None) -> None:
        self._catalog = catalog if catalog is not None else CardCatalog.from_loaded_registry()

    def recognize_frame(
        self,
        frame_path: str,
        *,
        frame_index: int,
        timestamp_seconds: float,
    ) -> tuple[list[ConfirmedCardObservation], list[AmbiguousCardObservation]]:
        del frame_path, frame_index, timestamp_seconds
        return [], []


def classify_probe_hits(
    hits: Sequence[RawCardProbeHit],
    *,
    catalog: CardCatalog,
    frame_index: int,
    timestamp_seconds: float,
    source: str = SOURCE_HEURISTIC,
) -> tuple[list[ConfirmedCardObservation], list[AmbiguousCardObservation]]:
    """Validate hits against catalog and apply confidence / ambiguity rules."""
    resolved: list[CardCandidate] = []
    location = LOC_UNKNOWN
    for hit in hits:
        card = _resolve_hit(hit, catalog)
        if card is None:
            continue
        conf = float(hit.confidence)
        if conf < 0:
            continue
        if conf > 1:
            conf = 1.0
        resolved.append(
            CardCandidate(card_id=card.card_id, card_name=card.card_name, confidence=conf)
        )
        location = _normalize_location(hit.location)

    if not resolved:
        return [], []

    # Dedupe by card_id keeping max confidence
    best: dict[str, CardCandidate] = {}
    for cand in resolved:
        prev = best.get(cand.card_id)
        if prev is None or cand.confidence > prev.confidence:
            best[cand.card_id] = cand
    ranked = sorted(best.values(), key=lambda c: c.confidence, reverse=True)

    top = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None

    # LOW — never authoritative
    if top.confidence < CONF_MEDIUM:
        return [], []

    # Ambiguous: two close medium/high candidates
    if second is not None and (top.confidence - second.confidence) <= _AMBIGUOUS_GAP:
        if second.confidence >= CONF_MEDIUM:
            return [], [
                AmbiguousCardObservation(
                    candidates=tuple(ranked[:3]),
                    frame_index=frame_index,
                    timestamp_seconds=timestamp_seconds,
                    location=location,
                    source=source,
                )
            ]

    # HIGH only → confirmed observation (MEDIUM alone is not a fact later)
    if top.confidence >= CONF_HIGH:
        return [
            ConfirmedCardObservation(
                card_id=top.card_id,
                card_name=top.card_name,
                confidence=top.confidence,
                frame_index=frame_index,
                timestamp_seconds=timestamp_seconds,
                location=location,
                source=source,
            )
        ], []

    # MEDIUM alone: not confirmed, not ambiguous — drop from authoritative outputs
    return [], []


def group_confirmed_cards(
    observations: Sequence[ConfirmedCardObservation],
    *,
    gap_seconds: float = DEFAULT_GROUP_GAP_SECONDS,
) -> list[ConfirmedCardFact]:
    """Temporal dedupe: same card on nearby frames → one interval."""
    if not observations:
        return []
    ordered = sorted(
        observations,
        key=lambda o: (o.card_id, o.timestamp_seconds, o.frame_index),
    )
    groups: list[ConfirmedCardFact] = []
    cur_id = ordered[0].card_id
    cur_name = ordered[0].card_name
    cur_conf = ordered[0].confidence
    first = ordered[0].timestamp_seconds
    last = ordered[0].timestamp_seconds

    def flush() -> None:
        groups.append(
            ConfirmedCardFact(
                card_id=cur_id,
                card_name=cur_name,
                confidence=cur_conf,
                first_seen=first,
                last_seen=last,
            )
        )

    for obs in ordered[1:]:
        if obs.card_id == cur_id and (obs.timestamp_seconds - last) <= gap_seconds:
            last = max(last, obs.timestamp_seconds)
            cur_conf = max(cur_conf, obs.confidence)
            continue
        flush()
        cur_id = obs.card_id
        cur_name = obs.card_name
        cur_conf = obs.confidence
        first = obs.timestamp_seconds
        last = obs.timestamp_seconds
    flush()
    return groups


def _resolve_hit(hit: RawCardProbeHit, catalog: CardCatalog) -> CatalogCard | None:
    return catalog.resolve(card_id=hit.card_id, card_name=hit.card_name)


def _normalize_location(raw: str | None) -> str:
    value = (raw or LOC_UNKNOWN).strip().lower()
    if value not in CARD_LOCATIONS:
        return LOC_UNKNOWN
    return value

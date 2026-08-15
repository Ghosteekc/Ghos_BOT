"""Cycle reconstruction from confirmed card_play events only."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from bot.services.ghosteek_ai.replay.events import (
    EVENT_CARD_PLAY,
    PLAYER_OPPONENT,
    PLAYER_SELF,
    ReplayEvent,
)


@dataclass(frozen=True)
class ReplayCycleState:
    player_cycle: list[str] = field(default_factory=list)
    opponent_cycle: list[str] = field(default_factory=list)
    confidence: float = 0.0
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "player_cycle": list(self.player_cycle),
            "opponent_cycle": list(self.opponent_cycle),
            "confidence": round(float(self.confidence), 4),
            "limitations": list(self.limitations),
        }


def build_cycle_from_confirmed_plays(
    confirmed_events: Sequence[ReplayEvent],
) -> ReplayCycleState:
    """
    Ordered unique card_ids from confirmed card_play only.

    Does not invent missing deck slots. Unknown-side plays are ignored for cycle.
    """
    player: list[str] = []
    opponent: list[str] = []
    limitations: list[str] = []

    plays = [
        e
        for e in confirmed_events
        if e.event_type == EVENT_CARD_PLAY
        and e.card_id
        and float(e.confidence) >= 0.90
    ]
    plays = sorted(plays, key=lambda e: (e.timestamp_seconds, e.card_id or ""))

    seen_p: set[str] = set()
    seen_o: set[str] = set()
    for ev in plays:
        cid = str(ev.card_id)
        if ev.player == PLAYER_SELF:
            if cid not in seen_p:
                seen_p.add(cid)
                player.append(cid)
        elif ev.player == PLAYER_OPPONENT:
            if cid not in seen_o:
                seen_o.add(cid)
                opponent.append(cid)
        else:
            limitations.append("unknown_side_plays_excluded_from_cycle")

    if not plays:
        limitations.append("cycle_unavailable_without_confirmed_card_play")
        return ReplayCycleState(limitations=limitations, confidence=0.0)

    if len(player) < 8:
        limitations.append("player_cycle_incomplete")
    if len(opponent) < 8:
        limitations.append("opponent_cycle_incomplete")

    conf = 0.55
    if player:
        conf = max(conf, 0.72)
    if opponent:
        conf = max(conf, 0.72)
    if len(player) >= 4 or len(opponent) >= 4:
        conf = max(conf, 0.80)

    # unique limitation strings
    uniq_lim: list[str] = []
    for item in limitations:
        if item not in uniq_lim:
            uniq_lim.append(item)

    return ReplayCycleState(
        player_cycle=player,
        opponent_cycle=opponent,
        confidence=round(conf, 4),
        limitations=uniq_lim,
    )

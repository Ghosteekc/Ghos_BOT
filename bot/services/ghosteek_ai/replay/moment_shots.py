"""Extract UI thumbnails for grounded replay moments. No LLM."""

from __future__ import annotations

import base64
import logging
import os
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from bot.services.ghosteek_ai.replay.card_recognizer import ConfirmedCardFact
from bot.services.ghosteek_ai.replay.events import (
    EVENT_BATTLE_END,
    EVENT_BATTLE_START,
    EVENT_CARD_IDENTITY_VISIBLE,
    EVENT_CARD_PLAY_CANDIDATE,
    EVENT_CARD_PLAY_CONFIRMED,
    EVENT_OVERTIME_VISIBLE,
    EVENT_RESULT_VISIBLE,
    ReplayEvent,
)
from bot.services.ghosteek_ai.replay.sampler import scaled_dimensions
from bot.services.ghosteek_ai.replay.validator import find_ffmpeg

logger = logging.getLogger(__name__)

MAX_MOMENT_SHOTS = 6
DISPLAY_SHORT_SIDE = 720
_EXTRACT_TIMEOUT = 8.0

_LABELS = {
    EVENT_BATTLE_START: "Начало боя",
    EVENT_BATTLE_END: "Конец боя",
    EVENT_RESULT_VISIBLE: "Экран результата",
    EVENT_CARD_IDENTITY_VISIBLE: "Карта на экране",
    EVENT_CARD_PLAY_CONFIRMED: "Розыгрыш",
    EVENT_CARD_PLAY_CANDIDATE: "Возможный розыгрыш",
    EVENT_OVERTIME_VISIBLE: "Овертайм",
}


@dataclass(frozen=True)
class MomentShot:
    timestamp_seconds: float
    label: str
    kind: str  # confirmed | candidate
    image_base64: str

    def to_dict(self) -> dict:
        return {
            "timestamp_seconds": round(float(self.timestamp_seconds), 3),
            "label": self.label,
            "kind": self.kind,
            "image_base64": self.image_base64,
        }


def extract_moment_shots(
    video_path: Path,
    *,
    src_width: int,
    src_height: int,
    confirmed_events: Sequence[ReplayEvent] = (),
    candidate_events: Sequence[ReplayEvent] = (),
    confirmed_cards: Sequence[ConfirmedCardFact] = (),
    limit: int = MAX_MOMENT_SHOTS,
) -> list[MomentShot]:
    """
    FFmpeg stills for grounded event timestamps only.
    Failures skip a shot; never raise into the analyze pipeline.
    """
    targets = _select_targets(
        confirmed_events=confirmed_events,
        candidate_events=candidate_events,
        confirmed_cards=confirmed_cards,
        limit=limit,
    )
    if not targets:
        return []
    binary = find_ffmpeg()
    if not binary:
        return []
    out_w, out_h = scaled_dimensions(src_width, src_height, short_side=DISPLAY_SHORT_SIDE)
    shots: list[MomentShot] = []
    for ts, label, kind in targets:
        try:
            b64 = _extract_jpeg_b64(
                binary=binary,
                video_path=video_path,
                timestamp=ts,
                width=out_w,
                height=out_h,
            )
        except Exception:
            logger.debug("moment shot failed at t=%.3f", ts, exc_info=True)
            continue
        if not b64:
            continue
        shots.append(
            MomentShot(
                timestamp_seconds=float(ts),
                label=label,
                kind=kind,
                image_base64=b64,
            )
        )
    return shots


def _select_targets(
    *,
    confirmed_events: Sequence[ReplayEvent],
    candidate_events: Sequence[ReplayEvent],
    confirmed_cards: Sequence[ConfirmedCardFact],
    limit: int,
) -> list[tuple[float, str, str]]:
    card_names = {c.card_id: c.card_name for c in confirmed_cards if c.card_id}
    out: list[tuple[float, str, str]] = []
    seen_ts: set[float] = set()

    def add(ev: ReplayEvent, kind: str) -> None:
        ts = round(float(ev.timestamp_seconds), 3)
        if ts in seen_ts:
            return
        seen_ts.add(ts)
        out.append((ts, _label_for(ev, card_names), kind))

    for ev in sorted(confirmed_events, key=lambda e: e.timestamp_seconds):
        add(ev, "confirmed")
        if len(out) >= limit:
            return out[:limit]
    for ev in sorted(candidate_events, key=lambda e: e.timestamp_seconds):
        if ev.event_type != EVENT_CARD_PLAY_CANDIDATE:
            continue
        add(ev, "candidate")
        if len(out) >= limit:
            break
    return out[:limit]


def _label_for(ev: ReplayEvent, card_names: dict[str, str]) -> str:
    base = _LABELS.get(ev.event_type, "Момент")
    if ev.card_id and ev.card_id in card_names:
        return f"{base}: {card_names[ev.card_id]}"
    return base


def _extract_jpeg_b64(
    *,
    binary: str,
    video_path: Path,
    timestamp: float,
    width: int,
    height: int,
) -> str | None:
    handle = tempfile.NamedTemporaryFile(prefix="ghosteek-moment-", suffix=".jpg", delete=False)
    dest = Path(handle.name)
    handle.close()
    try:
        vf = f"scale={width}:{height}:flags=lanczos"
        cmd = [
            binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-vf",
            vf,
            "-q:v",
            "5",
            "-y",
            str(dest),
        ]
        completed = subprocess.run(
            cmd,
            capture_output=True,
            timeout=_EXTRACT_TIMEOUT,
            check=False,
            **_subprocess_kwargs(),
        )
        if completed.returncode != 0 or not dest.is_file() or dest.stat().st_size <= 0:
            return None
        return base64.b64encode(dest.read_bytes()).decode("ascii")
    finally:
        dest.unlink(missing_ok=True)


def _subprocess_kwargs() -> dict:
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}

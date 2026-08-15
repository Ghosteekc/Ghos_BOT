"""Replay validation + Stage 3–7 detection/timeline/facts/cards/coach. Single-flight lock."""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path

from bot.services.ghosteek_ai.replay.battle_timeline import ReplayBattleTimelineBuilder
from bot.services.ghosteek_ai.replay.card_recognizer import (
    AmbiguousCardObservation,
    ConfirmedCardObservation,
    HeuristicCardRecognizer,
    ReplayCardRecognizer,
    group_confirmed_cards,
)
from bot.services.ghosteek_ai.replay.coach_renderer import ReplayCoachRenderer
from bot.services.ghosteek_ai.replay.compressor import compress_replay_video
from bot.services.ghosteek_ai.replay.cycle import build_cycle_from_confirmed_plays
from bot.services.ghosteek_ai.replay.elixir import ElixirObserver
from bot.services.ghosteek_ai.replay.events import ReplayEventDetector
from bot.services.ghosteek_ai.replay.facts import ReplayFactsBuilder
from bot.services.ghosteek_ai.replay.game_state import GameStateBuilder
from bot.services.ghosteek_ai.replay.hud_analyzer import HeuristicHudAnalyzer
from bot.services.ghosteek_ai.replay.models import (
    STATUS_CR,
    DetectionBundle,
    FrameSignalSnapshot,
    ReplayAnalyzeOutcome,
    ReplayAnalysisResult,
    ReplayDetection,
    max_concurrent_jobs,
)
from bot.services.ghosteek_ai.replay.sampler import FrameSampler
from bot.services.ghosteek_ai.replay.tactical_analysis import ReplayTacticalAnalyzer
from bot.services.ghosteek_ai.replay.timeline import ReplayTimelineBuilder
from bot.services.ghosteek_ai.replay.validator import (
    CODE_BUSY,
    CODE_FRAME_ANALYSIS_FAILED,
    CODE_INTERNAL,
    CODE_TOO_LARGE,
    CODE_TOO_LONG,
    MAX_DURATION_SECONDS,
    MAX_SIZE_BYTES,
    ReplayError,
    ReplayMeta,
    probe_video,
    validate_identity,
    validate_size,
)

logger = logging.getLogger(__name__)

_READ_CHUNK = 1024 * 1024
ReadChunk = Callable[[int], Awaitable[bytes]]


class ReplayAnalyzeService:
    def __init__(
        self,
        *,
        sampler: FrameSampler | None = None,
        analyzer: HeuristicHudAnalyzer | None = None,
        timeline_builder: ReplayTimelineBuilder | None = None,
        facts_builder: ReplayFactsBuilder | None = None,
        card_recognizer: ReplayCardRecognizer | None = None,
        event_detector: ReplayEventDetector | None = None,
        battle_timeline_builder: ReplayBattleTimelineBuilder | None = None,
        tactical_analyzer: ReplayTacticalAnalyzer | None = None,
        coach_renderer: ReplayCoachRenderer | None = None,
    ) -> None:
        self._busy = False
        self._active_jobs = 0
        self._max_jobs = max_concurrent_jobs()
        self._sampler = sampler
        self._analyzer = analyzer
        self._timeline_builder = timeline_builder
        self._facts_builder = facts_builder
        self._card_recognizer = card_recognizer
        self._event_detector = event_detector
        self._battle_timeline_builder = battle_timeline_builder
        self._tactical_analyzer = tactical_analyzer
        self._coach_renderer = coach_renderer
        self._game_state_builder = GameStateBuilder()
        self._elixir_observer = ElixirObserver()

    async def validate_upload(
        self,
        *,
        filename: str | None,
        content_type: str | None,
        read: ReadChunk,
    ) -> ReplayMeta:
        meta, _detection, _analysis = await self._run_pipeline(
            filename=filename,
            content_type=content_type,
            read=read,
            detect=False,
        )
        return meta

    async def analyze_upload(
        self,
        *,
        filename: str | None,
        content_type: str | None,
        read: ReadChunk,
    ) -> ReplayAnalyzeOutcome:
        meta, detection, analysis = await self._run_pipeline(
            filename=filename,
            content_type=content_type,
            read=read,
            detect=True,
        )
        assert detection is not None
        if analysis is not None and detection.status == STATUS_CR:
            analysis = await self._attach_coach(analysis)
        return ReplayAnalyzeOutcome(
            filename=meta.filename,
            mime_type=meta.mime_type,
            size_bytes=meta.size_bytes,
            duration_seconds=meta.duration_seconds,
            width=meta.width,
            height=meta.height,
            fps=meta.fps,
            detection=detection,
            analysis=analysis,
        )

    async def _attach_coach(self, analysis: ReplayAnalysisResult) -> ReplayAnalysisResult:
        renderer = self._coach_renderer or ReplayCoachRenderer()
        try:
            result = await renderer.arender(
                tactical=analysis.tactical_analysis,  # type: ignore[arg-type]
                battle_timeline=analysis.battle_timeline,  # type: ignore[arg-type]
                confirmed_cards=list(analysis.confirmed_cards),
                confirmed_events=list(analysis.confirmed_events),
                events=list(analysis.events),
                candidate_events=list(analysis.candidate_events),
                limitations=list(analysis.limitations),
                facts=list(analysis.facts),
            )
        except Exception:
            logger.exception("replay coach attach failed")
            fallback = renderer.render_template(
                tactical=analysis.tactical_analysis,  # type: ignore[arg-type]
                battle_timeline=analysis.battle_timeline,  # type: ignore[arg-type]
                confirmed_cards=list(analysis.confirmed_cards),
                confirmed_events=list(analysis.confirmed_events),
                events=list(analysis.events),
                candidate_events=list(analysis.candidate_events),
                limitations=list(analysis.limitations),
                facts=list(analysis.facts),
            )
            return replace(
                analysis,
                coach_reply=fallback.text,
                coach_source=fallback.source,
            )
        return replace(
            analysis,
            coach_reply=result.text,
            coach_source=result.source,
        )

    async def _run_pipeline(
        self,
        *,
        filename: str | None,
        content_type: str | None,
        read: ReadChunk,
        detect: bool,
    ) -> tuple[ReplayMeta, ReplayDetection | None, ReplayAnalysisResult | None]:
        if self._busy or self._active_jobs >= self._max_jobs:
            raise ReplayError(CODE_BUSY)
        self._busy = True
        self._active_jobs += 1
        temps: list[Path] = []
        try:
            header, tmp_path, size_bytes = await _spool_limited(read)
            temps.append(tmp_path)
            validate_size(size_bytes)
            safe_name, mime = validate_identity(filename, content_type, header)
            duration, width, height, fps = probe_video(tmp_path)
            if duration > MAX_DURATION_SECONDS:
                raise ReplayError(CODE_TOO_LONG)
            working = compress_replay_video(
                tmp_path,
                size_bytes=size_bytes,
                width=width,
                height=height,
                fps=fps,
            )
            if working != tmp_path:
                temps.append(working)
                duration, width, height, fps = probe_video(working)
                size_bytes = working.stat().st_size
                mime = "video/mp4"
            meta = ReplayMeta(
                filename=safe_name,
                mime_type=mime,
                size_bytes=size_bytes,
                duration_seconds=round(duration, 3),
                width=width,
                height=height,
                fps=fps,
            )
            if not detect:
                return meta, None, None
            bundle = self._run_detection(working, duration, width, height)
            analysis = self._build_stage4(bundle, duration_seconds=meta.duration_seconds)
            return meta, bundle.detection, analysis
        except ReplayError:
            raise
        except Exception:
            logger.exception("replay %s failed", "analysis" if detect else "validation")
            raise ReplayError(CODE_INTERNAL) from None
        finally:
            for path in temps:
                _unlink_quiet(path)
            self._active_jobs = max(0, self._active_jobs - 1)
            self._busy = False

    def _run_detection(
        self,
        video_path: Path,
        duration: float,
        width: int,
        height: int,
    ) -> DetectionBundle:
        sampler = self._sampler or FrameSampler()
        analyzer = self._analyzer or HeuristicHudAnalyzer()
        recognizer = self._card_recognizer or HeuristicCardRecognizer()
        scores: list[float] = []
        observations: list[str] = []
        hits: dict[str, int] = {}
        frames: list[FrameSignalSnapshot] = []
        confirmed_cards: list[ConfirmedCardObservation] = []
        ambiguous_cards: list[AmbiguousCardObservation] = []
        try:
            for index, frame in enumerate(
                sampler.iter_sampled_frames(
                    video_path,
                    duration=duration,
                    src_width=width,
                    src_height=height,
                )
            ):
                scored = analyzer.analyze_frame(frame.path)
                scores.append(scored.score)
                frames.append(
                    FrameSignalSnapshot(
                        frame_index=index,
                        timestamp=float(frame.timestamp),
                        score=float(scored.score),
                        signals=tuple(scored.signals),
                    )
                )
                for sig in scored.signals:
                    if sig.score >= 0.55 and sig.observation:
                        hits[sig.signal] = hits.get(sig.signal, 0) + 1
                        if sig.observation not in observations:
                            observations.append(sig.observation)
                # Recognize while frame file still exists (sampler cleans after yield).
                confirmed, ambiguous = recognizer.recognize_frame(
                    frame.path,
                    frame_index=index,
                    timestamp_seconds=float(frame.timestamp),
                )
                confirmed_cards.extend(confirmed)
                ambiguous_cards.extend(ambiguous)
        except ReplayError:
            raise
        except Exception:
            logger.exception("replay frame analysis failed")
            raise ReplayError(CODE_FRAME_ANALYSIS_FAILED) from None
        detection = analyzer.classify(
            scores,
            observations,
            frames_analyzed=len(scores),
            signal_hits=hits,
        )
        game_states = self._game_state_builder.build(frames)
        return DetectionBundle(
            detection=detection,
            frames=tuple(frames),
            confirmed_card_observations=tuple(confirmed_cards),
            ambiguous_card_observations=tuple(ambiguous_cards),
            game_state_observations=tuple(game_states),
        )

    def _build_stage4(
        self,
        bundle: DetectionBundle,
        *,
        duration_seconds: float,
    ) -> ReplayAnalysisResult | None:
        if bundle.detection.status != STATUS_CR:
            return None
        timeline_builder = self._timeline_builder or ReplayTimelineBuilder()
        facts_builder = self._facts_builder or ReplayFactsBuilder()
        event_detector = self._event_detector or ReplayEventDetector()
        timeline = timeline_builder.build(bundle.frames)
        confirmed = group_confirmed_cards(bundle.confirmed_card_observations)
        raw_events = event_detector.detect(
            card_observations=list(bundle.confirmed_card_observations),
            timeline=timeline,
            ambiguous_present=bool(bundle.ambiguous_card_observations),
        )
        events, confirmed_events, candidate_events = event_detector.partition(raw_events)
        battle_builder = self._battle_timeline_builder or ReplayBattleTimelineBuilder()
        battle_timeline = battle_builder.build(
            duration_seconds=duration_seconds,
            events=events,
            confirmed_events=confirmed_events,
            confirmed_cards=confirmed,
            confidence=float(bundle.detection.confidence),
        )
        tactical_analyzer = self._tactical_analyzer or ReplayTacticalAnalyzer()
        tactical = tactical_analyzer.analyze(
            battle_timeline=battle_timeline,
            confirmed_cards=confirmed,
            confirmed_events=confirmed_events,
            events=events,
        )
        game_states = list(bundle.game_state_observations)
        elixir = self._elixir_observer.observe(game_states)
        cycle = build_cycle_from_confirmed_plays(confirmed_events)
        return facts_builder.build(
            bundle.detection,
            timeline,
            duration_seconds=duration_seconds,
            confirmed_cards=confirmed,
            ambiguous_cards=list(bundle.ambiguous_card_observations),
            events=events,
            confirmed_events=confirmed_events,
            candidate_events=candidate_events,
            battle_timeline=battle_timeline,
            tactical_analysis=tactical,
            game_state_observations=game_states,
            elixir_observations=elixir,
            cycle=cycle,
        )


async def _spool_limited(read: ReadChunk) -> tuple[bytes, Path, int]:
    handle = tempfile.NamedTemporaryFile(prefix="ghosteek-replay-", suffix=".bin", delete=False)
    path = Path(handle.name)
    written = 0
    header = b""
    try:
        while True:
            chunk = await read(_READ_CHUNK)
            if not chunk:
                break
            if written + len(chunk) > MAX_SIZE_BYTES:
                raise ReplayError(CODE_TOO_LARGE)
            if len(header) < 16:
                need = 16 - len(header)
                header += chunk[:need]
            handle.write(chunk)
            written += len(chunk)
        handle.flush()
    except ReplayError:
        handle.close()
        _unlink_quiet(path)
        raise
    except Exception:
        handle.close()
        _unlink_quiet(path)
        raise
    else:
        handle.close()
    return header, path, written


def _unlink_quiet(path: Path) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        return
    except OSError:
        logger.warning("replay temp file not deleted: %s", path)


_SERVICE: ReplayAnalyzeService | None = None


def get_replay_service() -> ReplayAnalyzeService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = ReplayAnalyzeService()
    return _SERVICE

"""Replay validation + Stage 3 HUD detection. Single-flight lock, temp cleanup."""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from bot.services.ghosteek_ai.replay.hud_analyzer import HeuristicHudAnalyzer
from bot.services.ghosteek_ai.replay.models import ReplayAnalyzeOutcome, ReplayDetection
from bot.services.ghosteek_ai.replay.sampler import FrameSampler
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
    ) -> None:
        self._busy = False
        self._sampler = sampler
        self._analyzer = analyzer

    async def validate_upload(
        self,
        *,
        filename: str | None,
        content_type: str | None,
        read: ReadChunk,
    ) -> ReplayMeta:
        meta, _detection = await self._run_pipeline(
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
        meta, detection = await self._run_pipeline(
            filename=filename,
            content_type=content_type,
            read=read,
            detect=True,
        )
        assert detection is not None
        return ReplayAnalyzeOutcome(
            filename=meta.filename,
            mime_type=meta.mime_type,
            size_bytes=meta.size_bytes,
            duration_seconds=meta.duration_seconds,
            width=meta.width,
            height=meta.height,
            fps=meta.fps,
            detection=detection,
        )

    async def _run_pipeline(
        self,
        *,
        filename: str | None,
        content_type: str | None,
        read: ReadChunk,
        detect: bool,
    ) -> tuple[ReplayMeta, ReplayDetection | None]:
        if self._busy:
            raise ReplayError(CODE_BUSY)
        self._busy = True
        tmp_path: Path | None = None
        try:
            header, tmp_path, size_bytes = await _spool_limited(read)
            validate_size(size_bytes)
            safe_name, mime = validate_identity(filename, content_type, header)
            duration, width, height, fps = probe_video(tmp_path)
            if duration > MAX_DURATION_SECONDS:
                raise ReplayError(CODE_TOO_LONG)
            meta = ReplayMeta(
                filename=safe_name,
                mime_type=mime,
                size_bytes=size_bytes,
                duration_seconds=round(duration, 3),
                width=width,
                height=height,
                fps=fps,
            )
            detection = self._run_detection(tmp_path, duration, width, height) if detect else None
            return meta, detection
        except ReplayError:
            raise
        except Exception:
            logger.exception("replay %s failed", "analysis" if detect else "validation")
            raise ReplayError(CODE_INTERNAL) from None
        finally:
            if tmp_path is not None:
                _unlink_quiet(tmp_path)
            self._busy = False

    def _run_detection(
        self,
        video_path: Path,
        duration: float,
        width: int,
        height: int,
    ) -> ReplayDetection:
        sampler = self._sampler or FrameSampler()
        analyzer = self._analyzer or HeuristicHudAnalyzer()
        scores: list[float] = []
        observations: list[str] = []
        hits: dict[str, int] = {}
        try:
            for frame in sampler.iter_sampled_frames(
                video_path,
                duration=duration,
                src_width=width,
                src_height=height,
            ):
                scored = analyzer.analyze_frame(frame.path)
                scores.append(scored.score)
                for sig in scored.signals:
                    if sig.score >= 0.55 and sig.observation:
                        hits[sig.signal] = hits.get(sig.signal, 0) + 1
                        if sig.observation not in observations:
                            observations.append(sig.observation)
        except ReplayError:
            raise
        except Exception:
            logger.exception("replay frame analysis failed")
            raise ReplayError(CODE_FRAME_ANALYSIS_FAILED) from None
        return analyzer.classify(
            scores,
            observations,
            frames_analyzed=len(scores),
            signal_hits=hits,
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

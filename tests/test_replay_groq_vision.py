"""Groq vision adapter + provider factory for Stage 5."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from bot.services.ghosteek_ai.replay.groq_vision_analyzer import (
    DEFAULT_GROQ_VISION_MODEL,
    GroqVisionAnalyzer,
    GroqVisionTimeout,
    GroqVisionUnavailable,
)
from bot.services.ghosteek_ai.replay.ollama_vision_analyzer import OllamaVisionAnalyzer
from bot.services.ghosteek_ai.replay.vision_analyzer import VisionObservation
from bot.services.ghosteek_ai.replay.vision_errors import VisionTimeout, VisionUnavailable
from bot.services.ghosteek_ai.replay.vision_factory import create_vision_analyzer, vision_provider


def test_vision_provider_defaults_to_groq(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REPLAY_VISION_PROVIDER", raising=False)
    assert vision_provider() == "groq"


def test_vision_provider_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLAY_VISION_PROVIDER", "ollama")
    assert vision_provider() == "ollama"


def test_create_vision_analyzer_groq(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLAY_VISION_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    analyzer = create_vision_analyzer()
    assert isinstance(analyzer, GroqVisionAnalyzer)
    assert analyzer.model == DEFAULT_GROQ_VISION_MODEL or bool(analyzer.model)


def test_create_vision_analyzer_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLAY_VISION_PROVIDER", "ollama")
    analyzer = create_vision_analyzer()
    assert isinstance(analyzer, OllamaVisionAnalyzer)


def test_groq_exceptions_subclass_shared() -> None:
    assert issubclass(GroqVisionTimeout, VisionTimeout)
    assert issubclass(GroqVisionUnavailable, VisionUnavailable)


def test_groq_parses_openai_style_response(tmp_path: Path) -> None:
    frame = tmp_path / "f.jpg"
    frame.write_bytes(b"\xff\xd8\xff" + b"\x00" * 32)
    analyzer = GroqVisionAnalyzer(api_key="gsk_test", timeout_seconds=5.0)

    fake = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"observations":[{"event_type":"troop_visible",'
                        '"card_name":null,"side":"player","lane":"right","confidence":0.91}]}'
                    )
                }
            }
        ]
    }

    async def _run() -> list[VisionObservation]:
        with patch.object(analyzer, "_post_chat", return_value=fake):
            return await analyzer.analyze_frame(str(frame), frame_index=2, timestamp_seconds=3.5)

    out = asyncio.run(_run())
    assert len(out) == 1
    assert out[0].event_type == "troop_visible"
    assert out[0].side == "player"
    assert out[0].frame_index == 2
    assert out[0].timestamp_seconds == 3.5


def test_groq_timeout_returns_empty(tmp_path: Path) -> None:
    frame = tmp_path / "f.jpg"
    frame.write_bytes(b"\xff\xd8\xff" + b"\x00" * 32)
    analyzer = GroqVisionAnalyzer(api_key="gsk_test", timeout_seconds=0.01)

    async def _run() -> list[VisionObservation]:
        with patch.object(analyzer, "_post_chat", side_effect=GroqVisionTimeout("timeout")):
            return await analyzer.analyze_frame(str(frame), frame_index=0, timestamp_seconds=0.0)

    assert asyncio.run(_run()) == []


def test_groq_missing_key_returns_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    frame = tmp_path / "f.jpg"
    frame.write_bytes(b"\xff\xd8\xff" + b"\x00" * 32)
    analyzer = GroqVisionAnalyzer(api_key="", timeout_seconds=1.0)

    async def _run() -> list[VisionObservation]:
        return await analyzer.analyze_frame(str(frame), frame_index=0, timestamp_seconds=0.0)

    assert asyncio.run(_run()) == []

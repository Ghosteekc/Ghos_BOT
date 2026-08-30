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
from bot.services.ghosteek_ai.replay.replay_llm_provider import DEFAULT_REPLAY_WORDING_MODEL, replay_wording_provider
from bot.services.ghosteek_ai.replay.vision_analyzer import VisionObservation
from bot.services.ghosteek_ai.replay.vision_errors import VisionTimeout, VisionUnavailable
from bot.services.ghosteek_ai.replay.vision_factory import create_vision_analyzer, vision_provider
from bot.services.ghosteek_ai.replay.vision_shared import (
    parse_vision_json_content,
    salvage_observations_json,
    strip_model_thinking,
)


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


def test_strip_thinking_then_parse_json() -> None:
    raw = (
        "\n<think>\nplanning...\n"
        '{"observations":[{"event_type":"spell_visible","card_name":null,'
        '"side":"opponent","lane":"center","confidence":0.8}]}'
    )
    parsed = parse_vision_json_content(raw)
    assert isinstance(parsed, dict)
    assert parsed["observations"][0]["event_type"] == "spell_visible"
    assert strip_model_thinking("<think>foo") == ""


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


def test_groq_payload_disables_thinking(tmp_path: Path) -> None:
    analyzer = GroqVisionAnalyzer(api_key="gsk_test")
    captured: dict = {}

    async def fake_post(payload: dict) -> dict:
        captured.update(payload)
        return {"choices": [{"message": {"content": '{"observations":[]}'}}]}

    frame = tmp_path / "f.jpg"
    frame.write_bytes(b"\xff\xd8\xff" + b"\x00" * 32)

    async def _run() -> None:
        with patch.object(analyzer, "_post_chat", side_effect=fake_post):
            await analyzer.analyze_frame(str(frame), frame_index=0, timestamp_seconds=0.0)

    asyncio.run(_run())
    assert captured.get("reasoning_effort") == "none"
    assert captured.get("reasoning_format") == "hidden"
    assert captured.get("max_completion_tokens") == 1024


def test_salvage_truncated_vision_json() -> None:
    raw = (
        '```json\n{"observations":[{"event_type":"troop_visible","card_name":"Royal Recruits",'
        '"side":"player","lane":"right","confidence":0.9},{"event_type":"building_visible",'
        '"card_name":"Inferno Tower","sid'
    )
    parsed = parse_vision_json_content(raw)
    assert isinstance(parsed, dict)
    assert len(parsed["observations"]) == 1
    assert parsed["observations"][0]["card_name"] == "Royal Recruits"


def test_salvage_observations_json_helper() -> None:
    raw = (
        '{"observations":[{"event_type":"spell_visible","card_name":null,"side":"opponent",'
        '"lane":"center","confidence":0.8},{"event_type":"troop_visible","card_name":"Hog Rider"'
    )
    salvaged = salvage_observations_json(raw)
    assert salvaged is not None
    assert salvaged["observations"][0]["event_type"] == "spell_visible"


def test_replay_wording_provider_uses_separate_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from bot.config import settings

    monkeypatch.setattr(settings, "ghosteek_ai_backend", "groq")
    monkeypatch.setattr(settings, "llm_api_key", "gsk_test")
    monkeypatch.setattr(settings, "llm_base_url", "https://api.groq.com/openai/v1")
    monkeypatch.setattr(settings, "llm_model", "qwen/qwen3.6-27b")
    monkeypatch.setenv("REPLAY_WORDING_MODEL", "openai/gpt-oss-20b")
    provider = replay_wording_provider()
    assert provider.config.model == "openai/gpt-oss-20b"


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


def test_groq_retries_on_rate_limit() -> None:
    analyzer = GroqVisionAnalyzer(api_key="gsk_test", timeout_seconds=5.0)
    calls: list[int] = []

    class _Resp:
        def __init__(self, status: int, body: str) -> None:
            self.status = status
            self._body = body
            self.headers: dict[str, str] = {}

        async def text(self) -> str:
            return self._body

        async def __aenter__(self) -> "_Resp":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

    def fake_post(*_args: object, **_kwargs: object) -> _Resp:
        calls.append(1)
        if len(calls) == 1:
            return _Resp(429, '{"error":{"message":"try again in 0.01s"}}')
        return _Resp(200, '{"choices":[{"message":{"content":"{}"}}]}')

    session = type("S", (), {"closed": False, "post": fake_post})()

    async def _run() -> dict:
        analyzer._session = session  # noqa: SLF001
        with patch("asyncio.sleep", return_value=None):
            return await analyzer._post_chat({"model": "qwen/qwen3.6-27b"})  # noqa: SLF001

    result = asyncio.run(_run())
    assert len(calls) == 2
    assert result == {"choices": [{"message": {"content": "{}"}}]}

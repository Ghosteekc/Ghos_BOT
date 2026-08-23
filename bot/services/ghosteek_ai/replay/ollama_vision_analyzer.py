"""Ollama multimodal vision adapter for replay frame analysis. Not the text coaching renderer."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from pathlib import Path
from typing import Any

import aiohttp

from bot.services.ghosteek_ai.replay.card_catalog import CardCatalog
from bot.services.ghosteek_ai.replay.models import vision_timeout_seconds
from bot.services.ghosteek_ai.replay.vision_analyzer import VisionAnalyzer, VisionObservation
from bot.services.ghosteek_ai.replay.vision_events import parse_raw_observations

logger = logging.getLogger(__name__)

DEFAULT_VISION_MODEL = "qwen3.5:9b"

_VISION_SYSTEM = """You analyze Clash Royale replay still frames.
Return ONLY valid JSON with this shape:
{"observations":[{"event_type":"troop_visible","card_name":null,"side":"player","lane":"right","confidence":0.86}]}

Rules:
- observation only — never coaching or advice
- event_type must be one of: card_visible, card_play_candidate, troop_visible, spell_visible, building_visible, tower_damage_candidate, defensive_interaction_candidate, offensive_interaction_candidate, unknown
- confidence is required (0.0-1.0)
- card_name must be null unless you clearly read the card text/icon from THIS frame
- never guess card names from deck patterns or gameplay context
- side: player, opponent, or unknown
- lane: left, right, center, or unknown
- if unsure, use unknown event_type and lower confidence
"""


class OllamaVisionAnalyzer(VisionAnalyzer):
    """Qwen3.5:9b (or configured model) via Ollama /api/chat with image payloads."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        catalog: CardCatalog | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._base_url = (base_url or _default_base_url()).rstrip("/")
        self._model = (model or _default_model()).strip()
        self._timeout = float(timeout_seconds if timeout_seconds is not None else vision_timeout_seconds())
        self._catalog = catalog if catalog is not None else CardCatalog.from_loaded_registry()
        self._session = session

    @property
    def model(self) -> str:
        return self._model

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def analyze_frame(
        self,
        frame_path: str,
        *,
        frame_index: int,
        timestamp_seconds: float,
    ) -> list[VisionObservation]:
        path = Path(frame_path)
        if not path.is_file():
            logger.warning("vision frame missing: %s", frame_path)
            return []

        try:
            image_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError:
            logger.warning("vision frame unreadable: %s", frame_path)
            return []

        user_text = (
            f"Frame index {frame_index} at {timestamp_seconds:.2f}s. "
            "List visible gameplay observations only."
        )
        payload = {
            "model": self._model,
            "stream": False,
            "messages": [
                {"role": "system", "content": _VISION_SYSTEM},
                {
                    "role": "user",
                    "content": user_text,
                    "images": [image_b64],
                },
            ],
            "options": {
                "temperature": 0.1,
                "num_predict": 512,
            },
        }

        try:
            data = await self._post_chat(payload)
        except (OllamaVisionUnavailable, OllamaVisionTimeout) as exc:
            logger.warning("ollama vision unavailable/timeout frame=%s: %s", frame_index, exc)
            return []
        except Exception:
            logger.exception("ollama vision analyze failed frame=%s", frame_index)
            return []

        content = _extract_message_content(data)
        parsed = _parse_json_content(content)
        if parsed is None:
            logger.warning("ollama vision malformed JSON frame=%s", frame_index)
            return []

        return parse_raw_observations(
            parsed,
            frame_index=frame_index,
            timestamp_seconds=timestamp_seconds,
            catalog=self._catalog,
        )

    async def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}/api/chat"
        session = await self._get_session()
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        try:
            async with session.post(url, json=payload, timeout=timeout) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise OllamaVisionUnavailable(
                        f"Ollama HTTP {resp.status}: {text[:200]}"
                    )
                try:
                    return json.loads(text) if text else {}
                except json.JSONDecodeError as exc:
                    raise OllamaVisionUnavailable("Ollama returned non-JSON") from exc
        except asyncio.TimeoutError as exc:
            raise OllamaVisionTimeout("Ollama vision request timed out") from exc
        except aiohttp.ClientError as exc:
            raise OllamaVisionUnavailable(str(exc)) from exc

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session


class OllamaVisionUnavailable(Exception):
    """Ollama vision backend unreachable or errored."""


class OllamaVisionTimeout(Exception):
    """Ollama vision request exceeded timeout."""


def _default_base_url() -> str:
    try:
        from bot.config import settings

        return str(getattr(settings, "ollama_base_url", "") or "http://127.0.0.1:11434")
    except Exception:
        return "http://127.0.0.1:11434"


def _default_model() -> str:
    import os

    env = os.environ.get("REPLAY_VISION_MODEL", "").strip()
    if env:
        return env
    try:
        from bot.config import settings

        configured = str(getattr(settings, "replay_vision_model", "") or "").strip()
        if configured:
            return configured
    except Exception:
        pass
    return DEFAULT_VISION_MODEL


def _extract_message_content(data: dict[str, Any]) -> str:
    message = data.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
    return ""


def _parse_json_content(text: str) -> dict[str, Any] | list[Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                return None
        else:
            return None
    if isinstance(parsed, (dict, list)):
        return parsed
    return None

"""Groq multimodal vision adapter for replay frames. Not the text coaching renderer."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

import aiohttp

from bot.services.ghosteek_ai.replay.card_catalog import CardCatalog
from bot.services.ghosteek_ai.replay.models import vision_timeout_seconds
from bot.services.ghosteek_ai.replay.vision_analyzer import VisionAnalyzer, VisionObservation
from bot.services.ghosteek_ai.replay.vision_errors import VisionTimeout, VisionUnavailable
from bot.services.ghosteek_ai.replay.vision_events import parse_raw_observations
from bot.services.ghosteek_ai.replay.vision_shared import (
    VISION_SYSTEM_PROMPT,
    image_mime_for_path,
    parse_vision_json_content,
)

logger = logging.getLogger(__name__)

# Llama 4 Scout shut down on Groq (2026-07-17). Current vision models: qwen3.6 / 3.8.
DEFAULT_GROQ_VISION_MODEL = "qwen/qwen3.6-27b"
DEFAULT_GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class GroqVisionUnavailable(VisionUnavailable):
    """Groq vision backend unreachable or errored."""


class GroqVisionTimeout(VisionTimeout):
    """Groq vision request exceeded timeout."""


class GroqVisionAnalyzer(VisionAnalyzer):
    """OpenAI-compatible chat.completions with image_url (data URI) via Groq."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        catalog: CardCatalog | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._api_key = (api_key if api_key is not None else _default_api_key()).strip()
        self._base_url = (base_url or _default_base_url()).rstrip("/")
        self._model = (model or _default_model()).strip()
        self._timeout = float(
            timeout_seconds if timeout_seconds is not None else vision_timeout_seconds()
        )
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
        if not self._api_key:
            logger.warning("groq vision skipped: missing API key")
            return []

        path = Path(frame_path)
        if not path.is_file():
            logger.warning("vision frame missing: %s", frame_path)
            return []

        try:
            image_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError:
            logger.warning("vision frame unreadable: %s", frame_path)
            return []

        mime = image_mime_for_path(str(path))
        user_text = (
            f"Frame index {frame_index} at {timestamp_seconds:.2f}s. "
            "List visible gameplay observations only as JSON."
        )
        payload = {
            "model": self._model,
            "temperature": 0.1,
            "max_completion_tokens": 512,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": VISION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{image_b64}",
                            },
                        },
                    ],
                },
            ],
        }

        try:
            data = await self._post_chat(payload)
        except (GroqVisionUnavailable, GroqVisionTimeout) as exc:
            logger.warning("groq vision unavailable/timeout frame=%s: %s", frame_index, exc)
            return []
        except Exception:
            logger.exception("groq vision analyze failed frame=%s", frame_index)
            return []

        content = _extract_message_content(data)
        parsed = parse_vision_json_content(content)
        if parsed is None:
            logger.warning("groq vision malformed JSON frame=%s", frame_index)
            return []

        return parse_raw_observations(
            parsed,
            frame_index=frame_index,
            timestamp_seconds=timestamp_seconds,
            catalog=self._catalog,
        )

    async def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}/chat/completions"
        session = await self._get_session()
        timeout = aiohttp.ClientTimeout(total=self._timeout)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with session.post(url, json=payload, headers=headers, timeout=timeout) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise GroqVisionUnavailable(f"Groq HTTP {resp.status}: {text[:200]}")
                try:
                    return json.loads(text) if text else {}
                except json.JSONDecodeError as exc:
                    raise GroqVisionUnavailable("Groq returned non-JSON") from exc
        except asyncio.TimeoutError as exc:
            raise GroqVisionTimeout("Groq vision request timed out") from exc
        except aiohttp.ClientError as exc:
            raise GroqVisionUnavailable(str(exc)) from exc

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session


def _default_api_key() -> str:
    env = (os.environ.get("GROQ_API_KEY") or os.environ.get("LLM_API_KEY") or "").strip()
    if env:
        return env
    try:
        from bot.config import settings

        return str(getattr(settings, "llm_api_key", "") or "").strip()
    except Exception:
        return ""


def _default_base_url() -> str:
    env = (os.environ.get("REPLAY_VISION_BASE_URL") or "").strip()
    if env:
        return env
    try:
        from bot.config import settings

        base = str(getattr(settings, "llm_base_url", "") or "").strip()
        if "groq.com" in base.lower():
            return base
    except Exception:
        pass
    return DEFAULT_GROQ_BASE_URL


def _default_model() -> str:
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
    return DEFAULT_GROQ_VISION_MODEL


def _extract_message_content(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
    return ""

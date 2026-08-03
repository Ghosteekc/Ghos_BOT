"""Базовые типы / конфиг LLM-слоя (без вызова модели)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMCapabilities:
    """Что умеет конкретный провайдер."""

    tools: bool = False
    stream: bool = False
    json_mode: bool = False


@dataclass
class LLMConfig:
    """Параметры подключения. Модель не вызывается, пока provider не wired."""

    provider: str = "ollama"
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    temperature: float = 0.3
    max_tokens: int = 1024
    timeout_seconds: float = 60.0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout_seconds": self.timeout_seconds,
            "extra": dict(self.extra),
            # api_key намеренно не сериализуем в логи
        }

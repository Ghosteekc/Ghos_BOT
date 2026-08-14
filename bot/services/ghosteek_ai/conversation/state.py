"""ConversationState — полное состояние памяти диалога."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from bot.services.ghosteek_ai.models import ConversationMessage, FollowUpEvent

SESSION_TTL_SECONDS = 45 * 60
MAX_USER_MESSAGES = 20
MAX_ASSISTANT_MESSAGES = 20
MAX_TOOLS = 20
MAX_QUESTIONS = 20
MAX_FOLLOWUPS = 30
MAX_SUMMARY_CHARS = 1600


@dataclass
class ConversationState:
    """Память одной сессии пользователя."""

    # Interleaved timeline (после trim: ≤ 20 user + 20 assistant)
    messages: list[ConversationMessage] = field(default_factory=list)

    # Явные срезы (удобно для контекста / Qwen)
    last_questions: list[str] = field(default_factory=list)
    last_user_messages: list[str] = field(default_factory=list)
    last_assistant_messages: list[str] = field(default_factory=list)
    last_tools: list[str] = field(default_factory=list)

    last_deck: list[str] = field(default_factory=list)
    last_opponent_deck: list[str] = field(default_factory=list)
    last_battle_index: int | None = None
    last_battle: dict[str, Any] = field(default_factory=dict)
    last_recommendation: dict[str, Any] = field(default_factory=dict)
    last_analysis: dict[str, Any] = field(default_factory=dict)
    # Compact facts envelope for local renderer follow-ups («подробнее», «а почему?»).
    last_render_facts: dict[str, Any] = field(default_factory=dict)
    last_answer_brief: str = ""
    # Last accepted/uncertain CR replay upload (meta only — video file is deleted).
    last_replay: dict[str, Any] = field(default_factory=dict)

    last_intent: str | None = None
    last_service: str | None = None
    active_topic: str | None = None
    followups: list[FollowUpEvent] = field(default_factory=list)

    # Сжатая история
    summary: str = ""
    summary_updated_at: float = 0.0

    updated_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.updated_at = time.time()

    def expired(self, *, now: float | None = None) -> bool:
        ts = now if now is not None else time.time()
        return (ts - self.updated_at) > SESSION_TTL_SECONDS

    def user_count(self) -> int:
        return sum(1 for m in self.messages if m.role == "user")

    def assistant_count(self) -> int:
        return sum(1 for m in self.messages if m.role == "assistant")

    def to_public(self) -> dict[str, Any]:
        return {
            "last_deck": list(self.last_deck),
            "last_opponent_deck": list(self.last_opponent_deck),
            "last_battle_index": self.last_battle_index,
            "last_intent": self.last_intent,
            "last_service": self.last_service,
            "active_topic": self.active_topic,
            "message_count": len(self.messages),
            "user_message_count": self.user_count(),
            "assistant_message_count": self.assistant_count(),
            "question_count": len(self.last_questions),
            "tool_count": len(self.last_tools),
            "last_tools": list(self.last_tools[-5:]),
            "has_deck": len(self.last_deck) >= 8,
            "has_matchup": len(self.last_deck) >= 8 and len(self.last_opponent_deck) >= 8,
            "has_battle": self.last_battle_index is not None or bool(self.last_battle),
            "has_recommendation": bool(self.last_recommendation),
            "has_replay": bool(self.last_replay),
            "last_replay": dict(self.last_replay) if self.last_replay else None,
            "has_summary": bool(self.summary.strip()),
            "summary_preview": (self.summary[:160] + "…")
            if len(self.summary) > 160
            else self.summary,
        }

    def recent_messages_public(self, *, limit: int = 20) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for m in self.messages[-limit:]:
            out.append(
                {
                    "role": m.role,
                    "content": m.content,
                    "intent": m.intent,
                }
            )
        return out

    def memory_context(self) -> dict[str, Any]:
        """Контекст для Context Builder / Response Generator / будущего Qwen."""
        return {
            "summary": self.summary,
            "recent_messages": self.recent_messages_public(limit=20),
            "last_questions": list(self.last_questions[-10:]),
            "last_tools": list(self.last_tools[-10:]),
            "last_deck": list(self.last_deck),
            "last_opponent_deck": list(self.last_opponent_deck),
            "last_battle": dict(self.last_battle) if self.last_battle else None,
            "last_recommendation": dict(self.last_recommendation)
            if self.last_recommendation
            else None,
            "last_replay": dict(self.last_replay) if self.last_replay else None,
            "active_topic": self.active_topic,
            "last_intent": self.last_intent,
        }

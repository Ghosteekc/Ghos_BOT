"""Единый AIContext — все данные оркестратора в одном объекте.

Tools, Context Builder и Response Generator работают только с AIContext.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PlayerContext:
    telegram_id: int = 0
    tag: str | None = None
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"telegram_id": self.telegram_id, "tag": self.tag, "name": self.name}


@dataclass
class ArenaContext:
    arena_id: int | None = None
    trophies: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"arena_id": self.arena_id, "trophies": self.trophies}


@dataclass
class DeckContext:
    cards: list[str] = field(default_factory=list)
    opponent_cards: list[str] = field(default_factory=list)
    core: list[str] = field(default_factory=list)
    built_decks: list[dict[str, Any]] = field(default_factory=list)
    build_mode: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cards": list(self.cards),
            "opponent_cards": list(self.opponent_cards),
            "core": list(self.core),
            "built_decks": list(self.built_decks),
            "build_mode": self.build_mode,
        }


@dataclass
class BattleContext:
    battle_index: int | None = None
    won: bool | None = None
    opponent_name: str | None = None
    matchup_score: Any = None
    outcome_summary: str | None = None
    reasons: list[Any] = field(default_factory=list)
    match_difficulty: dict[str, Any] | None = None
    match_plan: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        if self.raw:
            return dict(self.raw)
        return {
            "battle_index": self.battle_index,
            "won": self.won,
            "opponent_name": self.opponent_name,
            "matchup_score": self.matchup_score,
            "outcome_summary": self.outcome_summary,
            "reasons": list(self.reasons),
            "match_difficulty": self.match_difficulty,
            "match_plan": self.match_plan,
        }

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "BattleContext":
        return cls(
            battle_index=data.get("battle_index"),
            won=data.get("won"),
            opponent_name=data.get("opponent_name"),
            matchup_score=data.get("matchup_score"),
            outcome_summary=data.get("outcome_summary"),
            reasons=list(data.get("reasons") or []),
            match_difficulty=data.get("match_difficulty")
            if isinstance(data.get("match_difficulty"), dict)
            else None,
            match_plan=data.get("match_plan")
            if isinstance(data.get("match_plan"), dict)
            else None,
            raw=dict(data),
        )


@dataclass
class RecommendationContext:
    payload: dict[str, Any] = field(default_factory=dict)
    synergy_score: Any = None
    synergy_notes: list[Any] = field(default_factory=list)
    improvement_needed: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation": dict(self.payload),
            "synergy_score": self.synergy_score,
            "synergy_notes": list(self.synergy_notes),
            "improvement_needed": self.improvement_needed,
        }


@dataclass
class EvaluationContext:
    score: Any = None
    rating: str | None = None
    reasons: list[Any] = field(default_factory=list)
    advantages: list[Any] = field(default_factory=list)
    disadvantages: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "rating": self.rating,
            "reasons": list(self.reasons),
            "advantages": list(self.advantages),
            "disadvantages": list(self.disadvantages),
        }

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "EvaluationContext":
        return cls(
            score=data.get("score"),
            rating=data.get("rating"),
            reasons=list(data.get("reasons") or []),
            advantages=list(data.get("advantages") or []),
            disadvantages=list(data.get("disadvantages") or []),
        )


@dataclass
class IntentContext:
    """Запросный intent + DeckIntent из RecommendationEngine."""

    request: str = ""
    service: str = ""
    deck_intent: dict[str, Any] = field(default_factory=dict)
    card_query: str | None = None
    mechanic_query: str | None = None
    coach_topic: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "service": self.service,
            "deck_intent": dict(self.deck_intent),
            "card_query": self.card_query,
            "mechanic_query": self.mechanic_query,
            "coach_topic": self.coach_topic,
        }


@dataclass
class GamePlanContext:
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)


@dataclass
class SessionContext:
    public: dict[str, Any] = field(default_factory=dict)
    last_deck: list[str] = field(default_factory=list)
    last_opponent_deck: list[str] = field(default_factory=list)
    last_battle_index: int | None = None
    last_battle: dict[str, Any] = field(default_factory=dict)
    last_recommendation: dict[str, Any] = field(default_factory=dict)
    active_topic: str | None = None
    last_intent: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "public": dict(self.public),
            "last_deck": list(self.last_deck),
            "last_opponent_deck": list(self.last_opponent_deck),
            "last_battle_index": self.last_battle_index,
            "last_battle": dict(self.last_battle),
            "last_recommendation": dict(self.last_recommendation),
            "active_topic": self.active_topic,
            "last_intent": self.last_intent,
        }


@dataclass
class ConversationContext:
    summary: str = ""
    recent_messages: list[dict[str, Any]] = field(default_factory=list)
    last_questions: list[str] = field(default_factory=list)
    last_tools: list[str] = field(default_factory=list)
    followups: list[dict[str, Any]] = field(default_factory=list)
    active_topic: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "recent_messages": list(self.recent_messages),
            "last_questions": list(self.last_questions),
            "last_tools": list(self.last_tools),
            "followups": list(self.followups),
            "active_topic": self.active_topic,
        }


@dataclass
class KnowledgeContext:
    mechanic: dict[str, Any] = field(default_factory=dict)
    card: dict[str, Any] = field(default_factory=dict)
    coach: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mechanic": dict(self.mechanic),
            "card": dict(self.card),
            "coach": dict(self.coach),
        }


@dataclass
class MetaContext:
    ready: bool = False
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "data": dict(self.data),
            "error_code": self.error_code,
        }


@dataclass
class HistoryContext:
    """Сжатая история + снимки предыдущих анализов."""

    summary: str = ""
    turns: list[dict[str, Any]] = field(default_factory=list)
    last_analysis: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "turns": list(self.turns),
            "last_analysis": dict(self.last_analysis),
        }


@dataclass
class AIContext:
    """Единый контекст Ghosteek AI.

    Содержит:
      Player, Deck, Battle, Recommendation, Evaluation,
      Intent, GamePlan, Session, Conversation, Knowledge,
      Meta, Arena, History

    Tools читают/пишут только через этот объект (+ ToolResult как дельта).
    """

    player: PlayerContext = field(default_factory=PlayerContext)
    arena: ArenaContext = field(default_factory=ArenaContext)
    deck: DeckContext = field(default_factory=DeckContext)
    battle: BattleContext = field(default_factory=BattleContext)
    recommendation: RecommendationContext = field(default_factory=RecommendationContext)
    evaluation: EvaluationContext = field(default_factory=EvaluationContext)
    intent: IntentContext = field(default_factory=IntentContext)
    game_plan: GamePlanContext = field(default_factory=GamePlanContext)
    session: SessionContext = field(default_factory=SessionContext)
    conversation: ConversationContext = field(default_factory=ConversationContext)
    knowledge: KnowledgeContext = field(default_factory=KnowledgeContext)
    meta: MetaContext = field(default_factory=MetaContext)
    history: HistoryContext = field(default_factory=HistoryContext)

    # Runtime / tool call
    raw_message: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    request_context: dict[str, Any] = field(default_factory=dict)
    ok: bool = False
    error_code: str | None = None
    error_params: dict[str, Any] = field(default_factory=dict)
    actions: list[dict[str, str]] = field(default_factory=list)
    tool_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)

    # Внутренняя ссылка на User для вызовов доменных сервисов (не для Generator)
    _user: Any = field(default=None, repr=False, compare=False)

    # --- Совместимость с Generator / старым плоским API ---

    @property
    def service(self) -> str:
        return self.intent.service

    @service.setter
    def service(self, value: str) -> None:
        self.intent.service = value

    @property
    def player_tag(self) -> str | None:
        return self.player.tag

    @property
    def player_name(self) -> str | None:
        return self.player.name

    @property
    def arena_id(self) -> int | None:
        return self.arena.arena_id

    @property
    def trophies(self) -> int | None:
        return self.arena.trophies

    @property
    def current_deck(self) -> list[str]:
        return list(self.deck.cards)

    @property
    def opponent_deck(self) -> list[str]:
        return list(self.deck.opponent_cards)

    @property
    def deck_intent(self) -> dict[str, Any] | None:
        return self.intent.deck_intent or None

    @property
    def synergy_score(self) -> Any:
        return self.recommendation.synergy_score

    @property
    def synergy_notes(self) -> list[Any]:
        return list(self.recommendation.synergy_notes)

    @property
    def recent_messages(self) -> list[dict[str, Any]]:
        return list(self.conversation.recent_messages)

    @property
    def last_questions(self) -> list[str]:
        return list(self.conversation.last_questions)

    @property
    def last_tools(self) -> list[str]:
        return list(self.conversation.last_tools)

    @property
    def conversation_summary(self) -> str:
        return self.conversation.summary or self.history.summary

    @property
    def active_topic(self) -> str | None:
        return self.conversation.active_topic or self.session.active_topic

    @property
    def followups(self) -> list[dict[str, Any]]:
        return list(self.conversation.followups)

    @property
    def last_battle_memory(self) -> dict[str, Any] | None:
        return dict(self.session.last_battle) if self.session.last_battle else None

    @property
    def last_recommendation_memory(self) -> dict[str, Any] | None:
        return (
            dict(self.session.last_recommendation)
            if self.session.last_recommendation
            else None
        )

    @property
    def card(self) -> dict[str, Any] | None:
        return self.knowledge.card or None

    @property
    def mechanic(self) -> dict[str, Any] | None:
        return self.knowledge.mechanic or None

    @property
    def coach(self) -> dict[str, Any] | None:
        return self.knowledge.coach or None

    @property
    def build(self) -> dict[str, Any] | None:
        if not self.deck.built_decks and not self.deck.core:
            return None
        return {
            "core": list(self.deck.core),
            "decks": list(self.deck.built_decks),
            "mode": self.deck.build_mode,
        }

    def request_intent_name(self) -> str:
        return self.intent.request

    def primary_tool_data(self) -> dict[str, Any]:
        return dict(self.data or {})

    def require_user(self) -> Any:
        if self._user is None:
            raise RuntimeError("AIContext has no bound User for domain service calls")
        return self._user

    def arg(self, key: str, default: Any = None) -> Any:
        if key in self.tool_args and self.tool_args[key] is not None:
            return self.tool_args[key]
        return default

    def cards_arg(self) -> list[str]:
        raw = self.arg("cards")
        if isinstance(raw, list) and raw:
            return [c for c in raw if isinstance(c, str)]
        if self.deck.cards:
            return list(self.deck.cards)
        return list(self.session.last_deck)

    def opponent_cards_arg(self) -> list[str]:
        raw = self.arg("opponent_cards")
        if isinstance(raw, list) and raw:
            return [c for c in raw if isinstance(c, str)]
        if self.deck.opponent_cards:
            return list(self.deck.opponent_cards)
        return list(self.session.last_opponent_deck)

    def to_public_dict(self) -> dict[str, Any]:
        """Сериализация для Qwen / отладки."""
        return {
            "player": self.player.to_dict(),
            "arena": self.arena.to_dict(),
            "deck": self.deck.to_dict(),
            "battle": self.battle.to_dict(),
            "recommendation": self.recommendation.to_dict(),
            "evaluation": self.evaluation.to_dict(),
            "intent": self.intent.to_dict(),
            "game_plan": self.game_plan.to_dict(),
            "session": self.session.to_dict(),
            "conversation": self.conversation.to_dict(),
            "knowledge": self.knowledge.to_dict(),
            "meta": self.meta.to_dict(),
            "history": self.history.to_dict(),
            "ok": self.ok,
            "error_code": self.error_code,
            "actions": list(self.actions),
        }


# Alias: Generator и тесты ожидают ctx.intent как строку интента запроса.
# IntentContext лежит в поле intent — для строкового доступа используем helper.


def get_request_intent(ctx: AIContext) -> str:
    return ctx.intent.request

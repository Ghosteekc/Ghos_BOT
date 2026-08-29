"""Единый AIContext — все данные оркестратора в одном объекте.

Tools, Context Builder и Response Generator работают только с AIContext.
Полная сериализация: to_dict / from_dict (без _user).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [c for c in value if isinstance(c, str)]


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(x) for x in value if isinstance(x, dict)]


@dataclass
class PlayerContext:
    telegram_id: int = 0
    tag: str | None = None
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"telegram_id": self.telegram_id, "tag": self.tag, "name": self.name}

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "PlayerContext":
        data = _as_dict(raw)
        return cls(
            telegram_id=int(data.get("telegram_id") or 0),
            tag=data.get("tag"),
            name=data.get("name"),
        )


@dataclass
class ArenaContext:
    arena_id: int | None = None
    trophies: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"arena_id": self.arena_id, "trophies": self.trophies}

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "ArenaContext":
        data = _as_dict(raw)
        return cls(arena_id=data.get("arena_id"), trophies=data.get("trophies"))


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

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "DeckContext":
        data = _as_dict(raw)
        return cls(
            cards=_as_str_list(data.get("cards")),
            opponent_cards=_as_str_list(data.get("opponent_cards")),
            core=_as_str_list(data.get("core")),
            built_decks=_as_dict_list(data.get("built_decks")),
            build_mode=data.get("build_mode"),
        )


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
        """Плоский вид для Generator (совместимость: при raw — payload боя)."""
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

    def to_state_dict(self) -> dict[str, Any]:
        """Полное состояние для AIContext.to_dict (round-trip)."""
        return {
            "battle_index": self.battle_index,
            "won": self.won,
            "opponent_name": self.opponent_name,
            "matchup_score": self.matchup_score,
            "outcome_summary": self.outcome_summary,
            "reasons": list(self.reasons),
            "match_difficulty": dict(self.match_difficulty)
            if isinstance(self.match_difficulty, dict)
            else self.match_difficulty,
            "match_plan": dict(self.match_plan)
            if isinstance(self.match_plan, dict)
            else self.match_plan,
            "raw": dict(self.raw),
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

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "BattleContext":
        data = _as_dict(raw)
        if not data:
            return cls()
        nested_raw = data.get("raw") if isinstance(data.get("raw"), dict) else None
        # state_dict from to_state_dict / structured payload
        if nested_raw is not None or any(
            k in data for k in ("won", "opponent_name", "outcome_summary", "matchup_score")
        ):
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
                raw=dict(nested_raw) if nested_raw is not None else {},
            )
        return cls.from_data(data)


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

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "RecommendationContext":
        data = _as_dict(raw)
        payload = data.get("recommendation")
        if not isinstance(payload, dict):
            payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
        return cls(
            payload=dict(payload),
            synergy_score=data.get("synergy_score"),
            synergy_notes=list(data.get("synergy_notes") or []),
            improvement_needed=data.get("improvement_needed"),
        )


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

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "EvaluationContext":
        return cls.from_data(_as_dict(raw))


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

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "IntentContext":
        data = _as_dict(raw)
        return cls(
            request=str(data.get("request") or ""),
            service=str(data.get("service") or ""),
            deck_intent=_as_dict(data.get("deck_intent")),
            card_query=data.get("card_query"),
            mechanic_query=data.get("mechanic_query"),
            coach_topic=data.get("coach_topic"),
        )


@dataclass
class GamePlanContext:
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.payload)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "GamePlanContext":
        return cls(payload=_as_dict(raw))


@dataclass
class SessionContext:
    public: dict[str, Any] = field(default_factory=dict)
    last_deck: list[str] = field(default_factory=list)
    last_opponent_deck: list[str] = field(default_factory=list)
    last_build_core: list[str] = field(default_factory=list)
    last_build_shown: list[list[str]] = field(default_factory=list)
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
            "last_build_core": list(self.last_build_core),
            "last_build_shown": [list(d) for d in self.last_build_shown],
            "last_battle_index": self.last_battle_index,
            "last_battle": dict(self.last_battle),
            "last_recommendation": dict(self.last_recommendation),
            "active_topic": self.active_topic,
            "last_intent": self.last_intent,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "SessionContext":
        data = _as_dict(raw)
        shown_raw = data.get("last_build_shown") or []
        shown: list[list[str]] = []
        if isinstance(shown_raw, list):
            for item in shown_raw:
                if isinstance(item, list):
                    names = [c for c in item if isinstance(c, str)][:8]
                    if names:
                        shown.append(names)
        return cls(
            public=_as_dict(data.get("public")),
            last_deck=_as_str_list(data.get("last_deck")),
            last_opponent_deck=_as_str_list(data.get("last_opponent_deck")),
            last_build_core=_as_str_list(data.get("last_build_core")),
            last_build_shown=shown,
            last_battle_index=data.get("last_battle_index"),
            last_battle=_as_dict(data.get("last_battle")),
            last_recommendation=_as_dict(data.get("last_recommendation")),
            active_topic=data.get("active_topic"),
            last_intent=data.get("last_intent"),
        )


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

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "ConversationContext":
        data = _as_dict(raw)
        return cls(
            summary=str(data.get("summary") or ""),
            recent_messages=_as_dict_list(data.get("recent_messages")),
            last_questions=_as_str_list(data.get("last_questions")),
            last_tools=_as_str_list(data.get("last_tools")),
            followups=_as_dict_list(data.get("followups")),
            active_topic=data.get("active_topic"),
        )


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

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "KnowledgeContext":
        data = _as_dict(raw)
        return cls(
            mechanic=_as_dict(data.get("mechanic")),
            card=_as_dict(data.get("card")),
            coach=_as_dict(data.get("coach")),
        )


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

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "MetaContext":
        data = _as_dict(raw)
        return cls(
            ready=bool(data.get("ready")),
            data=_as_dict(data.get("data")),
            error_code=data.get("error_code"),
        )


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

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "HistoryContext":
        data = _as_dict(raw)
        return cls(
            summary=str(data.get("summary") or ""),
            turns=_as_dict_list(data.get("turns")),
            last_analysis=_as_dict(data.get("last_analysis")),
        )


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
    # Structured UI cards (optional; text answer stays separate)
    deck_card: dict[str, Any] | None = None
    # Local renderer only: compact facts envelope (не ToolResult / не API contract)
    render_facts: dict[str, Any] | None = None

    # Внутренняя ссылка на User для доменных сервисов (не для Generator / LLM)
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
        """Компактная сериализация (совместимость / отладка)."""
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

    def to_dict(self) -> dict[str, Any]:
        """Полная сериализация AIContext (без _user) — round-trip через from_dict."""
        return {
            "player": self.player.to_dict(),
            "arena": self.arena.to_dict(),
            "deck": self.deck.to_dict(),
            "battle": self.battle.to_state_dict(),
            "recommendation": self.recommendation.to_dict(),
            "evaluation": self.evaluation.to_dict(),
            "intent": self.intent.to_dict(),
            "game_plan": self.game_plan.to_dict(),
            "session": self.session.to_dict(),
            "conversation": self.conversation.to_dict(),
            "knowledge": self.knowledge.to_dict(),
            "meta": self.meta.to_dict(),
            "history": self.history.to_dict(),
            "raw_message": self.raw_message,
            "tool_args": dict(self.tool_args),
            "request_context": dict(self.request_context),
            "ok": self.ok,
            "error_code": self.error_code,
            "error_params": dict(self.error_params),
            "actions": list(self.actions),
            "tool_outputs": {k: dict(v) for k, v in self.tool_outputs.items()},
            "data": dict(self.data),
            "deck_card": dict(self.deck_card) if isinstance(self.deck_card, dict) else None,
        }

    def to_llm_dict(self) -> dict[str, Any]:
        """Компактный контекст для LLM: факты без дублей и пустых блоков.

        Не включает: полную историю сообщений (идёт отдельным блоком),
        сырой battle.raw, пустые секции, request_context целиком.
        """
        out: dict[str, Any] = {}

        player = {
            k: v
            for k, v in {
                "tag": self.player.tag,
                "name": self.player.name,
            }.items()
            if v
        }
        if player:
            out["player"] = player

        arena = {
            k: v
            for k, v in {
                "arena_id": self.arena.arena_id,
                "trophies": self.arena.trophies,
            }.items()
            if v is not None
        }
        if arena:
            out["arena"] = arena

        deck: dict[str, Any] = {}
        if self.deck.cards:
            deck["cards"] = list(self.deck.cards)[:8]
        if self.deck.opponent_cards:
            deck["opponent_cards"] = list(self.deck.opponent_cards)[:8]
        if self.deck.core:
            deck["core"] = list(self.deck.core)[:4]
        if self.deck.build_mode:
            deck["build_mode"] = self.deck.build_mode
        # Если есть deck_card для UI — не отдаём LLM полный список карт (иначе перечисляет в тексте).
        if self.deck_card and isinstance(self.deck_card, dict):
            deck["ui_deck_card"] = {
                "archetype": self.deck_card.get("archetype"),
                "average_elixir": self.deck_card.get("average_elixir"),
                "title": self.deck_card.get("title"),
                "shown_in_ui": True,
            }
        elif self.deck.built_decks:
            compact_builds: list[Any] = []
            for item in self.deck.built_decks[:2]:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("archetype")
                    if name:
                        compact_builds.append(str(name))
            if compact_builds:
                deck["built_decks"] = compact_builds
        if deck:
            out["deck"] = deck

        battle: dict[str, Any] = {}
        for key in (
            "battle_index",
            "won",
            "opponent_name",
            "matchup_score",
            "outcome_summary",
        ):
            val = getattr(self.battle, key, None)
            if val is not None and val != "":
                battle[key] = val
        if self.battle.reasons:
            battle["reasons"] = list(self.battle.reasons)[:4]
        if isinstance(self.battle.match_difficulty, dict) and self.battle.match_difficulty:
            # только ключевые поля, не весь объект
            md = self.battle.match_difficulty
            battle["match_difficulty"] = {
                k: md[k]
                for k in ("rating", "score", "label", "difficulty")
                if k in md
            } or {"keys": list(md.keys())[:5]}
        if isinstance(self.battle.match_plan, dict) and self.battle.match_plan:
            mp = self.battle.match_plan
            battle["match_plan"] = {
                k: mp[k]
                for k in ("how_to_win", "primary_threat", "key_tips", "tips")
                if k in mp
            } or {"keys": list(mp.keys())[:5]}
        # battle.raw намеренно НЕ включаем — раздувает TPM
        if battle:
            out["battle"] = battle

        intent = {
            k: v
            for k, v in self.intent.to_dict().items()
            if v not in (None, "", [], {})
        }
        if intent:
            out["intent"] = intent

        rec = {
            k: v
            for k, v in self.recommendation.to_dict().items()
            if v not in (None, "", [], {})
        }
        if rec:
            out["recommendation"] = rec

        evaluation = {
            k: v
            for k, v in self.evaluation.to_dict().items()
            if v not in (None, "", [], {})
        }
        if evaluation:
            out["evaluation"] = evaluation

        game_plan = {
            k: v
            for k, v in self.game_plan.to_dict().items()
            if v not in (None, "", [], {})
        }
        if game_plan:
            out["game_plan"] = game_plan

        knowledge = {
            k: v
            for k, v in self.knowledge.to_dict().items()
            if v not in (None, "", [], {})
        }
        if knowledge:
            out["knowledge"] = knowledge

        meta = {
            k: v
            for k, v in self.meta.to_dict().items()
            if v not in (None, "", [], {})
        }
        if meta:
            out["meta"] = meta

        # session — только полезные якоря, без полной истории
        session_src = self.session.to_dict() if hasattr(self.session, "to_dict") else {}
        session: dict[str, Any] = {}
        for key in (
            "last_deck",
            "last_opponent_deck",
            "active_topic",
            "last_intent",
            "last_questions",
        ):
            val = session_src.get(key) if isinstance(session_src, dict) else None
            if val not in (None, "", [], {}):
                if key == "last_questions" and isinstance(val, list):
                    session[key] = [str(x)[:120] for x in val[-3:]]
                else:
                    session[key] = val
        if session:
            out["session"] = session

        if self.ok is False:
            out["ok"] = False
        if self.error_code:
            out["error_code"] = self.error_code
        if self.error_params:
            out["error_params"] = dict(self.error_params)
        if self.data:
            # data часто дублирует tool payload — урезаем размер
            out["data"] = _compact_mapping(self.data, depth=0)

        return out

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "AIContext":
        data = _as_dict(raw)
        tool_outputs_raw = data.get("tool_outputs")
        tool_outputs: dict[str, dict[str, Any]] = {}
        if isinstance(tool_outputs_raw, dict):
            for key, val in tool_outputs_raw.items():
                if isinstance(val, dict):
                    tool_outputs[str(key)] = dict(val)

        actions_raw = data.get("actions")
        actions: list[dict[str, str]] = []
        if isinstance(actions_raw, list):
            for item in actions_raw:
                if isinstance(item, dict):
                    actions.append(
                        {
                            "type": str(item.get("type") or "navigate"),
                            "path": str(item.get("path") or "/"),
                        }
                    )

        return cls(
            player=PlayerContext.from_dict(data.get("player")),
            arena=ArenaContext.from_dict(data.get("arena")),
            deck=DeckContext.from_dict(data.get("deck")),
            battle=BattleContext.from_dict(data.get("battle")),
            recommendation=RecommendationContext.from_dict(data.get("recommendation")),
            evaluation=EvaluationContext.from_dict(data.get("evaluation")),
            intent=IntentContext.from_dict(data.get("intent")),
            game_plan=GamePlanContext.from_dict(data.get("game_plan")),
            session=SessionContext.from_dict(data.get("session")),
            conversation=ConversationContext.from_dict(data.get("conversation")),
            knowledge=KnowledgeContext.from_dict(data.get("knowledge")),
            meta=MetaContext.from_dict(data.get("meta")),
            history=HistoryContext.from_dict(data.get("history")),
            raw_message=str(data.get("raw_message") or ""),
            tool_args=_as_dict(data.get("tool_args")),
            request_context=_as_dict(data.get("request_context")),
            ok=bool(data.get("ok")),
            error_code=data.get("error_code"),
            error_params=_as_dict(data.get("error_params")),
            actions=actions,
            tool_outputs=tool_outputs,
            data=_as_dict(data.get("data")),
            deck_card=_as_dict(data.get("deck_card")) or None,
            _user=None,
        )


def _compact_mapping(value: Any, *, depth: int) -> Any:
    """Рекурсивно урезать большие dict/list для LLM prompt."""
    if depth > 3:
        return "…"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= 24:
                out["…"] = f"+{len(value) - 24} keys"
                break
            if v in (None, "", [], {}):
                continue
            out[str(k)] = _compact_mapping(v, depth=depth + 1)
        return out
    if isinstance(value, list):
        items = value[:12]
        compact = [_compact_mapping(x, depth=depth + 1) for x in items]
        if len(value) > 12:
            compact.append(f"…+{len(value) - 12}")
        return compact
    if isinstance(value, str) and len(value) > 280:
        return value[:277] + "…"
    return value


def get_request_intent(ctx: AIContext) -> str:
    return ctx.intent.request

"""Planner — выбирает Tool по каталогу, не зная реализации."""

from __future__ import annotations

from bot.services.ghosteek_ai.intents import (
    INTENT_ANALYZE_DECK,
    INTENT_BUILD_DECK,
    INTENT_CARD_INFO,
    INTENT_CLARIFY,
    INTENT_EXPLAIN_MECHANIC,
    INTENT_GAME_COACH,
    INTENT_IMPROVE_DECK,
    INTENT_LAST_BATTLE,
    INTENT_MATCHUP,
    INTENT_META,
    INTENT_STATS,
    INTENT_UNSUPPORTED,
    SERVICE_BY_INTENT,
    DetectedIntent,
)
from bot.services.ghosteek_ai.models import Plan, ToolSpec
from bot.services.ghosteek_ai.tools.base import ToolRegistry, get_default_registry

# Intent → tool name(s). Только имена из каталога Registry.
INTENT_TOOL_MAP: dict[str, list[str]] = {
    INTENT_UNSUPPORTED: ["unsupported"],
    INTENT_CLARIFY: ["clarify"],
    INTENT_LAST_BATTLE: ["battle_analysis"],
    INTENT_EXPLAIN_MECHANIC: ["knowledge"],
    INTENT_GAME_COACH: ["game_coach"],
    INTENT_CARD_INFO: ["card_info"],
    INTENT_BUILD_DECK: ["deck_builder"],
    INTENT_ANALYZE_DECK: ["deck_analysis"],
    INTENT_IMPROVE_DECK: ["recommendation"],
    INTENT_MATCHUP: ["matchup"],
    INTENT_META: ["meta"],
    INTENT_STATS: ["stats"],
}


class Planner:
    """Выбор tools по имени из Registry. Без текста и без импорта сервисов.

    Использование:
      Planner.plan(detected)           # совместимый static API
      Planner(registry).build(detected)  # instance API

    TODO(Qwen): заменить select_tool_names на tool_calls из модели,
    оставив validate + ToolCaller.execute_qwen_tool_calls.
    HOOK: bot.services.ghosteek_ai.planner.planner.Planner.build
    Модель пока не подключена.
    """

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self.registry = registry or get_default_registry()

    def available_tools(self) -> list[dict]:
        return self.registry.catalog()

    def qwen_tools(self) -> list[dict]:
        return self.registry.qwen_tools()

    def build(self, detected: DetectedIntent) -> Plan:
        intent = detected.intent
        service = detected.service or SERVICE_BY_INTENT.get(intent, "Clarify")
        names = self.select_tool_names(intent)
        args = self.args_from_detected(detected)
        tools = self.specs_for_names(names, args)
        return Plan(intent=intent, service=service, tools=tools)

    def plan_from_tool_names(
        self,
        names: list[str],
        *,
        intent: str = "",
        service: str = "",
        args: dict | None = None,
    ) -> Plan:
        tools = self.specs_for_names(names, args or {})
        return Plan(intent=intent or "qwen", service=service or "Qwen", tools=tools)

    def select_tool_names(self, intent: str) -> list[str]:
        return list(INTENT_TOOL_MAP.get(intent) or ["clarify"])

    def specs_for_names(self, names: list[str], args: dict) -> list[ToolSpec]:
        specs: list[ToolSpec] = []
        for name in names:
            if not self.registry.has(name):
                if self.registry.has("clarify"):
                    specs.append(ToolSpec(name="clarify", args=dict(args)))
                continue
            specs.append(ToolSpec(name=name, args=dict(args)))
        if not specs and self.registry.has("clarify"):
            specs.append(ToolSpec(name="clarify", args=dict(args)))
        return specs

    @staticmethod
    def args_from_detected(detected: DetectedIntent) -> dict:
        return {
            "cards": list(detected.cards),
            "opponent_cards": list(detected.opponent_cards),
            "card_query": detected.card_query,
            "mechanic_query": detected.mechanic_query,
            "coach_topic": detected.coach_topic,
            "raw": detected.raw,
        }

    @staticmethod
    def plan(detected: DetectedIntent, registry: ToolRegistry | None = None) -> Plan:
        """Static entry — не знает реализацию tools, только имена каталога."""
        return Planner(registry).build(detected)

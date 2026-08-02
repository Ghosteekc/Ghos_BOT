"""Tool Layer — BaseTool / Registry / ToolCaller работают только с AIContext."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Any

from bot.models.database import User
from bot.services.ghosteek_ai.context.ai_context import AIContext
from bot.services.ghosteek_ai.context.builder import ContextBuilder
from bot.services.ghosteek_ai.models import Plan, ToolResult, ToolSpec
from bot.services.ghosteek_ai.tools.schema import (
    STANDARD_OUTPUT_SCHEMA,
    ToolCall,
    ToolDefinition,
)


class BaseTool(ABC):
    """Универсальный Tool: name / description / schemas / execute(AIContext).

    Tools не принимают User/dict напрямую — только AIContext.
    """

    name: str = ""
    description: str = ""
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}
    output_schema: dict[str, Any] = STANDARD_OUTPUT_SCHEMA

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=self.description,
            input_schema=dict(self.input_schema),
            output_schema=dict(self.output_schema),
        )

    def to_qwen_function(self) -> dict[str, Any]:
        return self.definition().to_qwen_function()

    def to_openai_tool(self) -> dict[str, Any]:
        return self.definition().to_openai_tool()

    @abstractmethod
    async def execute(self, ctx: AIContext) -> ToolResult:
        """Выполнить tool. Читает AIContext, возвращает structured data."""
        ...

    async def run(self, ctx: AIContext) -> ToolResult:
        return await self.execute(ctx)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if not tool.name:
            raise ValueError("Tool must have a non-empty name")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools.keys())

    def definitions(self) -> list[ToolDefinition]:
        return [t.definition() for t in self._tools.values()]

    def catalog(self) -> list[dict[str, Any]]:
        return [d.to_catalog_entry() for d in self.definitions()]

    def qwen_tools(self) -> list[dict[str, Any]]:
        return [t.to_qwen_function() for t in self._tools.values()]

    def openai_tools(self) -> list[dict[str, Any]]:
        return self.qwen_tools()

    def has(self, name: str) -> bool:
        return name in self._tools


class ToolCaller:
    """Исполняет ToolCall / Plan, обновляя единый AIContext."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    async def execute_call(self, call: ToolCall, ctx: AIContext) -> ToolResult:
        tool = self.registry.get(call.name)
        if tool is None:
            result = ToolResult(
                tool=call.name,
                ok=False,
                error_code="UNKNOWN_TOOL",
                error_params={"name": call.name},
            )
            ContextBuilder.apply_tool_result(ctx, result)
            return result

        # Аргументы текущего вызова — в AIContext
        ctx.tool_args = dict(call.to_spec_args())
        # Синхронизация query-полей в Intent
        if ctx.tool_args.get("card_query"):
            ctx.intent.card_query = ctx.tool_args["card_query"]
        if ctx.tool_args.get("mechanic_query"):
            ctx.intent.mechanic_query = ctx.tool_args["mechanic_query"]
        if ctx.tool_args.get("coach_topic"):
            ctx.intent.coach_topic = ctx.tool_args["coach_topic"]
        cards = ctx.tool_args.get("cards")
        if isinstance(cards, list) and cards:
            ctx.deck.cards = [c for c in cards if isinstance(c, str)][:8]
        opp = ctx.tool_args.get("opponent_cards")
        if isinstance(opp, list) and opp:
            ctx.deck.opponent_cards = [c for c in opp if isinstance(c, str)][:8]

        result = await tool.execute(ctx)
        if not result.tool:
            result.tool = tool.name
        ContextBuilder.apply_tool_result(ctx, result)
        return result

    async def execute_calls(
        self,
        calls: list[ToolCall],
        ctx: AIContext,
    ) -> list[ToolResult]:
        results: list[ToolResult] = []
        for call in calls:
            results.append(await self.execute_call(call, ctx))
        return results

    async def execute_plan(self, plan: Plan, ctx: AIContext) -> list[ToolResult]:
        calls = [
            ToolCall(
                name=spec.name,
                arguments=dict(spec.args),
                id=f"plan_{uuid.uuid4().hex[:8]}",
            )
            for spec in plan.tools
        ]
        return await self.execute_calls(calls, ctx)

    async def execute_qwen_tool_calls(
        self,
        raw_tool_calls: list[dict[str, Any]],
        ctx: AIContext,
    ) -> list[ToolResult]:
        calls = [ToolCall.from_qwen_tool_call(raw) for raw in raw_tool_calls]
        return await self.execute_calls(calls, ctx)


async def execute_plan(
    plan: Plan,
    *,
    user: User,
    context: dict[str, Any],
    session_public: dict[str, Any],
    raw_message: str,
    registry: ToolRegistry,
    conversation: Any = None,
) -> list[ToolResult]:
    """Совместимость: собирает AIContext и вызывает ToolCaller."""
    from bot.services.ghosteek_ai.conversation.manager import ConversationManager

    conv = conversation
    if conv is None:
        conv = ConversationManager.get_or_create(user.telegram_id)

    ctx = ContextBuilder.bootstrap(
        user=user,
        plan=plan,
        conversation=conv,
        request_context=context,
        raw_message=raw_message,
        tool_args=dict(plan.tools[0].args) if plan.tools else {},
    )
    # session_public уже внутри bootstrap через conversation
    del session_public
    return await ToolCaller(registry).execute_plan(plan, ctx)


def build_default_registry() -> ToolRegistry:
    from bot.services.ghosteek_ai.tools.battle import BattleAnalysisTool
    from bot.services.ghosteek_ai.tools.card_info import CardInfoTool
    from bot.services.ghosteek_ai.tools.clarify import ClarifyTool
    from bot.services.ghosteek_ai.tools.coach import GameCoachTool
    from bot.services.ghosteek_ai.tools.deck_analysis import DeckAnalysisTool
    from bot.services.ghosteek_ai.tools.deck_builder import DeckBuilderTool
    from bot.services.ghosteek_ai.tools.knowledge import KnowledgeTool, MechanicsTool
    from bot.services.ghosteek_ai.tools.matchup import MatchupTool
    from bot.services.ghosteek_ai.tools.meta import MetaTool
    from bot.services.ghosteek_ai.tools.recommendation import RecommendationTool
    from bot.services.ghosteek_ai.tools.stats import StatsTool
    from bot.services.ghosteek_ai.tools.unsupported import UnsupportedTool

    registry = ToolRegistry()
    for tool in (
        UnsupportedTool(),
        ClarifyTool(),
        BattleAnalysisTool(),
        KnowledgeTool(),
        MechanicsTool(),
        GameCoachTool(),
        CardInfoTool(),
        DeckBuilderTool(),
        DeckAnalysisTool(),
        RecommendationTool(),
        MatchupTool(),
        MetaTool(),
        StatsTool(),
    ):
        registry.register(tool)
    return registry


_DEFAULT_REGISTRY: ToolRegistry | None = None


def get_default_registry() -> ToolRegistry:
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = build_default_registry()
    return _DEFAULT_REGISTRY

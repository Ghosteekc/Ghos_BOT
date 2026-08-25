"""Production audit regression tests (deck SoT, context, Pro/Credits, replay routing)."""

from __future__ import annotations

import asyncio

import pytest

from bot.services.ghosteek_ai.conversation.manager import ConversationManager
from bot.services.ghosteek_ai.conversation.state import ConversationState
from bot.services.ghosteek_ai.deck_card import extract_deck_names
from bot.services.ghosteek_ai.intents import INTENT_BUILD_DECK, detect_intent
from bot.services.ghosteek_ai.llm.local_renderer import attach_render_facts, detect_followup_kind
from bot.services.ghosteek_ai.replay_followup import is_replay_coaching_request
from bot.services.credits import TYPE_REFERRAL_REWARD, credit_once, get_credits_balance
from bot.services.pro.activation import activate_pro_from_payload
from bot.services.pro.entitlement import is_user_pro
from bot.services.referral.service import referral_stats_for_user
from tests.fixtures.local_renderer_toolresults import HOG_CYCLE, fixture_recommendation
from tests.test_referral import _add_user, _make_db


def test_recommendation_session_uses_original_deck_not_improved() -> None:
    session = ConversationState()
    original = list(HOG_CYCLE)
    improved = list(original)
    improved[0] = "Giant"

    ConversationManager.update_from_ai_context(
        session,
        intent="recommendation",
        service="recommendation",
        data={
            "deck": original,
            "original_deck": original,
            "improved_deck": improved,
        },
        ok=True,
    )
    assert session.last_deck == original
    assert session.last_deck != improved


def test_build_deck_ignores_stale_context_deck() -> None:
    stale = [
        "Hog Rider",
        "Musketeer",
        "Ice Spirit",
        "Skeletons",
        "Cannon",
        "Fireball",
        "The Log",
        "Ice Golem",
    ]
    detected = detect_intent("Собери колоду с Ведьмой", context_cards=stale)
    assert detected.intent == INTENT_BUILD_DECK
    assert detected.cards == ["Witch"]
    assert "Hog Rider" not in detected.cards


def test_attach_render_facts_does_not_reuse_when_tool_has_facts() -> None:
    from bot.services.ghosteek_ai.context.ai_context import AIContext
    from bot.services.ghosteek_ai.models import ToolResult
    from tests.fixtures.local_renderer_toolresults import ctx_from_tool_result

    prev_ctx = ctx_from_tool_result(
        fixture_recommendation(),
        intent="improve_deck",
        message="улучши колоду",
    )
    prev = attach_render_facts(prev_ctx)

    tr = ToolResult(
        tool="deck_analysis",
        ok=True,
        data={
            "deck": list(HOG_CYCLE),
            "average_elixir": 2.8,
            "roles": {"win_condition": "Hog Rider"},
        },
    )
    ctx = ctx_from_tool_result(tr, intent="deck_analysis", message="подробнее")
    ctx.request_context = {"last_render_facts": prev}
    assert detect_followup_kind("подробнее") == "detail"

    env = attach_render_facts(ctx)
    assert env["tool"] == "deck_analysis"
    assert env is not prev


def test_replay_deck_only_request_not_coaching() -> None:
    assert not is_replay_coaching_request("разбери колоду")
    assert not is_replay_coaching_request("анализ колоды")
    assert is_replay_coaching_request("разбери реплей")


def test_active_topic_preserved_on_chat() -> None:
    session = ConversationState()
    session.active_topic = "build_deck"
    ConversationManager.update_from_ai_context(
        session,
        intent="chat",
        service=None,
        data={},
        ok=True,
        active_topic=None,
    )
    assert session.active_topic == "build_deck"


def test_extract_deck_names_reads_deck_key() -> None:
    names = extract_deck_names({"deck": list(HOG_CYCLE)})
    assert names == list(HOG_CYCLE)


async def _run_credits_activation_fail_closed() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        user = await _add_user(session, 206_001)
        await credit_once(
            session,
            user_id=user.id,
            amount=10,
            tx_type=TYPE_REFERRAL_REWARD,
            reference_id="seed-10-fail",
        )
        await session.commit()

        result = await activate_pro_from_payload(
            session,
            user,
            plan_id="pro_1m",
            payment_charge_id="charge-fail-credits",
            amount_stars=50,
            credits_used=50,
        )
        assert result.activated is False
        assert await get_credits_balance(session, user.id) == 10
        assert await is_user_pro(session, user) is False
    await engine.dispose()


def test_credits_activation_fail_closed() -> None:
    asyncio.run(_run_credits_activation_fail_closed())


async def _run_referral_stats_from_ledger() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        user = await _add_user(session, 207_001)
        await credit_once(
            session,
            user_id=user.id,
            amount=10,
            tx_type=TYPE_REFERRAL_REWARD,
            reference_id="ref-earn-1",
        )
        await credit_once(
            session,
            user_id=user.id,
            amount=15,
            tx_type=TYPE_REFERRAL_REWARD,
            reference_id="ref-earn-2",
        )
        await session.commit()
        stats = await referral_stats_for_user(session, user)
        assert stats.credits_earned_from_referrals == 25
        assert stats.friends_purchased == 0
    await engine.dispose()


def test_referral_stats_credits_earned_from_ledger() -> None:
    asyncio.run(_run_referral_stats_from_ledger())

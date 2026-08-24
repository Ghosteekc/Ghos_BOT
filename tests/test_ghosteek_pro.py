"""Ghosteek Pro: access guards, Stars activation/renewal and meta gating."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.api.app import create_app
from bot.api.deps import PRO_REQUIRED, get_subscription_info, require_pro, require_pro_linked
from bot.api.routes import battles as battles_route
from bot.api.routes import meta as meta_route
from bot.api.schemas import MetaLadderResponse, SubscriptionInfo
from bot.models.database import Base, ProPayment, Subscription, User
from bot.services.pro.activation import activate_pro_from_payload, activate_pro_trial
from bot.services.pro.entitlement import get_pro_status, is_user_pro, status_from_subscription
from bot.services.pro.plans import PRO_PLANS, TRIAL_DAYS, TRIAL_PLAN_ID, add_calendar_months
from bot.services.pro.reminders import REMINDER_RENEW_2D, REMINDER_TRIAL_LAST

MINUTE = timedelta(minutes=1)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def _make_db(url: str = "sqlite+aiosqlite:///:memory:"):
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _add_user(session: AsyncSession, telegram_id: int, *, linked: bool = True) -> User:
    user = User(telegram_id=telegram_id, player_tag=f"#T{telegram_id}" if linked else None)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def _set_subscription(
    session: AsyncSession,
    user: User,
    *,
    is_active: bool,
    expires_at: datetime | None,
    plan_id: str | None = "pro_1m",
) -> Subscription:
    sub = Subscription(
        user_id=user.id,
        is_active=is_active,
        started_at=_utc_now() - timedelta(days=1),
        expires_at=expires_at,
        plan_id=plan_id,
    )
    session.add(sub)
    await session.commit()
    return sub


def _pro_detail(exc: HTTPException) -> dict:
    assert exc.status_code == 403
    assert isinstance(exc.detail, dict)
    return exc.detail


GUARDED_FEATURES = (
    ("ai_coach", require_pro_linked("ai_coach")),
    ("player_search", require_pro("player_search")),
    ("deck_improve", require_pro_linked("deck_improve")),
)


# --------------------------------------------------------------------------- #
# Guards
# --------------------------------------------------------------------------- #


async def _run_free_user_is_denied() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        user = await _add_user(session, 960_001)
        for feature, guard in GUARDED_FEATURES:
            try:
                await guard(user=user, session=session)
            except HTTPException as exc:
                detail = _pro_detail(exc)
                assert detail["error_code"] == PRO_REQUIRED
                assert detail["code"] == PRO_REQUIRED
                assert detail["feature"] == feature
            else:
                raise AssertionError(f"FREE user passed the {feature} guard")
    await engine.dispose()


async def _run_active_pro_is_allowed() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        user = await _add_user(session, 960_002)
        await _set_subscription(
            session, user, is_active=True, expires_at=_utc_now() + timedelta(days=10)
        )
        for _feature, guard in GUARDED_FEATURES:
            assert await guard(user=user, session=session) is user
    await engine.dispose()


async def _run_expired_pro_is_denied() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        user = await _add_user(session, 960_003)
        await _set_subscription(session, user, is_active=True, expires_at=_utc_now() - MINUTE)
        assert await is_user_pro(session, user) is False

        # Expired rows are lazily deactivated so the DB stays consistent.
        sub = (
            await session.execute(select(Subscription).where(Subscription.user_id == user.id))
        ).scalar_one()
        assert sub.is_active is False

        for _feature, guard in GUARDED_FEATURES:
            try:
                await guard(user=user, session=session)
            except HTTPException as exc:
                assert _pro_detail(exc)["error_code"] == PRO_REQUIRED
            else:
                raise AssertionError("expired Pro passed the guard")
    await engine.dispose()


def test_free_user_gets_pro_required() -> None:
    asyncio.run(_run_free_user_is_denied())


def test_active_pro_passes_guards() -> None:
    asyncio.run(_run_active_pro_is_allowed())


def test_expired_pro_is_denied() -> None:
    asyncio.run(_run_expired_pro_is_denied())


async def _run_admin_env_gets_pro_without_subscription() -> None:
    from unittest.mock import patch

    admin_id = 960_777
    engine, factory = await _make_db()
    async with factory() as session:
        user = await _add_user(session, admin_id)
        with patch("bot.services.pro.entitlement.get_admin_telegram_ids", return_value=[admin_id]):
            status = await get_pro_status(session, user)
            assert status.is_pro is True
            assert status.plan_id == "admin"
            assert status.expires_at is None
            assert await is_user_pro(session, user) is True
            for _feature, guard in GUARDED_FEATURES:
                assert await guard(user=user, session=session) is user
    await engine.dispose()


async def _run_non_admin_still_requires_subscription() -> None:
    from unittest.mock import patch

    engine, factory = await _make_db()
    async with factory() as session:
        user = await _add_user(session, 960_778)
        with patch("bot.services.pro.entitlement.get_admin_telegram_ids", return_value=[111_222_333]):
            assert await is_user_pro(session, user) is False
            try:
                await require_pro("player_search")(user=user, session=session)
            except HTTPException as exc:
                assert _pro_detail(exc)["error_code"] == PRO_REQUIRED
            else:
                raise AssertionError("non-admin passed Pro guard")
    await engine.dispose()


def test_admin_telegram_ids_grant_pro_access() -> None:
    asyncio.run(_run_admin_env_gets_pro_without_subscription())


def test_non_admin_not_granted_pro_by_admin_list() -> None:
    asyncio.run(_run_non_admin_still_requires_subscription())


async def _run_trial_activation() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        user = await _add_user(session, 962_010)
        result = await activate_pro_trial(session, user)
        assert result.activated is True
        assert result.status.is_pro is True
        assert result.status.plan_id == TRIAL_PLAN_ID
        assert result.status.trial_used is True
        assert result.status.expires_at is not None
        assert result.status.days_left is not None
        assert result.status.days_left >= TRIAL_DAYS - 1

        again = await activate_pro_trial(session, user)
        assert again.activated is False
        assert "пробн" in again.message.lower()
    await engine.dispose()


def test_pro_trial_grants_seven_days_once() -> None:
    asyncio.run(_run_trial_activation())


def test_reminder_kinds_are_distinct() -> None:
    assert REMINDER_RENEW_2D != REMINDER_TRIAL_LAST


def test_expiration_boundary_is_not_pro() -> None:
    """expires_at == now already counts as free — no grace second."""
    now = _utc_now()
    sub = Subscription(user_id=1, is_active=True, expires_at=now, plan_id="pro_1m")

    at_boundary = status_from_subscription(sub, now=now)
    assert at_boundary.is_pro is False
    assert at_boundary.expired is True
    assert at_boundary.days_left == 0

    just_before = status_from_subscription(sub, now=now - timedelta(seconds=1))
    assert just_before.is_pro is True
    assert just_before.expired is False


def test_naive_expires_at_is_treated_as_utc() -> None:
    now = _utc_now()
    sub = Subscription(
        user_id=1,
        is_active=True,
        expires_at=(now + timedelta(days=3)).replace(tzinfo=None),
        plan_id="pro_1m",
    )
    assert status_from_subscription(sub, now=now).is_pro is True


# --------------------------------------------------------------------------- #
# Activation / renewal
# --------------------------------------------------------------------------- #


async def _run_purchase_plan(plan_id: str) -> None:
    plan = PRO_PLANS[plan_id]
    engine, factory = await _make_db()
    async with factory() as session:
        user = await _add_user(session, 961_000 + plan.months)
        before = _utc_now()
        result = await activate_pro_from_payload(
            session,
            user,
            plan_id=plan_id,
            payment_charge_id=f"charge-{plan_id}",
            invoice_payload=f"ghosteek_pro:{plan_id}:1:abc",
        )
        assert result.activated is True
        assert result.duplicate is False
        assert result.status.is_pro is True
        assert result.status.plan_id == plan_id

        expected = add_calendar_months(before, plan.months)
        assert result.status.expires_at is not None
        assert abs((result.status.expires_at - expected).total_seconds()) < 60
        assert await is_user_pro(session, user) is True

        payment = (
            await session.execute(
                select(ProPayment).where(
                    ProPayment.telegram_payment_charge_id == f"charge-{plan_id}"
                )
            )
        ).scalar_one()
        assert payment.stars == plan.stars
        assert payment.currency == "XTR"
        assert payment.plan_id == plan_id
    await engine.dispose()


async def _run_renewal_extends() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        user = await _add_user(session, 962_001)
        first = await activate_pro_from_payload(
            session, user, plan_id="pro_1m", payment_charge_id="charge-a"
        )
        first_expires = first.status.expires_at
        assert first_expires is not None

        second = await activate_pro_from_payload(
            session, user, plan_id="pro_3m", payment_charge_id="charge-b"
        )
        assert second.activated is True
        assert second.status.expires_at is not None
        assert second.status.expires_at > first_expires
        assert second.status.expires_at == add_calendar_months(first_expires, 3)
        assert second.status.plan_id == "pro_3m"
    await engine.dispose()


async def _run_duplicate_charge_does_not_extend() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        user = await _add_user(session, 962_002)
        first = await activate_pro_from_payload(
            session, user, plan_id="pro_1m", payment_charge_id="charge-dup"
        )
        expires = first.status.expires_at

        replay = await activate_pro_from_payload(
            session, user, plan_id="pro_1m", payment_charge_id="charge-dup"
        )
        assert replay.duplicate is True
        assert replay.activated is False
        assert replay.status.expires_at == expires

        payments = (
            await session.execute(
                select(ProPayment).where(ProPayment.telegram_payment_charge_id == "charge-dup")
            )
        ).scalars().all()
        assert len(payments) == 1
    await engine.dispose()


async def _run_survives_restart(db_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    engine, factory = await _make_db(url)
    async with factory() as session:
        user = await _add_user(session, 963_001)
        activated = await activate_pro_from_payload(
            session, user, plan_id="pro_6m", payment_charge_id="charge-restart"
        )
        expires = activated.status.expires_at
        telegram_id = user.telegram_id
    await engine.dispose()

    # A fresh engine stands in for a process restart: entitlement is re-read from DB.
    engine2 = create_async_engine(url)
    factory2 = async_sessionmaker(engine2, class_=AsyncSession, expire_on_commit=False)
    async with factory2() as session:
        reloaded = (
            await session.execute(select(User).where(User.telegram_id == telegram_id))
        ).scalar_one()
        assert await is_user_pro(session, reloaded) is True
        sub = (
            await session.execute(select(Subscription).where(Subscription.user_id == reloaded.id))
        ).scalar_one()
        assert sub.plan_id == "pro_6m"
        assert sub.expires_at is not None
        assert expires is not None
        stored = sub.expires_at
        if stored.tzinfo is None:
            stored = stored.replace(tzinfo=timezone.utc)
        assert abs((stored - expires).total_seconds()) < 1
    await engine2.dispose()


def test_purchase_one_month() -> None:
    asyncio.run(_run_purchase_plan("pro_1m"))


def test_purchase_three_months() -> None:
    asyncio.run(_run_purchase_plan("pro_3m"))


def test_purchase_six_months() -> None:
    asyncio.run(_run_purchase_plan("pro_6m"))


def test_renewal_extends_expiration() -> None:
    asyncio.run(_run_renewal_extends())


def test_duplicate_payment_does_not_double_extend() -> None:
    asyncio.run(_run_duplicate_charge_does_not_extend())


def test_pro_survives_restart(tmp_path: Path) -> None:
    asyncio.run(_run_survives_restart(tmp_path / "pro_restart.db"))


# --------------------------------------------------------------------------- #
# Meta gating
# --------------------------------------------------------------------------- #


def _meta_deck(rank: int) -> dict:
    return {
        "rank": rank,
        "deck_hash": f"deck-{rank}",
        "cards": [
            {
                "id": f"card-{rank}-{slot}",
                "name": f"Card {slot}",
                "icon": "",
                "cost": 3,
                "slot": slot,
            }
            for slot in range(8)
        ],
        "games_count": 100 - rank,
        "wins": 50,
        "losses": 50 - rank,
        "win_rate": 55.0,
        "unique_players": 10,
    }


def _meta_payload(total: int) -> dict:
    return {
        "mode": "league",
        "status": "ok",
        "message": None,
        "sample_note": "note",
        "updated_at": None,
        "min_games": 5,
        "decks": [_meta_deck(i + 1) for i in range(total)],
    }


def test_meta_free_shows_five_pro_shows_all() -> None:
    assert meta_route.FREE_META_DECK_LIMIT == 5

    free = MetaLadderResponse(**meta_route._apply_pro_limit(_meta_payload(12), is_pro=False))
    assert len(free.decks) == 5
    assert [d.rank for d in free.decks] == [1, 2, 3, 4, 5]
    assert free.is_pro is False
    assert free.total_decks == 12
    assert free.pro_locked_count == 7

    pro = MetaLadderResponse(**meta_route._apply_pro_limit(_meta_payload(12), is_pro=True))
    assert len(pro.decks) == 12
    assert pro.is_pro is True
    assert pro.pro_locked_count == 0
    assert pro.total_decks == 12

    # Fewer decks than the free limit must not report phantom locked decks.
    short = MetaLadderResponse(**meta_route._apply_pro_limit(_meta_payload(3), is_pro=False))
    assert len(short.decks) == 3
    assert short.pro_locked_count == 0


async def _run_meta_route_free_vs_pro() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        free_user = await _add_user(session, 964_001)
        pro_user = await _add_user(session, 964_002)
        await _set_subscription(
            session, pro_user, is_active=True, expires_at=_utc_now() + timedelta(days=30)
        )

        original_ladder = meta_route.get_ladder_meta
        original_cards = meta_route.ensure_cards_loaded

        async def fake_ladder(mode: str) -> dict:
            return {**_meta_payload(9), "mode": mode}

        async def fake_cards() -> None:
            return None

        meta_route.get_ladder_meta = fake_ladder
        meta_route.ensure_cards_loaded = fake_cards
        try:
            free_body = await meta_route.meta_league(user=free_user, session=session)
            pro_body = await meta_route.meta_league(user=pro_user, session=session)
        finally:
            meta_route.get_ladder_meta = original_ladder
            meta_route.ensure_cards_loaded = original_cards

        assert len(free_body.decks) == 5
        assert free_body.pro_locked_count == 4
        assert free_body.is_pro is False

        assert len(pro_body.decks) == 9
        assert pro_body.pro_locked_count == 0
        assert pro_body.is_pro is True
    await engine.dispose()


def test_meta_league_route_gates_free_users() -> None:
    asyncio.run(_run_meta_route_free_vs_pro())


# --------------------------------------------------------------------------- #
# Battle detail gating
# --------------------------------------------------------------------------- #

_PRO_ONLY_BATTLE_FIELDS = (
    "tactical_matchup",
    "user_elixir",
    "opponent_elixir",
    "match_difficulty",
    "match_plan",
    "battle_coach",
)

_FREE_BATTLE_FIELDS = (
    "index",
    "won",
    "opponent_name",
    "opponent_tag",
    "trophy_change",
    "duration",
    "played_at",
    "crown_score",
    "user_deck",
    "opponent_deck",
    "user_stats",
    "opponent_stats",
)


def _sample_battle() -> dict:
    def _cards(names: list[str]) -> list[dict]:
        return [{"name": name, "level": 14, "maxLevel": 14, "elixirCost": 3} for name in names]

    return {
        "type": "PvP",
        "battleTime": "20260824T120000.000Z",
        "gameDuration": 180,
        "team": [
            {
                "tag": "#ABC123",
                "name": "Me",
                "crowns": 2,
                "trophyChange": 30,
                "startingTrophies": 6000,
                "cards": _cards([
                    "Hog Rider", "Musketeer", "Cannon", "Ice Spirit",
                    "Skeletons", "Fireball", "The Log", "Ice Golem",
                ]),
            }
        ],
        "opponent": [
            {
                "tag": "#XYZ789",
                "name": "Rival",
                "crowns": 1,
                "trophyChange": -30,
                "startingTrophies": 6000,
                "cards": _cards([
                    "Golem", "Baby Dragon", "Mega Minion", "Lightning",
                    "Tornado", "Elixir Collector", "Barbarian Hut", "Lumberjack",
                ]),
            }
        ],
    }


def test_battle_detail_strips_pro_fields_for_free_users() -> None:
    detail = battles_route._build_battle_detail(0, _sample_battle())
    assert detail.detailed_unlocked is True
    assert detail.pro_required is False

    free = battles_route._strip_pro_details(
        battles_route._build_battle_detail(0, _sample_battle())
    )
    assert free.detailed_unlocked is False
    assert free.pro_required is True
    for field in _PRO_ONLY_BATTLE_FIELDS:
        assert getattr(free, field) is None, f"{field} must be hidden from FREE users"
    assert free.reasons == []
    assert free.opponent_threats == []
    assert free.user_key_cards == []
    assert free.opponent_key_cards == []
    assert free.low_impact_cards == []

    for field in _FREE_BATTLE_FIELDS:
        assert getattr(free, field) == getattr(detail, field), f"{field} must stay free"


# --------------------------------------------------------------------------- #
# Profile mapping + route wiring
# --------------------------------------------------------------------------- #


async def _run_subscription_info_maps_to_schema() -> None:
    engine, factory = await _make_db()
    async with factory() as session:
        user = await _add_user(session, 965_001)
        free = SubscriptionInfo(**await get_subscription_info(user, session))
        assert free.active is False
        assert free.is_pro is False
        assert free.expires_at is None
        assert free.plan_id is None

        await activate_pro_from_payload(
            session, user, plan_id="pro_3m", payment_charge_id="charge-profile"
        )
        info = await get_subscription_info(user, session)
        # Every key returned by get_subscription_info must be accepted by the schema.
        mapped = SubscriptionInfo(**info)
        assert mapped.active is True
        assert mapped.is_pro is True
        assert mapped.plan_id == "pro_3m"
        assert mapped.expires_at is not None
        assert mapped.started_at is not None
        assert mapped.days_left is not None and mapped.days_left > 0
        assert mapped.expired is False
    await engine.dispose()


def test_subscription_info_matches_profile_schema() -> None:
    asyncio.run(_run_subscription_info_maps_to_schema())


def _iter_api_routes(app):
    """Included routers are nested in newer FastAPI versions — walk them."""
    pending = list(app.routes)
    seen: set[int] = set()
    while pending:
        route = pending.pop()
        if id(route) in seen:
            continue
        seen.add(id(route))
        original = getattr(route, "original_router", None)
        if original is not None:
            pending.extend(getattr(original, "routes", []) or [])
        pending.extend(getattr(route, "routes", []) or [])
        if getattr(route, "dependant", None) is not None:
            yield route


def _dependency_qualnames(app, path: str, method: str) -> set[str]:
    for route in _iter_api_routes(app):
        if getattr(route, "path", None) != path:
            continue
        if method not in (getattr(route, "methods", None) or set()):
            continue
        names: set[str] = set()
        stack = [route.dependant]
        while stack:
            dep = stack.pop()
            call = getattr(dep, "call", None)
            if call is not None:
                names.add(getattr(call, "__qualname__", ""))
            stack.extend(dep.dependencies)
        return names
    raise AssertionError(f"route not found: {method} {path}")


PRO_GUARD_QUALNAMES = {"require_pro.<locals>._dep", "require_pro_linked.<locals>._dep"}


def test_routes_are_wired_to_the_expected_guards() -> None:
    app = create_app()

    for method, path in (
        ("POST", "/api/ai/ask"),
        ("GET", "/api/search"),
        ("POST", "/api/decks/recommend"),
    ):
        names = _dependency_qualnames(app, path, method)
        assert names & PRO_GUARD_QUALNAMES, f"{method} {path} is not Pro-gated"

    # FREE users keep the battle list and the basic battle card.
    for method, path in (
        ("GET", "/api/battles"),
        ("GET", "/api/battles/{index}"),
        ("GET", "/api/players/{tag}"),
        ("GET", "/api/meta/league"),
        ("GET", "/api/meta/clan-wars"),
    ):
        names = _dependency_qualnames(app, path, method)
        assert "require_linked_player" in names, f"{method} {path} lost the link guard"
        assert not (names & PRO_GUARD_QUALNAMES), f"{method} {path} must stay open to FREE users"


if __name__ == "__main__":
    test_free_user_gets_pro_required()
    test_active_pro_passes_guards()
    test_expired_pro_is_denied()
    test_expiration_boundary_is_not_pro()
    test_purchase_one_month()
    test_renewal_extends_expiration()
    test_duplicate_payment_does_not_double_extend()
    test_meta_free_shows_five_pro_shows_all()
    print("OK")

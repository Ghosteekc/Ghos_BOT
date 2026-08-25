"""Ghosteek Pro HTTP API: status + Telegram Stars invoice link."""

from __future__ import annotations

import logging
import secrets
from typing import Any

from aiogram import Bot
from aiogram.types import LabeledPrice
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from bot.api.deps import get_current_user, get_db
from bot.models.database import User
from bot.services.pro.activation import activate_pro_trial
from bot.services.pro.entitlement import get_pro_status
from bot.services.pro.plans import TRIAL_DAYS, TRIAL_PLAN_ID, build_invoice_payload, get_plan, list_plans
from bot.services.referral.service import get_invitee_discount, resolve_plan_stars
from bot.user_errors import http_error

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pro", tags=["pro"])


class ProPlanOut(BaseModel):
    id: str
    title: str
    description: str
    stars: int
    months: int
    badge: str | None = None
    original_stars: int | None = None


class ProStatusOut(BaseModel):
    is_pro: bool
    started_at: str | None = None
    expires_at: str | None = None
    days_left: int | None = None
    plan_id: str | None = None
    trial_used: bool = False
    trial_available: bool = False
    trial_days: int = TRIAL_DAYS
    is_trial: bool = False
    expired: bool = False
    plans: list[ProPlanOut] = Field(default_factory=list)
    referral_discount_active: bool = False
    referral_discount_expires_at: str | None = None


class ProTrialOut(BaseModel):
    ok: bool = True
    activated: bool
    message: str
    is_pro: bool
    expires_at: str | None = None
    days_left: int | None = None
    plan_id: str | None = None
    trial_used: bool = True
    is_trial: bool = False


class CreateInvoiceIn(BaseModel):
    plan_id: str


class CreateInvoiceOut(BaseModel):
    ok: bool = True
    plan_id: str
    stars: int
    invoice_link: str


def _bot_from_request(request: Request) -> Bot:
    bot = getattr(request.app.state, "bot", None)
    if bot is None:
        raise http_error("E099", status=503, message="Платежный бот временно недоступен.")
    return bot


@router.get("/status", response_model=ProStatusOut)
async def pro_status(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ProStatusOut:
    status = await get_pro_status(session, user)
    discount = await get_invitee_discount(session, user)
    plans = [
        ProPlanOut(
            id=p.id,
            title=p.title,
            description=p.description,
            stars=discount.prices.get(p.id, p.stars) if discount.active else p.stars,
            months=p.months,
            badge=p.badge,
            original_stars=p.stars if discount.active else None,
        )
        for p in list_plans()
    ]
    payload = status.to_dict()
    is_trial = bool(status.is_pro and status.plan_id == TRIAL_PLAN_ID)
    return ProStatusOut(
        is_pro=bool(payload["is_pro"]),
        started_at=payload.get("started_at"),
        expires_at=payload.get("expires_at"),
        days_left=payload.get("days_left"),
        plan_id=payload.get("plan_id"),
        trial_used=bool(payload.get("trial_used")),
        trial_available=not bool(payload["is_pro"]) and not bool(payload.get("trial_used")),
        trial_days=TRIAL_DAYS,
        is_trial=is_trial,
        expired=bool(payload.get("expired")),
        plans=plans,
        referral_discount_active=discount.active,
        referral_discount_expires_at=(
            discount.expires_at.isoformat() if discount.expires_at and discount.active else None
        ),
    )


@router.post("/trial", response_model=ProTrialOut)
async def start_pro_trial(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ProTrialOut:
    result = await activate_pro_trial(session, user)
    status = result.status
    return ProTrialOut(
        activated=result.activated,
        message=result.message,
        is_pro=status.is_pro,
        expires_at=status.expires_at.isoformat() if status.expires_at else None,
        days_left=status.days_left,
        plan_id=status.plan_id,
        trial_used=status.trial_used,
        is_trial=status.is_pro and status.plan_id == TRIAL_PLAN_ID,
    )


@router.post("/invoice", response_model=CreateInvoiceOut)
async def create_pro_invoice(
    body: CreateInvoiceIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> CreateInvoiceOut:
    plan = get_plan(body.plan_id)
    if plan is None:
        raise http_error("E001", status=400, message="Неизвестный тариф Ghosteek Pro.")

    stars = await resolve_plan_stars(session, user, plan.id)
    if stars is None:
        raise http_error("E001", status=400, message="Неизвестный тариф Ghosteek Pro.")

    bot = _bot_from_request(request)
    nonce = secrets.token_hex(8)
    payload = build_invoice_payload(
        plan_id=plan.id,
        telegram_id=user.telegram_id,
        nonce=nonce,
    )
    try:
        link = await bot.create_invoice_link(
            title="Ghosteek Pro",
            description=plan.description,
            payload=payload,
            currency="XTR",
            prices=[LabeledPrice(label=plan.title, amount=stars)],
        )
    except Exception as exc:
        logger.exception("Failed to create Stars invoice for user=%s", user.telegram_id)
        raise http_error(
            "E099",
            status=502,
            message="Не удалось создать счёт Telegram Stars. Попробуйте позже.",
        ) from exc

    return CreateInvoiceOut(plan_id=plan.id, stars=stars, invoice_link=str(link))

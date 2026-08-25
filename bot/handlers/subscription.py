"""Ghosteek Pro — Telegram Stars (XTR) payment handlers."""

from __future__ import annotations

import logging
import secrets

from aiogram import F, Router
from aiogram.types import LabeledPrice, Message, PreCheckoutQuery

from bot.models.database import async_session
from bot.services.clash_api import SubscriptionService
from bot.services.pro.activation import activate_pro_from_payload
from bot.services.pro.plans import (
    build_invoice_payload,
    get_plan,
    parse_invoice_payload,
)
from bot.services.referral.service import quote_plan_purchase

logger = logging.getLogger(__name__)

router = Router(name="ghosteek_pro")


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery) -> None:
    parsed = parse_invoice_payload(query.invoice_payload or "")
    if parsed is None:
        logger.warning("Rejecting pre-checkout: unknown payload=%s", query.invoice_payload)
        await query.answer(ok=False, error_message="Неизвестный тариф Ghosteek Pro.")
        return

    plan_id, telegram_id, credits_used = parsed
    plan = get_plan(plan_id)
    if plan is None:
        await query.answer(ok=False, error_message="Тариф недоступен.")
        return

    if query.from_user and query.from_user.id != telegram_id:
        await query.answer(ok=False, error_message="Счёт выписан другому пользователю.")
        return

    if query.currency != "XTR":
        await query.answer(ok=False, error_message="Поддерживается только оплата Stars.")
        return

    amount = int(query.total_amount or 0)
    async with async_session() as session:
        sub_service = SubscriptionService(session)
        user = await sub_service.get_or_create_user(telegram_id)
        quote = await quote_plan_purchase(session, user, plan.id)
        if quote is None:
            await query.answer(ok=False, error_message="Тариф недоступен.")
            return
        # Accept the invoice amount if it matches a valid quote for this user.
        # Credits in payload must not exceed what the quote allows.
        claimed = max(0, int(credits_used))
        if claimed > quote.max_credits or claimed > quote.available_credits:
            logger.warning(
                "Pre-checkout credits claim too high: claimed=%s max=%s bal=%s",
                claimed,
                quote.max_credits,
                quote.available_credits,
            )
            await query.answer(ok=False, error_message="Некорректная сумма счёта.")
            return
        expected_stars = quote.final_price - claimed
        if expected_stars < 1:
            await query.answer(ok=False, error_message="Некорректная сумма счёта.")
            return
        allowed = {expected_stars, quote.stars_to_pay, plan.stars, quote.final_price}

    if amount not in allowed:
        logger.warning(
            "Pre-checkout amount mismatch: got=%s allowed=%s plan=%s",
            amount,
            sorted(allowed),
            plan.id,
        )
        await query.answer(ok=False, error_message="Некорректная сумма счёта.")
        return

    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message) -> None:
    payment = message.successful_payment
    if payment is None or message.from_user is None:
        return

    payload = payment.invoice_payload or ""
    parsed = parse_invoice_payload(payload)
    if parsed is None:
        logger.warning("Successful payment with non-Pro payload=%s — ignored", payload)
        return

    plan_id, telegram_id, credits_used = parsed
    if message.from_user.id != telegram_id:
        logger.error(
            "Payment user mismatch: from=%s payload_tg=%s charge=%s",
            message.from_user.id,
            telegram_id,
            payment.telegram_payment_charge_id,
        )
        await message.answer(
            "Оплата получена, но не удалось привязать подписку. Напишите в поддержку."
        )
        return

    charge_id = payment.telegram_payment_charge_id
    async with async_session() as session:
        sub_service = SubscriptionService(session)
        user = await sub_service.get_or_create_user(message.from_user.id)
        try:
            result = await activate_pro_from_payload(
                session,
                user,
                plan_id=plan_id,
                payment_charge_id=charge_id,
                provider_payment_charge_id=payment.provider_payment_charge_id,
                currency=payment.currency or "XTR",
                amount_stars=int(payment.total_amount or 0),
                invoice_payload=payload,
                credits_used=credits_used,
            )
        except Exception:
            logger.exception("Failed to activate Pro after payment charge=%s", charge_id)
            await message.answer(
                "Оплата прошла, но активация Ghosteek Pro не удалась. "
                "Напишите в поддержку и укажите ID платежа."
            )
            return

    plan = get_plan(plan_id)
    if result.duplicate:
        await message.answer("Этот платёж уже учтён. Ghosteek Pro активен.")
        return

    expires = result.status.expires_at
    expires_txt = expires.strftime("%d.%m.%Y") if expires else "без срока"
    title = plan.title if plan else plan_id
    await message.answer(
        f"✅ Ghosteek Pro активирован ({title}).\n"
        f"Действует до {expires_txt}.\n\n"
        "Откройте Mini App — премиум-функции уже доступны."
    )


@router.message(F.text == "/pro")
async def cmd_pro(message: Message) -> None:
    """Quick Stars invoice for 1 month (chat fallback — full catalog price)."""
    plan = get_plan("pro_1m")
    if plan is None or message.from_user is None:
        return
    payload = build_invoice_payload(
        plan_id=plan.id,
        telegram_id=message.from_user.id,
        nonce=secrets.token_hex(6),
        credits_used=0,
    )
    await message.answer_invoice(
        title="Ghosteek Pro",
        description=plan.description,
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(label=plan.title, amount=plan.stars)],
    )

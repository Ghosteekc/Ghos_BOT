import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from bot.config import settings
from bot.models.database import async_session
from bot.services.clash_api import SubscriptionService

logger = logging.getLogger(__name__)

router = Router()


@router.callback_query(F.data == "sub_trial")
async def activate_trial(callback: CallbackQuery) -> None:
    logger.info(f"User {callback.from_user.id} activated trial")
    async with async_session() as session:
        sub_service = SubscriptionService(session)
        user = await sub_service.get_or_create_user(callback.from_user.id)
        success, msg = await sub_service.activate_trial(user)

    if success:
        logger.info(f"Trial activated successfully for user {callback.from_user.id}")
        await callback.message.edit_text(f"🎉 {msg}\n\nВсе функции анализа теперь доступны!")
    else:
        logger.warning(f"Failed to activate trial for user {callback.from_user.id}: {msg}")
        await callback.message.edit_text(f"❌ {msg}")
    await callback.answer()


@router.callback_query(F.data == "sub_pay")
async def pay_subscription(callback: CallbackQuery) -> None:
    logger.info(f"User {callback.from_user.id} initiated payment")
    await callback.message.answer_invoice(
        title="Ghosteek CR Assistant — Подписка",
        description="30 дней полного доступа ко всем функциям анализа колод и боёв",
        payload="cr_sub_30d",
        currency="XTR",
        prices=[LabeledPrice(label="Подписка 30 дней", amount=settings.subscription_price_stars)],
    )
    await callback.answer()


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery) -> None:
    logger.info(f"Pre-checkout query from user {query.from_user.id}")
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message) -> None:
    payment_info = message.successful_payment
    logger.info(
        f"Successful payment from user {message.from_user.id}: "
        f"amount={payment_info.total_amount}, currency={payment_info.currency}, "
        f"payload={payment_info.invoice_payload}"
    )
    async with async_session() as session:
        sub_service = SubscriptionService(session)
        user = await sub_service.get_or_create_user(message.from_user.id)
        await sub_service.activate_subscription(user, days=30)

    await message.answer(
        "🎉 Спасибо за оплату!\n"
        "Подписка активирована на 30 дней. Все функции доступны!"
    )

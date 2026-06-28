from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

from bot.models.database import async_session
from bot.services.clash_api import SubscriptionService


class SubscriptionMiddleware(BaseMiddleware):
    """Inject user into handlers that need it (legacy callbacks)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        telegram_id: int | None = None
        if isinstance(event, CallbackQuery):
            telegram_id = event.from_user.id

        if telegram_id is not None:
            async with async_session() as session:
                sub_service = SubscriptionService(session)
                user = await sub_service.get_or_create_user(telegram_id)
                data["user"] = user
                data["sub_service"] = sub_service

        return await handler(event, data)

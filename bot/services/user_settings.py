"""Persisted Mini App user preferences."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.api.schemas import SettingsResponse, SettingsUpdateRequest
from bot.models.database import UserSettings


def settings_to_response(row: UserSettings) -> SettingsResponse:
    return SettingsResponse(
        theme=row.theme,  # type: ignore[arg-type]
        language=row.language,  # type: ignore[arg-type]
        notifications=row.notifications,
        telegram_notifications=row.telegram_notifications,
        haptic_enabled=row.haptic_enabled,
    )


async def get_or_create_user_settings(
    session: AsyncSession,
    user_id: int,
    *,
    commit_on_create: bool = True,
) -> UserSettings:
    result = await session.execute(select(UserSettings).where(UserSettings.user_id == user_id))
    row = result.scalar_one_or_none()
    if row is not None:
        return row

    row = UserSettings(user_id=user_id)
    session.add(row)
    await session.flush()
    if commit_on_create:
        await session.commit()
        await session.refresh(row)
    return row


async def load_settings_response(session: AsyncSession, user_id: int) -> SettingsResponse:
    row = await get_or_create_user_settings(session, user_id)
    return settings_to_response(row)


async def update_user_settings(
    session: AsyncSession,
    user_id: int,
    payload: SettingsUpdateRequest,
) -> SettingsResponse:
    row = await get_or_create_user_settings(session, user_id, commit_on_create=False)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(row, key, value)
    await session.commit()
    await session.refresh(row)
    return settings_to_response(row)

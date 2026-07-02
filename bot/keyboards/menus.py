from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from bot.config import settings


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="💎 Подписка")],
            [KeyboardButton(text="💬 Поддержка")],
        ],
        resize_keyboard=True,
    )


def subscription_keyboard(trial_available: bool, price_stars: int) -> InlineKeyboardMarkup:
    buttons = []
    if trial_available:
        buttons.append([
            InlineKeyboardButton(
                text=f"🎁 Пробный период ({settings.trial_days} дн.)",
                callback_data="sub_trial",
            )
        ])
    buttons.append([
        InlineKeyboardButton(
            text=f"💎 Подписка — {price_stars} ⭐",
            callback_data="sub_pay",
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

PROFILE_BUTTON = "👤 Профиль"
REGISTRATION_BUTTON = "📝 Регистрация"
SUPPORT_BUTTON = "💬 Поддержка"
LEGACY_SUBSCRIPTION_BUTTON = "💎 Подписка"

MENU_BUTTONS = frozenset(
    {
        PROFILE_BUTTON,
        REGISTRATION_BUTTON,
        SUPPORT_BUTTON,
        LEGACY_SUBSCRIPTION_BUTTON,
    }
)


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=PROFILE_BUTTON), KeyboardButton(text=REGISTRATION_BUTTON)],
            [KeyboardButton(text=SUPPORT_BUTTON)],
        ],
        resize_keyboard=True,
    )

from aiogram.types import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from bot.config import settings

PROFILE_BUTTON = "👤 Профиль"
REGISTRATION_BUTTON = "📝 Регистрация"
SUPPORT_BUTTON = "💬 Поддержка"
OPEN_APP_BUTTON = "📱 Открыть приложение"
LEGACY_SUBSCRIPTION_BUTTON = "💎 Подписка"

MENU_BUTTONS = frozenset(
    {
        PROFILE_BUTTON,
        REGISTRATION_BUTTON,
        SUPPORT_BUTTON,
        OPEN_APP_BUTTON,
        LEGACY_SUBSCRIPTION_BUTTON,
    }
)


def _webapp_info() -> WebAppInfo | None:
    """Native Mini App launch URL — never use as plain url= button."""
    webapp = (settings.webapp_url or "").strip().rstrip("/")
    if not webapp or "your-domain" in webapp:
        return None
    if not webapp.startswith("https://"):
        return None
    return WebAppInfo(url=webapp)


def main_menu() -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = []
    info = _webapp_info()
    if info is not None:
        # Reply keyboard web_app = Telegram Mini App launch (не url-кнопка).
        rows.append([KeyboardButton(text=OPEN_APP_BUTTON, web_app=info)])
    rows.append(
        [KeyboardButton(text=PROFILE_BUTTON), KeyboardButton(text=REGISTRATION_BUTTON)],
    )
    rows.append([KeyboardButton(text=SUPPORT_BUTTON)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

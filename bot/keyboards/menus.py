from aiogram.types import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from bot.config import settings

PROFILE_BUTTON = "👤 Профиль"
REGISTRATION_BUTTON = "📝 Регистрация"
SUPPORT_BUTTON = "💬 Поддержка"
GHOSTEEK_AI_BUTTON = "⚡Ghosteek AI"
OPEN_APP_BUTTON = "📱 Открыть приложение"
LEGACY_SUBSCRIPTION_BUTTON = "💎 Подписка"

MENU_BUTTONS = frozenset(
    {
        PROFILE_BUTTON,
        REGISTRATION_BUTTON,
        SUPPORT_BUTTON,
        GHOSTEEK_AI_BUTTON,
        OPEN_APP_BUTTON,
        LEGACY_SUBSCRIPTION_BUTTON,
    }
)


def _webapp_info(path: str = "") -> WebAppInfo | None:
    """Native Mini App launch URL — never use as plain url= button."""
    webapp = (settings.webapp_url or "").strip().rstrip("/")
    if not webapp or "your-domain" in webapp:
        return None
    if not webapp.startswith("https://"):
        return None
    suffix = path if not path or path.startswith("/") else f"/{path}"
    return WebAppInfo(url=f"{webapp}{suffix}")


def main_menu() -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = [
        [KeyboardButton(text=PROFILE_BUTTON), KeyboardButton(text=REGISTRATION_BUTTON)],
    ]
    ai_info = _webapp_info("/ai")
    if ai_info is not None:
        rows.append(
            [
                KeyboardButton(text=SUPPORT_BUTTON),
                KeyboardButton(text=GHOSTEEK_AI_BUTTON, web_app=ai_info),
            ]
        )
    else:
        rows.append([KeyboardButton(text=SUPPORT_BUTTON)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

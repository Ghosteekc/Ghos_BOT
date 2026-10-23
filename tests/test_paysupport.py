"""Payment support command reuses the existing Telegram support channel."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from bot.handlers import support


class PaymentSupportTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_configured_support_link(self) -> None:
        message = AsyncMock()
        with patch.object(support.settings, "support_username", "@ghosteek_support"):
            await support.cmd_paysupport(message)

        self.assertEqual(message.answer.await_count, 2)
        intro = message.answer.await_args_list[0].args[0]
        contact = message.answer.await_args_list[1].args[0]
        self.assertIn("ошибочно", intro)
        self.assertIn("подписка не появилась", intro)
        self.assertIn("возврат Stars", intro)
        self.assertIn("https://t.me/ghosteek_support", contact)
        self.assertIn("Платёжные данные", intro)

    async def test_does_not_promise_unavailable_forwarding(self) -> None:
        message = AsyncMock()
        with (
            patch.object(support.settings, "support_username", None),
            patch.object(support.settings, "admin_telegram_id", 123456),
        ):
            await support.cmd_paysupport(message)

        self.assertEqual(message.answer.await_count, 2)
        contact = message.answer.await_args_list[1].args[0]
        self.assertIn("не настроен", contact)
        self.assertNotIn("передадим", contact)
        self.assertNotIn("123456", contact)

    def test_command_is_registered_in_support_router(self) -> None:
        self.assertTrue(any(
            handler.callback is support.cmd_paysupport
            for handler in support.router.message.handlers
        ))


if __name__ == "__main__":
    unittest.main()

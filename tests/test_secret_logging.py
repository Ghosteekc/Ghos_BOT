"""Regression checks for credentials in application logs."""

from __future__ import annotations

import io
import logging
import sys
import unittest
from contextlib import redirect_stderr
from types import SimpleNamespace

from bot.secret_logging import install_secret_redaction


class SecretLoggingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.previous_factory = logging.getLogRecordFactory()
        cls.previous_excepthook = sys.excepthook
        cls.database_url = "postgresql+asyncpg://ghost:db%40pass@db.example/test"
        cls.bot_token = "123456:fake-telegram-token"
        cls.api_key = "fake-clash-api-key"
        cls.proxy_secret = "fake-proxy-secret"
        cls.llm_key = "fake-llm-api-key"
        cls.url_key = "fake-key-in-url"
        install_secret_redaction(SimpleNamespace(
            database_url=cls.database_url,
            bot_token=cls.bot_token,
            clash_royale_api_key=cls.api_key,
            clash_royale_proxy_secret=cls.proxy_secret,
            llm_api_key=cls.llm_key,
            llm_base_url=f"https://llm.example/v1?api_key={cls.url_key}",
        ))

    @classmethod
    def tearDownClass(cls) -> None:
        logging.setLogRecordFactory(cls.previous_factory)
        sys.excepthook = cls.previous_excepthook

    def setUp(self) -> None:
        self.output = io.StringIO()
        self.handler = logging.StreamHandler(self.output)
        self.handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        self.logger = logging.getLogger(f"test.secret_logging.{self._testMethodName}")
        self.logger.addHandler(self.handler)
        self.logger.propagate = False
        self.logger.setLevel(logging.DEBUG)

    def tearDown(self) -> None:
        self.logger.removeHandler(self.handler)
        self.handler.close()

    def test_configured_secrets_and_encoded_password_are_redacted(self) -> None:
        self.logger.debug(
            "DB %s; password %s; decoded %s; bot %s; api %s; proxy %s; llm %s; url %s",
            self.database_url,
            "db%40pass",
            "db@pass",
            self.bot_token,
            self.api_key,
            self.proxy_secret,
            self.llm_key,
            self.url_key,
        )
        log = self.output.getvalue()
        for secret in (
            self.database_url, "db%40pass", "db@pass", self.bot_token,
            self.api_key, self.proxy_secret, self.llm_key, self.url_key,
        ):
            self.assertNotIn(secret, log)
        self.assertIn("DB [REDACTED]", log)
        self.assertIn("DEBUG", log)

    def test_exception_traceback_preserves_diagnostics_without_credentials(self) -> None:
        try:
            raise RuntimeError(f"connection failed: {self.database_url} ({self.bot_token})")
        except RuntimeError:
            self.logger.exception("Database initialization failed")

        log = self.output.getvalue()
        self.assertIn("Database initialization failed", log)
        self.assertIn("RuntimeError: connection failed", log)
        self.assertIn("test_exception_traceback_preserves_diagnostics", log)
        self.assertNotIn(self.database_url, log)
        self.assertNotIn("db@pass", log)
        self.assertNotIn(self.bot_token, log)

    def test_dynamic_invite_and_invoice_payload_are_redacted(self) -> None:
        invite = "beta_0123456789abcdef"
        invoice = "ghosteek_pro:pro_1m:123:nonce:0"
        self.logger.warning("Invalid invite %s and invoice %s", invite, invoice)
        log = self.output.getvalue()
        self.assertNotIn(invite, log)
        self.assertNotIn(invoice, log)
        self.assertIn("beta_[REDACTED]", log)
        self.assertIn("ghosteek_pro:[REDACTED]", log)

    def test_formatter_can_still_use_structured_log_arguments(self) -> None:
        class AccessLikeFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                method, path, status = record.args
                self_test.assertEqual((method, status), ("GET", 200))
                self_test.assertNotIn(self_test.url_key, path)
                record.msg = "%s %s %s"
                return super().format(record)

        self_test = self
        self.handler.setFormatter(AccessLikeFormatter("%(message)s"))
        self.logger.info("%s %s %s", "GET", f"/api?api_key={self.url_key}", 200)
        log = self.output.getvalue()
        self.assertIn("GET /api?api_key=[REDACTED] 200", log)
        self.assertNotIn(self.url_key, log)

    def test_uncaught_traceback_is_redacted(self) -> None:
        output = io.StringIO()
        try:
            raise RuntimeError(f"could not connect to {self.database_url}")
        except RuntimeError:
            with redirect_stderr(output):
                sys.excepthook(*sys.exc_info())

        text = output.getvalue()
        self.assertIn("RuntimeError: could not connect", text)
        self.assertIn("test_uncaught_traceback_is_redacted", text)
        self.assertNotIn(self.database_url, text)
        self.assertNotIn("db%40pass", text)

    def test_personal_identifiers_not_payment_diagnostics(self) -> None:
        self.logger.warning(
            "Payment user mismatch user_id=%s payload_tg=%s username=%s tag=%s amount=%s status=%s",
            12, 987654321, "fixture_person", "ABC123", 100, 403,
        )
        self.logger.info("User %s linked #P0YQ88 @fixture_person", 987654321)
        text = self.output.getvalue()
        for value in ("user_id=12", "987654321", "fixture_person", "ABC123", "P0YQ88"):
            self.assertNotIn(value, text)
        self.assertIn("Payment user mismatch", text)
        self.assertIn("amount=100 status=403", text)

    def test_traceback_hides_identifiers_and_database_conflict_values(self) -> None:
        detail = "Key (telegram_id)=(987654321) already exists"
        try:
            raise ValueError(detail + " player_tag=#P0YQ88 username=fixture_person")
        except ValueError:
            self.logger.exception("Integrity conflict")
        text = self.output.getvalue()
        self.assertIn("ValueError", text)
        self.assertIn("Key (telegram_id)=([REDACTED]) already exists", text)
        for value in ("987654321", "P0YQ88", "fixture_person"):
            self.assertNotIn(value, text)

    def test_uvicorn_access_formatter_preserves_status_without_query_or_ip(self) -> None:
        from uvicorn.logging import AccessFormatter

        record = logging.getLogRecordFactory()(
            "uvicorn.access", logging.INFO, __file__, 1,
            '%s - "%s %s HTTP/%s" %d',
            ("192.0.2.5:12345", "GET", "/api/players/%23P0YQ88?initData=private-message", "1.1", 403),
            None,
        )
        text = AccessFormatter('%(client_addr)s %(request_line)s %(status_code)s', use_colors=False).format(record)
        for value in ("192.0.2.5", "P0YQ88", "initData", "private-message"):
            self.assertNotIn(value, text)
        self.assertIn("GET /api/players/", text)
        self.assertIn("403", text)
        self.assertEqual(record.args[-1], 403)

    def test_structured_error_context_omits_personal_fields(self) -> None:
        from bot.user_errors import log_error

        log_error(self.logger, "E062", "Link rejected", user_id=12, username="fixture_person", status=409)
        text = self.output.getvalue()
        self.assertIn("[E062] Link rejected", text)
        self.assertIn("status=409", text)
        self.assertNotIn("user_id", text)
        self.assertNotIn("fixture_person", text)

    def test_sqlalchemy_error_hides_bound_user_values(self) -> None:
        from sqlalchemy.exc import StatementError
        from bot.models.database import _engine_kwargs

        self.assertTrue(_engine_kwargs()["hide_parameters"])
        error = StatementError(
            "Insert failed", "INSERT INTO users (telegram_id) VALUES (?)",
            (987654321,), ValueError("constraint conflict"), hide_parameters=True,
        )
        self.logger.error("Database write failed: %s", error)
        text = self.output.getvalue()
        self.assertIn("Database write failed", text)
        self.assertIn("INSERT INTO users", text)
        self.assertNotIn("987654321", text)

    def test_ai_response_body_and_error_context_are_not_logged(self) -> None:
        from bot.services.ghosteek_ai.llm.provider import QwenLLMProvider
        from bot.services.ghosteek_ai.llm.base import ProviderError
        from unittest.mock import patch

        provider = object.__new__(QwenLLMProvider)
        private_text = "fixture private conversation"
        with patch("bot.services.ghosteek_ai.llm.provider.logger", self.logger):
            provider._log_raw_response(
                url="https://fixture.invalid/?private=1", status=400,
                headers={"X-User": private_text}, raw_text=private_text,
                data={"message": private_text},
            )
        try:
            raise ProviderError(private_text, code="HTTP_ERROR", details={"body": private_text})
        except ProviderError:
            self.logger.exception("Renderer failed")
        self.logger.warning("Provider unavailable: %s", ProviderError(private_text, code="HTTP_ERROR"))
        text = self.output.getvalue()
        self.assertNotIn(private_text, text)
        self.assertNotIn("fixture.invalid", text)
        self.assertIn("status=400", text)
        self.assertIn("ProviderError: HTTP_ERROR", text)
        self.assertIn("test_ai_response_body", text)


if __name__ == "__main__":
    unittest.main()

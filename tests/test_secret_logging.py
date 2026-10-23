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


if __name__ == "__main__":
    unittest.main()

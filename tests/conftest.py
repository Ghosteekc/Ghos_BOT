"""Pytest bootstrap: minimal env so Settings() loads during test collection."""

from __future__ import annotations

import os

os.environ.setdefault("BOT_TOKEN", "pytest-bot-token")
os.environ.setdefault("CLASH_ROYALE_API_KEY", "pytest-cr-api-key")

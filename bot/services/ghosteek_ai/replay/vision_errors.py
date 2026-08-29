"""Shared vision-backend errors for Ollama / Groq adapters."""

from __future__ import annotations


class VisionUnavailable(Exception):
    """Vision backend unreachable, auth failed, or returned an error."""


class VisionTimeout(Exception):
    """Vision request exceeded the configured timeout."""

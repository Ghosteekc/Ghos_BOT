"""Tests for multi-stage deck build fallback."""

from __future__ import annotations

from bot.services.deck_builder.staged_build import (
    STAGE_FREEFORM,
    STAGE_META,
    build_decks_staged,
)


def test_giant_skeleton_builds_without_meta_templates():
    result = build_decks_staged(["Giant Skeleton"], limit=2)
    assert result["ok"] is True
    assert result["mode"] == STAGE_FREEFORM
    builds = result.get("build_results") or []
    assert builds
    assert len(builds[0].deck) == 8
    assert "Giant Skeleton" in builds[0].deck


def test_hog_still_uses_meta_when_available():
    result = build_decks_staged(["Hog Rider"], limit=2)
    assert result["ok"] is True
    assert result["mode"] == STAGE_META
    assert result.get("decks")


def test_unknown_card_is_only_hard_error():
    result = build_decks_staged(["DefinitelyNotACard123"], limit=1)
    assert result["ok"] is False
    assert result["error_code"] == "BUILD_UNKNOWN_CARD"

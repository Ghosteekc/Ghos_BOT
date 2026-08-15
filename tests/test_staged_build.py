"""Tests for multi-stage deck build — Validation gate only."""

from __future__ import annotations

from bot.services.deck_builder.staged_build import (
    ERROR_NO_VALID_BUILD,
    STAGE_FREEFORM,
    STAGE_META,
    build_decks_staged,
)


def test_successful_build_is_always_validated():
    result = build_decks_staged(["Hog Rider"], limit=2)
    if result["ok"]:
        assert result["mode"] in {STAGE_META, STAGE_FREEFORM, "archetype_fallback"}
        if result["mode"] == STAGE_META:
            assert result.get("decks")
        else:
            builds = result.get("build_results") or []
            assert builds
            for item in builds:
                assert item.balanced is True
                assert item.validation is not None
                assert item.validation.stable is True
                assert len(item.deck) == 8
    else:
        assert result["error_code"] == ERROR_NO_VALID_BUILD
        assert result["status"] == ERROR_NO_VALID_BUILD
        assert result.get("reason")
        assert result.get("suggestion")
        assert not result.get("build_results")
        assert not result.get("decks")


def test_multi_seed_keeps_all_requested_cards():
    """Hog + Tornado + Electro Spirit — все три должны быть в колоде (не чистый 2.6)."""
    seed = ["Hog Rider", "Tornado", "Electro Spirit"]
    result = build_decks_staged(seed, limit=2)
    assert result["ok"] is True
    names: list[str] = []
    if result.get("mode") == STAGE_META and result.get("decks"):
        names = list(result["decks"][0].get("cards") or [])
        # meta entries may store cards as list[str] or list[dict]
        if names and isinstance(names[0], dict):
            names = [str(c.get("name") or "") for c in names]
    else:
        builds = result.get("build_results") or []
        assert builds
        names = list(builds[0].deck)
    for card in seed:
        assert card in names, f"{card} missing from {names} (mode={result.get('mode')})"


def test_hog_alone_still_can_use_meta():
    result = build_decks_staged(["Hog Rider"], limit=2)
    assert result["ok"] is True
    assert result["mode"] == STAGE_META


def test_giant_skeleton_never_returns_unvalidated_success():
    result = build_decks_staged(["Giant Skeleton"], limit=2)
    if result["ok"]:
        builds = result.get("build_results") or []
        assert builds
        assert builds[0].balanced is True
        assert builds[0].validation is not None
        assert builds[0].validation.stable is True
        assert "Giant Skeleton" in builds[0].deck
    else:
        assert result["ok"] is False
        assert result["error_code"] == ERROR_NO_VALID_BUILD
        assert result["status"] == "NO_VALID_BUILD"
        assert "reason" in result
        assert "suggestion" in result


def test_unknown_card_is_only_hard_error():
    result = build_decks_staged(["DefinitelyNotACard123"], limit=1)
    assert result["ok"] is False
    assert result["error_code"] == "BUILD_UNKNOWN_CARD"


def test_no_ok_true_with_unbalanced_build_results():
    # Smoke: any ok=True path must not carry unbalanced BuildResult.
    for seed in (["Hog Rider"], ["Giant Skeleton"], ["Miner", "Poison"]):
        result = build_decks_staged(seed, limit=3)
        if not result.get("ok"):
            continue
        for item in result.get("build_results") or []:
            assert item.balanced is True
            assert item.validation is not None and item.validation.stable

"""Session battle cache must be bound to the linked player tag."""

from __future__ import annotations

from bot.services.battle_session_cache import (
    clear_user,
    get_session_battles,
    get_session_tag,
    set_session_battles,
)


def test_session_battles_require_matching_tag() -> None:
    clear_user(900001, "#AAA")
    set_session_battles(900001, "#AAA", [{"id": "a"}])
    assert get_session_tag(900001) == "#AAA"
    assert get_session_battles(900001, expected_tag="#AAA") == [{"id": "a"}]
    assert get_session_battles(900001, expected_tag="#BBB") is None
    assert get_session_battles(900001) == [{"id": "a"}]

    clear_user(900001, "#AAA")
    assert get_session_battles(900001, expected_tag="#AAA") is None


def test_retag_overwrites_session() -> None:
    clear_user(900002)
    set_session_battles(900002, "#OLD", [{"id": "old"}])
    set_session_battles(900002, "#NEW", [{"id": "new"}])
    assert get_session_battles(900002, expected_tag="#OLD") is None
    assert get_session_battles(900002, expected_tag="#NEW") == [{"id": "new"}]

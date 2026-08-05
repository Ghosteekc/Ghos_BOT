"""Сборка DeckCardResponse из уже готовых Builder / template entries.

Не вызывает Builder и RecommendationEngine заново — только маппинг полей.
"""

from __future__ import annotations

from typing import Any

from bot.services.card_registry import build_deck_share_link
from bot.services.deck_analyzer import analyze_deck


def extract_deck_names(entry: dict[str, Any]) -> list[str]:
    cards = entry.get("cards") or entry.get("card_names") or []
    if not isinstance(cards, list):
        return []
    names: list[str] = []
    for item in cards:
        if isinstance(item, str) and item.strip():
            names.append(item.strip())
        elif isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
    return names[:8]


def _weakness_lines(entry: dict[str, Any]) -> list[str]:
    out: list[str] = []
    sanity = entry.get("sanity_report")
    if not isinstance(sanity, dict):
        rec = entry.get("recommendation")
        if isinstance(rec, dict):
            sanity = rec.get("sanity_report")
    if isinstance(sanity, dict) and not sanity.get("passed", True):
        for msg in sanity.get("critical_messages") or []:
            if isinstance(msg, str) and msg.strip() and msg.strip() not in out:
                out.append(msg.strip())
        verdict = sanity.get("coach_verdict")
        if isinstance(verdict, str) and verdict.strip() and verdict.strip() not in out:
            out.insert(0, verdict.strip())
    gp = entry.get("game_plan")
    if isinstance(gp, dict):
        for w in gp.get("critical_weaknesses") or []:
            if isinstance(w, str) and w.strip() and w.strip() not in out:
                out.append(w.strip())
    report = entry.get("evaluation_report")
    if isinstance(report, dict):
        for w in report.get("weaknesses") or []:
            if isinstance(w, str) and w.strip() and w.strip() not in out:
                out.append(w.strip())
    return out[:5]


def _sanity_failed(entry: dict[str, Any]) -> bool:
    sanity = entry.get("sanity_report")
    if isinstance(sanity, dict) and "passed" in sanity:
        return not bool(sanity.get("passed"))
    rec = entry.get("recommendation")
    if isinstance(rec, dict):
        nested = rec.get("sanity_report")
        if isinstance(nested, dict) and "passed" in nested:
            return not bool(nested.get("passed"))
    return False


def _gameplan_lines(entry: dict[str, Any]) -> list[str]:
    # Пока Sanity не пройден — не отдаём «как играть».
    if _sanity_failed(entry):
        return []
    lines: list[str] = []
    gp = entry.get("game_plan")
    if isinstance(gp, dict):
        for key in ("how_to_win", "when_to_attack", "primary_threat"):
            val = gp.get(key)
            if isinstance(val, str) and val.strip():
                lines.append(val.strip())
        combos = gp.get("core_combinations")
        if isinstance(combos, list):
            for c in combos[:2]:
                if isinstance(c, str) and c.strip():
                    lines.append(c.strip())
    rec = entry.get("recommendation")
    if isinstance(rec, dict) and not lines:
        coaching = rec.get("coaching") or {}
        if isinstance(coaching, dict):
            for tip in (coaching.get("usage_tips") or [])[:2]:
                if isinstance(tip, str) and tip.strip():
                    lines.append(tip.strip())
    desc = entry.get("description")
    if not lines and isinstance(desc, str) and desc.strip():
        lines.append(desc.strip())
    return lines[:5]


def _evaluation_payload(entry: dict[str, Any]) -> dict[str, Any]:
    report = entry.get("evaluation_report")
    if isinstance(report, dict) and report:
        # Урезанный снимок для UI — без тяжёлых вложенных деревьев
        keys = (
            "total_score",
            "archetype",
            "strengths",
            "weaknesses",
            "reasons",
        )
        payload = {k: report[k] for k in keys if k in report}
        if "synergy" in report and isinstance(report["synergy"], dict):
            payload["synergy_score"] = report["synergy"].get("score")
        return payload
    payload: dict[str, Any] = {}
    for key in ("total_score", "synergy_score", "confidence", "balanced"):
        if key in entry and entry[key] is not None:
            payload[key] = entry[key]
    breakdown = entry.get("score_breakdown")
    if isinstance(breakdown, dict) and breakdown:
        payload["score_breakdown"] = breakdown
    return payload


def deck_card_from_entry(
    entry: dict[str, Any] | None,
    *,
    arena: str | None = None,
) -> dict[str, Any] | None:
    """Маппинг constructor/meta entry → dict совместимый с DeckCardResponse."""
    if not isinstance(entry, dict):
        return None
    names = extract_deck_names(entry)
    if len(names) != 8:
        return None

    avg = entry.get("avg_elixir")
    if avg is None:
        avg = entry.get("average_elixir")
    if avg is None:
        avg = float(analyze_deck(names).avg_elixir)

    import_url = entry.get("deck_link") or entry.get("import_url") or ""
    if not import_url:
        import_url = build_deck_share_link(names) or ""

    archetype = str(entry.get("archetype") or entry.get("category") or entry.get("name") or "")
    title = entry.get("name")
    if title is not None:
        title = str(title)

    return {
        "deck": names,
        "average_elixir": round(float(avg), 1),
        "archetype": archetype,
        "arena": arena,
        "import_url": str(import_url or ""),
        "gameplan": _gameplan_lines(entry),
        "weaknesses": _weakness_lines(entry),
        "evaluation": _evaluation_payload(entry),
        "title": title,
        "sanity_passed": not _sanity_failed(entry),
    }


def deck_card_from_build_data(
    data: dict[str, Any] | None,
    *,
    arena: str | None = None,
) -> dict[str, Any] | None:
    """Первая колода из tool data (core/decks/mode) → DeckCard."""
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("deck_card"), dict) and data["deck_card"].get("deck"):
        card = dict(data["deck_card"])
        if arena and not card.get("arena"):
            card["arena"] = arena
        return card
    decks = data.get("decks")
    if not isinstance(decks, list) or not decks:
        return None
    first = decks[0]
    if not isinstance(first, dict):
        return None
    return deck_card_from_entry(first, arena=arena)


def format_arena_label(arena_id: int | None, trophies: int | None = None) -> str | None:
    if arena_id is None and trophies is None:
        return None
    if arena_id is not None:
        return f"Арена {arena_id}"
    return None

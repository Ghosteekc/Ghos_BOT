"""Сравнение колод на основе локальных контр и синергий (DeckShop → card_matchups)."""

from __future__ import annotations

from bot.services.card_data import card_counters_for_spell, is_pure_spell
from bot.services.card_matchups import (
    calculate_deck_synergy,
    calculate_matchup_score,
    counters_in_deck,
    ru,
    ru_list,
    targets_countered_by,
)
from bot.services.deck_analyzer import analyze_deck


def _note(card: str, tone: str, text: str) -> dict:
    return {"card": card, "card_ru": ru(card), "tone": tone, "text": text}


def _dedupe(items: list[str], limit: int = 8) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out[:limit]


def _analyze_own_card(card: str, own_deck: list[str], opp_deck: list[str]) -> dict:
    label = ru(card)
    strong_opp, partial_opp = targets_countered_by(card, opp_deck)
    opp_strong, opp_partial = counters_in_deck(card, opp_deck)

    if is_pure_spell(card) and not strong_opp and not partial_opp:
        return _note(
            card,
            "neutral",
            f"{label} — заклинание, картой не контрится; бьёт по юнитам на поле",
        )

    if strong_opp:
        extra = f", слабее против {ru_list(partial_opp)}" if partial_opp else ""
        if card == "Monk" and any(is_pure_spell(t) for t in strong_opp):
            spells = ru_list([t for t in strong_opp if is_pure_spell(t)])
            troops = ru_list([t for t in strong_opp if not is_pure_spell(t)])
            parts = []
            if spells:
                parts.append(f"отражает {spells}")
            if troops:
                parts.append(f"контрит {troops}")
            return _note(card, "good", f"{label} — {'; '.join(parts)}{extra}")
        return _note(
            card,
            "good",
            f"{label} — контрит {ru_list(strong_opp)}{extra}",
        )
    if partial_opp:
        return _note(
            card,
            "warn",
            f"{label} — частично помогает против {ru_list(partial_opp)}",
        )
    if opp_strong:
        return _note(
            card,
            "warn",
            f"{label} — соперник останавливает через {ru_list(opp_strong)}",
        )
    if opp_partial:
        return _note(
            card,
            "warn",
            f"{label} — у соперника слабый ответ ({ru_list(opp_partial)})",
        )
    return _note(card, "neutral", f"{label} — нейтральная карта в этом матчапе")


def _analyze_enemy_card(card: str, enemy_deck: list[str], your_deck: list[str]) -> dict:
    label = ru(card)
    your_strong, your_partial = counters_in_deck(card, your_deck)

    if your_strong:
        if is_pure_spell(card):
            return _note(
                card,
                "good",
                f"{label} — {ru_list(your_strong)} отражает заклинание",
            )
        extra = f", частично: {ru_list(your_partial)}" if your_partial else ""
        return _note(
            card,
            "good",
            f"{label} — ваши {ru_list(your_strong)} держат угрозу{extra}",
        )
    if your_partial:
        return _note(
            card,
            "warn",
            f"{label} — только слабый ответ ({ru_list(your_partial)}), можно пробить",
        )
    if is_pure_spell(card):
        return _note(
            card,
            "neutral",
            f"{label} — заклинание, картой-контрой не остановить",
        )
    return _note(
        card,
        "bad",
        f"{label} — в колоде нет надёжной контры",
    )


def compare_decks(user_cards: list[str], ref_cards: list[str]) -> dict:
    empty = {
        "user_better": [],
        "user_worse": [],
        "reference_better": [],
        "reference_worse": [],
        "user_card_notes": [],
        "reference_card_notes": [],
        "matchup_score": 50.0,
        "opponent_matchup_score": 50.0,
        "user_synergy_score": 50.0,
        "reference_synergy_score": 50.0,
        "user_synergy_notes": [],
        "reference_synergy_notes": [],
    }

    if len(user_cards) != 8 or len(ref_cards) != 8:
        empty["user_worse"] = ["Нужна полная колода из 8 карт для сравнения"]
        return empty

    user_notes = [_analyze_own_card(c, user_cards, ref_cards) for c in user_cards]
    ref_notes = [_analyze_enemy_card(c, ref_cards, user_cards) for c in ref_cards]

    user_better: list[str] = []
    user_worse: list[str] = []
    ref_better: list[str] = []
    ref_worse: list[str] = []

    for threat in ref_cards:
        if is_pure_spell(threat) and not card_counters_for_spell(threat):
            continue
        t = ru(threat)
        strong, partial = counters_in_deck(threat, user_cards)
        if strong:
            tail = f", слабее: {ru_list(partial)}" if partial else ""
            user_better.append(f"Есть контра на {t} ({ru_list(strong)}{tail})")
        elif partial:
            user_worse.append(f"Слабый ответ на {t} ({ru_list(partial)})")
            ref_better.append(f"{t} сложнее остановить без полной контры")
        else:
            user_worse.append(f"Нет контры на {t}")
            ref_better.append(f"{t} в колоде арены сложнее остановить")

    for threat in user_cards:
        if is_pure_spell(threat) and not card_counters_for_spell(threat):
            continue
        t = ru(threat)
        strong, partial = counters_in_deck(threat, ref_cards)
        if strong:
            user_worse.append(f"Ваш {t} встречает контру ({ru_list(strong)})")
            ref_better.append(f"Есть ответ на ваш {t} ({ru_list(strong)})")
        elif partial:
            user_worse.append(f"Ваш {t} частично контрится ({ru_list(partial)})")
        else:
            user_better.append(f"Ваш {t} труднее остановить")
            ref_worse.append(f"Слабее против вашего {t}")

    user_syn_score, user_syn_notes = calculate_deck_synergy(user_cards)
    ref_syn_score, ref_syn_notes = calculate_deck_synergy(ref_cards)

    if user_syn_score > ref_syn_score + 6:
        user_better.append(
            f"Лучше синергия внутри колоды ({user_syn_score:.0f}% против {ref_syn_score:.0f}%)",
        )
        ref_worse.append(f"Слабее синергия ({ref_syn_score:.0f}% против {user_syn_score:.0f}%)")
    elif ref_syn_score > user_syn_score + 6:
        user_worse.append(
            f"Слабее синергия ({user_syn_score:.0f}% против {ref_syn_score:.0f}%)",
        )
        ref_better.append(
            f"Лучше синергия внутри колоды ({ref_syn_score:.0f}% против {user_syn_score:.0f}%)",
        )

    u = analyze_deck(user_cards)
    r = analyze_deck(ref_cards)
    if u.avg_elixir + 0.3 < r.avg_elixir:
        user_better.append(f"Быстрее цикл ({u.avg_elixir} против {r.avg_elixir} эликсира)")
        ref_worse.append(f"Медленнее цикл ({r.avg_elixir} против {u.avg_elixir} эликсира)")
    elif r.avg_elixir + 0.3 < u.avg_elixir:
        user_worse.append(f"Медленнее цикл ({u.avg_elixir} против {r.avg_elixir} эликсира)")
        ref_better.append(f"Быстрее цикл ({r.avg_elixir} против {u.avg_elixir} эликсира)")

    if not user_better and not user_worse:
        user_better.append("Колоды близки по контрам и синергии")

    return {
        "user_better": _dedupe(user_better),
        "user_worse": _dedupe(user_worse),
        "reference_better": _dedupe(ref_better),
        "reference_worse": _dedupe(ref_worse),
        "user_card_notes": user_notes,
        "reference_card_notes": ref_notes,
        "matchup_score": calculate_matchup_score(user_cards, ref_cards),
        "opponent_matchup_score": calculate_matchup_score(ref_cards, user_cards),
        "user_synergy_score": user_syn_score,
        "reference_synergy_score": ref_syn_score,
        "user_synergy_notes": user_syn_notes,
        "reference_synergy_notes": ref_syn_notes,
    }

"""Per-deck stats: matchups, winrate from battle history.

Recommendations — только через RecommendationEngine (без локальных gap-эвристик).
"""

from __future__ import annotations

from bot.services.card_data import is_pure_spell
from bot.services.card_knowledge import canonical_card_names
from bot.services.card_matchups import card_counters_target, counters_in_deck
from bot.services.card_names_ru import card_name_ru
from bot.services.clash_api import normalize_tag
from bot.services.deck_analyzer import analyze_deck, extract_deck
from bot.services.meta_analyzer import _guess_deck_name
from bot.services.recommendation_engine import RecommendationEngine

# Мелкий цикл / духи: обычно не дефают ради эликсира — контру в UI не пишем.
_SKIP_COUNTER_ADVICE = frozenset({
    "Skeletons",
    "Ice Spirit",
    "Fire Spirit",
    "Electro Spirit",
    "Heal Spirit",
})


def deck_key(cards: list[str]) -> str:
    return "|".join(sorted(cards))


def _skip_counter_advice(threat: str) -> bool:
    return threat in _SKIP_COUNTER_ADVICE


def _effective_counters(deck: list[str], threat: str) -> list[str]:
    """Карты из колоды, которые реально отвечают на угрозу (не wincon vs здание)."""
    if is_pure_spell(threat) or _skip_counter_advice(threat):
        return []
    strong, partial = counters_in_deck(threat, deck)
    return strong or partial


def _suggested_counters(threat: str, *, limit: int = 3) -> list[str]:
    """Подсказки «подойдут», без атакующих wincon как «контры» зданий и без цикла."""
    if is_pure_spell(threat) or _skip_counter_advice(threat):
        return []
    candidates = sorted(canonical_card_names())
    strong = [card for card in candidates if card_counters_target(card, threat) == "strong"]
    partial = [card for card in candidates if card_counters_target(card, threat) == "partial"]
    return (strong + partial)[:limit]


def _filter_battles_for_deck(battles: list[dict], player_tag: str, cards: list[str]) -> list[dict]:
    if len(cards) != 8:
        return []
    key = deck_key(cards)
    tag_norm = normalize_tag(player_tag)
    out: list[dict] = []

    for battle in battles:
        battle_type = battle.get("type") or "PvP"
        if battle_type in ("friendly", "clanMate", "warDay", "boatBattle", "challenge"):
            continue
        team = battle.get("team", [{}])[0]
        team_tag = team.get("tag") or ""
        if team_tag and normalize_tag(team_tag) != tag_norm:
            continue
        user_cards = extract_deck(team)
        if deck_key(user_cards) != key:
            continue
        out.append(battle)

    return out


def _analyze_opponent_card_matchups(deck_cards: list[str], deck_battles: list[dict]) -> tuple[list[dict], list[dict]]:
    """Cards opponents played that this deck handles well or poorly."""
    card_stats: dict[str, dict[str, int]] = {}

    for battle in deck_battles:
        team = battle.get("team", [{}])[0]
        opponent = battle.get("opponent", [{}])[0]
        won = team.get("crowns", 0) > opponent.get("crowns", 0)
        for card in set(extract_deck(opponent)):
            stat = card_stats.setdefault(card, {"wins": 0, "total": 0})
            stat["total"] += 1
            if won:
                stat["wins"] += 1

    strong: list[dict] = []
    weak: list[dict] = []

    for card, stat in card_stats.items():
        total = stat["total"]
        if total < 2:
            continue
        wins = stat["wins"]
        wr = round(wins / total * 100, 1)
        counters = _effective_counters(deck_cards, card)
        label = card_name_ru(card, short=True) or card
        skip_advice = _skip_counter_advice(card)

        if wr >= 55:
            if skip_advice:
                # Винрейт оставляем, контру на мелкий цикл не пишем.
                strong.append({
                    "card": card,
                    "card_ru": label,
                    "winrate": wr,
                    "games": total,
                    "reason": "Мелкая цикл-карта — обычно не дефают ради эликсира",
                })
            elif counters:
                strong.append({
                    "card": card,
                    "card_ru": label,
                    "winrate": wr,
                    "games": total,
                    "reason": (
                        "Есть ответ ("
                        f"{', '.join(card_name_ru(c, short=True) or c for c in counters[:3])}"
                        ")"
                    ),
                })
        elif wr <= 45 or (not counters and not skip_advice and wr < 52):
            if skip_advice:
                reason = f"Винрейт {wr:.0f}% — слабый матчап (не из‑за отсутствия контры)"
            elif counters:
                reason = f"Винрейт {wr:.0f}% — счётчик есть, но матчап слабый"
            else:
                rec = ", ".join(
                    card_name_ru(c, short=True) or c for c in _suggested_counters(card)
                )
                reason = f"Винрейт {wr:.0f}% — нет прямого счётчика"
                if rec:
                    reason += f". Подойдут: {rec}"
            weak.append({
                "card": card,
                "card_ru": label,
                "winrate": wr,
                "games": total,
                "reason": reason,
            })

    strong.sort(key=lambda x: (-x["games"], -x["winrate"]))
    weak.sort(key=lambda x: (-x["games"], x["winrate"]))
    return strong[:8], weak[:8]


def build_mine_deck_stats(battles: list[dict], player_tag: str, cards: list[str]) -> dict:
    if len(cards) != 8:
        return {"error": "Нужна полная колода из 8 карт"}

    deck_battles = _filter_battles_for_deck(battles, player_tag, cards)
    wins = 0
    for battle in deck_battles:
        team = battle.get("team", [{}])[0]
        opponent = battle.get("opponent", [{}])[0]
        if team.get("crowns", 0) > opponent.get("crowns", 0):
            wins += 1
    total = len(deck_battles)
    losses = total - wins
    winrate = round(wins / total * 100, 1) if total else 0.0

    stats = analyze_deck(cards)
    strong, weak = _analyze_opponent_card_matchups(cards, deck_battles)

    rec = RecommendationEngine.analyze(cards, apply_swaps=False)
    improvements = rec.improvements_ui()
    # balanced — только Builder SoT (EvaluationReport), не локальный score.
    from bot.services.deck_builder.quality import is_good_deck

    balanced = is_good_deck(report=rec.evaluation_report) and len(improvements) == 0

    sample_note = ""
    if total == 0:
        sample_note = "Нет боёв с этой колодой в истории — статистика по матчапам недоступна"
    elif total < 5:
        sample_note = f"Мало данных ({total} боёв) — выводы могут быть неточными"

    return {
        "name": _guess_deck_name(cards),
        "cards": cards,
        "wins": wins,
        "losses": losses,
        "total_games": total,
        "winrate": winrate,
        "avg_elixir": stats.avg_elixir,
        "win_conditions": stats.win_conditions,
        "strong_against": strong,
        "weak_against": weak,
        "improvements": improvements,
        "balanced": balanced,
        "sample_note": sample_note,
        "game_plan": rec.game_plan.to_dict(),
        "recommendation": rec.to_public_dict(),
        # Passport отображает только EvaluationReport (единый слой оценки).
        "evaluation_report": (
            rec.evaluation_report.to_dict() if rec.evaluation_report is not None else None
        ),
    }

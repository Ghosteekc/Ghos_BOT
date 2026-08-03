"""Извлечение допустимых фактов из AIContext для post-validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", ".").replace("%", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _add_number(bucket: set[float], value: Any) -> None:
    num = _as_float(value)
    if num is None:
        return
    bucket.add(num)
    # также целая форма для сравнения «74» vs 74.0
    if abs(num - round(num)) < 1e-9:
        bucket.add(float(round(num)))


def _walk_dict_numbers(raw: dict[str, Any], bucket: set[float], *, keys_hint: tuple[str, ...]) -> None:
    for key, val in raw.items():
        key_l = str(key).lower()
        if any(h in key_l for h in keys_hint):
            if isinstance(val, dict):
                _walk_dict_numbers(val, bucket, keys_hint=keys_hint)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        _walk_dict_numbers(item, bucket, keys_hint=keys_hint)
                    else:
                        _add_number(bucket, item)
            else:
                _add_number(bucket, val)
        elif isinstance(val, dict):
            _walk_dict_numbers(val, bucket, keys_hint=keys_hint)


@dataclass
class AllowedFacts:
    """Числа и флаги наличия данных, на которые можно ссылаться в ответе."""

    numbers: set[float] = field(default_factory=set)
    percentages: set[float] = field(default_factory=set)
    has_trophies: bool = False
    has_synergy: bool = False
    has_evaluation: bool = False
    has_battle: bool = False
    has_winrate: bool = False
    has_score: bool = False
    has_elixir_stats: bool = False
    # Данные, которых в CR-пайплайне обычно нет — по умолчанию False
    has_damage: bool = False
    has_dps: bool = False
    has_opponent_elixir: bool = False
    has_replay: bool = False
    has_timer: bool = False
    has_positioning: bool = False

    def allows_number(self, value: float, *, tol: float = 0.6) -> bool:
        for allowed in self.numbers:
            if abs(allowed - value) <= tol:
                return True
        return False

    def allows_percentage(self, value: float, *, tol: float = 0.6) -> bool:
        for allowed in self.percentages:
            if abs(allowed - value) <= tol:
                return True
        # процент мог лежать и в общем numbers (winrate как 0.74 vs 74)
        if self.allows_number(value, tol=tol):
            return True
        if value <= 1.0 and self.allows_number(value * 100.0, tol=tol):
            return True
        return False


_NUMBER_KEY_HINTS = (
    "troph",
    "elixir",
    "synergy",
    "score",
    "winrate",
    "win_rate",
    "wr",
    "rating",
    "matchup",
    "percent",
    "pct",
)


def extract_allowed_facts(ctx: Any | None) -> AllowedFacts:
    facts = AllowedFacts()
    if ctx is None:
        return facts

    trophies = getattr(ctx, "trophies", None)
    if trophies is None:
        arena = getattr(ctx, "arena", None)
        trophies = getattr(arena, "trophies", None) if arena is not None else None
    if trophies is not None:
        facts.has_trophies = True
        _add_number(facts.numbers, trophies)

    synergy = getattr(ctx, "synergy_score", None)
    if synergy is None:
        rec = getattr(ctx, "recommendation", None)
        synergy = getattr(rec, "synergy_score", None) if rec is not None else None
    if synergy is not None:
        facts.has_synergy = True
        facts.has_score = True
        _add_number(facts.numbers, synergy)
        _add_number(facts.percentages, synergy)

    evaluation = getattr(ctx, "evaluation", None)
    ev_score = getattr(evaluation, "score", None) if evaluation is not None else None
    if ev_score is not None:
        facts.has_evaluation = True
        facts.has_score = True
        _add_number(facts.numbers, ev_score)
        _add_number(facts.percentages, ev_score)

    battle = getattr(ctx, "battle", None)
    has_battle = False
    if battle is not None:
        if getattr(battle, "raw", None) or getattr(battle, "outcome_summary", None) is not None:
            has_battle = True
        if getattr(battle, "won", None) is not None or getattr(battle, "battle_index", None) is not None:
            has_battle = True
        matchup = getattr(battle, "matchup_score", None)
        if matchup is not None:
            has_battle = True
            facts.has_score = True
            _add_number(facts.numbers, matchup)
            _add_number(facts.percentages, matchup)
        for blob in (
            getattr(battle, "raw", None),
            getattr(battle, "match_difficulty", None),
            getattr(battle, "match_plan", None),
        ):
            if isinstance(blob, dict):
                _walk_dict_numbers(blob, facts.numbers, keys_hint=_NUMBER_KEY_HINTS)
                _collect_special_flags(blob, facts)
    facts.has_battle = has_battle

    data = getattr(ctx, "data", None)
    if isinstance(data, dict):
        _walk_dict_numbers(data, facts.numbers, keys_hint=_NUMBER_KEY_HINTS)
        _collect_special_flags(data, facts)
        for key, val in data.items():
            key_l = str(key).lower()
            if "winrate" in key_l or "win_rate" in key_l or key_l == "wr":
                facts.has_winrate = True
                num = _as_float(val)
                if num is not None:
                    _add_number(facts.percentages, num if num > 1 else num * 100.0)
                    _add_number(facts.numbers, num)
            if "synergy" in key_l:
                facts.has_synergy = True
            if "score" in key_l or "rating" in key_l:
                facts.has_score = True
            if "elixir" in key_l:
                facts.has_elixir_stats = True

    rec = getattr(ctx, "recommendation", None)
    payload = getattr(rec, "payload", None) if rec is not None else None
    if isinstance(payload, dict):
        _walk_dict_numbers(payload, facts.numbers, keys_hint=_NUMBER_KEY_HINTS)
        _collect_special_flags(payload, facts)

    # проценты 0–100 из numbers, похожие на winrate/score
    for n in list(facts.numbers):
        if 0 <= n <= 100:
            facts.percentages.add(n)

    return facts


def _collect_special_flags(raw: dict[str, Any], facts: AllowedFacts) -> None:
    for key, val in raw.items():
        key_l = str(key).lower()
        if val in (None, "", [], {}):
            continue
        if any(x in key_l for x in ("damage", "урон", "dmg")):
            facts.has_damage = True
        if "dps" in key_l or "дпс" in key_l:
            facts.has_dps = True
        if "opponent_elixir" in key_l or "elixir_in_hand" in key_l or "enemy_elixir" in key_l:
            facts.has_opponent_elixir = True
        if "replay" in key_l or "реплей" in key_l:
            facts.has_replay = True
        if any(x in key_l for x in ("timer", "second", "секунд", "timestamp")):
            facts.has_timer = True
        if any(x in key_l for x in ("position", "позиц", "tile", "координат")):
            facts.has_positioning = True
        if isinstance(val, dict):
            _collect_special_flags(val, facts)

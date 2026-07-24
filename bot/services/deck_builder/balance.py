"""Жёсткие и мягкие ограничения баланса колод + score breakdown."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from bot.services.card_data import WIN_CONDITIONS, get_card_elixir
from bot.services.card_matchups import calculate_deck_synergy, synergy_between
from bot.services.deck_builder.constants import (
    ARCHETYPE_ANCHORS,
    ARCHETYPE_ELIXIR,
    ARCHETYPE_PRIMARY_WIN,
    DEFAULT_ELIXIR_MAX,
    DEFAULT_ELIXIR_MIN,
    GENERIC_CARDS,
    KNOWN_SYNERGY_PAIRS,
    MAX_SPELLS,
    MAX_WINS,
    ROLE_AIR,
    ROLE_ANTI_SWARM,
    ROLE_ANTI_TANK,
    ROLE_BIG_SPELL,
    ROLE_BUILDING,
    ROLE_COUNTERPUSH,
    ROLE_DEFENSIVE,
    ROLE_DPS,
    ROLE_MINI_TANK,
    ROLE_SMALL_SPELL,
    ROLE_SPLASH,
    ROLE_TANK,
    ROLE_WIN,
    SYNERGY_PARTIAL,
    SYNERGY_STRONG,
    SYNERGY_WEAK,
)
from bot.services.deck_builder.loader import DeckDatabase

PairSynergyFn = Callable[[str, str], int]

# Мягкие роли — бонусы при доборе, не жёсткое требование.
SOFT_ROLE_BONUS: dict[str, float] = {
    ROLE_BIG_SPELL: 12.0,
    ROLE_SMALL_SPELL: 10.0,
    ROLE_AIR: 8.0,
    ROLE_ANTI_TANK: 7.0,
    ROLE_DEFENSIVE: 7.0,
    ROLE_ANTI_SWARM: 6.0,
    ROLE_MINI_TANK: 5.0,
    ROLE_BUILDING: 4.0,
    ROLE_DPS: 3.0,
    ROLE_COUNTERPUSH: 3.0,
}

SCORE_WEIGHTS: dict[str, float] = {
    "synergy": 0.25,
    "offense": 0.12,
    "defense": 0.12,
    "anti_air": 0.12,
    "anti_swarm": 0.10,
    "spell_balance": 0.10,
    "elixir": 0.10,
    "archetype_fit": 0.09,
}


@dataclass
class ScoreBreakdown:
    synergy: float = 0.0
    offense: float = 0.0
    defense: float = 0.0
    anti_air: float = 0.0
    anti_swarm: float = 0.0
    spell_balance: float = 0.0
    elixir: float = 0.0
    archetype_fit: float = 0.0
    total: float = 0.0
    hard_issues: list[str] = field(default_factory=list)
    soft_issues: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "synergy": round(self.synergy, 1),
            "offense": round(self.offense, 1),
            "defense": round(self.defense, 1),
            "anti_air": round(self.anti_air, 1),
            "anti_swarm": round(self.anti_swarm, 1),
            "spell_balance": round(self.spell_balance, 1),
            "elixir": round(self.elixir, 1),
            "archetype_fit": round(self.archetype_fit, 1),
            "total": round(self.total, 1),
            "hard_issues": list(self.hard_issues),
            "soft_issues": list(self.soft_issues),
        }


def _avg_elixir(cards: list[str], db: DeckDatabase) -> float:
    if not cards:
        return 0.0
    total = sum(db.get_card(c).elixir if db.get_card(c) else get_card_elixir(c) for c in cards)
    return round(total / len(cards), 2)


def _card_roles(db: DeckDatabase, name: str) -> frozenset[str]:
    rec = db.get_card(name)
    return rec.roles if rec else frozenset()


def is_spell(db: DeckDatabase, name: str) -> bool:
    roles = _card_roles(db, name)
    return "spell" in roles or ROLE_SMALL_SPELL in roles or ROLE_BIG_SPELL in roles


def is_attack_win(name: str) -> bool:
    """Primary tower-push win condition (Hog, Giant, Ram…) — not Bandit/support push."""
    return name in WIN_CONDITIONS


def is_win(db: DeckDatabase, name: str) -> bool:
    return is_attack_win(name) or ROLE_WIN in _card_roles(db, name)


def count_spells(deck: list[str], db: DeckDatabase) -> int:
    return sum(1 for c in deck if is_spell(db, c))


def count_wins(deck: list[str], db: DeckDatabase) -> int:
    """Count primary attacking win-conditions only (for MAX_WINS / ensure)."""
    return sum(1 for c in deck if is_attack_win(c))


def count_role(deck: list[str], db: DeckDatabase, role: str) -> int:
    return sum(1 for c in deck if role in _card_roles(db, c))


def has_role(deck: list[str], db: DeckDatabase, role: str) -> bool:
    return count_role(deck, db, role) > 0


def _elixir_bounds(archetype: str) -> tuple[float, float]:
    return ARCHETYPE_ELIXIR.get(archetype, (DEFAULT_ELIXIR_MIN, DEFAULT_ELIXIR_MAX))


def default_pair_synergy(db: DeckDatabase, a: str, b: str) -> int:
    key = frozenset({a, b})
    if key in KNOWN_SYNERGY_PAIRS:
        return KNOWN_SYNERGY_PAIRS[key]
    if key in db.synergy_pairs:
        return db.synergy_pairs[key]
    tier = synergy_between(a, b)
    if tier == "strong":
        return SYNERGY_STRONG
    if tier == "partial":
        return SYNERGY_PARTIAL
    return SYNERGY_WEAK


def hard_constraint_issues(
    deck: list[str],
    db: DeckDatabase,
    core: list[str] | None = None,
) -> list[str]:
    issues: list[str] = []
    if len(deck) != 8:
        issues.append("deck_size")
    if len(deck) != len(set(deck)):
        issues.append("duplicate_cards")
    if core and not all(c in deck for c in core):
        issues.append("missing_core")
    if not any(is_attack_win(c) for c in deck):
        issues.append("win_condition")
    if count_wins(deck, db) > MAX_WINS:
        issues.append("too_many_wins")
    if count_spells(deck, db) > MAX_SPELLS:
        issues.append("too_many_spells")
    return issues


def soft_balance_issues(deck: list[str], db: DeckDatabase, archetype: str) -> list[str]:
    lo, hi = _elixir_bounds(archetype)
    issues: list[str] = []
    avg = _avg_elixir(deck, db)

    if not has_role(deck, db, ROLE_BIG_SPELL):
        issues.append("big_spell")
    if not has_role(deck, db, ROLE_SMALL_SPELL):
        issues.append("small_spell")
    if count_role(deck, db, ROLE_AIR) < 2:
        issues.append("air_defense")
    if not has_role(deck, db, ROLE_ANTI_TANK):
        issues.append("anti_tank")
    if not has_role(deck, db, ROLE_DEFENSIVE):
        issues.append("defensive")
    if not has_role(deck, db, ROLE_ANTI_SWARM):
        issues.append("anti_swarm")
    if avg < lo - 0.4 or avg > hi + 0.4:
        issues.append("elixir")
    return issues


def balance_issues(deck: list[str], db: DeckDatabase, archetype: str) -> list[str]:
    """Обратная совместимость: все issues (hard + soft)."""
    return hard_constraint_issues(deck, db) + soft_balance_issues(deck, db, archetype)


def _core_synergy_avg(
    deck: list[str],
    core: list[str],
    pair_synergy: PairSynergyFn,
) -> float:
    if not core:
        return 0.0
    total, n = 0.0, 0
    for c in core:
        for d in deck:
            if c != d:
                total += pair_synergy(c, d)
                n += 1
    return total / n if n else 0.0


def _axis_synergy(deck: list[str], core: list[str], pair_synergy: PairSynergyFn) -> float:
    deck_score, _ = calculate_deck_synergy(deck)
    core_avg = _core_synergy_avg(deck, core, pair_synergy)
    blended = deck_score * 0.55 + core_avg * 0.45
    return min(100.0, max(0.0, blended))


def _axis_offense(deck: list[str], db: DeckDatabase) -> float:
    score = 0.0
    if any(is_attack_win(c) for c in deck):
        score += 40.0
    if has_role(deck, db, ROLE_DPS):
        score += 20.0
    if has_role(deck, db, ROLE_COUNTERPUSH):
        score += 15.0
    if has_role(deck, db, ROLE_TANK):
        score += 15.0
    if count_wins(deck, db) > 1:
        score -= 15.0
    return min(100.0, max(0.0, score))


def _axis_defense(deck: list[str], db: DeckDatabase) -> float:
    score = 0.0
    if has_role(deck, db, ROLE_DEFENSIVE):
        score += 35.0
    if has_role(deck, db, ROLE_MINI_TANK):
        score += 30.0
    if has_role(deck, db, ROLE_BUILDING):
        score += 25.0
    if has_role(deck, db, ROLE_ANTI_TANK):
        score += 10.0
    return min(100.0, max(0.0, score))


def _axis_anti_air(deck: list[str], db: DeckDatabase) -> float:
    n = count_role(deck, db, ROLE_AIR)
    if n >= 2:
        return 100.0 if n == 2 else 90.0
    if n == 1:
        return 55.0
    return 15.0


def _axis_anti_swarm(deck: list[str], db: DeckDatabase) -> float:
    if has_role(deck, db, ROLE_ANTI_SWARM):
        return 100.0
    if has_role(deck, db, ROLE_SPLASH):
        return 60.0
    return 25.0


def _axis_spell_balance(deck: list[str], db: DeckDatabase) -> float:
    spells = count_spells(deck, db)
    has_big = has_role(deck, db, ROLE_BIG_SPELL)
    has_small = has_role(deck, db, ROLE_SMALL_SPELL)
    if has_big and has_small:
        base = 100.0
    elif has_big:
        base = 65.0
    elif has_small:
        base = 70.0
    elif spells == 0:
        base = 20.0
    else:
        base = 45.0
    if spells == MAX_SPELLS and has_big and has_small:
        base = min(100.0, base)
    elif spells > MAX_SPELLS:
        base = 10.0
    return base


def _axis_elixir(deck: list[str], db: DeckDatabase, archetype: str) -> float:
    lo, hi = _elixir_bounds(archetype)
    avg = _avg_elixir(deck, db)
    if lo <= avg <= hi:
        return 100.0
    diff = max(lo - avg, avg - hi, 0.0)
    if diff <= 0.4:
        return max(50.0, 100.0 - diff * 125.0)
    return max(15.0, 50.0 - (diff - 0.4) * 80.0)


def _axis_archetype_fit(deck: list[str], db: DeckDatabase, archetype: str) -> float:
    anchors = ARCHETYPE_ANCHORS.get(archetype, set())
    deck_set = set(deck)
    anchor_hits = len(deck_set & anchors) if anchors else 0
    anchor_score = (anchor_hits / max(len(anchors), 1)) * 80.0 if anchors else 50.0
    primary = ARCHETYPE_PRIMARY_WIN.get(archetype, [])
    if any(w in deck_set for w in primary):
        anchor_score += 20.0
    return min(100.0, max(0.0, anchor_score))


def compute_score_breakdown(
    deck: list[str],
    db: DeckDatabase,
    core: list[str],
    archetype: str,
    *,
    pair_synergy: PairSynergyFn | None = None,
) -> ScoreBreakdown:
    ps = pair_synergy or (lambda a, b: default_pair_synergy(db, a, b))
    hard = hard_constraint_issues(deck, db, core)
    soft = soft_balance_issues(deck, db, archetype)

    axes = {
        "synergy": _axis_synergy(deck, core, ps),
        "offense": _axis_offense(deck, db),
        "defense": _axis_defense(deck, db),
        "anti_air": _axis_anti_air(deck, db),
        "anti_swarm": _axis_anti_swarm(deck, db),
        "spell_balance": _axis_spell_balance(deck, db),
        "elixir": _axis_elixir(deck, db, archetype),
        "archetype_fit": _axis_archetype_fit(deck, db, archetype),
    }
    total = sum(axes[k] * SCORE_WEIGHTS[k] for k in axes)

    return ScoreBreakdown(
        synergy=axes["synergy"],
        offense=axes["offense"],
        defense=axes["defense"],
        anti_air=axes["anti_air"],
        anti_swarm=axes["anti_swarm"],
        spell_balance=axes["spell_balance"],
        elixir=axes["elixir"],
        archetype_fit=axes["archetype_fit"],
        total=total,
        hard_issues=hard,
        soft_issues=soft,
    )


def is_playable_balanced(
    breakdown: ScoreBreakdown,
    *,
    core_synergy_avg: float,
    min_core_synergy: float = 62.0,
    min_total: float = 58.0,
) -> bool:
    """Играбельность: hard OK, ядро не разрушено, общий score приемлем."""
    if breakdown.hard_issues:
        return False
    if core_synergy_avg < min_core_synergy:
        return False
    return breakdown.total >= min_total


def _missing_soft_roles(deck: list[str], db: DeckDatabase, archetype: str) -> set[str]:
    return set(soft_balance_issues(deck, db, archetype))


def _soft_role_bonus_for_card(
    card: str,
    missing_roles: set[str],
    db: DeckDatabase,
) -> float:
    roles = _card_roles(db, card)
    bonus = 0.0
    for issue in missing_roles:
        role = {
            "big_spell": ROLE_BIG_SPELL,
            "small_spell": ROLE_SMALL_SPELL,
            "air_defense": ROLE_AIR,
            "anti_tank": ROLE_ANTI_TANK,
            "defensive": ROLE_DEFENSIVE,
            "anti_swarm": ROLE_ANTI_SWARM,
        }.get(issue)
        if role and role in roles:
            bonus += SOFT_ROLE_BONUS.get(role, 4.0)
    return bonus


def _filler_candidate_score(
    card: str,
    deck: list[str],
    core: list[str],
    db: DeckDatabase,
    archetype: str,
    missing_roles: set[str],
    pair_synergy: PairSynergyFn,
) -> float:
    test_deck = deck + [card]
    syn_with_deck = sum(pair_synergy(card, x) for x in deck) / max(len(deck), 1)
    syn_with_core = sum(pair_synergy(card, c) for c in core) / max(len(core), 1)
    role_bonus = _soft_role_bonus_for_card(card, missing_roles, db)
    lo, hi = _elixir_bounds(archetype)
    mid = (lo + hi) / 2
    elixir_penalty = abs(_avg_elixir(test_deck, db) - mid) * 3.0
    generic_penalty = 4.0 if card in GENERIC_CARDS else 0.0
    return syn_with_deck * 0.45 + syn_with_core * 0.35 + role_bonus * 2.5 - elixir_penalty - generic_penalty


def _pick_best_filler(
    deck: list[str],
    core: list[str],
    db: DeckDatabase,
    pool: set[str],
    archetype: str,
    pair_synergy: PairSynergyFn,
    *,
    allow_spells: bool = True,
    allow_wins: bool = True,
) -> str | None:
    missing = _missing_soft_roles(deck, db, archetype)
    candidates = [
        c for c in pool
        if c not in deck
        and (allow_spells or not is_spell(db, c))
        and (allow_wins or not is_attack_win(c))
    ]
    if not candidates:
        return None

    def rank(card: str) -> float:
        if is_spell(db, card) and count_spells(deck, db) >= MAX_SPELLS:
            return float("-inf")
        if is_attack_win(card) and count_wins(deck, db) >= MAX_WINS:
            return float("-inf")
        return _filler_candidate_score(card, deck, core, db, archetype, missing, pair_synergy)

    best = max(candidates, key=rank)
    return best if rank(best) > float("-inf") else None


def _replace_weakest_filler(
    deck: list[str],
    core: list[str],
    replacement: str,
    pair_synergy: PairSynergyFn,
) -> list[str]:
    core_set = set(core)
    # Prefer dropping a non-attack filler so we never remove an existing push card.
    fillers = [c for c in deck if c not in core_set and not is_attack_win(c)]
    if not fillers:
        fillers = [c for c in deck if c not in core_set]
    if not fillers or replacement in deck:
        return deck
    worst = min(
        fillers,
        key=lambda c: sum(pair_synergy(c, x) for x in deck if x != c),
    )
    out = list(deck)
    out[out.index(worst)] = replacement
    return out


def _trim_excess_spells(
    deck: list[str],
    core: list[str],
    db: DeckDatabase,
    pair_synergy: PairSynergyFn,
) -> list[str]:
    core_set = set(core)
    out = list(deck)
    while count_spells(out, db) > MAX_SPELLS:
        removable = [c for c in out if is_spell(db, c) and c not in core_set]
        if not removable:
            break
        out.remove(min(removable, key=lambda c: sum(pair_synergy(c, x) for x in out if x != c)))
    return out


def _trim_excess_wins(
    deck: list[str],
    core: list[str],
    db: DeckDatabase,
) -> list[str]:
    core_set = set(core)
    out = list(deck)
    while count_wins(out, db) > MAX_WINS:
        extra = [c for c in out if is_attack_win(c) and c not in core_set]
        if not extra:
            break
        out.remove(extra[0])
    return out


def _ensure_win_condition(
    deck: list[str],
    core: list[str],
    db: DeckDatabase,
    pool: set[str],
    archetype: str,
    pair_synergy: PairSynergyFn,
) -> list[str]:
    """Guarantee at least one primary attacking card, preferred by core synergy."""
    if any(is_attack_win(c) for c in deck):
        return deck

    preferred = [
        w for w in ARCHETYPE_PRIMARY_WIN.get(archetype, [])
        if is_attack_win(w)
    ]
    win_pick = next((w for w in preferred if w in pool and w not in deck), None)
    if not win_pick:
        candidates = [
            c for c in pool
            if c not in deck and is_attack_win(c) and not is_spell(db, c)
        ]
        if candidates:
            # Prefer synergy with the player's selected core cards.
            win_pick = max(
                candidates,
                key=lambda c: (
                    sum(pair_synergy(c, x) for x in core) * 3
                    + sum(pair_synergy(c, x) for x in deck)
                ),
            )
    if not win_pick:
        # Last resort: any known attack win even outside arena pool.
        fallback = preferred or [
            "Hog Rider", "Miner", "Battle Ram", "Royal Giant", "Goblin Barrel", "Wall Breakers",
        ]
        win_pick = next((w for w in fallback if w not in deck), None)
    if not win_pick:
        return deck
    if len(deck) >= 8:
        return _replace_weakest_filler(deck, core, win_pick, pair_synergy)
    return deck + [win_pick]


def finalize_deck(
    deck: list[str],
    core: list[str],
    db: DeckDatabase,
    pool: set[str],
    archetype: str,
    pair_synergy: PairSynergyFn,
) -> list[str]:
    """Финализация: жёсткие правила + добор по score (мягкий баланс)."""
    core_set = set(core)
    out = list(dict.fromkeys(core + [c for c in deck if c not in core_set]))

    out = _trim_excess_spells(out, core, db, pair_synergy)
    out = _trim_excess_wins(out, core, db)
    out = _ensure_win_condition(out, core, db, pool, archetype, pair_synergy)

    while len(out) < 8:
        pick = _pick_best_filler(out, core, db, pool, archetype, pair_synergy)
        if not pick:
            break
        out.append(pick)

    out = _trim_excess_spells(out, core, db, pair_synergy)
    out = _trim_excess_wins(out, core, db)
    # Re-ensure after trims — Bandit-like soft wins must not leave the deck without a push card.
    out = _ensure_win_condition(out, core, db, pool, archetype, pair_synergy)

    while len(out) > 8:
        droppable = [c for c in out if c not in core_set and not is_attack_win(c)]
        if not droppable:
            droppable = [c for c in out if c not in core_set]
        if not droppable:
            break
        out.remove(min(droppable, key=lambda c: sum(pair_synergy(c, x) for x in out if x != c)))

    while len(out) < 8:
        pick = _pick_best_filler(
            out,
            core,
            db,
            pool,
            archetype,
            pair_synergy,
            allow_spells=count_spells(out, db) < MAX_SPELLS,
            allow_wins=count_wins(out, db) < MAX_WINS,
        )
        if not pick:
            extra = next((c for c in pool if c not in out), None)
            if not extra:
                break
            out.append(extra)
        else:
            out.append(pick)

    out = _ensure_win_condition(out[:8], core, db, pool, archetype, pair_synergy)
    return out[:8]

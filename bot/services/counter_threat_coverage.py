"""Counter Threat Coverage — validate & minimally repair counter decks.

Does not replace ``counter_engine`` generation. Runs after a candidate counter
deck is built and only mutates slots when a critical coverage gap is found.

Source of Truth: card profiles (``card_is_flying`` / ``card_can_target_air`` /
``is_pure_spell``), not LLM.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from bot.services.card_data import (
    WIN_CONDITIONS,
    card_can_target_air,
    card_has_role,
    card_is_flying,
    get_card_elixir,
    is_building,
    is_pure_spell,
    is_spam_card,
)

logger = logging.getLogger(__name__)

# Soft air chips alone do not force a permanent AA troop (Bats bait).
_SOFT_AIR_ONLY = frozenset({"Bats"})

# Spells / temporary control — never count as reliable standing air defense.
_UNRELIABLE_AIR_ANSWERS = frozenset({
    "Tornado",
    "Zap",
    "The Log",
    "Arrows",
    "Giant Snowball",
    "Barbarian Barrel",
    "Royal Delivery",
    "Clone",
    "Rage",
    "Freeze",
})

# Heavy tanks that need a lasting answer beyond a single spell.
_CRITICAL_TANKS = frozenset({
    "Golem",
    "Electro Giant",
    "Giant",
    "Goblin Giant",
    "Lava Hound",
    "P.E.K.K.A",
    "Mega Knight",
    "Elixir Golem",
    "Royal Giant",
})


ThreatKind = str  # "critical_air" | "critical_tank" | "swarm" | "win_condition"


@dataclass(frozen=True)
class EnemyThreat:
    card: str
    kind: ThreatKind
    tags: tuple[str, ...] = ()


@dataclass
class ThreatCoverageReport:
    critical_threats: list[EnemyThreat] = field(default_factory=list)
    covered_threats: list[EnemyThreat] = field(default_factory=list)
    weakly_covered_threats: list[EnemyThreat] = field(default_factory=list)
    uncovered_threats: list[EnemyThreat] = field(default_factory=list)
    reliable_air_defense: list[str] = field(default_factory=list)
    is_valid: bool = True
    reasons: list[str] = field(default_factory=list)
    repaired: bool = False
    replacements: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "repaired": self.repaired,
            "reasons": list(self.reasons),
            "reliable_air_defense": list(self.reliable_air_defense),
            "critical_threats": [
                {"card": t.card, "kind": t.kind, "tags": list(t.tags)}
                for t in self.critical_threats
            ],
            "uncovered_threats": [
                {"card": t.card, "kind": t.kind, "tags": list(t.tags)}
                for t in self.uncovered_threats
            ],
            "weakly_covered_threats": [
                {"card": t.card, "kind": t.kind, "tags": list(t.tags)}
                for t in self.weakly_covered_threats
            ],
            "replacements": list(self.replacements),
        }


def is_reliable_air_defense(card: str) -> bool:
    """Standing troop/building that can target air — not a one-shot spell."""
    if not card or is_pure_spell(card) or card in _UNRELIABLE_AIR_ANSWERS:
        return False
    return bool(card_can_target_air(card))


def is_critical_air_threat(card: str) -> bool:
    if not card_is_flying(card):
        return False
    if card in _SOFT_AIR_ONLY:
        return False
    return True


def analyze_enemy_threats(opponent_deck: list[str]) -> list[EnemyThreat]:
    """Structured threat list for an opponent deck (facts only)."""
    out: list[EnemyThreat] = []
    seen: set[tuple[str, str]] = set()

    for card in opponent_deck:
        if not card:
            continue
        tags: list[str] = []
        kind: ThreatKind | None = None

        if is_critical_air_threat(card):
            kind = "critical_air"
            tags.append("air_unit")
            if card_can_target_air(card):
                tags.append("ranged_air")
            if card_has_role(card, "splash"):
                tags.append("splash")
            if card_has_role(card, "win_condition"):
                tags.append("win_condition")
            if card_has_role(card, "support") or card in {
                "Electro Dragon",
                "Baby Dragon",
                "Flying Machine",
            }:
                tags.append("support_unit")
        elif card in _CRITICAL_TANKS or (
            card_has_role(card, "win_condition")
            and get_card_elixir(card) >= 5
            and not card_is_flying(card)
        ):
            kind = "critical_tank"
            tags.append("tank")
            if card_has_role(card, "win_condition"):
                tags.append("win_condition")
        elif is_spam_card(card) or card_has_role(card, "swarm"):
            kind = "swarm"
            tags.append("swarm")
        elif card_has_role(card, "win_condition"):
            kind = "win_condition"
            tags.append("win_condition")
            if is_building(card) or card in {"X-Bow", "Mortar"}:
                tags.append("building_win")

        if kind is None:
            continue
        key = (card, kind)
        if key in seen:
            continue
        seen.add(key)
        out.append(EnemyThreat(card=card, kind=kind, tags=tuple(tags)))

    return out


def reliable_air_defense_in_deck(deck: list[str]) -> list[str]:
    return [c for c in deck if is_reliable_air_defense(c)]


def evaluate_threat_coverage(
    counter_deck: list[str],
    opponent_deck: list[str],
) -> ThreatCoverageReport:
    """Deck-level coverage check. Spells alone ≠ reliable air coverage."""
    threats = analyze_enemy_threats(opponent_deck)
    critical = [t for t in threats if t.kind in {"critical_air", "critical_tank"}]
    aa = reliable_air_defense_in_deck(counter_deck)

    report = ThreatCoverageReport(
        critical_threats=list(critical),
        reliable_air_defense=list(aa),
    )

    for threat in threats:
        if threat.kind == "critical_air":
            if aa:
                report.covered_threats.append(threat)
            else:
                # Spell-only / no AA → uncovered critical
                report.uncovered_threats.append(threat)
                report.reasons.append(
                    f"missing reliable air defense vs {threat.card}"
                )
        elif threat.kind == "critical_tank":
            if _has_tank_answer(counter_deck, threat.card):
                report.covered_threats.append(threat)
            else:
                report.weakly_covered_threats.append(threat)
                # Soft for now — do not invalidate solely on tank (air is hard gate)
        elif threat.kind == "swarm":
            if _has_swarm_answer(counter_deck):
                report.covered_threats.append(threat)
            else:
                report.weakly_covered_threats.append(threat)
        else:
            report.covered_threats.append(threat)

    air_critical = [t for t in critical if t.kind == "critical_air"]
    if air_critical and not aa:
        report.is_valid = False
        if "missing reliable air defense" not in " ".join(report.reasons):
            report.reasons.append("missing reliable air defense")

    return report


def _has_tank_answer(deck: list[str], threat: str) -> bool:
    from bot.services.card_matchups import card_counters_target

    for card in deck:
        if is_pure_spell(card):
            continue
        if card_has_role(card, "anti_tank") or is_building(card):
            return True
        if card_counters_target(card, threat) in {"strong", "partial"}:
            return True
    return False


def _has_swarm_answer(deck: list[str]) -> bool:
    return any(
        card_has_role(c, "anti_swarm")
        or card_has_role(c, "splash")
        or c in {"The Log", "Zap", "Arrows", "Barbarian Barrel", "Giant Snowball"}
        for c in deck
    )


def _locked_slots(deck: list[str]) -> set[str]:
    locked = {c for c in deck if c in WIN_CONDITIONS}
    if locked:
        return locked
    soft = [c for c in deck if card_has_role(c, "win_condition")]
    return {soft[0]} if soft else set()


def _drop_priority(card: str, opponent_deck: list[str]) -> tuple:
    """Lower tuple = better to drop when inserting AA."""
    # Prefer dropping ground buildings that don't hit air, then low-value cycle.
    no_air = 0 if (is_building(card) and not card_can_target_air(card)) else 1
    is_aa = 0 if is_reliable_air_defense(card) else 1  # never prefer dropping AA
    # Invert: we want to drop non-AA first → higher is_aa means keep AA
    keep_aa = 0 if not is_reliable_air_defense(card) else 10
    elixir = get_card_elixir(card)
    spellish = 0 if is_pure_spell(card) else 1
    return (keep_aa, no_air, spellish, -elixir, card)


def _air_repair_candidates(
    deck: list[str],
    pool: set[str],
    ranked: list[tuple[float, str]],
    opponent_deck: list[str],
) -> list[str]:
    banned_opp = set(opponent_deck)
    deck_set = set(deck)
    out: list[str] = []

    for _score, card in ranked:
        if card in deck_set or card in banned_opp or card not in pool:
            continue
        if not is_reliable_air_defense(card):
            continue
        out.append(card)

    if not out:
        for card in sorted(pool):
            if card in deck_set or card in banned_opp:
                continue
            if is_reliable_air_defense(card):
                out.append(card)
    return out


def repair_critical_air_gap(
    deck: list[str],
    opponent_deck: list[str],
    *,
    pool: set[str],
    ranked: list[tuple[float, str]],
) -> tuple[list[str], list[dict[str, str]]]:
    """Minimal one-slot swap to add reliable air defense. Preserves win condition."""
    from bot.services.counter_engine import _can_swap_in

    current = list(deck)
    if len(current) != 8:
        return current, []
    if reliable_air_defense_in_deck(current):
        return current, []

    locked = _locked_slots(current)
    candidates = _air_repair_candidates(current, pool, ranked, opponent_deck)
    if not candidates:
        logger.warning(
            "Counter threat repair: no reliable AA in pool for vs %s",
            [c for c in opponent_deck if is_critical_air_threat(c)],
        )
        return current, []

    droppable = [c for c in current if c not in locked]
    if not droppable:
        # Last resort: allow dropping a non-primary if everything locked oddly
        droppable = list(current)

    droppable.sort(key=lambda c: _drop_priority(c, opponent_deck))

    replacements: list[dict[str, str]] = []
    for drop in droppable:
        trial_base = [c for c in current if c != drop]
        for pick in candidates:
            if pick in trial_base or pick == drop:
                continue
            # Critical air gap: allow AA even when role caps would block a soft swap.
            if pick in trial_base:
                continue
            if not _can_swap_in(pick, trial_base, drop):
                # Still allow if pick is dedicated AA and drop is not AA / not locked.
                if is_reliable_air_defense(drop):
                    continue
            idx = current.index(drop)
            trial = list(current)
            trial[idx] = pick
            if len(trial) != 8 or len(set(trial)) != 8:
                continue
            if not reliable_air_defense_in_deck(trial):
                continue
            # Keep at least one win condition if we had one.
            if locked and not (set(trial) & locked) and not any(
                c in WIN_CONDITIONS or card_has_role(c, "win_condition") for c in trial
            ):
                continue
            replacements.append({"drop": drop, "pick": pick, "reason": "critical_air"})
            logger.info(
                "Counter threat repair: %s → %s (critical air coverage)",
                drop,
                pick,
            )
            return trial, replacements

    return current, []


def ensure_counter_threat_coverage(
    deck: list[str],
    opponent_deck: list[str],
    *,
    pool: set[str] | None = None,
    ranked: list[tuple[float, str]] | None = None,
    preferred: list[str] | None = None,
    arena_id: int | None = None,
    trophies: int | None = None,
) -> tuple[list[str], ThreatCoverageReport]:
    """Validate coverage; minimally repair critical air gaps; re-check.

    Returns (deck, report). Does not rebuild the whole counter deck.
    """
    del preferred, arena_id, trophies  # reserved for future soft repairs
    cards = [c for c in deck if c][:8]
    report = evaluate_threat_coverage(cards, opponent_deck)

    if report.is_valid:
        return cards, report

    air_gap = any(t.kind == "critical_air" for t in report.uncovered_threats)
    if not air_gap:
        return cards, report

    pool_set = set(pool or [])
    ranked_list = list(ranked or [])
    if not pool_set:
        from bot.services.card_data import CARD_META

        pool_set = set(CARD_META.keys())

    repaired, swaps = repair_critical_air_gap(
        cards,
        opponent_deck,
        pool=pool_set,
        ranked=ranked_list,
    )
    report = evaluate_threat_coverage(repaired, opponent_deck)
    if swaps:
        report.repaired = True
        report.replacements = list(swaps)

    # Soft sanity: size / duplicates only — full archetype sanity is for builder decks.
    if len(repaired) == 8 and len(set(repaired)) == 8:
        try:
            from bot.services.deck_sanity_validator import validate_deck_sanity

            sanity = validate_deck_sanity(repaired)
            if not sanity.checks.get("anti_air", True):
                # Should be fixed by repair; log if still weak for meta axes
                logger.debug(
                    "Counter deck sanity anti_air after repair: %s",
                    sanity.checks.get("anti_air"),
                )
        except Exception:
            logger.debug("Counter deck sanity skipped", exc_info=True)

    return repaired[:8], report

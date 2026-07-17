"""Интеллектуальный генератор колод — 7 шагов."""

from __future__ import annotations

from dataclasses import dataclass

from bot.services.card_data import WIN_CONDITIONS, get_card_elixir
from bot.services.card_matchups import calculate_deck_synergy, synergy_between
from bot.services.deck_builder.constants import (
    ARCHETYPE_ANCHORS,
    ARCHETYPE_ELIXIR,
    ARCHETYPE_PRIMARY_WIN,
    DEFAULT_ELIXIR_MAX,
    DEFAULT_ELIXIR_MIN,
    FILL_PRIORITY,
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
    ROLE_CYCLE,
    ROLE_DEFENSIVE,
    ROLE_DPS,
    ROLE_MINI_TANK,
    ROLE_SMALL_SPELL,
    ROLE_WIN,
    SYNERGY_PARTIAL,
    SYNERGY_STRONG,
    SYNERGY_WEAK,
    WEIGHT_ARCHETYPE,
    WEIGHT_CARD_MATCH,
    WEIGHT_ELIXIR,
    WEIGHT_POPULARITY,
    WEIGHT_SYNERGY,
)
from bot.services.deck_builder.loader import DeckDatabase, DeckRecord, get_database


@dataclass
class BuildResult:
    deck: list[str]
    archetype: str
    average_elixir: float
    synergy_score: float
    confidence: float
    source_deck_id: str | None = None
    balanced: bool = True


@dataclass
class ScoredDeck:
    record: DeckRecord
    score: float
    confidence: float
    overlap: int


def _avg_elixir(cards: list[str], db: DeckDatabase) -> float:
    if not cards:
        return 0.0
    total = sum(db.get_card(c).elixir if db.get_card(c) else get_card_elixir(c) for c in cards)
    return round(total / len(cards), 2)


def _card_roles(db: DeckDatabase, name: str) -> frozenset[str]:
    rec = db.get_card(name)
    return rec.roles if rec else frozenset()


def _is_spell(db: DeckDatabase, name: str) -> bool:
    roles = _card_roles(db, name)
    return "spell" in roles or ROLE_SMALL_SPELL in roles or ROLE_BIG_SPELL in roles


def _is_win(db: DeckDatabase, name: str) -> bool:
    return name in WIN_CONDITIONS or ROLE_WIN in _card_roles(db, name)


def _detect_archetype(core: list[str]) -> str:
    core_wins = [c for c in core if c in WIN_CONDITIONS]
    for win in core_wins:
        if win in {"Lava Hound", "Balloon"}:
            return "Lava"
        if win in {"Golem", "Giant", "Electro Giant"}:
            return "Beatdown"
        if win == "Royal Giant":
            return "Royal Giant"
        if win in {"Hog Rider", "Battle Ram"}:
            return "Cycle"
        if win == "Goblin Barrel":
            return "Log Bait"
        if win == "Graveyard":
            return "Graveyard"
        if win in {"X-Bow", "Mortar"}:
            return "Siege"
        if win in {"P.E.K.K.A", "Mega Knight", "Royal Ghost", "Bandit"}:
            return "Bridge Spam"
        if win == "Miner":
            return "Control"

    core_set = set(core)
    best, best_hits = "Meta", 0
    for archetype, anchors in ARCHETYPE_ANCHORS.items():
        hits = len(core_set & anchors)
        if hits > best_hits:
            best_hits, best = hits, archetype
    if best_hits > 0:
        return best

    if any(c in {"X-Bow", "Mortar"} for c in core):
        return "Siege"
    avg = _avg_elixir(core, get_database())
    if avg <= 3.3:
        return "Cycle"
    if avg >= 4.0:
        return "Beatdown"
    return best


def _pair_synergy(db: DeckDatabase, a: str, b: str) -> int:
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


def _meaningful_overlap(core: list[str], template_cards: list[str]) -> list[str]:
    core_set = set(core)
    return [c for c in template_cards if c in core_set and c not in GENERIC_CARDS]


def _template_is_usable(core: list[str], template: DeckRecord) -> bool:
    core_set = set(core)
    meaningful = _meaningful_overlap(core, list(template.cards))
    if len(meaningful) >= 2:
        return True

    primary = ARCHETYPE_PRIMARY_WIN.get(template.archetype, [])
    if any(w in core_set for w in primary) and len(meaningful) >= 1:
        return True

    if any(c in WIN_CONDITIONS for c in core) and len(meaningful) >= 1:
        return True

    template_wins = [c for c in template.cards if c in WIN_CONDITIONS]
    if template_wins and not any(w in core_set for w in template_wins):
        return False

    return len(meaningful) >= 1


def _overlap_score(core: list[str], template_cards: list[str]) -> float:
    core_set = set(core)
    score = 0.0
    for card in template_cards:
        if card not in core_set:
            continue
        score += 0.5 if card in GENERIC_CARDS else 4.0
        if card in WIN_CONDITIONS:
            score += 6.0
    return score


def _core_synergy_with_deck(db: DeckDatabase, core: list[str], deck_cards: list[str]) -> float:
    total, n = 0.0, 0
    for c in core:
        for d in deck_cards:
            if c != d:
                total += _pair_synergy(db, c, d)
                n += 1
    return total / n if n else 0.0


def _score_deck_match(
    db: DeckDatabase,
    core: list[str],
    archetype: str,
    record: DeckRecord,
) -> ScoredDeck | None:
    if not _template_is_usable(core, record):
        return None

    weighted = _overlap_score(core, list(record.cards))
    card_score = weighted * (WEIGHT_CARD_MATCH / 4)
    arch_score = WEIGHT_ARCHETYPE if record.archetype == archetype else 0.0
    elixir_diff = abs(record.avg_elixir - _avg_elixir(core, db))
    elixir_score = max(0.0, WEIGHT_ELIXIR - elixir_diff * 5.0)
    syn_score = (_core_synergy_with_deck(db, core, list(record.cards)) / 100.0) * WEIGHT_SYNERGY
    pop_score = (record.popularity / 100.0) * WEIGHT_POPULARITY

    raw = card_score + arch_score + elixir_score + syn_score + pop_score
    max_possible = 4 * WEIGHT_CARD_MATCH + WEIGHT_ARCHETYPE + WEIGHT_ELIXIR + WEIGHT_SYNERGY + WEIGHT_POPULARITY
    confidence = min(100.0, (raw / max_possible) * 100.0)
    overlap = len(_meaningful_overlap(core, list(record.cards)))
    return ScoredDeck(record=record, score=raw, confidence=confidence, overlap=overlap)


def _rank_similar_decks(db: DeckDatabase, core: list[str], archetype: str, *, limit: int = 12) -> list[ScoredDeck]:
    indices = db.candidate_indices(core)
    scored: list[ScoredDeck] = []
    for idx in indices:
        sd = _score_deck_match(db, core, archetype, db.decks[idx])
        if sd:
            scored.append(sd)
    if not scored:
        for record in db.decks:
            sd = _score_deck_match(db, core, archetype, record)
            if sd:
                scored.append(sd)
    scored.sort(key=lambda x: (-x.score, -x.confidence, -x.overlap))
    return scored[:limit]


def _elixir_bounds(archetype: str) -> tuple[float, float]:
    return ARCHETYPE_ELIXIR.get(archetype, (DEFAULT_ELIXIR_MIN, DEFAULT_ELIXIR_MAX))


def _count_spells(deck: list[str], db: DeckDatabase) -> int:
    return sum(1 for c in deck if _is_spell(db, c))


def _count_wins(deck: list[str], db: DeckDatabase) -> int:
    return sum(1 for c in deck if _is_win(db, c))


def _balance_issues(deck: list[str], db: DeckDatabase, archetype: str) -> list[str]:
    lo, hi = _elixir_bounds(archetype)
    issues: list[str] = []
    avg = _avg_elixir(deck, db)

    if not any(_is_win(db, c) for c in deck):
        issues.append("win_condition")
    if _count_wins(deck, db) > MAX_WINS:
        issues.append("too_many_wins")
    if not any(ROLE_BIG_SPELL in _card_roles(db, c) for c in deck):
        issues.append("big_spell")
    if not any(ROLE_SMALL_SPELL in _card_roles(db, c) for c in deck):
        issues.append("small_spell")
    if _count_spells(deck, db) > MAX_SPELLS:
        issues.append("too_many_spells")
    if sum(1 for c in deck if ROLE_AIR in _card_roles(db, c)) < 2:
        issues.append("air_defense")
    if not any(ROLE_ANTI_TANK in _card_roles(db, c) for c in deck):
        issues.append("anti_tank")
    if not any(ROLE_DEFENSIVE in _card_roles(db, c) for c in deck):
        issues.append("defensive")
    if not any(ROLE_ANTI_SWARM in _card_roles(db, c) for c in deck):
        issues.append("anti_swarm")
    if avg < lo - 0.4 or avg > hi + 0.4:
        issues.append("elixir")
    return issues


def _pick_for_role(
    deck: list[str],
    db: DeckDatabase,
    pool: set[str],
    role: str,
    core: list[str],
    archetype: str,
) -> str | None:
    lo, hi = _elixir_bounds(archetype)
    mid = (lo + hi) / 2
    candidates = [
        c for c in pool
        if c not in deck and role in _card_roles(db, c)
    ]
    if not candidates:
        return None

    def rank(card: str) -> tuple[float, float]:
        syn = sum(_pair_synergy(db, card, x) for x in deck) / max(len(deck), 1)
        elixir_penalty = abs(_avg_elixir(deck + [card], db) - mid)
        return (-syn, elixir_penalty)

    return min(candidates, key=rank)


def _fillers_from_template(core: list[str], template: DeckRecord, db: DeckDatabase) -> list[str]:
    core_set = set(core)
    core_has_win = any(c in WIN_CONDITIONS for c in core)
    wins = [c for c in template.cards if c not in core_set and c in WIN_CONDITIONS]
    troops = [
        c for c in template.cards
        if c not in core_set and c not in WIN_CONDITIONS and not _is_spell(db, c) and c not in GENERIC_CARDS
    ]
    spells = [
        c for c in template.cards
        if c not in core_set and _is_spell(db, c) and c not in GENERIC_CARDS
    ]
    generic = [c for c in template.cards if c not in core_set and c in GENERIC_CARDS]
    ordered = ([] if core_has_win else wins[:1]) + troops + spells + generic
    return ordered[:4]


def _finalize_deck(
    deck: list[str],
    core: list[str],
    db: DeckDatabase,
    pool: set[str],
    archetype: str,
) -> list[str]:
    core_set = set(core)
    out = list(dict.fromkeys(core + [c for c in deck if c not in core_set]))

    while _count_spells(out, db) > MAX_SPELLS:
        removable = [c for c in out if _is_spell(db, c) and c not in core_set]
        if not removable:
            break
        out.remove(min(removable, key=lambda c: sum(_pair_synergy(db, c, x) for x in out if x != c)))

    while _count_wins(out, db) > MAX_WINS:
        extra = [c for c in out if _is_win(db, c) and c not in core_set]
        if not extra:
            break
        out.remove(extra[0])

    if not any(_is_win(db, c) for c in out):
        preferred = ARCHETYPE_PRIMARY_WIN.get(archetype, [])
        win_pick = next((w for w in preferred if w in pool and w not in out), None)
        if not win_pick:
            candidates = [c for c in pool if c not in out and c in WIN_CONDITIONS and not _is_spell(db, c)]
            win_pick = max(candidates, key=lambda c: sum(_pair_synergy(db, c, x) for x in out), default=None)
        if win_pick:
            if len(out) >= 8:
                fillers = [c for c in out if c not in core_set]
                if fillers:
                    worst = min(fillers, key=lambda c: sum(_pair_synergy(db, c, x) for x in out))
                    out[out.index(worst)] = win_pick
            else:
                out.append(win_pick)

    issues = _balance_issues(out, db, archetype)
    for role in FILL_PRIORITY:
        while len(out) < 8 and role in issues:
            pick = _pick_for_role(out, db, pool, role, core, archetype)
            if not pick:
                break
            if _is_spell(db, pick) and _count_spells(out, db) >= MAX_SPELLS:
                break
            if _is_win(db, pick) and _count_wins(out, db) >= MAX_WINS:
                break
            out.append(pick)
            issues = _balance_issues(out, db, archetype)

    extras = sorted(
        [c for c in pool if c not in out and not _is_spell(db, c)],
        key=lambda c: -sum(_pair_synergy(db, c, x) for x in out),
    )
    for card in extras:
        if len(out) >= 8:
            break
        if _is_win(db, card) and _count_wins(out, db) >= MAX_WINS:
            continue
        out.append(card)

    while _count_spells(out, db) > MAX_SPELLS:
        removable = [c for c in out if _is_spell(db, c) and c not in core_set]
        if not removable:
            break
        out.remove(min(removable, key=lambda c: sum(_pair_synergy(db, c, x) for x in out)))

    while len(out) > 8:
        droppable = [c for c in out if c not in core_set]
        if not droppable:
            break
        out.remove(min(droppable, key=lambda c: sum(_pair_synergy(db, c, x) for x in out)))

    while len(out) < 8:
        extra = next((c for c in pool if c not in out and not _is_spell(db, c)), None)
        if not extra:
            break
        out.append(extra)

    return out[:8]


def _build_one_variant(
    core: list[str],
    db: DeckDatabase,
    pool: set[str],
    archetype: str,
    template: DeckRecord | None = None,
    *,
    filler_skip: int = 0,
) -> list[str]:
    fillers = _fillers_from_template(core, template, db) if template else []
    if filler_skip:
        fillers = fillers[filler_skip:]
    deck = list(core)
    for card in fillers:
        if len(deck) >= 8:
            break
        if card not in deck:
            deck.append(card)
    arch = template.archetype if template else archetype
    return _finalize_deck(deck, core, db, pool, arch)


def build_deck_from_core(
    core: list[str],
    pool: set[str] | None = None,
    *,
    db: DeckDatabase | None = None,
) -> BuildResult:
    if len(core) != 4 or len(set(core)) != 4:
        raise ValueError("Нужно ровно 4 уникальные карты")

    db = db or get_database()
    if pool is None:
        pool = set(db.cards.keys())
    pool = set(pool) | set(core)

    archetype = _detect_archetype(core)
    ranked = _rank_similar_decks(db, core, archetype, limit=6)
    best = ranked[0] if ranked else None
    deck = _build_one_variant(core, db, pool, archetype, best.record if best else None)
    issues = _balance_issues(deck, db, archetype)
    synergy_score, _ = calculate_deck_synergy(deck)

    return BuildResult(
        deck=deck,
        archetype=archetype,
        average_elixir=_avg_elixir(deck, db),
        synergy_score=round(synergy_score, 1),
        confidence=round(best.confidence if best else 35.0, 1),
        source_deck_id=best.record.id if best else None,
        balanced=len(issues) == 0,
    )


def build_multiple_decks(
    core: list[str],
    pool: set[str] | None = None,
    *,
    limit: int = 6,
) -> list[BuildResult]:
    db = get_database()
    if pool is None:
        pool = set(db.cards.keys())
    pool = set(pool) | set(core)

    archetype = _detect_archetype(core)
    ranked = _rank_similar_decks(db, core, archetype, limit=limit * 5)

    results: list[BuildResult] = []
    seen: set[str] = set()

    for sd in ranked:
        if len(results) >= limit:
            break
        for filler_skip in (0, 1, 2):
            deck = _build_one_variant(core, db, pool, archetype, sd.record, filler_skip=filler_skip)
            if len(deck) != 8 or "win_condition" in _balance_issues(deck, db, sd.record.archetype):
                continue
            key = _deck_key(deck)
            if key in seen:
                continue
            seen.add(key)
            synergy_score, _ = calculate_deck_synergy(deck)
            results.append(BuildResult(
                deck=deck,
                archetype=sd.record.archetype,
                average_elixir=_avg_elixir(deck, db),
                synergy_score=round(synergy_score, 1),
                confidence=round(sd.confidence, 1),
                source_deck_id=sd.record.id,
                balanced=len(_balance_issues(deck, db, sd.record.archetype)) == 0,
            ))
            break

    if not results:
        deck = _build_one_variant(core, db, pool, archetype)
        key = _deck_key(deck)
        seen.add(key)
        synergy_score, _ = calculate_deck_synergy(deck)
        results.append(BuildResult(
            deck=deck,
            archetype=archetype,
            average_elixir=_avg_elixir(deck, db),
            synergy_score=round(synergy_score, 1),
            confidence=35.0,
            balanced=len(_balance_issues(deck, db, archetype)) == 0,
        ))

    fallback = _finalize_deck(core, core, db, pool, archetype)
    fkey = _deck_key(fallback)
    if fkey not in seen and len(results) < limit:
        synergy_score, _ = calculate_deck_synergy(fallback)
        results.append(BuildResult(
            deck=fallback,
            archetype=archetype,
            average_elixir=_avg_elixir(fallback, db),
            synergy_score=round(synergy_score, 1),
            confidence=30.0,
            balanced=len(_balance_issues(fallback, db, archetype)) == 0,
        ))

    results.sort(key=lambda r: -(r.synergy_score + r.confidence))
    return _dedupe_build_results(results)[:limit]


def _deck_key(deck: list[str]) -> str:
    return "|".join(sorted(deck))


def _dedupe_build_results(results: list[BuildResult]) -> list[BuildResult]:
    out: list[BuildResult] = []
    seen: set[str] = set()
    for item in results:
        key = _deck_key(item.deck)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out

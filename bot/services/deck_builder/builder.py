"""Интеллектуальный генератор колод — 7 шагов."""

from __future__ import annotations

from dataclasses import dataclass

from bot.services.card_matchups import calculate_deck_synergy, synergy_between
from bot.services.card_data import get_card_elixir, WIN_CONDITIONS
from bot.services.deck_builder.constants import (
    ARCHETYPE_ANCHORS,
    ARCHETYPE_ELIXIR,
    DEFAULT_ELIXIR_MAX,
    DEFAULT_ELIXIR_MIN,
    FILL_PRIORITY,
    KNOWN_SYNERGY_PAIRS,
    MATCH_CONFIDENCE_THRESHOLD,
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
    SYNERGY_MIN_THRESHOLD,
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
    source_deck_name: str | None = None


@dataclass
class ScoredDeck:
    record: DeckRecord
    score: float
    confidence: float
    overlap: int


def _avg_elixir(cards: list[str]) -> float:
    if not cards:
        return 0.0
    return round(sum(get_card_elixir(c) for c in cards) / len(cards), 2)


def _card_roles(db: DeckDatabase, name: str) -> frozenset[str]:
    rec = db.get_card(name)
    return rec.roles if rec else frozenset()


def _core_roles(db: DeckDatabase, core: list[str]) -> dict[str, list[str]]:
    return {card: sorted(_card_roles(db, card)) for card in core}


def _detect_archetype(db: DeckDatabase, core: list[str]) -> str:
    """Шаг 2: определить архетип по якорям или ролям."""
    core_set = set(core)
    best_arch = "Meta"
    best_hits = 0

    for archetype, anchors in ARCHETYPE_ANCHORS.items():
        hits = len(core_set & anchors)
        if hits > best_hits:
            best_hits = hits
            best_arch = archetype

    if best_hits > 0:
        return best_arch

    roles_union: set[str] = set()
    for card in core:
        roles_union |= set(_card_roles(db, card))

    if ROLE_WIN in roles_union and any(c in WIN_CONDITIONS for c in core):
        wins = [c for c in core if c in WIN_CONDITIONS]
        if any(c in {"Lava Hound", "Balloon"} for c in wins + core):
            return "Lava"
        if any(c in {"Golem", "Giant", "Electro Giant"} for c in wins):
            return "Beatdown"
        if any(c in {"Royal Giant"} for c in wins):
            return "Royal Giant"
        if any(c in {"Hog Rider", "Battle Ram"} for c in wins):
            return "Cycle"
        if any(c in {"Goblin Barrel"} for c in wins):
            return "Log Bait"
        if any(c in {"Graveyard"} for c in wins):
            return "Graveyard"
        if any(c in {"X-Bow", "Mortar"} for c in wins + core):
            return "Siege"
        if any(c in {"P.E.K.K.A", "Mega Knight"} for c in wins):
            return "Bridge Spam"
        if any(c in {"Miner"} for c in wins):
            return "Control"

    avg = _avg_elixir(core)
    if avg <= 3.3 and ROLE_CYCLE in roles_union:
        return "Cycle"
    if avg >= 4.0 and "tank" in roles_union:
        return "Beatdown"

    return best_arch


def _pair_synergy(db: DeckDatabase, a: str, b: str) -> int:
    """Шаг 6: совместимость пары 0–100."""
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


def _deck_synergy_score(db: DeckDatabase, cards: list[str]) -> float:
    if len(cards) < 2:
        return 50.0
    total = 0.0
    pairs = 0
    for i, a in enumerate(cards):
        for b in cards[i + 1:]:
            total += _pair_synergy(db, a, b)
            pairs += 1
    return round(total / pairs, 1) if pairs else 50.0


def _core_synergy_with_deck(db: DeckDatabase, core: list[str], deck_cards: list[str]) -> float:
    if not core or not deck_cards:
        return 0.0
    total = 0.0
    n = 0
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
) -> ScoredDeck:
    """Шаг 3: рейтинг похожести."""
    core_set = set(core)
    deck_set = set(record.cards)
    overlap = len(core_set & deck_set)

    card_score = overlap * WEIGHT_CARD_MATCH
    arch_score = WEIGHT_ARCHETYPE if record.archetype == archetype else 0.0

    target_avg = _avg_elixir(core)
    elixir_diff = abs(record.avg_elixir - target_avg)
    elixir_score = max(0.0, WEIGHT_ELIXIR - elixir_diff * 5.0)

    syn = _core_synergy_with_deck(db, core, list(record.cards))
    syn_score = (syn / 100.0) * WEIGHT_SYNERGY

    pop_score = (record.popularity / 100.0) * WEIGHT_POPULARITY

    raw = card_score + arch_score + elixir_score + syn_score + pop_score
    max_possible = 4 * WEIGHT_CARD_MATCH + WEIGHT_ARCHETYPE + WEIGHT_ELIXIR + WEIGHT_SYNERGY + WEIGHT_POPULARITY
    confidence = min(100.0, (raw / max_possible) * 100.0)

    return ScoredDeck(record=record, score=raw, confidence=confidence, overlap=overlap)


def _rank_similar_decks(
    db: DeckDatabase,
    core: list[str],
    archetype: str,
    *,
    limit: int = 12,
) -> list[ScoredDeck]:
    indices = db.candidate_indices(core)
    scored: list[ScoredDeck] = []
    for idx in indices:
        sd = _score_deck_match(db, core, archetype, db.decks[idx])
        if sd.overlap >= 1 or sd.record.archetype == archetype:
            scored.append(sd)
    if not scored:
        for record in db.decks:
            scored.append(_score_deck_match(db, core, archetype, record))
    scored.sort(key=lambda x: (-x.score, -x.confidence, -x.overlap))
    return scored[:limit]


def _elixir_bounds(archetype: str) -> tuple[float, float]:
    return ARCHETYPE_ELIXIR.get(archetype, (DEFAULT_ELIXIR_MIN, DEFAULT_ELIXIR_MAX))


def _has_role(deck: list[str], db: DeckDatabase, role: str) -> bool:
    for card in deck:
        if role in _card_roles(db, card):
            return True
    return False


def _count_role(deck: list[str], db: DeckDatabase, role: str) -> int:
    return sum(1 for c in deck if role in _card_roles(db, c))


def _balance_ok(deck: list[str], db: DeckDatabase, archetype: str) -> tuple[bool, list[str]]:
    """Шаг 5: проверка баланса."""
    issues: list[str] = []
    lo, hi = _elixir_bounds(archetype)
    avg = _avg_elixir(deck)

    if not _has_role(deck, db, ROLE_WIN) and not any(c in WIN_CONDITIONS for c in deck):
        issues.append("win_condition")
    if not _has_role(deck, db, ROLE_BIG_SPELL):
        issues.append("big_spell")
    if not _has_role(deck, db, ROLE_SMALL_SPELL):
        issues.append("small_spell")
    if _count_role(deck, db, ROLE_AIR) < 2:
        issues.append("air_defense")
    if not _has_role(deck, db, ROLE_ANTI_TANK):
        issues.append("anti_tank")
    if not _has_role(deck, db, ROLE_DEFENSIVE):
        issues.append("defensive")
    if not _has_role(deck, db, ROLE_ANTI_SWARM):
        issues.append("anti_swarm")
    if avg < lo - 0.3 or avg > hi + 0.3:
        issues.append("elixir")

    return len(issues) == 0, issues


def _pick_for_role(
    deck: list[str],
    db: DeckDatabase,
    pool: set[str],
    role: str,
    core: list[str],
    archetype: str,
) -> str | None:
    lo, hi = _elixir_bounds(archetype)
    candidates = [
        c for c in pool
        if c not in deck and role in _card_roles(db, c)
    ]
    if not candidates:
        return None

    def rank(card: str) -> tuple[float, float, float]:
        syn = sum(_pair_synergy(db, card, x) for x in deck) / max(len(deck), 1)
        trial_avg = _avg_elixir(deck + [card])
        elixir_penalty = abs(trial_avg - (lo + hi) / 2)
        core_bonus = 2.0 if card in core else 0.0
        return (-syn - core_bonus, elixir_penalty, get_card_elixir(card))

    return min(candidates, key=rank)


def _auto_complete(
    deck: list[str],
    core: list[str],
    db: DeckDatabase,
    pool: set[str],
    archetype: str,
    template_fillers: list[str] | None = None,
) -> list[str]:
    """Шаг 4: достроить колоду по ролям."""
    out = list(dict.fromkeys(deck))
    core_set = set(core)

    if template_fillers:
        for card in template_fillers:
            if len(out) >= 8:
                break
            if card in pool and card not in out:
                out.append(card)

    _, issues = _balance_ok(out, db, archetype)
    fill_issues = list(issues)

    for role in FILL_PRIORITY:
        while len(out) < 8:
            need = role in fill_issues or (
                role == ROLE_WIN and not any(c in WIN_CONDITIONS for c in out)
            )
            if not need and _has_role(out, db, role):
                continue
            pick = _pick_for_role(out, db, pool, role, core, archetype)
            if not pick:
                break
            out.append(pick)
            fill_issues = _balance_ok(out, db, archetype)[1]
            if role not in fill_issues:
                break

    extras = sorted(
        [c for c in pool if c not in out],
        key=lambda c: -sum(_pair_synergy(db, c, x) for x in out),
    )
    for card in extras:
        if len(out) >= 8:
            break
        out.append(card)

    return out[:8]


def _replace_weak_fillers(
    deck: list[str],
    core: list[str],
    db: DeckDatabase,
    pool: set[str],
    archetype: str,
) -> list[str]:
    """Шаг 6: заменить слабые добавленные карты."""
    core_set = set(core)
    out = list(deck)
    score = _deck_synergy_score(db, out)
    if score >= SYNERGY_MIN_THRESHOLD:
        return out

    fillers = [c for c in out if c not in core_set]
    for _ in range(3):
        if score >= SYNERGY_MIN_THRESHOLD:
            break
        worst = min(
            fillers,
            key=lambda c: sum(_pair_synergy(db, c, x) for x in out if x != c),
            default=None,
        )
        if not worst:
            break
        candidates = [
            c for c in pool
            if c not in out and c not in core_set
        ]
        if not candidates:
            break
        best = max(
            candidates,
            key=lambda c: sum(_pair_synergy(db, c, x) for x in out if x != worst),
        )
        idx = out.index(worst)
        out[idx] = best
        fillers = [c for c in out if c not in core_set]
        score = _deck_synergy_score(db, out)

    return out


def build_deck_from_core(
    core: list[str],
    pool: set[str] | None = None,
    *,
    db: DeckDatabase | None = None,
) -> BuildResult:
    """
    Главная точка входа: 4 карты ядра → полная колода 8 карт.
    Первые 4 карты не изменяются.
    """
    if len(core) != 4 or len(set(core)) != 4:
        raise ValueError("Нужно ровно 4 уникальные карты")

    db = db or get_database()
    if pool is None:
        pool = set(db.cards.keys())
    pool = set(pool) | set(core)

    archetype = _detect_archetype(db, core)
    ranked = _rank_similar_decks(db, core, archetype, limit=8)

    best = ranked[0] if ranked else None
    source_id: str | None = None
    source_name: str | None = None
    confidence = best.confidence if best else 0.0

    core_set = set(core)
    if best and confidence >= MATCH_CONFIDENCE_THRESHOLD:
        fillers = [c for c in best.record.cards if c not in core_set]
        deck = list(core) + fillers[:4]
        source_id = best.record.id
        source_name = best.record.name
    elif best and best.overlap >= 2:
        fillers = [c for c in best.record.cards if c not in core_set]
        deck = list(core) + fillers[:4]
        source_id = best.record.id
        source_name = best.record.name
        confidence = max(confidence, 60.0)
    else:
        deck = list(core)
        fillers = [c for c in best.record.cards if c not in core_set] if best else None
        deck = _auto_complete(deck, core, db, pool, archetype, fillers)

    if len(deck) < 8:
        deck = _auto_complete(deck, core, db, pool, archetype)

    deck = _replace_weak_fillers(deck, core, db, pool, archetype)

    ok, issues = _balance_ok(deck, db, archetype)
    if not ok:
        deck = _auto_complete(deck, core, db, pool, archetype)

    synergy_score, _ = calculate_deck_synergy(deck)
    if synergy_score < SYNERGY_MIN_THRESHOLD:
        synergy_score = _deck_synergy_score(db, deck)

    return BuildResult(
        deck=deck[:8],
        archetype=archetype,
        average_elixir=_avg_elixir(deck[:8]),
        synergy_score=round(synergy_score, 1),
        confidence=round(confidence, 1),
        source_deck_id=source_id,
        source_deck_name=source_name,
    )


def build_multiple_decks(
    core: list[str],
    pool: set[str] | None = None,
    *,
    limit: int = 6,
) -> list[BuildResult]:
    """Несколько вариантов из топ похожих колод."""
    db = get_database()
    if pool is None:
        pool = set(db.cards.keys())
    pool = set(pool) | set(core)

    archetype = _detect_archetype(db, core)
    ranked = _rank_similar_decks(db, core, archetype, limit=limit * 2)

    results: list[BuildResult] = []
    seen: set[str] = set()

    for sd in ranked:
        if len(results) >= limit:
            break
        core_set = set(core)
        fillers = [c for c in sd.record.cards if c not in core_set][:4]
        deck = list(core) + fillers
        if len(deck) < 8:
            deck = _auto_complete(deck, core, db, pool, sd.record.archetype, fillers)
        deck = _replace_weak_fillers(deck, core, db, pool, sd.record.archetype)
        key = "|".join(sorted(deck))
        if key in seen or len(deck) != 8:
            continue
        seen.add(key)

        synergy_score, _ = calculate_deck_synergy(deck)
        results.append(BuildResult(
            deck=deck,
            archetype=sd.record.archetype,
            average_elixir=_avg_elixir(deck),
            synergy_score=round(synergy_score, 1),
            confidence=round(sd.confidence, 1),
            source_deck_id=sd.record.id,
            source_deck_name=sd.record.name,
        ))

    if not results:
        results.append(build_deck_from_core(core, pool, db=db))

    return results[:limit]

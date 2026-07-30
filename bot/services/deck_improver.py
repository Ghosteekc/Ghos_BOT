"""Точечное улучшение колоды — сохраняет win-condition и спеллы игрока.

Процесс:
  DeckIntent → gaps → для КАЖДОГО gap полный поиск решения по ступеням
  ideal → good → acceptable → compromise → any improvement.
Оставлять gap незакрытым можно только если ни одна карта не улучшает ситуацию.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from bot.services.card_data import WIN_CONDITIONS, card_has_role, get_card_elixir, get_card_roles
from bot.services.card_matchups import synergy_partners
from bot.services.card_names_ru import card_name_ru
from bot.services.deck_analyzer import analyze_deck
from bot.services.deck_builder.balance import soft_balance_issues
from bot.services.deck_builder.builder import (
    _avg_elixir,
    _card_has_role,
    _card_roles,
    _count_spells,
    _count_wins,
    _detect_archetype,
    _is_spell,
    _is_win,
    _pair_synergy,
)
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
    ROLE_CYCLE,
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
from bot.services.deck_builder.loader import get_database
from bot.services.deck_intent import DeckIntent, DeckIntentEngine
from bot.services.deck_game_plan import GamePlan, build_game_plan
from bot.services.special_card_policy import SpecialCardPolicy

logger = logging.getLogger(__name__)

# TODO(card-profile): _ANTI_AIR_CARDS / _SPLASH_* дублируют CardProfile.is_air_defense / is_splash.
# Не удалять и не менять логику improve — только метка для миграции.
_SMALL_SPELLS = frozenset({
    "Zap", "The Log", "Giant Snowball", "Barbarian Barrel", "Ice Spirit", "Electro Spirit",
})
_FINISHERS = frozenset({"Fireball", "Rocket", "Lightning", "Poison"})
_ANTI_AIR_CARDS = frozenset({
    "Archers", "Musketeer", "Three Musketeers", "Wizard", "Baby Dragon", "Electro Dragon",
    "Executioner", "Electro Wizard", "Ice Wizard", "Inferno Dragon", "Magic Archer",
    "Flying Machine", "Minions", "Minion Horde", "Mega Minion", "Bats", "Skeleton Dragons",
    "Firecracker", "Mother Witch", "Phoenix", "Princess", "Hunter", "Dart Goblin",
    "Witch", "Spear Goblins", "Zappies", "Rascals", "Archer Queen", "Little Prince",
    "Night Witch", "Tesla", "Inferno Tower",
})
_SPLASH_CARDS = frozenset({
    "Wizard", "Baby Dragon", "Valkyrie", "Bowler", "Executioner", "Bomber",
    "Fireball", "Arrows", "Poison", "Earthquake", "Electro Dragon",
    "Goblin Demolisher", "Magic Archer", "Witch", "Electro Wizard", "Ice Wizard",
    "Skeleton Dragons", "Mega Knight", "Dark Prince", "Firecracker", "Skeleton King",
    "Mother Witch", "Royal Delivery",
})
_DEFENSE_ROLES = frozenset({
    ROLE_AIR, ROLE_SPLASH, ROLE_ANTI_TANK, ROLE_DEFENSIVE, ROLE_ANTI_SWARM, ROLE_BUILDING,
})

_SPLASH_TROOPS = frozenset({
    "Executioner", "Wizard", "Bowler", "Valkyrie", "Baby Dragon",
    "Electro Wizard", "Hunter", "Magic Archer", "Firecracker",
})

_CATEGORY_ROLE: dict[str, str | None] = {
    "spells": ROLE_BIG_SPELL,
    "finishers": ROLE_BIG_SPELL,
    "anti_air": ROLE_AIR,
    "splash": ROLE_SPLASH,
    "defense": ROLE_BUILDING,
    "point_target": ROLE_ANTI_TANK,
    "swarm": ROLE_SMALL_SPELL,
    "cycle": ROLE_CYCLE,
    "win_condition": ROLE_WIN,
    "support": ROLE_BIG_SPELL,
    "focus": None,
}

# Категория gap → soft-check DeckIntent (None = всегда актуально, если пробел есть).
_CATEGORY_SOFT_CHECK: dict[str, str | None] = {
    "spells": None,
    "win_condition": None,
    "finishers": "big_spell",
    "anti_air": "air_defense",
    "splash": "anti_swarm",
    "defense": "building",
    "point_target": "anti_tank",
    "swarm": "small_spell",
    "cycle": "cycle",
    "support": "big_spell",
    "focus": None,
}

# Soft-check / role-id → роли карты (для intent / универсальности, без списков «лучших карт»).
_SOFT_CHECK_ROLES: dict[str, frozenset[str]] = {
    "big_spell": frozenset({ROLE_BIG_SPELL}),
    "small_spell": frozenset({ROLE_SMALL_SPELL}),
    "air_defense": frozenset({ROLE_AIR}),
    "anti_tank": frozenset({ROLE_ANTI_TANK, ROLE_DPS}),
    "anti_swarm": frozenset({ROLE_ANTI_SWARM, ROLE_SPLASH}),
    "building": frozenset({ROLE_BUILDING}),
    "cycle": frozenset({ROLE_CYCLE}),
    "defensive": frozenset({ROLE_DEFENSIVE, ROLE_BUILDING}),
}

_ROLE_ID_ROLES: dict[str, frozenset[str]] = {
    "win_condition": frozenset({ROLE_WIN}),
    "big_spell": frozenset({ROLE_BIG_SPELL}),
    "small_spell": frozenset({ROLE_SMALL_SPELL}),
    "anti_air": frozenset({ROLE_AIR}),
    "splash": frozenset({ROLE_SPLASH}),
    "dps": frozenset({ROLE_DPS, ROLE_ANTI_TANK}),
    "tank": frozenset({ROLE_TANK}),
    "mini_tank": frozenset({ROLE_MINI_TANK}),
    "building": frozenset({ROLE_BUILDING}),
}

# Веса итогового рейтинга (сумма = 1.0). Ни одна ось не доминирует одна.
_RATING_WEIGHTS: dict[str, float] = {
    "strategy_fit": 0.12,
    "gameplan_fit": 0.10,
    "primary_win_support": 0.14,
    "secondary_combo_support": 0.10,
    "tempo_fit": 0.08,
    "deck_identity": 0.10,
    "existing_synergy": 0.12,
    "future_synergy": 0.08,
    "role_overlap": 0.08,       # выше = меньше вредного дубля ролей
    "replacement_cost": 0.08,   # выше = дешевле отдать drop
}


@dataclass(frozen=True)
class CandidateRating:
    """Итоговый рейтинг кандидата — только после оценки всех факторов."""

    card: str
    strategy_fit: float
    gameplan_fit: float
    primary_win_support: float
    secondary_combo_support: float
    tempo_fit: float
    deck_identity: float
    existing_synergy: float
    future_synergy: float
    role_overlap: float
    replacement_cost: float
    total: float


class SolutionTier(str, Enum):
    """Ступени поиска решения для gap (от лучшего к худшему)."""

    IDEAL = "ideal"
    GOOD = "good"
    ACCEPTABLE = "acceptable"
    COMPROMISE = "compromise"
    ANY_IMPROVEMENT = "any"


_TIER_ORDER: tuple[SolutionTier, ...] = (
    SolutionTier.IDEAL,
    SolutionTier.GOOD,
    SolutionTier.ACCEPTABLE,
    SolutionTier.COMPROMISE,
    SolutionTier.ANY_IMPROVEMENT,
)

# min_total + floors по ключевым осям (не по одной роли).
_TIER_POLICY: dict[SolutionTier, dict[str, float | str]] = {
    SolutionTier.IDEAL: {
        "min_total": 68.0,
        "elixir_tol_mult": 1.0,
        "min_existing_synergy": float(SYNERGY_PARTIAL),
        "min_primary_win": float(SYNERGY_WEAK),
        "min_strategy_fit": 55.0,
        "strategy": "full",
    },
    SolutionTier.GOOD: {
        "min_total": 58.0,
        "elixir_tol_mult": 1.5,
        "min_existing_synergy": float(SYNERGY_WEAK),
        "min_primary_win": 45.0,
        "min_strategy_fit": 48.0,
        "strategy": "full",
    },
    SolutionTier.ACCEPTABLE: {
        "min_total": 48.0,
        "elixir_tol_mult": 2.2,
        "min_existing_synergy": 40.0,
        "min_primary_win": 25.0,
        "min_strategy_fit": 40.0,
        "strategy": "soft",
    },
    SolutionTier.COMPROMISE: {
        "min_total": 36.0,
        "elixir_tol_mult": 3.5,
        "min_existing_synergy": 25.0,
        "min_primary_win": 0.0,
        "min_strategy_fit": 30.0,
        "strategy": "soft",
    },
    SolutionTier.ANY_IMPROVEMENT: {
        "min_total": 0.0,
        "elixir_tol_mult": 99.0,
        "min_existing_synergy": 0.0,
        "min_primary_win": 0.0,
        "min_strategy_fit": 0.0,
        "strategy": "legal",
    },
}


@dataclass(frozen=True)
class GapSolution:
    drop: str
    pick: str
    tier: SolutionTier
    rating: CandidateRating


def _clamp_score(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))



def _card_ru(name: str) -> str:
    return card_name_ru(name, short=True) or name


def _has_small_spell_answer(cards: list[str]) -> bool:
    return any(c in _SMALL_SPELLS for c in cards)


def _has_finisher(cards: list[str], db) -> bool:
    return any(c in _FINISHERS or _card_has_role(db, c, ROLE_BIG_SPELL) for c in cards)


def _is_defensive_core(db, card: str) -> bool:
    if card in _ANTI_AIR_CARDS or card in _SPLASH_TROOPS:
        return True
    roles = _card_roles(db, card)
    return bool(roles & _DEFENSE_ROLES)


def _defensive_core_cards(deck: list[str], db) -> set[str]:
    return {c for c in deck if _is_defensive_core(db, c)}


def _is_cycle_card(db, card: str) -> bool:
    return _card_has_role(db, card, ROLE_CYCLE) or get_card_elixir(card) <= 2


def _count_cycle_cards(deck: list[str], db) -> int:
    return sum(1 for c in deck if _is_cycle_card(db, c))


def _count_air_defense(deck: list[str], db) -> int:
    return sum(1 for c in deck if _card_has_role(db, c, ROLE_AIR) or c in _ANTI_AIR_CARDS)


def _gap_relevant_for_intent(category: str, intent: DeckIntent) -> bool:
    """Пробел учитывается только если стратегия его реально требует."""
    soft = _CATEGORY_SOFT_CHECK.get(category, None)
    if soft is None:
        return True
    if soft == "building":
        return intent.require_building
    if soft == "cycle":
        return intent.min_cycle_cards > 0
    if soft == "air_defense":
        return intent.min_air_defense > 0
    if soft == "anti_swarm" and "splash" in intent.required_role_ids:
        return True
    return soft in intent.required_soft_checks


def _needs_building(deck: list[str], stats, db, intent: DeckIntent) -> bool:
    if not intent.require_building:
        return False
    if stats.buildings:
        return False
    defensive = _defensive_core_cards(deck, db)
    if len(defensive) >= 2 and stats.air_coverage and stats.point_target_coverage:
        return False
    if stats.air_coverage and stats.splash_coverage and stats.point_target_coverage:
        return False
    return True


def _collect_improvement_gaps(deck: list[str], db, intent: DeckIntent) -> list[dict]:
    """Настоящие проблемы относительно DeckIntent — не универсальный чек-лист."""
    if len(deck) != 8:
        return []

    stats = analyze_deck(deck)
    deck_set = set(deck)
    gaps: list[dict] = []

    def add(category: str, message: str, suggested: list[str]) -> None:
        if not _gap_relevant_for_intent(category, intent):
            return
        missing = [c for c in suggested if c not in deck_set][:4]
        if not missing:
            return
        gaps.append({
            "category": category,
            "message": message,
            "suggested_cards": missing,
        })

    has_spells = bool(stats.spells) or any(_is_spell(db, c) for c in deck)
    if not has_spells:
        add(
            "spells",
            "В колоде нет заклинаний — сложнее контролировать поле и добивать башни",
            ["The Log", "Fireball", "Zap", "Arrows"],
        )
    elif not _has_finisher(deck, db):
        add(
            "finishers",
            "Мало добивающих заклинаний — добавьте Fireball или Rocket для финиша",
            ["Fireball", "Rocket", "Lightning"],
        )

    air_n = _count_air_defense(deck, db)
    if intent.min_air_defense > 0 and (
        air_n < max(1, intent.min_air_defense) or not stats.air_coverage
    ):
        add(
            "anti_air",
            "Слабая защита от воздуха — Balloon и Minions будут опасны",
            ["Musketeer", "Mega Minion", "Inferno Dragon", "Tesla", "Archers"],
        )

    if not stats.splash_coverage:
        add(
            "splash",
            "Нет сплеша — спам и связки Goblin Gang / Skeleton Army сложно зачищать",
            ["Valkyrie", "Wizard", "Baby Dragon", "Fireball", "Arrows"],
        )

    if _needs_building(deck, stats, db, intent):
        add(
            "defense",
            "Нет построек — Hog Rider и Balloon сложнее останавливать на мосту",
            ["Cannon", "Tesla", "Tombstone", "Inferno Tower"],
        )

    if not stats.point_target_coverage:
        add(
            "point_target",
            "Нет ответа на точечный урон — Стражи держат P.E.K.K.A, Мини P.E.K.K.A, Хог и подобных",
            ["Guards", "Knight", "Ice Golem", "Skeleton Army"],
        )

    if not _has_small_spell_answer(deck):
        add(
            "swarm",
            "Нет дешёвого ответа на спам — Zap или Ice Spirit сильно помогут в цикле",
            list(_SMALL_SPELLS),
        )

    cycle_n = _count_cycle_cards(deck, db)
    if intent.min_cycle_cards > 0 and cycle_n < intent.min_cycle_cards:
        add(
            "cycle",
            f"Недостаточно карт цикла ({cycle_n}/{intent.min_cycle_cards}) для стратегии {intent.archetype}",
            ["Skeletons", "Ice Spirit", "Electro Spirit", "Ice Golem"],
        )
    elif stats.avg_elixir > 4.2 and cycle_n < max(1, intent.min_cycle_cards):
        add(
            "cycle",
            f"Тяжёлая колода ({stats.avg_elixir} эл.) — добавьте дешёвый цикл для давления",
            ["Skeletons", "Ice Spirit", "Electro Spirit", "Ice Golem"],
        )

    if not stats.win_conditions:
        add(
            "win_condition",
            "Нет явного win-condition — добавьте карту для урона по башне",
            ["Hog Rider", "Balloon", "Royal Giant", "Miner", "Goblin Barrel"],
        )

    return gaps


def _swap_keeps_balance(deck: list[str], drop: str, pick: str, db) -> bool:
    before = analyze_deck(deck)
    after_deck = list(deck)
    after_deck[after_deck.index(drop)] = pick
    after = analyze_deck(after_deck)

    if before.air_coverage and not after.air_coverage:
        return False
    if before.splash_coverage and not after.splash_coverage:
        return False
    if before.point_target_coverage and not after.point_target_coverage:
        return False
    if _has_finisher(deck, db) and not _has_finisher(after_deck, db):
        return False
    if _has_small_spell_answer(deck) and not _has_small_spell_answer(after_deck):
        return False
    return True


def _locked_cards(deck: list[str], db) -> set[str]:
    """Win-condition и заклинания игрока не трогаем (по всем roles[], не primary)."""
    locked: set[str] = set()
    for card in deck:
        if _is_win(db, card) or card in WIN_CONDITIONS or card_has_role(card, "win_condition"):
            locked.add(card)
        if _is_spell(db, card) or card_has_role(card, "spell"):
            locked.add(card)
    return locked


def _avg_synergy_with_deck(db, card: str, deck: list[str]) -> float:
    others = [c for c in deck if c != card]
    if not others:
        return 0.0
    return sum(_pair_synergy(db, card, other) for other in others) / len(others)


def _strengthens_archetype(pick: str, deck: list[str], drop: str, archetype: str, db) -> bool:
    """Динамически: средняя синергия с текущей колодой (без списков «лучших карт»)."""
    del archetype  # стратегия уже в intent; порог — по синергии с составом
    remain = [c for c in deck if c != drop]
    return _avg_synergy_with_deck(db, pick, remain) >= SYNERGY_WEAK


def _strengthens_primary_win(pick: str, intent: DeckIntent, db) -> bool:
    if not intent.primary_win:
        return True
    return _pair_synergy(db, pick, intent.primary_win) >= SYNERGY_WEAK


def _elixir_tolerance(intent: DeckIntent) -> float:
    if intent.min_cycle_cards >= 2:
        return 0.05
    if intent.min_cycle_cards >= 1:
        return 0.12
    return 0.25


def _compatible_with_strategy(
    deck: list[str],
    drop: str,
    pick: str,
    intent: DeckIntent,
    db,
    *,
    elixir_tol_mult: float = 1.0,
    strategy: str = "full",
) -> bool:
    """Проверка совместимости. strategy: full | soft | legal."""
    if strategy == "legal":
        return True

    if not _swap_keeps_balance(deck, drop, pick, db):
        return False

    after = list(deck)
    after[after.index(drop)] = pick

    before_avg = _avg_elixir(deck, db)
    after_avg = _avg_elixir(after, db)
    if after_avg > before_avg + _elixir_tolerance(intent) * elixir_tol_mult:
        return False

    before_cycle = _count_cycle_cards(deck, db)
    after_cycle = _count_cycle_cards(after, db)
    if intent.min_cycle_cards > 0:
        if after_cycle < intent.min_cycle_cards and before_cycle >= intent.min_cycle_cards:
            if strategy == "full":
                return False
        if _is_cycle_card(db, drop) and not _is_cycle_card(db, pick) and after_cycle < before_cycle:
            if after_cycle < max(intent.min_cycle_cards, 1) and strategy == "full":
                return False

    if intent.require_building:
        before_b = sum(1 for c in deck if _card_has_role(db, c, ROLE_BUILDING))
        after_b = sum(1 for c in after if _card_has_role(db, c, ROLE_BUILDING))
        if before_b > 0 and after_b == 0 and strategy == "full":
            return False

    if intent.min_air_defense > 0:
        if _count_air_defense(after, db) < intent.min_air_defense:
            if _count_air_defense(deck, db) >= intent.min_air_defense and strategy == "full":
                return False

    if strategy == "full":
        if not _strengthens_archetype(pick, deck, drop, intent.archetype, db):
            return False
        if not _strengthens_primary_win(pick, intent, db):
            return False
        remain = [c for c in deck if c != drop]
        if _avg_synergy_with_deck(db, pick, remain) < SYNERGY_WEAK:
            return False

    return True


def _card_matches_soft(pick: str, soft: str, db) -> bool:
    if soft == "cycle":
        return _is_cycle_card(db, pick)
    mapped = _SOFT_CHECK_ROLES.get(soft, frozenset())
    return any(_card_has_role(db, pick, r) for r in mapped)


def _rate_strategy_fit(
    pick: str,
    intent: DeckIntent,
    db,
    *,
    category: str | None,
    role: str | None,
) -> float:
    """Совместимость со стратегией Intent. Закрытие одной роли даёт лишь часть очков."""
    roles = _card_roles(db, pick)
    checks = list(intent.required_soft_checks) or ["big_spell", "small_spell", "air_defense"]
    hits = sum(1 for soft in checks if _card_matches_soft(pick, soft, db))
    soft_score = 100.0 * hits / max(len(checks), 1)

    role_ids = list(intent.required_role_ids) or ["anti_air", "splash", "dps"]
    role_hits = 0
    for rid in role_ids:
        mapped = _ROLE_ID_ROLES.get(rid, frozenset())
        if roles & mapped or (rid == "anti_air" and pick in _ANTI_AIR_CARDS):
            role_hits += 1
    role_score = 100.0 * role_hits / max(len(role_ids), 1)

    # Узкое закрытие текущего gap — максимум +18, не может «выиграть» рейтинг одно.
    gap_bonus = 0.0
    if role and role in roles:
        gap_bonus = 18.0
    elif category == "cycle" and _is_cycle_card(db, pick):
        gap_bonus = 18.0
    elif category == "anti_air" and (ROLE_AIR in roles or pick in _ANTI_AIR_CARDS):
        gap_bonus = 18.0
    elif category == "splash" and (ROLE_SPLASH in roles or pick in _SPLASH_CARDS):
        gap_bonus = 18.0
    elif category in {"spells", "finishers", "swarm"} and _is_spell(db, pick):
        gap_bonus = 16.0
    elif category == "defense" and ROLE_BUILDING in roles:
        gap_bonus = 18.0
    elif category == "win_condition" and (ROLE_WIN in roles or pick in WIN_CONDITIONS):
        gap_bonus = 18.0

    bias = intent.attack_bias
    style = 0.0
    if bias >= 0.65 and roles & {ROLE_DPS, ROLE_MINI_TANK, ROLE_WIN, ROLE_SPLASH}:
        style += 8.0
    elif bias <= 0.45 and roles & {ROLE_BUILDING, ROLE_DEFENSIVE, ROLE_AIR, ROLE_ANTI_TANK}:
        style += 8.0
    else:
        style += 4.0
    if intent.require_building and ROLE_BUILDING in roles:
        style += 6.0
    if intent.min_cycle_cards > 0 and _is_cycle_card(db, pick):
        style += 6.0

    return _clamp_score(soft_score * 0.35 + role_score * 0.30 + gap_bonus + style)


def _rate_gameplan_fit(
    pick: str,
    remain: list[str],
    intent: DeckIntent,
    db,
    game_plan: GamePlan | None,
) -> float:
    if game_plan is None:
        # Fallback: синергия с key-подобными картами (win + cheap cycle + spells).
        keys: list[str] = []
        if intent.primary_win and intent.primary_win in remain:
            keys.append(intent.primary_win)
        extras = sorted(
            c for c in remain
            if c not in keys and (
                _card_has_role(db, c, ROLE_BIG_SPELL)
                or _card_has_role(db, c, ROLE_SMALL_SPELL)
                or _is_cycle_card(db, c)
            )
        )
        keys.extend(extras)
        keys = keys[:5]
        if not keys:
            return 50.0
        avg = sum(_pair_synergy(db, pick, k) for k in keys) / len(keys)
        return _clamp_score(avg)

    score = 40.0
    key_cards = sorted(c for c in game_plan.key_cards if c in remain)
    if key_cards:
        avg = sum(_pair_synergy(db, pick, k) for k in key_cards) / len(key_cards)
        score = avg * 0.7 + 20.0

    # Усиливает комбинации плана: pick + partner уже в колоде.
    combo_hits = 0
    for combo in game_plan.core_combinations[:4]:
        parts = [p.strip() for p in combo.split("+")]
        if len(parts) != 2:
            continue
        a, b = parts
        if (a == pick and b in remain) or (b == pick and a in remain):
            combo_hits += 1
        elif a in remain and b in remain:
            # pick синергирует с обеими сторонами связки
            if _pair_synergy(db, pick, a) >= SYNERGY_PARTIAL and _pair_synergy(db, pick, b) >= SYNERGY_PARTIAL:
                combo_hits += 1
    score += combo_hits * 12.0
    return _clamp_score(score)


def _rate_primary_win_support(pick: str, intent: DeckIntent, db) -> float:
    if not intent.primary_win:
        return 55.0
    return _clamp_score(_pair_synergy(db, pick, intent.primary_win))


def _rate_secondary_combo_support(pick: str, remain: list[str], db) -> float:
    """Синергия с не-win ключевыми картами и известными парами."""
    if not remain:
        return 45.0
    # Топ-3 партнёра по синергии в колоде (кроме чистого average).
    pair_scores = sorted((_pair_synergy(db, pick, c) for c in remain), reverse=True)
    top = sum(pair_scores[:3]) / max(len(pair_scores[:3]), 1)

    known = 0.0
    n_known = 0
    for pair, score in KNOWN_SYNERGY_PAIRS.items():
        if pick not in pair:
            continue
        other = next(iter(pair - {pick}))
        if other in remain:
            known += float(score)
            n_known += 1
    known_avg = known / n_known if n_known else 50.0
    return _clamp_score(top * 0.65 + known_avg * 0.35)


def _rate_tempo_fit(
    deck: list[str],
    drop: str,
    pick: str,
    intent: DeckIntent,
    db,
) -> float:
    after = list(deck)
    after[after.index(drop)] = pick
    before_avg = _avg_elixir(deck, db)
    after_avg = _avg_elixir(after, db)
    lo, hi = ARCHETYPE_ELIXIR.get(
        intent.archetype, (DEFAULT_ELIXIR_MIN, DEFAULT_ELIXIR_MAX),
    )
    mid = (lo + hi) / 2.0

    dist = abs(after_avg - mid)
    fit = 100.0 - dist * 55.0
    delta = after_avg - before_avg
    fit -= max(0.0, delta) * 48.0
    fit += max(0.0, -delta) * 22.0

    if intent.min_cycle_cards >= 2 and get_card_elixir(pick) <= 2:
        fit += 10.0
    if after_avg < lo - 0.35 or after_avg > hi + 0.35:
        fit -= 25.0

    # Темп: цикл-архетипы любят дешёвые; beatdown — не штрафуем средний 4+.
    if intent.min_cycle_cards >= 2 and get_card_elixir(pick) >= 5:
        fit -= 12.0
    if intent.attack_bias >= 0.7 and get_card_elixir(pick) <= 2:
        fit += 4.0

    return _clamp_score(fit)


def _rate_deck_identity(pick: str, remain: list[str], intent: DeckIntent, db) -> float:
    """Усиливает идентичность архетипа, а не размывает её."""
    anchors = ARCHETYPE_ANCHORS.get(intent.archetype, set())
    primary_list = ARCHETYPE_PRIMARY_WIN.get(intent.archetype, [])
    score = 48.0

    if pick in anchors:
        score += 28.0
    elif any(_pair_synergy(db, pick, a) >= SYNERGY_PARTIAL for a in anchors if a in remain):
        score += 16.0

    if pick in primary_list:
        score += 12.0
    if intent.primary_win and _pair_synergy(db, pick, intent.primary_win) >= SYNERGY_STRONG:
        score += 10.0

    # Штраф: лишний attack-win размывает identity при MAX_WINS.
    if pick in WIN_CONDITIONS and intent.primary_win and pick != intent.primary_win:
        score -= 22.0

    # Синергия со «скелетом» архетипа в колоде.
    present_anchors = [a for a in anchors if a in remain]
    if present_anchors:
        avg = sum(_pair_synergy(db, pick, a) for a in present_anchors) / len(present_anchors)
        score = score * 0.55 + avg * 0.45

    return _clamp_score(score)


def _rate_existing_synergy(pick: str, remain: list[str], db) -> float:
    return _clamp_score(_avg_synergy_with_deck(db, pick, remain))


def _rate_future_synergy(pick: str, remain: list[str], db) -> float:
    """Потенциал новых сильных связок и совместимость со спеллами."""
    score = 45.0
    # Известные пары, где второй партнёр ещё не в колоде, но pick открывает путь —
    # косвенно: сильные синергии с текущими картами выше порога.
    strong_links = sum(1 for c in remain if _pair_synergy(db, pick, c) >= SYNERGY_STRONG)
    partial_links = sum(1 for c in remain if SYNERGY_PARTIAL <= _pair_synergy(db, pick, c) < SYNERGY_STRONG)
    score += strong_links * 14.0 + partial_links * 6.0

    spells = [c for c in remain if _is_spell(db, c)]
    if spells:
        avg_sp = sum(_pair_synergy(db, pick, s) for s in spells) / len(spells)
        score = score * 0.7 + avg_sp * 0.3
        if _is_spell(db, pick):
            big_in = sum(1 for s in spells if _card_has_role(db, s, ROLE_BIG_SPELL))
            if _card_has_role(db, pick, ROLE_BIG_SPELL) and big_in >= 1:
                score -= 14.0
            small_in = sum(
                1 for s in spells
                if _card_has_role(db, s, ROLE_SMALL_SPELL) or s in _SMALL_SPELLS
            )
            if (_card_has_role(db, pick, ROLE_SMALL_SPELL) or pick in _SMALL_SPELLS) and small_in >= 1:
                score -= 10.0

    # Известная пара pick+X где X уже в колоде.
    for pair, val in KNOWN_SYNERGY_PAIRS.items():
        if pick in pair and (pair - {pick}).issubset(set(remain)):
            score += (val - 70) * 0.35

    return _clamp_score(score)


def _rate_role_overlap(pick: str, remain: list[str], db) -> float:
    """Выше = меньше вредного дублирования уже покрытых ролей."""
    pick_roles = _card_roles(db, pick)
    if not pick_roles:
        return 60.0

    covered: dict[str, int] = {}
    for c in remain:
        for r in _card_roles(db, c):
            covered[r] = covered.get(r, 0) + 1

    overlap_penalty = 0.0
    unique_value = 0.0
    interesting = {
        ROLE_AIR, ROLE_SPLASH, ROLE_ANTI_TANK, ROLE_DEFENSIVE,
        ROLE_ANTI_SWARM, ROLE_BUILDING, ROLE_CYCLE, ROLE_DPS,
        ROLE_MINI_TANK, ROLE_BIG_SPELL, ROLE_SMALL_SPELL, ROLE_WIN, ROLE_TANK,
    }
    for r in pick_roles & interesting:
        n = covered.get(r, 0)
        if n == 0:
            unique_value += 14.0
        elif n == 1:
            overlap_penalty += 8.0
        else:
            overlap_penalty += 16.0

    # Дубль win особенно дорогой.
    if ROLE_WIN in pick_roles or pick in WIN_CONDITIONS:
        wins_in = sum(1 for c in remain if c in WIN_CONDITIONS or ROLE_WIN in _card_roles(db, c))
        if wins_in >= 1:
            overlap_penalty += 20.0

    return _clamp_score(70.0 + unique_value - overlap_penalty)


def _rate_replacement_cost(drop: str, remain_after_without_drop: list[str], intent: DeckIntent, db) -> float:
    """Выше = drop дешевле отдать (слабая / дублирующая карта)."""
    # remain_after_without_drop = deck without drop (same as remain before pick)
    cost = 55.0
    drop_roles = _card_roles(db, drop)

    # Сильная синергия drop с колодой → дороже терять.
    syn = _avg_synergy_with_deck(db, drop, remain_after_without_drop)
    cost -= (syn - 50.0) * 0.45

    if drop in GENERIC_CARDS:
        cost += 18.0
    if intent.primary_win and drop == intent.primary_win:
        cost -= 40.0
    if drop in WIN_CONDITIONS or ROLE_WIN in drop_roles:
        cost -= 25.0
    if _is_spell(db, drop):
        cost -= 12.0

    # Если роли drop уже дублируются в remain — дешевле заменить.
    for r in drop_roles & {
        ROLE_AIR, ROLE_SPLASH, ROLE_CYCLE, ROLE_DEFENSIVE, ROLE_ANTI_SWARM,
    }:
        if any(r in _card_roles(db, c) for c in remain_after_without_drop):
            cost += 8.0

    if intent.min_cycle_cards > 0 and _is_cycle_card(db, drop):
        cycle_left = sum(1 for c in remain_after_without_drop if _is_cycle_card(db, c))
        if cycle_left < intent.min_cycle_cards:
            cost -= 20.0

    return _clamp_score(cost)


def _archetype_card_popularity(archetype: str, card: str, db) -> int:
    """Популярность карты в архетипе (частота × popularity колод + якоря)."""
    cache_attr = "_archetype_pop_cache"
    cache: dict[str, dict[str, int]] = getattr(db, cache_attr, None) or {}
    if not cache:
        setattr(db, cache_attr, cache)
    if archetype not in cache:
        counts: dict[str, int] = {}
        for idx in db._by_archetype.get(archetype, []):
            rec = db.decks[idx]
            weight = max(1, int(getattr(rec, "popularity", 50)))
            for c in rec.cards:
                counts[c] = counts.get(c, 0) + weight
        for a in ARCHETYPE_ANCHORS.get(archetype, ()):
            counts[a] = counts.get(a, 0) + 200
        for w in ARCHETYPE_PRIMARY_WIN.get(archetype, []):
            counts[w] = counts.get(w, 0) + 120
        cache[archetype] = counts
    return cache[archetype].get(card, 0)


def candidate_sort_key(
    rating: CandidateRating,
    drop: str,
    intent: DeckIntent,
    db,
) -> tuple:
    """Детерминированный порядок: total → strategy_fit → synergy → elixir delta → popularity.

    Запрещён случайный выбор при равном total.
    """
    elixir_delta = abs(get_card_elixir(rating.card) - get_card_elixir(drop))
    popularity = _archetype_card_popularity(intent.archetype, rating.card, db)
    return (
        -rating.total,
        -rating.strategy_fit,
        -rating.existing_synergy,
        elixir_delta,
        -popularity,
        rating.card,
    )


def is_better_candidate(
    challenger: CandidateRating,
    incumbent: CandidateRating,
    *,
    challenger_drop: str,
    incumbent_drop: str,
    intent: DeckIntent,
    db,
) -> bool:
    """True, если challenger строго лучше по фиксированному tie-break."""
    return candidate_sort_key(challenger, challenger_drop, intent, db) < candidate_sort_key(
        incumbent, incumbent_drop, intent, db,
    )


def rate_candidate(
    deck: list[str],
    drop: str,
    pick: str,
    intent: DeckIntent,
    db,
    *,
    role: str | None = None,
    category: str | None = None,
    game_plan: GamePlan | None = None,
) -> CandidateRating:
    """Полный рейтинг по всем факторам. Итог — только после всех осей."""
    remain = [c for c in deck if c != drop]

    strategy_fit = _rate_strategy_fit(pick, intent, db, category=category, role=role)
    gameplan_fit = _rate_gameplan_fit(pick, remain, intent, db, game_plan)
    primary_win_support = _rate_primary_win_support(pick, intent, db)
    secondary_combo_support = _rate_secondary_combo_support(pick, remain, db)
    tempo_fit = _rate_tempo_fit(deck, drop, pick, intent, db)
    deck_identity = _rate_deck_identity(pick, remain, intent, db)
    existing_synergy = _rate_existing_synergy(pick, remain, db)
    future_synergy = _rate_future_synergy(pick, remain, db)
    role_overlap = _rate_role_overlap(pick, remain, db)
    replacement_cost = _rate_replacement_cost(drop, remain, intent, db)

    total = (
        strategy_fit * _RATING_WEIGHTS["strategy_fit"]
        + gameplan_fit * _RATING_WEIGHTS["gameplan_fit"]
        + primary_win_support * _RATING_WEIGHTS["primary_win_support"]
        + secondary_combo_support * _RATING_WEIGHTS["secondary_combo_support"]
        + tempo_fit * _RATING_WEIGHTS["tempo_fit"]
        + deck_identity * _RATING_WEIGHTS["deck_identity"]
        + existing_synergy * _RATING_WEIGHTS["existing_synergy"]
        + future_synergy * _RATING_WEIGHTS["future_synergy"]
        + role_overlap * _RATING_WEIGHTS["role_overlap"]
        + replacement_cost * _RATING_WEIGHTS["replacement_cost"]
    )
    total -= SpecialCardPolicy.rating_penalty(
        pick,
        deck=remain,
        intent=intent,
        game_plan=game_plan,
    )

    return CandidateRating(
        card=pick,
        strategy_fit=round(strategy_fit, 2),
        gameplan_fit=round(gameplan_fit, 2),
        primary_win_support=round(primary_win_support, 2),
        secondary_combo_support=round(secondary_combo_support, 2),
        tempo_fit=round(tempo_fit, 2),
        deck_identity=round(deck_identity, 2),
        existing_synergy=round(existing_synergy, 2),
        future_synergy=round(future_synergy, 2),
        role_overlap=round(role_overlap, 2),
        replacement_cost=round(replacement_cost, 2),
        total=round(total, 2),
    )


def rank_candidates(
    deck: list[str],
    drop: str,
    candidates: list[str],
    intent: DeckIntent,
    db,
    *,
    role: str | None = None,
    category: str | None = None,
    tier: SolutionTier = SolutionTier.IDEAL,
    game_plan: GamePlan | None = None,
) -> list[CandidateRating]:
    """Оценить кандидатов ступени tier и отсортировать по total (desc)."""
    policy = _TIER_POLICY[tier]
    strategy = str(policy["strategy"])
    elixir_mult = float(policy["elixir_tol_mult"])
    min_total = float(policy["min_total"])
    min_existing = float(policy["min_existing_synergy"])
    min_win = float(policy["min_primary_win"])
    min_strategy = float(policy["min_strategy_fit"])

    rated: list[CandidateRating] = []
    remain_ctx = [c for c in deck if c != drop]
    for pick in candidates:
        if pick == drop:
            continue
        # Situational spells запрещены как fillers / role-gap / compromise.
        if SpecialCardPolicy.forbid_as_auto_pick(
            pick,
            deck=remain_ctx,
            intent=intent,
            game_plan=game_plan,
        ):
            continue
        if not _legal_swap(deck, drop, pick, db):
            continue
        if not _compatible_with_strategy(
            deck, drop, pick, intent, db,
            elixir_tol_mult=elixir_mult,
            strategy=strategy,
        ):
            continue
        if not _improves_situation(deck, drop, pick, intent, db, category=category, role=role):
            continue

        rating = rate_candidate(
            deck, drop, pick, intent, db,
            role=role, category=category, game_plan=game_plan,
        )
        if rating.total < min_total:
            continue
        if rating.existing_synergy < min_existing and tier != SolutionTier.ANY_IMPROVEMENT:
            continue
        if rating.primary_win_support < min_win and tier not in {
            SolutionTier.COMPROMISE, SolutionTier.ANY_IMPROVEMENT,
        }:
            continue
        if rating.strategy_fit < min_strategy and tier != SolutionTier.ANY_IMPROVEMENT:
            continue
        rated.append(rating)

    rated.sort(key=lambda r: candidate_sort_key(r, drop, intent, db))
    return rated


def _legal_swap(deck: list[str], drop: str, pick: str, db) -> bool:
    if pick == drop or pick in deck:
        return False
    if drop not in deck:
        return False
    if _is_win(db, drop) or drop in WIN_CONDITIONS:
        return False
    if _is_win(db, pick) and _count_wins(deck, db) >= MAX_WINS:
        return False
    # Замена спелла на спелл ок; добавление сверх лимита — нет
    if _is_spell(db, pick) and not _is_spell(db, drop) and _count_spells(deck, db) >= MAX_SPELLS:
        return False
    return True


def _category_metric_improved(
    before_deck: list[str],
    after_deck: list[str],
    category: str | None,
    intent: DeckIntent,
    db,
) -> bool:
    """Gap-специфичное улучшение (закрытие или ослабление проблемы)."""
    if not category:
        return False

    before = analyze_deck(before_deck)
    after = analyze_deck(after_deck)

    if category == "anti_air":
        return _count_air_defense(after_deck, db) > _count_air_defense(before_deck, db) or (
            after.air_coverage and not before.air_coverage
        )
    if category == "splash":
        return after.splash_coverage and not before.splash_coverage
    if category == "defense":
        return bool(after.buildings) and not before.buildings
    if category == "point_target":
        return after.point_target_coverage and not before.point_target_coverage
    if category in {"spells", "finishers"}:
        if category == "spells":
            return (bool(after.spells) or any(_is_spell(db, c) for c in after_deck)) and not (
                bool(before.spells) or any(_is_spell(db, c) for c in before_deck)
            )
        return _has_finisher(after_deck, db) and not _has_finisher(before_deck, db)
    if category == "swarm":
        return _has_small_spell_answer(after_deck) and not _has_small_spell_answer(before_deck)
    if category == "cycle":
        return _count_cycle_cards(after_deck, db) > _count_cycle_cards(before_deck, db) or (
            after.avg_elixir < before.avg_elixir - 0.05
        )
    if category == "win_condition":
        return bool(after.win_conditions) and not before.win_conditions

    soft = _CATEGORY_SOFT_CHECK.get(category)
    if soft:
        before_soft = set(soft_balance_issues(before_deck, db, intent.archetype))
        after_soft = set(soft_balance_issues(after_deck, db, intent.archetype))
        return soft in before_soft and soft not in after_soft
    return False


def _improves_situation(
    deck: list[str],
    drop: str,
    pick: str,
    intent: DeckIntent,
    db,
    *,
    category: str | None,
    role: str | None,
) -> bool:
    """True, если замена реально улучшает колоду относительно текущей ситуации/gap."""
    after = list(deck)
    after[after.index(drop)] = pick

    if _category_metric_improved(deck, after, category, intent, db):
        return True

    before_soft = set(soft_balance_issues(deck, db, intent.archetype))
    after_soft = set(soft_balance_issues(after, db, intent.archetype))
    if len(after_soft) < len(before_soft):
        return True
    soft = _CATEGORY_SOFT_CHECK.get(category or "")
    if soft and soft in before_soft and soft not in after_soft:
        return True

    # Роль закрыта, а раньше в колоде её не было
    if role:
        if role and not any(_card_has_role(db, c, role) for c in deck):
            if _card_has_role(db, pick, role):
                return True

    # Синергия с primary win заметно лучше, чем у drop
    if intent.primary_win:
        if _pair_synergy(db, pick, intent.primary_win) > _pair_synergy(db, drop, intent.primary_win) + 8:
            if _avg_synergy_with_deck(db, pick, [c for c in deck if c != drop]) >= (
                _avg_synergy_with_deck(db, drop, [c for c in deck if c != drop])
            ):
                return True

    return False


def _gather_replacement_candidates(
    deck: list[str],
    pool: set[str],
    *,
    role: str | None,
    suggestions: list[str] | None,
    db,
    soft_check: str | None = None,
    include_full_pool: bool = False,
) -> list[str]:
    deck_set = set(deck)
    out: list[str] = []
    seen: set[str] = set()

    def push(card: str) -> None:
        if card in pool and card not in deck_set and card not in seen:
            seen.add(card)
            out.append(card)

    if suggestions:
        for card in suggestions:
            push(card)

    # sorted(pool) — детерминированный обход (set иначе зависит от PYTHONHASHSEED).
    pool_sorted = sorted(pool)

    if role:
        for card in pool_sorted:
            if _card_has_role(db, card, role):
                push(card)

    if soft_check:
        for card in pool_sorted:
            if _card_matches_soft(card, soft_check, db):
                push(card)

    if include_full_pool:
        for card in pool_sorted:
            push(card)

    return out


def _list_replaceable(
    deck: list[str],
    locked: set[str],
    db,
    *,
    avoid_roles: frozenset[str] | None = None,
    protect_defensive: bool = True,
) -> list[str]:
    """Все карты, которые можно выкинуть (лучшие первыми)."""
    protected = set(locked)
    if protect_defensive:
        protected |= _defensive_core_cards(deck, db)
    candidates = [
        c for c in deck
        if c not in protected
        and not (_is_win(db, c) or c in WIN_CONDITIONS or card_has_role(c, "win_condition"))
    ]
    if not candidates and protect_defensive:
        return _list_replaceable(
            deck, locked, db, avoid_roles=avoid_roles, protect_defensive=False,
        )
    if not candidates:
        return []

    def rank(card: str) -> tuple[int, int, float, int, str]:
        roles = _card_roles(db, card)
        penalty = 1 if avoid_roles and roles & avoid_roles else 0
        generic_rank = 0 if card in GENERIC_CARDS else 1
        syn = _avg_synergy_with_deck(db, card, deck)
        elixir = get_card_elixir(card)
        return (penalty, generic_rank, syn, -elixir, card)

    return sorted(candidates, key=rank)


def _pick_replaceable(
    deck: list[str],
    locked: set[str],
    db,
    *,
    avoid_roles: frozenset[str] | None = None,
) -> str | None:
    cards = _list_replaceable(deck, locked, db, avoid_roles=avoid_roles)
    return cards[0] if cards else None


def search_gap_solution(
    deck: list[str],
    pool: set[str],
    locked: set[str],
    intent: DeckIntent,
    db,
    *,
    category: str,
    role: str | None,
    suggestions: list[str] | None,
    avoid_roles: frozenset[str] | None = None,
    game_plan: GamePlan | None = None,
) -> GapSolution | None:
    """Полный поиск решения gap: ideal → good → acceptable → compromise → any."""
    soft_check = _CATEGORY_SOFT_CHECK.get(category)
    drops = _list_replaceable(deck, locked, db, avoid_roles=avoid_roles)
    if not drops:
        return None

    for tier in _TIER_ORDER:
        include_full = tier in {
            SolutionTier.COMPROMISE, SolutionTier.ANY_IMPROVEMENT,
        }
        # На acceptable расширяем soft/role; полный pool — с compromise
        candidates = _gather_replacement_candidates(
            deck,
            pool,
            role=role,
            suggestions=suggestions,
            db=db,
            soft_check=soft_check,
            include_full_pool=include_full,
        )
        if not candidates:
            continue

        best: GapSolution | None = None
        for drop in drops:
            ranked = rank_candidates(
                deck, drop, candidates, intent, db,
                role=role, category=category, tier=tier, game_plan=game_plan,
            )
            if not ranked:
                continue
            top = ranked[0]
            cand = GapSolution(drop=drop, pick=top.card, tier=tier, rating=top)
            if best is None or is_better_candidate(
                cand.rating,
                best.rating,
                challenger_drop=cand.drop,
                incumbent_drop=best.drop,
                intent=intent,
                db=db,
            ):
                best = cand
        if best is not None:
            return best

    return None


def _pick_replacement(
    deck: list[str],
    pool: set[str],
    locked: set[str],
    archetype: str,
    *,
    role: str | None = None,
    suggestions: list[str] | None = None,
    db=None,
    drop: str | None = None,
    intent: DeckIntent | None = None,
    category: str | None = None,
    game_plan: GamePlan | None = None,
) -> str | None:
    """Обратная совместимость: лучший pick через ступенчатый поиск (drop фиксирован если дан)."""
    db = db or get_database()
    intent = intent or DeckIntentEngine.infer(deck, archetype=archetype)
    category = category or "support"
    plan = game_plan or build_game_plan(deck, archetype=intent.archetype, intent=intent)

    if drop:
        for tier in _TIER_ORDER:
            include_full = tier in {
                SolutionTier.ACCEPTABLE,
                SolutionTier.COMPROMISE,
                SolutionTier.ANY_IMPROVEMENT,
            }
            candidates = _gather_replacement_candidates(
                deck,
                pool,
                role=role,
                suggestions=suggestions,
                db=db,
                soft_check=_CATEGORY_SOFT_CHECK.get(category),
                include_full_pool=include_full,
            )
            ranked = rank_candidates(
                deck, drop, candidates, intent, db,
                role=role, category=category, tier=tier, game_plan=plan,
            )
            if ranked:
                return ranked[0].card
        return None

    solution = search_gap_solution(
        deck, pool, locked, intent, db,
        category=category, role=role, suggestions=suggestions, game_plan=plan,
    )
    return solution.pick if solution else None


def _apply_arena_fixes(
    deck: list[str],
    pool: set[str],
    issues: list[str],
) -> bool:
    changed = False
    for index, card in enumerate(list(deck)):
        if card in pool:
            continue
        changed = True
        issues.append(f"{_card_ru(card)} недоступна на вашей арене")
        replacement = _find_arena_replacement(card, pool, deck)
        if replacement:
            deck[index] = replacement
            issues.append(f"{_card_ru(card)} → {_card_ru(replacement)}")
            issues.append("Причина: карта доступна на вашей арене и закрывает ту же роль.")
    return changed


def _find_arena_replacement(card: str, pool: set[str], current: list[str]) -> str | None:
    """Арена-замена: пересечение roles[] + ближайший эликсир (не только primary)."""
    elixir = get_card_elixir(card)
    needed = get_card_roles(card)
    current_set = set(current)
    same_role = [
        c for c in pool
        if c not in current_set and (get_card_roles(c) & needed)
    ]
    if same_role:
        return min(same_role, key=lambda c: abs(get_card_elixir(c) - elixir))
    near = [
        c for c in pool
        if c not in current_set and abs(get_card_elixir(c) - elixir) <= 1
    ]
    if near:
        return min(near, key=lambda c: abs(get_card_elixir(c) - elixir))
    return None


def _fix_elixir_if_needed(
    deck: list[str],
    pool: set[str],
    locked: set[str],
    issues: list[str],
    intent: DeckIntent | None = None,
) -> bool:
    stats = analyze_deck(deck)
    threshold = 3.9 if intent and intent.min_cycle_cards >= 2 else 4.2
    if stats.avg_elixir <= threshold:
        return False

    db = get_database()
    intent = intent or DeckIntentEngine.infer(deck)
    plan = build_game_plan(deck, archetype=intent.archetype, intent=intent)
    solution = search_gap_solution(
        deck,
        pool,
        locked,
        intent,
        db,
        category="cycle",
        role=ROLE_CYCLE,
        suggestions=None,
        game_plan=plan,
    )
    if not solution:
        return False
    if get_card_elixir(solution.pick) >= get_card_elixir(solution.drop):
        return False

    deck[deck.index(solution.drop)] = solution.pick
    issues.append(
        f"{_card_ru(solution.drop)} → {_card_ru(solution.pick)}"
    )
    issues.append("Причина: снижает средний эликсир, сохраняя темп колоды.")
    logger.debug(
        "elixir fix %s → %s tier=%s total=%.2f",
        solution.drop, solution.pick, solution.tier.value, solution.rating.total,
    )
    return True


def _apply_suggestion(
    deck: list[str],
    pool: set[str],
    locked: set[str],
    archetype: str,
    suggestion: dict,
    issues: list[str],
    db,
    intent: DeckIntent | None = None,
) -> bool:
    """Каждый gap проходит полный ступенчатый поиск. Без «вернуть gap и выйти»."""
    category = suggestion["category"]
    message = suggestion["message"]
    suggested_cards = suggestion.get("suggested_cards") or []

    if category == "focus":
        return False

    intent = intent or DeckIntentEngine.infer(deck, archetype=archetype)
    if not _gap_relevant_for_intent(category, intent):
        return False

    role = _CATEGORY_ROLE.get(category)
    avoid_roles: frozenset[str] | None = None
    if category == "anti_air":
        avoid_roles = frozenset({ROLE_AIR})
    elif category == "point_target":
        # Не выкидываем splash/mini_tank (Валькирия) ради здания «anti_tank».
        avoid_roles = frozenset({
            ROLE_ANTI_TANK, ROLE_DEFENSIVE, ROLE_MINI_TANK, ROLE_SPLASH, ROLE_COUNTERPUSH,
        })
    elif category == "defense":
        avoid_roles = frozenset({ROLE_BUILDING, ROLE_DEFENSIVE, ROLE_SPLASH, ROLE_MINI_TANK, ROLE_COUNTERPUSH})

    plan = build_game_plan(deck, archetype=intent.archetype, intent=intent)
    solution = search_gap_solution(
        deck,
        pool,
        locked,
        intent,
        db,
        category=category,
        role=role,
        suggestions=suggested_cards,
        avoid_roles=avoid_roles,
        game_plan=plan,
    )
    if not solution:
        # Полный поиск исчерпан — реальных улучшающих карт нет
        return False

    deck[deck.index(solution.drop)] = solution.pick
    issues.append(f"{_card_ru(solution.drop)} → {_card_ru(solution.pick)}")
    issues.append(f"Причина: {message}")
    logger.debug(
        "gap fix %s → %s category=%s tier=%s total=%.2f",
        solution.drop, solution.pick, category, solution.tier.value, solution.rating.total,
    )
    return True


def _resolve_all_gaps(
    deck: list[str],
    pool: set[str],
    locked: set[str],
    archetype: str,
    issues: list[str],
    db,
    intent: DeckIntent,
    *,
    max_passes: int = 8,
) -> DeckIntent:
    """Пока есть gaps и находятся улучшения — закрываем. Иначе останавливаемся."""
    for _ in range(max_passes):
        intent = DeckIntentEngine.infer(deck, archetype=archetype)
        gaps = _collect_improvement_gaps(deck, db, intent)
        if not gaps:
            break

        progress = False
        for suggestion in gaps:
            if len(deck) != 8:
                break
            if _apply_suggestion(
                deck, pool, locked, archetype, suggestion, issues, db, intent,
            ):
                progress = True
                locked = _locked_cards(deck, db)
                intent = DeckIntentEngine.infer(deck, archetype=archetype)
        if not progress:
            # Gaps остались, но ни один не улучшается ни одной картой из pool
            break
    return intent


def _trim_spell_and_win_limits(deck: list[str], locked: set[str], db) -> None:
    while _count_spells(deck, db) > MAX_SPELLS:
        removable = [c for c in deck if _is_spell(db, c) and c not in locked]
        if not removable:
            break
        worst = min(removable, key=lambda c: _avg_synergy_with_deck(db, c, deck))
        deck.remove(worst)


def _build_synergy_map(deck: list[str], locked: set[str], pool: set[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    deck_set = set(deck)
    for card in sorted(locked):
        strong, partial = synergy_partners(card, pool, limit=6)
        partners = [p for p in strong + partial if p in deck_set and p != card][:4]
        if partners:
            result[card] = partners
    return result


def improve_player_deck(
    current_deck: list[str],
    arena_id: int | None,
    trophies: int | None = None,
    preferred_cards: list[str] | None = None,
    *,
    pool: set[str] | None = None,
) -> dict:
    """Улучшает колоду точечными заменами через RecommendationEngine."""
    from bot.services.deck_analyzer import analyze_deck
    from bot.services.recommendation_engine import RecommendationEngine

    if len(current_deck) != 8:
        result = RecommendationEngine.analyze(
            current_deck,
            arena_id=arena_id,
            trophies=trophies,
            preferred_cards=preferred_cards,
            pool=pool,
            apply_swaps=False,
        )
        return result.to_improve_dict(
            original=current_deck,
            issues=["Нужна полная колода из 8 карт"],
            avg_elixir=0.0,
        )

    result = RecommendationEngine.analyze(
        current_deck,
        arena_id=arena_id,
        trophies=trophies,
        preferred_cards=preferred_cards,
        pool=pool,
        apply_swaps=True,
    )
    improved = result.improvement_plan.improved_deck
    issues = list(result.decision_explanation.why_picks)
    if not result.improvement_plan.needed and result.risk_assessment.open_gaps:
        # gaps остались без замены
        for step in result.improvement_plan.steps:
            if step.drop is None:
                issues.append(step.message)

    db = get_database()
    locked = set(result.improvement_plan.locked)
    synergies = (
        _build_synergy_map(improved, locked, set(pool or improved))
        if result.improvement_plan.needed
        else {}
    )
    stats = analyze_deck(improved if len(improved) == 8 else current_deck)
    return result.to_improve_dict(
        original=current_deck,
        issues=issues,
        synergies=synergies,
        avg_elixir=stats.avg_elixir,
    )


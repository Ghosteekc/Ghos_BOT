"""Внутренний GamePlan колоды — для анализа и рекомендаций (не UI)."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from bot.services.card_data import WIN_CONDITIONS, card_has_role, get_card_elixir
from bot.services.card_matchups import synergy_between
from bot.services.deck_builder.archetype_detect import detect_archetype_from_cards
from bot.services.deck_builder.constants import (
    KNOWN_SYNERGY_PAIRS,
    SYNERGY_PARTIAL,
    SYNERGY_STRONG,
)
from bot.services.deck_intent import DeckIntent, DeckIntentEngine

_WIN_PLAN: dict[str, str] = {
    "Cycle": "Давление дешёвым win-condition через быстрый цикл и повторные атаки",
    "Log Bait": "Сплит-давление бочкой и bait-картами, вынуждая соперника тратить Log/малый спелл",
    "Fireball Bait": "Накопление ценности через bait и добивание большим спеллом",
    "Beatdown": "Набор танка сзади и контрпуш с поддержкой после удачной защиты",
    "Lava": "Воздушный пуш Lava Hound + Balloon с поддержкой спеллами",
    "Bridge Spam": "Агрессия на мосту несколькими угрозами, заставляя ошибаться в ответах",
    "Siege": "Контроль зданиями и набор урона осадной картой при минусе оппонента",
    "Control": "Выматывание обменами и точечный урон при преимуществе в эликсире",
    "Graveyard": "Защита → накопление → Graveyard на танк/спелл-связку",
    "Royal Giant": "Давление RG на мосту при поддержке и контроле зданиями",
    "Split Lane": "Одновременное давление на две линии дешёвыми угрозами",
    "Meta": "Гибкая игра от сильных обменов и давления основной угрозой",
}

_ATTACK_TIMING: dict[str, str] = {
    "Быстрый цикл": "Сразу после выгодного обмена или когда win снова в руке",
    "Сплит-пуш": "Когда у соперника нет малого спелла / Log или он потрачен на bait",
    "Контрпуш": "Только после успешной защиты, превращая оставшиеся войска в пуш",
    "Агрессивная": "С первых секунд и при любом плюсе эликсира",
    "Осадная": "Когда оппонент в минусе по эликсиру или контр-пуш отбит зданием",
    "Контроль": "В двойном эликсире и при явном плюсе после защиты",
    "Оборонительная": "После стопа пуша — угроза на мост с поддержкой",
    "Гибридная": "По ситуации: давление при плюсе, иначе набор через защиту",
}


@dataclass(frozen=True)
class GamePlan:
    how_to_win: str
    primary_threat: str
    when_to_attack: str
    key_cards: list[str]
    core_combinations: list[str]
    critical_weaknesses: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _pair_score(a: str, b: str) -> int:
    key = frozenset({a, b})
    if key in KNOWN_SYNERGY_PAIRS:
        return int(KNOWN_SYNERGY_PAIRS[key])
    tier = synergy_between(a, b)
    if tier == "strong":
        return SYNERGY_STRONG
    if tier == "partial":
        return SYNERGY_PARTIAL
    return 40


def _primary_win(cards: list[str], intent: DeckIntent) -> str | None:
    if intent.primary_win:
        return intent.primary_win
    wins = [c for c in cards if c in WIN_CONDITIONS or card_has_role(c, "win_condition")]
    return sorted(wins)[0] if wins else None


def _key_cards(cards: list[str], primary: str | None, intent: DeckIntent) -> list[str]:
    keys: list[str] = []
    if primary and primary in cards:
        keys.append(primary)

    scored: list[tuple[int, str]] = []
    for c in cards:
        if c == primary:
            continue
        s = 0
        if primary:
            s += _pair_score(c, primary)
        if card_has_role(c, "big_spell") or card_has_role(c, "small_spell"):
            s += 12
        if intent.require_building and card_has_role(c, "building"):
            s += 18
        if intent.min_cycle_cards > 0 and (
            card_has_role(c, "cycle") or get_card_elixir(c) <= 2
        ):
            s += 10
        if card_has_role(c, "support") or card_has_role(c, "dps") or card_has_role(c, "mini_tank"):
            s += 8
        if card_has_role(c, "tank"):
            s += 10
        scored.append((s, c))
    scored.sort(key=lambda x: (-x[0], x[1]))
    for _, c in scored:
        if len(keys) >= 5:
            break
        if c not in keys:
            keys.append(c)
    return keys[:5]


def _combinations(cards: list[str], primary: str | None) -> list[str]:
    combos: list[tuple[int, str]] = []
    card_set = set(cards)
    for pair, score in KNOWN_SYNERGY_PAIRS.items():
        a, b = tuple(sorted(pair))
        if a in card_set and b in card_set and score >= SYNERGY_PARTIAL:
            combos.append((int(score), f"{a} + {b}"))
    if primary:
        for c in sorted(cards):
            if c == primary:
                continue
            s = _pair_score(primary, c)
            if s >= SYNERGY_PARTIAL:
                text = f"{primary} + {c}"
                rev = f"{c} + {primary}"
                if not any(text == t or rev == t for _, t in combos):
                    combos.append((s, text))
    combos.sort(key=lambda x: (-x[0], x[1]))
    return [t for _, t in combos[:4]]


def _critical_weaknesses(cards: list[str], intent: DeckIntent) -> list[str]:
    out: list[str] = []
    air_n = sum(1 for c in cards if card_has_role(c, "air_defense"))
    if intent.min_air_defense > 0 and air_n < intent.min_air_defense:
        out.append("критично уязвима к воздуху (Balloon / Lava)")
    if intent.require_building and not any(card_has_role(c, "building") for c in cards):
        out.append("нет здания при осадном/контрольном плане")
    if intent.min_cycle_cards > 0:
        cycle_n = sum(1 for c in cards if card_has_role(c, "cycle") or get_card_elixir(c) <= 2)
        if cycle_n < intent.min_cycle_cards:
            out.append("недостаточно карт цикла для стратегии")
    if "anti_swarm" in intent.required_soft_checks and not any(
        card_has_role(c, "splash") or card_has_role(c, "anti_swarm") for c in cards
    ):
        out.append("критично уязвима к спаму")
    if "anti_tank" in intent.required_soft_checks and not any(
        card_has_role(c, "anti_tank") for c in cards
    ):
        out.append("критично уязвима к тяжёлым танкам")
    if not any(card_has_role(c, "big_spell") for c in cards) and "big_spell" in intent.required_soft_checks:
        out.append("нет большого заклинания для добивания / защиты")
    return out[:5]


def build_game_plan(
    cards: list[str],
    *,
    archetype: str | None = None,
    intent: DeckIntent | None = None,
) -> GamePlan:
    """Построить внутренний GamePlan для колоды."""
    arch = archetype or detect_archetype_from_cards(cards)
    intent = intent or DeckIntentEngine.infer(cards, archetype=arch)
    primary = _primary_win(cards, intent)
    play = intent.play_style

    how = _WIN_PLAN.get(arch, _WIN_PLAN["Meta"])
    if primary:
        how = f"{how}. Основной инструмент — {primary} ({play.lower()} стиль)"

    if primary:
        threat = f"{primary} — главная угроза башне и ось давления архетипа {arch}"
    else:
        threat = "Нет явной win-condition — давление размыто"

    when = _ATTACK_TIMING.get(play, _ATTACK_TIMING["Гибридная"])
    if intent.min_cycle_cards >= 2:
        when = f"{when}. Цикл важен — атаковать при возврате win в руку"
    elif intent.attack_bias >= 0.7:
        when = f"{when}. Высокий attack bias — держать постоянное давление"

    return GamePlan(
        how_to_win=how,
        primary_threat=threat,
        when_to_attack=when,
        key_cards=_key_cards(cards, primary, intent),
        core_combinations=_combinations(cards, primary),
        critical_weaknesses=_critical_weaknesses(cards, intent),
    )

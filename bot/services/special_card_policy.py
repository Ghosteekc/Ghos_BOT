"""SpecialCardPolicy — situational-карты не являются обычными fillers.

Mirror / Clone / Freeze / Rage / Goblin Curse и аналоги запрещены
в автодоборе, компромиссах и закрытии role gaps, пока DeckIntent,
GamePlan или шаблон архетипа явно не предусматривают карту.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.services.deck_game_plan import GamePlan
    from bot.services.deck_intent import DeckIntent

# Карты со специальной механикой — не замена Log/Zap/Fireball.
SPECIAL_CARDS: frozenset[str] = frozenset({
    "Mirror",
    "Clone",
    "Freeze",
    "Rage",
    "Goblin Curse",
    "Tornado",
    "Void",
    "Vines",
})

# Явные «триггеры» в колоде/ядре, без которых карта бессмысленна как filler.
# Mirror / Void / Vines — пусто: только Intent / GamePlan / ARCHETYPE_ANCHORS.
SPECIAL_CARD_ENABLERS: dict[str, frozenset[str]] = {
    "Freeze": frozenset({"Graveyard", "Balloon", "Sparky"}),
    "Rage": frozenset({
        "Balloon", "Lava Hound", "Elixir Golem", "Battle Healer", "Golem",
    }),
    "Clone": frozenset({
        "Balloon", "Lava Hound", "Golem", "Elixir Golem", "Night Witch",
        "Skeleton Barrel",
    }),
    "Mirror": frozenset(),
    "Goblin Curse": frozenset({
        "Goblin Barrel", "Goblin Gang", "Goblin Giant", "Spear Goblins",
        "Dart Goblin", "Goblin Demolisher", "Goblin Cage", "Goblin Drill",
        "Goblin Hut",
    }),
    "Tornado": frozenset({
        "Executioner", "Wizard", "Sparky", "Inferno Dragon", "Baby Dragon",
        "Bowler", "Electro Wizard", "Royal Delivery",
    }),
    "Void": frozenset(),
    "Vines": frozenset(),
}

# Штраф к CandidateRating.total, если special не разрешён явно.
SPECIAL_CARD_RATING_PENALTY = 80.0


class SpecialCardPolicy:
    """Единые правила для situational spells / special mechanics."""

    @staticmethod
    def is_special(card: str) -> bool:
        return card in SPECIAL_CARDS

    @staticmethod
    def is_allowed(
        card: str,
        *,
        deck: list[str] | set[str] | None = None,
        archetype: str | None = None,
        intent: "DeckIntent | None" = None,
        game_plan: "GamePlan | None" = None,
    ) -> bool:
        """True только при явном контексте под карту.

        Источники разрешения (любой один достаточен):
        - карта в ARCHETYPE_ANCHORS архетипа;
        - карта в GamePlan.key_cards / core_combinations;
        - в колоде есть enabler из SPECIAL_CARD_ENABLERS
          (или primary_win Intent — enabler);
        - известная синергия KNOWN_SYNERGY_PAIRS с картой уже в колоде.
        """
        if not SpecialCardPolicy.is_special(card):
            return True

        # Ленивый импорт — иначе cycle: constants ← deck_builder.__init__ ← balance.
        from bot.services.deck_builder.constants import ARCHETYPE_ANCHORS, KNOWN_SYNERGY_PAIRS

        arch = archetype or (intent.archetype if intent else None)
        if arch and card in ARCHETYPE_ANCHORS.get(arch, ()):
            return True

        if game_plan is not None:
            if card in game_plan.key_cards:
                return True
            for combo in game_plan.core_combinations:
                parts = [p.strip() for p in combo.replace("→", "+").split("+")]
                if card in parts:
                    return True

        present: set[str] = set(deck or ())
        if intent is not None:
            if intent.primary_win:
                present.add(intent.primary_win)
            if arch is None:
                arch = intent.archetype
                if arch and card in ARCHETYPE_ANCHORS.get(arch, ()):
                    return True

        enablers = SPECIAL_CARD_ENABLERS.get(card, frozenset())
        if enablers and present & enablers:
            return True

        for pair in KNOWN_SYNERGY_PAIRS:
            if card not in pair:
                continue
            other = next(iter(pair - {card}))
            if other in present:
                return True

        return False

    @staticmethod
    def forbid_as_auto_pick(
        card: str,
        *,
        deck: list[str] | set[str] | None = None,
        archetype: str | None = None,
        intent: "DeckIntent | None" = None,
        game_plan: "GamePlan | None" = None,
    ) -> bool:
        """Запрет для автодобора / gap / compromise."""
        return SpecialCardPolicy.is_special(card) and not SpecialCardPolicy.is_allowed(
            card,
            deck=deck,
            archetype=archetype,
            intent=intent,
            game_plan=game_plan,
        )

    @staticmethod
    def rating_penalty(
        card: str,
        *,
        deck: list[str] | set[str] | None = None,
        archetype: str | None = None,
        intent: "DeckIntent | None" = None,
        game_plan: "GamePlan | None" = None,
    ) -> float:
        """Очень большой штраф к total, если special без явного контекста."""
        if SpecialCardPolicy.forbid_as_auto_pick(
            card,
            deck=deck,
            archetype=archetype,
            intent=intent,
            game_plan=game_plan,
        ):
            return SPECIAL_CARD_RATING_PENALTY
        return 0.0

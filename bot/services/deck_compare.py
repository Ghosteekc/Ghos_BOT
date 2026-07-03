"""Side-by-side deck comparison for arena / meta views."""

from __future__ import annotations

from bot.services.card_data import COUNTERS
from bot.services.card_names_ru import card_name_ru
from bot.services.deck_analyzer import analyze_deck, find_opponent_threats

_AIR_DEFENSE = {
    "Musketeer", "Wizard", "Executioner", "Inferno Dragon", "Mini P.E.K.K.A",
    "Mega Minion", "Electro Wizard", "Hunter", "Inferno Tower", "Tesla",
    "Archers", "Bats", "Minions", "Mega Minion", "Phoenix", "Firecracker",
}

_GROUND_DEFENSE = {
    "Knight", "Valkyrie", "P.E.K.K.A", "Barbarians", "Guards", "Bowler",
    "Cannon", "Tesla", "Inferno Tower", "Bomb Tower", "Skeleton Army",
}


def _label(card: str) -> str:
    return card_name_ru(card, short=True) or card


def compare_decks(user_cards: list[str], ref_cards: list[str]) -> dict[str, list[str]]:
    """Return RU bullet lists: user_better, user_worse, reference_better, reference_worse."""
    user_better: list[str] = []
    user_worse: list[str] = []
    ref_better: list[str] = []
    ref_worse: list[str] = []

    if len(user_cards) != 8 or len(ref_cards) != 8:
        return {
            "user_better": [],
            "user_worse": ["Нужна полная колода из 8 карт для сравнения"],
            "reference_better": [],
            "reference_worse": [],
        }

    u = analyze_deck(user_cards)
    r = analyze_deck(ref_cards)

    if u.air_coverage and not r.air_coverage:
        user_better.append("Есть защита от воздушных карт")
        ref_worse.append("Нет защиты от воздуха")
    elif not u.air_coverage and r.air_coverage:
        user_worse.append("Нет защиты от воздушных карт")
        ref_better.append("Есть защита от воздуха")

    u_air = len(set(user_cards) & _AIR_DEFENSE)
    r_air = len(set(ref_cards) & _AIR_DEFENSE)
    if u_air > r_air + 1:
        user_better.append("Больше карт против воздуха")
        ref_worse.append("Меньше защиты воздуха")
    elif r_air > u_air + 1:
        user_worse.append("Меньше защиты воздуха")
        ref_better.append("Сильнее против воздушных угроз")

    if u.splash_coverage and not r.splash_coverage:
        user_better.append("Лучше защита от роя (сплеш)")
        ref_worse.append("Слабая защита от роя")
    elif not u.splash_coverage and r.splash_coverage:
        user_worse.append("Слабая защита от роя — нет сплеша")
        ref_better.append("Есть сплеш против роя")

    u_spells = len(u.spells)
    r_spells = len(r.spells)
    if u_spells == 0:
        user_worse.append("Нет заклинаний — сложнее контролировать поле")
    elif u_spells < r_spells:
        user_worse.append(f"Мало заклинаний ({u_spells} vs {r_spells})")
        ref_better.append("Больше заклинаний для контроля")
    elif u_spells > r_spells:
        user_better.append(f"Больше заклинаний ({u_spells} vs {r_spells})")
        ref_worse.append("Меньше заклинаний")

    if u_spells >= 2 and r_spells >= 2:
        u_spell_set = frozenset(u.spells)
        r_spell_set = frozenset(r.spells)
        if u_spell_set != r_spell_set and not u_spell_set & {"Fireball", "Lightning", "Rocket", "Poison"}:
            if any(c in ref_cards for c in ("Giant", "Golem", "Lava Hound", "Royal Giant")):
                user_worse.append("Заклинания слабо бьют по тяжёлым пушам соперника")

    if u.avg_elixir + 0.35 < r.avg_elixir:
        user_better.append(f"Быстрее цикл ({u.avg_elixir} vs {r.avg_elixir} эликсира)")
        ref_worse.append(f"Тяжелее колода ({r.avg_elixir} эликсира)")
    elif u.avg_elixir > r.avg_elixir + 0.35:
        user_worse.append(f"Колода тяжелее ({u.avg_elixir} vs {r.avg_elixir} эликсира)")
        ref_better.append(f"Быстрее цикл ({r.avg_elixir} эликсира)")

    u_build = len(u.buildings)
    r_build = len(r.buildings)
    if u_build > r_build:
        user_better.append("Больше построек для обороны")
        ref_worse.append("Мало построек")
    elif r_build > u_build and r_build > 0:
        user_worse.append("Нет построек для удержания агро")
        ref_better.append("Есть постройка для обороны")

    u_ground = len(set(user_cards) & _GROUND_DEFENSE)
    r_ground = len(set(ref_cards) & _GROUND_DEFENSE)
    if r_ground > u_ground + 1:
        user_worse.append("Слабее защита от наземных атакующих карт")
        ref_better.append("Сильнее наземная оборона")

    for threat in find_opponent_threats(ref_cards):
        counters = COUNTERS.get(threat, [])
        u_has = [c for c in counters if c in user_cards]
        r_has = [c for c in counters if c in ref_cards]
        t = _label(threat)
        if r_has and not u_has:
            user_worse.append(f"Нет ответа на {t}")
            ref_better.append(f"Есть защита от ваших угроз через {t}")
        elif u_has and not r_has:
            user_better.append(f"Есть ответ на {t}")
            ref_worse.append(f"Нет ответа на {t}")

    for threat in find_opponent_threats(user_cards):
        counters = COUNTERS.get(threat, [])
        u_has = [c for c in counters if c in user_cards]
        r_has = [c for c in counters if c in ref_cards]
        t = _label(threat)
        if r_has and not u_has:
            ref_better.append(f"Есть ответ на ваш {t}")
        elif not r_has and u_has:
            ref_worse.append(f"Слабее против {t}")

    if not u.win_conditions:
        user_worse.append("Нет явного win-condition")
    if len(u.win_conditions) > 1 and len(r.win_conditions) <= 1:
        user_worse.append("Несколько win-condition — колода может быть нестабильной")

    def _dedupe(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for item in items:
            if item not in seen:
                seen.add(item)
                out.append(item)
        return out[:8]

    return {
        "user_better": _dedupe(user_better),
        "user_worse": _dedupe(user_worse),
        "reference_better": _dedupe(ref_better),
        "reference_worse": _dedupe(ref_worse),
    }

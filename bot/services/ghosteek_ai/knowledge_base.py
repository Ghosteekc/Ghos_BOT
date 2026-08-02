"""Curated Knowledge Base для механик Clash Royale (без выдуманных цифр)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MechanicEntry:
    key: str
    title: str
    summary: str
    tips: tuple[str, ...] = ()


MECHANICS: dict[str, MechanicEntry] = {
    "cycle": MechanicEntry(
        key="cycle",
        title="Cycle (цикл)",
        summary=(
            "Цикл — скорость, с которой вы возвращаете ключевые карты в руку. "
            "Чем дешевле средняя колода и чем больше дешёвых «cycle»-карт, "
            "тем быстрее снова доступен win condition."
        ),
        tips=(
            "1–2 эликсирные карты ускоряют цикл.",
            "Против тяжёлых колод быстрый цикл даёт повторные атаки.",
        ),
    ),
    "elixir_trade": MechanicEntry(
        key="elixir_trade",
        title="Elixir trade",
        summary=(
            "Elixir trade — сравнение эликсира, потраченного вами и соперником "
            "на один фрагмент розыгрыша. Цель — чаще выходить в плюс."
        ),
        tips=(
            "Positive trade: вы потратили меньше эликсира, чем соперник.",
            "Negative trade: вы потратили больше — допустим ради башни или темпа.",
        ),
    ),
    "positive_elixir_trade": MechanicEntry(
        key="positive_elixir_trade",
        title="Positive elixir trade",
        summary=(
            "Positive elixir trade — вы ответили на розыгрыш соперника меньшим "
            "эликсиром (например, 3 эл. ответ на 5 эл. пуш) и сохранили преимущество."
        ),
        tips=(
            "Дешёвые ответы на дорогие пуши — основа контроля.",
            "Плюс по эликсиру обычно конвертируют в свою атаку.",
        ),
    ),
    "negative_elixir_trade": MechanicEntry(
        key="negative_elixir_trade",
        title="Negative elixir trade",
        summary=(
            "Negative elixir trade — вы потратили больше эликсира, чем соперник. "
            "Иногда это осознанно: спасти башню, убрать win condition, выиграть темп."
        ),
        tips=("После минуса не спамьте — восстановите эликсир и цикл.",),
    ),
    "bridge_spam": MechanicEntry(
        key="bridge_spam",
        title="Bridge spam",
        summary=(
            "Bridge spam — давление дешёвыми/средними картами прямо с моста "
            "(Bandit, Battle Ram, Royal Ghost и т.п.), чтобы перегрузить защиту "
            "и заставить ошибиться по эликсиру."
        ),
        tips=(
            "Важно иметь ответы на одиночные угрозы у моста.",
            "Контрпуш после защиты — типичный план против spam.",
        ),
    ),
    "dual_lane_pressure": MechanicEntry(
        key="dual_lane_pressure",
        title="Dual lane pressure",
        summary=(
            "Dual lane pressure — одновременное или быстро чередующееся давление "
            "на обе линии, чтобы защита соперника не успевала на обе стороны."
        ),
        tips=(
            "Работает при преимуществе по эликсиру или быстром цикле.",
            "Слабее против тяжёлых сплит-защит и широких спеллов.",
        ),
    ),
    "beatdown": MechanicEntry(
        key="beatdown",
        title="Beatdown",
        summary=(
            "Beatdown — тяжёлый пуш за танком (Golem, Lava Hound, Giant): "
            "накапливаете поддержку сзади и продавливаете одну линию."
        ),
        tips=("Не отдавайте дешёвые плюсы до большого пуша.",),
    ),
    "control": MechanicEntry(
        key="control",
        title="Control",
        summary=(
            "Control — защита с плюсом по эликсиру и точечные контрпуши "
            "(часто X-Bow, mortar-control, mid-ladder midrange)."
        ),
    ),
    "bait": MechanicEntry(
        key="bait",
        title="Bait (Log Bait и аналоги)",
        summary=(
            "Bait провоцирует маленькие спеллы соперника (Log/Zap/Arrows), "
            "после чего проходит основной win condition (бочка, wall breakers и т.д.)."
        ),
    ),
    "spell_cycle": MechanicEntry(
        key="spell_cycle",
        title="Spell cycle",
        summary=(
            "Spell cycle — добор урона по башне повторными спеллами, "
            "когда прямой пуш рискован или башня уже низкая."
        ),
    ),
    "kiting": MechanicEntry(
        key="kiting",
        title="Kiting",
        summary=(
            "Kiting — оттягивание юнита (часто танков) дешёвой картой в зону "
            "вашей башни/защиты, чтобы выиграть время и эликсир."
        ),
    ),
    "tank": MechanicEntry(
        key="tank",
        title="Tank",
        summary=(
            "Tank — юнит с высоким HP впереди пуша; поддержка идёт сзади. "
            "Win condition часто именно танк или то, что идёт за ним."
        ),
    ),
}


def lookup_mechanic(key: str | None) -> MechanicEntry | None:
    if not key:
        return None
    return MECHANICS.get(key)


def list_mechanic_titles() -> list[str]:
    return [m.title for m in MECHANICS.values()]

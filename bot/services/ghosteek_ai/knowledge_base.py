"""Knowledge Base — короткий словарь терминов Clash Royale для Ghosteek AI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MechanicEntry:
    key: str
    title: str
    summary: str
    example: str
    tip: str = ""


# Короткие карточки: суть + пример. Без «википедии».
MECHANICS: dict[str, MechanicEntry] = {
    "cycle": MechanicEntry(
        key="cycle",
        title="Cycle",
        summary="Скорость возврата ключевых карт в руку. Дешёвая колода = быстрее снова доступен win condition.",
        example="В Hog 2.6 после Hog ты быстро снова достаёшь его через Skeletons / Ice Spirit.",
        tip="Считай цикл, когда решаешь, давить сейчас или подождать карту.",
    ),
    "beatdown": MechanicEntry(
        key="beatdown",
        title="Beatdown",
        summary="Тяжёлый пуш за танком: копишь поддержку сзади и продавливаешь одну линию.",
        example="Golem впереди, сзади Night Witch / Baby Dragon — классический beatdown.",
        tip="До большого пуша не раздавай бесплатные плюсы по эликсиру.",
    ),
    "control": MechanicEntry(
        key="control",
        title="Control",
        summary="Игра через защиту с плюсом и точечные контрпуши, а не через огромный танк.",
        example="X-Bow / Mortar: отбил атаку дёшево — сразу давление зданием или шахтёром.",
        tip="Цель — выиграть трейды, потом конвертировать плюс в урон.",
    ),
    "bridge_spam": MechanicEntry(
        key="bridge_spam",
        title="Bridge Spam",
        summary="Давление дешёвыми угрозами прямо с моста, чтобы перегрузить защиту.",
        example="Bandit + Battle Ram с моста заставляют держать ответы на обе угрозы.",
        tip="Имей дешёвый ответ на одиночку у моста — иначе получишь башню.",
    ),
    "split_push": MechanicEntry(
        key="split_push",
        title="Split Push",
        summary="Давление сразу на две линии или быстрый сплит, чтобы защита не успела на обе.",
        example="Royal Hogs по двум мостам или Goblin Giant + бочка на другую линию.",
        tip="Сплит силён, когда у тебя плюс по эликсиру или быстрый цикл.",
    ),
    "positive_elixir_trade": MechanicEntry(
        key="positive_elixir_trade",
        title="Positive Elixir Trade",
        summary="Ты потратил меньше эликсира, чем соперник, на тот же фрагмент розыгрыша.",
        example="Ответ 3 эл. на 5-эликсирный пуш — плюс +2, можно сразу давить.",
        tip="Плюс почти всегда конвертируй в атаку, а не сиди в афк.",
    ),
    "negative_elixir_trade": MechanicEntry(
        key="negative_elixir_trade",
        title="Negative Trade",
        summary="Ты потратил больше эликсира, чем соперник. Иногда это ок ради башни или темпа.",
        example="Fireball + Zap по бочке и принцессе — минус по эликсиру, но спас башню.",
        tip="После минуса не overcommit — восстанови цикл и эликсир.",
    ),
    "elixir_trade": MechanicEntry(
        key="elixir_trade",
        title="Elixir Trade",
        summary="Сравнение эликсира на куске боя: кто потратил меньше — тот в плюсе.",
        example="Knight (3) съел Mini P.E.K.K.A (4) под башней — небольшой плюс.",
        tip="Смотри не только «убил/не убил», а сколько эликсира ушло.",
    ),
    "tempo": MechanicEntry(
        key="tempo",
        title="Tempo",
        summary="Кто задаёт ритм боя: ты заставляешь отвечать или сам догоняешь угрозы.",
        example="Выставил здание заранее — соперник уже реагирует, темп у тебя.",
        tip="Проигрыш темпа часто хуже небольшого минуса по эликсиру.",
    ),
    "pressure": MechanicEntry(
        key="pressure",
        title="Pressure",
        summary="Постоянные угрозы, из‑за которых соперник не может спокойно копить свой пуш.",
        example="Chip Хогом каждые 10–12 секунд не даёт спокойно собрать Golem.",
        tip="Давление без эликсира = overcommit. Дави, когда есть плюс или цикл.",
    ),
    "counterpush": MechanicEntry(
        key="counterpush",
        title="Counterpush",
        summary="Атака сразу после защиты выжившими войсками — самый выгодный момент.",
        example="Отбил Hog Мушкетёром — Мушкетёр идёт в контрпуш с твоим Ice Golem.",
        tip="Не сбрасывай живых юнитов зря: они уже оплачены эликсиром.",
    ),
    "win_condition": MechanicEntry(
        key="win_condition",
        title="Win Condition",
        summary="Карта (или связка), которой ты стабильно наносишь урон башне.",
        example="Hog Rider, Royal Giant, Balloon, X-Bow, Goblin Barrel — типичные WC.",
        tip="Вся колода строится вокруг того, как провести win condition.",
    ),
    "support_card": MechanicEntry(
        key="support_card",
        title="Support Card",
        summary="Карта поддержки: чистит, защищает или усиливает пуш, но сама редко ломает башню.",
        example="Musketeer / Mega Minion за Golem или рядом с Hog.",
        tip="Не путай саппорт с win condition — роли разные.",
    ),
    "mini_tank": MechanicEntry(
        key="mini_tank",
        title="Mini Tank",
        summary="Недорогой танк на 3–4 эликсира: держит урон и открывает путь саппорту или WC.",
        example="Knight, Ice Golem, Valkyrie впереди лучников или шахтёра.",
        tip="Мини-танк часто лучший ответ на одиночную угрозу у моста.",
    ),
    "reset": MechanicEntry(
        key="reset",
        title="Reset",
        summary="Сброс заряда атаки (Inferno, Sparky и т.п.) электро-эффектом или оттягиванием.",
        example="Zap / Electro Spirit по Inferno Tower сбрасывает заряд — Hog проходит.",
        tip="Без ресета тяжёлый танк часто умирает впустую в Inferno.",
    ),
    "kiting": MechanicEntry(
        key="kiting",
        title="Kiting",
        summary="Оттягивание юнита дешёвой картой в зону башни/защиты, чтобы выиграть время.",
        example="Ice Golem уводит Mega Knight на свою сторону — башни помогают добить.",
        tip="Кайт работает, если юнит реально переключает агро.",
    ),
    "lane_control": MechanicEntry(
        key="lane_control",
        title="Lane Control",
        summary="Кто владеет линией: можешь ли ты безопасно давить и не получать бесплатный урон.",
        example="Здание на своей половине + дешёвый цикл = контроль линии против Hog.",
        tip="Потерял контроль линии — сначала стабилизируй, потом атакуй.",
    ),
    "spell_cycle": MechanicEntry(
        key="spell_cycle",
        title="Spell Cycle",
        summary="Добор башни повторными спеллами, когда лобовой пуш рискован или башня уже низкая.",
        example="Rocket / Fireball cycle в эндгейме, когда X-Bow уже не ставится.",
        tip="Не сливай оба спелла рано — оставь на добор или защиту от свайпа.",
    ),
    "overcommit": MechanicEntry(
        key="overcommit",
        title="Overcommit",
        summary="Слишком много эликсира в атаку/защиту сразу — соперник отвечает дёшево и контрпушит.",
        example="Кинул 12 эликсира в пуш, получил Log + здание — и остался без руки.",
        tip="Если рука пустая, а у врага полный эликсир — ты уже overcommit'нул.",
    ),
    "dual_lane_pressure": MechanicEntry(
        key="dual_lane_pressure",
        title="Dual Lane Pressure",
        summary="Быстрое давление на обе линии, чтобы ответы не успевали на обе стороны.",
        example="Угроза слева зданием, справа Hog — соперник ошибается в распределении.",
        tip="Нужен плюс по эликсиру или очень быстрый цикл.",
    ),
    "bait": MechanicEntry(
        key="bait",
        title="Bait",
        summary="Провокация маленького спелла соперника, после чего проходит основной win condition.",
        example="Princess / Gang выманивают Log — затем Goblin Barrel заходит чище.",
        tip="Не трать свой Log первым на мелочь, если ждёшь бочку.",
    ),
    "tank": MechanicEntry(
        key="tank",
        title="Tank",
        summary="Толстый юнит впереди пуша; саппорт идёт сзади под его HP.",
        example="Golem / Giant / Lava Hound как стена для поддержки.",
        tip="Танк без поддержки часто бесплатно умирает в зданиях.",
    ),
}


# Длинные алиасы первыми
_ALIAS_TO_KEY: list[tuple[str, str]] = sorted(
    [
        ("positive elixir trade", "positive_elixir_trade"),
        ("negative elixir trade", "negative_elixir_trade"),
        ("позитивный трейд", "positive_elixir_trade"),
        ("позитивн", "positive_elixir_trade"),
        ("плюс по эликсир", "positive_elixir_trade"),
        ("негативный трейд", "negative_elixir_trade"),
        ("негативн", "negative_elixir_trade"),
        ("минус по эликсир", "negative_elixir_trade"),
        ("negative trade", "negative_elixir_trade"),
        ("elixir trade", "elixir_trade"),
        ("обмен эликсир", "elixir_trade"),
        ("эликсир трейд", "elixir_trade"),
        ("bridge spam", "bridge_spam"),
        ("бридж спам", "bridge_spam"),
        ("спам с моста", "bridge_spam"),
        ("split push", "split_push"),
        ("сплит пуш", "split_push"),
        ("сплитпуш", "split_push"),
        ("dual lane", "dual_lane_pressure"),
        ("две линии", "dual_lane_pressure"),
        ("lane control", "lane_control"),
        ("контроль линии", "lane_control"),
        ("spell cycle", "spell_cycle"),
        ("спелл цикл", "spell_cycle"),
        ("win condition", "win_condition"),
        ("винкондишн", "win_condition"),
        ("вин кондишн", "win_condition"),
        ("support card", "support_card"),
        ("саппорт карт", "support_card"),
        ("карта поддержки", "support_card"),
        ("mini tank", "mini_tank"),
        ("мини танк", "mini_tank"),
        ("мини-танк", "mini_tank"),
        ("counterpush", "counterpush"),
        ("counter push", "counterpush"),
        ("контрпуш", "counterpush"),
        ("контр-пуш", "counterpush"),
        ("overcommit", "overcommit"),
        ("оверкоммит", "overcommit"),
        ("перерасход", "overcommit"),
        ("card cycle", "cycle"),
        ("быстрый цикл", "cycle"),
        ("цикл колоды", "cycle"),
        ("log bait", "bait"),
        ("битдаун", "beatdown"),
        ("beatdown", "beatdown"),
        ("bridge", "bridge_spam"),
        ("pressure", "pressure"),
        ("давление", "pressure"),
        ("control", "control"),
        ("контроль", "control"),
        ("tempo", "tempo"),
        ("темп", "tempo"),
        ("kiting", "kiting"),
        ("кайт", "kiting"),
        ("kite", "kiting"),
        ("cycle", "cycle"),
        ("цикл", "cycle"),
        ("reset", "reset"),
        ("ресет", "reset"),
        ("сброс заряда", "reset"),
        ("bait", "bait"),
        ("бейт", "bait"),
        ("tank", "tank"),
        ("танк", "tank"),
        ("support", "support_card"),
        ("саппорт", "support_card"),
        ("винкон", "win_condition"),
        ("wc", "win_condition"),
    ],
    key=lambda x: len(x[0]),
    reverse=True,
)


def lookup_mechanic(key: str | None) -> MechanicEntry | None:
    if not key:
        return None
    return MECHANICS.get(key)


def resolve_mechanic_key(text: str) -> str | None:
    """Найти ключ термина по фразе игрока (самый длинный алиас)."""
    low = (text or "").lower()
    for alias, key in _ALIAS_TO_KEY:
        if alias in low:
            return key
    return None


def list_mechanic_titles(*, limit: int = 12) -> list[str]:
    titles = [m.title for m in MECHANICS.values()]
    return titles[:limit]


def format_mechanic_answer(entry: MechanicEntry) -> str:
    """Короткий ответ тренера: до нескольких предложений, с примером."""
    parts = [
        f"{entry.title} — {entry.summary}",
        f"Пример: {entry.example}",
    ]
    if entry.tip:
        parts.append(entry.tip)
    return "\n\n".join(parts)

"""Детект интента Ghosteek AI — закрытый набор, без угадывания."""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.services.card_data import CARD_META
from bot.services.card_names_ru import CARD_NAMES_RU, CARD_NAMES_SHORT
from bot.services.ghosteek_ai.constraints import is_unsupported_request
from bot.services.ghosteek_ai.knowledge_base import resolve_mechanic_key

# Intent → сервис (этап 1)
INTENT_BUILD_DECK = "build_deck"  # Builder
INTENT_ANALYZE_DECK = "analyze_deck"  # Analyzer
INTENT_IMPROVE_DECK = "improve_deck"  # Recommendation
INTENT_MATCHUP = "matchup"  # Matchup Analyzer
INTENT_LAST_BATTLE = "last_battle"  # Battle Analyzer
INTENT_CARD_INFO = "card_info"  # Card Database
INTENT_EXPLAIN_MECHANIC = "explain_mechanic"  # Knowledge Base
INTENT_GAME_COACH = "game_coach"  # Game Coach
INTENT_UNSUPPORTED = "unsupported"
INTENT_CLARIFY = "clarify"
INTENT_CHAT = "chat"  # Conversational: small talk / persona — без игровых tools

# Совместимость со старыми тестами / API
INTENT_UNKNOWN = INTENT_CLARIFY
INTENT_STATS = "stats"  # вне этапа 1 → clarify
INTENT_META = "meta"  # вне этапа 1 → clarify

SERVICE_BY_INTENT: dict[str, str] = {
    INTENT_BUILD_DECK: "Builder",
    INTENT_ANALYZE_DECK: "Analyzer",
    INTENT_IMPROVE_DECK: "Recommendation",
    INTENT_MATCHUP: "Matchup Analyzer",
    INTENT_LAST_BATTLE: "Battle Analyzer",
    INTENT_CARD_INFO: "Card Database",
    INTENT_EXPLAIN_MECHANIC: "Knowledge Base",
    INTENT_GAME_COACH: "Game Coach",
    INTENT_UNSUPPORTED: "HonestFallback",
    INTENT_CLARIFY: "Clarify",
    INTENT_CHAT: "Chat",
}

# Шаблон только когда intent реально неясен (не small talk).
CLARIFY_PROMPT = (
    "Не совсем понял задачу. Могу собрать колоду, разобрать состав, "
    "матчап или бой, объяснить карту или термин — напиши, что нужно."
)

# Вариативные fallback-ответы для conversational (если LLM недоступна / gate).
CHAT_FALLBACK_PROMPTS: tuple[str, ...] = (
    "Привет 👋 Я на месте. Могу колоду поковырять, бой разобрать или просто поболтать.",
    "О, привет. Готов поработать коучем 😎 Колода, бой или просто болталка?",
    "Здарова. Чем займёмся — сборка, разбор или свободный разговор?",
)


@dataclass
class DetectedIntent:
    intent: str
    cards: list[str] = field(default_factory=list)
    opponent_cards: list[str] = field(default_factory=list)
    card_query: str | None = None
    mechanic_query: str | None = None
    coach_topic: str | None = None
    service: str = ""
    raw: str = ""

    def __post_init__(self) -> None:
        if not self.service:
            self.service = SERVICE_BY_INTENT.get(self.intent, "Clarify")


def _build_alias_index() -> list[tuple[str, str]]:
    """(alias_lower, english_name), longest first."""
    pairs: dict[str, str] = {}
    for en in CARD_META:
        pairs[en.lower()] = en
    for en, ru in CARD_NAMES_RU.items():
        pairs[ru.lower()] = en
        pairs[en.lower()] = en
    for en, ru in CARD_NAMES_SHORT.items():
        pairs[ru.lower()] = en
    extras = {
        "хог": "Hog Rider",
        "хога": "Hog Rider",
        "хогом": "Hog Rider",
        "хогу": "Hog Rider",
        "хоге": "Hog Rider",
        "hog": "Hog Rider",
        "ведьма": "Witch",
        "ведьмы": "Witch",
        "ведьме": "Witch",
        "ведьму": "Witch",
        "ведьмой": "Witch",
        "ведьмою": "Witch",
        "пекка": "P.E.K.K.A",
        "pekka": "P.E.K.K.A",
        "мини пекка": "Mini P.E.K.K.A",
        "фаербол": "Fireball",
        "файрбол": "Fireball",
        "торнадо": "Tornado",
        "палач": "Executioner",
        "палача": "Executioner",
        "лава": "Lava Hound",
        "лавы": "Lava Hound",
        "шарик": "Balloon",
        "шарика": "Balloon",
        "шар": "Balloon",
        "бочка": "Goblin Barrel",
        "бочку": "Goblin Barrel",
        "принцесса": "Princess",
        "принцессу": "Princess",
        "логи": "The Log",
        "бревно": "The Log",
        "лог": "The Log",
        "землетряс": "Earthquake",
        "eq": "Earthquake",
        "lavaloon": "Lava Hound",
        "лавалун": "Lava Hound",
    }
    for alias, en in extras.items():
        pairs.setdefault(alias, en)

    # Авто-склонение однословных RU-номинативов (ведьма→ведьмой).
    for base, en in list(pairs.items()):
        if not base or " " in base or "-" in base:
            continue
        if not any("а" <= ch <= "я" or ch in "ёь" for ch in base):
            continue
        for form in _ru_case_forms(base):
            pairs.setdefault(form, en)

    # Составные / дефисные RU-имена + разговорные фразы (эликсирный голем, …).
    for en, ru in list(CARD_NAMES_RU.items()) + list(CARD_NAMES_SHORT.items()):
        ru_l = (ru or "").lower().replace("ё", "е").strip()
        if not ru_l:
            continue
        if " " in ru_l or "-" in ru_l:
            for form in _phrase_case_forms(ru_l):
                pairs.setdefault(form, en)
            # Дефис → пробел и перестановка частей («скелет-король» → «скелет король»).
            if "-" in ru_l and " " not in ru_l:
                left, right = ru_l.split("-", 1)
                for spaced in (f"{left} {right}", f"{right} {left}"):
                    pairs.setdefault(spaced, en)
                    for form in _phrase_case_forms(spaced):
                        pairs.setdefault(form, en)

    for en, phrases in _SPOKEN_COMPOUNDS.items():
        for ph in phrases:
            ph_l = ph.lower().replace("ё", "е")
            pairs.setdefault(ph_l, en)
            for form in _phrase_case_forms(ph_l):
                pairs.setdefault(form, en)

    return sorted(pairs.items(), key=lambda x: len(x[0]), reverse=True)


# Разговорные полные имена, которых нет (или обрезаны) в CARD_NAMES_*.
# Сленг, перестановки слов, сокращения — всё резолвится в EN id.
_SPOKEN_COMPOUNDS: dict[str, list[str]] = {
    "Elixir Golem": [
        "эликсирный голем",
        "элик голем",
        "элик-голем",
        "elixir golem",
    ],
    "Ice Golem": [
        "ледяной голем",
        "айс голем",
        "ice golem",
        "терпила",
    ],
    "Night Witch": [
        "ночная ведьма",
        "night witch",
        "ночнуха",
    ],
    "Skeleton King": [
        "король скелетов",
        "короля скелетов",
        "королём скелетов",
        "королем скелетов",
        "королю скелетов",
        "короле скелетов",
        "скелет король",
        "скелетного короля",
        "скелетным королём",
        "скел король",
        "скелкороль",
        "skeleton king",
    ],
    "Giant Skeleton": [
        "гигантский скелет",
        "гигантского скелета",
        "гигантским скелетом",
        "гиг скелет",
        "гиг-скелет",
        "giant skeleton",
    ],
    "Skeleton Army": [
        "армия скелетов",
        "армию скелетов",
        "армией скелетов",
        "скелет армия",
        "skeleton army",
    ],
    "Dart Goblin": [
        "плевака",
        "плеваки",
        "плеваку",
        "плевакой",
        "дарт гоблин",
        "dart goblin",
    ],
    "Mother Witch": [
        "бабуля",
        "бабули",
        "бабулю",
        "бабулей",
        "мама ведьма",
        "mother witch",
    ],
    "Mega Knight": [
        "меганайт",
        "мега найт",
        "мегарыцарь",
        "мегарыцаря",
        "мега рыцарь",
        "мега-рыцарь",
        "мега-рыцаря",
        "мка",
        "mega knight",
    ],
    "Elite Barbarians": [
        "элитки",
        "элиток",
        "элитками",
        "эбары",
        "elite barbarians",
    ],
    "Royal Giant": [
        "коргиг",
        "кор гиг",
        "королевский гигант",
        "royal giant",
    ],
    "Electro Wizard": [
        "электро маг",
        "электромиг",
        "ewiz",
        "electro wizard",
    ],
    "Inferno Dragon": [
        "инферно дракон",
        "инф дракон",
        "inferno dragon",
    ],
    "Inferno Tower": [
        "инферно башня",
        "инфернка",
        "inferno tower",
    ],
    "Hog Rider": [
        "хог райдер",
        "кабан",
        "кабана",
        "кабаном",
        "hog rider",
    ],
    "Goblin Barrel": [
        "гоблин бочка",
        "гоб бочка",
        "бочка гоблинов",
        "goblin barrel",
    ],
    "Skeleton Barrel": [
        "скелетная бочка",
        "скелетной бочки",
        "скелетную бочку",
        "скелетной бочкой",
        "скелет бочка",
        "скел бочка",
        "скел-бочка",
        "skeleton barrel",
    ],
    "The Log": [
        "бревно",
        "логи",
        "лог",
        "the log",
    ],
    "X-Bow": [
        "иксбоу",
        "икс боу",
        "арбалет",
        "xbow",
        "x-bow",
    ],
    "Lava Hound": [
        "лавахаунд",
        "лава хаунд",
        "лавалун",
        "lava hound",
        "lavaloon",
    ],
    "Balloon": [
        "шарик",
        "шарика",
        "шариком",
        "balloon",
    ],
    "P.E.K.K.A": [
        "пека",
        "пёкка",
        "pekka",
    ],
    "Mini P.E.K.K.A": [
        "минипека",
        "мини пека",
        "минипёкка",
        "mini pekka",
    ],
    "Three Musketeers": [
        "три мушкетёра",
        "три мушкета",
        "three musketeers",
    ],
    "Dark Prince": [
        "тёмный принц",
        "темный принц",
        "dark prince",
    ],
    "Archer Queen": [
        "королева лучниц",
        "лучница королева",
        "archer queen",
    ],
    "Golden Knight": [
        "золотой рыцарь",
        "голден найт",
        "golden knight",
    ],
    "Mighty Miner": [
        "шустрый шахтёр",
        "шустрый шахтер",
        "mighty miner",
    ],
    "Little Prince": [
        "маленький принц",
        "малый принц",
        "little prince",
    ],
    "Electro Giant": [
        "электро гигант",
        "egiant",
        "electro giant",
    ],
    "Goblin Giant": [
        "гоблин гигант",
        "гоб гиг",
        "goblin giant",
    ],
    "Royal Hogs": [
        "королевские кабаны",
        "кабаны",
        "кабанов",
        "кабанами",
        "royal hogs",
    ],
    "Wall Breakers": [
        "стенобои",
        "wall breakers",
    ],
    "Firecracker": [
        "ракетчица",
        "firecracker",
    ],
    "Magic Archer": [
        "магический лучник",
        "маг лучник",
        "magic archer",
    ],
    "Battle Ram": [
        "баттл рэм",
        "боевой таран",
        "battle ram",
    ],
    "Ram Rider": [
        "рем райдер",
        "рам райдер",
        "ram rider",
    ],
    "Graveyard": [
        "кладбище",
        "graveyard",
    ],
    "Sparky": [
        "спарки",
        "спарка",
        "sparky",
    ],
    "Lumberjack": [
        "дровосек",
        "lumberjack",
    ],
    "Executioner": [
        "палач",
        "executioner",
    ],
    "Bowler": [
        "боулер",
        "шаровик",
        "bowler",
    ],
    "Fisherman": [
        "рыбак",
        "fisherman",
    ],
    "Hunter": [
        "охотник",
        "хантер",
        "hunter",
    ],
    "Bandit": [
        "бандитка",
        "бандит",
        "bandit",
    ],
    "Royal Ghost": [
        "призрак",
        "роял гоуст",
        "royal ghost",
    ],
    "Baby Dragon": [
        "дракончик",
        "бэби дракон",
        "baby dragon",
    ],
    "Electro Dragon": [
        "электро дракон",
        "эл дракон",
        "edrag",
        "electro dragon",
    ],
    "Skeleton Dragons": [
        "скелет драконы",
        "скелет-драконы",
        "скел драконы",
        "skeleton dragons",
    ],
    "Flying Machine": [
        "летучка",
        "flying machine",
    ],
    "Cannon Cart": [
        "повозка",
        "пушечная повозка",
        "cannon cart",
    ],
    "Elixir Collector": [
        "сборщик",
        "памп",
        "pump",
        "elixir collector",
    ],
    "Goblin Drill": [
        "бур",
        "гоблин бур",
        "goblin drill",
    ],
    "Goblin Cage": [
        "клетка",
        "гоблин клетка",
        "goblin cage",
    ],
    "Heal Spirit": [
        "хил дух",
        "хилдух",
        "heal spirit",
    ],
    "Electro Spirit": [
        "электро дух",
        "электродух",
        "electro spirit",
    ],
    "Ice Spirit": [
        "ледяной дух",
        "айс дух",
        "ice spirit",
    ],
    "Fire Spirit": [
        "огненный дух",
        "фаер дух",
        "fire spirit",
    ],
    "Earthquake": [
        "землетрясение",
        "землетряс",
        "eq",
        "earthquake",
    ],
    "Royal Delivery": [
        "почта",
        "роял деливери",
        "royal delivery",
    ],
    "Barbarian Barrel": [
        "варварская бочка",
        "барб бочка",
        "barbarian barrel",
    ],
    "Giant Snowball": [
        "снежок",
        "снежный ком",
        "snowball",
    ],
    "Minion Horde": [
        "орда",
        "орда миньонов",
        "minion horde",
    ],
    "Mega Minion": [
        "мегамуха",
        "мега муха",
        "mega minion",
    ],
    "Boss Bandit": [
        "главная бандитка",
        "босс бандитка",
        "boss bandit",
    ],
}

# Если в тексте маркер составной карты — не оставлять «базовую» (Golem vs Elixir Golem).
_BASE_SHADOWS: list[tuple[str, str, tuple[str, ...]]] = [
    ("Elixir Golem", "Golem", ("эликсир", "элик-голем", "элик голем", "elixir")),
    ("Ice Golem", "Golem", ("терпил", "ледян", "айс голем", "ice golem")),
    ("Night Witch", "Witch", ("ночн", "ночь-ведьм", "night witch")),
    ("Mother Witch", "Witch", ("бабул", "mother witch")),
    ("Mini P.E.K.K.A", "P.E.K.K.A", ("мини", "mini")),
    ("Skeleton Barrel", "Barbarian Barrel", ("скелет", "скел-боч", "скел боч", "skeleton barrel")),
    ("Skeleton Barrel", "Goblin Barrel", ("скелет", "скел-боч", "скел боч", "skeleton barrel")),
]


def _ru_adj_forms(adj: str) -> list[str]:
    """Падежи прилагательных на -ый/-ий/-ой (эликсирный → эликсирным)."""
    a = (adj or "").strip().lower().replace("ё", "е")
    if len(a) < 4:
        return [a] if a else []
    forms = {a}
    if a.endswith(("ый", "ий")):
        stem = a[:-2]
        forms.update(
            {
                stem + "ый",
                stem + "ий",
                stem + "ого",
                stem + "ему",
                stem + "ому",
                stem + "ым",
                stem + "им",
                stem + "ом",
                stem + "ем",
                stem + "ое",
                stem + "ее",
                stem + "ая",
                stem + "ой",
                stem + "ую",
                stem + "ою",
            }
        )
    elif a.endswith("ая") and len(a) > 4:
        stem = a[:-2]
        forms.update(
            {
                stem + "ая",
                stem + "ой",
                stem + "ую",
                stem + "ою",
                stem + "ое",
                stem + "ого",
                stem + "ому",
                stem + "ым",
                stem + "ом",
            }
        )
    elif a.endswith("яя") and len(a) > 4:
        stem = a[:-2]
        forms.update(
            {
                stem + "яя",
                stem + "ей",
                stem + "юю",
                stem + "ее",
            }
        )
    return [f for f in forms if f]


def _phrase_case_forms(phrase: str) -> list[str]:
    """Склонение словосочетаний / дефисных имён карт."""
    p = (phrase or "").strip().lower().replace("ё", "е")
    if not p:
        return []
    if " " not in p and "-" in p:
        left, right = p.rsplit("-", 1)
        return [f"{left}-{f}" for f in _ru_case_forms(right)]
    parts = p.split()
    if len(parts) == 1:
        return _ru_case_forms(p)
    if len(parts) == 2:
        adj, noun = parts
        out: set[str] = set()
        adj_forms = (
            _ru_adj_forms(adj)
            if adj.endswith(("ый", "ий", "ой", "ая", "яя"))
            else [adj]
        )
        noun_forms = _ru_case_forms(noun)
        for af in adj_forms:
            for nf in noun_forms:
                out.add(f"{af} {nf}")
        for nf in noun_forms:
            out.add(f"{adj} {nf}")
        return list(out)
    head, last = " ".join(parts[:-1]), parts[-1]
    return [f"{head} {f}" for f in _ru_case_forms(last)]


def _ru_case_forms(nominative: str) -> list[str]:
    """Простые падежные формы для однословных RU-названий карт."""
    n = (nominative or "").strip().lower().replace("ё", "е")
    if len(n) < 3:
        return [n] if n else []
    forms = {n}
    if n.endswith("а") and len(n) > 3:
        stem = n[:-1]
        forms.update(
            {
                stem + "а",
                stem + "ы",
                stem + "е",
                stem + "у",
                stem + "ой",
                stem + "ою",
                stem + "ам",
                stem + "ами",
                stem + "ах",
            }
        )
    elif n.endswith("я") and len(n) > 3:
        stem = n[:-1]
        forms.update(
            {
                stem + "я",
                stem + "и",
                stem + "е",
                stem + "ю",
                stem + "ей",
                stem + "ею",
                stem + "ям",
                stem + "ями",
                stem + "ях",
            }
        )
    elif n.endswith(("й", "ь")) and len(n) > 3:
        stem = n[:-1]
        forms.update(
            {
                n,
                stem + "я",
                stem + "ю",
                stem + "ем",
                stem + "е",
                stem + "и",
                stem + "ями",
                stem + "ях",
            }
        )
    elif n[-1] not in "аеёиоуыэюяьъ" and len(n) >= 3:
        # Муж. род на согласную: хог → хогом / хога / …
        forms.update(
            {
                n,
                n + "а",
                n + "у",
                n + "ом",
                n + "е",
                n + "ы",
                n + "ов",
                n + "ами",
                n + "ах",
            }
        )
    return [f for f in forms if f]


def _prefer_specific_cards(found: list[str], low: str) -> list[str]:
    """Golem не должен побеждать Elixir Golem при маркере «эликсир…»."""
    out = list(found)
    for longer, shorter, hints in _BASE_SHADOWS:
        if longer in out and shorter in out:
            out.remove(shorter)
            continue
        if shorter in out and longer not in out and any(h in low for h in hints):
            out = [longer if c == shorter else c for c in out]
    # EN: «Elixir Golem» + «Golem» → оставить составную
    for longer in list(out):
        for shorter in list(out):
            if longer != shorter and longer.endswith(" " + shorter) and shorter in out:
                out.remove(shorter)
    # стабильный порядок без дублей
    dedup: list[str] = []
    for c in out:
        if c not in dedup:
            dedup.append(c)
    return dedup


# Глаголы / обороты сборки колоды (разговорные + формальные).
_BUILD_VERBS = (
    "собери",
    "собрать",
    "соберем",
    "соберём",
    "составь",
    "составить",
    "составим",
    "создай",
    "создать",
    "создадим",
    "сделай",
    "сделать",
    "сделаем",
    "построй",
    "построить",
    "подбери",
    "подобрать",
    "подберем",
    "придумай",
    "придумать",
    "придумаем",
    "накидай",
    "накидаем",
)
_BUILD_SOFT = (
    "хочу",
    "дай",
    "давай",
    "можешь",
    "помоги",
    "нужна",
    "нужно",
    "надо",
    "хотелось",
    "интересно",
    "можно",
    "а можно",
)
_BUILD_DECK_MARK = ("колод", "дек")  # колоду / колода / деку / дека …


def _is_build_deck_request(low: str) -> bool:
    """Семантика «собери/сделай/хочу деку …», без угадывания по одной карте."""
    if any(
        k in low
        for k in (
            "конструктор",
            "хочу играть через",
            "играть через",
            "колоду через",
            "деку через",
            "колода через",
            "дека через",
            "вокруг",
            "под неё",
            "под нее",
            "под неё подобрать",
            "под нее подобрать",
            "остальное под",
        )
    ):
        # «вокруг / через / под неё» без слова колода — только если есть карта или soft+deck
        if any(m in low for m in _BUILD_DECK_MARK) or "вокруг" in low or "через" in low:
            return True
        if "под не" in low and any(s in low for s in _BUILD_SOFT + _BUILD_VERBS):
            return True

    has_deck = any(m in low for m in _BUILD_DECK_MARK)
    has_verb = any(v in low for v in _BUILD_VERBS)
    has_soft = any(s in low for s in _BUILD_SOFT)

    if has_verb and has_deck:
        return True
    # «Хочу колоду с ведьмой» / «Давай деку через хога»
    if has_soft and has_deck:
        return True
    return False


def _is_build_deck_with_cards(low: str, extracted: list[str]) -> bool:
    """«Давай соберём что-нибудь с ведьмой» — глагол сборки + карта, без слова «колода»."""
    if not extracted:
        return False
    if not any(v in low for v in _BUILD_VERBS + _BUILD_SOFT):
        return False
    if any(
        k in low
        for k in (
            "разбер",
            "улучш",
            "замен",
            "матчап",
            "против",
            "бой",
            "что делает",
            "что за карта",
            "чем контр",
        )
    ):
        return False
    return True


_CR_ACTION_MARKERS = (
    "колод",
    "дек",
    "матчап",
    "замен",
    "помен",
    "вместо",
    "улучш",
    "разбер",
    "собери",
    "сделай",
    "создай",
    "подбери",
    "придумай",
    "против",
    "контр",
    "винрейт",
    "мета",
    "что такое",
    "что делает",
    "что значит",
    "что за карта",
    "последн",
    "прошл",
    "мой бой",
    "темп",
    "cycle",
)


def _is_stats_or_meta_request(low: str) -> bool:
    text = (low or "").strip()
    return any(
        k in text
        for k in (
            "винрейт",
            "winrate",
            "что в мете",
            "что по мете",
            "текущая мета",
            "мета сейчас",
        )
    )


def _is_chat_request(low: str) -> bool:
    """Small talk / persona — без игровых backend-фактов.

    Если в том же сообщении есть CR-действие («привет, что вместо Ведьмы?»),
    это не conversational: CR intent должен победить раньше.
    """
    text = (low or "").strip()
    if not text or len(text) > 180:
        return False
    if any(k in text for k in _CR_ACTION_MARKERS):
        return False

    compact = "".join(ch for ch in text if ch.isalnum() or ch.isspace()).strip()
    exact = {
        "привет",
        "здравствуй",
        "здравствуйте",
        "хай",
        "hello",
        "hi",
        "hey",
        "йо",
        "здарова",
        "здорово",
        "доброе утро",
        "добрый день",
        "добрый вечер",
        "как дела",
        "как сам",
        "как ты",
        "что делаешь",
        "чем занят",
        "ты тут",
        "здесь",
        "ау",
        "что умеешь",
        "что ты умеешь",
        "что можешь",
        "чем поможешь",
        "помощь",
        "help",
        "спасибо",
        "благодарю",
        "спс",
        "понятно",
        "ясно",
        "ок",
        "окей",
        "ладно",
        "ага",
        "угу",
        "ахах",
        "ахаха",
        "лол",
        "кек",
        "красавчик",
        "молодец",
        "как думаешь",
        "мне скучно",
        "скучно",
        "посоветуй чтонибудь",
        "посоветуй что нибудь",
        "что сегодня поделать",
        "что поделать",
        "расскажи про себя",
        "кто ты",
        "кто ты вообще",
        "а ты вообще кто",
        "ты кто",
        "ты хороший тренер",
        "ты крутой",
        "ты здесь",
    }
    if compact in exact or text.rstrip("!.?…,:)(").strip() in exact:
        return True

    chat_markers = (
        "как дела",
        "как сам",
        "как ты",
        "что делаешь",
        "чем занят",
        "ты тут",
        "что умеешь",
        "что ты умеешь",
        "хороший тренер",
        "ты тренер",
        "расскажи про себя",
        "расскажи о себе",
        "а ты вообще кто",
        "кто ты такой",
        "ты кто такой",
        "хорошо разбираешься",
        "ты разбираешься",
        "знаешь clash",
        "мне скучно",
        "посоветуй что",
        "просто поболтать",
        "просто поговорим",
        "давай поболтаем",
        "рада тебя",
        "рад тебя",
    )
    if any(m in text for m in chat_markers):
        return True

    prefixes = (
        "привет",
        "здравств",
        "хай",
        "hello",
        "hi",
        "йо",
        "здаров",
        "спасибо",
        "благодар",
        "понятн",
        "ясно",
        "ахах",
        "лол",
        "красав",
        "молодец",
    )
    if len(text.split()) <= 6 and any(text.startswith(p) for p in prefixes):
        return True
    return False


def _is_how_to_play_request(low: str) -> bool:
    """«Как ею играть?» / «как этой колодой играть» — не clarify."""
    if "против" in low:
        return False
    if any(
        k in low
        for k in (
            "как ей играть",
            "как им играть",
            "как ею играть",
            "как этой колодой",
            "как этой колоде",
            "как этой декой",
            "как играть этой",
            "как играть колодой",
            "как играть декой",
            "как ей играть",
        )
    ):
        return True
    if "как играть" in low and any(
        k in low for k in ("ею", "ей", "им", "этой", "этим", "колод", "дек")
    ):
        return True
    # короткое «как ею играть?»
    if "игра" in low and any(k in low for k in ("как ей", "как им", "как ею")):
        return True
    return False


_ALIAS_INDEX = _build_alias_index()


# Механики Knowledge Base — резолв через единый словарь алиасов
def _match_mechanic(low: str) -> str | None:
    return resolve_mechanic_key(low)


def extract_cards_from_text(text: str, *, limit: int = 16) -> list[str]:
    """Жадный матч по самым длинным алиасам без пересечений."""
    low = (text or "").lower().replace("ё", "е")
    found: list[str] = []
    occupied = [False] * len(low)
    for alias, en in _ALIAS_INDEX:
        if not alias:
            continue
        alias_n = alias.replace("ё", "е")
        start = 0
        while True:
            idx = low.find(alias_n, start)
            if idx < 0:
                break
            end = idx + len(alias_n)
            before_ok = idx == 0 or not low[idx - 1].isalnum()
            after_ok = end >= len(low) or not low[end].isalnum()
            if before_ok and after_ok and not any(occupied[idx:end]):
                if en not in found:
                    found.append(en)
                for i in range(idx, end):
                    occupied[i] = True
                if len(found) >= limit:
                    return _prefer_specific_cards(found, low)
            start = idx + 1
    return _prefer_specific_cards(found, low)


def detect_intent(message: str, *, context_cards: list[str] | None = None) -> DetectedIntent:
    """Rule-based intent. Если сигнал слабый — clarify, не угадывать."""
    raw = (message or "").strip()
    low = raw.lower().replace("ё", "е")
    extracted = extract_cards_from_text(raw)
    ctx = [c for c in (context_cards or []) if c]

    def _out(
        intent: str,
        *,
        cards: list[str] | None = None,
        opponent_cards: list[str] | None = None,
        card_query: str | None = None,
        mechanic_query: str | None = None,
        coach_topic: str | None = None,
    ) -> DetectedIntent:
        return DetectedIntent(
            intent=intent,
            cards=cards if cards is not None else extracted,
            opponent_cards=opponent_cards or [],
            card_query=card_query,
            mechanic_query=mechanic_query,
            coach_topic=coach_topic,
            raw=raw,
        )

    if not raw:
        return _out(INTENT_CLARIFY, cards=ctx[:8])

    if is_unsupported_request(raw):
        return _out(INTENT_UNSUPPORTED, cards=extracted or ctx[:8])

    # --- Battle Analyzer ---
    if any(
        k in low
        for k in (
            "последн",
            "прошл",
            "почему проигр",
            "разбор боя",
            "разбери бой",
            "разбери мой бой",
            "этот бой",
            "мой бой",
        )
    ):
        return _out(INTENT_LAST_BATTLE)

    # --- Knowledge Base (механики) — до «против», чтобы не путать ---
    mechanic = _match_mechanic(low)
    if mechanic and any(
        k in low
        for k in (
            "что такое",
            "что значит",
            "объясни",
            "означает",
            "что есть",
            "what is",
            "mechanic",
            "термин",
        )
    ):
        return _out(INTENT_EXPLAIN_MECHANIC, mechanic_query=mechanic)
    # Короткий запрос одним термином: «Cycle», «Overcommit», «Tempo»
    if mechanic and len(low.split()) <= 4:
        if not any(
            k in low
            for k in ("собери", "разбер", "улучш", "матчап", "против", "апнуть", "колод", "дек", "бой", "сделай", "создай")
        ):
            return _out(INTENT_EXPLAIN_MECHANIC, mechanic_query=mechanic)

    # --- Game Coach ---
    if _is_how_to_play_request(low):
        return _out(
            INTENT_GAME_COACH,
            cards=extracted or ctx[:8],
            coach_topic="how_to_play",
        )

    if any(
        k in low
        for k in (
            "как апнуть",
            "апнуть куб",
            "набрать куб",
            "поднять куб",
            "как поднять троф",
            "как фармить",
            "как играть против",
            "как против",
            "чем бить",
            "как контрить",
            "чем контрить",
        )
    ):
        topic = "climb" if any(k in low for k in ("куб", "троф", "апнуть", "фарм")) else "vs_advice"
        if topic == "vs_advice" and not any(k in low for k in ("против", "контр", "бить")):
            topic = "general"
        return _out(INTENT_GAME_COACH, cards=extracted or ctx[:8], coach_topic=topic)

    # «посоветуй / что делать» — CR только если есть игровая задача, иначе chat.
    if any(k in low for k in ("посоветуй", "дай совет", "что делать")):
        has_cr = bool(extracted) or any(
            k in low
            for k in (
                "колод",
                "дек",
                "куб",
                "троф",
                "против",
                "контр",
                "слил",
                "проигр",
                "бой",
                "карт",
            )
        )
        if has_cr:
            topic = "climb" if any(k in low for k in ("куб", "троф", "апнуть", "фарм")) else "general"
            return _out(INTENT_GAME_COACH, cards=extracted or ctx[:8], coach_topic=topic)

    if extracted and any(
        k in low
        for k in (
            "проигрыв",
            "постоянно слив",
            "сливает",
            "не работает",
            "считается слаб",
            "почему слаб",
            "плохо играет",
            "работают с",
            "идет с",
            "идёт с",
            "в связке",
            "синерг",
            "комбо",
        )
    ):
        return _out(INTENT_GAME_COACH, cards=extracted or ctx[:8], coach_topic="general")

    # --- Matchup Analyzer ---
    if any(k in low for k in ("матчап", "разбери матчап", "против колоды", " vs ", " vs")):
        user_cards = ctx[:8] if len(ctx) >= 8 else extracted[:8]
        opp = (
            extracted[8:16]
            if len(extracted) >= 16
            else (extracted if len(ctx) >= 8 else extracted[4:12])
        )
        return _out(INTENT_MATCHUP, cards=user_cards, opponent_cards=opp)

    # --- Builder (формальные + разговорные формулировки) ---
    if _is_build_deck_request(low) or _is_build_deck_with_cards(low, extracted):
        core = extracted[:4] or ctx[:4]
        return _out(INTENT_BUILD_DECK, cards=core)

    # --- Recommendation ---
    if any(
        k in low
        for k in (
            "улучш",
            "замен",
            "что помен",
            "что смен",
            "фикс колоды",
            "а что замен",
            "что лучше замен",
            "что тут замен",
            "а что тут замен",
            "что тут лучше",
            "что вместо",
            "а что вместо",
            "поставить вместо",
            "что поставить",
            "сюда лучше",
            "какую карту",
            "чем заменить",
            "медленн",
            "тормозн",
            "тяжелая",
            "тяжёлая",
            "тяжелова",
        )
    ) and (
        any(m in low for m in _BUILD_DECK_MARK)
        or "замен" in low
        or "помен" in low
        or "вместо" in low
        or "улучш" in low
        or "фикс" in low
        or "поставить" in low
        or "какую карту" in low
        or "сюда лучше" in low
    ):
        cards = extracted[:8] if len(extracted) >= 4 else (ctx[:8] if ctx else extracted)
        return _out(INTENT_IMPROVE_DECK, cards=cards)

    # --- Analyzer (явный разбор колоды) ---
    if any(
        k in low
        for k in (
            "разбери колоду",
            "разбор колоды",
            "анализ колоды",
            "проверь колоду",
            "оцени колоду",
            "паспорт колоды",
            "паспорт",
            "как тебе колода",
            "как тебе дека",
            "что скажешь про колоду",
            "что скажешь про деку",
        )
    ) or (
        "разбер" in low and "колод" in low
    ) or (
        "разбер" in low and "дек" in low
    ):
        cards = extracted[:8] if len(extracted) >= 4 else (ctx[:8] if ctx else extracted)
        return _out(INTENT_ANALYZE_DECK, cards=cards)

    # --- Card Database ---
    if any(
        k in low
        for k in (
            "что за карта",
            "что делает",
            "роль карты",
            "про карту",
            "объясни карту",
            "расскажи про карту",
        )
    ) or (len(extracted) == 1 and any(k in low for k in ("карта", "карт"))):
        q = extracted[0] if extracted else None
        return _out(INTENT_CARD_INFO, cards=extracted, card_query=q)

    if len(extracted) == 1 and any(
        k in low for k in ("расскажи про", "почему", "как работает", "стоит ли")
    ):
        return _out(INTENT_CARD_INFO, cards=extracted, card_query=extracted[0])

    # Голые «что такое …» без известной механики — Knowledge Base miss → clarify
    if any(k in low for k in ("что такое", "что значит", "объясни механику")):
        return _out(INTENT_EXPLAIN_MECHANIC, mechanic_query=None)

    if _is_stats_or_meta_request(low):
        return _out(INTENT_CLARIFY, cards=extracted or ctx[:8])

    # Список карт без глагола — не угадываем Analyzer/Builder.
    if extracted and not _is_chat_request(low):
        return _out(INTENT_CLARIFY, cards=extracted or ctx[:8])

    # MODE A: ordinary talk → Qwen, не clarify-template.
    return _out(INTENT_CHAT, cards=[])

from pydantic import BaseModel


class SubscriptionInfo(BaseModel):
    active: bool
    expires_at: str | None
    trial_used: bool


class ProfileResponse(BaseModel):
    player_tag: str | None
    player_name: str | None
    trophies: int | None
    exp_level: int | None
    arena_name: str | None
    arena_icon: str | None = None
    avatar_url: str | None = None
    favorite_card: str | None = None
    favorite_card_icon: str | None = None
    skill_rating: int | None = None
    winrate: float | None = None
    last_rating_change: int | None = None
    max_trophies: int | None = None
    clan_name: str | None = None
    subscription: SubscriptionInfo


class BattleSummary(BaseModel):
    index: int
    opponent_name: str
    opponent_tag: str = ""
    opponent_trophies: int = 0
    won: bool
    trophy_change: int
    matchup_score: float | None = None
    duration: int = 0
    avg_elixir: float = 0.0
    user_deck: list[str] = []
    opponent_deck: list[str] = []
    top_reason: str | None = None
    timestamp: str = ""


class BattleListResponse(BaseModel):
    battles: list[BattleSummary]
    cached_total: int | None = None
    cached_winrate: float | None = None


class DeckStatsResponse(BaseModel):
    avg_elixir: float
    win_conditions: list[str]
    spells: list[str]


class BattleDetailResponse(BaseModel):
    index: int
    won: bool
    opponent_name: str
    trophy_change: int
    matchup_score: float
    user_deck: list[str]
    opponent_deck: list[str]
    user_stats: DeckStatsResponse
    opponent_stats: DeckStatsResponse
    reasons: list[str]
    opponent_threats: list[str]


class WinrateEntry(BaseModel):
    cards: list[str]
    wins: int
    losses: int
    total: int
    winrate: float


class OpponentEntry(BaseModel):
    index: int
    name: str
    deck: list[str]
    threats: list[str]
    avg_elixir: float
    won_against: bool


class CounterDeckResponse(BaseModel):
    opponent_name: str
    opponent_deck: list[str]
    counter_deck: list[str]
    threats: list[str]
    preferred_cards: list[str]


class CustomizeResponse(BaseModel):
    original: list[str]
    customized: list[str]
    issues: list[str]
    avg_elixir: float


class SynergyResponse(BaseModel):
    core: list[str]
    deck: list[str]
    synergies: dict[str, list[str]]
    avg_elixir: float


class StatsDeckEntry(BaseModel):
    cards: list[str]
    total: int
    winrate: float


class StatsResponse(BaseModel):
    player_tag: str
    total: int
    wins: int
    losses: int
    winrate: float
    top_decks: list[StatsDeckEntry]
    top_cards: list[dict]
    win_streak: int
    loss_streak: int


class StatsOverviewResponse(BaseModel):
    total_battles: int
    wins: int
    losses: int
    draws: int = 0
    winrate: float
    avg_elixir: float = 0.0
    max_trophies: int = 0
    avg_time: float = 0.0
    winrate_by_day: list[dict] = []
    winrate_by_hour: list[dict] = []
    best_cards: list[dict] = []
    most_used_cards: list[dict] = []
    archetypes: list[dict] = []
    last_results: list[dict] = []
    activity_heatmap: list[list[int]] = []


class DeckCardInfo(BaseModel):
    id: str
    name: str
    icon: str = ""
    rarity: str = "common"
    cost: int = 0


class DeckEntry(BaseModel):
    id: int
    name: str = ""
    cards: list[DeckCardInfo]
    winrate: float
    total_games: int
    avg_elixir: float
    type: str = "rated"
    category: str = "mine"
    deck_link: str | None = None
    description: str = ""
    best_matchups: list = []
    worst_matchups: list = []


class DeckListResponse(BaseModel):
    decks: list[DeckEntry]


class SearchResult(BaseModel):
    player_tag: str
    player_name: str
    trophies: int
    arena: str


class CardCatalogEntry(BaseModel):
    name: str
    name_ru: str
    name_short: str = ""
    icon: str = ""
    id: int | None = None
    elixir: int | None = None


class CardCatalogResponse(BaseModel):
    cards: list[CardCatalogEntry]


class FavoriteDeckEntry(BaseModel):
    cards: list[str]
    deck_link: str | None = None


class FavoritesResponse(BaseModel):
    cards: list[dict] = []
    decks: list[list[str]] = []
    entries: list[FavoriteDeckEntry] = []


class SettingsResponse(BaseModel):
    theme: str = "dark"
    language: str = "ru"
    notifications: bool = True
    telegram_notifications: bool = True


class HomeResponse(BaseModel):
    profile: ProfileResponse
    battles: list[BattleSummary] = []
    stats: StatsOverviewResponse | None = None


class LastBattleSummary(BaseModel):
    won: bool
    opponent_name: str
    trophy_change: int
    matchup_score: float
    top_reason: str | None


class RecommendationsResponse(BaseModel):
    current_deck: list[str] = []
    avg_elixir: float = 0.0
    issues: list[str] = []
    customized_deck: list[str] = []
    synergy_core: list[str] = []
    synergy_deck: list[str] = []
    last_battle: LastBattleSummary | None = None


class RandomDeckResponse(BaseModel):
    cards: list[str]
    card_infos: list[DeckCardInfo]
    avg_elixir: float
    deck_link: str | None = None


class BattleInsightEntry(BaseModel):
    battle_index: int
    won: bool
    opponent_name: str
    summary: str
    matchup_score: float = 0.0
    details: list[str] = []
    timestamp: str = ""


class InsightsResponse(BaseModel):
    insights: list[BattleInsightEntry]
    patterns: list[str] = []
    sample_size: int = 0
    wins: int = 0
    losses: int = 0


class SyncResponse(BaseModel):
    ok: bool = True
    battles_loaded: int = 0

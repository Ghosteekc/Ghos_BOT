from pydantic import BaseModel


class SubscriptionInfo(BaseModel):
    active: bool
    expires_at: str | None
    trial_used: bool


class CardLevelCount(BaseModel):
    level: int
    count: int


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
    daily_trophy_change: int | None = None
    max_trophies: int | None = None
    clan_name: str | None = None
    total_wins: int | None = None
    three_crown_wins: int | None = None
    collection_level: int | None = None
    cards_by_level: list[CardLevelCount] = []
    subscription: SubscriptionInfo


class CollectionCardEntry(BaseModel):
    name: str
    name_ru: str
    owned: bool
    level: int | None = None
    max_level: int | None = None
    count: int = 0
    rarity: str = ""
    elixir: int | None = None
    evolution_level: int = 0
    max_evolution_level: int = 0
    display_mode: str = "base"
    icon: str = ""
    icon_base: str = ""
    icon_evo: str = ""
    icon_hero: str = ""


class CollectionMasteryEntry(BaseModel):
    card_name: str
    card_name_ru: str
    icon: str = ""
    icon_base: str = ""
    icon_evo: str = ""
    icon_hero: str = ""
    display_mode: str = "base"
    level: int
    max_level: int
    progress: int
    target: int | None = None
    progress_percent: float = 0.0
    next_hint: str = ""


class PlayerCollectionResponse(BaseModel):
    cards: list[CollectionCardEntry]
    cards_owned: int
    cards_total: int
    masteries: list[CollectionMasteryEntry]
    collection_level: int = 0
    evolution_count: int = 0
    hero_count: int = 0
    champion_count: int = 0
    legendary_count: int = 0
    epic_count: int = 0
    rare_count: int = 0
    common_count: int = 0
    cards_by_level: list[CardLevelCount] = []


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
    played_at: str = ""


class BattleListResponse(BaseModel):
    battles: list[BattleSummary]
    cached_total: int | None = None
    cached_winrate: float | None = None


class DeckStatsResponse(BaseModel):
    avg_elixir: float
    win_conditions: list[str]
    spells: list[str]


class KeyCardEntry(BaseModel):
    name: str
    name_ru: str
    note: str = ""


class BattleDetailResponse(BaseModel):
    index: int
    won: bool
    opponent_name: str
    trophy_change: int
    matchup_score: float
    duration: int = 0
    played_at: str = ""
    crown_score: str = ""
    outcome_summary: str = ""
    user_deck: list[str]
    opponent_deck: list[str]
    user_stats: DeckStatsResponse
    opponent_stats: DeckStatsResponse
    reasons: list[str]
    opponent_threats: list[str]
    user_key_cards: list[KeyCardEntry] = []
    opponent_key_cards: list[KeyCardEntry] = []
    low_impact_cards: list[KeyCardEntry] = []


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
    deck_link: str | None = None


class SynergyResponse(BaseModel):
    core: list[str]
    deck: list[str]
    synergies: dict[str, list[str]]
    avg_elixir: float
    deck_link: str | None = None


class ConstructorSlotRequest(BaseModel):
    name: str
    slot: int


class ConstructorRequest(BaseModel):
    slots: list[ConstructorSlotRequest]


class ConstructorDeckEntry(BaseModel):
    id: int
    name: str = ""
    cards: list[DeckCardInfo]
    synergy_score: float = 0.0
    synergy_notes: list[str] = []
    avg_elixir: float = 0.0
    deck_link: str | None = None
    description: str = ""
    type: str = "constructor"
    category: str = "custom"
    archetype: str = ""
    confidence: float = 0.0


class ConstructorResponse(BaseModel):
    core: list[DeckCardInfo]
    decks: list[ConstructorDeckEntry]


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
    evolution_level: int = 0
    is_hero: bool = False
    slot: int = 0


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
    meta_updated_at: str | None = None
    meta_source: str | None = None


class TopPlayerEntry(BaseModel):
    rank: int
    player_tag: str
    player_name: str
    trophies: int = 0
    clan_name: str = ""
    winrate: float = 0.0
    total_games: int = 0
    avg_elixir: float = 0.0
    cards: list[DeckCardInfo] = []
    deck_link: str | None = None


class TopPlayersResponse(BaseModel):
    players: list[TopPlayerEntry]
    updated_at: str | None = None


class ArenaDecksResponse(BaseModel):
    arena_name: str
    arena_id: int | None = None
    trophies: int = 0
    decks: list[DeckEntry]
    source: str = "curated"
    updated_at: str | None = None


class DeckCompareRequest(BaseModel):
    reference_cards: list[str]


class DeckCompareCardNote(BaseModel):
    card: str
    card_ru: str = ""
    tone: str = "neutral"
    text: str = ""


class DeckCompareResponse(BaseModel):
    reference_name: str = ""
    user_deck: list[DeckCardInfo]
    reference_deck: list[DeckCardInfo]
    user_better: list[str]
    user_worse: list[str]
    reference_better: list[str]
    reference_worse: list[str]
    user_card_notes: list[DeckCompareCardNote] = []
    reference_card_notes: list[DeckCompareCardNote] = []
    matchup_score: float = 50.0
    opponent_matchup_score: float = 50.0
    user_synergy_score: float = 50.0
    reference_synergy_score: float = 50.0
    user_synergy_notes: list[str] = []
    reference_synergy_notes: list[str] = []


class DeckCardMatchup(BaseModel):
    card: str
    card_ru: str = ""
    winrate: float = 0.0
    games: int = 0
    reason: str = ""


class DeckImprovementSuggestion(BaseModel):
    category: str
    message: str
    suggested_cards: list[str] = []


class MineDeckStatsRequest(BaseModel):
    cards: list[str]


class MineDeckStatsResponse(BaseModel):
    name: str = ""
    cards: list[DeckCardInfo] = []
    wins: int = 0
    losses: int = 0
    total_games: int = 0
    winrate: float = 0.0
    avg_elixir: float = 0.0
    win_conditions: list[str] = []
    strong_against: list[DeckCardMatchup] = []
    weak_against: list[DeckCardMatchup] = []
    improvements: list[DeckImprovementSuggestion] = []
    balanced: bool = False
    sample_note: str = ""


class SearchResult(BaseModel):
    player_tag: str
    player_name: str
    trophies: int
    arena: str
    max_trophies: int | None = None
    clan_name: str | None = None
    exp_level: int | None = None


class CardCatalogEntry(BaseModel):
    name: str
    name_ru: str
    name_short: str = ""
    icon: str = ""
    id: int | None = None
    elixir: int | None = None
    max_evolution_level: int = 0
    has_hero: bool = False
    icon_evo: str = ""
    icon_hero: str = ""


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
    rofl: bool = False
    rofl_name: str | None = None
    rofl_tagline: str | None = None
    rofl_key: str | None = None


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

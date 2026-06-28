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
    subscription: SubscriptionInfo


class BattleSummary(BaseModel):
    index: int
    opponent_name: str
    won: bool
    trophy_change: int
    matchup_score: float | None = None


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

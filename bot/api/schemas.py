from typing import Literal

from pydantic import BaseModel, Field


class SubscriptionInfo(BaseModel):
    active: bool
    expires_at: str | None
    trial_used: bool


class CardLevelCount(BaseModel):
    level: int
    count: int


class LeagueInfo(BaseModel):
    unlocked: bool = False
    unlock_trophies: int = 13_000
    current_league_number: int | None = None
    current_league_name: str | None = None
    current_league_icon: str | None = None
    best_league_number: int | None = None
    best_league_name: str | None = None
    best_league_icon: str | None = None
    is_absolute_champion: bool = False
    absolute_trophies: int | None = None


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
    league: LeagueInfo | None = None
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
    has_evolution_unlocked: bool = False
    has_hero_unlocked: bool = False
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


class BattleLeagueBadge(BaseModel):
    league_number: int
    league_name: str
    league_icon: str | None = None
    starting_trophies: int | None = None


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
    user_deck_cards: list["DeckCardInfo"] = []
    opponent_deck_cards: list["DeckCardInfo"] = []
    top_reason: str | None = None
    timestamp: str = ""
    played_at: str = ""
    is_ranked: bool = False
    user_league: BattleLeagueBadge | None = None
    opponent_league: BattleLeagueBadge | None = None


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


class TacticalDangerCard(BaseModel):
    name: str
    name_ru: str = ""
    reason: str = ""


class TacticalMatchupResponse(BaseModel):
    early_game: list[str] = []
    mid_game: list[str] = []
    late_game: list[str] = []
    pressure_points: list[str] = []
    critical_interactions: list[str] = []
    danger_cards: list[TacticalDangerCard] = []
    best_openings: list[str] = []
    worst_mistakes: list[str] = []


class ElixirEfficiencyResponse(BaseModel):
    average_cost: float = 0.0
    effective_cycle: int = 0
    cheap_rotation: int = 0
    punish_speed: int = 0
    recovery_speed: int = 0
    double_elixir_power: int = 0
    overtime_strength: int = 0
    elixir_profile: str = "Medium Cycle"
    explanations: list[str] = []


class MatchDifficultyResponse(BaseModel):
    difficulty: int = 50
    rating: str = "Равный"
    reasons: list[str] = []
    factors: dict[str, int] = {}


class MatchPlanSaveCard(BaseModel):
    name: str
    name_ru: str = ""
    reason: str = ""


class MatchGamePlanPhasesResponse(BaseModel):
    phase_1: list[str] = []
    phase_2: list[str] = []
    phase_3: list[str] = []


class MatchPlanResponse(BaseModel):
    game_plan: MatchGamePlanPhasesResponse = MatchGamePlanPhasesResponse()
    avoid: list[str] = []
    save_cards: list[MatchPlanSaveCard] = []
    win_condition_window: str = ""


class CoachInsightResponse(BaseModel):
    title: str
    text: str
    evidence: list[str] = []
    confidence: str = "medium"  # high | medium | low | insufficient


class BattleCoachResponse(BaseModel):
    main_mistakes: list[CoachInsightResponse] = []
    best_moment: CoachInsightResponse | None = None
    turning_point: CoachInsightResponse | None = None
    outcome_decider: CoachInsightResponse | None = None
    danger_moment: CoachInsightResponse | None = None
    counterfactual: CoachInsightResponse | None = None
    data_notes: list[str] = []
    sufficient: bool = False


class BattleDetailResponse(BaseModel):
    index: int
    won: bool
    opponent_name: str
    opponent_tag: str = ""
    trophy_change: int
    matchup_score: float
    duration: int = 0
    played_at: str = ""
    crown_score: str = ""
    outcome_summary: str = ""
    user_deck: list[str]
    opponent_deck: list[str]
    user_deck_cards: list["DeckCardInfo"] = []
    opponent_deck_cards: list["DeckCardInfo"] = []
    user_stats: DeckStatsResponse
    opponent_stats: DeckStatsResponse
    reasons: list[str]
    opponent_threats: list[str]
    user_key_cards: list[KeyCardEntry] = []
    opponent_key_cards: list[KeyCardEntry] = []
    low_impact_cards: list[KeyCardEntry] = []
    tactical_matchup: TacticalMatchupResponse | None = None
    user_elixir: ElixirEfficiencyResponse | None = None
    opponent_elixir: ElixirEfficiencyResponse | None = None
    match_difficulty: MatchDifficultyResponse | None = None
    match_plan: MatchPlanResponse | None = None
    battle_coach: BattleCoachResponse | None = None
    is_ranked: bool = False
    user_league: BattleLeagueBadge | None = None
    opponent_league: BattleLeagueBadge | None = None


class OpponentEntry(BaseModel):
    index: int
    name: str
    deck: list[str]
    deck_cards: list["DeckCardInfo"] = []
    threats: list[str]
    avg_elixir: float
    won_against: bool


class CounterDeckResponse(BaseModel):
    opponent_name: str
    opponent_deck: list[str]
    counter_deck: list[str]
    threats: list[str]
    preferred_cards: list[str]


class CustomizeCardInfo(BaseModel):
    id: str
    name: str
    name_ru: str = ""
    icon: str = ""
    cost: int = 0
    level: int | None = None
    recommended_level: int = 0
    needs_upgrade: bool = False
    deficit: int = 0
    slot: int = 0


class CustomizeUpgradePriority(BaseModel):
    name: str
    name_ru: str = ""
    level: int | None = None
    recommended_level: int = 0
    deficit: int = 0
    icon: str = ""


class CustomizeResponse(BaseModel):
    original: list[str]
    customized: list[str]
    issues: list[str]
    avg_elixir: float
    deck_link: str | None = None
    recommended_level: int = 0
    original_cards: list[CustomizeCardInfo] = []
    customized_cards: list[CustomizeCardInfo] = []
    upgrade_priority: list[CustomizeUpgradePriority] = []
    level_alt_deck: list[str] = []
    level_alt_cards: list[CustomizeCardInfo] = []
    level_alt_needed: bool = False
    level_alt_avg_elixir: float = 0.0
    level_alt_deck_link: str | None = None
    synergy_needed: bool = False
    balanced: bool = False


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


class ScoreBreakdownEntry(BaseModel):
    synergy: float = 0.0
    offense: float = 0.0
    defense: float = 0.0
    anti_air: float = 0.0
    anti_swarm: float = 0.0
    spell_balance: float = 0.0
    elixir: float = 0.0
    archetype_fit: float = 0.0
    total: float = 0.0
    hard_issues: list[str] = []
    soft_issues: list[str] = []


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
    balanced: bool = True
    score_breakdown: ScoreBreakdownEntry | None = None
    improvements: list[dict] = []
    game_plan: dict | None = None
    recommendation: dict | None = None
    is_alternative: bool = False


class CoreConflictInfo(BaseModel):
    conflicting_card: str
    conflicting_card_ru: str = ""
    reason: str = ""
    baseline_score: float = 0.0
    alternative_score: float = 0.0
    quality_gain: float = 0.0
    message: str = ""
    drop_scores: dict[str, float] = {}


class ConstructorResponse(BaseModel):
    core: list[DeckCardInfo]
    decks: list[ConstructorDeckEntry]
    core_conflict: CoreConflictInfo | None = None
    alternative_deck: ConstructorDeckEntry | None = None


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
    level: int | None = None


class WinrateEntry(BaseModel):
    cards: list[str]
    deck_cards: list[DeckCardInfo] = []
    wins: int
    losses: int
    total: int
    winrate: float


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
    # Реальные уровни референсной колоды (топ/арена) передаются только для UI.
    # Старые deep links с одними именами карт остаются полностью совместимы.
    reference_levels: list[int | None] | None = None


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
    user_recommendation: dict | None = None
    reference_recommendation: dict | None = None


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


class DeckGamePlan(BaseModel):
    """План игры колоды (из RecommendationEngine)."""

    how_to_win: str = ""
    primary_threat: str = ""
    when_to_attack: str = ""
    key_cards: list[str] = []
    core_combinations: list[str] = []
    critical_weaknesses: list[str] = []


class DeckIntentModel(BaseModel):
    archetype: str = ""
    play_style: str = ""
    primary_win: str | None = None
    required_soft_checks: list[str] = []
    min_air_defense: int = 0
    require_building: bool = False
    min_cycle_cards: int = 0
    required_role_ids: list[str] = []
    attack_bias: float = 0.5


class BalanceIssuesModel(BaseModel):
    hard: list[str] = []
    soft: list[str] = []
    messages: list[str] = []


class CandidateRatingModel(BaseModel):
    card: str = ""
    strategy_fit: float = 0.0
    gameplan_fit: float = 0.0
    primary_win_support: float = 0.0
    secondary_combo_support: float = 0.0
    tempo_fit: float = 0.0
    deck_identity: float = 0.0
    existing_synergy: float = 0.0
    future_synergy: float = 0.0
    role_overlap: float = 0.0
    replacement_cost: float = 0.0
    total: float = 0.0


class ImprovementStepModel(BaseModel):
    category: str = ""
    message: str = ""
    drop: str | None = None
    pick: str | None = None
    suggested_cards: list[str] = []
    tier: str | None = None
    rating: CandidateRatingModel | None = None
    reason: str | None = None


class ImprovementPlanModel(BaseModel):
    needed: bool = False
    steps: list[ImprovementStepModel] = []
    improved_deck: list[str] = []
    locked: list[str] = []


class RejectedCandidateExplanationModel(BaseModel):
    card: str = ""
    reasons: list[str] = []


class PickExplanationModel(BaseModel):
    category: str = ""
    pick: str = ""
    drop: str | None = None
    reason: str = ""
    pros: list[str] = []
    rejected: list[RejectedCandidateExplanationModel] = []


class RecommendationSwapModel(BaseModel):
    drop: str | None = None
    pick: str = ""
    reason: str = ""


class DecisionExplanationModel(BaseModel):
    archetype: str = ""
    primary_win: str | None = None
    why_gaps: list[str] = []
    why_picks: list[str] = []
    rejected: list[str] = []
    pick_explanations: list[PickExplanationModel] = []
    swaps: list[RecommendationSwapModel] = []


class CandidateRankingModel(BaseModel):
    by_gap: dict[str, list[CandidateRatingModel]] = {}
    applied: list[CandidateRatingModel] = []


class RiskAssessmentModel(BaseModel):
    score: float = 0.0
    factors: list[str] = []
    open_gaps: list[str] = []


class DeckCoachingModel(BaseModel):
    strengths: list[str] = []
    play_style: str = ""
    key_combinations: list[str] = []
    usage_tips: list[str] = []
    card_choices: list[dict[str, object]] = []


class RecommendationResultModel(BaseModel):
    intent: DeckIntentModel
    game_plan: DeckGamePlan
    balance_issues: BalanceIssuesModel
    improvement_plan: ImprovementPlanModel
    decision_explanation: DecisionExplanationModel
    candidate_ranking: CandidateRankingModel
    risk_assessment: RiskAssessmentModel
    origin: str = "player"
    coaching: DeckCoachingModel | None = None


class RecommendDeckRequest(BaseModel):
    cards: list[str]
    apply_swaps: bool = False
    origin: str = "player"
    builder_score: float | None = None


class RecommendDeckResponse(BaseModel):
    recommendation: RecommendationResultModel
    improvements: list[DeckImprovementSuggestion] = []


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
    game_plan: DeckGamePlan | None = None
    recommendation: RecommendationResultModel | None = None


class SearchResult(BaseModel):
    player_tag: str
    player_name: str
    trophies: int
    arena: str
    max_trophies: int | None = None
    clan_name: str | None = None
    exp_level: int | None = None
    collection_level: int | None = None
    arena_icon: str | None = None
    winrate: float | None = None
    total_wins: int | None = None
    total_losses: int | None = None
    recent_winrate: float | None = None
    recent_games: int = 0
    favorite_card: str | None = None
    favorite_card_icon: str | None = None
    avatar_url: str | None = None
    cards: list[DeckCardInfo] = []
    avg_elixir: float = 0.0
    deck_link: str | None = None
    deck_winrate: float | None = None
    deck_games: int = 0
    league: LeagueInfo | None = None


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
    theme: Literal["dark", "light", "auto"] = "dark"
    language: Literal["ru", "en"] = "ru"
    notifications: bool = True
    telegram_notifications: bool = True
    haptic_enabled: bool = True
    haptic_intensity: Literal["weak", "standard", "strong"] = "standard"


class SettingsUpdateRequest(BaseModel):
    theme: Literal["dark", "light", "auto"] | None = None
    language: Literal["ru", "en"] | None = None
    notifications: bool | None = None
    telegram_notifications: bool | None = None
    haptic_enabled: bool | None = None
    haptic_intensity: Literal["weak", "standard", "strong"] | None = None

    model_config = {"extra": "forbid"}


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


class BattleHistoryClearResponse(BaseModel):
    ok: bool = True
    deleted_count: int = 0


class GhosteekAiReplayContext(BaseModel):
    status: str
    filename: str | None = None
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    confidence: float | None = None


class GhosteekAiContext(BaseModel):
    cards: list[str] | None = None
    opponent_cards: list[str] | None = None
    battle_index: int | None = None
    battle_time: str | None = None
    replay: GhosteekAiReplayContext | None = None


class GhosteekAiAskRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    context: GhosteekAiContext | None = None


class GhosteekAiAction(BaseModel):
    type: str = "navigate"
    path: str


class DeckCardResponse(BaseModel):
    """Структурированная колода для UI (не текст и не markdown)."""

    deck: list[str] = Field(default_factory=list)
    average_elixir: float = 0.0
    archetype: str = ""
    arena: str | None = None
    import_url: str = ""
    gameplan: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    evaluation: dict = Field(default_factory=dict)
    title: str | None = None


class BattleCardResponse(BaseModel):
    """Зарезервировано: structured battle card (пока не используется)."""

    pass


class AnalysisCardResponse(BaseModel):
    """Зарезервировано: structured analysis card (пока не используется)."""

    pass


class ReplayDetectionResponse(BaseModel):
    status: str
    confidence: float
    frames_analyzed: int
    observations: list[str] = Field(default_factory=list)


class ReplayTimelineItemResponse(BaseModel):
    timestamp_seconds: float
    frame_index: int
    observation_type: str
    confidence: float
    source: str = "heuristic"


class ReplayConfirmedCardResponse(BaseModel):
    card_id: str
    card_name: str
    confidence: float
    first_seen: float
    last_seen: float


class ReplayAmbiguousCardCandidateResponse(BaseModel):
    card_id: str
    card_name: str
    confidence: float


class ReplayAmbiguousCardResponse(BaseModel):
    candidates: list[ReplayAmbiguousCardCandidateResponse] = Field(default_factory=list)
    frame_index: int
    timestamp_seconds: float
    location: str = "unknown"
    source: str = "heuristic"


class ReplayEventEvidenceResponse(BaseModel):
    frame_indices: list[int] = Field(default_factory=list)
    observation_ids: list[str] = Field(default_factory=list)
    timestamps: list[float] = Field(default_factory=list)


class ReplayEventResponse(BaseModel):
    timestamp_seconds: float
    event_type: str
    player: str = "unknown"
    card_id: str | None = None
    confidence: float
    source: str = "heuristic"
    evidence_frame_indexes: list[int] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)
    evidence: ReplayEventEvidenceResponse = Field(default_factory=ReplayEventEvidenceResponse)


class ReplayUnknownIntervalResponse(BaseModel):
    from_: float = Field(alias="from")
    to: float
    status: str = "unknown"

    model_config = {"populate_by_name": True}


class ReplayBattlePhaseResponse(BaseModel):
    phase: str
    timestamp_seconds: float
    confidence: float


class ReplayBattleTimelineSummaryResponse(BaseModel):
    confirmed_event_count: int = 0
    confirmed_card_count: int = 0
    first_event: float | None = None
    last_event: float | None = None
    known_duration: float = 0.0
    unknown_intervals_count: int = 0


class ReplayBattleTimelineResponse(BaseModel):
    duration_seconds: float
    events: list[ReplayEventResponse] = Field(default_factory=list)
    confirmed_events: list[ReplayEventResponse] = Field(default_factory=list)
    unknown_intervals: list[ReplayUnknownIntervalResponse] = Field(default_factory=list)
    confidence: float = 0.0
    phases: list[ReplayBattlePhaseResponse] = Field(default_factory=list)
    summary: ReplayBattleTimelineSummaryResponse | None = None


class ReplayTacticalLimitationsResponse(BaseModel):
    what_we_know: list[str] = Field(default_factory=list)
    what_we_dont_know: list[str] = Field(default_factory=list)


class ReplayTacticalAnalysisResponse(BaseModel):
    summary: str = ""
    positive_actions: list[str] = Field(default_factory=list)
    possible_mistakes: list[str] = Field(default_factory=list)
    matchup_observations: list[str] = Field(default_factory=list)
    deck_observations: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    limitations: ReplayTacticalLimitationsResponse = Field(
        default_factory=ReplayTacticalLimitationsResponse
    )
    conclusions: list[dict] = Field(default_factory=list)


class ReplayMomentShotResponse(BaseModel):
    timestamp_seconds: float
    label: str
    kind: str = "confirmed"
    image_base64: str


class ReplayEvidenceFrameResponse(BaseModel):
    timestamp_seconds: float
    frame_index: int
    width: int | None = None
    height: int | None = None


class ReplayVisualMomentResponse(BaseModel):
    event_type: str
    timestamp_seconds: float
    card_name: str | None = None
    confidence: float
    evidence_frame: ReplayEvidenceFrameResponse
    evidence_id: str | None = None
    clip_id: str | None = None
    clip_available: bool = False
    preview_base64: str | None = None
    source: str = "vision"


class ReplayFactsResponse(BaseModel):
    source: str = "replay_analysis"
    replay_status: str
    confidence: float
    duration_seconds: float
    frames_analyzed: int
    timeline: list[ReplayTimelineItemResponse] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    confirmed_cards: list[ReplayConfirmedCardResponse] = Field(default_factory=list)
    ambiguous_cards: list[ReplayAmbiguousCardResponse] = Field(default_factory=list)
    events: list[ReplayEventResponse] = Field(default_factory=list)
    confirmed_events: list[ReplayEventResponse] = Field(default_factory=list)
    candidate_events: list[ReplayEventResponse] = Field(default_factory=list)
    moment_shots: list[ReplayMomentShotResponse] = Field(default_factory=list)
    visual_moments: list[ReplayVisualMomentResponse] = Field(default_factory=list)
    battle_timeline: ReplayBattleTimelineResponse | None = None
    tactical_analysis: ReplayTacticalAnalysisResponse | None = None
    coach_reply: str | None = None
    coach_source: str | None = None
    game_state_observations: list[dict] = Field(default_factory=list)
    elixir_observations: list[dict] = Field(default_factory=list)
    cycle: dict | None = None
    what_is_confirmed: list[str] = Field(default_factory=list)
    what_is_uncertain: list[str] = Field(default_factory=list)
    what_is_unavailable: list[str] = Field(default_factory=list)


class ReplayAnalyzeSuccess(BaseModel):
    ok: bool = True
    status: str
    filename: str
    mime_type: str
    size_bytes: int
    duration_seconds: float
    width: int
    height: int
    fps: float | None = None
    replay_detection: ReplayDetectionResponse | None = None
    replay_facts: ReplayFactsResponse | None = None


class ReplayAnalyzeError(BaseModel):
    ok: bool = False
    error_code: str


class GhosteekAiAskResponse(BaseModel):
    intent: str
    answer: str
    sources: dict = Field(default_factory=dict)
    actions: list[GhosteekAiAction] = Field(default_factory=list)
    deck_card: DeckCardResponse | None = None
    battle_card: BattleCardResponse | None = None
    analysis_card: AnalysisCardResponse | None = None


class MetaHistoryPoint(BaseModel):
    day: str
    games: int


class MetaLadderDeck(BaseModel):
    rank: int
    deck_hash: str = ""
    cards: list[DeckCardInfo]
    games_count: int
    wins: int = 0
    losses: int = 0
    win_rate: float
    unique_players: int = 0
    trend: str = "stable"
    trend_percent: float | None = None
    history: list[MetaHistoryPoint] = Field(default_factory=list)
    history_available: bool = False
    last_seen: str | None = None
    deck_link: str | None = None
    low_sample: bool = False


class MetaLadderResponse(BaseModel):
    mode: str
    status: str
    message: str | None = None
    sample_note: str
    updated_at: str | None = None
    min_games: int = 0
    decks: list[MetaLadderDeck] = Field(default_factory=list)


class MetaWarDeck(BaseModel):
    rank: int
    cards: list[DeckCardInfo]
    name: str = ""
    role: str = ""
    recommendation: str = ""
    deck_link: str | None = None


class MetaWarResponse(BaseModel):
    mode: str = "clan_wars"
    status: str
    message: str | None = None
    source: str = ""
    source_url: str = ""
    updated_at: str | None = None
    sample_note: str = ""
    decks: list[MetaWarDeck] = Field(default_factory=list)

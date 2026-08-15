"""Grounded replay tactical analysis. No LLM; no invented coaching."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from bot.services.card_matchups import card_counters_target, synergy_between
from bot.services.card_profile import get_card_profile
from bot.services.ghosteek_ai.replay.battle_timeline import ReplayBattleTimeline
from bot.services.ghosteek_ai.replay.card_catalog import CardCatalog, CatalogCard
from bot.services.ghosteek_ai.replay.card_recognizer import ConfirmedCardFact
from bot.services.ghosteek_ai.replay.events import (
    EVENT_BATTLE_ENDED,
    EVENT_BATTLE_STARTED,
    EVENT_CARD_PLAY,
    EVENT_CARD_PLAY_CANDIDATE,
    EVENT_CARD_VISIBLE,
    EVENT_OVERTIME_STARTED,
    EVENT_RESULT_VISIBLE,
    PLAYER_OPPONENT,
    PLAYER_SELF,
    ReplayEvent,
)

_INSUFFICIENT_MOMENT = (
    "По доступным данным я не могу подтвердить причину этого момента."
)

_DEFAULT_DONT_KNOW = (
    "exact elixir",
    "exact damage",
    "tower HP",
    "some card plays",
    "frame-level timing",
    "full deck identity",
)

CONCLUSION_KINDS = frozenset(
    {
        "positive_play",
        "negative_play",
        "possible_mistake",
        "good_defense",
        "bad_trade",
        "pressure_opportunity",
        "cycle_opportunity",
        "matchup_issue",
    }
)


@dataclass(frozen=True)
class AnalysisLimitations:
    what_we_know: list[str] = field(default_factory=list)
    what_we_dont_know: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "what_we_know": list(self.what_we_know),
            "what_we_dont_know": list(self.what_we_dont_know),
        }


@dataclass(frozen=True)
class TacticalConclusion:
    kind: str
    text: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    related_events: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.kind not in CONCLUSION_KINDS:
            raise ValueError(f"unknown conclusion kind: {self.kind}")

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "text": self.text,
            "confidence": round(float(self.confidence), 4),
            "evidence": list(self.evidence),
            "related_events": [round(float(t), 3) for t in self.related_events],
        }


@dataclass(frozen=True)
class ReplayTacticalAnalysis:
    summary: str
    positive_actions: list[str] = field(default_factory=list)
    possible_mistakes: list[str] = field(default_factory=list)
    matchup_observations: list[str] = field(default_factory=list)
    deck_observations: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    confidence: float = 0.0
    limitations: AnalysisLimitations = field(default_factory=AnalysisLimitations)
    conclusions: list[TacticalConclusion] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "positive_actions": list(self.positive_actions),
            "possible_mistakes": list(self.possible_mistakes),
            "matchup_observations": list(self.matchup_observations),
            "deck_observations": list(self.deck_observations),
            "recommendations": list(self.recommendations),
            "confidence": round(float(self.confidence), 4),
            "limitations": self.limitations.to_dict(),
            "conclusions": [c.to_dict() for c in self.conclusions],
        }


class ReplayTacticalAnalyzer:
    """
    Structured tactical notes from confirmed timeline/cards only.

    Candidate events and unknown cards are never treated as authoritative.
    Matchup engine runs only when both sides have confirmed cards.
    """

    def __init__(self, catalog: CardCatalog | None = None) -> None:
        self._catalog = catalog if catalog is not None else CardCatalog.from_loaded_registry()

    def analyze(
        self,
        *,
        battle_timeline: ReplayBattleTimeline | None,
        confirmed_cards: Sequence[ConfirmedCardFact] = (),
        confirmed_events: Sequence[ReplayEvent] | None = None,
        events: Sequence[ReplayEvent] = (),
    ) -> ReplayTacticalAnalysis:
        if battle_timeline is None:
            return self._insufficient(
                summary="Недостаточно данных для тактического разбора реплея.",
                confidence=0.0,
                know=[],
            )

        confirmed = list(
            confirmed_events
            if confirmed_events is not None
            else battle_timeline.confirmed_events
        )
        all_events = list(events) if events else list(battle_timeline.events)
        cards = [c for c in confirmed_cards if float(c.confidence) >= 0.90]

        player_names, opponent_names, unresolved = self._side_card_names(confirmed, cards)
        has_candidates = any(e.event_type == EVENT_CARD_PLAY_CANDIDATE for e in all_events)

        know = self._what_we_know(battle_timeline, confirmed, cards, player_names, opponent_names)
        dont = list(_DEFAULT_DONT_KNOW)
        if has_candidates:
            dont.append("card_play_candidate events are not confirmed plays")
        if unresolved:
            dont.append("some detected card ids could not be resolved in the card database")
        if not any(e.event_type == EVENT_CARD_PLAY for e in confirmed):
            dont.append("confirmed card_play timestamps")

        deck_obs = self._deck_observations(cards, player_names, opponent_names)
        matchup_obs = self._matchup_observations(player_names, opponent_names)
        positives = self._positive_actions(confirmed, player_names, opponent_names)
        mistakes = self._possible_mistakes(
            confirmed=confirmed,
            cards=cards,
            has_candidates=has_candidates,
        )
        recommendations = self._recommendations(
            cards=cards,
            player_names=player_names,
            opponent_names=opponent_names,
            has_candidates=has_candidates,
            matchup_obs=matchup_obs,
        )
        summary = self._summary(
            battle_timeline=battle_timeline,
            cards=cards,
            confirmed=confirmed,
            matchup_obs=matchup_obs,
        )
        confidence = self._confidence(battle_timeline, cards, confirmed, matchup_obs)
        conclusions = self._conclusions(
            confirmed=confirmed,
            player_names=player_names,
            opponent_names=opponent_names,
            matchup_obs=matchup_obs,
        )

        return ReplayTacticalAnalysis(
            summary=summary,
            positive_actions=positives,
            possible_mistakes=mistakes,
            matchup_observations=matchup_obs,
            deck_observations=deck_obs,
            recommendations=recommendations,
            confidence=confidence,
            limitations=AnalysisLimitations(what_we_know=know, what_we_dont_know=dont),
            conclusions=conclusions,
        )

    def _insufficient(
        self,
        *,
        summary: str,
        confidence: float,
        know: list[str],
    ) -> ReplayTacticalAnalysis:
        return ReplayTacticalAnalysis(
            summary=summary,
            positive_actions=[],
            possible_mistakes=[_INSUFFICIENT_MOMENT],
            matchup_observations=[],
            deck_observations=[],
            recommendations=[
                "Пришли запись боя целиком и покрупнее — так проще подтвердить карты и ключевые моменты."
            ],
            confidence=confidence,
            limitations=AnalysisLimitations(
                what_we_know=know,
                what_we_dont_know=list(_DEFAULT_DONT_KNOW),
            ),
            conclusions=[],
        )

    def _resolve_name(self, card_id: str | None, card_name: str | None = None) -> str | None:
        if not card_id and not card_name:
            return None
        found: CatalogCard | None = self._catalog.resolve(card_id=card_id, card_name=card_name)
        if found is None:
            return None
        return found.card_name

    def _side_card_names(
        self,
        confirmed: Sequence[ReplayEvent],
        cards: Sequence[ConfirmedCardFact],
    ) -> tuple[list[str], list[str], list[str]]:
        player: set[str] = set()
        opponent: set[str] = set()
        unresolved: list[str] = []

        for ev in confirmed:
            if not ev.card_id:
                continue
            name = self._resolve_name(ev.card_id)
            if name is None:
                unresolved.append(str(ev.card_id))
                continue
            if ev.player == PLAYER_SELF:
                player.add(name)
            elif ev.player == PLAYER_OPPONENT:
                opponent.add(name)

        for card in cards:
            name = self._resolve_name(card.card_id, card.card_name)
            if name is None:
                unresolved.append(card.card_id)
        return sorted(player), sorted(opponent), sorted(set(unresolved))

    def _what_we_know(
        self,
        battle_timeline: ReplayBattleTimeline,
        confirmed: Sequence[ReplayEvent],
        cards: Sequence[ConfirmedCardFact],
        player_names: Sequence[str],
        opponent_names: Sequence[str],
    ) -> list[str]:
        know: list[str] = []
        if battle_timeline.duration_seconds > 0:
            know.append(f"replay duration ≈ {round(battle_timeline.duration_seconds, 1)}s")
        if any(e.event_type == EVENT_BATTLE_STARTED for e in confirmed):
            know.append("battle_start confirmed")
        if any(e.event_type in {EVENT_RESULT_VISIBLE, EVENT_BATTLE_ENDED} for e in confirmed):
            know.append("result/ending markers confirmed")
        if any(e.event_type == EVENT_OVERTIME_STARTED for e in confirmed):
            know.append("overtime_started confirmed")
        if cards:
            know.append(f"{len(cards)} confirmed card presence interval(s)")
        if player_names:
            know.append(f"{len(player_names)} player-side confirmed card(s)")
        if opponent_names:
            know.append(f"{len(opponent_names)} opponent-side confirmed card(s)")
        if battle_timeline.unknown_intervals:
            know.append(f"{len(battle_timeline.unknown_intervals)} unknown timeline gap(s)")
        return know

    def _deck_observations(
        self,
        cards: Sequence[ConfirmedCardFact],
        player_names: Sequence[str],
        opponent_names: Sequence[str],
    ) -> list[str]:
        obs: list[str] = []
        seen_names: list[str] = []
        for card in cards:
            name = self._resolve_name(card.card_id, card.card_name)
            if name is None:
                continue
            if name in seen_names:
                continue
            seen_names.append(name)
            profile = get_card_profile(name)
            roles = sorted(profile.roles)[:4]
            role_txt = ", ".join(roles) if roles else "no roles listed"
            bits = [f"{name}: elixir {profile.elixir}", f"type {profile.card_type}", role_txt]
            if profile.is_win_condition:
                bits.append("win condition (database)")
            if profile.is_flying:
                bits.append("flying (database)")
            if profile.can_target_air:
                bits.append("anti-air (database)")
            obs.append("; ".join(bits))

        for label, names in (("player", player_names), ("opponent", opponent_names)):
            for i, a in enumerate(names):
                for b in names[i + 1 :]:
                    tier = synergy_between(a, b)
                    if tier == "strong":
                        obs.append(f"{label} synergy (database): {a} + {b}")
        return obs[:16]

    def _matchup_observations(
        self,
        player_names: Sequence[str],
        opponent_names: Sequence[str],
    ) -> list[str]:
        if not player_names or not opponent_names:
            return []
        obs: list[str] = []
        if len(player_names) >= 8 and len(opponent_names) >= 8:
            try:
                from bot.services.matchup_evaluation import evaluate_matchup

                report = evaluate_matchup(list(player_names[:8]), list(opponent_names[:8]))
                obs.append(
                    f"Matchup score (confirmed 8+8 only): {report.score} ({report.rating})"
                )
                for reason in list(report.reasons)[:3]:
                    obs.append(f"matchup: {reason}")
            except Exception:
                pass
            try:
                from bot.services.tactical_matchup import analyze_tactical_matchup

                tactical = analyze_tactical_matchup(
                    list(player_names[:8]), list(opponent_names[:8])
                )
                for item in list(getattr(tactical, "critical_interactions", None) or [])[:3]:
                    text = item if isinstance(item, str) else str(item)
                    if text.strip():
                        obs.append(f"tactical: {text.strip()}")
            except Exception:
                pass

        for p in player_names:
            for o in opponent_names:
                tier = card_counters_target(p, o)
                if tier == "strong":
                    obs.append(f"database counter: {p} answers {o} (strong)")
                elif tier == "partial":
                    obs.append(f"database counter: {p} partially answers {o}")
                rev = card_counters_target(o, p)
                if rev == "strong":
                    obs.append(f"database threat: {o} answers {p} (strong)")
        return obs[:12]

    def _positive_actions(
        self,
        confirmed: Sequence[ReplayEvent],
        player_names: Sequence[str],
        opponent_names: Sequence[str],
    ) -> list[str]:
        out: list[str] = []
        if any(e.event_type == EVENT_BATTLE_STARTED for e in confirmed):
            out.append("Подтверждено начало боя в timeline.")
        visibles = [e for e in confirmed if e.event_type == EVENT_CARD_VISIBLE and e.card_id]
        if visibles:
            out.append(
                f"Подтверждено присутствие карт на кадрах ({len(visibles)} visibility event(s))."
            )
        if player_names:
            out.append(
                "Подтверждены карты игрока: "
                + ", ".join(player_names[:6])
                + ("…" if len(player_names) > 6 else "")
            )
        if opponent_names:
            out.append(
                "Подтверждены карты оппонента: "
                + ", ".join(opponent_names[:6])
                + ("…" if len(opponent_names) > 6 else "")
            )
        if any(e.event_type == EVENT_RESULT_VISIBLE for e in confirmed):
            out.append("Подтверждён экран результата.")
        return out[:8]

    def _conclusions(
        self,
        *,
        confirmed: Sequence[ReplayEvent],
        player_names: Sequence[str],
        opponent_names: Sequence[str],
        matchup_obs: Sequence[str],
    ) -> list[TacticalConclusion]:
        """Emit structured conclusions only when backed by confirmed events/evidence."""
        out: list[TacticalConclusion] = []
        plays = [e for e in confirmed if e.event_type == EVENT_CARD_PLAY and e.card_id]
        if any(e.event_type == EVENT_BATTLE_STARTED for e in confirmed):
            started = next(e for e in confirmed if e.event_type == EVENT_BATTLE_STARTED)
            out.append(
                TacticalConclusion(
                    kind="positive_play",
                    text="Подтверждено начало боя по HUD/арене.",
                    confidence=float(started.confidence),
                    evidence=list(started.evidence.observation_ids),
                    related_events=[float(started.timestamp_seconds)],
                )
            )
        for ev in plays[:6]:
            name = self._resolve_name(ev.card_id) or "карта"
            side = "ты" if ev.player == PLAYER_SELF else "соперник" if ev.player == PLAYER_OPPONENT else "неизвестная сторона"
            out.append(
                TacticalConclusion(
                    kind="positive_play",
                    text=f"Подтверждённый розыгрыш: {side} — {name}.",
                    confidence=float(ev.confidence),
                    evidence=list(ev.evidence.observation_ids),
                    related_events=[float(ev.timestamp_seconds)],
                )
            )
        # Defense / matchup conclusions only with both sides + temporal pairing
        player_plays = [e for e in plays if e.player == PLAYER_SELF]
        opp_plays = [e for e in plays if e.player == PLAYER_OPPONENT]
        for pp in player_plays:
            for op in opp_plays:
                gap = float(op.timestamp_seconds) - float(pp.timestamp_seconds)
                if 0.05 <= gap <= 4.0:
                    p_name = self._resolve_name(pp.card_id)
                    o_name = self._resolve_name(op.card_id)
                    if not p_name or not o_name:
                        continue
                    tier = card_counters_target(o_name, p_name)
                    if tier in {"strong", "partial"}:
                        out.append(
                            TacticalConclusion(
                                kind="good_defense",
                                text=f"Возможный ответ: {o_name} после {p_name} (~{gap:.1f}s).",
                                confidence=min(float(pp.confidence), float(op.confidence), 0.88),
                                evidence=list(pp.evidence.observation_ids)
                                + list(op.evidence.observation_ids),
                                related_events=[
                                    float(pp.timestamp_seconds),
                                    float(op.timestamp_seconds),
                                ],
                            )
                        )
                        break
        if matchup_obs and player_names and opponent_names:
            out.append(
                TacticalConclusion(
                    kind="matchup_issue",
                    text=matchup_obs[0],
                    confidence=0.7,
                    evidence=["matchup_engine"],
                    related_events=[],
                )
            )
        if len(plays) >= 3:
            out.append(
                TacticalConclusion(
                    kind="cycle_opportunity",
                    text="Есть несколько подтверждённых розыгрышей — cycle можно строить только по ним.",
                    confidence=0.74,
                    evidence=[f"card_play:{e.card_id}" for e in plays[:4]],
                    related_events=[float(e.timestamp_seconds) for e in plays[:4]],
                )
            )
        # Never invent negative_play / bad_trade / possible_mistake without evidence
        return out[:12]

    def _possible_mistakes(
        self,
        *,
        confirmed: Sequence[ReplayEvent],
        cards: Sequence[ConfirmedCardFact],
        has_candidates: bool,
    ) -> list[str]:
        if not cards and not confirmed:
            return [_INSUFFICIENT_MOMENT]
        if has_candidates:
            return [
                "Есть только предположения по постановкам карт — "
                "ошибки по таймингу и эликсиру пока не подтверждаю."
            ]
        return [_INSUFFICIENT_MOMENT]

    def _recommendations(
        self,
        *,
        cards: Sequence[ConfirmedCardFact],
        player_names: Sequence[str],
        opponent_names: Sequence[str],
        has_candidates: bool,
        matchup_obs: Sequence[str],
    ) -> list[str]:
        out: list[str] = []
        if not cards:
            out.append(
                "Нужно чётче видеть карты на экране — тогда разберу конкретные розыгрыши."
            )
        if has_candidates:
            out.append(
                "Похожие постановки пока только предположения — на них как на факт не опирайся."
            )
        if player_names and not opponent_names:
            out.append("Карты соперника пока не подтвердил — полный матчап не собираю.")
        if opponent_names and not player_names:
            out.append("Твои карты по стороне пока не подтвердил — полный матчап не собираю.")
        if player_names and opponent_names and not matchup_obs:
            out.append("Обе стороны частично видны, но устойчивых контр по базе пока нет.")
        if len(player_names) < 8 or len(opponent_names) < 8:
            out.append("Полные колоды пока не собрал — недостающие карты не угадываю.")
        if not out:
            out.append(
                "Опирайся только на то, что уже видно уверенно; пустые участки боя не заполняю догадками."
            )
        return out[:8]

    def _summary(
        self,
        *,
        battle_timeline: ReplayBattleTimeline,
        cards: Sequence[ConfirmedCardFact],
        confirmed: Sequence[ReplayEvent],
        matchup_obs: Sequence[str],
    ) -> str:
        n_cards = len(cards)
        n_ev = len(confirmed)
        if n_cards == 0 and n_ev == 0:
            return (
                "Похоже на реплей Clash Royale, но по этой записи пока мало уверенных деталей "
                "для полного разбора."
            )
        parts: list[str] = []
        if n_cards:
            parts.append(f"Уверенно вижу на записи {n_cards} карт(ы).")
        if n_ev:
            parts.append(f"Собрал {n_ev} подтверждённых момента(ов) по бою.")
        if battle_timeline.summary and battle_timeline.summary.unknown_intervals_count:
            parts.append("Часть боя пока без уверенных сигналов.")
        if matchup_obs:
            parts.append("По подтверждённым картам обеих сторон есть наблюдения по матчапу.")
        else:
            parts.append(
                "Тайминги розыгрышей, эликсир и причину поражения пока не подтверждаю."
            )
        return " ".join(parts)

    def _confidence(
        self,
        battle_timeline: ReplayBattleTimeline,
        cards: Sequence[ConfirmedCardFact],
        confirmed: Sequence[ReplayEvent],
        matchup_obs: Sequence[str],
    ) -> float:
        base = float(battle_timeline.confidence or 0.0)
        if not confirmed and not cards:
            return 0.0
        if not matchup_obs:
            return round(min(base, 0.72), 4)
        return round(min(max(base, 0.5), 0.88), 4)

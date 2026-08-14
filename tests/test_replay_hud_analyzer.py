"""HeuristicHudAnalyzer: synthetic frames, conservative CR / not-CR / uncertain."""

from __future__ import annotations

from PIL import Image, ImageDraw

from bot.services.ghosteek_ai.replay.hud_analyzer import HeuristicHudAnalyzer, _sanitize_observations
from bot.services.ghosteek_ai.replay.models import STATUS_CR, STATUS_NOT_CR, STATUS_UNCERTAIN


def make_cr_like(width: int = 360, height: int = 640) -> Image.Image:
    im = Image.new("RGB", (width, height), (36, 92, 48))
    draw = ImageDraw.Draw(im)
    for x in range(0, width, 12):
        for y in range(int(height * 0.16), int(height * 0.76), 12):
            draw.rectangle(
                [x, y, x + 6, y + 6],
                fill=(40 + (x % 40), 88 + (y % 35), 50 + (x // 9) % 20),
            )
    draw.rectangle([int(width * 0.28), int(height * 0.14), int(width * 0.72), int(height * 0.30)], fill=(190, 48, 48))
    draw.rectangle([int(width * 0.28), int(height * 0.54), int(width * 0.72), int(height * 0.70)], fill=(36, 72, 210))
    bar_y = int(height * 0.82)
    draw.rectangle([0, bar_y, width, height], fill=(36, 32, 28))
    slot = width // 5
    colors = [(210, 70, 70), (70, 200, 80), (70, 90, 220), (210, 200, 70)]
    for i, color in enumerate(colors):
        x = 8 + i * slot
        draw.rectangle([x, bar_y + 6, x + slot - 14, height - 8], fill=color)
    # Purple blob in the last slot / HUD corner — keep card peaks intact.
    hx = int(width * 0.82)
    draw.ellipse([hx, int(height * 0.88), width - 4, height - 4], fill=(180, 40, 210))
    return im


def make_document() -> Image.Image:
    return Image.new("RGB", (360, 640), (248, 248, 248))


def make_grass_only() -> Image.Image:
    return Image.new("RGB", (360, 640), (48, 140, 52))


def test_cr_like_frame_high_score() -> None:
    analyzer = HeuristicHudAnalyzer()
    scored = analyzer.analyze_frame(make_cr_like())
    assert scored.score >= 0.55
    names = {s.signal for s in scored.signals if s.score >= 0.55}
    assert "card_bar" in names or "elixir_hud" in names or "arena_layout" in names


def test_non_cr_frame_low_score() -> None:
    analyzer = HeuristicHudAnalyzer()
    scored = analyzer.analyze_frame(make_document())
    assert scored.score <= 0.40


def test_cr_like_aggregate_is_cr() -> None:
    analyzer = HeuristicHudAnalyzer()
    frame = make_cr_like()
    scores: list[float] = []
    hits: dict[str, int] = {}
    obs: list[str] = []
    for _ in range(20):
        scored = analyzer.analyze_frame(frame)
        scores.append(scored.score)
        for sig in scored.signals:
            if sig.score >= 0.55 and sig.observation:
                hits[sig.signal] = hits.get(sig.signal, 0) + 1
                if sig.observation not in obs:
                    obs.append(sig.observation)
    result = analyzer.classify(scores, obs, frames_analyzed=20, signal_hits=hits)
    assert result.status == STATUS_CR
    assert result.confidence >= 0.75
    assert result.frames_analyzed == 20
    blob = " ".join(result.observations).lower()
    assert "hog" not in blob
    assert "played at" not in blob


def test_non_cr_aggregate_is_not_cr() -> None:
    analyzer = HeuristicHudAnalyzer()
    scores: list[float] = []
    hits: dict[str, int] = {}
    for _ in range(20):
        scored = analyzer.analyze_frame(make_document())
        scores.append(scored.score)
        for sig in scored.signals:
            if sig.score >= 0.55:
                hits[sig.signal] = hits.get(sig.signal, 0) + 1
    result = analyzer.classify(scores, [], frames_analyzed=20, signal_hits=hits)
    assert result.status == STATUS_NOT_CR
    assert result.confidence <= 0.30
    assert any("not detected" in o.lower() or "insufficient" in o.lower() for o in result.observations)


def test_mixed_frames_uncertain() -> None:
    analyzer = HeuristicHudAnalyzer()
    scores = [0.82] * 8 + [0.16] * 7 + [0.44] * 5
    result = analyzer.classify(scores, ["gameplay-like layout detected"], frames_analyzed=20, signal_hits={})
    assert result.status == STATUS_UNCERTAIN
    assert 0.30 < result.confidence < 0.75


def test_one_positive_among_many_negative_not_cr() -> None:
    analyzer = HeuristicHudAnalyzer()
    scores = [0.88] + [0.12] * 19
    result = analyzer.classify(
        scores,
        ["bottom card-like UI region detected"],
        frames_analyzed=20,
        signal_hits={"card_bar": 1},
    )
    assert result.status != STATUS_CR
    assert result.confidence < 0.75


def test_filename_has_zero_influence() -> None:
    analyzer = HeuristicHudAnalyzer()
    img = make_grass_only()
    a = analyzer.analyze_frame(img)
    b = analyzer.analyze_frame(img)
    assert a.score == b.score
    result = analyzer.classify([a.score] * 16, [], frames_analyzed=16, signal_hits={})
    assert result.status != STATUS_CR
    # analyze_frame has no filename argument — grass-only must not become CR.


def test_never_returns_cards_or_events() -> None:
    dirty = _sanitize_observations(
        [
            "Hog Rider",
            "Witch at 32s",
            "played at 32s",
            "spent 4 elixir",
            "lost tower",
            "made mistake",
            "card bar detected",
        ]
    )
    blob = " ".join(dirty).lower()
    for token in ("hog", "witch", "played at", "spent", "lost tower", "made mistake"):
        assert token not in blob
    assert "card bar detected" in dirty

    analyzer = HeuristicHudAnalyzer()
    scored = analyzer.analyze_frame(make_cr_like())
    for sig in scored.signals:
        low = sig.observation.lower()
        assert "hog" not in low
        assert "fireball" not in low
        assert "32s" not in low

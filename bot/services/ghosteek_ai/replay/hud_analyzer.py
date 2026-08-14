"""Conservative Clash Royale HUD heuristics. No OCR, no card names, no events."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PIL import Image

from bot.services.ghosteek_ai.replay.models import (
    STATUS_CR,
    STATUS_NOT_CR,
    STATUS_UNCERTAIN,
    FrameScore,
    HeuristicSignal,
    ReplayDetection,
    detection_thresholds,
)

_ANALYSIS_MAX = (180, 320)

_FORBIDDEN = (
    "hog",
    "witch",
    "fireball",
    "cannon",
    "miner",
    "knight",
    "goblin",
    "elixir golem",
    "played at",
    "spent",
    "lost tower",
    "made mistake",
    "win condition",
)


def _open_rgb(source: Image.Image | str | Path) -> Image.Image:
    if isinstance(source, Image.Image):
        im = source.convert("RGB").copy()
    else:
        with Image.open(source) as raw:
            im = raw.convert("RGB")
            im.load()
    im.thumbnail(_ANALYSIS_MAX, Image.BILINEAR)
    return im


def _region(im: Image.Image, x0: float, y0: float, x1: float, y1: float) -> Image.Image:
    w, h = im.size
    left = max(0, int(w * x0))
    top = max(0, int(h * y0))
    right = min(w, max(left + 1, int(w * x1)))
    bottom = min(h, max(top + 1, int(h * y1)))
    return im.crop((left, top, right, bottom))


def _mean_rgb(im: Image.Image) -> tuple[float, float, float]:
    pixels = list(im.getdata())
    n = max(len(pixels), 1)
    r = sum(p[0] for p in pixels) / n
    g = sum(p[1] for p in pixels) / n
    b = sum(p[2] for p in pixels) / n
    return r, g, b


def _luma(p: tuple[int, int, int]) -> float:
    return 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]


def _stddev_luma(im: Image.Image) -> float:
    pixels = list(im.getdata())
    if not pixels:
        return 0.0
    values = [_luma(p) for p in pixels]
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return var ** 0.5


class MobileAspectRatioHeuristic:
    def run(self, im: Image.Image) -> HeuristicSignal:
        w, h = im.size
        ratio = h / max(w, 1)
        if ratio >= 1.5:
            return HeuristicSignal("mobile_aspect", 0.82, 0.62, "portrait/mobile gameplay layout")
        if ratio >= 1.25:
            return HeuristicSignal("mobile_aspect", 0.55, 0.45, "tall gameplay layout")
        if w / max(h, 1) >= 1.5:
            return HeuristicSignal("mobile_aspect", 0.22, 0.30, "landscape layout")
        return HeuristicSignal("mobile_aspect", 0.20, 0.25, "non-mobile aspect ratio")


class GameplayRegionHeuristic:
    def run(self, im: Image.Image) -> HeuristicSignal:
        center = _region(im, 0.12, 0.18, 0.88, 0.74)
        std = _stddev_luma(center)
        r, g, b = _mean_rgb(center)
        chroma = abs(r - g) + abs(g - b) + abs(b - r)
        if std >= 22 and chroma >= 18:
            return HeuristicSignal("gameplay_region", 0.72, 0.60, "gameplay-like central region detected")
        if std >= 18:
            return HeuristicSignal("gameplay_region", 0.40, 0.45, "textured central region")
        return HeuristicSignal("gameplay_region", 0.12, 0.55, "flat or non-gameplay center")


class CardBarHeuristic:
    def run(self, im: Image.Image) -> HeuristicSignal:
        bar = _region(im, 0.04, 0.80, 0.96, 0.99)
        w, h = bar.size
        if w < 16 or h < 4:
            return HeuristicSignal("card_bar", 0.05, 0.4, "")
        cols: list[float] = []
        pix = bar.load()
        step = max(1, w // 48)
        for x in range(0, w, step):
            total = 0.0
            n = 0
            for y in range(h):
                total += _luma(pix[x, y])
                n += 1
            cols.append(total / max(n, 1))
        if len(cols) < 8:
            return HeuristicSignal("card_bar", 0.08, 0.4, "")
        mean = sum(cols) / len(cols)
        peaks: list[int] = []
        for i in range(1, len(cols) - 1):
            if cols[i] >= cols[i - 1] and cols[i] >= cols[i + 1] and cols[i] > mean + 8:
                if not peaks or i - peaks[-1] >= 2:
                    peaks.append(i)
        n_peaks = len(peaks)
        if 3 <= n_peaks <= 8:
            gaps = [peaks[i + 1] - peaks[i] for i in range(len(peaks) - 1)]
            if gaps:
                avg_gap = sum(gaps) / len(gaps)
                jitter = sum(abs(g - avg_gap) for g in gaps) / len(gaps)
                if avg_gap > 0 and jitter / avg_gap <= 0.55:
                    return HeuristicSignal(
                        "card_bar",
                        0.84,
                        0.78,
                        "bottom card-like UI region detected",
                    )
            return HeuristicSignal("card_bar", 0.58, 0.55, "bottom card-like UI region detected")
        return HeuristicSignal("card_bar", 0.10, 0.50, "")


class ElixirHudHeuristic:
    def run(self, im: Image.Image) -> HeuristicSignal:
        zones = (
            _region(im, 0.55, 0.82, 0.99, 0.99),
            _region(im, 0.01, 0.82, 0.45, 0.99),
        )
        best = 0.0
        for zone in zones:
            pixels = list(zone.getdata())
            if not pixels:
                continue
            purple = 0
            for r, g, b in pixels:
                if r > 90 and b > 95 and g < 0.78 * min(r, b) and max(r, b) - g > 28:
                    purple += 1
            frac = purple / len(pixels)
            if frac > best:
                best = frac
        if 0.012 <= best <= 0.32:
            return HeuristicSignal("elixir_hud", 0.80, 0.72, "elixir-like HUD region detected")
        if best >= 0.008:
            return HeuristicSignal("elixir_hud", 0.42, 0.45, "weak purple HUD hint")
        return HeuristicSignal("elixir_hud", 0.06, 0.55, "")


class ArenaLayoutHeuristic:
    def run(self, im: Image.Image) -> HeuristicSignal:
        arena = _region(im, 0.10, 0.16, 0.90, 0.78)
        upper = _region(im, 0.22, 0.16, 0.78, 0.40)
        lower = _region(im, 0.22, 0.50, 0.78, 0.74)
        grass = _green_or_dirt_frac(arena)
        upper_red = _red_frac(upper)
        lower_blue = _blue_frac(lower)
        split = upper_red >= 0.04 and lower_blue >= 0.04
        if grass >= 0.12 and split:
            return HeuristicSignal(
                "arena_layout",
                0.82,
                0.74,
                "arena-like central gameplay region detected",
            )
        if grass >= 0.18:
            return HeuristicSignal("arena_layout", 0.40, 0.45, "arena-like central gameplay region detected")
        if split:
            return HeuristicSignal("arena_layout", 0.48, 0.40, "red/blue lane-like split detected")
        return HeuristicSignal("arena_layout", 0.08, 0.50, "")


def _green_or_dirt_frac(im: Image.Image) -> float:
    pixels = list(im.getdata())
    if not pixels:
        return 0.0
    hit = 0
    for r, g, b in pixels:
        grass = g > r + 8 and g > b and g > 55
        dirt = r > 70 and r >= g >= b and (r - b) > 18
        if grass or dirt:
            hit += 1
    return hit / len(pixels)


def _red_frac(im: Image.Image) -> float:
    pixels = list(im.getdata())
    if not pixels:
        return 0.0
    hit = sum(1 for r, g, b in pixels if r > g + 18 and r > b + 18 and r > 90)
    return hit / len(pixels)


def _blue_frac(im: Image.Image) -> float:
    pixels = list(im.getdata())
    if not pixels:
        return 0.0
    hit = sum(1 for r, g, b in pixels if b > r + 12 and b > g + 8 and b > 90)
    return hit / len(pixels)


_WEIGHTS = {
    "mobile_aspect": 0.08,
    "gameplay_region": 0.12,
    "card_bar": 0.30,
    "elixir_hud": 0.25,
    "arena_layout": 0.25,
}


class HeuristicHudAnalyzer:
    def __init__(self) -> None:
        self._heuristics = (
            MobileAspectRatioHeuristic(),
            GameplayRegionHeuristic(),
            CardBarHeuristic(),
            ElixirHudHeuristic(),
            ArenaLayoutHeuristic(),
        )

    def analyze_frame(self, source: Image.Image | str | Path) -> FrameScore:
        im = _open_rgb(source)
        try:
            signals = tuple(h.run(im) for h in self._heuristics)
        finally:
            im.close()
        denom = 0.0
        numer = 0.0
        for sig in signals:
            weight = _WEIGHTS.get(sig.signal, 0.1)
            numer += sig.score * sig.confidence * weight
            denom += sig.confidence * weight
        score = numer / denom if denom else 0.0
        return FrameScore(score=max(0.0, min(1.0, score)), signals=signals)

    def classify(
        self,
        frame_scores: Sequence[float],
        observations: Sequence[str],
        *,
        frames_analyzed: int,
        signal_hits: dict[str, int] | None = None,
    ) -> ReplayDetection:
        cr_th, not_cr_th = detection_thresholds()
        n = len(frame_scores)
        clean_obs = _sanitize_observations(observations)
        if n == 0:
            return ReplayDetection(
                status=STATUS_UNCERTAIN,
                confidence=0.0,
                frames_analyzed=0,
                observations=["insufficient Clash Royale-specific signals"],
            )

        mean = sum(frame_scores) / n
        high = sum(1 for s in frame_scores if s >= 0.55)
        low = sum(1 for s in frame_scores if s <= 0.38)
        frac_high = high / n
        frac_low = low / n

        confidence = mean
        if frac_high >= 0.70:
            confidence = 0.50 * mean + 0.50 * (0.55 + 0.45 * frac_high)
        elif frac_low >= 0.55 and frac_high < 0.35:
            confidence = min(mean, 0.22 + 0.25 * frac_high)
        else:
            confidence = 0.34 + 0.32 * frac_high

        if n >= 8 and high <= 1:
            confidence = min(confidence, 0.42)

        hits = signal_hits or {}
        specific = 0
        for key in ("card_bar", "elixir_hud", "arena_layout"):
            if hits.get(key, 0) >= max(1, int(0.4 * n)):
                specific += 1
        if specific < 2:
            confidence = min(confidence, 0.68)

        confidence = max(0.0, min(1.0, confidence))
        if confidence >= cr_th and specific >= 2:
            status = STATUS_CR
        elif confidence <= not_cr_th:
            status = STATUS_NOT_CR
        else:
            status = STATUS_UNCERTAIN

        if status == STATUS_CR and not clean_obs:
            clean_obs = ["card bar detected", "arena-like gameplay region detected"]
        elif status == STATUS_NOT_CR:
            clean_obs = clean_obs or ["Clash Royale HUD signals not detected"]
        elif status == STATUS_UNCERTAIN:
            if not clean_obs:
                clean_obs = ["insufficient Clash Royale-specific signals"]
            elif "insufficient Clash Royale-specific signals" not in clean_obs:
                has_gameplay = any("gameplay" in o.lower() for o in clean_obs)
                if has_gameplay:
                    clean_obs = list(clean_obs) + ["insufficient Clash Royale-specific signals"]

        return ReplayDetection(
            status=status,
            confidence=round(confidence, 4),
            frames_analyzed=frames_analyzed,
            observations=clean_obs[:8],
        )


def _sanitize_observations(observations: Sequence[str]) -> list[str]:
    out: list[str] = []
    for raw in observations:
        text = " ".join(str(raw).split())
        if not text:
            continue
        low = text.lower()
        if any(token in low for token in _FORBIDDEN):
            continue
        if text not in out:
            out.append(text)
    return out

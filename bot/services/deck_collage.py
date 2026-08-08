"""Render a 4x2 deck collage PNG (evo / hero frames) for Telegram digests."""

from __future__ import annotations

import hashlib
import io
import logging
from pathlib import Path

import aiohttp
from PIL import Image, ImageDraw, ImageFont

from bot.config import settings
from bot.services.card_data import get_card_elixir
from bot.services.card_registry import get_card_info

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "card_icon_cache"

# Canvas
_COLS = 4
_ROWS = 2
_CARD = 168
_GAP = 14
_PAD = 28
_RADIUS = 22
_FRAME = 5

_BG_TOP = (8, 14, 36)
_BG_BOT = (4, 8, 22)
_SLOT_FILL = (18, 28, 52, 230)
_BASE_FRAME = (70, 90, 130)
_EVO_FRAME = (168, 85, 247)
_HERO_FRAME = (234, 179, 8)
_ELIXIR_BG = (120, 40, 180)
_ELIXIR_FG = (255, 255, 255)


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def _gradient_bg(width: int, height: int) -> Image.Image:
    img = Image.new("RGB", (width, height), _BG_BOT)
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(height - 1, 1)
        r = int(_BG_TOP[0] * (1 - t) + _BG_BOT[0] * t)
        g = int(_BG_TOP[1] * (1 - t) + _BG_BOT[1] * t)
        b = int(_BG_TOP[2] * (1 - t) + _BG_BOT[2] * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    # Soft vignette dots
    for i in range(0, width, 48):
        for j in range(0, height, 48):
            draw.ellipse((i + 8, j + 8, i + 14, j + 14), fill=(30, 45, 80))
    return img


def _frame_color(evolution_level: int, is_hero: bool) -> tuple[int, int, int]:
    if is_hero:
        return _HERO_FRAME
    if evolution_level >= 1:
        return _EVO_FRAME
    return _BASE_FRAME


def _resolve_icon_url(card: dict) -> str:
    name = (card.get("name") or "").strip()
    evo = int(card.get("evolution_level") or 0)
    hero = bool(card.get("is_hero"))
    info = get_card_info(name) or {}
    if hero and info.get("hero_icon"):
        return str(info["hero_icon"])
    if evo >= 1 and info.get("evolution_icon"):
        return str(info["evolution_icon"])
    if card.get("icon"):
        return str(card["icon"])
    return str(info.get("icon") or "")


def _absolute_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("/"):
        base = (settings.webapp_url or "").rstrip("/")
        return f"{base}{url}" if base else url
    return url


async def _fetch_icon(session: aiohttp.ClientSession, url: str) -> Image.Image | None:
    abs_url = _absolute_url(url)
    if not abs_url:
        return None
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(abs_url.encode("utf-8")).hexdigest()
    cached = _CACHE_DIR / f"{key}.png"
    if cached.exists() and cached.stat().st_size > 0:
        try:
            return Image.open(cached).convert("RGBA")
        except Exception:
            pass
    try:
        async with session.get(abs_url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
            if resp.status != 200:
                logger.debug("Icon fetch %s -> %s", abs_url, resp.status)
                return None
            data = await resp.read()
        cached.write_bytes(data)
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception as exc:
        logger.debug("Icon fetch failed %s: %s", abs_url, exc)
        return None


def _placeholder(size: int, name: str) -> Image.Image:
    img = Image.new("RGBA", (size, size), (40, 55, 90, 255))
    draw = ImageDraw.Draw(img)
    label = (name or "?")[:2].upper()
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    draw.text((size // 3, size // 3), label, fill=(200, 210, 230), font=font)
    return img


def _fit_card(src: Image.Image, size: int) -> Image.Image:
    fitted = src.copy()
    fitted.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ox = (size - fitted.width) // 2
    oy = (size - fitted.height) // 2
    canvas.paste(fitted, (ox, oy), fitted)
    return canvas


def _draw_elixir_badge(card_img: Image.Image, elixir: int) -> None:
    draw = ImageDraw.Draw(card_img)
    r = 18
    cx, cy = 22, 22
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=_ELIXIR_BG)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    text = str(elixir)
    draw.text((cx - 4, cy - 6), text, fill=_ELIXIR_FG, font=font)


async def render_deck_collage(cards: list[dict]) -> bytes | None:
    """Build PNG bytes for up to 8 cards. Each card: name, icon?, evolution_level?, is_hero?."""
    if not cards:
        return None
    slots = list(cards)[:8]
    while len(slots) < 8:
        slots.append({"name": "", "icon": "", "evolution_level": 0, "is_hero": False})

    width = _PAD * 2 + _COLS * _CARD + (_COLS - 1) * _GAP
    height = _PAD * 2 + _ROWS * _CARD + (_ROWS - 1) * _GAP
    canvas = _gradient_bg(width, height).convert("RGBA")

    async with aiohttp.ClientSession() as session:
        icons: list[Image.Image] = []
        for card in slots:
            url = _resolve_icon_url(card)
            img = await _fetch_icon(session, url) if url else None
            if img is None:
                img = _placeholder(_CARD, card.get("name") or "?")
            icons.append(_fit_card(img, _CARD - _FRAME * 2))

    for idx, card in enumerate(slots):
        col = idx % _COLS
        row = idx // _COLS
        x = _PAD + col * (_CARD + _GAP)
        y = _PAD + row * (_CARD + _GAP)

        evo = int(card.get("evolution_level") or 0)
        hero = bool(card.get("is_hero"))
        frame = _frame_color(evo, hero)

        slot = Image.new("RGBA", (_CARD, _CARD), (0, 0, 0, 0))
        slot_draw = ImageDraw.Draw(slot)
        slot_draw.rounded_rectangle(
            (0, 0, _CARD - 1, _CARD - 1),
            radius=_RADIUS,
            fill=_SLOT_FILL,
            outline=frame + (255,),
            width=_FRAME,
        )
        inner = icons[idx]
        mask = _rounded_mask(inner.size, _RADIUS - 4)
        ox = (_CARD - inner.width) // 2
        oy = (_CARD - inner.height) // 2
        slot.paste(inner, (ox, oy), mask)

        name = (card.get("name") or "").strip()
        if name:
            elixir = int(card.get("cost") or get_card_elixir(name) or 0)
            if elixir > 0:
                _draw_elixir_badge(slot, elixir)

        canvas.paste(slot, (x, y), slot)

    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()

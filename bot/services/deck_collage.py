"""Render a polished 4x2 deck collage PNG for Telegram digests."""

from __future__ import annotations

import hashlib
import io
import logging
from pathlib import Path

import aiohttp
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from bot.config import settings
from bot.services.card_data import get_card_elixir
from bot.services.card_icons import _refresh_card_icon
from bot.services.card_registry import get_card_info

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "card_icon_cache"

_COLS = 4
_ROWS = 2
_CARD = 176
_GAP = 18
_PAD = 32

# Ghosteek brand: accent blue → deep navy (tokens: --palette-blue / --palette-canvas)
_BG_TOP = (61, 108, 242)
_BG_MID = (18, 36, 96)
_BG_BOT = (0, 5, 26)

_EVO_GLOW = (168, 85, 247)
_HERO_GLOW = (234, 179, 8)
_BASE_SHADOW = (20, 40, 90)

# Webapp ElixirIcon: #e040fb
_ELIXIR_PINK = (224, 64, 251)
_ELIXIR_PINK_DARK = (170, 30, 200)


def _font(size: int) -> ImageFont.ImageFont:
    for name in (
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _gradient_bg(width: int, height: int) -> Image.Image:
    """Smooth vertical gradient: brand blue → mid navy → deep dark. No pattern noise."""
    img = Image.new("RGB", (width, height), _BG_BOT)
    draw = ImageDraw.Draw(img)
    mid = height * 0.42
    for y in range(height):
        if y <= mid:
            t = y / max(mid, 1)
            c0, c1 = _BG_TOP, _BG_MID
        else:
            t = (y - mid) / max(height - mid, 1)
            c0, c1 = _BG_MID, _BG_BOT
        r = int(c0[0] * (1 - t) + c1[0] * t)
        g = int(c0[1] * (1 - t) + c1[1] * t)
        b = int(c0[2] * (1 - t) + c1[2] * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    # Soft vignette (edges darker) without dots
    vignette = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    vdraw = ImageDraw.Draw(vignette)
    for i in range(48):
        alpha = int(70 * (1 - i / 48))
        vdraw.rectangle((i, i, width - 1 - i, height - 1 - i), outline=(0, 0, 0, alpha))
    base = img.convert("RGBA")
    return Image.alpha_composite(base, vignette).convert("RGB")


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


def normalize_collage_card(card: dict) -> dict:
    """Ensure evolution_level / is_hero / icon are consistent for rendering."""
    out = {
        "name": (card.get("name") or "").strip(),
        "icon": card.get("icon") or "",
        "evolution_level": int(card.get("evolution_level") or 0),
        "is_hero": bool(card.get("is_hero")),
        "cost": int(card.get("cost") or 0),
        "slot": int(card.get("slot") or 0),
    }
    if not out["cost"] and out["name"]:
        out["cost"] = int(get_card_elixir(out["name"]) or 0)
    # Heroes never show as evo simultaneously.
    if out["is_hero"]:
        out["evolution_level"] = 0
    _refresh_card_icon(out)
    # If catalog still empty, keep prior icon.
    if not out.get("icon"):
        info = get_card_info(out["name"]) or {}
        if out["is_hero"] and info.get("hero_icon"):
            out["icon"] = info["hero_icon"]
        elif out["evolution_level"] >= 1 and info.get("evolution_icon"):
            out["icon"] = info["evolution_icon"]
        else:
            out["icon"] = info.get("icon") or card.get("icon") or ""
    return out


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
    img = Image.new("RGBA", (size, size), (24, 40, 80, 255))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((4, 4, size - 5, size - 5), radius=18, outline=(80, 110, 180, 200), width=2)
    label = (name or "?")[:2].upper()
    font = _font(max(18, size // 5))
    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - tw) / 2, (size - th) / 2 - 2), label, fill=(220, 230, 255), font=font)
    return img


def _fit_card(src: Image.Image, size: int) -> Image.Image:
    """Contain card art in square, preserve aspect (native CR frames stay intact)."""
    fitted = src.copy()
    fitted.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ox = (size - fitted.width) // 2
    oy = (size - fitted.height) // 2
    canvas.paste(fitted, (ox, oy), fitted)
    return canvas


def _drop_mask(w: int, h: int) -> Image.Image:
    """Rasterize elixir drop path into an alpha mask (viewBox 20×24)."""
    # Scale path coordinates from 20x24 to w x h
    sx, sy = w / 20.0, h / 24.0
    # Approximate drop with ellipse body + pointed top polygon (matches CR drop silhouette)
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    # Body circle (cx=10, cy≈14.5, r≈5.8 in viewBox)
    cx, cy = 10 * sx, 14.2 * sy
    rx, ry = 5.8 * sx, 5.8 * sy
    draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=255)
    # Tip toward top (point at 10,1.2)
    tip_x, tip_y = 10 * sx, 1.2 * sy
    left = (4.8 * sx, 10 * sy)
    right = (15.2 * sx, 10 * sy)
    draw.polygon([left, (tip_x, tip_y), right], fill=255)
    return mask.filter(ImageFilter.GaussianBlur(radius=0.4))


def _draw_elixir_drop(card_img: Image.Image, elixir: int) -> None:
    drop_w, drop_h = 36, 44
    drop = Image.new("RGBA", (drop_w + 6, drop_h + 6), (0, 0, 0, 0))
    mask = _drop_mask(drop_w, drop_h)
    # Shadow
    shadow = Image.new("RGBA", drop.size, (0, 0, 0, 0))
    shadow_mask = Image.new("L", drop.size, 0)
    shadow_mask.paste(mask, (4, 4))
    shadow_layer = Image.new("RGBA", drop.size, (0, 0, 0, 110))
    drop.paste(shadow_layer, (0, 0), shadow_mask)
    # Fill
    fill = Image.new("RGBA", (drop_w, drop_h), _ELIXIR_PINK + (255,))
    # Subtle darker edge
    edge = Image.new("RGBA", (drop_w, drop_h), _ELIXIR_PINK_DARK + (255,))
    edge_mask = mask.point(lambda p: 220 if p > 20 else 0)
    fill = Image.composite(fill, edge, mask)
    # Highlight
    hi = ImageDraw.Draw(fill)
    hi.ellipse((10, 14, 18, 22), fill=(255, 180, 255, 90))
    drop.paste(fill, (1, 1), mask)

    font = _font(18)
    num = str(elixir)
    nd = ImageDraw.Draw(drop)
    bbox = nd.textbbox((0, 0), num, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    # Bias number slightly down into the bulb
    tx = (drop.size[0] - tw) / 2
    ty = (drop.size[1] - th) / 2 + 3
    nd.text((tx + 1, ty + 1), num, fill=(0, 0, 0, 160), font=font)
    nd.text((tx, ty), num, fill=(255, 255, 255, 255), font=font)

    card_img.alpha_composite(drop, dest=(-2, -4))


def _mode_badge(label: str, color: tuple[int, int, int]) -> Image.Image:
    font = _font(13)
    pad_x, pad_y = 8, 4
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = tmp.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    w, h = tw + pad_x * 2, th + pad_y * 2
    badge = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(badge)
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, fill=color + (230,))
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, outline=(255, 255, 255, 60), width=1)
    draw.text((pad_x - bbox[0], pad_y - bbox[1] - 1), label, fill=(255, 255, 255, 255), font=font)
    return badge


def _glow_behind(size: int, color: tuple[int, int, int], strength: int = 140) -> Image.Image:
    glow = Image.new("RGBA", (size + 24, size + 24), (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    cx = cy = (size + 24) // 2
    for i, alpha in ((size // 2 + 10, strength // 4), (size // 2 + 4, strength // 2), (size // 2 - 2, strength)):
        draw.ellipse(
            (cx - i, cy - i, cx + i, cy + i),
            fill=color + (alpha,),
        )
    return glow.filter(ImageFilter.GaussianBlur(radius=8))


def _compose_slot(card_art: Image.Image, card: dict) -> Image.Image:
    evo = int(card.get("evolution_level") or 0) >= 1
    hero = bool(card.get("is_hero"))
    size = _CARD
    canvas = Image.new("RGBA", (size + 24, size + 24), (0, 0, 0, 0))

    if hero:
        canvas.alpha_composite(_glow_behind(size, _HERO_GLOW, 160), dest=(0, 0))
    elif evo:
        canvas.alpha_composite(_glow_behind(size, _EVO_GLOW, 150), dest=(0, 0))
    else:
        canvas.alpha_composite(_glow_behind(size, _BASE_SHADOW, 90), dest=(0, 0))

    # Soft plate under card
    plate = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pdraw = ImageDraw.Draw(plate)
    pdraw.rounded_rectangle(
        (2, 2, size - 3, size - 3),
        radius=20,
        fill=(8, 16, 40, 160),
    )
    canvas.alpha_composite(plate, dest=(12, 12))
    canvas.alpha_composite(card_art, dest=(12, 12))

    # Mode ring (outside art so native CR frames stay readable)
    ring = Image.new("RGBA", (size + 24, size + 24), (0, 0, 0, 0))
    rdraw = ImageDraw.Draw(ring)
    if hero:
        color = _HERO_GLOW + (220,)
        width = 4
    elif evo:
        color = _EVO_GLOW + (220,)
        width = 4
    else:
        color = (90, 120, 190, 120)
        width = 2
    rdraw.rounded_rectangle(
        (10, 10, size + 13, size + 13),
        radius=22,
        outline=color,
        width=width,
    )
    canvas.alpha_composite(ring)

    if hero:
        badge = _mode_badge("HERO", _HERO_GLOW)
        canvas.alpha_composite(badge, dest=(size + 12 - badge.width, 6))
    elif evo:
        badge = _mode_badge("EVO", _EVO_GLOW)
        canvas.alpha_composite(badge, dest=(size + 12 - badge.width, 6))

    name = (card.get("name") or "").strip()
    if name:
        elixir = int(card.get("cost") or get_card_elixir(name) or 0)
        if elixir > 0:
            # Draw drop onto a layer aligned to card top-left
            layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            drop_host = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            _draw_elixir_drop(drop_host, elixir)
            layer.alpha_composite(drop_host, dest=(8, 6))
            canvas.alpha_composite(layer)

    return canvas


async def render_deck_collage(cards: list[dict]) -> bytes | None:
    """Build PNG for up to 8 cards. Respects evolution_level / is_hero for art + chrome."""
    if not cards:
        return None

    slots = [normalize_collage_card(c) for c in list(cards)[:8]]
    while len(slots) < 8:
        slots.append(normalize_collage_card({"name": ""}))

    slot_size = _CARD + 24
    width = _PAD * 2 + _COLS * slot_size + (_COLS - 1) * _GAP
    height = _PAD * 2 + _ROWS * slot_size + (_ROWS - 1) * _GAP
    canvas = _gradient_bg(width, height).convert("RGBA")

    async with aiohttp.ClientSession() as session:
        arts: list[Image.Image] = []
        for card in slots:
            url = str(card.get("icon") or "")
            img = await _fetch_icon(session, url) if url else None
            if img is None:
                img = _placeholder(_CARD, card.get("name") or "?")
            arts.append(_fit_card(img, _CARD))

    for idx, card in enumerate(slots):
        col = idx % _COLS
        row = idx // _COLS
        x = _PAD + col * (slot_size + _GAP)
        y = _PAD + row * (slot_size + _GAP)
        slot = _compose_slot(arts[idx], card)
        canvas.alpha_composite(slot, dest=(x, y))

    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()

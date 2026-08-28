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
_ASSETS = Path(__file__).resolve().parents[1] / "assets"
_BG_PATH = _ASSETS / "digest_bg.png"
_TITLE_FONT_PATH = _ASSETS / "Supercell-Magic.ttf"

# Clean digest_bg.png (894×678): gold frame OUTERS are 165×208.
# Inner content rects — cards are contained+centered here (no stretch, no overflow).
_SLOT_INNERS: list[tuple[int, int, int, int]] = [
    (68, 168, 159, 202),
    (268, 168, 159, 202),
    (467, 168, 159, 202),
    (667, 168, 159, 202),
    (68, 422, 159, 202),
    (268, 422, 159, 202),
    (467, 422, 159, 202),
    (667, 422, 159, 202),
]

# Elixir drop anchor (top-left) on each slot — overlaps frame corner like the reference.
_DROP_ORIGINS: list[tuple[int, int]] = [
    (58, 155),
    (258, 155),
    (457, 155),
    (657, 155),
    (58, 409),
    (258, 409),
    (457, 409),
    (657, 409),
]

_TITLE = "ЛУЧШАЯ КОЛОДА НЕДЕЛИ"
# #d3a92c
_TITLE_FILL = (211, 169, 44, 255)
_TITLE_OUTLINE = (18, 28, 70, 255)
_ELIXIR_PINK = (224, 64, 251)
_EVO_BADGE = (232, 121, 249, 255)
_EVO_BADGE_DARK = (126, 34, 206, 255)
_HERO_BADGE = (253, 230, 138, 255)
_HERO_BADGE_DARK = (217, 119, 6, 255)


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


def _title_font(size: int) -> ImageFont.ImageFont:
    if _TITLE_FONT_PATH.exists():
        try:
            return ImageFont.truetype(str(_TITLE_FONT_PATH), size=size)
        except OSError:
            pass
    return _font(size)


def _elixir_font(size: int) -> ImageFont.ImageFont:
    # Bundled font first — Railway/Linux often has no arial/dejavu (load_default = tiny digits).
    if _TITLE_FONT_PATH.exists():
        try:
            return ImageFont.truetype(str(_TITLE_FONT_PATH), size=size)
        except OSError:
            pass
    for name in (
        "C:/Windows/Fonts/ariblk.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return _font(size)


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
    if out["is_hero"]:
        out["evolution_level"] = 0
    _refresh_card_icon(out)
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


def _placeholder(width: int, height: int, name: str) -> Image.Image:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    label = (name or "?")[:2].upper()
    font = _font(max(18, min(width, height) // 5))
    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((width - tw) / 2, (height - th) / 2 - 2), label, fill=(220, 230, 255, 220), font=font)
    return img


def _opaque_bbox(src: Image.Image) -> tuple[int, int, int, int] | None:
    return src.getchannel("A").getbbox()


def _fit_card_contain(src: Image.Image, width: int, height: int) -> Image.Image:
    """Fit card icon inside the slot, keep aspect ratio, center — never stretch/crop.

    Slight inset so the card's own frame stays inside the gold BG rim.
    """
    img = src.convert("RGBA")
    bbox = _opaque_bbox(img)
    if bbox:
        img = img.crop(bbox)
    if img.width <= 0 or img.height <= 0:
        return Image.new("RGBA", (width, height), (0, 0, 0, 0))

    # Leave room so gold frame of the background stays fully visible
    pad = 10
    inner_w = max(1, width - pad * 2)
    inner_h = max(1, height - pad * 2)
    scale = min(inner_w / img.width, inner_h / img.height)
    nw = max(1, int(round(img.width * scale)))
    nh = max(1, int(round(img.height * scale)))
    resized = img.resize((nw, nh), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ox = (width - nw) // 2
    oy = (height - nh) // 2
    canvas.alpha_composite(resized, dest=(ox, oy))
    return canvas


def _drop_mask(w: int, h: int) -> Image.Image:
    """Solid pink drop (webapp ElixirIcon path), supersampled — no tip artifacts."""
    scale = 8
    sw, sh = w * scale, h * scale
    sx, sy = sw / 20.0, sh / 24.0
    big = Image.new("L", (sw, sh), 0)
    draw = ImageDraw.Draw(big)
    cx, cy, r = 10 * sx, 12.2 * sy, 5.8 * sx
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    tip_y = 1.55 * sy
    tip_w = 0.7 * sx
    draw.polygon(
        [
            (cx - tip_w, tip_y),
            (cx + tip_w, tip_y),
            (15.5 * sx, 10.6 * sy),
            (4.5 * sx, 10.6 * sy),
        ],
        fill=255,
    )
    return big.resize((w, h), Image.Resampling.LANCZOS)


def _draw_elixir_drop_at(canvas: Image.Image, origin: tuple[int, int], elixir: int) -> None:
    """Pink drop + centered white cost over the slot corner."""
    if elixir <= 0:
        return
    drop_w, drop_h = 52, 62
    mask = _drop_mask(drop_w, drop_h)
    pad = 3
    layer = Image.new("RGBA", (drop_w + pad * 2, drop_h + pad * 2), (0, 0, 0, 0))

    shadow_mask = Image.new("L", layer.size, 0)
    shadow_mask.paste(mask, (pad + 2, pad + 3))
    shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(radius=2.0))
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 90), (0, 0), shadow_mask)
    layer.alpha_composite(shadow)

    fill = Image.new("RGBA", (drop_w, drop_h), (*_ELIXIR_PINK, 255))
    body = Image.new("RGBA", (drop_w, drop_h), (0, 0, 0, 0))
    body.paste(fill, (0, 0), mask)
    layer.alpha_composite(body, dest=(pad, pad))

    font = _elixir_font(40)
    num = str(elixir)
    draw = ImageDraw.Draw(layer)
    cx = pad + drop_w / 2
    cy = pad + drop_h * (12.2 / 24.0) - 1.0
    tb = draw.textbbox((0, 0), num, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    tx = cx - tw / 2 - tb[0]
    ty = cy - th / 2 - tb[1]
    for ox, oy, a in ((0, 1, 140), (0, 2, 60)):
        draw.text((tx + ox, ty + oy), num, font=font, fill=(0, 0, 0, a))
    draw.text((tx, ty), num, font=font, fill=(255, 255, 255, 255))

    ox, oy = origin
    canvas.alpha_composite(layer, dest=(ox - pad, oy - pad))


def _draw_title(canvas: Image.Image) -> None:
    """Draw title with uniform letter height (Supercell Magic Cyrillic is uneven)."""
    text = _TITLE.upper()
    font = _title_font(46)
    # Reference cap-height from a "clean" letter (А) — scale outliers like Д to match
    ref = font.getbbox("А")
    target_h = max(1, ref[3] - ref[1])
    space_w = max(12, int(round(font.getlength(" ") or 14)))

    glyphs: list[Image.Image | None] = []
    widths: list[int] = []
    for ch in text:
        if ch == " ":
            glyphs.append(None)
            widths.append(space_w)
            continue
        bbox = font.getbbox(ch)
        gw = max(1, bbox[2] - bbox[0])
        gh = max(1, bbox[3] - bbox[1])
        gimg = Image.new("RGBA", (gw, gh), (0, 0, 0, 0))
        ImageDraw.Draw(gimg).text((-bbox[0], -bbox[1]), ch, font=font, fill=(255, 255, 255, 255))
        if gh != target_h:
            nw = max(1, int(round(gw * (target_h / gh))))
            gimg = gimg.resize((nw, target_h), Image.Resampling.LANCZOS)
        glyphs.append(gimg)
        widths.append(gimg.width)

    gap = 1
    total_w = sum(widths) + gap * max(0, len(widths) - 1)
    total_h = target_h
    # Outline padding
    pad = 4
    layer = Image.new("RGBA", (total_w + pad * 2, total_h + pad * 2), (0, 0, 0, 0))

    def _blit_colored(color: tuple[int, int, int, int], dx: int, dy: int) -> None:
        x = pad + dx
        for g, w in zip(glyphs, widths):
            if g is None:
                x += w + gap
                continue
            tinted = Image.new("RGBA", g.size, color)
            tinted.putalpha(g.getchannel("A"))
            layer.alpha_composite(tinted, dest=(x, pad + dy))
            x += w + gap

    for ox in range(-3, 4):
        for oy in range(-3, 4):
            if ox * ox + oy * oy <= 10:
                _blit_colored(_TITLE_OUTLINE, ox, oy)
    _blit_colored(_TITLE_FILL, 0, 0)

    cx = canvas.width / 2
    cy = 78
    dest = (int(round(cx - layer.width / 2)), int(round(cy - layer.height / 2)))
    canvas.alpha_composite(layer, dest=dest)


def _load_background() -> Image.Image:
    if not _BG_PATH.exists():
        raise FileNotFoundError(f"Digest background missing: {_BG_PATH}")
    return Image.open(_BG_PATH).convert("RGBA")


def _draw_upgrade_badge(
    canvas: Image.Image,
    slot: tuple[int, int, int, int],
    *,
    is_hero: bool,
    is_evo: bool,
) -> None:
    """Diamond badge at top-center — same signal as Mini App card-upgrade-badges."""
    if not is_hero and not is_evo:
        return
    x, y, w, h = slot
    cx = x + w // 2
    cy = y + 12
    size = 11
    # Diamond polygon (rotated square)
    pts = [
        (cx, cy - size),
        (cx + size, cy),
        (cx, cy + size),
        (cx - size, cy),
    ]
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    # Soft shadow
    shadow = [(p[0] + 1, p[1] + 2) for p in pts]
    draw.polygon(shadow, fill=(0, 0, 0, 120))
    if is_hero:
        draw.polygon(pts, fill=_HERO_BADGE_DARK)
        inset = [
            (cx, cy - size + 3),
            (cx + size - 3, cy),
            (cx, cy + size - 3),
            (cx - size + 3, cy),
        ]
        draw.polygon(inset, fill=_HERO_BADGE)
    else:
        draw.polygon(pts, fill=_EVO_BADGE_DARK)
        inset = [
            (cx, cy - size + 3),
            (cx + size - 3, cy),
            (cx, cy + size - 3),
            (cx - size + 3, cy),
        ]
        draw.polygon(inset, fill=_EVO_BADGE)
    # White rim
    draw.polygon(pts, outline=(255, 255, 255, 230))
    canvas.alpha_composite(layer)


async def render_deck_collage(cards: list[dict]) -> bytes | None:
    """Build PNG: clean BG → centered card icons → evo/hero badges → elixir → title."""
    if not cards:
        return None

    slots = [normalize_collage_card(c) for c in list(cards)[:8]]
    while len(slots) < 8:
        slots.append(normalize_collage_card({"name": ""}))

    canvas = _load_background()
    _draw_title(canvas)

    async with aiohttp.ClientSession() as session:
        arts: list[Image.Image] = []
        for idx, card in enumerate(slots):
            _, _, fw, fh = _SLOT_INNERS[idx]
            url = str(card.get("icon") or "")
            img = await _fetch_icon(session, url) if url else None
            if img is None:
                arts.append(_placeholder(fw, fh, card.get("name") or "?"))
            else:
                arts.append(_fit_card_contain(img, fw, fh))

    for idx, card in enumerate(slots):
        x, y, fw, fh = _SLOT_INNERS[idx]
        canvas.alpha_composite(arts[idx], dest=(x, y))
        is_hero = bool(card.get("is_hero"))
        is_evo = (not is_hero) and int(card.get("evolution_level") or 0) >= 1
        _draw_upgrade_badge(canvas, (x, y, fw, fh), is_hero=is_hero, is_evo=is_evo)
        name = (card.get("name") or "").strip()
        elixir = int(card.get("cost") or (get_card_elixir(name) if name else 0) or 0)
        _draw_elixir_drop_at(canvas, _DROP_ORIGINS[idx], elixir)

    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()

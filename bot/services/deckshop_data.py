"""Безопасный доступ к offline-снимку DeckShop (без HTTP в рантайме)."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_MAX_AGE_DAYS = 30
SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "data" / "deckshop_counters.py"


@dataclass(frozen=True)
class DeckshopSnapshotStatus:
    available: bool
    status: str  # ok | missing | corrupt | empty
    scraped_at: str | None
    site: str | None
    cards_count: int
    card_slugs_seen: int | None = None
    cards_parsed: int | None = None
    load_error: str | None = None
    age_days: float | None = None
    stale: bool = False
    max_age_days: int = DEFAULT_MAX_AGE_DAYS

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "status": self.status,
            "scraped_at": self.scraped_at,
            "site": self.site,
            "cards_count": self.cards_count,
            "card_slugs_seen": self.card_slugs_seen,
            "cards_parsed": self.cards_parsed,
            "load_error": self.load_error,
            "age_days": round(self.age_days, 1) if self.age_days is not None else None,
            "stale": self.stale,
            "max_age_days": self.max_age_days,
        }


def _parse_scraped_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _age_days(scraped_at: str | None) -> float | None:
    dt = _parse_scraped_at(scraped_at)
    if not dt:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0


@lru_cache(maxsize=1)
def load_deckshop_snapshot() -> tuple[dict[str, dict], dict[str, Any], DeckshopSnapshotStatus]:
    """Загрузить snapshot с диска. Никогда не бросает исключений."""
    if not SNAPSHOT_PATH.exists():
        status = DeckshopSnapshotStatus(
            available=False,
            status="missing",
            scraped_at=None,
            site=None,
            cards_count=0,
            load_error=f"file not found: {SNAPSHOT_PATH.name}",
        )
        return {}, {}, status

    try:
        spec = importlib.util.spec_from_file_location(
            "bot.data.deckshop_counters_snapshot",
            SNAPSHOT_PATH,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot create module spec")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:
        status = DeckshopSnapshotStatus(
            available=False,
            status="corrupt",
            scraped_at=None,
            site=None,
            cards_count=0,
            load_error=str(exc),
        )
        return {}, {}, status

    source = getattr(mod, "DECKSHOP_SOURCE", {}) or {}
    counters = getattr(mod, "DECKSHOP_COUNTERS", None)
    if not isinstance(source, dict):
        source = {}
    if not isinstance(counters, dict):
        status = DeckshopSnapshotStatus(
            available=False,
            status="corrupt",
            scraped_at=source.get("scraped_at"),
            site=source.get("site"),
            cards_count=0,
            load_error="DECKSHOP_COUNTERS is not a dict",
        )
        return {}, source, status

    scraped_at = source.get("scraped_at")
    age = _age_days(scraped_at)
    stale = age is not None and age > DEFAULT_MAX_AGE_DAYS
    file_status = "empty" if not counters else "ok"

    status = DeckshopSnapshotStatus(
        available=bool(counters),
        status=file_status,
        scraped_at=scraped_at,
        site=source.get("site"),
        cards_count=len(counters),
        card_slugs_seen=source.get("card_slugs_seen"),
        cards_parsed=source.get("cards_parsed"),
        age_days=age,
        stale=stale,
    )
    return counters, source, status


def check_deckshop_snapshot(*, max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> DeckshopSnapshotStatus:
    counters, source, status = load_deckshop_snapshot()
    if status.status in {"missing", "corrupt"}:
        return status

    scraped_at = source.get("scraped_at")
    age = _age_days(scraped_at)
    stale = age is not None and age > max_age_days
    file_status = "empty" if not counters else "ok"
    return DeckshopSnapshotStatus(
        available=bool(counters),
        status=file_status,
        scraped_at=scraped_at,
        site=source.get("site"),
        cards_count=len(counters),
        card_slugs_seen=source.get("card_slugs_seen"),
        cards_parsed=source.get("cards_parsed"),
        age_days=age,
        stale=stale,
        max_age_days=max_age_days,
    )


def get_deckshop_counters() -> dict[str, dict]:
    counters, _, _ = load_deckshop_snapshot()
    return counters


def get_deckshop_source() -> dict[str, Any]:
    _, source, _ = load_deckshop_snapshot()
    return dict(source)


def get_deckshop_status_summary() -> dict[str, Any]:
    return check_deckshop_snapshot().as_dict()


def format_deckshop_status(status: DeckshopSnapshotStatus | None = None) -> str:
    status = status or check_deckshop_snapshot()
    lines = ["DeckShop snapshot"]
    lines.append(f"- Status: {status.status}")
    if status.site:
        lines.append(f"- Source: {status.site}")
    if status.scraped_at:
        lines.append(f"- Updated: {status.scraped_at}")
    if status.age_days is not None:
        lines.append(f"- Age: {status.age_days:.1f} days (limit {status.max_age_days} days)")
    lines.append(f"- Cards in file: {status.cards_count}")
    if status.cards_parsed is not None:
        lines.append(f"- Parsed at build: {status.cards_parsed}")
    if status.load_error:
        lines.append(f"- Error: {status.load_error}")
    if status.stale:
        lines.append("WARN: snapshot is stale. Run: python scripts/scrape_deckshop_counters.py")
    elif status.status == "ok":
        lines.append("OK: snapshot is available.")
    elif status.status in {"missing", "corrupt", "empty"}:
        lines.append("INFO: using manual counters + card_data + role fallback.")
    return "\n".join(lines)

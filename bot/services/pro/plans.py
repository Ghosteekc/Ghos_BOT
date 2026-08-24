"""Ghosteek Pro plan catalog (server-side source of truth)."""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ProPlan:
    id: str
    title: str
    description: str
    stars: int
    months: int
    badge: str | None = None


PRO_1M = ProPlan(
    id="pro_1m",
    title="1 месяц",
    description="Ghosteek Pro на 1 месяц",
    stars=100,
    months=1,
)
PRO_3M = ProPlan(
    id="pro_3m",
    title="3 месяца",
    description="Ghosteek Pro на 3 месяца",
    stars=250,
    months=3,
    badge="Выгодно",
)
PRO_6M = ProPlan(
    id="pro_6m",
    title="6 месяцев",
    description="Ghosteek Pro на 6 месяцев",
    stars=500,
    months=6,
)

PRO_PLANS: dict[str, ProPlan] = {
    PRO_1M.id: PRO_1M,
    PRO_3M.id: PRO_3M,
    PRO_6M.id: PRO_6M,
}

PAYLOAD_PREFIX = "ghosteek_pro:"


def get_plan(plan_id: str) -> ProPlan | None:
    return PRO_PLANS.get(plan_id)


def list_plans() -> list[ProPlan]:
    return [PRO_1M, PRO_3M, PRO_6M]


def add_calendar_months(dt: datetime, months: int) -> datetime:
    """Add calendar months (not a fixed second count)."""
    if months <= 0:
        return dt
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    day = min(dt.day, monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def build_invoice_payload(*, plan_id: str, telegram_id: int, nonce: str) -> str:
    return f"{PAYLOAD_PREFIX}{plan_id}:{telegram_id}:{nonce}"


def parse_invoice_payload(payload: str) -> tuple[str, int] | None:
    """Return (plan_id, telegram_id) or None if payload is not a Pro invoice."""
    if not payload or not payload.startswith(PAYLOAD_PREFIX):
        return None
    rest = payload[len(PAYLOAD_PREFIX) :]
    parts = rest.split(":")
    if len(parts) < 2:
        return None
    plan_id, tg_raw = parts[0], parts[1]
    if plan_id not in PRO_PLANS:
        return None
    try:
        telegram_id = int(tg_raw)
    except ValueError:
        return None
    return plan_id, telegram_id

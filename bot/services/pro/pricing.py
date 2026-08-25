"""Pro purchase price quote: referral % discount then Credits (max 50%)."""

from __future__ import annotations

from dataclasses import dataclass

from bot.config import settings


@dataclass(frozen=True)
class PurchaseQuote:
    plan_id: str
    base_price: int
    discount_percent: int
    discount_stars: int
    final_price: int
    available_credits: int
    max_credits: int
    credits_to_use: int
    stars_to_pay: int


def discount_percent_config() -> int:
    raw = int(getattr(settings, "referral_discount_percent", 15) or 15)
    return max(0, min(100, raw))


def credits_max_share_percent() -> int:
    raw = int(getattr(settings, "credits_max_share_percent", 50) or 50)
    return max(1, min(50, raw))  # hard cap at 50% per product rules


def apply_percent_discount(base_price: int, percent: int) -> tuple[int, int]:
    """Return (discount_stars, final_price). Floor discount → favor project."""
    base = max(0, int(base_price))
    pct = max(0, min(100, int(percent)))
    if base <= 0 or pct <= 0:
        return 0, base
    cut = (base * pct) // 100
    final = base - cut
    # Never free from discount alone.
    if final <= 0:
        final = 1
        cut = base - 1
    return cut, final


def max_credits_for_price(final_price: int) -> int:
    """Max Credits = floor(final * share%). Always leaves at least 1★ when final >= 1."""
    final = max(0, int(final_price))
    if final <= 0:
        return 0
    share = credits_max_share_percent()
    capped = (final * share) // 100
    # Never allow stars_to_pay == 0 when paying for a positive-price plan.
    return min(capped, final - 1)


def build_purchase_quote(
    *,
    plan_id: str,
    base_price: int | None = None,
    referral_discount: bool,
    available_credits: int,
    discount_percent: int | None = None,
) -> PurchaseQuote | None:
    from bot.services.pro.plans import get_plan

    plan = get_plan(plan_id)
    if plan is None and base_price is None:
        return None
    base = int(base_price if base_price is not None else plan.stars)  # type: ignore[union-attr]
    pct = discount_percent_config() if referral_discount else 0
    if discount_percent is not None and referral_discount:
        pct = max(0, min(100, int(discount_percent)))

    cut, final = apply_percent_discount(base, pct)
    avail = max(0, int(available_credits))
    max_c = max_credits_for_price(final)
    use = min(avail, max_c)
    stars = final - use
    if stars < 1 and final >= 1:
        use = max(0, final - 1)
        stars = final - use
    if stars < 0:
        stars = 0

    return PurchaseQuote(
        plan_id=plan_id,
        base_price=base,
        discount_percent=pct if referral_discount else 0,
        discount_stars=cut if referral_discount else 0,
        final_price=final,
        available_credits=avail,
        max_credits=max_c,
        credits_to_use=use,
        stars_to_pay=stars,
    )

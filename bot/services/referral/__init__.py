"""Permanent Ghosteek Pro referral system."""

from bot.services.referral.service import (
    REFERRAL_PREFIX,
    REQUIRED_REFERRALS,
    REWARD_DAYS,
    ReferralStats,
    build_referral_link,
    parse_referral_payload,
    process_referral_conversion,
    referral_stats_for_user,
)

__all__ = [
    "REFERRAL_PREFIX",
    "REQUIRED_REFERRALS",
    "REWARD_DAYS",
    "ReferralStats",
    "build_referral_link",
    "parse_referral_payload",
    "process_referral_conversion",
    "referral_stats_for_user",
]

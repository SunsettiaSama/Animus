from __future__ import annotations

from enum import Enum


class ExpectationTier(str, Enum):
    very_low = "极低"
    low = "较低"
    medium = "中"
    high = "较高"
    very_high = "极高"


TIER_ALIASES: dict[str, ExpectationTier] = {
    "very_low": ExpectationTier.very_low,
    "low": ExpectationTier.low,
    "medium": ExpectationTier.medium,
    "high": ExpectationTier.high,
    "very_high": ExpectationTier.very_high,
    "极低": ExpectationTier.very_low,
    "较低": ExpectationTier.low,
    "中": ExpectationTier.medium,
    "较高": ExpectationTier.high,
    "极高": ExpectationTier.very_high,
}


def parse_expectation_tier(value: str | ExpectationTier | None) -> ExpectationTier | None:
    if value is None:
        return None
    if isinstance(value, ExpectationTier):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text in TIER_ALIASES:
        return TIER_ALIASES[text]
    lowered = text.lower().replace(" ", "_")
    return TIER_ALIASES.get(lowered)

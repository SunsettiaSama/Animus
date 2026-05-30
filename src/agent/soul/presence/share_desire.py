from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from config.soul.presence.config import (
    OUTBOUND_THRESHOLD_EAGER,
    OUTBOUND_THRESHOLD_MODERATE,
    share_desire_weights,
)


class ShareDesire(str, Enum):
    """Agent 对一次 Soul 演化的分享意愿（软阈值分层）。"""

    none = "none"
    mild = "mild"
    moderate = "moderate"
    eager = "eager"


SHARE_DESIRE_ORDER: dict[ShareDesire, int] = {
    ShareDesire.none: 0,
    ShareDesire.mild: 1,
    ShareDesire.moderate: 2,
    ShareDesire.eager: 3,
}


def parse_share_desire(
    value: str | ShareDesire | None,
    *,
    default: ShareDesire = ShareDesire.mild,
) -> ShareDesire:
    if value is None:
        return default
    if isinstance(value, ShareDesire):
        return value
    text = str(value).strip().lower()
    if not text:
        return default
    return ShareDesire(text)


def share_desire_weight(desire: ShareDesire) -> float:
    return share_desire_weights()[desire.value]


def max_share_desire(a: ShareDesire, b: ShareDesire) -> ShareDesire:
    if SHARE_DESIRE_ORDER[a] >= SHARE_DESIRE_ORDER[b]:
        return a
    return b


def share_desire_from_intensity(intensity: float) -> ShareDesire:
    if intensity <= 0.0:
        return ShareDesire.none
    if intensity < OUTBOUND_THRESHOLD_MODERATE:
        return ShareDesire.mild
    if intensity < OUTBOUND_THRESHOLD_EAGER:
        return ShareDesire.moderate
    return ShareDesire.eager


def share_desire_from_impulse(impulse_level: float) -> ShareDesire:
    if impulse_level >= OUTBOUND_THRESHOLD_EAGER:
        return ShareDesire.eager
    if impulse_level >= OUTBOUND_THRESHOLD_MODERATE:
        return ShareDesire.moderate
    if impulse_level >= share_desire_weight(ShareDesire.mild):
        return ShareDesire.mild
    return ShareDesire.none


@dataclass
class StaticStatePatch:
    """静态 narrative 显式写入（boundary/scan 不得使用）。"""

    affect: str | None = None
    somatic: str | None = None
    thinking: str | None = None
    perception: str | None = None

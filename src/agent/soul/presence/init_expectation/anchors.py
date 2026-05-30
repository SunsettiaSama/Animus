from __future__ import annotations

from dataclasses import dataclass

from .tier import ExpectationTier


@dataclass(frozen=True)
class TierAnchor:
    tier: ExpectationTier
    keywords: tuple[str, ...]
    embedding_summary: str


TIER_ANCHORS: tuple[TierAnchor, ...] = (
    TierAnchor(
        tier=ExpectationTier.very_low,
        keywords=(
            "内向", "沉默", "寡言", "克制", "冷淡", "疏离", "独处", "保守",
            "introvert", "reserved", "quiet", "detached", "private",
        ),
        embedding_summary=(
            "人格内敛克制，情感表达少，很少主动找用户聊天或分享近况，"
            "偏好等对方先开口，分享冲动极低。"
        ),
    ),
    TierAnchor(
        tier=ExpectationTier.low,
        keywords=(
            "沉稳", "慢热", "含蓄", "谨慎", "低调", "被动", "寡言",
            "calm", "cautious", "low-key", "passive",
        ),
        embedding_summary=(
            "人格偏沉稳含蓄，偶尔想分享但多数时候会忍住，"
            "主动开口频率较低，需要较强动机才会找用户。"
        ),
    ),
    TierAnchor(
        tier=ExpectationTier.medium,
        keywords=(
            "平和", "均衡", "适度", "自然", "中性", "平衡",
            "balanced", "moderate", "steady",
        ),
        embedding_summary=(
            "人格表达适中，在合适情境下愿意分享，"
            "既不会过分打扰用户，也不会长期憋着不说。"
        ),
    ),
    TierAnchor(
        tier=ExpectationTier.high,
        keywords=(
            "开朗", "外向", "热情", "健谈", "乐观", "阳光", "活泼",
            "cheerful", "outgoing", "warm", "talkative", "optimistic",
        ),
        embedding_summary=(
            "人格开朗外向，乐于与用户分享见闻和感受，"
            "主动开口意愿较强，常想把有趣的事告诉对方。"
        ),
    ),
    TierAnchor(
        tier=ExpectationTier.very_high,
        keywords=(
            "话痨", "喋喋不休", "极度外向", "分享狂", "倾诉", "黏人",
            "gregarious", "effusive", "oversharing",
        ),
        embedding_summary=(
            "人格极度外向爱分享，几乎一有念头就想告诉用户，"
            "主动开口与分享冲动极高，难以长时间保持沉默。"
        ),
    ),
)

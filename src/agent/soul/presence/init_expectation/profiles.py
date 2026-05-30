from __future__ import annotations

from dataclasses import dataclass

from config.soul.presence.config import PresenceConfig

from .tier import ExpectationTier


@dataclass(frozen=True)
class ExpectationTierPreset:
    """单档分享/期待阈值（硬编码，供 persona 自动选型）。"""

    tier: ExpectationTier
    proactive_open_threshold: float
    reply_urge_threshold: float
    share_desire_weight_mild: float
    share_desire_weight_moderate: float
    share_desire_weight_eager: float
    outbound_threshold_moderate: float
    outbound_threshold_eager: float
    reply_urge_mild: float
    reply_urge_moderate: float
    reply_urge_eager: float

    def apply_to(self, base: PresenceConfig) -> PresenceConfig:
        return PresenceConfig(
            wake_at=base.wake_at,
            dialogue_working_memory_window_sec=base.dialogue_working_memory_window_sec,
            dialogue_working_memory_max_chunks=base.dialogue_working_memory_max_chunks,
            dialogue_fsm_refresh_every_k=base.dialogue_fsm_refresh_every_k,
            share_desire_weight_mild=self.share_desire_weight_mild,
            share_desire_weight_moderate=self.share_desire_weight_moderate,
            share_desire_weight_eager=self.share_desire_weight_eager,
            outbound_threshold_moderate=self.outbound_threshold_moderate,
            outbound_threshold_eager=self.outbound_threshold_eager,
            proactive_open_threshold=self.proactive_open_threshold,
            reply_urge_threshold=self.reply_urge_threshold,
            reply_urge_mild=self.reply_urge_mild,
            reply_urge_moderate=self.reply_urge_moderate,
            reply_urge_eager=self.reply_urge_eager,
            share_intent_queue_max_items=base.share_intent_queue_max_items,
            experience_memory_ingest_threshold=base.experience_memory_ingest_threshold,
            experience_hot_window_hours=base.experience_hot_window_hours,
            experience_collision_scan_limit=base.experience_collision_scan_limit,
            experience_collision_window_min=base.experience_collision_window_min,
        )


EXPECTATION_TIER_PRESETS: dict[ExpectationTier, ExpectationTierPreset] = {
    ExpectationTier.very_low: ExpectationTierPreset(
        tier=ExpectationTier.very_low,
        proactive_open_threshold=0.88,
        reply_urge_threshold=0.55,
        share_desire_weight_mild=0.06,
        share_desire_weight_moderate=0.12,
        share_desire_weight_eager=0.28,
        outbound_threshold_moderate=0.55,
        outbound_threshold_eager=0.82,
        reply_urge_mild=0.06,
        reply_urge_moderate=0.14,
        reply_urge_eager=0.28,
    ),
    ExpectationTier.low: ExpectationTierPreset(
        tier=ExpectationTier.low,
        proactive_open_threshold=0.78,
        reply_urge_threshold=0.45,
        share_desire_weight_mild=0.10,
        share_desire_weight_moderate=0.22,
        share_desire_weight_eager=0.45,
        outbound_threshold_moderate=0.42,
        outbound_threshold_eager=0.72,
        reply_urge_mild=0.08,
        reply_urge_moderate=0.18,
        reply_urge_eager=0.38,
    ),
    ExpectationTier.medium: ExpectationTierPreset(
        tier=ExpectationTier.medium,
        proactive_open_threshold=0.65,
        reply_urge_threshold=0.35,
        share_desire_weight_mild=0.15,
        share_desire_weight_moderate=0.35,
        share_desire_weight_eager=0.65,
        outbound_threshold_moderate=0.35,
        outbound_threshold_eager=0.65,
        reply_urge_mild=0.10,
        reply_urge_moderate=0.25,
        reply_urge_eager=0.45,
    ),
    ExpectationTier.high: ExpectationTierPreset(
        tier=ExpectationTier.high,
        proactive_open_threshold=0.40,
        reply_urge_threshold=0.28,
        share_desire_weight_mild=0.20,
        share_desire_weight_moderate=0.44,
        share_desire_weight_eager=0.58,
        outbound_threshold_moderate=0.28,
        outbound_threshold_eager=0.55,
        reply_urge_mild=0.12,
        reply_urge_moderate=0.22,
        reply_urge_eager=0.38,
    ),
    ExpectationTier.very_high: ExpectationTierPreset(
        tier=ExpectationTier.very_high,
        proactive_open_threshold=0.32,
        reply_urge_threshold=0.20,
        share_desire_weight_mild=0.22,
        share_desire_weight_moderate=0.48,
        share_desire_weight_eager=0.52,
        outbound_threshold_moderate=0.22,
        outbound_threshold_eager=0.48,
        reply_urge_mild=0.14,
        reply_urge_moderate=0.20,
        reply_urge_eager=0.32,
    ),
}


def preset_for(tier: ExpectationTier) -> ExpectationTierPreset:
    return EXPECTATION_TIER_PRESETS[tier]

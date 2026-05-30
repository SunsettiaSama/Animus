from __future__ import annotations

from typing import Any

from config.soul.presence.config import PresenceConfig, reload_presence_config

from .profiles import preset_for
from .resolver import EmbedderPort, TierResolveResult, resolve_expectation_tier
from .tier import ExpectationTier, parse_expectation_tier


def _rebind_presence_constant_aliases(cfg: PresenceConfig) -> None:
    """reload 后同步已 import 的模块级别名（避免旧阈值滞留）。"""
    import agent.soul.presence.state.dynamic as dynamic_pkg
    import agent.soul.presence.state.dynamic.expectation as expectation_pkg
    import agent.soul.presence.state as state_pkg

    for module in (expectation_pkg, dynamic_pkg, state_pkg):
        module.PROACTIVE_OPEN_THRESHOLD = cfg.proactive_open_threshold
        module.REPLY_URGE_THRESHOLD = cfg.reply_urge_threshold


def apply_expectation_tier(
    tier: ExpectationTier,
    *,
    base: PresenceConfig | None = None,
) -> PresenceConfig:
    root = base or PresenceConfig.default()
    cfg = preset_for(tier).apply_to(root)
    reload_presence_config(cfg)
    _rebind_presence_constant_aliases(cfg)
    return cfg


def sync_presence_expectation_from_persona(
    persona_snapshot: dict[str, Any],
    *,
    embedder: EmbedderPort | None = None,
    tier_override: str | ExpectationTier | None = None,
    base: PresenceConfig | None = None,
) -> dict[str, Any]:
    """根据 persona 快照选型并热更新 presence 模块级阈值（用户无感知）。"""
    resolved = resolve_expectation_tier(
        persona_snapshot,
        embedder=embedder,
        override=tier_override,
    )
    cfg = apply_expectation_tier(resolved.tier, base=base)
    return {
        "tier": resolved.tier.value,
        "proactive_open_threshold": cfg.proactive_open_threshold,
        "reply_urge_threshold": cfg.reply_urge_threshold,
        "share_weights": {
            "mild": cfg.share_desire_weight_mild,
            "moderate": cfg.share_desire_weight_moderate,
            "eager": cfg.share_desire_weight_eager,
        },
        "resolve": {
            "keyword_scores": resolved.keyword_scores,
            "embedding_scores": resolved.embedding_scores,
            "combined_scores": resolved.combined_scores,
            "notes": list(resolved.notes),
        },
    }


def parse_tier_label(value: str | None) -> ExpectationTier | None:
    return parse_expectation_tier(value)

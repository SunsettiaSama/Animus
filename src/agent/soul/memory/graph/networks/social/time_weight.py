from __future__ import annotations

import math
from datetime import datetime, timezone

from agent.soul.memory.graph.base_node import BaseNode
from agent.soul.memory.graph.networks.social.node import SocialCoreNode


def event_time_weight(
    unit: BaseNode,
    now: datetime,
    *,
    half_life_days: float = 60.0,
) -> float:
    """事件发生时间距现在越远，权重越低；核心画像节点不衰减。"""
    if isinstance(unit, SocialCoreNode):
        return 1.0
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    anchor = unit.created_at
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    delta_days = max((now - anchor).total_seconds() / 86400.0, 0.0)
    hl = max(half_life_days, 0.1)
    return math.exp(-math.log(2) / hl * delta_days)

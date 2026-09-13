"""剧情材料新鲜度策略（纯逻辑，零依赖）。

双维过期：
- 墙钟维：距生成时间的秒龄；
- 剧情维：预载后的剧情推进量（往来轮次增量）。

两种材料的判级语义不同：
- 池内候选（opening 候选大纲）：fresh → 可直接注入；expired → 丢弃；
- 活体快照（重启前的进行中剧情）：fresh → 可恢复；expired → 弃用
  （等价于跨重启延续 30 分钟闲置休眠语义）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

FreshnessLevel = Literal["fresh", "expired"]

# 池内候选默认保鲜期：1 天（用户提案值）
DEFAULT_POOL_ENTRY_TTL_SEC = 86_400.0
# 活体快照默认保鲜期：与 SPEAK_IDLE_DORMANT_SEC 对齐（30 分钟闲置即休眠重init）
DEFAULT_LIVE_SNAPSHOT_TTL_SEC = 1_800.0


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class FreshnessPolicy:
    """单一 TTL 维判级；剧情推进维由调用方折算进 `age_sec` 之前决定是否调用。"""

    max_age_sec: float = DEFAULT_POOL_ENTRY_TTL_SEC

    def classify(self, *, created_at: float, now: float) -> FreshnessLevel:
        """created_at <= 0 视为无时间戳：保守判过期。"""
        if created_at <= 0 or now < created_at:
            return "expired"
        return "fresh" if (now - created_at) <= self.max_age_sec else "expired"


def pool_entry_policy() -> FreshnessPolicy:
    return FreshnessPolicy(
        max_age_sec=_env_float(
            "REACT_STORY_POOL_TTL_SEC", DEFAULT_POOL_ENTRY_TTL_SEC
        )
    )


def live_snapshot_policy() -> FreshnessPolicy:
    return FreshnessPolicy(
        max_age_sec=_env_float(
            "REACT_STORY_LIVE_TTL_SEC", DEFAULT_LIVE_SNAPSHOT_TTL_SEC
        )
    )

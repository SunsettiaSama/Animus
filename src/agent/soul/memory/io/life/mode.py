from __future__ import annotations

from enum import Enum


class MemoryIngestMode(str, Enum):
    """Life → Memory 写入模式（快速内化后仅保留 formal）。"""

    formal = "formal"
    """路由 → 候选 → Agent 选父节点 → 持久落图（ExperienceGraphIngest）。"""

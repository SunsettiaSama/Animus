from __future__ import annotations

import math
import uuid
from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import ClassVar

from agent.soul.memory.domain.enums import MemoryNetwork, MemoryTier, Valence
from agent.soul.memory.emotion_intensity import node_emotion_intensity


def node_now() -> datetime:
    return datetime.now(timezone.utc)


def node_uid() -> str:
    return str(uuid.uuid4())


@dataclass(kw_only=True)
class BaseNode(ABC):
    """记忆图节点基类：event / social 具体类型在各自子模块定义。"""

    NODE_KIND: ClassVar[str]

    focus: str
    emotion: str = ""
    emotion_intensity: float = 0.0
    valence: Valence = Valence.neutral
    tier: MemoryTier = MemoryTier.short_term
    base_activation: float = 0.5
    recall_count: int = 0
    rehearsal_count: int = 0
    narrative_ref_count: int = 0
    last_accessed: datetime = field(default_factory=node_now)
    created_at: datetime = field(default_factory=node_now)
    meta: dict = field(default_factory=dict)
    id: str = field(default_factory=node_uid)
    network: MemoryNetwork = MemoryNetwork.event
    interactor_id: str = ""

    @property
    def MEMORY_TYPE(self) -> str:
        return self.NODE_KIND

    def activation(
        self,
        now: datetime | None = None,
        half_life_days: float = 7.0,
    ) -> float:
        if now is None:
            now = node_now()
        delta = (now - self.last_accessed).total_seconds() / 86400.0
        decay = math.exp(-math.log(2) / half_life_days * max(delta, 0.0))
        boost_recall = math.log1p(self.recall_count)
        boost_emotion = node_emotion_intensity(self) * 0.5
        return min(1.0, self.base_activation * decay + boost_recall + boost_emotion)

    def on_recall(self) -> None:
        self.recall_count += 1
        self.last_accessed = node_now()

    def on_rehearsal(self) -> None:
        self.rehearsal_count += 1
        self.last_accessed = node_now()

    def promote_to_long(self) -> None:
        self.tier = MemoryTier.long

    def embed_text(self) -> str:
        chunks = [self.focus]
        for attr in (
            "fact",
            "perception",
            "reconstructed_fact",
            "narrative",
            "core_traits",
            "content",
        ):
            val = getattr(self, attr, "")
            if val:
                chunks.append(str(val))
        return " ".join(chunks)


MemoryUnit = BaseNode

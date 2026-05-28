from __future__ import annotations

import math
import uuid
from abc import ABC
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import ClassVar

from .enums import MemoryNetwork, MemoryTier, SocialNodeRole, Valence


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return str(uuid.uuid4())


@dataclass(kw_only=True)
class GraphNode(ABC):
    """记忆图节点抽象基类。"""

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
    last_accessed: datetime = field(default_factory=_now)
    created_at: datetime = field(default_factory=_now)
    meta: dict = field(default_factory=dict)
    id: str = field(default_factory=_uid)
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
            now = _now()
        delta = (now - self.last_accessed).total_seconds() / 86400.0
        decay = math.exp(-math.log(2) / half_life_days * max(delta, 0.0))
        boost_recall = math.log1p(self.recall_count)
        boost_emotion = self.emotion_intensity * 0.5
        return min(1.0, self.base_activation * decay + boost_recall + boost_emotion)

    def on_recall(self) -> None:
        self.recall_count += 1
        self.last_accessed = _now()

    def on_rehearsal(self) -> None:
        self.rehearsal_count += 1
        self.last_accessed = _now()

    def promote_to_long(self) -> None:
        self.tier = MemoryTier.long

    def embed_text(self) -> str:
        chunks = [self.focus]
        for attr in ("fact", "perception", "reconstructed_fact", "narrative", "core_traits", "content"):
            val = getattr(self, attr, "")
            if val:
                chunks.append(str(val))
        return " ".join(chunks)


# ── Event network nodes ───────────────────────────────────────────────────────

@dataclass(kw_only=True)
class FactualMemory(GraphNode):
    NODE_KIND = "factual"

    fact: str = ""
    perception: str = ""
    life_event_id: str = ""

    def __post_init__(self) -> None:
        self.network = MemoryNetwork.event


@dataclass(kw_only=True)
class ReconstructiveMemory(GraphNode):
    NODE_KIND = "reconstructive"

    source_id: str = ""
    reconstructed_fact: str = ""
    trigger: str = ""

    def __post_init__(self) -> None:
        self.network = MemoryNetwork.event


@dataclass(kw_only=True)
class NarrativeMemory(GraphNode):
    NODE_KIND = "narrative"

    narrative: str = ""
    source_ids: list[str] = field(default_factory=list)
    chapter: str = ""

    def __post_init__(self) -> None:
        self.network = MemoryNetwork.event
        self.tier = MemoryTier.long


EventNode = FactualMemory | ReconstructiveMemory | NarrativeMemory


# ── Social network nodes ──────────────────────────────────────────────────────

@dataclass(kw_only=True)
class SocialCoreNode(GraphNode):
    NODE_KIND = "social_core"

    core_traits: str = ""
    trait_version: int = 1
    last_evolved_at: datetime = field(default_factory=_now)
    node_role: SocialNodeRole = SocialNodeRole.core

    def __post_init__(self) -> None:
        self.network = MemoryNetwork.social
        self.node_role = SocialNodeRole.core
        self.tier = MemoryTier.long


@dataclass(kw_only=True)
class SocialNeighborhoodNode(GraphNode):
    NODE_KIND = "social_neighborhood"

    label: str = ""
    content: str = ""
    node_role: SocialNodeRole = SocialNodeRole.neighborhood

    def __post_init__(self) -> None:
        self.network = MemoryNetwork.social
        self.node_role = SocialNodeRole.neighborhood


SocialNode = SocialCoreNode | SocialNeighborhoodNode

# Backward-compatible alias
MemoryUnit = GraphNode

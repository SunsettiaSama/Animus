from __future__ import annotations

from dataclasses import dataclass, field

from agent.soul.memory.domain.enums import MemoryNetwork, MemoryTier
from agent.soul.memory.graph.base_node import BaseNode


@dataclass(kw_only=True)
class FactualMemory(BaseNode):
    NODE_KIND = "factual"

    fact: str = ""
    perception: str = ""
    life_event_id: str = ""

    def __post_init__(self) -> None:
        self.network = MemoryNetwork.event


@dataclass(kw_only=True)
class ReconstructiveMemory(BaseNode):
    NODE_KIND = "reconstructive"

    source_id: str = ""
    reconstructed_fact: str = ""
    trigger: str = ""

    def __post_init__(self) -> None:
        self.network = MemoryNetwork.event


@dataclass(kw_only=True)
class NarrativeMemory(BaseNode):
    NODE_KIND = "narrative"

    narrative: str = ""
    source_ids: list[str] = field(default_factory=list)
    chapter: str = ""

    def __post_init__(self) -> None:
        self.network = MemoryNetwork.event
        self.tier = MemoryTier.long


EventNode = FactualMemory | ReconstructiveMemory | NarrativeMemory

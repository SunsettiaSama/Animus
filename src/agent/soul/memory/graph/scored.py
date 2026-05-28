from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from agent.soul.memory.domain import GraphNode, MemoryTier, Valence


@dataclass
class ScoredUnit:
    unit: GraphNode
    relevance: float = 1.0
    activation: float = 0.0
    final_score: float = 0.0
    source: str = "memory"

    def render_line(self, max_content: int = 80) -> str:
        line = f"[{self.unit.MEMORY_TYPE}] {self.unit.focus}"
        for attr in ("fact", "reconstructed_fact", "narrative", "core_traits", "content"):
            val = getattr(self.unit, attr, "")
            if val:
                line += f"：{str(val)[:max_content]}"
                break
        return line

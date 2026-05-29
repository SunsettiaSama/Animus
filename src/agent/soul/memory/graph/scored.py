from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from agent.soul.memory.domain import MemoryTier, Valence
from agent.soul.memory.graph.base_node import BaseNode


@dataclass
class ScoredUnit:
    unit: BaseNode
    relevance: float = 1.0
    activation: float = 0.0
    final_score: float = 0.0
    source: str = "memory"

    def render_line(self, max_content: int = 80) -> str:
        line = f"[{self.unit.MEMORY_TYPE}] {self.unit.focus}"
        for attr in (
            "fact",
            "reconstructed_fact",
            "narrative",
            "content",
            "agent_relation",
            "trait_changelog",
        ):
            val = getattr(self.unit, attr, "")
            if val:
                line += f"：{str(val)[:max_content]}"
                break
        if "：" not in line and hasattr(self.unit, "portrait"):
            portrait = getattr(self.unit, "portrait", None)
            if portrait is not None:
                rendered = portrait.render().strip()
                if rendered:
                    line += f"：{rendered[:max_content]}"
        if "：" not in line:
            label = getattr(self.unit, "label", "")
            if label:
                line += f"：{str(label)[:max_content]}"
        return line

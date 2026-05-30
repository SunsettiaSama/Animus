from __future__ import annotations

from dataclasses import dataclass, field

from agent.soul.memory.domain import ActivatedNode
from agent.soul.memory.emergence.line_dedup import dedupe_memory_line_pairs


@dataclass
class HotEmergenceResult:
    session_id: str
    interactor_id: str
    unit_ids: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    activated: list[ActivatedNode] = field(default_factory=list)
    cue_hash: str = ""


@dataclass
class PointEmergenceResult:
    session_id: str
    interactor_id: str
    turn_index: int = 0
    precise_lines: list[str] = field(default_factory=list)
    precise_unit_ids: list[str] = field(default_factory=list)
    associative_lines: list[str] = field(default_factory=list)
    associative_unit_ids: list[str] = field(default_factory=list)
    associative_ready: bool = False
    cue_hash: str = ""

    def _merged_pairs(self) -> tuple[list[str], list[str]]:
        lines = list(self.precise_lines) + list(self.associative_lines)
        unit_ids = list(self.precise_unit_ids) + list(self.associative_unit_ids)
        return dedupe_memory_line_pairs(lines, unit_ids)

    def merged_lines(self) -> list[str]:
        lines, _ = self._merged_pairs()
        return lines

    def merged_unit_ids(self) -> list[str]:
        _, unit_ids = self._merged_pairs()
        return unit_ids

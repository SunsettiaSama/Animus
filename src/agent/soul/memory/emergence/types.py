from __future__ import annotations

from dataclasses import dataclass, field

from agent.soul.memory.domain import ActivatedNode


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

    def merged_lines(self) -> list[str]:
        return list(self.precise_lines) + list(self.associative_lines)

    def merged_unit_ids(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for uid in self.precise_unit_ids + self.associative_unit_ids:
            if uid in seen:
                continue
            seen.add(uid)
            out.append(uid)
        return out

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CrewResult:
    agent_id: str
    status: str = "running"   # "running" | "done" | "failed" | "timeout" | "not_found"
    answer: str = ""
    error: str = ""
    log: list[str] = field(default_factory=list)

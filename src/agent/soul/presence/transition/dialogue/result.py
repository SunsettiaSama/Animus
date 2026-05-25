from __future__ import annotations

from dataclasses import dataclass, field

from agent.soul.presence.transition.expectation import Expectation


@dataclass
class DialogueRefreshResult:
    session_id: str
    applied: bool
    source: str = "fallback"
    narratives: dict[str, str] = field(default_factory=dict)
    reason: str = ""
    dialogue_expectation: Expectation | None = None


@dataclass
class DialogueObserveResult:
    session_id: str
    counted: bool
    block_count: int = 0
    refreshed: bool = False
    refresh: DialogueRefreshResult | None = None
    notes: list[str] = field(default_factory=list)

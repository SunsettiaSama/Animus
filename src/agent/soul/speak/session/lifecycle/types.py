from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol


SessionOpenTrigger = Literal["user_message", "proactive_outbound"]
SessionEndReason = Literal["temporal_idle", "semantic_shift", "manual"]


@dataclass
class SessionOpenResult:
    session_id: str
    generation: int
    trigger: SessionOpenTrigger = "user_message"
    woke: bool = False
    temporal_rotated: bool = False
    started: bool = False
    proactive_opened: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class SessionEndResult:
    session_id: str
    reason: SessionEndReason
    generation: int
    ingested: bool = False
    experience_id: str = ""
    turn_index: int = 0
    source: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class TurnRecordResult:
    recorded: bool = False
    exchange_id: str = ""
    notes: list[str] = field(default_factory=list)
    ended: SessionEndResult | None = None


class SessionLifecyclePort(Protocol):
    def close_dialogue_interaction(self, session_id: str) -> dict: ...

    def start_dialogue_session(
        self,
        session_id: str,
        *,
        trigger: SessionOpenTrigger = "user_message",
    ) -> dict: ...

    def open_proactive_outbound(
        self,
        session_id: str,
        message: str,
        *,
        proactive_intent_id: str = "",
    ) -> dict: ...

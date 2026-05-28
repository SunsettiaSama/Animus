from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .enums import MemoryNetwork


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ActivationCue:
    session_id: str
    interactor_id: str
    user_text: str
    agent_text: str = ""
    networks: tuple[MemoryNetwork, ...] = (MemoryNetwork.social, MemoryNetwork.event)


@dataclass(frozen=True)
class ActivatedNode:
    unit_id: str
    network: MemoryNetwork
    score: float
    hop: int


@dataclass
class ActivationSnapshot:
    session_id: str
    interactor_id: str
    nodes: list[ActivatedNode] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now)
    cue_hash: str = ""

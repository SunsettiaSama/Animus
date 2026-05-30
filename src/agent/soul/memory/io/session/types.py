from __future__ import annotations

from dataclasses import dataclass, field

from agent.soul.memory.graph.node.create.compression import DialogueCompressionBlock


@dataclass
class SessionBlockRecord:
    block_index: int
    node_id: str
    edge_id: str
    anchor_node_id: str
    summary: str
    emotion_label: str = ""
    salience: float = 0.5
    network: str = "social"


@dataclass
class SessionBufferState:
    session_id: str
    interactor_id: str
    blocks: list[SessionBlockRecord] = field(default_factory=list)


__all__ = [
    "DialogueCompressionBlock",
    "SessionBlockRecord",
    "SessionBufferState",
]

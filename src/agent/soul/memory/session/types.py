from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DialogueCompressionBlock:
    """Speak 上下文压缩产出的一轮粗粒度体验块。"""

    session_id: str
    block_index: int
    summary: str
    emotion_label: str = ""
    valence: str = "neutral"
    salience: float = 0.5
    valence_delta: float = 0.0
    arousal_delta: float = 0.0
    transcript: str = ""


@dataclass
class SessionBlockRecord:
    block_index: int
    node_id: str
    edge_id: str
    anchor_node_id: str
    summary: str
    emotion_label: str = ""
    salience: float = 0.5


@dataclass
class SessionBufferState:
    session_id: str
    interactor_id: str
    blocks: list[SessionBlockRecord] = field(default_factory=list)

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InteractionTurn:
    """会话内单轮快照（账本粒度，不等于最终体验单元）。"""

    turn_index: int
    user_text: str
    agent_reply: str
    salience: float = 0.3
    emotion_label: str = ""
    valence_delta: float = 0.0
    arousal_delta: float = 0.0
    activated_memory_ids: list[str] = field(default_factory=list)
    experience_id: str = ""
    early_ingested: bool = False

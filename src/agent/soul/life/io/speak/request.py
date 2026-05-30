from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SessionOpenTrigger = Literal["user_message", "proactive_outbound"]


@dataclass(frozen=True)
class DialogueTurnInbound:
    """Speak → Life：一轮对话写入体验管线（含 presence 同步）。"""

    session_id: str
    user_text: str
    agent_text: str
    salience: float = 0.3
    salience_note: str = ""
    emotion_label: str = ""
    valence_delta: float = 0.0
    arousal_delta: float = 0.0
    activated_memory_ids: tuple[str, ...] = ()
    proactive_intent_id: str = ""


@dataclass(frozen=True)
class TouchDialogueInbound:
    """Speak 会话活跃时刷新 Life 侧 dialogue state 时间戳。"""

    session_id: str


@dataclass(frozen=True)
class DialogueSessionOpenInbound:
    """Speak lifecycle：打开 dialogue 体验会话。"""

    session_id: str
    trigger: SessionOpenTrigger = "user_message"


@dataclass(frozen=True)
class ProactiveOutboundInbound:
    """Speak lifecycle：标记主动 outbound，期待用户回复。"""

    session_id: str
    message: str
    proactive_intent_id: str = ""


@dataclass(frozen=True)
class DialogueSessionCloseInbound:
    """Speak lifecycle：闭合对话并尝试生成 ExperienceUnit。"""

    session_id: str


@dataclass
class DialogueSessionOpenAck:
    ok: bool = True
    session_id: str = ""
    trigger: str = "user_message"
    turn_count: int = 0


@dataclass
class DialogueSessionCloseAck:
    ok: bool = True
    session_id: str = ""
    ingested: bool = False
    source: str = ""
    turn_index: int = 0
    experience_id: str = ""
    notes: list[str] = field(default_factory=list)

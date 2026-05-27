from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Literal

SpeakTurnMode = Literal["inbound", "proactive"]
SpeakPushPhase = Literal["idle", "pushing"]


@dataclass
class InterruptContext:
    """用户插队上下文：供 compose / LLM 判断如何处理已暂停队列。"""

    new_user_text: str
    previous_user_text: str = ""
    partial_agent_output: str = ""
    suspended_compose_count: int = 0
    suspended_compose_summary: str = ""
    dialogue_compressed: str = ""
    queue_decision_maintain: bool | None = None
    queue_decision_thought: str = ""
    queue_decision_reorder: tuple[int, ...] | None = None


@dataclass
class SubmitUserInputResult:
    queued: bool = False
    interrupt: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class SessionRuntime:
    session_id: str
    phase: SpeakPushPhase = "idle"
    active_user_text: str = ""
    partial_agent_output: str = ""
    interrupt: InterruptContext | None = None
    suspended_compose: list[Any] = field(default_factory=list)
    queue_decision_pending: bool = False
    queue_decision_token: int = 0
    queue_decision: Any | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    queue_decision_event: threading.Event = field(default_factory=threading.Event)

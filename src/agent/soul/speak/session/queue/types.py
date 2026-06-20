from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Literal

from ..pacing import SessionUtterancePacing

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
class BrewLine:
    text: str
    reason: str = ""


@dataclass
class SessionRuntime:
    session_id: str
    pacing: SessionUtterancePacing = field(default_factory=SessionUtterancePacing)
    phase: SpeakPushPhase = "idle"
    active_user_text: str = ""
    partial_agent_output: str = ""
    interrupt: InterruptContext | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    typing_active: bool = False
    typing_idle: bool = True
    last_typing_at: float = 0.0
    draft_user_text: str = ""
    pending_user_text: str = ""
    pending_stream: bool = False
    pending_record: bool = True
    pending_mode: SpeakTurnMode = "inbound"
    brew_queue: list[BrewLine] = field(default_factory=list)
    director_generation: int = 0
    typing_idle_ms: int = 3000
    idle_timer: threading.Timer | None = None
    on_typing_idle: Any | None = None
    typing_idle_event: threading.Event = field(default_factory=threading.Event)
    typing_idle_handoff: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self) -> None:
        if self.typing_idle:
            self.typing_idle_event.set()
            self.typing_idle_handoff.set()

    def merge_pending_user_text(self, text: str) -> str:
        incoming = text.strip()
        if not incoming:
            return self.pending_user_text.strip()
        draft = self.draft_user_text.strip()
        parts: list[str] = []
        for piece in (self.pending_user_text.strip(), draft, incoming):
            if piece and (not parts or parts[-1] != piece):
                parts.append(piece)
        merged = "\n".join(parts).strip()
        self.pending_user_text = merged
        return merged

    def snapshot_typing(self) -> dict[str, object]:
        return {
            "typing_active": self.typing_active,
            "typing_idle": self.typing_idle,
            "draft_user_text": self.draft_user_text,
            "pending_user_text": self.pending_user_text,
            "brew_queue_depth": len(self.brew_queue),
            "typing_idle_ms": self.typing_idle_ms,
        }

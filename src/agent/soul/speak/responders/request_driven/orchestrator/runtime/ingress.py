from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

IngressEventKind = Literal["user_input", "poll_tick", "session_close", "delivery_done"]


@dataclass(frozen=True)
class IngressEvent:
    kind: IngressEventKind
    session_id: str
    user_text: str = ""
    turn_index: int = 0
    trigger: str = ""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Literal

PollTrigger = Literal["append", "idle", "interrupt"]


@dataclass
class PollCursor:
    """sqrt(2) 条件轮询游标。"""

    session_id: str
    trigger: PollTrigger = "idle"
    k: int = 0
    base_ms: int = 800
    max_ms: int = 12000
    armed: bool = False
    next_fire_at: float = 0.0
    session_opened_at: float = field(default_factory=time.monotonic)
    session_max_sec: float = 1800.0
    notes: list[str] = field(default_factory=list)

    def interval_ms(self) -> int:
        scaled = self.base_ms * (math.sqrt(2) ** self.k)
        return int(min(self.max_ms, scaled))

    def is_session_expired(self) -> bool:
        elapsed = time.monotonic() - self.session_opened_at
        return elapsed >= self.session_max_sec

    def schedule_next(self) -> None:
        delay_sec = self.interval_ms() / 1000.0
        self.next_fire_at = time.monotonic() + delay_sec
        self.k += 1

    def reset(self) -> None:
        self.k = 0
        self.armed = False
        self.next_fire_at = 0.0

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "trigger": self.trigger,
            "k": self.k,
            "interval_ms": self.interval_ms(),
            "armed": self.armed,
            "next_fire_at": self.next_fire_at,
            "session_expired": self.is_session_expired(),
            "notes": list(self.notes),
        }

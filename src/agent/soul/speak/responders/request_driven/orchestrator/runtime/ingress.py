from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

IngressEventKind = Literal["user_input", "poll_tick", "session_close", "delivery_done"]

# 用户入站只走 fast/slow；角色回复由 sync turn（origin=user）或 poll due（origin=director）
IngressPhase = Literal["", "fast", "slow"]


@dataclass(frozen=True)
class IngressEvent:
    kind: IngressEventKind
    session_id: str
    user_text: str = ""
    turn_index: int = 0
    trigger: str = ""
    # fast=首响应帧（清静默/写表）；slow=后台完整导演编排；均不催生角色回复
    phase: IngressPhase = ""

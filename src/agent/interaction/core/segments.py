from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


class InteractionDirection(str, Enum):
    """交互由谁开启（语义层，非传输层）。"""

    inbound = "inbound"
    outbound = "outbound"


@dataclass
class UserStimulus:
    """用户侧刺激：同一段 SemanticInteraction 内可有多条。"""

    text: str
    id: str = field(default_factory=_uid)
    at: str = field(default_factory=_now_iso)


@dataclass
class AgentUtterance:
    """Agent 对用户可见的表述 s1、s2… 同属一个 SemanticInteraction。"""

    text: str
    id: str = field(default_factory=_uid)
    at: str = field(default_factory=_now_iso)
    final: bool = False


@dataclass
class AgentTraceRef:
    """指向 ReAct 执行迹的引用（thought / 行为 / observation 在 react 侧展开）。"""

    step_index: int
    thought: str = ""
    action: str = ""
    observation: str = ""
    id: str = field(default_factory=_uid)
    at: str = field(default_factory=_now_iso)

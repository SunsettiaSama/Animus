from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SpeakStreamKind = Literal[
    "chunk",
    "tag",
    "thought",
    "speak",
    "action",
    "state",
    "anchor",
    "observe",
    "segment",
    "agent_typing",
    "finish",
    "error",
]


@dataclass(frozen=True)
class SpeakStreamEvent:
    """Speak 流式出站事件（kind 与输出 tag 对齐）。"""

    kind: SpeakStreamKind
    text: str
    final: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

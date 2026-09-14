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
    # 剧情卡片帧（single-stream 需求 §8）：卡片建立/进度刷新，meta 承载双段
    "story_card",
    "story_progress",
]


@dataclass(frozen=True)
class SpeakStreamEvent:
    """Speak 流式出站事件（kind 与输出 tag 对齐）。"""

    kind: SpeakStreamKind
    text: str
    final: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

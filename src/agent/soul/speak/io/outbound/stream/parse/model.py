from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .tags import SpeakTagBlock

SpeakSessionState = Literal["finish", "append", "share", "recall"]

SPEAK_CORE_PARSE_FIELDS: tuple[str, ...] = (
    "thought",
    "speak",
    "actions",
    "session_state",
    "recall_query",
)
SPEAK_OPTIONAL_PARSE_FIELDS: tuple[str, ...] = (
    "anchor_tool",
    "observe",
)
SPEAK_PARSE_FIELDS: tuple[str, ...] = (
    *SPEAK_CORE_PARSE_FIELDS,
    *SPEAK_OPTIONAL_PARSE_FIELDS,
    "blocks",
    "raw",
)


@dataclass(frozen=True)
class SpeakAgentOutput:
    """io/outbound/stream/parse：LLM 原始输出解析结果。"""

    thought: str = ""
    speak: str = ""
    actions: tuple[str, ...] = ()
    session_state: SpeakSessionState = "finish"
    recall_query: str = ""
    anchor_tool: str = ""
    observe: str = ""
    blocks: tuple[SpeakTagBlock, ...] = ()
    raw: str = ""

    @property
    def action(self) -> str:
        return self.actions[0] if self.actions else ""

    @property
    def text(self) -> str:
        return self.speak

    def to_dict(self) -> dict[str, Any]:
        return {
            "thought": self.thought,
            "speak": self.speak,
            "actions": list(self.actions),
            "session_state": self.session_state,
            "recall_query": self.recall_query,
            "anchor_tool": self.anchor_tool,
            "observe": self.observe,
            "blocks": [{"kind": block.kind, "content": block.content} for block in self.blocks],
            "raw": self.raw,
            "action": self.action,
            "text": self.text,
        }

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


class AgentOutputKind(str, Enum):
    """Agent 在一段 SemanticInteraction 内的最小输出类型。"""

    thought = "thought"
    dialogue = "dialogue"
    action = "action"


@dataclass
class AgentThought:
    """思考：内心推理、计划、权衡。

    默认不对交互对方可见；不单独构成对话拍边界。
    """

    content: str
    id: str = field(default_factory=_uid)
    at: str = field(default_factory=_now_iso)
    step_index: int = 0
    visible: bool = False


@dataclass
class AgentDialogue:
    """对话：对交互对方可见的表述（自然语言）。

    可多段 s1、s2；``final`` 标记本段是否为可见交付收束点之一。
    """

    text: str
    id: str = field(default_factory=_uid)
    at: str = field(default_factory=_now_iso)
    final: bool = False


@dataclass
class AgentAction:
    """动作：Agent 在世界上发起的操作（Tool / Skill / MCP 等均映射为此）。

    ``observation`` 为环境反馈，在 ReAct 侧 observe 后回填。
    """

    name: str
    arguments: dict = field(default_factory=dict)
    id: str = field(default_factory=_uid)
    at: str = field(default_factory=_now_iso)
    step_index: int = 0
    observation: str = ""


@dataclass
class AgentOutput:
    """Agent 最小输出单元 — 三者必居其一。"""

    kind: AgentOutputKind
    id: str = field(default_factory=_uid)
    at: str = field(default_factory=_now_iso)
    thought: AgentThought | None = None
    dialogue: AgentDialogue | None = None
    action: AgentAction | None = None

    @staticmethod
    def from_thought(item: AgentThought) -> AgentOutput:
        return AgentOutput(kind=AgentOutputKind.thought, thought=item)

    @staticmethod
    def from_dialogue(item: AgentDialogue) -> AgentOutput:
        return AgentOutput(kind=AgentOutputKind.dialogue, dialogue=item)

    @staticmethod
    def from_action(item: AgentAction) -> AgentOutput:
        return AgentOutput(kind=AgentOutputKind.action, action=item)

    def to_dict(self) -> dict:
        base = {"id": self.id, "at": self.at, "kind": self.kind.value}
        if self.thought is not None:
            base["thought"] = {
                "content": self.thought.content,
                "step_index": self.thought.step_index,
                "visible": self.thought.visible,
            }
        if self.dialogue is not None:
            base["dialogue"] = {
                "text": self.dialogue.text,
                "final": self.dialogue.final,
            }
        if self.action is not None:
            base["action"] = {
                "name": self.action.name,
                "arguments": dict(self.action.arguments),
                "step_index": self.action.step_index,
                "observation": self.action.observation,
            }
        return base

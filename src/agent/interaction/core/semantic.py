from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from .context import InteractionContext
from .expectation import Expectation
from .outputs import (
    AgentAction,
    AgentDialogue,
    AgentOutput,
    AgentOutputKind,
    AgentThought,
)
from .segments import (
    AgentTraceRef,
    AgentUtterance,
    InteractionDirection,
    UserStimulus,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


class InteractionStatus(str, Enum):
    open = "open"
    closed = "closed"


class InteractionCloseReason(str, Enum):
    """语义 Interaction 闭合原因。"""

    user_shift = "user_shift"
    agent_done = "agent_done"
    explicit_close = "explicit_close"
    continuity_break = "continuity_break"
    idle_timeout = "idle_timeout"
    superseded = "superseded"


@dataclass
class SemanticInteraction:
    """最小语义单元。

    有且仅有 **语义连续性** 界定边界。同一单元内可包含：
    - 多条用户刺激；
    - 多条 Agent 最小输出（思考 / 对话 / 动作，见 ``outputs``）；
    - 遗留 ``agent_utterances`` / ``agent_trace`` 与 ReAct 迹兼容。

    与 HTTP 一轮、ReAct 一步、单个 tool call **无固定 1:1 关系**。
    闭合后由 anchor 等下游消费（交互层不依赖 anchor）。
    """

    context: InteractionContext
    direction: InteractionDirection = InteractionDirection.inbound
    id: str = field(default_factory=_uid)
    status: InteractionStatus = InteractionStatus.open
    opened_at: str = field(default_factory=_now_iso)
    closed_at: str = ""
    close_reason: InteractionCloseReason | None = None
    user_stimuli: list[UserStimulus] = field(default_factory=list)
    agent_outputs: list[AgentOutput] = field(default_factory=list)
    agent_utterances: list[AgentUtterance] = field(default_factory=list)
    agent_trace: list[AgentTraceRef] = field(default_factory=list)
    stakes: str = ""
    last_touch_at: str = field(default_factory=_now_iso)

    @property
    def session_id(self) -> str:
        return self.context.session_id

    @property
    def expectation(self) -> Expectation:
        return self.context.expectation

    @expectation.setter
    def expectation(self, value: Expectation) -> None:
        self.context.expectation = value

    @property
    def is_open(self) -> bool:
        return self.status == InteractionStatus.open

    def touch_expectation(self, value: Expectation) -> None:
        self.context.expectation = value

    def _touch(self) -> None:
        self.last_touch_at = _now_iso()

    def last_user_text(self) -> str:
        if not self.user_stimuli:
            return ""
        return self.user_stimuli[-1].text

    def last_agent_text(self) -> str:
        for out in reversed(self.agent_outputs):
            if out.kind == AgentOutputKind.dialogue and out.dialogue is not None:
                return out.dialogue.text
        if not self.agent_utterances:
            return ""
        return self.agent_utterances[-1].text

    def outputs_of(self, kind: AgentOutputKind) -> list[AgentOutput]:
        return [o for o in self.agent_outputs if o.kind == kind]

    def continuity_digest(self, *, max_chars: int = 600) -> str:
        """供 LLM / 日志使用的紧凑语义摘要。"""
        parts: list[str] = []
        if self.stakes:
            parts.append(f"[stakes] {self.stakes[:120]}")
        if self.user_stimuli:
            parts.append(f"[user] {self.last_user_text()[:200]}")
        if self.outputs_of(AgentOutputKind.dialogue):
            parts.append(f"[dialogue] {self.last_agent_text()[:200]}")
        elif self.agent_utterances:
            parts.append(f"[agent] {self.last_agent_text()[:200]}")
        last_action = self.outputs_of(AgentOutputKind.action)
        if last_action and last_action[-1].action is not None:
            act = last_action[-1].action
            parts.append(f"[行为] {act.name[:80]}")
        if self.agent_trace:
            t = self.agent_trace[-1]
            if t.thought:
                parts.append(f"[thought] {t.thought[:120]}")
            if t.action:
                parts.append(f"[action] {t.action[:80]}")
        parts.append(f"[expectation] {self.expectation.value}")
        text = " | ".join(parts)
        if len(text) > max_chars:
            return text[: max_chars - 3] + "..."
        return text

    def append_user(self, text: str) -> UserStimulus:
        item = UserStimulus(text=text)
        self.user_stimuli.append(item)
        self._touch()
        return item

    def append_thought(
        self,
        content: str,
        *,
        step_index: int = 0,
        visible: bool = False,
    ) -> AgentThought:
        item = AgentThought(
            content=content,
            step_index=step_index,
            visible=visible,
        )
        self.agent_outputs.append(AgentOutput.from_thought(item))
        self._touch()
        return item

    def append_dialogue(self, text: str, *, final: bool = False) -> AgentDialogue:
        item = AgentDialogue(text=text, final=final)
        self.agent_outputs.append(AgentOutput.from_dialogue(item))
        self.agent_utterances.append(
            AgentUtterance(text=text, final=final, id=item.id, at=item.at)
        )
        self._touch()
        return item

    def append_action(
        self,
        name: str,
        *,
        arguments: dict | None = None,
        step_index: int = 0,
        observation: str = "",
    ) -> AgentAction:
        item = AgentAction(
            name=name,
            arguments=dict(arguments or {}),
            step_index=step_index,
            observation=observation,
        )
        self.agent_outputs.append(AgentOutput.from_action(item))
        self._touch()
        return item

    def append_utterance(self, text: str, *, final: bool = False) -> AgentUtterance:
        item = self.append_dialogue(text, final=final)
        return AgentUtterance(text=item.text, final=item.final, id=item.id, at=item.at)

    def append_trace(
        self,
        step_index: int,
        *,
        thought: str = "",
        action: str = "",
        observation: str = "",
    ) -> AgentTraceRef:
        item = AgentTraceRef(
            step_index=step_index,
            thought=thought,
            action=action,
            observation=observation,
        )
        self.agent_trace.append(item)
        self._touch()
        return item

    def close(self, reason: InteractionCloseReason) -> None:
        self.status = InteractionStatus.closed
        self.close_reason = reason
        self.closed_at = _now_iso()
        self.context.expectation = Expectation.none

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "direction": self.direction.value,
            "status": self.status.value,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
            "close_reason": self.close_reason.value if self.close_reason else "",
            "expectation": self.expectation.value,
            "in_scene": self.context.in_scene,
            "stakes": self.stakes,
            "user_stimuli": [
                {"id": u.id, "at": u.at, "text": u.text} for u in self.user_stimuli
            ],
            "agent_outputs": [o.to_dict() for o in self.agent_outputs],
            "agent_utterances": [
                {
                    "id": a.id,
                    "at": a.at,
                    "text": a.text,
                    "final": a.final,
                }
                for a in self.agent_utterances
            ],
            "agent_trace": [
                {
                    "id": t.id,
                    "at": t.at,
                    "step_index": t.step_index,
                    "thought": t.thought,
                    "action": t.action,
                    "observation": t.observation,
                }
                for t in self.agent_trace
            ],
        }
